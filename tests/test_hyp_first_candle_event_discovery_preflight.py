from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import pandas as pd
import yaml

from src.research.hyp_first_candle_event_discovery import (
    DISCOVERY_END,
    DISCOVERY_START,
    ALLOWED_CLASSIFICATIONS,
    EXPECTED_SYMBOLS,
    REQUIRED_OUTPUT_FILES,
    ExecutionProgress,
    FcrEventDiscoveryRequest,
    RuntimeState,
    filter_discovery_analytic_frame,
    prepare_only_manifest,
    run_profile_synthetic,
    run_operational_discovery,
    validate_discovery_preflight,
)
from src.research.hyp_first_candle_event_study import EVENT_TYPES, FcrEventStudyConfig, canonical_event_config_hash


HEAD = "0" * 40
OTHER_HEAD = "1" * 40


def write_config(path: Path, *, symbols: tuple[str, ...] = EXPECTED_SYMBOLS) -> str:
    payload = {
        "schema_version": 1,
        "hypothesis_id": "HYP-FCR-EVENT-01",
        "type": "event_study",
        "strategy_status": "non_strategy",
        "symbols": list(symbols),
        "periods": {
            "discovery_2022_2024": {
                "start": DISCOVERY_START,
                "end": DISCOVERY_END,
                "status": "preregistered_prepare_only_not_executed",
            },
            "validation_2025": {
                "start": "2025-01-01",
                "end": "2025-12-31",
                "status": "blocked_not_opened",
            },
            "parity_debug_2026": {
                "start": "2026-01-01",
                "end": "2026-12-31",
                "status": "blocked_not_opened",
            },
        },
        "event_constraints": {
            "no_entries": True,
            "no_exits": True,
            "no_stops": True,
            "no_targets": True,
            "no_position_sizing": True,
            "no_pnl": True,
        },
        "safety_flags": {
            "live_trading": False,
            "broker_connected": False,
            "orders_sent": False,
            "paper_broker_enabled": False,
        },
    }
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return canonical_event_config_hash(path)


def write_manifest(
    path: Path,
    *,
    symbol: str,
    status: str = "approved_for_or_fvg_backtest",
    excluded_sessions: list[dict] | None = None,
    curated_file: str | None = None,
) -> None:
    excluded_sessions = excluded_sessions or []
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
        "first_timestamp": "2022-01-03 09:30:00-05:00",
        "last_timestamp": "2026-07-06 15:59:00-04:00",
        "input_file": curated_file or f"data/curated/{symbol}_synthetic_curated.csv",
        "output_file": curated_file or f"data/curated/{symbol}_synthetic_curated.csv",
        "curated_file": curated_file or f"data/curated/{symbol}_synthetic_curated.csv",
        "sha256": symbol.lower() * 16,
        "calendar_source": "builtin_us_equity_calendar_v1",
        "calendar_loaded": True,
        "calendar_holidays_loaded": 1,
        "calendar_early_closes_loaded": 1,
        "audit_apt_for_or_fvg_backtest": status == "approved_for_or_fvg_backtest",
        "audit_critical_warnings": [] if status == "approved_for_or_fvg_backtest" else ["MISSING_RTH_BARS"],
        "audit_warnings": [],
        "dataset_status": status,
        "total_excluded_sessions": len(excluded_sessions),
        "excluded_sessions": excluded_sessions,
        "broker_connected": False,
        "orders_sent": False,
        "live_trading_enabled": False,
        "paper_broker_enabled": False,
        "project_safety_state": {
            "broker_connected": False,
            "live_trading": False,
            "orders_sent": False,
        },
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def write_failed_spy_annual(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "symbol": "SPY",
                "timeframe": "1min",
                "dataset_status": "failed_audit",
                "audit_apt_for_or_fvg_backtest": False,
            }
        ),
        encoding="utf-8",
    )


