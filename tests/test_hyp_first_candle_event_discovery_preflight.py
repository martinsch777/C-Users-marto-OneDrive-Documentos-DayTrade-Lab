from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import yaml

from src.research.hyp_first_candle_event_discovery import (
    DISCOVERY_END,
    DISCOVERY_START,
    EXPECTED_SYMBOLS,
    FcrEventDiscoveryRequest,
    RuntimeState,
    prepare_only_manifest,
    validate_discovery_preflight,
)
from src.research.hyp_first_candle_event_study import canonical_event_config_hash


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


if __name__ == "__main__":
    unittest.main()
