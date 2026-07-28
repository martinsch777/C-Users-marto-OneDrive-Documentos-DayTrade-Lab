from __future__ import annotations

import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import yaml

from src.research.hyp_or_cont_event_01_discovery import (
    EXPECTED_CANONICAL_HASH,
    EXPECTED_FREEZE_COMMIT,
    REQUIRED_OUTPUT_FILES,
    ExecutionProgress,
    OrContDiscoveryRequest,
    RuntimeState,
    prepare_only_manifest,
    run_operational_discovery,
    validate_discovery_preflight,
)
from src.research.hyp_or_cont_event_01 import (
    HORIZONS,
    PRIMARY_HORIZON,
    OrContEventConfig,
    aggregate_incremental_metrics,
    aggregate_incremental_metrics_reference,
    assert_no_strategy_columns,
    attach_cost_thresholds,
    attach_incremental_returns,
    bootstrap_mean_by_session,
    bootstrap_mean_by_session_reference,
    compute_aggregation_and_bootstrap_outputs,
    compute_unconditional_control,
    compute_unconditional_control_reference,
    compute_or_continuation_paths,
    detect_or_continuation_events,
    evaluate_discovery_gate,
    frozen_cost_profiles,
    round_trip_cost_return,
    validate_or_cont_period,
)


CONFIG_PATH = Path("configs/research/hypotheses/HYP-OR-CONT-EVENT-01.yaml")
EXECUTION_FREEZE_COMMIT = "f" * 40
DISCOVERY_ARTIFACT_DIR = Path("artifacts/research/HYP-OR-CONT-EVENT-01/discovery_2022_2024")
DISCOVERY_RESULTS_DOC = Path("docs/HYP_OR_CONT_EVENT_01_DISCOVERY_RESULTS.md")
RESEARCH_REGISTRY_PATH = Path("docs/RESEARCH_HYPOTHESIS_REGISTRY.md")


def ts(value: str) -> pd.Timestamp:
    return pd.Timestamp(value, tz="America/New_York").tz_convert("UTC")


def bar(value: str, open_: float, high: float, low: float, close: float) -> dict:
    return {
        "timestamp": ts(value),
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": 1000,
    }


def opening(date: str = "2024-07-01") -> list[dict]:
    return [
        bar(f"{date} 09:30", 100.0, 101.0, 99.0, 100.0),
        bar(f"{date} 09:35", 100.0, 101.0, 99.0, 100.0),
        bar(f"{date} 09:40", 100.0, 101.0, 99.0, 100.0),
        bar(f"{date} 09:45", 100.0, 101.0, 99.0, 100.0),
        bar(f"{date} 09:50", 100.0, 101.0, 99.0, 100.0),
        bar(f"{date} 09:55", 100.0, 101.0, 99.0, 100.0),
    ]


def frame(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows).sort_values("timestamp").reset_index(drop=True)


def low_sweep_day(extra: list[dict] | None = None, date: str = "2024-07-01") -> pd.DataFrame:
    rows = opening(date)
    rows.extend(
        [
            bar(f"{date} 10:00", 100.0, 100.2, 98.8, 99.4),
            bar(f"{date} 10:05", 99.4, 100.1, 98.9, 99.5),
            bar(f"{date} 10:10", 99.5, 100.0, 98.9, 99.6),
            bar(f"{date} 10:15", 99.6, 100.3, 98.95, 99.7),
            bar(f"{date} 10:20", 100.0, 100.2, 99.4, 99.8),
        ]
    )
    rows.extend(extra or [])
    return frame(rows)


def high_sweep_day(extra: list[dict] | None = None, date: str = "2024-07-01") -> pd.DataFrame:
    rows = opening(date)
    rows.extend(
        [
            bar(f"{date} 10:00", 100.0, 101.2, 99.8, 100.6),
            bar(f"{date} 10:05", 100.6, 101.1, 99.8, 100.5),
            bar(f"{date} 10:10", 100.5, 101.0, 99.7, 100.4),
            bar(f"{date} 10:15", 100.4, 100.9, 99.6, 100.3),
            bar(f"{date} 10:20", 100.0, 100.8, 99.5, 100.2),
        ]
    )
    rows.extend(extra or [])
    return frame(rows)


def synthetic_unconditional_inputs(*, sessions: int = 6) -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    frames: dict[str, pd.DataFrame] = {}
    path_rows: list[dict] = []
    for symbol, base_price in (("QQQ", 100.0), ("SPY", 200.0)):
        rows: list[dict] = []
        for session_number in range(sessions):
            day = pd.Timestamp("2024-01-02") + pd.offsets.Day(session_number)
            date = day.strftime("%Y-%m-%d")
            for bar_number, minute in enumerate(range(9 * 60 + 30, 16 * 60, 5)):
                hour = minute // 60
                minute_of_hour = minute % 60
                price = base_price + session_number * 0.13 + bar_number * 0.017
                rows.append(
                    bar(
                        f"{date} {hour:02d}:{minute_of_hour:02d}",
                        price,
                        price + 0.2,
                        price - 0.2,
                        price + 0.03,
                    )
                )
            for orientation in ("continuation_long", "continuation_short"):
                for horizon in ("15min", "30min", "60min", "session_close"):
                    executable = ts(f"{date} 10:00")
                    path_rows.append(
                        {
                            "symbol": symbol,
                            "session_date": date,
                            "executable_timestamp": executable,
                            "direction_orientation": orientation,
                            "year": 2024,
                            "executable_timestamp_hour_bucket": "10:00",
                            "horizon": horizon,
                            "event_return": 0.001 if orientation == "continuation_long" else -0.001,
                        }
                    )
        frames[symbol] = frame(rows)
    return frames, pd.DataFrame(path_rows)


