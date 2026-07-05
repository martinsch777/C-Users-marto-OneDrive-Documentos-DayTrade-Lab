import unittest

import pandas as pd

from src.backtesting import BacktestEngine
from src.cli import build_parser
from src.execution_simulator import ExecutionRequest, ExecutionSimulator
from src.indicators import detect_fvg_and_mss
from src.strategies import OpeningRangeFVGStrategy, Signal, build_strategies


def strategy_frame() -> pd.DataFrame:
    local_times = [
        "2025-07-02 09:29",
        "2025-07-02 09:30",
        "2025-07-02 09:31",
        "2025-07-02 09:32",
        "2025-07-02 09:33",
        "2025-07-02 09:34",
        "2025-07-02 09:35",
        "2025-07-02 09:36",
        "2025-07-02 09:37",
        "2025-07-02 09:38",
        "2025-07-02 09:39",
        "2025-07-02 16:00",
        "2025-07-02 16:01",
    ]
    timestamps = (
        pd.DatetimeIndex(local_times)
        .tz_localize("America/New_York")
        .tz_convert("UTC")
    )
    prices = [
        (110.0, 112.0, 109.0, 111.0),
        (100.0, 100.2, 99.8, 100.0),
        (100.0, 100.3, 99.9, 100.1),
        (100.1, 100.4, 100.0, 100.2),
        (100.2, 100.5, 100.1, 100.3),
        (100.3, 100.6, 100.2, 100.5),
        (100.7, 101.6, 100.8, 101.5),
        (101.55, 103.1, 100.5, 100.5),
        (100.5, 100.55, 100.3, 100.5),
        (100.5, 100.7, 100.4, 100.6),
        (100.8, 101.8, 100.8, 101.6),
        (105.0, 106.0, 104.0, 105.5),
        (105.5, 107.0, 105.0, 106.5),
    ]
    frame = pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": [row[0] for row in prices],
            "high": [row[1] for row in prices],
            "low": [row[2] for row in prices],
            "close": [row[3] for row in prices],
            "volume": [100_000.0] * len(prices),
        }
    )
    frame["atr"] = 1.0
    frame["rsi"] = 50.0
    frame["vwap"] = 100.0
    frame["ema_9"] = 100.0
    frame["ema_20"] = 100.0
    frame["relative_volume"] = 1.5
    return frame


def strategy_config(**overrides) -> dict:
    config = {
        "session_timezone": "America/New_York",
        "session_start": "09:30",
        "session_end": "16:00",
        "candidate_end": "15:30",
        "opening_range_minutes": 5,
        "minimum_range_atr": 0.5,
        "maximum_range_atr": 5.0,
        "minimum_displacement_atr": 0.5,
        "minimum_fvg_gap_atr": 0.2,
        "structure_lookback": 3,
        "stop_mode": "breakout_candle",
        "risk_reward": 2.0,
        "max_trades_per_day": 1,
    }
    config.update(overrides)
    return config


