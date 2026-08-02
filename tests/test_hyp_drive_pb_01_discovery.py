from __future__ import annotations

import csv
import hashlib
import inspect
import json
import subprocess
import tempfile
import unittest
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import yaml

import src.research.hyp_drive_pb_01_discovery as discovery
from src.data.sessions import EquitySessionCalendar
from src.research.hyp_drive_pb_01 import (
    Direction,
    canonical_payload,
    canonical_payload_hash,
    load_config_yaml,
)


ROOT = Path(__file__).resolve().parents[1]
CONFIG = load_config_yaml(ROOT / discovery.CONFIG_PATH)
CALENDAR = EquitySessionCalendar.us_equity()
HEAD = "f" * 40
REAL_EXECUTION_PROGRESS = discovery.ExecutionProgress


def session_dates(count: int, start: date = date(2024, 1, 2)) -> list[date]:
    values: list[date] = []
    current = start
    while len(values) < count:
        if CALENDAR.is_session_day(current):
            values.append(current)
        current += timedelta(days=1)
    return values


def set_block(
    frame: pd.DataFrame,
    session_date: date,
    clock: str,
    *,
    open_: float,
    high: float,
    low: float,
    close: float,
) -> None:
    local = pd.to_datetime(frame["timestamp"], utc=True).dt.tz_convert(
        CALENDAR.timezone
    )
    start = pd.Timestamp(f"{session_date} {clock}", tz=CALENDAR.timezone)
    mask = (local >= start) & (local < start + pd.Timedelta(5, unit="min"))
    indices = frame.index[mask]
    frame.loc[indices, ["open", "high", "low", "close"]] = [
        open_,
        high,
        low,
        close,
    ]
    frame.loc[indices[0], "open"] = open_
    frame.loc[indices[-1], "close"] = close


def synthetic_minutes(symbol: str, direction: Direction) -> pd.DataFrame:
    rows: list[dict] = []
    days = session_dates(22)
    for session_date in days:
        for timestamp in CALENDAR.expected_timestamps(
            session_date, session_date, "1min"
        ):
            rows.append(
                {
                    "timestamp": timestamp,
                    "open": 100.0,
                    "high": 101.0,
                    "low": 99.0,
                    "close": 100.0,
                    "volume": 100.0,
                    "symbol": symbol,
                }
            )
    frame = pd.DataFrame(rows)
    event_date = days[-1]
    if direction is Direction.LONG:
        set_block(frame, event_date, "09:30", open_=100, high=104, low=99.5, close=103)
        set_block(frame, event_date, "09:35", open_=103, high=108, low=102, close=107)
        set_block(frame, event_date, "09:40", open_=107, high=111, low=106, close=110)
        set_block(frame, event_date, "09:45", open_=110, high=110.5, low=109.99, close=110.2)
        set_block(frame, event_date, "09:50", open_=110.2, high=110.9, low=110, close=110.7)
        prices = (("10:00", 111), ("10:15", 112), ("10:30", 113), ("11:00", 114), ("15:55", 115))
        high_delta, low_delta, close_delta = 0.5, -0.2, 0.2
    else:
        set_block(frame, event_date, "09:30", open_=100, high=100.5, low=96, close=97)
        set_block(frame, event_date, "09:35", open_=97, high=98, low=92, close=93)
        set_block(frame, event_date, "09:40", open_=93, high=94, low=89, close=90)
        set_block(frame, event_date, "09:45", open_=90, high=90.01, low=89.5, close=89.8)
        set_block(frame, event_date, "09:50", open_=89.8, high=90, low=89.1, close=89.3)
        prices = (("10:00", 89), ("10:15", 88), ("10:30", 87), ("11:00", 86), ("15:55", 85))
        high_delta, low_delta, close_delta = 0.2, -0.5, -0.2
    for clock, price in prices:
        set_block(
            frame,
            event_date,
            clock,
            open_=price,
            high=price + high_delta,
            low=price + low_delta,
            close=price + close_delta,
        )
    return frame


def prepared_symbol(symbol: str, direction: Direction):
    minute = discovery.validate_minute_frame(
        synthetic_minutes(symbol, direction), symbol, CALENDAR
    )
    sessions = discovery.build_daily_approved_sessions(minute, (), CALENDAR)
    five = discovery.resample_rth_1min_to_5min(
        discovery.crop_discovery_period(minute)
    )
    events, exclusions, objects = discovery.detect_confirmed_events(
        symbol, minute, five, sessions, CONFIG
    )
    return minute, five, sessions, events, exclusions, objects


def valid_manifest_payload(
    symbol: str,
    dataset_path: Path,
    digest: str,
    *,
    exclusions: list[dict] | None = None,
) -> dict:
    excluded = list(exclusions or [])
    return {
        "symbol": symbol,
        "asset_class": "equity",
        "timeframe": "1min",
        "provider": "alpaca",
        "feed": "sip",
        "adjustment": "all",
        "source_timezone": "America/New_York",
        "rth_only": True,
        "start": discovery.DISCOVERY_START,
        "end": "2026-07-06",
        "rows": 1,
        "first_timestamp": "2022-01-03T14:30:00Z",
        "last_timestamp": "2026-07-06T19:59:00Z",
        "input_file": str(dataset_path),
        "sha256": digest,
        "calendar_source": "builtin_us_equity_calendar_v1",
        "calendar_loaded": True,
        "calendar_holidays_loaded": 1,
        "calendar_early_closes_loaded": 1,
        "audit_apt_for_or_fvg_backtest": True,
        "audit_critical_warnings": [],
        "audit_warnings": [],
        "output_file": str(dataset_path),
        "raw_input_file": None,
        "curated_file": str(dataset_path),
        "rows_input": 1,
        "rows_output": 1,
        "rows_removed": 0,
        "total_excluded_sessions": len(excluded),
        "excluded_sessions": excluded,
        "dataset_status": "approved_for_or_fvg_backtest",
        "created_at": "2026-07-29T00:00:00Z",
        "broker_connected": False,
        "orders_sent": False,
        "live_trading_enabled": False,
        "paper_broker_enabled": False,
    }


def make_contract(
    root: Path,
    symbol: str,
    *,
    exclusions: list[dict] | None = None,
) -> discovery.ManifestContract:
    dataset = root / f"{symbol}.csv"
    dataset.write_bytes(f"synthetic-{symbol}".encode())
    digest = hashlib.sha256(dataset.read_bytes()).hexdigest()
    manifest = root / f"{symbol}.json"
    manifest.write_text(
        json.dumps(
            valid_manifest_payload(
                symbol, dataset, digest, exclusions=exclusions
            )
        ),
        encoding="utf-8",
    )
    return discovery.validate_manifest_contract(symbol, dataset, manifest)