def synthetic_bootstrap_path_metrics(*, sessions: int = 6) -> pd.DataFrame:
    frames, paths = synthetic_unconditional_inputs(sessions=sessions)
    control = compute_unconditional_control(frames, paths)
    enriched = attach_incremental_returns(paths, control)
    enriched["maximum_favorable_excursion"] = enriched["event_return"].astype(float).abs() + 0.002
    enriched["maximum_adverse_excursion"] = -enriched["event_return"].astype(float).abs() - 0.001
    enriched["baseline_cost_return"] = 0.0004
    enriched["stress_cost_return"] = 0.0008
    return enriched


def write_manifest(path: Path, symbol: str, *, status: str = "approved_for_or_fvg_backtest") -> None:
    payload = {
        "symbol": symbol,
        "asset_class": "equity",
        "timeframe": "1min",
        "provider": "alpaca",
        "feed": "sip",
        "adjustment": "raw",
        "source_timezone": "America/New_York",
        "rth_only": True,
        "start": "2022-01-01",
        "end": "2026-07-06",
        "rows": 1,
        "first_timestamp": "2022-01-03T14:30:00Z",
        "last_timestamp": "2026-07-06T19:59:00Z",
        "input_file": f"data/curated/{symbol}_synthetic.csv",
        "output_file": f"data/curated/{symbol}_synthetic.csv",
        "curated_file": f"data/curated/{symbol}_synthetic.csv",
        "sha256": symbol.lower() * 16,
        "calendar_source": "builtin_us_equity_calendar_v1",
        "calendar_loaded": True,
        "calendar_holidays_loaded": 1,
        "calendar_early_closes_loaded": 1,
        "audit_apt_for_or_fvg_backtest": status == "approved_for_or_fvg_backtest",
        "audit_critical_warnings": [] if status == "approved_for_or_fvg_backtest" else ["failed"],
        "audit_warnings": [],
        "dataset_status": status,
        "total_excluded_sessions": 0,
        "excluded_sessions": [],
        "broker_connected": False,
        "orders_sent": False,
        "live_trading_enabled": False,
        "paper_broker_enabled": False,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


class HypOrContEvent01Tests(unittest.TestCase):
    def test_event_does_not_exist_before_third_confirmation_bar_closes(self):
        data = frame(opening() + low_sweep_day().iloc[6:9].to_dict("records"))
        events, exclusions = detect_or_continuation_events(data, "QQQ")
        self.assertTrue(events.empty)
        self.assertIn("insufficient_confirmation_bars", set(exclusions["reason_for_exclusion"]))

    def test_executable_timestamp_is_open_after_third_confirmation_bar(self):
        events, _ = detect_or_continuation_events(low_sweep_day(), "QQQ")
        event = events.iloc[0]
        self.assertEqual(event["confirmation_timestamp"], ts("2024-07-01 10:20"))
        self.assertEqual(event["executable_timestamp"], ts("2024-07-01 10:20"))
        self.assertEqual(event["confirmation_bar_count"], 3)

    def test_future_prices_after_executable_do_not_select_event(self):
        base_events, _ = detect_or_continuation_events(
            low_sweep_day([bar("2024-07-01 10:25", 100.0, 100.1, 99.6, 99.8)]),
            "QQQ",
        )
        changed = low_sweep_day([bar("2024-07-01 10:25", 100.0, 150.0, 50.0, 140.0)])
        changed_events, _ = detect_or_continuation_events(changed, "QQQ")
        pd.testing.assert_frame_equal(base_events, changed_events)

    def test_exactly_three_confirmation_bars_are_used(self):
        data = low_sweep_day([bar("2024-07-01 10:25", 102.0, 103.0, 102.0, 100.2)])
        events, _ = detect_or_continuation_events(data, "QQQ")
        self.assertEqual(events.iloc[0]["confirmation_bar_count"], 3)
        self.assertEqual(len(events), 1)

    def test_first_signal_per_session_wins_independent_of_side(self):
        data = low_sweep_day(
            [
                bar("2024-07-01 10:25", 100.0, 101.4, 99.7, 100.8),
                bar("2024-07-01 10:30", 100.8, 101.2, 99.8, 100.7),
                bar("2024-07-01 10:35", 100.7, 101.0, 99.6, 100.6),
                bar("2024-07-01 10:40", 100.6, 100.9, 99.6, 100.5),
                bar("2024-07-01 10:45", 100.5, 100.8, 99.5, 100.4),
            ]
        )
        events, _ = detect_or_continuation_events(data, "QQQ")
        self.assertEqual(len(events), 1)
        self.assertEqual(events.iloc[0]["swept_side"], "low")

    def test_maximum_one_event_per_session(self):
        data = pd.concat([low_sweep_day(date="2024-07-01"), high_sweep_day(date="2024-07-02")])
        events, _ = detect_or_continuation_events(data, "SPY")
        self.assertEqual(events.groupby("session_date").size().max(), 1)
        self.assertEqual(len(events), 2)

    def test_low_sweep_orientation_is_continuation_short(self):
        events, _ = detect_or_continuation_events(low_sweep_day(), "QQQ")
        self.assertEqual(events.iloc[0]["swept_side"], "low")
        self.assertEqual(events.iloc[0]["direction_orientation"], "continuation_short")

    def test_high_sweep_orientation_is_continuation_long(self):
        events, _ = detect_or_continuation_events(high_sweep_day(), "QQQ")
        self.assertEqual(events.iloc[0]["swept_side"], "high")
        self.assertEqual(events.iloc[0]["direction_orientation"], "continuation_long")

    def test_horizons_are_measured_from_executable_timestamp(self):
        data = low_sweep_day(
            [
                bar("2024-07-01 10:25", 100.0, 100.2, 98.0, 99.0),
                bar("2024-07-01 10:30", 99.0, 99.2, 97.8, 98.0),
                bar("2024-07-01 10:35", 98.0, 98.2, 97.0, 97.5),
                bar("2024-07-01 10:40", 97.5, 98.0, 96.8, 97.2),
                bar("2024-07-01 10:45", 97.2, 97.4, 96.5, 96.8),
                bar("2024-07-01 10:50", 96.8, 97.0, 96.0, 97.0),
            ]
        )
        events, _ = detect_or_continuation_events(data, "QQQ")
        paths = compute_or_continuation_paths(data, events, horizons=("30min",))
        self.assertEqual(paths.iloc[0]["horizon"], "30min")
        self.assertEqual(paths.iloc[0]["future_close"], 97.0)
        self.assertAlmostEqual(paths.iloc[0]["event_return"], 0.03)

    def test_paths_do_not_cross_overnight(self):
        data = low_sweep_day(
            [
                bar("2024-07-01 10:25", 100.0, 100.1, 99.8, 100.0),
                bar("2024-07-02 09:30", 200.0, 201.0, 199.0, 200.0),
                bar("2024-07-02 09:35", 200.0, 201.0, 199.0, 200.0),
                bar("2024-07-02 09:40", 200.0, 201.0, 199.0, 200.0),
                bar("2024-07-02 09:45", 200.0, 201.0, 199.0, 200.0),
                bar("2024-07-02 09:50", 200.0, 201.0, 199.0, 200.0),
                bar("2024-07-02 09:55", 200.0, 201.0, 199.0, 200.0),
                bar("2024-07-02 10:00", 200.0, 200.5, 199.5, 200.0),
            ]
        )
        events, _ = detect_or_continuation_events(data, "QQQ")
        paths = compute_or_continuation_paths(data, events, horizons=("60min",))
        self.assertTrue(paths.empty)

    def test_validation_2025_is_blocked(self):
        with self.assertRaises(PermissionError):
            validate_or_cont_period("validation_2025")

    def test_2026_is_blocked(self):
        with self.assertRaises(PermissionError):
            validate_or_cont_period("parity_debug_2026")

    def test_primary_horizon_is_fixed_at_30min(self):
        payload = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
        self.assertEqual(PRIMARY_HORIZON, "30min")
        self.assertEqual(payload["horizons"]["primary"], "30min")
        self.assertNotEqual(payload["horizons"]["primary"], "5min")
        self.assertEqual(HORIZONS[0], "30min")

    def test_costs_are_explicit_and_match_fcr_source(self):
        costs = frozen_cost_profiles()
        self.assertEqual(costs["baseline"]["commission_rate_per_side"], 0.0001)
        self.assertEqual(costs["baseline"]["slippage_ticks_per_execution"], 1.0)
        self.assertEqual(costs["baseline"]["round_trip_slippage_dollars_per_share"], 0.02)
        self.assertEqual(costs["stress"]["commission_rate_per_side"], 0.0002)
        self.assertEqual(costs["stress"]["slippage_ticks_per_execution"], 2.0)
        self.assertAlmostEqual(round_trip_cost_return("baseline", 100.0), 0.0004)

    def test_no_orders_no_strategy_no_position_sizing(self):
        payload = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
        self.assertTrue(payload["blocked_actions"]["create_strategy"])
        self.assertTrue(payload["blocked_actions"]["create_orders"])
        self.assertTrue(payload["blocked_actions"]["backtest_pnl"])
        events, _ = detect_or_continuation_events(low_sweep_day(), "QQQ")
        paths = compute_or_continuation_paths(low_sweep_day(), events, horizons=("15min",))
        assert_no_strategy_columns(events)
        assert_no_strategy_columns(paths)

    def test_safety_flags_remain_false(self):
        config = OrContEventConfig()
        self.assertEqual(config.confirmation_bar_count, 3)
        payload = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
        self.assertFalse(any(payload["safety_flags"].values()))

    def make_request(self, root: Path, **overrides) -> OrContDiscoveryRequest:
        qqq_manifest = root / "QQQ_manifest.json"
        spy_manifest = root / "SPY_manifest.json"
        write_manifest(qqq_manifest, "QQQ")
        write_manifest(spy_manifest, "SPY")
        values = {
            "mode": "run_discovery",
            "expected_freeze_commit": EXECUTION_FREEZE_COMMIT,
            "expected_canonical_hash": EXPECTED_CANONICAL_HASH,
            "manifest_paths": {"QQQ": qqq_manifest, "SPY": spy_manifest},
            "dataset_paths": {"QQQ": root / "QQQ.csv", "SPY": root / "SPY.csv"},
        }
        values.update(overrides)
        return OrContDiscoveryRequest(**values)

    def operational_day(self, *, symbol: str) -> pd.DataFrame:
        base = low_sweep_day() if symbol == "QQQ" else high_sweep_day()
        rows = base.to_dict("records")
        rows.extend(
            [
                bar("2024-07-01 10:25", 100.0, 100.2, 99.0, 99.6),
                bar("2024-07-01 10:30", 99.6, 100.0, 98.8, 99.2),
                bar("2024-07-01 10:35", 99.2, 100.1, 98.5, 99.0),
                bar("2024-07-01 10:40", 99.0, 100.2, 98.2, 98.8),
                bar("2024-07-01 10:45", 98.8, 100.3, 98.0, 98.6),
                bar("2024-07-01 10:50", 98.6, 100.4, 97.8, 98.4),
                bar("2024-07-01 11:20", 98.4, 100.5, 97.6, 98.2),
            ]
        )
        if symbol == "SPY":
            for row in rows:
                row["open"], row["high"], row["low"], row["close"] = (
                    200.0,
                    201.4 if row["timestamp"] == ts("2024-07-01 10:00") else 200.8,
                    199.5,
                    201.0,
                )
        return frame(rows)

    def fake_loader(self, symbol: str, csv_path: Path, manifest_path: Path):
        data = self.operational_day(symbol=symbol)
        blocked = frame([bar("2025-01-02 10:00", 1, 1, 1, 1), bar("2026-01-02 10:00", 1, 1, 1, 1)])
        return pd.concat([data, blocked], ignore_index=True), {"symbol": symbol, "sha256": f"{symbol}-sha"}

    def test_prepare_only_runner_does_not_execute(self):
        payload = prepare_only_manifest()
        self.assertFalse(payload["event_study_executed"])
        self.assertFalse(payload["results_written"])

    def test_cli_recognizes_expected_freeze_and_hash_arguments_in_prepare_only(self):
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "src.research.hyp_or_cont_event_01_discovery",
                "--mode",
                "prepare_only",
                "--expected-freeze-commit",
                EXECUTION_FREEZE_COMMIT,
                "--expected-canonical-hash",
                EXPECTED_CANONICAL_HASH,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["mode"], "prepare_only")
        self.assertEqual(payload["execution_freeze_commit"], EXECUTION_FREEZE_COMMIT)

    def test_cli_requires_expected_freeze_and_hash_for_run_discovery(self):
        completed = subprocess.run(
            [sys.executable, "-m", "src.research.hyp_or_cont_event_01_discovery", "--mode", "run_discovery"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("--expected-freeze-commit is required for run_discovery", completed.stderr)

    def test_preflight_validates_freeze_commit_and_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request = self.make_request(root)
            runtime = RuntimeState(EXECUTION_FREEZE_COMMIT, EXPECTED_FREEZE_COMMIT, EXPECTED_FREEZE_COMMIT)
            payload = validate_discovery_preflight(request, runtime_state=runtime)
            self.assertEqual(payload["preregistration_commit"], EXPECTED_FREEZE_COMMIT)
            self.assertEqual(payload["execution_freeze_commit"], EXECUTION_FREEZE_COMMIT)
            self.assertEqual(payload["freeze_commit"], EXECUTION_FREEZE_COMMIT)
            self.assertEqual(payload["canonical_payload_hash"], EXPECTED_CANONICAL_HASH)

    def test_preflight_rejects_wrong_freeze_commit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request = self.make_request(root)
            runtime = RuntimeState("0" * 40, EXPECTED_FREEZE_COMMIT, EXPECTED_FREEZE_COMMIT)
            with self.assertRaisesRegex(PermissionError, "expected_freeze_commit=.*actual_head_commit"):
                validate_discovery_preflight(request, runtime_state=runtime)

    def test_preflight_rejects_wrong_canonical_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request = self.make_request(root, expected_canonical_hash="0" * 64)
            runtime = RuntimeState(EXECUTION_FREEZE_COMMIT, EXPECTED_FREEZE_COMMIT, EXPECTED_FREEZE_COMMIT)
            with self.assertRaisesRegex(PermissionError, "Canonical payload hash mismatch"):
                validate_discovery_preflight(request, runtime_state=runtime)

    def test_preflight_requires_run_discovery_arguments(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request = self.make_request(root, expected_freeze_commit=None, expected_canonical_hash=None)
            runtime = RuntimeState(EXECUTION_FREEZE_COMMIT, EXPECTED_FREEZE_COMMIT, EXPECTED_FREEZE_COMMIT)
            with self.assertRaisesRegex(PermissionError, "--expected-freeze-commit"):
                validate_discovery_preflight(request, runtime_state=runtime)

    def test_preflight_requires_approved_curated_manifests(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request = self.make_request(root)
            write_manifest(request.manifest_paths["QQQ"], "QQQ", status="failed_audit")
            runtime = RuntimeState(EXECUTION_FREEZE_COMMIT, EXPECTED_FREEZE_COMMIT, EXPECTED_FREEZE_COMMIT)
            with self.assertRaises(PermissionError):
                validate_discovery_preflight(request, runtime_state=runtime)

    def test_unconditional_control_is_matched_by_symbol_year_hour_horizon(self):
        data = low_sweep_day(
            [
                bar("2024-07-01 10:25", 100.0, 100.5, 99.0, 99.0),
                bar("2024-07-01 10:50", 99.0, 99.5, 98.5, 98.0),
            ]
        )
        events, _ = detect_or_continuation_events(data, "QQQ")
        paths = compute_or_continuation_paths(data, events, horizons=("30min",))
        control = compute_unconditional_control({"QQQ": data}, paths)
        self.assertEqual(control.iloc[0]["symbol"], "QQQ")
        self.assertEqual(control.iloc[0]["year"], 2024)
        self.assertEqual(control.iloc[0]["executable_timestamp_hour_bucket"], "10:00")
        self.assertEqual(control.iloc[0]["horizon"], "30min")
        self.assertGreaterEqual(control.iloc[0]["unconditional_sample_count"], 1)

    def test_unconditional_control_optimized_matches_reference_exactly(self):
        frames, paths = synthetic_unconditional_inputs(sessions=8)
        reference = compute_unconditional_control_reference(frames, paths)
        optimized = compute_unconditional_control(frames, paths, progress_interval_seconds=0)
        pd.testing.assert_frame_equal(reference, optimized, check_dtype=False, rtol=0.0, atol=1e-12)
        reference_incremental = attach_incremental_returns(paths, reference)
        optimized_incremental = attach_incremental_returns(paths, optimized)
        pd.testing.assert_series_equal(
            reference_incremental["incremental_return"],
            optimized_incremental["incremental_return"],
            check_names=False,
            check_dtype=False,
            rtol=0.0,
            atol=1e-12,
        )
        self.assertEqual(
            int(pd.util.hash_pandas_object(reference.astype(str), index=False).sum()),
            int(pd.util.hash_pandas_object(optimized.astype(str), index=False).sum()),
        )

    def test_unconditional_control_progress_reports_internally(self):
        frames, paths = synthetic_unconditional_inputs(sessions=3)
        updates: list[dict] = []
        control = compute_unconditional_control(
            frames,
            paths,
            progress_callback=lambda **payload: updates.append(payload),
            progress_interval_seconds=0,
        )
        self.assertFalse(control.empty)
        self.assertGreaterEqual(len(updates), 2)
        self.assertIn("groups_total", updates[-1])
        self.assertEqual(updates[-1]["groups_processed"], updates[-1]["groups_total"])
        self.assertIn("rows_processed", updates[-1])
        self.assertIn("memory_mb", updates[-1])
        self.assertIn("eta_seconds", updates[-1])

    def test_unconditional_control_does_not_match_2025_or_2026_when_path_year_is_2024(self):
        frames, paths = synthetic_unconditional_inputs(sessions=1)
        future_rows = []
        for date in ("2025-01-02", "2026-01-02"):
            future_rows.extend(
                [
                    bar(f"{date} 10:00", 500.0, 501.0, 499.0, 500.5),
                    bar(f"{date} 10:30", 600.0, 601.0, 599.0, 600.5),
                ]
            )
        frames["QQQ"] = pd.concat([frames["QQQ"], frame(future_rows)], ignore_index=True).sort_values("timestamp").reset_index(drop=True)
        qqq_2024_paths = paths[(paths["symbol"] == "QQQ") & (paths["horizon"] == "30min")].head(1).reset_index(drop=True)
        control = compute_unconditional_control({"QQQ": frames["QQQ"]}, qqq_2024_paths)
        reference = compute_unconditional_control_reference({"QQQ": frames["QQQ"]}, qqq_2024_paths)
        self.assertEqual(int(control.iloc[0]["unconditional_sample_count"]), int(reference.iloc[0]["unconditional_sample_count"]))
        self.assertEqual(int(control.iloc[0]["year"]), 2024)

    def test_unconditional_control_uses_only_requested_horizon_for_30min(self):
        frames, paths = synthetic_unconditional_inputs(sessions=1)
        qqq_30min = paths[(paths["symbol"] == "QQQ") & (paths["horizon"] == "30min")].head(1).reset_index(drop=True)
        baseline = compute_unconditional_control({"QQQ": frames["QQQ"]}, qqq_30min)
        changed = frames["QQQ"].copy()
        late_mask = changed["timestamp"] == ts("2024-01-02 11:30")
        changed.loc[late_mask, "close"] = 9999.0
        shifted = compute_unconditional_control({"QQQ": changed}, qqq_30min)
        self.assertAlmostEqual(
            float(baseline.iloc[0]["unconditional_return"]),
            float(shifted.iloc[0]["unconditional_return"]),
            places=12,
        )

    def test_incremental_return_is_event_minus_control(self):
        paths = pd.DataFrame(
            [
                {
                    "symbol": "QQQ",
                    "session_date": "2024-07-01",
                    "executable_timestamp": ts("2024-07-01 10:20"),
                    "direction_orientation": "continuation_short",
                    "horizon": "30min",
                    "event_return": 0.01,
                }
            ]
        )
        control = paths.copy()
        control["unconditional_return"] = 0.004
        control["unconditional_sample_count"] = 12
        merged = attach_incremental_returns(paths, control)
        self.assertAlmostEqual(merged.iloc[0]["incremental_return"], 0.006)

    def test_bootstrap_mean_by_session_matches_reference(self):
        sample = pd.DataFrame(
            [
                {"session_date": "2024-01-02", "event_return": 0.01},
                {"session_date": "2024-01-02", "event_return": 0.02},
                {"session_date": "2024-01-03", "event_return": -0.01},
                {"session_date": "2024-01-04", "event_return": 0.03},
            ]
        )
        reference = bootstrap_mean_by_session_reference(sample, value_column="event_return", n_bootstrap=25, seed=17)
        optimized = bootstrap_mean_by_session(sample, value_column="event_return", n_bootstrap=25, seed=17)
        self.assertAlmostEqual(reference[0], optimized[0], places=12)
        self.assertAlmostEqual(reference[1], optimized[1], places=12)

    def test_aggregate_incremental_metrics_optimized_matches_reference(self):
        path_metrics = synthetic_bootstrap_path_metrics(sessions=5)
        for group_by in (("symbol", "direction_orientation", "horizon"), ("symbol",), ("year",)):
            with self.subTest(group_by=group_by):
                reference = aggregate_incremental_metrics_reference(path_metrics, group_by=group_by, n_bootstrap=25, seed=17)
                optimized = aggregate_incremental_metrics(path_metrics, group_by=group_by, n_bootstrap=25, seed=17)
                pd.testing.assert_frame_equal(reference, optimized, check_dtype=False, rtol=0.0, atol=1e-12)
                self.assertTrue((optimized["bootstrap_seed"] == 17).all())

    def test_aggregation_stage_outputs_match_reference_and_gate(self):
        path_metrics = synthetic_bootstrap_path_metrics(sessions=6)
        outputs = compute_aggregation_and_bootstrap_outputs(path_metrics, n_bootstrap=25, seed=17, progress_interval_seconds=0)
        reference_incremental = aggregate_incremental_metrics_reference(
            path_metrics,
            group_by=("symbol", "direction_orientation", "horizon"),
            n_bootstrap=25,
            seed=17,
        )
        reference_symbol = aggregate_incremental_metrics_reference(path_metrics, group_by=("symbol",), n_bootstrap=25, seed=17)
        reference_year = aggregate_incremental_metrics_reference(path_metrics, group_by=("year",), n_bootstrap=25, seed=17)
        pd.testing.assert_frame_equal(reference_incremental, outputs["incremental_metrics"], check_dtype=False, rtol=0.0, atol=1e-12)
        pd.testing.assert_frame_equal(reference_symbol, outputs["metrics_by_symbol"], check_dtype=False, rtol=0.0, atol=1e-12)
        pd.testing.assert_frame_equal(reference_year, outputs["metrics_by_year"], check_dtype=False, rtol=0.0, atol=1e-12)
        reference_bootstrap = reference_incremental.loc[
            :,
            [
                "symbol",
                "direction_orientation",
                "horizon",
                "bootstrap_ci_low",
                "bootstrap_ci_high",
                "bootstrap_grouped_by",
                "bootstrap_seed",
            ],
        ]
        pd.testing.assert_frame_equal(reference_bootstrap, outputs["bootstrap_intervals"], check_dtype=False, rtol=0.0, atol=1e-12)
        self.assertEqual(outputs["gate"], evaluate_discovery_gate(path_metrics, reference_bootstrap))
        self.assertEqual(
            int(pd.util.hash_pandas_object(outputs["incremental_metrics"].astype(str), index=False).sum()),
            int(pd.util.hash_pandas_object(reference_incremental.astype(str), index=False).sum()),
        )

    def test_aggregation_progress_reports_replicates_and_session_grouping(self):
        path_metrics = synthetic_bootstrap_path_metrics(sessions=4)
        updates: list[dict] = []
        outputs = compute_aggregation_and_bootstrap_outputs(
            path_metrics,
            n_bootstrap=11,
            seed=17,
            progress_callback=lambda **payload: updates.append(payload),
            progress_interval_seconds=0,
        )
        self.assertFalse(outputs["incremental_metrics"].empty)
        self.assertGreaterEqual(len(updates), 2)
        self.assertEqual(updates[-1]["groups_processed"], updates[-1]["groups_total"])
        self.assertEqual(updates[-1]["bootstrap_replicates_processed"], updates[-1]["bootstrap_replicates_total"])
        self.assertEqual(int(outputs["incremental_metrics"]["session_count"].min()), 4)
        self.assertTrue((outputs["incremental_metrics"]["bootstrap_grouped_by"] == "session_date").all())

    def test_aggregation_outputs_do_not_introduce_2025_or_2026(self):
        path_metrics = synthetic_bootstrap_path_metrics(sessions=3)
        outputs = compute_aggregation_and_bootstrap_outputs(path_metrics, n_bootstrap=10, seed=17)
        self.assertEqual(set(outputs["metrics_by_year"]["year"].astype(int)), {2024})
        self.assertTrue(outputs["gate"]["criteria"]["no_2025_or_2026_contamination"])

    def test_gate_passes_only_when_all_primary_criteria_pass(self):
        rows = []
        for symbol in ("QQQ", "SPY"):
            for orientation in ("continuation_short", "continuation_long"):
                for year in (2022, 2023, 2024):
                    rows.append(
                        {
                            "symbol": symbol,
                            "session_date": f"{year}-07-01",
                            "year": year,
                            "direction_orientation": orientation,
                            "horizon": "30min",
                            "event_return": 0.01,
                            "incremental_return": 0.005,
                            "baseline_cost_return": 0.0004,
                        }
                    )
        primary = pd.DataFrame(rows)
        bootstrap = pd.DataFrame(
            [
                {
                    "symbol": symbol,
                    "direction_orientation": orientation,
                    "horizon": "30min",
                    "bootstrap_ci_high": 0.02,
                }
                for symbol in ("QQQ", "SPY")
                for orientation in ("continuation_short", "continuation_long")
            ]
        )
        gate = evaluate_discovery_gate(primary, bootstrap)
        self.assertTrue(gate["passed"])
        self.assertEqual(gate["primary_horizon"], "30min")

    def test_secondary_horizons_cannot_rescue_primary_fail(self):
        paths = pd.DataFrame(
            [
                {
                    "symbol": "QQQ",
                    "session_date": "2024-07-01",
                    "year": 2024,
                    "direction_orientation": "continuation_short",
                    "horizon": "30min",
                    "event_return": -0.01,
                    "incremental_return": -0.01,
                    "baseline_cost_return": 0.0004,
                },
                {
                    "symbol": "QQQ",
                    "session_date": "2024-07-01",
                    "year": 2024,
                    "direction_orientation": "continuation_short",
                    "horizon": "60min",
                    "event_return": 0.10,
                    "incremental_return": 0.10,
                    "baseline_cost_return": 0.0004,
                },
            ]
        )
        bootstrap = pd.DataFrame([{"horizon": "30min", "bootstrap_ci_high": 0.02}])
        gate = evaluate_discovery_gate(paths, bootstrap)
        self.assertFalse(gate["passed"])
        self.assertTrue(gate["secondary_horizons_cannot_override_primary_fail"])

    def test_run_discovery_writes_exact_outputs_atomically_with_synthetic_loader(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "out"
            request = self.make_request(root)
            runtime = RuntimeState(EXECUTION_FREEZE_COMMIT, EXPECTED_FREEZE_COMMIT, EXPECTED_FREEZE_COMMIT)
            payload = run_operational_discovery(
                request,
                output_dir=output,
                runtime_state=runtime,
                dataset_loader=self.fake_loader,
                five_minute_preparer=lambda frame: frame,
                n_bootstrap=10,
                progress=ExecutionProgress(emit_console=False),
            )
            self.assertTrue(payload["results_written"])
            self.assertEqual(payload["preregistration_commit"], EXPECTED_FREEZE_COMMIT)
            self.assertEqual(payload["execution_freeze_commit"], EXECUTION_FREEZE_COMMIT)
            self.assertEqual(payload["head_commit"], EXECUTION_FREEZE_COMMIT)
            self.assertEqual({path.name for path in output.iterdir()}, set(REQUIRED_OUTPUT_FILES))
            self.assertTrue((output / "confirmed_events.csv").exists())
            self.assertTrue((output / "unconditional_control.csv").exists())
            run_manifest = json.loads((output / "run_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(run_manifest["preregistration_commit"], EXPECTED_FREEZE_COMMIT)
            self.assertEqual(run_manifest["execution_freeze_commit"], EXECUTION_FREEZE_COMMIT)

    def test_atomic_write_leaves_no_final_directory_on_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "out"
            request = self.make_request(root)
            runtime = RuntimeState(EXECUTION_FREEZE_COMMIT, EXPECTED_FREEZE_COMMIT, EXPECTED_FREEZE_COMMIT)
            with patch("src.research.hyp_or_cont_event_01_discovery._verify_required_outputs", side_effect=FileNotFoundError("missing")):
                payload = run_operational_discovery(
                    request,
                    output_dir=output,
                    runtime_state=runtime,
                    dataset_loader=self.fake_loader,
                    five_minute_preparer=lambda frame: frame,
                    n_bootstrap=10,
                    progress=ExecutionProgress(emit_console=False),
                    raise_on_error=False,
                )
            self.assertFalse(payload["results_written"])
            self.assertFalse(output.exists())

    def test_keyboard_interrupt_preserves_temp_progress_without_final_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "out"
            request = self.make_request(root)
            runtime = RuntimeState(EXECUTION_FREEZE_COMMIT, EXPECTED_FREEZE_COMMIT, EXPECTED_FREEZE_COMMIT)

            def interrupting_loader(symbol: str, csv_path: Path, manifest_path: Path):
                raise KeyboardInterrupt

            payload = run_operational_discovery(
                request,
                output_dir=output,
                runtime_state=runtime,
                dataset_loader=interrupting_loader,
                five_minute_preparer=lambda frame: frame,
                progress=ExecutionProgress(emit_console=False),
                raise_on_error=False,
            )
            self.assertTrue(payload["interrupted"])
            self.assertFalse(payload["results_written"])
            self.assertFalse(output.exists())
            temp_dirs = list(root.glob(".out.tmp-*"))
            self.assertEqual(len(temp_dirs), 1)
            progress_payload = json.loads((temp_dirs[0] / "execution_progress.json").read_text(encoding="utf-8"))
            self.assertTrue(any(stage.get("interrupted") for stage in progress_payload["stages"]))

    def test_keyboard_interrupt_during_bootstrap_preserves_progress_without_final_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "out"
            request = self.make_request(root)
            runtime = RuntimeState(EXECUTION_FREEZE_COMMIT, EXPECTED_FREEZE_COMMIT, EXPECTED_FREEZE_COMMIT)
            with patch(
                "src.research.hyp_or_cont_event_01_discovery.compute_aggregation_and_bootstrap_outputs",
                side_effect=KeyboardInterrupt,
            ):
                payload = run_operational_discovery(
                    request,
                    output_dir=output,
                    runtime_state=runtime,
                    dataset_loader=self.fake_loader,
                    five_minute_preparer=lambda frame: frame,
                    n_bootstrap=10,
                    progress=ExecutionProgress(emit_console=False),
                    raise_on_error=False,
                )
            self.assertTrue(payload["interrupted"])
            self.assertFalse(payload["results_written"])
            self.assertFalse(output.exists())
            temp_dirs = list(root.glob(".out.tmp-*"))
            self.assertEqual(len(temp_dirs), 1)
            progress_payload = json.loads((temp_dirs[0] / "execution_progress.json").read_text(encoding="utf-8"))
            self.assertTrue(any(stage.get("stage") == "aggregations_and_bootstrap" for stage in progress_payload["stages"]))
            self.assertTrue(any(stage.get("interrupted") for stage in progress_payload["stages"]))

    def test_preflight_failure_happens_before_dataset_load_and_final_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "out"
            request = self.make_request(root)
            runtime = RuntimeState("0" * 40, EXPECTED_FREEZE_COMMIT, EXPECTED_FREEZE_COMMIT)
            loader_called = False

            def blocked_loader(symbol: str, csv_path: Path, manifest_path: Path):
                nonlocal loader_called
                loader_called = True
                return self.fake_loader(symbol, csv_path, manifest_path)

            payload = run_operational_discovery(
                request,
                output_dir=output,
                runtime_state=runtime,
                dataset_loader=blocked_loader,
                five_minute_preparer=lambda frame: frame,
                progress=ExecutionProgress(emit_console=False),
                raise_on_error=False,
            )
            self.assertIn("Execution freeze commit mismatch", payload["error"])
            self.assertFalse(loader_called)
            self.assertFalse(output.exists())

    def test_existing_final_output_blocks_before_dataset_load(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "out"
            output.mkdir()
            (output / "sentinel.txt").write_text("existing", encoding="utf-8")
            request = self.make_request(root)
            runtime = RuntimeState(EXECUTION_FREEZE_COMMIT, EXPECTED_FREEZE_COMMIT, EXPECTED_FREEZE_COMMIT)
            loader_called = False

            def blocked_loader(symbol: str, csv_path: Path, manifest_path: Path):
                nonlocal loader_called
                loader_called = True
                return self.fake_loader(symbol, csv_path, manifest_path)

            payload = run_operational_discovery(
                request,
                output_dir=output,
                runtime_state=runtime,
                dataset_loader=blocked_loader,
                five_minute_preparer=lambda frame: frame,
                progress=ExecutionProgress(emit_console=False),
                raise_on_error=False,
            )
            self.assertIn("Output directory already exists", payload["error"])
            self.assertFalse(loader_called)
            self.assertTrue((output / "sentinel.txt").exists())

    def test_runner_outputs_do_not_contain_strategy_columns(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "out"
            request = self.make_request(root)
            runtime = RuntimeState(EXECUTION_FREEZE_COMMIT, EXPECTED_FREEZE_COMMIT, EXPECTED_FREEZE_COMMIT)
            run_operational_discovery(
                request,
                output_dir=output,
                runtime_state=runtime,
                dataset_loader=self.fake_loader,
                five_minute_preparer=lambda frame: frame,
                n_bootstrap=10,
                progress=ExecutionProgress(emit_console=False),
            )
            text = "\n".join(path.read_text(encoding="utf-8").lower() for path in output.glob("*.csv"))
            self.assertNotIn("entry_price", text)
            self.assertNotIn("stop", text)
            self.assertNotIn("target", text)
            self.assertNotIn("quantity", text)

    def test_cost_thresholds_are_price_dependent(self):
        paths = pd.DataFrame(
            [
                {"executable_price_reference": 100.0, "event_return": 0.01},
                {"executable_price_reference": 200.0, "event_return": 0.01},
            ]
        )
        enriched = attach_cost_thresholds(paths)
        self.assertGreater(enriched.iloc[0]["baseline_cost_return"], enriched.iloc[1]["baseline_cost_return"])

    def read_artifact_csv(self, name: str) -> list[dict]:
        with (DISCOVERY_ARTIFACT_DIR / name).open(newline="", encoding="utf-8") as handle:
            return list(csv.DictReader(handle))

    def test_frozen_discovery_artifacts_close_as_failed_without_future_contamination(self):
        expected_files = {
            "run_manifest.json",
            "dataset_manifest_snapshot.json",
            "config_snapshot.yaml",
            "confirmed_events.csv",
            "path_metrics.csv",
            "unconditional_control.csv",
            "incremental_metrics.csv",
            "metrics_by_symbol.csv",
            "metrics_by_year.csv",
            "bootstrap_intervals.csv",
            "cost_threshold_comparison.csv",
            "discovery_gate.json",
            "execution_progress.json",
            "checksums.json",
        }
        self.assertTrue(DISCOVERY_ARTIFACT_DIR.exists())
        self.assertEqual({path.name for path in DISCOVERY_ARTIFACT_DIR.iterdir()}, expected_files)

        run_manifest = json.loads((DISCOVERY_ARTIFACT_DIR / "run_manifest.json").read_text(encoding="utf-8"))
        gate = json.loads((DISCOVERY_ARTIFACT_DIR / "discovery_gate.json").read_text(encoding="utf-8"))
        events = self.read_artifact_csv("confirmed_events.csv")
        path_metrics = self.read_artifact_csv("path_metrics.csv")

        self.assertEqual(len(events), 1496)
        self.assertEqual(len(path_metrics), 5967)
        self.assertEqual({row["symbol"] for row in events}, {"QQQ", "SPY"})
        self.assertEqual({row["symbol"] for row in path_metrics}, {"QQQ", "SPY"})
        self.assertEqual(min(row["session_date"] for row in events), "2022-01-03")
        self.assertEqual(max(row["session_date"] for row in events), "2024-12-31")
        self.assertEqual({row["year"] for row in path_metrics}, {"2022", "2023", "2024"})
        self.assertEqual(run_manifest["requested_start"], "2022-01-01")
        self.assertEqual(run_manifest["requested_end"], "2024-12-31")
        self.assertEqual(run_manifest["primary_horizon"], "30min")
        self.assertTrue(run_manifest["results_written"])
        self.assertFalse(run_manifest["strategy_created"])
        self.assertFalse(run_manifest["validation_2025_executed"])
        self.assertFalse(run_manifest["historical_2026_executed"])
        self.assertFalse(run_manifest["orders_created"])
        self.assertFalse(run_manifest["position_sizing_used"])
        self.assertFalse(any(run_manifest["safety_flags"].values()))

        self.assertEqual(run_manifest["preregistration_commit"], EXPECTED_FREEZE_COMMIT)
        self.assertEqual(run_manifest["execution_freeze_commit"], "ec8803fae45ec7f07f338350e6d77b80ec6a8929")
        self.assertEqual(run_manifest["canonical_payload_hash"], EXPECTED_CANONICAL_HASH)
        self.assertEqual(gate["classification"], "discovery_failed")
        self.assertFalse(gate["passed"])
        self.assertEqual(gate["primary_horizon"], "30min")
        self.assertFalse(gate["validation_2025_unlocked"])
        self.assertFalse(gate["paper_eligible"])
        self.assertFalse(gate["live_eligible"])
        self.assertTrue(gate["secondary_horizons_cannot_override_primary_fail"])
        self.assertTrue(gate["criteria"]["no_2025_or_2026_contamination"])

    def test_primary_results_fail_costs_and_do_not_promote_short(self):
        primary_metrics = [
            row for row in self.read_artifact_csv("incremental_metrics.csv") if row["horizon"] == "30min"
        ]
        cost_rows = [row for row in self.read_artifact_csv("cost_threshold_comparison.csv") if row["horizon"] == "30min"]
        bootstrap_rows = [row for row in self.read_artifact_csv("bootstrap_intervals.csv") if row["horizon"] == "30min"]

        self.assertEqual(len(primary_metrics), 4)
        self.assertTrue(all(row["baseline_cost_passed"] == "False" for row in cost_rows))
        self.assertTrue(all(row["stress_cost_passed"] == "False" for row in cost_rows))
        self.assertTrue(all(float(row["bootstrap_ci_low"]) < 0 < float(row["bootstrap_ci_high"]) for row in bootstrap_rows))

        by_key = {(row["symbol"], row["direction_orientation"]): row for row in primary_metrics}
        self.assertLess(float(by_key[("QQQ", "continuation_long")]["mean"]), 0)
        self.assertGreater(float(by_key[("SPY", "continuation_long")]["mean"]), 0)
        self.assertGreater(float(by_key[("QQQ", "continuation_short")]["mean"]), 0)
        self.assertGreater(float(by_key[("SPY", "continuation_short")]["mean"]), 0)
        self.assertLess(
            float(by_key[("QQQ", "continuation_short")]["mean"]),
            float(by_key[("QQQ", "continuation_short")]["mean_baseline_cost_return"]),
        )
        self.assertLess(
            float(by_key[("SPY", "continuation_short")]["mean"]),
            float(by_key[("SPY", "continuation_short")]["mean_baseline_cost_return"]),
        )

    def test_discovery_report_and_registry_preserve_closure_controls(self):
        report = DISCOVERY_RESULTS_DOC.read_text(encoding="utf-8")
        registry = RESEARCH_REGISTRY_PATH.read_text(encoding="utf-8")
        combined = report + "\n" + registry

        self.assertIn("discovery_failed", report)
        self.assertIn("causal_post_confirmation_continuation_failed", registry)
        self.assertIn("Primary horizon `30min`", registry)
        self.assertIn("validation_2025_unlocked=false", registry)
        self.assertIn("paper/live/strategy all false", registry)
        self.assertIn(EXPECTED_FREEZE_COMMIT, combined)
        self.assertIn("ec8803fae45ec7f07f338350e6d77b80ec6a8929", combined)
        self.assertIn(EXPECTED_CANONICAL_HASH, combined)
        self.assertIn("Secondary horizons cannot override a primary-horizon fail.", report)
        self.assertIn("not a new strategy and not a new approved hypothesis", report)
        self.assertIn("No `HYP-OR-CONT-SHORT-02` may be created", registry)
        self.assertIn("2025 remains closed. 2026 was not executed.", report)


if __name__ == "__main__":
    unittest.main()
