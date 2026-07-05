import unittest

import pandas as pd

from src.backtesting import (
    BacktestEngine,
    add_market_context,
    evaluate_replay_candidate,
    out_of_sample_from_signals,
    walk_forward_yearly_from_signals,
)
from src.strategies import Signal, build_strategies
from src.utils import generate_synthetic_intraday


def engine():
    return BacktestEngine(
        {
            "initial_equity": 100000,
            "risk_per_trade_pct": 0.001,
            "max_daily_loss_pct": 0.50,
            "max_weekly_loss_pct": 0.50,
            "max_trades_per_day": 100,
            "max_consecutive_losses": 100,
            "max_exposure_pct": 1,
            "max_position_notional": 100000,
            "minimum_risk_reward": 1.0,
            "max_spread_bps": 100,
            "min_relative_volume": 0,
            "max_atr_pct": 1,
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
            "trading_window_start": "00:00",
            "trading_window_end": "23:59",
            "max_trades_per_hour": 100,
            "block_fomo": False,
        },
    )


class Sprint2ValidationTests(unittest.TestCase):
    def test_crypto_strategies_use_utc_sessions(self):
        strategies = build_strategies(
            {"project": {"timezone": "America/New_York"}, "strategies": {}},
            asset_class="crypto",
        )
        for strategy in strategies:
            self.assertEqual(strategy.config["session_timezone"], "UTC")
        self.assertEqual(strategies[0].config["session_start"], "00:00")

    def test_oos_and_yearly_walk_forward_use_temporal_blocks(self):
        timestamps = pd.date_range(
            "2022-01-01",
            "2024-12-31",
            periods=60,
            tz="UTC",
        )
        frame = pd.DataFrame(
            {
                "timestamp": timestamps,
                "open": [100.0] * 60,
                "high": [103.0] * 60,
                "low": [99.5] * 60,
                "close": [102.0] * 60,
                "volume": [10000.0] * 60,
            }
        )
        signals = [
            Signal(
                timestamp=frame.iloc[position]["timestamp"],
                symbol="BTCUSDT",
                timeframe="15min",
                strategy="fixed",
                side="long",
                entry_price=100,
                stop_price=99,
                take_profit=102,
                reason="test",
                relative_volume=1,
                atr=1,
            )
            for position in range(0, 58, 3)
        ]
        oos = out_of_sample_from_signals(frame, signals, engine())
        split_time = frame.iloc[int(len(frame) * 0.70)]["timestamp"]
        if not oos.trades.empty:
            actual = pd.to_datetime(oos.trades["timestamp"], utc=True)
            self.assertTrue((actual >= split_time).all())
        walk, _ = walk_forward_yearly_from_signals(frame, signals, engine())
        self.assertEqual(set(walk["test_year"]), {2023, 2024})
        self.assertTrue((walk["train_end_year"] < walk["test_year"]).all())

    def test_market_context_labels_are_causal_columns(self):
        frame = generate_synthetic_intraday(sessions=20, timeframe="15min")
        context = add_market_context(frame)
        self.assertEqual(len(context), len(frame))
        self.assertTrue(
            {"year", "utc_hour", "day_of_week", "regime", "volatility_bucket"}
            .issubset(context.columns)
        )

    def test_replay_candidate_never_approves_internal_paper(self):
        decision = evaluate_replay_candidate(
            "opening_range_breakout",
            pd.DataFrame(),
            pd.DataFrame(),
            dataset_count=9,
            initial_equity=100000,
            guard_allowed_rate=0,
            maximum_dataset_drawdown=0,
        )
        self.assertFalse(decision.candidate_for_replay)
        self.assertFalse(decision.candidate_for_internal_paper)


if __name__ == "__main__":
    unittest.main()