class HypFirstCandleEventDiscoveryPreflightTests(unittest.TestCase):
    def make_request(self, root: Path, **overrides) -> FcrEventDiscoveryRequest:
        config = root / "HYP-FCR-EVENT-01.yaml"
        canonical_hash = write_config(config)
        spy_exclusion = {
            "symbol": "SPY",
            "date": "2023-06-05",
            "policy": "exclude_entire_session",
            "reason": "MISSING_RTH_BARS_FROM_PROVIDER",
        }
        qqq_manifest = root / "QQQ_1min_2022-01-01_2026-07-06_curated_manifest.json"
        spy_manifest = root / "SPY_1min_2022-01-01_2026-07-06_curated_manifest.json"
        spy_annual = root / "SPY_1min_2023-01-01_2023-12-31_alpaca_sip_raw_rth_manifest.json"
        write_manifest(qqq_manifest, symbol="QQQ")
        write_manifest(spy_manifest, symbol="SPY", excluded_sessions=[spy_exclusion])
        write_failed_spy_annual(spy_annual)
        values = {
            "mode": "run_discovery",
            "expected_freeze_commit": HEAD,
            "expected_canonical_hash": canonical_hash,
            "preregistered_canonical_hash": canonical_hash,
            "config_path": config,
            "manifest_paths": {"QQQ": qqq_manifest, "SPY": spy_manifest},
            "spy_failed_annual_manifest_path": spy_annual,
        }
        values.update(overrides)
        return FcrEventDiscoveryRequest(**values)

    def test_01_default_prepare_only(self):
        self.assertEqual(FcrEventDiscoveryRequest().mode, "prepare_only")
        payload = prepare_only_manifest()
        self.assertFalse(payload["event_study_executed"])
        self.assertFalse(payload["results_written"])

    def test_02_run_discovery_requires_expected_freeze_commit(self):
        with tempfile.TemporaryDirectory() as directory:
            request = self.make_request(Path(directory), expected_freeze_commit="")
            with self.assertRaises(PermissionError):
                validate_discovery_preflight(request, runtime_state=RuntimeState(HEAD, True))

    def test_03_rejects_freeze_commit_placeholder(self):
        with tempfile.TemporaryDirectory() as directory:
            request = self.make_request(Path(directory), expected_freeze_commit="<EVENT_FREEZE_COMMIT>")
            with self.assertRaises(PermissionError):
                validate_discovery_preflight(request, runtime_state=RuntimeState(HEAD, True))

    def test_04_rejects_non_full_freeze_commit(self):
        with tempfile.TemporaryDirectory() as directory:
            request = self.make_request(Path(directory), expected_freeze_commit="abc")
            with self.assertRaises(PermissionError):
                validate_discovery_preflight(request, runtime_state=RuntimeState(HEAD, True))

    def test_05_rejects_commit_distinct_from_head(self):
        with tempfile.TemporaryDirectory() as directory:
            request = self.make_request(Path(directory), expected_freeze_commit=OTHER_HEAD)
            with self.assertRaises(PermissionError):
                validate_discovery_preflight(request, runtime_state=RuntimeState(HEAD, True))

    def test_06_rejects_dirty_working_tree(self):
        with tempfile.TemporaryDirectory() as directory:
            request = self.make_request(Path(directory))
            with self.assertRaises(PermissionError):
                validate_discovery_preflight(request, runtime_state=RuntimeState(HEAD, False))

    def test_07_rejects_wrong_canonical_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            request = self.make_request(Path(directory), expected_canonical_hash="f" * 64)
            with self.assertRaises(PermissionError):
                validate_discovery_preflight(request, runtime_state=RuntimeState(HEAD, True))

    def test_08_accepts_correct_canonical_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            request = self.make_request(Path(directory))
            payload = validate_discovery_preflight(request, runtime_state=RuntimeState(HEAD, True))
            self.assertTrue(payload["preflight_passed"])

    def test_09_rejects_2025_period(self):
        with tempfile.TemporaryDirectory() as directory:
            request = self.make_request(Path(directory), period="validation_2025")
            with self.assertRaises(PermissionError):
                validate_discovery_preflight(request, runtime_state=RuntimeState(HEAD, True))

    def test_10_rejects_2026_period(self):
        with tempfile.TemporaryDirectory() as directory:
            request = self.make_request(Path(directory), period="parity_debug_2026")
            with self.assertRaises(PermissionError):
                validate_discovery_preflight(request, runtime_state=RuntimeState(HEAD, True))

    def test_11_rejects_holdout(self):
        with tempfile.TemporaryDirectory() as directory:
            request = self.make_request(Path(directory), period="holdout")
            with self.assertRaises(PermissionError):
                validate_discovery_preflight(request, runtime_state=RuntimeState(HEAD, True))

    def test_12_rejects_other_symbols(self):
        with tempfile.TemporaryDirectory() as directory:
            request = self.make_request(Path(directory), symbols=("QQQ", "SPY", "IWM"))
            with self.assertRaises(PermissionError):
                validate_discovery_preflight(request, runtime_state=RuntimeState(HEAD, True))

    def test_13_requires_exact_discovery_range(self):
        with tempfile.TemporaryDirectory() as directory:
            request = self.make_request(Path(directory), requested_end="2025-01-01")
            with self.assertRaises(PermissionError):
                validate_discovery_preflight(request, runtime_state=RuntimeState(HEAD, True))

    def test_14_rejects_unapproved_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request = self.make_request(root)
            write_manifest(request.manifest_paths["QQQ"], symbol="QQQ", status="failed_audit")
            with self.assertRaises(PermissionError):
                validate_discovery_preflight(request, runtime_state=RuntimeState(HEAD, True))

    def test_15_accepts_curated_consolidated_approved_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            request = self.make_request(Path(directory))
            payload = validate_discovery_preflight(request, runtime_state=RuntimeState(HEAD, True))
            self.assertEqual(payload["manifest_summary"]["QQQ"]["dataset_status"], "approved_for_or_fvg_backtest")
            self.assertEqual(payload["manifest_summary"]["SPY"]["dataset_status"], "approved_for_or_fvg_backtest")

    def test_16_respects_spy_2023_06_05_exclusion(self):
        with tempfile.TemporaryDirectory() as directory:
            request = self.make_request(Path(directory))
            payload = validate_discovery_preflight(request, runtime_state=RuntimeState(HEAD, True))
            excluded = payload["manifest_summary"]["SPY"]["excluded_sessions"]
            self.assertEqual(excluded[0]["date"], "2023-06-05")

    def test_17_does_not_use_failed_annual_raw_manifest_as_final_dataset(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request = self.make_request(root)
            failed_final = root / "SPY_1min_2023-01-01_2023-12-31_alpaca_sip_raw_rth_manifest.json"
            request = FcrEventDiscoveryRequest(
                mode=request.mode,
                expected_freeze_commit=request.expected_freeze_commit,
                expected_canonical_hash=request.expected_canonical_hash,
                preregistered_canonical_hash=request.preregistered_canonical_hash,
                config_path=request.config_path,
                manifest_paths={"QQQ": request.manifest_paths["QQQ"], "SPY": failed_final},
                spy_failed_annual_manifest_path=failed_final,
            )
            with self.assertRaises(PermissionError):
                validate_discovery_preflight(request, runtime_state=RuntimeState(HEAD, True))

    def test_18_preflight_does_not_require_ohlc_files_to_exist(self):
        with tempfile.TemporaryDirectory() as directory:
            request = self.make_request(Path(directory))
            payload = validate_discovery_preflight(request, runtime_state=RuntimeState(HEAD, True))
            self.assertTrue(payload["preflight_passed"])

    def test_19_absence_of_orders(self):
        with tempfile.TemporaryDirectory() as directory:
            request = self.make_request(Path(directory))
            payload = validate_discovery_preflight(request, runtime_state=RuntimeState(HEAD, True))
            self.assertFalse(payload["orders_sent"])

    def test_20_absence_of_position_sizing(self):
        with tempfile.TemporaryDirectory() as directory:
            request = self.make_request(Path(directory))
            payload = validate_discovery_preflight(request, runtime_state=RuntimeState(HEAD, True))
            self.assertFalse(payload["position_sizing_used"])

    def test_21_preflight_is_deterministic(self):
        with tempfile.TemporaryDirectory() as directory:
            request = self.make_request(Path(directory))
            first = validate_discovery_preflight(request, runtime_state=RuntimeState(HEAD, True))
            second = validate_discovery_preflight(request, runtime_state=RuntimeState(HEAD, True))
            self.assertEqual(first, second)

    def test_22_prepare_only_creates_no_result_artifact_payload(self):
        payload = prepare_only_manifest()
        self.assertNotIn("events_csv", payload)
        self.assertNotIn("path_metrics_csv", payload)
        self.assertFalse(payload["results_written"])

    def fake_loader(self, symbol: str, csv_path: Path, manifest_path: Path):
        timestamps = [
            "2024-07-01 09:30",
            "2024-07-01 10:00",
            "2025-01-02 10:00",
            "2026-01-02 10:00",
        ]
        if symbol == "SPY":
            timestamps.append("2023-06-05 10:00")
        rows = [
            {
                "timestamp": pd.Timestamp(value, tz="America/New_York").tz_convert("UTC"),
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.0,
                "volume": 1000,
            }
            for value in timestamps
            if not (symbol == "SPY" and value.startswith("2023-06-05"))
        ]
        manifest = {
            "symbol": symbol,
            "sha256": f"{symbol.lower()}-sha",
            "excluded_sessions": [
                {"symbol": "SPY", "date": "2023-06-05", "policy": "exclude_entire_session"}
            ]
            if symbol == "SPY"
            else [],
        }
        return pd.DataFrame(rows), manifest

    def fake_prepare(self, frame: pd.DataFrame) -> pd.DataFrame:
        local_dates = pd.to_datetime(frame["timestamp"], utc=True).dt.tz_convert("America/New_York").dt.date
        self.assertFalse(any(item.year >= 2025 for item in local_dates))
        self.assertNotIn("2023-06-05", {str(item) for item in local_dates})
        return frame

    def fake_events(self, five_minute: pd.DataFrame, symbol: str, config: FcrEventStudyConfig):
        base_time = pd.Timestamp("2024-07-01 10:00", tz="America/New_York").tz_convert("UTC")
        return pd.DataFrame(
            [
                {
                    "hypothesis_id": "HYP-FCR-EVENT-01",
                    "symbol": symbol,
                    "session_date": "2024-07-01",
                    "event_type": event_type,
                    "event_side": "low" if index % 2 else "high",
                    "event_time": base_time + pd.Timedelta(int(index), unit="min"),
                    "event_price": 100.0,
                    "opening_high": 101.0,
                    "opening_low": 99.0,
                    "opening_midpoint": 100.0,
                    "year": 2024,
                }
                for index, event_type in enumerate(EVENT_TYPES)
            ]
        )

    def fake_paths(self, five_minute: pd.DataFrame, events: pd.DataFrame, config: FcrEventStudyConfig, *, horizons=None):
        rows = []
        for _, event in events.iterrows():
            for horizon in horizons or config.horizons:
                rows.append(
                    {
                        "hypothesis_id": "HYP-FCR-EVENT-01",
                        "symbol": event["symbol"],
                        "session_date": event["session_date"],
                        "year": int(event["year"]),
                        "event_type": event["event_type"],
                        "event_side": event["event_side"],
                        "orientation": "long_reversal" if event["event_side"] == "low" else "short_reversal",
                        "event_time": event["event_time"],
                        "horizon": horizon,
                        "event_price": 100.0,
                        "availability_status": "available",
                        "future_close": 101.0,
                        "horizon_close": 101.0,
                        "raw_return": 0.01,
                        "future_return": 0.01,
                        "reversal_return": 0.01,
                        "continuation_return": -0.01,
                        "maximum_favorable_excursion": 0.02,
                        "MFE": 0.02,
                        "maximum_adverse_excursion": -0.005,
                        "MAE": -0.005,
                        "time_to_mfe": event["event_time"],
                        "time_to_MFE": event["event_time"],
                        "time_to_mae": event["event_time"],
                        "time_to_MAE": event["event_time"],
                        "path_high": 102.0,
                        "path_low": 99.5,
                        "returned_to_or_center": True,
                        "return_to_OR_midpoint": True,
                        "reached_opposite_or_extreme": False,
                        "reached_opposite_OR_extreme": False,
                        "broke_same_or_extreme": False,
                        "rebreak_same_extreme": False,
                        "bars_in_path": 1,
                    }
                )
        return pd.DataFrame(rows)

    def run_synthetic_discovery(self, root: Path, output: Path):
        request = self.make_request(root)
        with patch("src.research.hyp_first_candle_event_discovery.prepare_five_minute_frame", self.fake_prepare), patch(
            "src.research.hyp_first_candle_event_discovery.detect_fcr_event_study_events", self.fake_events
        ), patch("src.research.hyp_first_candle_event_discovery.compute_fcr_event_paths", self.fake_paths):
            return run_operational_discovery(
                request,
                output_dir=output,
                runtime_state=RuntimeState(HEAD, True),
                dataset_loader=self.fake_loader,
                n_bootstrap=10,
                progress=ExecutionProgress(emit_console=False),
            )

    def test_23_run_discovery_calls_engine_only_after_preflight_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request = self.make_request(root)
            executor = Mock(return_value={"results_written": True, "output_dir": str(root / "out"), "required_outputs": [], "event_count": 0, "path_metric_rows": 0})
            with patch("src.research.hyp_first_candle_event_discovery._execute_event_study_outputs", executor):
                payload = run_operational_discovery(request, output_dir=root / "out", runtime_state=RuntimeState(HEAD, True), progress=ExecutionProgress(emit_console=False))
            self.assertTrue(payload["event_study_executed"])
            executor.assert_called_once()

    def test_24_preflight_fail_prevents_data_read(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request = self.make_request(root, expected_freeze_commit=OTHER_HEAD)
            loader = Mock(side_effect=AssertionError("data loader must not run"))
            with self.assertRaises(PermissionError):
                run_operational_discovery(request, output_dir=root / "out", runtime_state=RuntimeState(HEAD, True), dataset_loader=loader, progress=ExecutionProgress(emit_console=False))
            loader.assert_not_called()

    def test_25_prepare_only_never_calls_engine(self):
        executor = Mock(side_effect=AssertionError("engine must not run"))
        with patch("src.research.hyp_first_candle_event_discovery._execute_event_study_outputs", executor):
            payload = run_operational_discovery(FcrEventDiscoveryRequest(), runtime_state=RuntimeState(HEAD, True), progress=ExecutionProgress(emit_console=False))
        self.assertFalse(payload["event_study_executed"])
        executor.assert_not_called()

    def test_26_run_discovery_success_marks_executed_and_written(self):
        with tempfile.TemporaryDirectory() as directory:
            payload = self.run_synthetic_discovery(Path(directory), Path(directory) / "out")
            self.assertTrue(payload["event_study_executed"])
            self.assertTrue(payload["results_written"])

    def test_27_results_written_requires_verified_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request = self.make_request(root)
            with patch("src.research.hyp_first_candle_event_discovery._verify_required_outputs", side_effect=FileNotFoundError("missing")):
                payload = run_operational_discovery(
                    request,
                    output_dir=root / "out",
                    runtime_state=RuntimeState(HEAD, True),
                    dataset_loader=self.fake_loader,
                    raise_on_error=False,
                    progress=ExecutionProgress(emit_console=False),
                )
            self.assertTrue(payload["event_study_executed"])
            self.assertFalse(payload["results_written"])

    def test_28_error_during_study_leaves_results_written_false(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request = self.make_request(root)
            with patch("src.research.hyp_first_candle_event_discovery._execute_event_study_outputs", side_effect=RuntimeError("boom")):
                payload = run_operational_discovery(
                    request,
                    output_dir=root / "out",
                    runtime_state=RuntimeState(HEAD, True),
                    raise_on_error=False,
                    progress=ExecutionProgress(emit_console=False),
                )
            self.assertFalse(payload["results_written"])

    def test_29_no_final_partial_artifacts_after_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request = self.make_request(root)
            with patch("src.research.hyp_first_candle_event_discovery._verify_required_outputs", side_effect=FileNotFoundError("missing")):
                run_operational_discovery(
                    request,
                    output_dir=root / "out",
                    runtime_state=RuntimeState(HEAD, True),
                    dataset_loader=self.fake_loader,
                    raise_on_error=False,
                    progress=ExecutionProgress(emit_console=False),
                )
            self.assertFalse((root / "out").exists())

    def test_30_strict_crop_excludes_2025_and_2026(self):
        data, _ = self.fake_loader("QQQ", Path("QQQ.csv"), Path("manifest.json"))
        filtered = filter_discovery_analytic_frame(data, "QQQ")
        years = set(pd.to_datetime(filtered["timestamp"], utc=True).dt.tz_convert("America/New_York").dt.year)
        self.assertEqual(years, {2024})

    def test_31_spy_excluded_session_is_not_allowed_in_analytic_frame(self):
        data = pd.DataFrame(
            [
                {
                    "timestamp": pd.Timestamp("2023-06-05 10:00", tz="America/New_York").tz_convert("UTC"),
                    "open": 1,
                    "high": 1,
                    "low": 1,
                    "close": 1,
                    "volume": 1,
                }
            ]
        )
        with self.assertRaises(AssertionError):
            filter_discovery_analytic_frame(data, "SPY")

    def test_32_exactly_ten_event_types_are_recorded(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.run_synthetic_discovery(root, root / "out")
            manifest = json.loads((root / "out" / "run_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(tuple(manifest["event_types_executed"]), EVENT_TYPES)

    def test_33_exact_preregistered_horizons_are_recorded(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.run_synthetic_discovery(root, root / "out")
            manifest = json.loads((root / "out" / "run_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(tuple(manifest["horizons"]), ("5min", "15min", "30min", "60min", "session_close"))

    def test_34_outputs_have_no_orders(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.run_synthetic_discovery(root, root / "out")
            text = (root / "out" / "events.csv").read_text(encoding="utf-8") + (root / "out" / "path_metrics.csv").read_text(encoding="utf-8")
            self.assertNotIn("order", text.lower())

    def test_35_outputs_have_no_position_sizing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.run_synthetic_discovery(root, root / "out")
            text = "\n".join(path.read_text(encoding="utf-8") for path in (root / "out").glob("*.csv"))
            self.assertNotIn("position_size", text)
            self.assertNotIn("quantity", text)

    def test_36_discovery_module_does_not_import_brokers(self):
        import ast

        tree = ast.parse(Path("src/research/hyp_first_candle_event_discovery.py").read_text(encoding="utf-8"))
        imported_modules = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_modules.extend(alias.name.lower() for alias in node.names)
            if isinstance(node, ast.ImportFrom) and node.module:
                imported_modules.append(node.module.lower())
        self.assertFalse(any("alpaca" in module or "bybit" in module for module in imported_modules))

    def test_37_classifications_are_limited_to_allowed_set(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.run_synthetic_discovery(root, root / "out")
            payload = json.loads((root / "out" / "classification.json").read_text(encoding="utf-8"))
            self.assertIn(payload["classification"], ALLOWED_CLASSIFICATIONS)

    def test_38_bootstrap_is_grouped_by_session(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.run_synthetic_discovery(root, root / "out")
            intervals = pd.read_csv(root / "out" / "bootstrap_intervals.csv")
            self.assertEqual(set(intervals["bootstrap_grouped_by"]), {"session_date"})

    def test_39_checksums_are_deterministic(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.run_synthetic_discovery(root, root / "out1")
            self.run_synthetic_discovery(root, root / "out2")
            first = json.loads((root / "out1" / "checksums.json").read_text(encoding="utf-8"))
            second = json.loads((root / "out2" / "checksums.json").read_text(encoding="utf-8"))
            self.assertEqual(first, second)

    def test_40_results_are_reproducible_with_same_seed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.run_synthetic_discovery(root, root / "out1")
            self.run_synthetic_discovery(root, root / "out2")
            first = (root / "out1" / "aggregate_metrics.csv").read_text(encoding="utf-8")
            second = (root / "out2" / "aggregate_metrics.csv").read_text(encoding="utf-8")
            self.assertEqual(first, second)

    def test_41_registry_is_not_modified_if_execution_fails(self):
        registry = Path("docs/RESEARCH_HYPOTHESIS_REGISTRY.md")
        before = registry.read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request = self.make_request(root)
            with patch("src.research.hyp_first_candle_event_discovery._execute_event_study_outputs", side_effect=RuntimeError("boom")):
                run_operational_discovery(request, output_dir=root / "out", runtime_state=RuntimeState(HEAD, True), raise_on_error=False, progress=ExecutionProgress(emit_console=False))
        self.assertEqual(registry.read_text(encoding="utf-8"), before)

    def test_42_prepare_only_generates_no_results_document(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_operational_discovery(FcrEventDiscoveryRequest(), output_dir=root / "out", runtime_state=RuntimeState(HEAD, True), progress=ExecutionProgress(emit_console=False))
            self.assertFalse((root / "out").exists())

    def test_43_successful_run_writes_exact_required_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.run_synthetic_discovery(root, root / "out")
            self.assertEqual({path.name for path in (root / "out").iterdir()}, set(REQUIRED_OUTPUT_FILES))

    def test_44_execution_progress_is_persisted_as_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.run_synthetic_discovery(root, root / "out")
            progress = json.loads((root / "out" / "execution_progress.json").read_text(encoding="utf-8"))
            stages = {item["stage"] for item in progress["stages"]}
            self.assertIn("preflight", stages)
            self.assertIn("path_metrics", stages)
            self.assertIn("bootstrap", stages)
            self.assertTrue(all("elapsed_seconds" in item for item in progress["stages"]))

    def test_45_profile_synthetic_reads_no_real_ohlc(self):
        payload = run_profile_synthetic(base_sessions=2, n_bootstrap=20, progress=ExecutionProgress(emit_console=False))
        self.assertTrue(payload["synthetic_only"])
        self.assertFalse(payload["real_ohlc_read"])
        self.assertGreater(payload["first"]["events"], 0)
        self.assertLess(payload["growth_when_doubling_sessions"]["path_metrics_seconds"], 10)

    def test_46_benchmark_subset_requires_session_cap(self):
        with tempfile.TemporaryDirectory() as directory:
            request = self.make_request(Path(directory), mode="benchmark_subset", max_sessions_per_symbol=None)
            with self.assertRaises(PermissionError):
                validate_discovery_preflight(request, runtime_state=RuntimeState(HEAD, True))

    def test_47_benchmark_subset_writes_only_diagnostic_temp_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request = self.make_request(root, mode="benchmark_subset", max_sessions_per_symbol=2)
            with patch("src.research.hyp_first_candle_event_discovery.prepare_five_minute_frame", self.fake_prepare), patch(
                "src.research.hyp_first_candle_event_discovery.detect_fcr_event_study_events", self.fake_events
            ), patch("src.research.hyp_first_candle_event_discovery.compute_fcr_event_paths", self.fake_paths):
                payload = run_operational_discovery(
                    request,
                    output_dir=root / "out",
                    runtime_state=RuntimeState(HEAD, True),
                    dataset_loader=self.fake_loader,
                    n_bootstrap=10,
                    progress=ExecutionProgress(emit_console=False),
                )
            diagnostic_dir = Path(payload["diagnostic_dir"])
            self.assertTrue(payload["benchmark_only"])
            self.assertFalse(payload["results_written"])
            self.assertFalse((root / "out").exists())
            self.assertTrue((diagnostic_dir / "benchmark_manifest.json").exists())
            self.assertTrue((diagnostic_dir / "execution_progress.json").exists())
            self.assertFalse((diagnostic_dir / "classification.json").exists())

    def test_48_keyboard_interrupt_leaves_results_unwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request = self.make_request(root)
            with patch("src.research.hyp_first_candle_event_discovery._execute_event_study_outputs", side_effect=KeyboardInterrupt):
                payload = run_operational_discovery(
                    request,
                    output_dir=root / "out",
                    runtime_state=RuntimeState(HEAD, True),
                    raise_on_error=False,
                    progress=ExecutionProgress(emit_console=False),
                )
            self.assertTrue(payload["interrupted"])
            self.assertFalse(payload["results_written"])
            self.assertFalse((root / "out").exists())


if __name__ == "__main__":
    unittest.main()