def request() -> discovery.DiscoveryRequest:
    return discovery.DiscoveryRequest(
        mode="run_discovery",
        expected_preregistration_commit=discovery.PREREGISTRATION_FREEZE_COMMIT,
        expected_execution_freeze_commit=HEAD,
        expected_canonical_hash=discovery.EXPECTED_CANONICAL_HASH,
    )


def good_reports():
    causal = discovery.CausalIntegrityReport(
        True, True, True, True, True, True, True, 0, 0, 0
    )
    temporal = discovery.TemporalAccessReport(
        discovery.DISCOVERY_START,
        discovery.DISCOVERY_END,
        "2022-01-03T14:30:00+00:00",
        "2024-12-31T20:59:00+00:00",
        0,
    )
    return causal, temporal


def synthetic_gate_metrics(rows: int = 150) -> pd.DataFrame:
    records = []
    for index in range(rows):
        year = 2022 + index % 3
        records.append(
            {
                "event_id": f"E{index}",
                "symbol": discovery.SYMBOLS[index % 2],
                "session_date": date(year, 1 + (index // 28) % 12, 1 + index % 28),
                "direction": (
                    Direction.LONG.value
                    if index % 2 == 0
                    else Direction.SHORT.value
                ),
                "horizon": "30min",
                "horizon_available": True,
                "path_complete": True,
                "event_return": 0.02,
                "unconditional_return": 0.005,
                "incremental_return": 0.015,
                "baseline_round_trip_cost": 0.0004,
                "stress_round_trip_cost": 0.0008,
                "net_return_baseline": 0.0196,
                "net_return_stress": 0.0192,
                "MFE": 0.025,
                "MAE": -0.005,
            }
        )
    return pd.DataFrame(records)


class GovernanceApiTests(unittest.TestCase):
    def test_public_runner_signature_is_closed(self) -> None:
        self.assertEqual(
            tuple(inspect.signature(discovery.run_discovery).parameters),
            ("request",),
        )
        for name in (
            "runtime_state",
            "manifest_loader",
            "dataset_loader",
            "verify_dataset_hashes",
            "synthetic_config",
            "output_dir",
        ):
            with self.assertRaises(TypeError, msg=name):
                discovery.run_discovery(request(), **{name: object()})

    def test_cli_has_no_output_or_bypass_flags(self) -> None:
        parser = discovery.build_parser()
        destinations = {action.dest for action in parser._actions}
        self.assertNotIn("output_dir", destinations)
        self.assertNotIn("verify_dataset_hashes", destinations)
        with self.assertRaises(SystemExit):
            parser.parse_args(["--mode", "run_discovery", "--output-dir", "x"])

    def test_run_discovery_always_enters_preflight(self) -> None:
        with patch.object(
            discovery,
            "validate_discovery_preflight",
            side_effect=RuntimeError("preflight-called"),
        ) as preflight:
            with self.assertRaisesRegex(RuntimeError, "preflight-called"):
                discovery.run_discovery(request())
        preflight.assert_called_once_with(request())

    def test_validate_implementation_uses_canonical_10000(self) -> None:
        payload = discovery.validate_implementation()
        self.assertTrue(payload["implementation_valid"])
        self.assertEqual(CONFIG.bootstrap_resamples, 10_000)


class GitPreflightTests(unittest.TestCase):
    def fake_git(self, status: str = "", *, exists: int = 0, ancestor: int = 0):
        def run(args, **kwargs):
            command = tuple(args[1:])
            if command == ("rev-parse", "--verify", "HEAD"):
                return subprocess.CompletedProcess(args, 0, HEAD + "\n", "")
            if command == ("status", "--porcelain=v1", "--untracked-files=all"):
                return subprocess.CompletedProcess(args, 0, status, "")
            if command[0:2] == ("cat-file", "-e"):
                return subprocess.CompletedProcess(args, exists, "", "")
            if command[0:2] == ("merge-base", "--is-ancestor"):
                return subprocess.CompletedProcess(args, ancestor, "", "")
            raise AssertionError(command)

        return run

    def test_clean_real_git_state(self) -> None:
        with patch.object(subprocess, "run", side_effect=self.fake_git()):
            state = discovery.collect_runtime_state()
        self.assertTrue(state.working_tree_clean)
        self.assertTrue(state.preregistration_commit_exists)
        self.assertTrue(state.preregistration_is_ancestor)

    def test_staged_unstaged_untracked_and_line_endings_are_dirty(self) -> None:
        for status in ("M  staged.py\n", " M unstaged.py\n", "?? new.py\n", " M crlf.py\r\n"):
            with self.subTest(status=status):
                with patch.object(subprocess, "run", side_effect=self.fake_git(status)):
                    self.assertFalse(discovery.collect_runtime_state().working_tree_clean)

    def test_missing_commit_and_nonancestor(self) -> None:
        with patch.object(
            subprocess, "run", side_effect=self.fake_git(exists=1)
        ):
            state = discovery.collect_runtime_state()
            self.assertFalse(state.preregistration_commit_exists)
            self.assertFalse(state.preregistration_is_ancestor)
        with patch.object(
            subprocess, "run", side_effect=self.fake_git(ancestor=1)
        ):
            self.assertFalse(
                discovery.collect_runtime_state().preregistration_is_ancestor
            )

    def test_git_error_and_invalid_output_fail(self) -> None:
        with patch.object(
            subprocess, "run", side_effect=subprocess.CalledProcessError(2, "git")
        ):
            with self.assertRaises(subprocess.CalledProcessError):
                discovery.collect_runtime_state()
        broken = self.fake_git()

        def invalid(args, **kwargs):
            result = broken(args, **kwargs)
            if tuple(args[1:]) == ("rev-parse", "--verify", "HEAD"):
                result.stdout = "short\n"
            return result

        with patch.object(subprocess, "run", side_effect=invalid):
            with self.assertRaisesRegex(RuntimeError, "invalid full HEAD"):
                discovery.collect_runtime_state()

    def test_preflight_rejects_expected_sha_before_manifests(self) -> None:
        bad = replace(
            request(), expected_preregistration_commit="0" * 40
        )
        with patch.object(discovery, "validate_manifest_contract") as validator:
            with self.assertRaises(PermissionError):
                discovery.validate_discovery_preflight(bad)
        validator.assert_not_called()

    def test_preflight_rejects_runtime_failures(self) -> None:
        states = (
            discovery.RuntimeState(HEAD, False, True, True, "?? x"),
            discovery.RuntimeState(HEAD, True, False, False, ""),
            discovery.RuntimeState(HEAD, True, True, False, ""),
            discovery.RuntimeState("e" * 40, True, True, True, ""),
        )
        for state in states:
            with self.subTest(state=state):
                with patch.object(discovery, "collect_runtime_state", return_value=state):
                    with self.assertRaises(PermissionError):
                        discovery.validate_discovery_preflight(request())


class ManifestContractTests(unittest.TestCase):
    def test_valid_official_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            contract = make_contract(Path(temporary), "QQQ")
            self.assertEqual(contract.manifest.symbol, "QQQ")
            self.assertEqual(contract.manifest.feed, "sip")

    def mutate_and_reject(self, mutation) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dataset = root / "QQQ.csv"
            dataset.write_bytes(b"dataset")
            digest = hashlib.sha256(dataset.read_bytes()).hexdigest()
            payload = valid_manifest_payload("QQQ", dataset, digest)
            mutation(payload, dataset)
            manifest = root / "QQQ.json"
            manifest.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(Exception):
                discovery.validate_manifest_contract("QQQ", dataset, manifest)

    def test_rejects_critical_warning_calendar_status_and_audit(self) -> None:
        mutations = (
            lambda p, _: p.update(audit_critical_warnings=["critical"]),
            lambda p, _: p.update(calendar_source="wrong"),
            lambda p, _: p.update(dataset_status="not_audited"),
            lambda p, _: p.update(audit_apt_for_or_fvg_backtest=False),
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                self.mutate_and_reject(mutation)

    def test_rejects_missing_or_inconsistent_exclusions(self) -> None:
        self.mutate_and_reject(lambda p, _: p.pop("excluded_sessions"))
        self.mutate_and_reject(lambda p, _: p.update(total_excluded_sessions=1))

    def test_rejects_symbol_timeframe_source_and_asset(self) -> None:
        mutations = (
            lambda p, _: p.update(symbol="SPY"),
            lambda p, _: p.update(timeframe="5min"),
            lambda p, _: p.update(provider="other"),
            lambda p, _: p.update(feed="iex"),
            lambda p, _: p.update(asset_class="crypto"),
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                self.mutate_and_reject(mutation)

    def test_rejects_curated_file_hash_missing_file_and_live(self) -> None:
        self.mutate_and_reject(
            lambda p, d: p.update(curated_file=str(d.with_name("other.csv")))
        )
        self.mutate_and_reject(lambda p, _: p.update(sha256="0" * 64))
        self.mutate_and_reject(lambda p, _: p.update(live_trading_enabled=True))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaises(FileNotFoundError):
                discovery.validate_manifest_contract(
                    "QQQ", root / "missing.csv", root / "missing.json"
                )


class DataContractTests(unittest.TestCase):
    def valid_frame(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "timestamp": [pd.Timestamp("2024-01-02 09:30", tz=CALENDAR.timezone)],
                "open": [100.0],
                "high": [101.0],
                "low": [99.0],
                "close": [100.0],
                "volume": [100.0],
                "symbol": ["QQQ"],
            }
        )

    def test_valid_and_manifest_bound_symbol(self) -> None:
        frame = self.valid_frame()
        self.assertEqual(
            discovery.validate_minute_frame(frame, "QQQ").iloc[0]["symbol"],
            "QQQ",
        )
        self.assertIn(
            "symbol",
            discovery.validate_minute_frame(frame.drop(columns="symbol"), "QQQ"),
        )

    def test_rejects_nonpositive_prices_negative_volume_and_nonfinite(self) -> None:
        for column, value in (
            ("open", 0.0),
            ("close", -1.0),
            ("volume", -1.0),
            ("high", np.inf),
            ("low", np.nan),
        ):
            with self.subTest(column=column, value=value):
                frame = self.valid_frame()
                frame.loc[0, column] = value
                with self.assertRaises(ValueError):
                    discovery.validate_minute_frame(frame, "QQQ")

    def test_rejects_naive_out_of_order_duplicates_and_bad_ohlc(self) -> None:
        naive = self.valid_frame()
        naive["timestamp"] = naive["timestamp"].dt.tz_localize(None)
        with self.assertRaises(ValueError):
            discovery.validate_minute_frame(naive, "QQQ")
        ordered = pd.concat(
            [
                self.valid_frame().assign(
                    timestamp=pd.Timestamp("2024-01-02 09:31", tz=CALENDAR.timezone)
                ),
                self.valid_frame(),
            ],
            ignore_index=True,
        )
        with self.assertRaises(ValueError):
            discovery.validate_minute_frame(ordered, "QQQ")
        duplicate = pd.concat([self.valid_frame(), self.valid_frame()], ignore_index=True)
        with self.assertRaises(ValueError):
            discovery.validate_minute_frame(duplicate, "QQQ")
        bad = self.valid_frame()
        bad.loc[0, "high"] = 98
        with self.assertRaises(ValueError):
            discovery.validate_minute_frame(bad, "QQQ")

    def test_rejects_outside_rth_wrong_symbol_and_subminute(self) -> None:
        outside = self.valid_frame()
        outside.loc[0, "timestamp"] = pd.Timestamp(
            "2024-01-02 08:00", tz=CALENDAR.timezone
        )
        with self.assertRaises(ValueError):
            discovery.validate_minute_frame(outside, "QQQ")
        wrong = self.valid_frame()
        wrong["symbol"] = "SPY"
        with self.assertRaises(ValueError):
            discovery.validate_minute_frame(wrong, "QQQ")
        subminute = self.valid_frame()
        subminute.loc[0, "timestamp"] += pd.Timedelta(30, unit="s")
        with self.assertRaises(ValueError):
            discovery.validate_minute_frame(subminute, "QQQ")

    def test_early_close_is_calendar_aware(self) -> None:
        frame = self.valid_frame()
        frame.loc[0, "timestamp"] = pd.Timestamp(
            "2024-11-29 12:59", tz=CALENDAR.timezone
        )
        discovery.validate_minute_frame(frame, "QQQ")
        frame.loc[0, "timestamp"] = pd.Timestamp(
            "2024-11-29 13:00", tz=CALENDAR.timezone
        )
        with self.assertRaises(ValueError):
            discovery.validate_minute_frame(frame, "QQQ")


class TemporalAndSessionTests(unittest.TestCase):
    def test_bounded_csv_materializes_no_2025_or_2026(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "mixed.csv"
            with path.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(
                    stream, fieldnames=(*discovery.MINUTE_COLUMNS, "symbol")
                )
                writer.writeheader()
                for year in (2024, 2025, 2026):
                    writer.writerow(
                        {
                            "timestamp": f"{year}-01-02T14:30:00Z",
                            "open": 100,
                            "high": 101,
                            "low": 99,
                            "close": 100,
                            "volume": 1,
                            "symbol": "QQQ",
                        }
                    )
            frame, report = discovery.load_bounded_dataset(path)
        self.assertEqual(len(frame), 1)
        self.assertTrue(frame.iloc[0]["timestamp"].startswith("2024"))
        self.assertTrue(report.contamination_absent)
        self.assertEqual(report.historical_2025_rows_materialized, 0)
        self.assertEqual(report.historical_2026_rows_materialized, 0)

    def test_future_materialization_derives_contamination_false(self) -> None:
        report = discovery.TemporalAccessReport(
            discovery.DISCOVERY_START,
            discovery.DISCOVERY_END,
            None,
            None,
            1,
            historical_2025_rows_materialized=1,
        )
        self.assertFalse(report.contamination_absent)

    def test_complete_missing_and_excluded_sessions(self) -> None:
        minute = discovery.validate_minute_frame(
            synthetic_minutes("QQQ", Direction.LONG), "QQQ", CALENDAR
        )
        complete = discovery.build_daily_approved_sessions(minute, (), CALENDAR)
        event_date = session_dates(22)[-1]
        self.assertIn(event_date, complete.approved_session_dates)
        local = minute["timestamp"].dt.tz_convert(CALENDAR.timezone)
        missing = minute.drop(
            minute[(local.dt.date == event_date)].index[-1]
        ).reset_index(drop=True)
        incomplete = discovery.build_daily_approved_sessions(missing, (), CALENDAR)
        self.assertIn(event_date, incomplete.incomplete_session_dates)
        self.assertNotIn(event_date, incomplete.approved_session_dates)
        excluded = discovery.build_daily_approved_sessions(
            minute, (event_date,), CALENDAR
        )
        self.assertNotIn(event_date, excluded.approved_session_dates)

    def test_early_close_complete_and_regular_grid_fails(self) -> None:
        early = date(2024, 11, 29)
        expected = CALENDAR.expected_timestamps(early, early, "1min")
        rows = pd.DataFrame(
            {
                "timestamp": expected,
                "open": 100,
                "high": 101,
                "low": 99,
                "close": 100,
                "volume": 1,
                "symbol": "QQQ",
            }
        )
        valid = discovery.validate_minute_frame(rows, "QQQ", CALENDAR)
        sessions = discovery.build_daily_approved_sessions(valid, (), CALENDAR)
        self.assertIn(early, sessions.approved_session_dates)
        extra = pd.concat(
            [
                rows,
                rows.iloc[[0]].assign(
                    timestamp=pd.Timestamp("2024-11-29 13:00", tz=CALENDAR.timezone)
                ),
            ],
            ignore_index=True,
        )
        with self.assertRaises(ValueError):
            discovery.validate_minute_frame(extra, "QQQ", CALENDAR)

    def test_incomplete_or_manifest_excluded_date_never_generates_event(self) -> None:
        minute, five, sessions, events, _, _ = prepared_symbol(
            "QQQ", Direction.LONG
        )
        event_date = events.iloc[0]["session_date"]
        excluded_sessions = discovery.build_daily_approved_sessions(
            minute, (event_date,), CALENDAR
        )
        excluded_events, exclusions, _ = discovery.detect_confirmed_events(
            "QQQ", minute, five, excluded_sessions, CONFIG
        )
        self.assertTrue(excluded_events.empty)
        self.assertIn(
            "EXCLUDED_SESSION_NOT_APPROVED", set(exclusions["exclusion_reason"])
        )
        local = minute["timestamp"].dt.tz_convert(CALENDAR.timezone)
        incomplete_minute = minute[
            ~((local.dt.date == event_date) & (local.dt.strftime("%H:%M") == "11:00"))
        ].reset_index(drop=True)
        incomplete_sessions = discovery.build_daily_approved_sessions(
            incomplete_minute, (), CALENDAR
        )
        incomplete_five = discovery.resample_rth_1min_to_5min(incomplete_minute)
        incomplete_events, exclusions, _ = discovery.detect_confirmed_events(
            "QQQ",
            incomplete_minute,
            incomplete_five,
            incomplete_sessions,
            CONFIG,
        )
        self.assertTrue(incomplete_events.empty)
        self.assertIn(
            "EXCLUDED_INCOMPLETE_INTRADAY_DATA",
            set(exclusions["exclusion_reason"]),
        )
        no_group_five = incomplete_five[
            incomplete_five["session_date"] != event_date
        ]
        no_group_events, no_group_exclusions, _ = (
            discovery.detect_confirmed_events(
                "QQQ",
                incomplete_minute,
                no_group_five,
                incomplete_sessions,
                CONFIG,
            )
        )
        self.assertTrue(no_group_events.empty)
        audited = no_group_exclusions[
            no_group_exclusions["session_date"] == event_date
        ]
        self.assertEqual(
            audited.iloc[0]["exclusion_reason"],
            "EXCLUDED_INCOMPLETE_INTRADAY_DATA",
        )


class EventPathAndDescriptiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qqq = prepared_symbol("QQQ", Direction.LONG)
        cls.spy = prepared_symbol("SPY", Direction.SHORT)

    def test_resample_and_long_short_events_are_causal(self) -> None:
        for prepared, direction in (
            (self.qqq, Direction.LONG),
            (self.spy, Direction.SHORT),
        ):
            five, events = prepared[1], prepared[3]
            self.assertEqual(len(events), 1)
            self.assertEqual(events.iloc[0]["direction_orientation"], direction.value)
            labels = five[five["session_date"] == events.iloc[0]["session_date"]][
                "timestamp"
            ].dt.tz_convert(CALENDAR.timezone).dt.strftime("%H:%M")
            self.assertEqual(labels.iloc[0], "09:30")
            self.assertEqual(labels.iloc[-1], "15:55")

    def test_atr_rvol_and_vwap_are_correct_and_descriptive(self) -> None:
        minute, _, _, events, _, _ = self.qqq
        event = events.iloc[0]
        self.assertAlmostEqual(float(event["atr20"]), 2.0)
        self.assertAlmostEqual(float(event["rvol_descriptive"]), 1.0)
        causal = minute[minute["timestamp"] < event["confirmation_timestamp"]]
        causal = causal[
            causal["timestamp"].dt.tz_convert(CALENDAR.timezone).dt.date
            == event["session_date"]
        ]
        typical = (causal["high"] + causal["low"] + causal["close"]) / 3
        expected = float((typical * causal["volume"]).sum() / causal["volume"].sum())
        self.assertAlmostEqual(float(event["vwap_descriptive"]), expected)

    def test_future_minutes_do_not_change_vwap(self) -> None:
        minute, five, sessions, events, _, _ = self.qqq
        changed = minute.copy()
        changed.loc[
            changed["timestamp"] > events.iloc[0]["confirmation_timestamp"],
            ["open", "high", "low", "close"],
        ] *= 2
        changed_events, _, _ = discovery.detect_confirmed_events(
            "QQQ", changed, five, sessions, CONFIG
        )
        self.assertAlmostEqual(
            changed_events.iloc[0]["vwap_descriptive"],
            events.iloc[0]["vwap_descriptive"],
        )

    def test_all_horizons_complete_and_internal_gap_unavailable(self) -> None:
        _, five, _, events, _, objects = self.qqq
        paths = discovery.compute_path_metrics(
            events, objects, five, CONFIG, CALENDAR
        )
        self.assertEqual(set(paths["horizon"]), set(discovery.HORIZONS))
        self.assertTrue(paths["horizon_available"].all())
        target = events.iloc[0]["executable_timestamp"] + pd.Timedelta(10, unit="min")
        missing = five[five["timestamp"] != target]
        missing_paths = discovery.compute_path_metrics(
            events, objects, missing, CONFIG, CALENDAR
        )
        row = missing_paths[missing_paths["horizon"] == "30min"].iloc[0]
        self.assertFalse(row["horizon_available"])
        self.assertTrue(pd.isna(row["MFE"]))
        self.assertTrue(pd.isna(row["MAE"]))

    def test_missing_target_and_session_close_gap_are_unavailable(self) -> None:
        _, five, _, events, _, objects = self.qqq
        target = events.iloc[0]["executable_timestamp"] + pd.Timedelta(30, unit="min")
        missing_target = five[five["timestamp"] != target]
        paths = discovery.compute_path_metrics(
            events, objects, missing_target, CONFIG, CALENDAR
        )
        self.assertFalse(
            paths.loc[paths["horizon"] == "30min", "horizon_available"].iloc[0]
        )
        close_gap = five[five["timestamp"] != five.iloc[-2]["timestamp"]]
        paths = discovery.compute_path_metrics(
            events, objects, close_gap, CONFIG, CALENDAR
        )
        self.assertFalse(
            paths.loc[
                paths["horizon"] == "session_close", "horizon_available"
            ].iloc[0]
        )


class ControlAndIntegrityTests(unittest.TestCase):
    def control_fixture(self, direction: Direction, future: float):
        rows = []
        for day in (date(2024, 1, 2), date(2024, 1, 3)):
            for minute in range(0, 31, 5):
                clock = f"10:{minute:02d}"
                price = future if minute == 30 else 100.0
                rows.append(
                    {
                        "timestamp": pd.Timestamp(
                            f"{day} {clock}", tz=CALENDAR.timezone
                        ),
                        "open": price,
                        "high": price,
                        "low": price,
                        "close": price,
                        "volume": 1,
                        "session_date": day,
                        "complete": True,
                    }
                )
        five = pd.DataFrame(rows)
        event = pd.DataFrame(
            [
                {
                    "event_id": "E",
                    "symbol": "SPY",
                    "session_date": date(2024, 1, 3),
                    "direction": direction.value,
                    "executable_timestamp": pd.Timestamp(
                        "2024-01-03 10:00", tz=CALENDAR.timezone
                    ),
                    "horizon": "30min",
                    "event_return": 0.0,
                }
            ]
        )
        candidates = discovery.build_unconditional_candidates(
            event,
            {"SPY": five},
            {"SPY": frozenset({date(2024, 1, 2), date(2024, 1, 3)})},
            CALENDAR,
        )
        attached, _ = discovery.attach_unconditional_control(
            event, candidates, CONFIG
        )
        return candidates, attached

    def test_short_control_exact_geometry(self) -> None:
        _, rising = self.control_fixture(Direction.SHORT, 110.0)
        _, falling = self.control_fixture(Direction.SHORT, 90.0)
        self.assertAlmostEqual(rising.iloc[0]["unconditional_return"], 100 / 110 - 1)
        self.assertAlmostEqual(falling.iloc[0]["unconditional_return"], 100 / 90 - 1)

    def test_long_control_and_excluded_session(self) -> None:
        candidates, attached = self.control_fixture(Direction.LONG, 110.0)
        self.assertAlmostEqual(attached.iloc[0]["unconditional_return"], 0.10)
        filtered = discovery.build_unconditional_candidates(
            pd.DataFrame(
                [
                    {
                        "symbol": "SPY",
                        "direction": Direction.LONG.value,
                        "executable_timestamp": pd.Timestamp(
                            "2024-01-03 10:00", tz=CALENDAR.timezone
                        ),
                        "horizon": "30min",
                    }
                ]
            ),
            {"SPY": candidates.assign(
                open=100, high=100, low=100, close=100, volume=1, complete=True
            )},
            {"SPY": frozenset()},
            CALENDAR,
        )
        self.assertTrue(filtered.empty)

    def test_integrity_reports_are_derived_and_false_blocks_gate(self) -> None:
        good, temporal = good_reports()
        self.assertTrue(good.causal_integrity_passed)
        bad = replace(good, accepted_incomplete_sessions=1)
        self.assertFalse(bad.causal_integrity_passed)
        config = replace(CONFIG, bootstrap_resamples=40)
        passed = discovery.aggregate_and_gate(
            synthetic_gate_metrics(), config, good, temporal
        )["gate"]
        blocked = discovery.aggregate_and_gate(
            synthetic_gate_metrics(),
            config,
            bad,
            replace(temporal, historical_2025_rows_materialized=1),
        )["gate"]
        self.assertTrue(passed["passed"])
        self.assertFalse(blocked["passed"])
        self.assertFalse(blocked["validation_2025_unlocked"])

    def test_lookahead_counter_is_derived_from_event_timestamps(self) -> None:
        qqq = prepared_symbol("QQQ", Direction.LONG)
        spy = prepared_symbol("SPY", Direction.SHORT)
        events = pd.concat([qqq[3], spy[3]], ignore_index=True)
        paths = pd.concat(
            [
                discovery.compute_path_metrics(
                    prepared[3], prepared[5], prepared[1], CONFIG, CALENDAR
                )
                for prepared in (qqq, spy)
            ],
            ignore_index=True,
        )
        candidates = discovery.build_unconditional_candidates(
            paths,
            {"QQQ": qqq[1], "SPY": spy[1]},
            {
                "QQQ": qqq[2].approved_session_dates,
                "SPY": spy[2].approved_session_dates,
            },
            CALENDAR,
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            contracts = {
                symbol: replace(
                    make_contract(root, symbol),
                    dataset_path=discovery.DEFAULT_DATASET_PATHS[symbol],
                    manifest_path=discovery.DEFAULT_MANIFEST_PATHS[symbol],
                )
                for symbol in discovery.SYMBOLS
            }
        good = discovery.derive_causal_integrity_report(
            contracts,
            {"QQQ": qqq[0], "SPY": spy[0]},
            {"QQQ": qqq[2], "SPY": spy[2]},
            {"QQQ": qqq[1], "SPY": spy[1]},
            events,
            paths,
            candidates,
        )
        self.assertTrue(good.causal_integrity_passed)
        invalid = events.copy()
        invalid.loc[0, "executable_timestamp"] = (
            invalid.loc[0, "confirmation_timestamp"] + pd.Timedelta(10, unit="min")
        )
        bad = discovery.derive_causal_integrity_report(
            contracts,
            {"QQQ": qqq[0], "SPY": spy[0]},
            {"QQQ": qqq[2], "SPY": spy[2]},
            {"QQQ": qqq[1], "SPY": spy[1]},
            invalid,
            paths,
            candidates,
        )
        self.assertEqual(bad.lookahead_violations, 1)
        self.assertFalse(bad.causal_integrity_passed)


class AggregationBootstrapProgressTests(unittest.TestCase):
    def test_complete_aggregation_contract_and_primary_gate(self) -> None:
        causal, temporal = good_reports()
        config = replace(CONFIG, bootstrap_resamples=40)
        result = discovery.aggregate_and_gate(
            synthetic_gate_metrics(), config, causal, temporal
        )
        for key in (
            "metrics_pooled",
            "metrics_by_symbol",
            "metrics_by_year",
            "metrics_by_direction",
            "metrics_by_horizon",
            "concentration_metrics",
            "leave_one_out_metrics",
        ):
            self.assertFalse(result[key].empty, key)
        pooled = result["metrics_pooled"].iloc[0]
        for column in (
            "gross_win_rate",
            "MFE_mean",
            "MAE_median",
            "availability_rate",
        ):
            self.assertIn(column, pooled.index)
        self.assertEqual(result["gate"]["primary_horizon"], "30min")
        self.assertIn("gate_inputs", result["gate"])

    def test_numpy_bootstrap_is_deterministic_and_reports_intermediate_progress(self) -> None:
        config = replace(CONFIG, bootstrap_resamples=600)
        updates: list[dict] = []
        first = discovery.clustered_percentile_bootstrap_arrays(
            synthetic_gate_metrics(),
            config,
            progress_callback=lambda **payload: updates.append(payload),
            block_size=100,
        )
        second = discovery.clustered_percentile_bootstrap_arrays(
            synthetic_gate_metrics(), config, block_size=100
        )
        self.assertEqual(first, second)
        processed = [item["bootstrap_replicates_processed"] for item in updates]
        self.assertEqual(processed, sorted(processed))
        self.assertGreater(len(processed), 2)
        self.assertEqual(processed[-1], 600)
        self.assertTrue(all(item["groups_total"] > 1 for item in updates))

    def test_progress_failed_interrupted_memory_and_bounds(self) -> None:
        progress = discovery.ExecutionProgress(emit_console=False)
        stage = progress.start(
            "bootstrap",
            groups_total=3,
            groups_processed=0,
            bootstrap_replicates_total=10,
            bootstrap_replicates_processed=0,
        )
        progress.update(
            stage,
            groups_processed=3,
            bootstrap_replicates_processed=5,
            eta_seconds=1,
        )
        self.assertIsInstance(stage["memory_mb"], float)
        with self.assertRaises(ValueError):
            progress.update(stage, bootstrap_replicates_processed=11)
        progress.mark_failed(RuntimeError("failure"), temp_dir=None)
        self.assertEqual(stage["status"], "failed")
        interrupted = discovery.ExecutionProgress(emit_console=False)
        interrupted.start("load")
        interrupted.mark_interrupted(temp_dir=None)
        interrupted.mark_interrupted(temp_dir=None)
        self.assertEqual(
            sum(item["stage"] == "interrupt" for item in interrupted.stages), 1
        )


class AtomicReplaceRetryTests(unittest.TestCase):
    @staticmethod
    def access_denied() -> PermissionError:
        error = PermissionError("Access is denied")
        error.winerror = 5
        return error

    @staticmethod
    def generic_winerror_5() -> OSError:
        error = OSError("Access is denied")
        error.winerror = 5
        return error

    def test_os_replace_succeeds_on_first_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / ".payload.tmp"
            destination = root / "payload.json"
            source.write_text("new", encoding="utf-8")
            destination.write_text("old", encoding="utf-8")
            real_replace = discovery.os.replace
            with (
                patch.object(discovery.os, "replace", wraps=real_replace) as replace_mock,
                patch.object(discovery.time, "sleep") as sleep_mock,
            ):
                discovery._atomic_replace_with_retry(source, destination)
            replace_mock.assert_called_once_with(source, destination)
            sleep_mock.assert_not_called()
            self.assertEqual(destination.read_text(encoding="utf-8"), "new")

    def test_two_permission_errors_then_success(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / ".payload.tmp"
            destination = root / "payload.json"
            source.write_text("new", encoding="utf-8")
            real_replace = discovery.os.replace
            calls = 0

            def flaky_replace(src, dst):
                nonlocal calls
                calls += 1
                if calls <= 2:
                    raise self.access_denied()
                return real_replace(src, dst)

            with (
                patch.object(
                    discovery.os, "replace", side_effect=flaky_replace
                ) as replace_mock,
                patch.object(discovery.time, "sleep") as sleep_mock,
            ):
                discovery._atomic_replace_with_retry(source, destination)
            self.assertEqual(replace_mock.call_count, 3)
            self.assertEqual(
                [item.args[0] for item in sleep_mock.call_args_list],
                list(discovery._ATOMIC_REPLACE_RETRY_DELAYS_SECONDS[:2]),
            )
            self.assertEqual(destination.read_text(encoding="utf-8"), "new")

    def test_generic_oserror_with_winerror_5_is_retried(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / ".payload.tmp"
            destination = root / "payload.json"
            source.write_text("new", encoding="utf-8")
            real_replace = discovery.os.replace
            calls = 0

            def flaky_replace(src, dst):
                nonlocal calls
                calls += 1
                if calls == 1:
                    raise self.generic_winerror_5()
                return real_replace(src, dst)

            with (
                patch.object(
                    discovery.os, "replace", side_effect=flaky_replace
                ) as replace_mock,
                patch.object(discovery.time, "sleep") as sleep_mock,
            ):
                discovery._atomic_replace_with_retry(source, destination)
            self.assertEqual(replace_mock.call_count, 2)
            sleep_mock.assert_called_once_with(
                discovery._ATOMIC_REPLACE_RETRY_DELAYS_SECONDS[0]
            )

    def test_all_attempts_fail_and_original_error_is_propagated(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / ".payload.tmp"
            destination = root / "payload.json"
            source.write_text("new", encoding="utf-8")
            error = self.access_denied()
            with (
                patch.object(discovery.os, "replace", side_effect=error) as replace_mock,
                patch.object(discovery.time, "sleep") as sleep_mock,
            ):
                with self.assertRaises(PermissionError) as raised:
                    discovery._atomic_replace_with_retry(source, destination)
            self.assertIs(raised.exception, error)
            self.assertEqual(
                replace_mock.call_count,
                len(discovery._ATOMIC_REPLACE_RETRY_DELAYS_SECONDS) + 1,
            )
            self.assertEqual(
                sleep_mock.call_count,
                len(discovery._ATOMIC_REPLACE_RETRY_DELAYS_SECONDS),
            )
            self.assertTrue(source.is_file())
            self.assertFalse(destination.exists())

    def test_unrelated_error_is_not_retried(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / ".payload.tmp"
            destination = root / "payload.json"
            source.write_text("new", encoding="utf-8")
            error = OSError("unrelated")
            with (
                patch.object(discovery.os, "replace", side_effect=error) as replace_mock,
                patch.object(discovery.time, "sleep") as sleep_mock,
            ):
                with self.assertRaises(OSError) as raised:
                    discovery._atomic_replace_with_retry(source, destination)
            self.assertIs(raised.exception, error)
            replace_mock.assert_called_once_with(source, destination)
            sleep_mock.assert_not_called()
            self.assertTrue(source.is_file())

    def test_temporary_remains_available_during_retries(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / ".payload.tmp"
            destination = root / "payload.json"
            source.write_text("new", encoding="utf-8")
            real_replace = discovery.os.replace
            source_states: list[bool] = []

            def flaky_replace(src, dst):
                source_states.append(Path(src).is_file())
                if len(source_states) <= 2:
                    raise self.access_denied()
                return real_replace(src, dst)

            with (
                patch.object(discovery.os, "replace", side_effect=flaky_replace),
                patch.object(discovery.time, "sleep"),
            ):
                discovery._atomic_replace_with_retry(source, destination)
            self.assertEqual(source_states, [True, True, True])

    def test_temporary_disappears_after_success(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / ".payload.tmp"
            destination = root / "payload.json"
            source.write_text("new", encoding="utf-8")
            real_replace = discovery.os.replace
            with patch.object(discovery.os, "replace", wraps=real_replace):
                discovery._atomic_replace_with_retry(source, destination)
            self.assertFalse(source.exists())
            self.assertTrue(destination.is_file())

    def run_progress_update_with_transient_locks(self, root: Path):
        progress_path = root / "execution_progress.json"
        progress = discovery.ExecutionProgress(
            progress_path=progress_path,
            emit_console=False,
        )
        stage = progress.start(
            "aggregations_and_bootstrap",
            groups_total=4,
            groups_processed=0,
            bootstrap_replicates_total=10_000,
            bootstrap_replicates_processed=0,
        )
        real_replace = discovery.os.replace
        observations: list[dict] = []
        calls = 0

        def flaky_replace(src, dst):
            nonlocal calls
            calls += 1
            if calls <= 2:
                observations.append(
                    {
                        "temporary_exists": Path(src).is_file(),
                        "destination": json.loads(
                            Path(dst).read_text(encoding="utf-8")
                        ),
                        "temporary": json.loads(
                            Path(src).read_text(encoding="utf-8")
                        ),
                    }
                )
                raise self.access_denied()
            return real_replace(src, dst)

        with (
            patch.object(discovery.os, "replace", side_effect=flaky_replace),
            patch.object(discovery.time, "sleep"),
        ):
            progress.update(
                stage,
                groups_processed=2,
                bootstrap_replicates_processed=2_048,
                eta_seconds=1.0,
            )
        payload = json.loads(progress_path.read_text(encoding="utf-8"))
        return progress, stage, observations, payload

    def test_execution_progress_continues_after_transient_locks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            _, stage, observations, payload = (
                self.run_progress_update_with_transient_locks(Path(temporary))
            )
        self.assertEqual(len(observations), 2)
        self.assertEqual(stage["bootstrap_replicates_processed"], 2_048)
        self.assertEqual(
            payload["stages"][0]["bootstrap_replicates_processed"], 2_048
        )

    def test_progress_stage_is_not_duplicated_by_retries(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            progress, _, _, payload = self.run_progress_update_with_transient_locks(
                Path(temporary)
            )
        self.assertEqual(len(progress.stages), 1)
        self.assertEqual(len(payload["stages"]), 1)
        self.assertEqual(payload["stages"][0]["stage"], "aggregations_and_bootstrap")

    def test_results_written_does_not_change_during_progress_retries(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            _, stage, observations, payload = (
                self.run_progress_update_with_transient_locks(Path(temporary))
            )
        self.assertFalse(stage["results_written"])
        self.assertFalse(payload["stages"][0]["results_written"])
        for observation in observations:
            self.assertFalse(
                observation["destination"]["stages"][0]["results_written"]
            )
            self.assertFalse(
                observation["temporary"]["stages"][0]["results_written"]
            )

    def test_destination_remains_atomic_until_replace_succeeds(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / ".payload.tmp"
            destination = root / "payload.json"
            source.write_text("new", encoding="utf-8")
            destination.write_text("old", encoding="utf-8")
            real_replace = discovery.os.replace
            observed_destinations: list[str] = []
            calls = 0

            def flaky_replace(src, dst):
                nonlocal calls
                calls += 1
                if calls <= 2:
                    observed_destinations.append(
                        Path(dst).read_text(encoding="utf-8")
                    )
                    raise self.access_denied()
                return real_replace(src, dst)

            with (
                patch.object(discovery.os, "replace", side_effect=flaky_replace),
                patch.object(discovery.time, "sleep"),
            ):
                discovery._atomic_replace_with_retry(source, destination)
            self.assertEqual(observed_destinations, ["old", "old"])
            self.assertEqual(destination.read_text(encoding="utf-8"), "new")


class ChecksumAtomicTests(unittest.TestCase):
    def prepare_directory(self, root: Path):
        for name in discovery.REQUIRED_OUTPUT_FILES:
            if name != "checksums.json":
                (root / name).write_bytes(f"output-{name}".encode())
        input_dir = root / "inputs"
        input_dir.mkdir()
        input_file = input_dir / "input.bin"
        input_file.write_bytes(b"input")
        records = []
        for name in (
            "QQQ_curated_dataset",
            "SPY_curated_dataset",
            "QQQ_manifest",
            "SPY_manifest",
            "config_yaml",
        ):
            records.append(
                {
                    "name": name,
                    "kind": "file",
                    "path": str(input_file),
                    "size": input_file.stat().st_size,
                    "sha256": hashlib.sha256(input_file.read_bytes()).hexdigest(),
                }
            )
        for name in (
            "canonical_payload_hash",
            "preregistration_freeze_commit",
            "execution_freeze_commit",
            "head_commit",
        ):
            value = name
            records.append(
                {
                    "name": name,
                    "kind": "logical",
                    "value": value,
                    "size": len(value),
                    "sha256": hashlib.sha256(value.encode()).hexdigest(),
                }
            )
        discovery._write_checksums(root, records)
        return records

    def test_complete_checksums_reopen_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.prepare_directory(root)
            discovery._verify_checksums(root)

    def test_detects_corrupt_size_missing_extra_and_input(self) -> None:
        cases = ("corrupt", "missing", "extra", "input")
        for case in cases:
            with self.subTest(case=case):
                with tempfile.TemporaryDirectory() as temporary:
                    root = Path(temporary)
                    self.prepare_directory(root)
                    if case == "corrupt":
                        (root / "confirmed_events.csv").write_bytes(b"changed")
                    elif case == "missing":
                        (root / "confirmed_events.csv").unlink()
                    elif case == "extra":
                        (root / "extra.txt").write_text("x", encoding="utf-8")
                    else:
                        (root / "input.bin").write_bytes(b"changed")
                    with self.assertRaises(RuntimeError):
                        discovery._verify_checksums(root)


class ProductRunnerTests(unittest.TestCase):
    def pipeline_context(self, root: Path):
        contracts = {
            symbol: make_contract(root, symbol) for symbol in discovery.SYMBOLS
        }
        frames = {
            "QQQ": synthetic_minutes("QQQ", Direction.LONG),
            "SPY": synthetic_minutes("SPY", Direction.SHORT),
        }
        reports = {
            symbol: discovery.TemporalAccessReport(
                discovery.DISCOVERY_START,
                discovery.DISCOVERY_END,
                "2024-01-02T14:30:00+00:00",
                "2024-02-01T20:59:00+00:00",
                0,
            )
            for symbol in discovery.SYMBOLS
        }
        preflight = {
            "config": CONFIG,
            "manifest_contracts": contracts,
            "head_commit": HEAD,
        }

        def bounded(path):
            symbol = "QQQ" if "QQQ" in str(path) else "SPY"
            return frames[symbol].copy(), reports[symbol]

        return preflight, bounded

    def test_success_uses_canonical_path_contract_and_verified_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            preflight, bounded = self.pipeline_context(root)
            final = root / "final"
            with (
                patch.object(discovery, "DEFAULT_OUTPUT_DIR", final),
                patch.object(
                    discovery,
                    "ExecutionProgress",
                    side_effect=lambda: REAL_EXECUTION_PROGRESS(emit_console=False),
                ),
                patch.object(
                    discovery,
                    "validate_discovery_preflight",
                    return_value=preflight,
                ) as preflight_mock,
                patch.object(discovery, "load_bounded_dataset", side_effect=bounded),
            ):
                result = discovery.run_discovery(request())
            preflight_mock.assert_called_once_with(request())
            self.assertTrue(final.is_dir())
            self.assertEqual(
                {path.name for path in final.iterdir()},
                set(discovery.REQUIRED_OUTPUT_FILES),
            )
            discovery._verify_checksums(final)
            manifest = json.loads(
                (final / "run_manifest.json").read_text(encoding="utf-8")
            )
            self.assertTrue(manifest["results_written"])
            self.assertTrue(manifest["checksums_verified"])
            self.assertEqual(manifest["execution_freeze_commit"], HEAD)
            self.assertEqual(result["output_dir"], str(final))

    def test_final_preexisting_and_rename_failure_never_yield_valid_final(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            preflight, bounded = self.pipeline_context(root)
            final = root / "final"
            final.mkdir()
            with (
                patch.object(discovery, "DEFAULT_OUTPUT_DIR", final),
                patch.object(
                    discovery,
                    "collect_runtime_state",
                    return_value=discovery.RuntimeState(HEAD, True, True, True, ""),
                ),
            ):
                with self.assertRaises(FileExistsError):
                    discovery.validate_discovery_preflight(request())
            final.rmdir()
            with (
                patch.object(discovery, "DEFAULT_OUTPUT_DIR", final),
                patch.object(
                    discovery,
                    "ExecutionProgress",
                    side_effect=lambda: REAL_EXECUTION_PROGRESS(emit_console=False),
                ),
                patch.object(
                    discovery,
                    "validate_discovery_preflight",
                    return_value=preflight,
                ),
                patch.object(discovery, "load_bounded_dataset", side_effect=bounded),
                patch.object(
                    discovery, "_atomic_rename", side_effect=OSError("rename")
                ),
            ):
                with self.assertRaises(OSError):
                    discovery.run_discovery(request())
            self.assertFalse(final.exists())
            temps = list(root.glob(".final.tmp-*"))
            self.assertEqual(len(temps), 1)
            failed_manifest = json.loads(
                (temps[0] / "run_manifest.json").read_text(encoding="utf-8")
            )
            self.assertFalse(failed_manifest["results_written"])

    def test_interruptions_return_no_final_and_one_marker(self) -> None:
        targets = (
            "load_bounded_dataset",
            "detect_confirmed_events",
            "build_unconditional_candidates",
            "clustered_percentile_bootstrap_arrays",
            "_write_artifacts",
        )
        for target in targets:
            with self.subTest(target=target):
                with tempfile.TemporaryDirectory() as temporary:
                    root = Path(temporary)
                    preflight, bounded = self.pipeline_context(root)
                    final = root / "final"
                    patches = [
                        patch.object(discovery, "DEFAULT_OUTPUT_DIR", final),
                        patch.object(
                            discovery,
                            "ExecutionProgress",
                            side_effect=lambda: REAL_EXECUTION_PROGRESS(
                                emit_console=False
                            ),
                        ),
                        patch.object(
                            discovery,
                            "validate_discovery_preflight",
                            return_value=preflight,
                        ),
                        patch.object(
                            discovery, "load_bounded_dataset", side_effect=bounded
                        ),
                    ]
                    with patches[0], patches[1], patches[2], patches[3]:
                        with patch.object(
                            discovery, target, side_effect=KeyboardInterrupt
                        ):
                            with self.assertRaises(KeyboardInterrupt):
                                discovery.run_discovery(request())
                    self.assertFalse(final.exists())
                    temps = list(root.glob(".final.tmp-*"))
                    if temps:
                        payload = json.loads(
                            (temps[0] / "execution_progress.json").read_text(
                                encoding="utf-8"
                            )
                        )
                        self.assertEqual(
                            sum(
                                item["stage"] == "interrupt"
                                for item in payload["stages"]
                            ),
                            1,
                        )


class CliTests(unittest.TestCase):
    def test_required_arguments_and_unknown_mode(self) -> None:
        with self.assertRaises(SystemExit):
            discovery.main([])
        with self.assertRaises(SystemExit):
            discovery.main(["--mode", "unknown"])
        with self.assertRaises(SystemExit):
            discovery.main(["--mode", "run_discovery"])

    def test_validate_implementation_and_keyboard_interrupt_130(self) -> None:
        self.assertEqual(discovery.main(["--mode", "validate_implementation"]), 0)
        with patch.object(discovery, "run_discovery", side_effect=KeyboardInterrupt):
            self.assertEqual(
                discovery.main(
                    [
                        "--mode",
                        "run_discovery",
                        "--expected-preregistration-commit",
                        discovery.PREREGISTRATION_FREEZE_COMMIT,
                        "--expected-execution-freeze-commit",
                        HEAD,
                        "--expected-canonical-hash",
                        discovery.EXPECTED_CANONICAL_HASH,
                    ]
                ),
                130,
            )

    def test_validate_implementation_rejects_modified_canonical_mapping(self) -> None:
        mapping = yaml.safe_load((ROOT / discovery.CONFIG_PATH).read_text(encoding="utf-8"))
        mapping["safety_flags"]["broker_connected"] = True
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "bad.yaml"
            path.write_text(yaml.safe_dump(mapping), encoding="utf-8")
            with patch.object(discovery, "CONFIG_PATH", path):
                with self.assertRaises(ValueError):
                    discovery.validate_implementation()


if __name__ == "__main__":
    unittest.main()
