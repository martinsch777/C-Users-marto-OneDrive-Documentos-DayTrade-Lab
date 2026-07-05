import unittest

import pandas as pd

from src.psychology_guard import GuardContext, PsychologyGuard
from src.risk import PositionSizer, RiskManager, TradingState
from src.strategies import Signal


def signal(**overrides):
    values = {
        "timestamp": pd.Timestamp("2024-01-02 15:00:00+00:00"),
        "symbol": "SPY",
        "timeframe": "15min",
        "strategy": "opening_range_breakout",
        "side": "long",
        "entry_price": 100.0,
        "stop_price": 99.0,
        "take_profit": 102.0,
        "reason": "test",
        "relative_volume": 1.5,
        "atr": 1.0,
        "spread_bps": 2.0,
    }
    values.update(overrides)
    return Signal(**values)


class RiskAndGuardTests(unittest.TestCase):
    def setUp(self):
        self.risk_config = {
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
            "kill_switch": False,
        }
        self.state = TradingState(100000, 100000)

    def test_position_size_respects_risk_and_notional(self):
        size = PositionSizer(self.risk_config).calculate(signal(), 100000)
        self.assertEqual(size, 250)

    def test_bad_risk_reward_is_blocked(self):
        bad = signal(take_profit=101.2)
        decision = RiskManager(self.risk_config).evaluate(bad, 100, self.state)
        self.assertFalse(decision.approved)
        self.assertEqual(decision.reason, "BLOCKED_BAD_RISK_REWARD")

    def test_daily_loss_is_blocked(self):
        self.state.daily_pnl["2024-01-02"] = -1500
        decision = RiskManager(self.risk_config).evaluate(signal(), 100, self.state)
        self.assertEqual(decision.reason, "BLOCKED_DAILY_LOSS_LIMIT")

    def test_guard_blocks_stop_move_and_cooldown(self):
        guard = PsychologyGuard(
            {
                "allowed_setups": ["opening_range_breakout"],
                "loss_cooldown_minutes": 30,
                "trading_window_start": "09:35",
                "trading_window_end": "15:30",
                "max_trades_per_hour": 2,
                "block_fomo": True,
            }
        )
        moved = guard.evaluate(
            signal(),
            self.state,
            GuardContext(attempted_stop_move_away=True),
        )
        self.assertEqual(moved.reason, "BLOCKED_STOP_MOVED_AWAY")
        self.state.last_loss_timestamp = signal().timestamp - pd.Timedelta(minutes=5)
        cooldown = guard.evaluate(signal(), self.state)
        self.assertEqual(cooldown.reason, "BLOCKED_AFTER_LOSS_COOLDOWN")


if __name__ == "__main__":
    unittest.main()
