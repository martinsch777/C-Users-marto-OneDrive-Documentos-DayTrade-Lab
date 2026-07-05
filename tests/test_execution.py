import unittest

import pandas as pd

from src.execution_simulator import ExecutionRequest, ExecutionSimulator


def execution_frame(rows):
    timestamps = pd.date_range("2024-01-02 14:30", periods=len(rows), freq="15min", tz="UTC")
    return pd.DataFrame(
        [
            {
                "timestamp": timestamp,
                "open": values[0],
                "high": values[1],
                "low": values[2],
                "close": values[3],
                "volume": values[4],
            }
            for timestamp, values in zip(timestamps, rows)
        ]
    )


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.config = {
            "spread_bps": 0,
            "slippage_bps": 0,
            "commission_bps": 0,
            "latency_bars": 0,
            "max_volume_participation": 1.0,
            "allow_partial_fills": True,
            "same_bar_policy": "stop_first",
        }

    def test_ambiguous_bar_uses_stop_first(self):
        frame = execution_frame(
            [
                (100, 100.5, 99.5, 100, 10000),
                (100, 102, 98, 100, 10000),
                (100, 101, 99, 100, 10000),
            ]
        )
        result = ExecutionSimulator(self.config).simulate(
            frame,
            ExecutionRequest(
                signal_timestamp=frame.iloc[0]["timestamp"],
                side="long",
                quantity=10,
                stop_loss=99,
                take_profit=101,
            ),
        )
        self.assertEqual(result.status, "FILLED")
        self.assertEqual(result.exit_reason, "STOP_FIRST_AMBIGUOUS_BAR")
        self.assertLess(result.net_pnl, 0)

    def test_limit_can_expire_without_fill(self):
        frame = execution_frame(
            [
                (100, 101, 99, 100, 10000),
                (100, 101, 99, 100, 10000),
                (100, 101, 99, 100, 10000),
            ]
        )
        result = ExecutionSimulator(self.config).simulate(
            frame,
            ExecutionRequest(
                signal_timestamp=frame.iloc[0]["timestamp"],
                side="long",
                quantity=10,
                stop_loss=94,
                take_profit=101,
                order_type="limit",
                limit_price=95,
            ),
        )
        self.assertEqual(result.status, "NO_FILL")

    def test_volume_capacity_creates_partial_fill(self):
        frame = execution_frame(
            [
                (100, 101, 99, 100, 1000),
                (100, 101.5, 99.5, 101, 1000),
                (101, 102, 100.5, 101.5, 1000),
            ]
        )
        config = {**self.config, "max_volume_participation": 0.02}
        result = ExecutionSimulator(config).simulate(
            frame,
            ExecutionRequest(
                signal_timestamp=frame.iloc[0]["timestamp"],
                side="long",
                quantity=100,
                stop_loss=99,
                take_profit=101,
            ),
        )
        self.assertTrue(result.partial_fill)
        self.assertEqual(result.filled_quantity, 20)

    def test_partial_target_then_break_even_stop(self):
        frame = execution_frame(
            [
                (100, 100.2, 99.8, 100, 10000),
                (100, 101.2, 99.5, 101, 10000),
                (100.8, 101, 99.8, 100, 10000),
            ]
        )
        result = ExecutionSimulator(self.config).simulate(
            frame,
            ExecutionRequest(
                signal_timestamp=frame.iloc[0]["timestamp"],
                side="long",
                quantity=10,
                stop_loss=99,
                take_profit=101,
                partial_exit_fraction=0.5,
            ),
        )
        self.assertTrue(result.partial_exit)
        self.assertEqual(result.exit_reason, "PARTIAL_TARGET_THEN_STOP_LOSS")

    def test_spread_and_slippage_reduce_result(self):
        frame = execution_frame(
            [
                (100, 100.2, 99.8, 100, 10000),
                (100, 101.5, 99.8, 101, 10000),
                (101, 102.5, 100.8, 102, 10000),
            ]
        )
        request = ExecutionRequest(
            signal_timestamp=frame.iloc[0]["timestamp"],
            side="long",
            quantity=10,
            stop_loss=99,
            take_profit=102,
        )
        frictionless = ExecutionSimulator(self.config).simulate(frame, request)
        costly = ExecutionSimulator(
            {
                **self.config,
                "spread_bps": 10,
                "slippage_bps": 10,
            }
        ).simulate(frame, request)
        self.assertLess(costly.net_pnl, frictionless.net_pnl)
        self.assertGreater(costly.spread_cost, 0)
        self.assertGreater(costly.slippage_cost, 0)


if __name__ == "__main__":
    unittest.main()