class OpeningRangeFVGTests(unittest.TestCase):
    @staticmethod
    def gap_engine():
        return BacktestEngine(
            {
                "initial_equity": 100000,
                "risk_per_trade_pct": 0.001,
                "max_daily_loss_pct": 0.50,
                "max_weekly_loss_pct": 0.50,
                "max_trades_per_day": 5,
                "max_consecutive_losses": 5,
                "max_exposure_pct": 1.0,
                "max_position_notional": 100000,
                "minimum_risk_reward": 1.5,
                "max_spread_bps": 8,
                "min_relative_volume": 0,
                "max_atr_pct": 1,
            },
            {
                "spread_bps": 0,
                "slippage_bps": 0,
                "commission_bps": 0,
                "max_volume_participation": 1,
                "same_bar_policy": "stop_first",
                "force_flat_before_session_end": True,
            },
            {
                "allowed_setups": ["opening_range_fvg"],
                "trading_window_start": "09:30",
                "trading_window_end": "15:30",
                "max_trades_per_hour": 5,
                "loss_cooldown_minutes": 0,
            },
        )

    @staticmethod
    def gap_case(fill_open: float, *, max_gap_pct: float = 0.05):
        timestamps = pd.DatetimeIndex(
            [
                "2025-01-02 10:00",
                "2025-01-02 10:01",
                "2025-01-02 10:02",
                "2025-01-02 15:58",
            ]
        ).tz_localize("America/New_York").tz_convert("UTC")
        frame = pd.DataFrame(
            {
                "timestamp": timestamps,
                "open": [100.0, fill_open, fill_open, fill_open],
                "high": [100.2, fill_open + 0.2, fill_open + 10, fill_open + 0.2],
                "low": [99.8, fill_open - 0.2, fill_open - 0.2, fill_open - 0.2],
                "close": [100.0, fill_open, fill_open + 1, fill_open],
                "volume": [100000.0] * 4,
            }
        )
        signal = Signal(
            timestamp=timestamps[0],
            symbol="QQQ",
            timeframe="1min",
            strategy="opening_range_fvg",
            side="long",
            entry_price=100.0,
            stop_price=99.0,
            take_profit=102.0,
            reason="gap test",
            atr=1.0,
            metadata={
                "recalculate_risk_from_fill": True,
                "reward_r": 2.0,
                "max_entry_gap_pct": max_gap_pct,
            },
        )
        return frame, signal

    def test_closed_fvg_and_strategy_are_prefix_causal(self):
        frame = strategy_frame()
        full_structure = detect_fvg_and_mss(
            frame, structure_lookback=3, minimum_gap_atr=0.2
        )
        cutoff = 7
        prefix_structure = detect_fvg_and_mss(
            frame.iloc[:cutoff].copy(),
            structure_lookback=3,
            minimum_gap_atr=0.2,
        )
        pd.testing.assert_frame_equal(
            full_structure.iloc[:cutoff].reset_index(drop=True),
            prefix_structure.reset_index(drop=True),
        )

        strategy = OpeningRangeFVGStrategy(strategy_config())
        full_signals = strategy.generate_signals(frame, "QQQ", "1min")
        prefix_signals = strategy.generate_signals(
            frame.iloc[:cutoff].copy(), "QQQ", "1min"
        )
        self.assertEqual(
            [(item.timestamp, item.side) for item in full_signals[:1]],
            [(item.timestamp, item.side) for item in prefix_signals],
        )

    def test_signal_requires_completed_range_break_displacement_and_fvg(self):
        frame = strategy_frame()
        signal = OpeningRangeFVGStrategy(strategy_config()).generate_signals(
            frame, "QQQ", "1min"
        )[0]
        local = signal.timestamp.tz_convert("America/New_York")
        self.assertEqual(local.strftime("%H:%M"), "09:35")
        self.assertEqual(signal.side, "long")

        no_fvg = frame.copy()
        no_fvg.loc[6, "low"] = 100.45
        self.assertEqual(
            OpeningRangeFVGStrategy(strategy_config()).generate_signals(
                no_fvg.iloc[:8].copy(), "QQQ", "1min"
            ),
            [],
        )

        no_breakout = frame.copy()
        no_breakout.loc[5, "high"] = 102.0
        self.assertEqual(
            OpeningRangeFVGStrategy(strategy_config()).generate_signals(
                no_breakout, "QQQ", "1min"
            ),
            [],
        )

    def test_no_trade_without_break_and_outside_rth_is_ignored(self):
        frame = strategy_frame()
        no_break = frame.copy()
        no_break.loc[6:, ["open", "high", "low", "close"]] = [
            100.3,
            100.5,
            100.1,
            100.4,
        ]
        signals = OpeningRangeFVGStrategy(strategy_config()).generate_signals(
            no_break, "QQQ", "1min"
        )
        self.assertEqual(signals, [])

        valid = OpeningRangeFVGStrategy(strategy_config()).generate_signals(
            frame, "QQQ", "1min"
        )
        self.assertTrue(valid)
        for signal in valid:
            clock = signal.timestamp.tz_convert("America/New_York").time()
            self.assertGreaterEqual(clock, pd.Timestamp("09:35").time())
            self.assertLess(clock, pd.Timestamp("16:00").time())

    def test_entry_is_next_bar_and_ambiguous_bar_is_stop_first(self):
        frame = strategy_frame()
        signal = OpeningRangeFVGStrategy(strategy_config()).generate_signals(
            frame, "QQQ", "1min"
        )[0]
        result = ExecutionSimulator(
            {
                "spread_bps": 0,
                "slippage_bps": 0,
                "commission_bps": 0,
                "max_volume_participation": 1,
                "same_bar_policy": "stop_first",
                "force_flat_before_session_end": True,
            }
        ).simulate(
            frame,
            ExecutionRequest(
                signal_timestamp=signal.timestamp,
                side=signal.side,
                quantity=10,
                stop_loss=signal.stop_price,
                take_profit=signal.take_profit,
            ),
        )
        self.assertEqual(result.entry_timestamp, frame.iloc[7]["timestamp"])
        self.assertEqual(result.exit_reason, "STOP_FIRST_AMBIGUOUS_BAR")

    def test_daily_signal_limit_is_configurable(self):
        frame = strategy_frame()
        one = OpeningRangeFVGStrategy(
            strategy_config(max_trades_per_day=1)
        ).generate_signals(frame, "QQQ", "1min")
        two = OpeningRangeFVGStrategy(
            strategy_config(max_trades_per_day=2)
        ).generate_signals(frame, "QQQ", "1min")
        self.assertEqual(len(one), 1)
        self.assertEqual(len(two), 2)

    def test_cli_selects_only_opening_range_fvg(self):
        args = build_parser().parse_args(
            [
                "backtest",
                "--csv",
                "qqq.csv",
                "--symbol",
                "QQQ",
                "--timeframe",
                "1min",
                "--asset-class",
                "equity",
                "--strategy",
                "opening_range_fvg",
            ]
        )
        self.assertEqual(args.strategy, "opening_range_fvg")
        selected = build_strategies(
            {"strategies": {"opening_range_fvg": {}}},
            asset_class="equity",
            strategy_names=[args.strategy],
        )
        self.assertEqual([item.name for item in selected], ["opening_range_fvg"])

    def test_adverse_gap_recalculates_target_and_sizing_from_fill(self):
        frame, signal = self.gap_case(101.5)
        result = self.gap_engine().run_signals(frame, [signal])
        trade = result.trades.iloc[0]
        self.assertEqual(trade["status"], "FILLED")
        self.assertAlmostEqual(trade["entry_price"], 101.5)
        self.assertAlmostEqual(trade["take_profit"], 106.5)
        self.assertEqual(trade["position_size"], 40)
        self.assertAlmostEqual(trade["risk_amount"], 100.0)

    def test_favorable_gap_recalculates_target_and_sizing_from_fill(self):
        frame, signal = self.gap_case(99.5)
        result = self.gap_engine().run_signals(frame, [signal])
        trade = result.trades.iloc[0]
        self.assertEqual(trade["status"], "FILLED")
        self.assertAlmostEqual(trade["take_profit"], 100.5)
        self.assertEqual(trade["position_size"], 200)
        self.assertAlmostEqual(trade["risk_amount"], 100.0)

    def test_fill_beyond_stop_is_cancelled(self):
        frame, signal = self.gap_case(98.5)
        result = self.gap_engine().run_signals(frame, [signal])
        trade = result.trades.iloc[0]
        self.assertEqual(trade["status"], "CANCELLED")
        self.assertEqual(trade["exit_reason"], "CANCELLED_FILL_BEYOND_STOP")
        self.assertEqual(trade["position_size"], 0)

    def test_entry_gap_over_configured_limit_is_cancelled(self):
        frame, signal = self.gap_case(102.0, max_gap_pct=0.01)
        result = self.gap_engine().run_signals(frame, [signal])
        trade = result.trades.iloc[0]
        self.assertEqual(trade["status"], "CANCELLED")
        self.assertEqual(trade["exit_reason"], "CANCELLED_ENTRY_GAP_LIMIT")


if __name__ == "__main__":
    unittest.main()
