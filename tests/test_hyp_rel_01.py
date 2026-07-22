import tempfile
import unittest
from pathlib import Path

import pandas as pd

from src.data import EquitySessionCalendar
from src.research import hyp_rel_01 as rel


CALENDAR = EquitySessionCalendar.from_config({"source": "us_equity"})


def minute_frame(day: str, base: float, symbol: str) -> pd.DataFrame:
    rows = []
    for i, timestamp in enumerate(CALENDAR.expected_timestamps(pd.Timestamp(day).date(), pd.Timestamp(day).date(), "1min")):
        price = base + i * 0.01
        rows.append(
            {
                "timestamp": timestamp,
                "open": price,
                "high": price + 0.02,
                "low": price - 0.02,
                "close": price + (0.01 if symbol == "QQQ" else 0.005),
                "volume": 1000,
            }
        )
    return pd.DataFrame(rows)


class HypRel01Tests(unittest.TestCase):
    def test_preregistration_locks_holdout_and_safety(self):
        payload = rel._read_yaml(rel.PREREGISTRATION_PATH)

        self.assertEqual(payload["periods"]["holdout"]["status"], "closed_not_read_not_run")
        self.assertFalse(payload["safety_flags"]["live_trading"])
        self.assertFalse(payload["safety_flags"]["broker_connected"])
        self.assertFalse(payload["safety_flags"]["orders_sent"])
        self.assertFalse(payload["safety_flags"]["paper_broker_enabled"])
        self.assertFalse(payload["restrictions"]["use_2026"])
        self.assertFalse(payload["restrictions"]["implement_strategy"])

    def test_sync_keeps_only_common_timestamps_and_sessions(self):
        qqq = rel.resample_rth_1min_to_5min(minute_frame("2024-01-03", 100, "QQQ"), CALENDAR)
        spy = rel.resample_rth_1min_to_5min(minute_frame("2024-01-03", 90, "SPY"), CALENDAR)
        spy = spy.iloc[:-1].copy()
        qqq["session_date"] = "2024-01-03"
        spy["session_date"] = "2024-01-03"

        pair, diagnostics = rel.synchronize_pair(qqq, spy, calendar=CALENDAR)

        self.assertEqual(len(pair), len(spy))
        self.assertLess(diagnostics["common_5m_bars"].iloc[0], diagnostics["qqq_5m_bars"].iloc[0])

    def test_loader_excludes_holdout_and_spy_bad_session(self):
        spy, _ = rel.load_symbol_5min("SPY", (2023,))

        self.assertFalse(spy["session_date"].eq("2023-06-05").any())
        self.assertFalse(spy["session_date"].ge("2026-01-01").any())

    def test_beta_uses_prior_observations_only(self):
        prior = pd.DataFrame(
            {
                "qqq_log_return_5m": [0.02] * 1001,
                "spy_log_return_5m": [0.01] * 1001,
            }
        )

        beta, observations = rel.estimate_beta(prior)

        self.assertEqual(observations, 1001)
        self.assertAlmostEqual(beta, 2.0)
        current_changed = prior.copy()
        current_changed.loc[0, "qqq_log_return_5m"] = 99
        beta_changed, _ = rel.estimate_beta(current_changed.iloc[1:])
        self.assertAlmostEqual(beta_changed, 2.0)

    def test_detect_events_enforces_daily_direction_limit_and_cooldown(self):
        rows = []
        timestamps = CALENDAR.expected_timestamps(pd.Timestamp("2024-01-03").date(), pd.Timestamp("2024-01-03").date(), "5min")
        for i, timestamp in enumerate(timestamps[:78]):
            z = 2.5 if 6 <= i <= 20 else 0.0
            rows.append(
                {
                    "timestamp": timestamp,
                    "session_date": "2024-01-03",
                    "bar_time": timestamp.tz_convert("America/New_York").strftime("%H:%M"),
                    "z_score": z,
                    "beta": 1.0,
                    "beta_observations": 1000,
                    "relative_residual": 0.01,
                    "qqq_close": 100 + i,
                    "spy_close": 90 + i,
                }
            )
        features = pd.DataFrame(rows)

        events, blocked = rel.detect_events(features)

        self.assertEqual(len(events), 1)
        self.assertIn("direction_daily_limit", set(blocked["reason"]))

    def test_metric_summary_bootstrap_and_winsorization_are_reproducible(self):
        values = pd.Series([0.01, 0.02, -0.01, 0.50, 0.03])
        sessions = pd.Series(["a", "b", "c", "d", "e"])

        first = rel._metric_summary(values, sessions)
        second = rel._metric_summary(values, sessions)

        self.assertEqual(first["bootstrap_ci_95_lower"], second["bootstrap_ci_95_lower"])
        self.assertLess(first["winsor_5pct_mean_return"], values.mean())

    def test_runner_refuses_non_empty_output_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            (path / "x.txt").write_text("x", encoding="utf-8")

            with self.assertRaisesRegex(FileExistsError, "not empty"):
                rel.run(path)


if __name__ == "__main__":
    unittest.main()
