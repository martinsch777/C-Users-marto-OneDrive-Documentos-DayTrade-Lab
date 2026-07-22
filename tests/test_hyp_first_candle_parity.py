import unittest

import pandas as pd

from src.research.hyp_first_candle_parity import (
    FINAL_COST_ROUNDING_TOLERANCE,
    build_cost_reconciliation_final,
    classify_timing_difference,
    compare_pine_to_python_events,
)


def tv_trade(num: int, day: str, direction: str, entry_price: float) -> dict:
    return {
        "source_symbol": "BATS:QQQ",
        "normalized_symbol": "QQQ",
        "trade_num": num,
        "direction": direction,
        "entry_time_utc": f"{day}T14:30:00+00:00",
        "entry_price": entry_price,
        "exit_time_utc": f"{day}T14:35:00+00:00",
        "exit_price": entry_price + (1 if direction == "long" else -1),
        "qty": 1,
        "profit": 0.9,
        "commission": 0.1,
        "exit_comment": "TP o SL",
    }


def py_trade(num: int, day: str, direction: str, entry_price: float) -> dict:
    return {
        "symbol": "QQQ",
        "trade_num": num,
        "session_date": day,
        "direction": direction,
        "entry_time": f"{day}T14:30:00+00:00",
        "entry_price": entry_price,
        "exit_time": f"{day}T14:35:00+00:00",
        "exit_price": entry_price + (1 if direction == "long" else -1),
        "actual_quantity": 1,
        "profit": 0.9,
        "commission": 0.1,
        "exit_comment": "TP o SL",
    }


class HypFirstCandleParityTests(unittest.TestCase):
    def test_event_matching_prevents_sequence_shift_cascade(self):
        tv = pd.DataFrame(
            [
                tv_trade(0, "2026-06-11", "short", 700.0),
                tv_trade(1, "2026-06-12", "short", 710.0),
                tv_trade(2, "2026-06-17", "long", 720.0),
            ]
        )
        py = pd.DataFrame(
            [
                py_trade(0, "2026-06-10", "short", 690.0),
                py_trade(1, "2026-06-11", "short", 700.0),
                py_trade(2, "2026-06-12", "short", 710.0),
                py_trade(3, "2026-06-17", "long", 720.0),
            ]
        )

        comparison = compare_pine_to_python_events(tv, py)

        paired = comparison.loc[comparison["parity_bucket"] != "missing_in_tradingview"]
        self.assertEqual(paired["py_trade_num"].astype(int).tolist(), [1, 2, 3])
        self.assertEqual(int((comparison["matching_classification"] == "sequence_misalignment").sum()), 3)
        self.assertEqual(int((comparison["parity_bucket"] == "missing_in_tradingview").sum()), 1)

    def test_event_matching_is_one_to_one(self):
        tv = pd.DataFrame(
            [
                tv_trade(0, "2026-06-11", "short", 700.00),
                tv_trade(1, "2026-06-11", "short", 700.02),
            ]
        )
        py = pd.DataFrame([py_trade(0, "2026-06-11", "short", 700.01)])

        comparison = compare_pine_to_python_events(tv, py)

        self.assertEqual(int((comparison["parity_bucket"] == "missing_in_python").sum()), 1)
        self.assertEqual(int((comparison["parity_bucket"] != "missing_in_python").sum()), 1)

    def test_exit_time_difference_is_not_true_session_alignment(self):
        row = pd.Series(
            {
                "tv_trade_num": 8,
                "session_date": "2026-04-29",
                "direction": "short",
                "failed_fields": "exit_time,exit_price,profit",
                "difference_type": "SESSION_ALIGNMENT_DIFFERENCE",
                "event_alignment": "exact_event_match",
                "tv_entry_time_utc": "2026-04-29T16:20:00+00:00",
                "py_entry_time_utc": "2026-04-29T16:20:00+00:00",
                "tv_exit_time_utc": "2026-04-29T16:30:00+00:00",
                "py_exit_time_utc": "2026-04-29T18:35:00+00:00",
            }
        )

        classification = classify_timing_difference(row)

        self.assertEqual(classification["final_classification"], "EXIT_INTRABAR_TIMING")
        self.assertFalse(classification["blocks_discovery"])

    def test_entry_signal_shift_is_data_feed_signal_boundary(self):
        row = pd.Series(
            {
                "tv_trade_num": 18,
                "session_date": "2026-05-21",
                "direction": "long",
                "failed_fields": "entry_time,exit_time,entry_price,exit_price,profit",
                "difference_type": "SESSION_ALIGNMENT_DIFFERENCE",
                "event_alignment": "shifted_event",
                "tv_entry_time_utc": "2026-05-21T15:15:00+00:00",
                "py_entry_time_utc": "2026-05-21T15:45:00+00:00",
                "tv_exit_time_utc": "2026-05-21T17:15:00+00:00",
                "py_exit_time_utc": "2026-05-21T17:50:00+00:00",
            }
        )

        classification = classify_timing_difference(row)

        self.assertEqual(classification["final_classification"], "DATA_FEED_SIGNAL_BOUNDARY")
        self.assertEqual(classification["entry_time_delta_minutes"], -30.0)

    def test_tv_closedtrade_profit_is_net_of_reported_commission(self):
        comparison = pd.DataFrame(
            [
                {
                    "difference_type": "COST_CALCULATION_DIFFERENCE",
                    "tv_trade_num": 37,
                    "session_date": "2026-06-30",
                    "direction": "short",
                    "tv_entry_price": 730.47,
                    "tv_exit_price": 733.05,
                    "tv_quantity": 1.0,
                    "tv_commission": 0.146,
                    "tv_profit": -2.726,
                    "py_entry_price": 730.46,
                    "py_exit_price": 733.06,
                    "py_quantity": 1.0,
                    "py_commission": 0.146352,
                    "py_profit": -2.746352,
                }
            ]
        )

        reconciliation = build_cost_reconciliation_final(comparison).iloc[0]

        self.assertTrue(reconciliation["strategy_closedtrades_profit_net_of_commission"])
        self.assertAlmostEqual(reconciliation["expected_tv_net_profit"], -2.726)
        self.assertLessEqual(
            reconciliation["absolute_python_vs_tv_net_residual"],
            FINAL_COST_ROUNDING_TOLERANCE,
        )


if __name__ == "__main__":
    unittest.main()
