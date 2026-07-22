import unittest

import pandas as pd

from src.research.hyp_first_candle_discovery import _gate_evaluation, metrics_for_trades


class HypFirstCandleDiscoveryTests(unittest.TestCase):
    def test_metrics_for_trades_computes_primary_and_secondary_fields(self):
        trades = pd.DataFrame(
            [
                {
                    "actual_quantity": 1,
                    "net_pnl": 2.0,
                    "realized_R": 1.0,
                    "intended_R": 1.1,
                    "entry_time": "2022-01-03T15:00:00+00:00",
                    "exit_time": "2022-01-03T15:30:00+00:00",
                    "risk_percent_intended": 0.005,
                    "risk_percent_realized": 0.004,
                    "minutes_between_last_touch_and_confirmation": 10.0,
                    "fvg_size_ticks": 3.0,
                    "fvg_size_normalized_by_atr": 0.5,
                    "exit_reason": "TAKE_PROFIT",
                },
                {
                    "actual_quantity": 1,
                    "net_pnl": -1.0,
                    "realized_R": -0.5,
                    "intended_R": -0.4,
                    "entry_time": "2022-01-04T15:00:00+00:00",
                    "exit_time": "2022-01-04T15:05:00+00:00",
                    "risk_percent_intended": 0.005,
                    "risk_percent_realized": 0.003,
                    "minutes_between_last_touch_and_confirmation": 5.0,
                    "fvg_size_ticks": 2.0,
                    "fvg_size_normalized_by_atr": 0.25,
                    "exit_reason": "STOP_LOSS",
                },
            ]
        )

        metrics = metrics_for_trades(trades, initial_equity=1000, sizing_rejections=1)

        self.assertEqual(metrics["completed_trades"], 2)
        self.assertAlmostEqual(metrics["total_net_pnl"], 1.0)
        self.assertAlmostEqual(metrics["profit_factor_net"], 2.0)
        self.assertEqual(metrics["sizing_rejections"], 1)
        self.assertEqual(metrics["tp_exits"], 1)
        self.assertEqual(metrics["sl_exits"], 1)

    def test_gate_year_share_fails_when_total_pnl_non_positive(self):
        summary = {
            "baseline": {
                "completed_trades": 200,
                "net_expectancy_R": 0.1,
                "profit_factor_net": 1.2,
                "total_net_pnl": -1.0,
                "maximum_drawdown": 0.05,
            },
            "stress": {
                "net_expectancy_R": 0.0,
                "profit_factor_net": 1.0,
            },
        }
        by_symbol = pd.DataFrame(
            [
                {"scenario": "baseline", "symbol": "QQQ", "completed_trades": 100, "total_net_pnl": 1.0},
                {"scenario": "baseline", "symbol": "SPY", "completed_trades": 100, "total_net_pnl": 1.0},
            ]
        )
        by_year = pd.DataFrame(
            [
                {"scenario": "baseline", "year": 2022, "total_net_pnl": 1.0},
                {"scenario": "baseline", "year": 2023, "total_net_pnl": 1.0},
                {"scenario": "baseline", "year": 2024, "total_net_pnl": -3.0},
            ]
        )

        gate = _gate_evaluation(summary, by_symbol, by_year)

        criterion = {
            item["criterion"]: item for item in gate["criteria"]
        }["max_single_year_profit_share_lte_70pct"]
        self.assertFalse(criterion["passed"])
        self.assertIsNone(criterion["observed"]["max_year_share"])
        self.assertEqual(criterion["observed"]["reason"], "pooled_baseline_total_net_pnl_lte_0")
        self.assertEqual(gate["status"], "discovery_failed")


if __name__ == "__main__":
    unittest.main()
