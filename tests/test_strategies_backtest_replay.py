import unittest

import pandas as pd

from src.backtesting import BacktestEngine
from src.replay import MarketReplay
from src.strategies import Signal, Strategy, build_strategies
from src.utils import generate_synthetic_intraday


class FixedStrategy(Strategy):
    name = "fixed"

    def __init__(self, signal_item=None):
        super().__init__({})
        self.signal_item = signal_item
        self.visible_ends = []

    def generate_signals(self, frame, symbol, timeframe):
        self.visible_ends.append(frame.iloc[-1]["timestamp"])
        return [self.signal_item] if self.signal_item is not None else []


class StrategyBacktestReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frame = generate_synthetic_intraday(sessions=40, timeframe="15min", seed=3)

    def test_all_strategy_families_are_causal_and_levels_are_valid(self):
        strategies = build_strategies(
            {
                "strategies": {
                    "opening_range_breakout": {},
                    "vwap_pullback": {},
                    "relative_volume_momentum": {},
                    "extreme_mean_reversion": {},
                    "trend_day_continuation": {},
                }
            }
        )
        timestamps = set(self.frame["timestamp"])
        total = 0
        for strategy in strategies:
            signals = strategy.generate_signals(self.frame, "SPY", "15min")
            total += len(signals)
            for item in signals:
                self.assertIn(item.timestamp, timestamps)
                self.assertGreater(item.risk_per_unit, 0)
                self.assertGreater(item.risk_reward, 0)
        self.assertGreater(total, 0)

    def test_backtest_executes_fixed_signal(self):
        timestamp = self.frame.iloc[50]["timestamp"]
        entry = float(self.frame.iloc[50]["close"])
        item = Signal(
            timestamp=timestamp,
            symbol="SPY",
            timeframe="15min",
            strategy="fixed",
            side="long",
            entry_price=entry,
            stop_price=entry - 2,
            take_profit=entry + 4,
            reason="fixed test",
            relative_volume=1.5,
            atr=1,
        )
        engine = BacktestEngine(
            {
                "initial_equity": 100000,
                "risk_per_trade_pct": 0.005,
                "max_daily_loss_pct": 0.015,
                "max_weekly_loss_pct": 0.04,
                "max_trades_per_day": 5,
                "max_consecutive_losses": 3,
                "max_exposure_pct": 0.30,
                "max_position_notional": 25000,
                "minimum_risk_reward": 1.5,
                "max_spread_bps": 8,
                "min_relative_volume": 0.8,
                "max_atr_pct": 0.05,
            },
            {
                "spread_bps": 0,
                "slippage_bps": 0,
                "commission_bps": 0,
                "max_volume_participation": 1,
                "same_bar_policy": "stop_first",
            },
            {
                "allowed_setups": ["fixed"],
                "loss_cooldown_minutes": 30,
                "trading_window_start": "09:30",
                "trading_window_end": "16:00",
                "max_trades_per_hour": 2,
                "block_fomo": True,
            },
        )
        result = engine.run(self.frame, FixedStrategy(item), "SPY", "15min")
        self.assertEqual(len(result.trades), 1)
        self.assertEqual(result.trades.iloc[0]["status"], "FILLED")

    def test_replay_only_passes_visible_prefixes(self):
        strategy = FixedStrategy()
        replay = MarketReplay(
            {"initial_equity": 100000},
            {
                "allowed_setups": ["fixed"],
                "trading_window_start": "09:30",
                "trading_window_end": "16:00",
            },
        )
        subset = self.frame.iloc[:25].reset_index(drop=True)
        list(
            replay.iter_events(
                subset,
                strategy,
                "SPY",
                "15min",
                session_id="test",
                warmup_bars=20,
            )
        )
        self.assertEqual(strategy.visible_ends[-1], subset.iloc[-1]["timestamp"])
        self.assertEqual(len(strategy.visible_ends), 5)

    def test_consecutive_loss_lock_resets_next_session(self):
        timestamps = [
            pd.Timestamp("2024-01-02 15:00:00+00:00"),
            pd.Timestamp("2024-01-02 15:15:00+00:00"),
            pd.Timestamp("2024-01-02 15:30:00+00:00"),
            pd.Timestamp("2024-01-02 15:45:00+00:00"),
            pd.Timestamp("2024-01-02 16:00:00+00:00"),
            pd.Timestamp("2024-01-02 16:15:00+00:00"),
            pd.Timestamp("2024-01-03 15:00:00+00:00"),
            pd.Timestamp("2024-01-03 15:15:00+00:00"),
        ]
        frame = pd.DataFrame(
            {
                "timestamp": timestamps,
                "open": [100.0] * 8,
                "high": [100.5] * 8,
                "low": [98.5] * 8,
                "close": [99.0] * 8,
                "volume": [10000.0] * 8,
            }
        )
        signals = [
            Signal(
                timestamp=frame.iloc[position]["timestamp"],
                symbol="SPY",
                timeframe="15min",
                strategy="fixed",
                side="long",
                entry_price=100,
                stop_price=99,
                take_profit=102,
                reason="forced loss",
                relative_volume=1.5,
                atr=1,
            )
            for position in (0, 2, 4, 6)
        ]
        engine = BacktestEngine(
            {
                "initial_equity": 100000,
                "risk_per_trade_pct": 0.001,
                "max_daily_loss_pct": 0.50,
                "max_weekly_loss_pct": 0.50,
                "max_trades_per_day": 10,
                "max_consecutive_losses": 3,
                "max_exposure_pct": 1,
                "max_position_notional": 100000,
                "minimum_risk_reward": 1.5,
                "max_spread_bps": 8,
                "min_relative_volume": 0.8,
                "max_atr_pct": 0.05,
            },
            {
                "spread_bps": 0,
                "slippage_bps": 0,
                "commission_bps": 0,
                "max_volume_participation": 1,
                "same_bar_policy": "stop_first",
            },
            {
                "allowed_setups": ["fixed"],
                "loss_cooldown_minutes": 0,
                "trading_window_start": "09:30",
                "trading_window_end": "16:00",
                "max_trades_per_hour": 10,
                "block_fomo": True,
            },
        )
        result = engine.run_signals(frame, signals)
        self.assertEqual(len(result.trades), 4)


if __name__ == "__main__":
    unittest.main()
