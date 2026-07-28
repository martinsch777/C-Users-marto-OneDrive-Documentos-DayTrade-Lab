from __future__ import annotations

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
    assert_no_strategy_columns,
    attach_cost_thresholds,
    attach_incremental_returns,
    compute_unconditional_control,
    compute_or_continuation_paths,
    detect_or_continuation_events,
    evaluate_discovery_gate,
    frozen_cost_profiles,
    round_trip_cost_return,
    validate_or_cont_period,
)


CONFIG_PATH = Path("configs/research/hypotheses/HYP-OR-CONT-EVENT-01.yaml")
EXECUTION_FREEZE_COMMIT = "f" * 40


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


if __name__ == "__main__":
    unittest.main()
