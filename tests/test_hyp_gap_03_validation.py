import unittest

from src.research.hyp_gap_03_validation import (
    build_freeze_manifest,
    build_methodology_audit,
)


class HypGap03ValidationReviewTests(unittest.TestCase):
    def test_methodology_audit_authorizes_validation_without_opening_holdout(self):
        audit = build_methodology_audit()

        self.assertEqual(audit["conclusion"], "habilitada_para_validation")
        self.assertEqual(audit["serious_blockers"], [])
        self.assertFalse(audit["discovery_output_bounds"]["QQQ"]["contains_2025_or_2026"])
        self.assertFalse(audit["discovery_output_bounds"]["SPY"]["contains_2025_or_2026"])
        self.assertEqual(audit["holdout_status"], "cerrado_no_leido_no_ejecutado")
        self.assertFalse(audit["safety_flags"]["orders_sent"])

    def test_freeze_manifest_records_hyp_gap_03_and_safety_state(self):
        audit = build_methodology_audit()
        freeze = build_freeze_manifest(audit)

        self.assertEqual(freeze["variant_id"], "HYP-GAP-03")
        self.assertEqual(
            freeze["variant_definition"]["threshold"],
            {"normalized_gap_min": 0.35, "opening_move_atr_min": 0.10},
        )
        self.assertEqual(freeze["frozen_period"]["validation"]["start"], "2025-01-01")
        self.assertEqual(freeze["frozen_period"]["validation"]["end"], "2025-12-31")
        self.assertEqual(freeze["frozen_period"]["final_holdout"]["status"], "closed_not_read_not_run")
        self.assertIn("QQQ", freeze["input_datasets"])
        self.assertIn("SPY", freeze["input_datasets"])
        self.assertFalse(freeze["paper_or_live_authorized"])
        self.assertFalse(freeze["orders_authorized"])
        self.assertFalse(freeze["safety_flags"]["live_trading"])
        self.assertIn("freeze_hash", freeze)


if __name__ == "__main__":
    unittest.main()
