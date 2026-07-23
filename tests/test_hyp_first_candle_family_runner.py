import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

import pandas as pd

from src.data.dataset_manifest import FAILED_AUDIT, sha256_file
from src.research.hyp_first_candle_family_runner import (
    FAMILY_ID,
    VARIANT_IDS,
    FamilyRunRequest,
    canonical_yaml_hash,
    main,
    prepare_family_manifest,
    select_family_variant,
    validate_family_manifests,
    validate_family_run_request,
    validate_variant_set,
)


def ts(value: str) -> pd.Timestamp:
    return pd.Timestamp(value, tz="America/New_York").tz_convert("UTC")


def write_manifest(directory: Path, csv_path: Path, *, status="approved_for_or_fvg_backtest") -> None:
    payload = {
        "adjustment": "raw",
        "asset_class": "equity",
        "audit_apt_for_or_fvg_backtest": status != FAILED_AUDIT,
        "audit_critical_warnings": [],
        "audit_warnings": [],
        "broker_connected": False,
        "calendar_early_closes_loaded": 1,
        "calendar_holidays_loaded": 1,
        "calendar_loaded": True,
        "calendar_source": "builtin_us_equity_calendar_v1",
        "created_at": "2026-07-22T00:00:00+00:00",
        "curated_file": str(csv_path),
        "dataset_status": status,
        "end": "2024-07-01",
        "excluded_sessions": [],
        "feed": "sip",
        "first_timestamp": "2024-07-01 09:30:00-04:00",
        "input_file": str(csv_path),
        "last_timestamp": "2024-07-01 09:30:00-04:00",
        "live_trading_enabled": False,
        "orders_sent": False,
        "output_file": str(csv_path),
        "paper_broker_enabled": False,
        "provider": "alpaca",
        "rth_only": True,
        "rows": 1,
        "sha256": sha256_file(csv_path),
        "source_timezone": "America/New_York",
        "start": "2024-07-01",
        "symbol": "QQQ",
        "timeframe": "1min",
        "total_excluded_sessions": 0,
    }
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "QQQ_1min_2024-07-01_2024-07-01_curated_manifest.json").write_text(
        json.dumps(payload),
        encoding="utf-8",
    )


def result(hypothesis_id, passed, stress=0.1, pf=1.2, dd=0.05):
    return {
        "hypothesis_id": hypothesis_id,
        "gate_passed": passed,
        "stress_net_expectancy_R": stress,
        "baseline_profit_factor_net": pf,
        "baseline_maximum_drawdown": dd,
    }


class HypFirstCandleFamilyRunnerTests(unittest.TestCase):
    def test_runner_default_prepare_only(self):
        output = StringIO()
        with redirect_stdout(output):
            self.assertEqual(main([]), 0)
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["mode"], "prepare_only")
        self.assertFalse(payload["discovery_executed"])

    def test_runner_blocks_discovery_validation_2026_and_holdout(self):
        for mode in ("discovery", "validation", "parity_debug_2026", "holdout"):
            with self.assertRaisesRegex(PermissionError, "prepare_only"):
                validate_family_run_request(FamilyRunRequest(mode=mode))

    def test_runner_blocks_fourth_or_missing_variant(self):
        with self.assertRaisesRegex(PermissionError, "exactly"):
            validate_variant_set((*VARIANT_IDS, "HYP-FCR-05"))
        with self.assertRaisesRegex(PermissionError, "exactly"):
            validate_variant_set(("HYP-FCR-02", "HYP-FCR-03"))

    def test_selection_with_one_passing_variant(self):
        selection = select_family_variant(
            [
                result("HYP-FCR-02", False),
                result("HYP-FCR-03", True),
                result("HYP-FCR-04", False),
            ]
        )
        self.assertEqual(selection["selected_hypothesis_id"], "HYP-FCR-03")
        self.assertTrue(selection["validation_2025_unlocked"])

    def test_selection_with_multiple_passes_uses_stress_expectancy(self):
        selection = select_family_variant(
            [
                result("HYP-FCR-02", True, stress=0.2),
                result("HYP-FCR-03", True, stress=0.3),
                result("HYP-FCR-04", False),
            ]
        )
        self.assertEqual(selection["selected_hypothesis_id"], "HYP-FCR-03")
        self.assertEqual(selection["variant_statuses"]["HYP-FCR-02"], "discovery_passed_not_selected")

    def test_selection_tie_breaks_by_pf_drawdown_and_id(self):
        pf_selection = select_family_variant(
            [
                result("HYP-FCR-02", True, stress=0.205, pf=1.1),
                result("HYP-FCR-03", True, stress=0.201, pf=1.3),
                result("HYP-FCR-04", False),
            ]
        )
        self.assertEqual(pf_selection["selected_hypothesis_id"], "HYP-FCR-03")
        dd_selection = select_family_variant(
            [
                result("HYP-FCR-02", True, stress=0.2, pf=1.2, dd=0.08),
                result("HYP-FCR-03", True, stress=0.2, pf=1.2, dd=0.05),
                result("HYP-FCR-04", False),
            ]
        )
        self.assertEqual(dd_selection["selected_hypothesis_id"], "HYP-FCR-03")
        id_selection = select_family_variant(
            [
                result("HYP-FCR-02", True, stress=0.2, pf=1.2, dd=0.05),
                result("HYP-FCR-03", True, stress=0.2, pf=1.2, dd=0.05),
                result("HYP-FCR-04", False),
            ]
        )
        self.assertEqual(id_selection["selected_hypothesis_id"], "HYP-FCR-02")

    def test_no_passing_variant_keeps_validation_blocked(self):
        selection = select_family_variant(
            [
                result("HYP-FCR-02", False),
                result("HYP-FCR-03", False),
                result("HYP-FCR-04", False),
            ]
        )
        self.assertEqual(selection["family_status"], "discovery_failed")
        self.assertFalse(selection["validation_2025_unlocked"])

    def test_prepare_manifest_has_one_validation_candidate_slot_and_safety(self):
        payload = prepare_family_manifest()
        self.assertEqual(payload["family_id"], FAMILY_ID)
        self.assertEqual(payload["variant_ids"], list(VARIANT_IDS))
        self.assertFalse(payload["safety_flags"]["live_trading"])
        self.assertFalse(payload["paper_eligible"])
        self.assertFalse(payload["live_eligible"])

    def test_hashes_are_distinct_and_deterministic(self):
        paths = [Path("configs/research/hypotheses") / f"{item}.yaml" for item in VARIANT_IDS]
        hashes = [canonical_yaml_hash(path) for path in paths]
        self.assertEqual(len(set(hashes)), 3)
        self.assertEqual(hashes, [canonical_yaml_hash(path) for path in paths])

    def test_unapproved_manifests_are_rejected(self):
        directory = Path(tempfile.mkdtemp())
        csv_path = directory / "QQQ_1min.csv"
        pd.DataFrame(
            {
                "timestamp": [ts("2024-07-01 09:30")],
                "open": [100.0],
                "high": [101.0],
                "low": [99.0],
                "close": [100.5],
                "volume": [1000.0],
            }
        ).to_csv(csv_path, index=False)
        write_manifest(directory / "manifests", csv_path, status=FAILED_AUDIT)
        with self.assertRaisesRegex(ValueError, "approved_for_or_fvg_backtest"):
            validate_family_manifests({"QQQ": csv_path}, manifest_dir=directory / "manifests")


if __name__ == "__main__":
    unittest.main()
