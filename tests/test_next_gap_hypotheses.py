import tempfile
import unittest
from pathlib import Path

import pandas as pd

from src.research import next_gap_hypotheses as ngh


class NextGapHypothesesTests(unittest.TestCase):
    def test_preregistrations_preserve_holdout_and_safety_flags(self):
        for path in (ngh.ASYM_CONFIG, ngh.OR_CONFIG):
            payload = ngh._json(path)

            self.assertEqual(payload["periods"]["holdout_2026"]["status"], "closed_not_read_not_run")
            self.assertEqual(payload["periods"]["observed_2025"]["status"], "previously_observed_hypothesis_generation_evidence")
            self.assertFalse(payload["safety_flags"]["live_trading"])
            self.assertFalse(payload["safety_flags"]["broker_connected"])
            self.assertFalse(payload["safety_flags"]["orders_sent"])
            self.assertFalse(payload["safety_flags"]["paper_broker_enabled"])
            self.assertFalse(payload["restrictions"]["use_2025_as_clean_validation"])
            self.assertFalse(payload["restrictions"]["open_2026_holdout"])
            self.assertFalse(payload["restrictions"]["implement_strategy"])

    def test_research_pool_loader_excludes_2025_and_2026(self):
        frame, inputs = ngh.load_research_pool_symbol("QQQ")

        self.assertTrue(inputs)
        self.assertLessEqual(frame["_session_date"].max(), "2024-12-31")
        self.assertFalse(frame["_session_date"].str.startswith("2025").any())
        self.assertFalse(frame["_session_date"].str.startswith("2026").any())

    def test_gap_features_include_prev_close_atr_opening_range_and_directions(self):
        frame, _ = ngh.load_research_pool_symbol("SPY")
        events = ngh.build_gap_event_features("SPY", frame)

        self.assertIn("gap_up", set(events["gap_direction_label"]))
        self.assertIn("gap_down", set(events["gap_direction_label"]))
        self.assertTrue((events["previous_session_close"] > 0).all())
        self.assertTrue((events["prior_atr"] > 0).all())
        self.assertTrue((events["opening_range_width_atr"] > 0).all())
        self.assertFalse(events["session_date"].eq("2023-06-05").any())

    def test_frozen_terciles_are_applied_without_recalculation(self):
        events = pd.DataFrame(
            {
                "opening_range_width_atr": [0.1, 0.2, 0.3],
                "normalized_gap": [0.4, 0.5, 0.6],
            }
        )
        limits = {
            "opening_range_width_atr": {"narrow_max": 0.15, "wide_min": 0.25},
            "normalized_gap": {"small_max": 0.45, "large_min": 0.55},
        }

        bucketed = ngh.apply_frozen_regime_limits(events, limits)

        self.assertEqual(list(bucketed["opening_range_bucket"]), ["narrow", "normal", "wide"])
        self.assertEqual(list(bucketed["gap_size_bucket"]), ["small", "medium", "large"])

    def test_bootstrap_and_winsorization_are_reproducible(self):
        values = pd.Series([0.01, 0.02, -0.01, 0.03, 0.50])
        sessions = pd.Series(["a", "b", "c", "d", "e"])

        first = ngh._summary(values, sessions)
        second = ngh._summary(values, sessions)

        self.assertEqual(first["bootstrap_ci_95_lower"], second["bootstrap_ci_95_lower"])
        self.assertEqual(first["bootstrap_ci_95_upper"], second["bootstrap_ci_95_upper"])
        self.assertLess(first["winsor_5pct_mean_return"], values.mean())

    def test_runner_refuses_non_empty_output_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            (path / "sentinel.txt").write_text("x", encoding="utf-8")

            with self.assertRaisesRegex(FileExistsError, "not empty"):
                ngh.run(path)


if __name__ == "__main__":
    unittest.main()
