from __future__ import annotations

import math

import pandas as pd

from src.strategies import Signal

from .models import BlockReason, Decision, TradingState


class PositionSizer:
    def __init__(self, risk_config: dict | None = None) -> None:
        config = risk_config or {}
        self.risk_per_trade_pct = float(config.get("risk_per_trade_pct", 0.005))
        self.max_exposure_pct = float(config.get("max_exposure_pct", 0.30))
        self.max_position_notional = float(
            config.get("max_position_notional", 25_000.0)
        )

    def calculate(
        self,
        signal: Signal,
        equity: float,
        *,
        allow_fractional: bool = False,
    ) -> float:
        if signal.risk_per_unit <= 0 or signal.entry_price <= 0:
            return 0.0
        risk_budget = equity * self.risk_per_trade_pct
        by_risk = risk_budget / signal.risk_per_unit
        notional_limit = min(
            self.max_position_notional,
            equity * self.max_exposure_pct,
        )
        by_notional = notional_limit / signal.entry_price
        size = min(by_risk, by_notional)
        return max(0.0, size if allow_fractional else float(math.floor(size)))


class RiskManager:
    def __init__(self, risk_config: dict | None = None) -> None:
        config = risk_config or {}
        self.initial_equity = float(config.get("initial_equity", 100_000.0))
        self.max_daily_loss_pct = float(config.get("max_daily_loss_pct", 0.015))
        self.max_weekly_loss_pct = float(config.get("max_weekly_loss_pct", 0.04))
        self.max_trades_per_day = int(config.get("max_trades_per_day", 5))
        self.max_consecutive_losses = int(config.get("max_consecutive_losses", 3))
        self.max_exposure_pct = float(config.get("max_exposure_pct", 0.30))
        self.max_position_notional = float(
            config.get("max_position_notional", 25_000.0)
        )
        self.minimum_risk_reward = float(
            config.get("minimum_risk_reward", 1.5)
        )
        self.max_spread_bps = float(config.get("max_spread_bps", 8.0))
        self.min_relative_volume = float(config.get("min_relative_volume", 0.8))
        self.max_atr_pct = float(config.get("max_atr_pct", 0.05))
        self.kill_switch = bool(config.get("kill_switch", False))

    def evaluate(
        self,
        signal: Signal,
        quantity: float,
        state: TradingState,
    ) -> Decision:
        day = state.day_key(signal.timestamp)
        week = state.week_key(signal.timestamp)
        checks = [
            (
                self.kill_switch,
                BlockReason.KILL_SWITCH,
                "Risk kill switch is active",
            ),
            (
                not signal.data_valid,
                BlockReason.MISSING_DATA,
                "Signal is based on incomplete or invalid data",
            ),
            (
                signal.stop_price <= 0 or signal.risk_per_unit <= 0,
                BlockReason.STOP_REQUIRED,
                "A valid stop loss is mandatory",
            ),
            (
                signal.risk_reward < self.minimum_risk_reward,
                BlockReason.BAD_RISK_REWARD,
                f"Risk/reward {signal.risk_reward:.2f} is below minimum",
            ),
            (
                signal.spread_bps > self.max_spread_bps,
                BlockReason.SPREAD_TOO_HIGH,
                f"Spread {signal.spread_bps:.2f} bps exceeds limit",
            ),
            (
                state.daily_pnl.get(day, 0.0)
                <= -self.initial_equity * self.max_daily_loss_pct,
                BlockReason.DAILY_LOSS_LIMIT,
                "Daily loss limit reached",
            ),
            (
                state.weekly_pnl.get(week, 0.0)
                <= -self.initial_equity * self.max_weekly_loss_pct,
                BlockReason.WEEKLY_LOSS_LIMIT,
                "Weekly loss limit reached",
            ),
            (
                state.consecutive_losses >= self.max_consecutive_losses,
                BlockReason.MAX_CONSECUTIVE_LOSSES,
                "Maximum consecutive losses reached",
            ),
            (
                state.trades_by_day.get(day, 0) >= self.max_trades_per_day,
                BlockReason.OVERTRADING,
                "Maximum trades per day reached",
            ),
            (
                signal.relative_volume > 0
                and signal.relative_volume < self.min_relative_volume,
                BlockReason.LOW_VOLUME,
                "Relative volume is below the configured floor",
            ),
            (
                signal.atr > 0
                and signal.entry_price > 0
                and signal.atr / signal.entry_price > self.max_atr_pct,
                BlockReason.ABNORMAL_VOLATILITY,
                "ATR as a percentage of price is abnormally high",
            ),
            (
                quantity * signal.entry_price > self.max_position_notional,
                BlockReason.POSITION_TOO_LARGE,
                "Position notional exceeds absolute limit",
            ),
            (
                state.open_exposure + quantity * signal.entry_price
                > state.equity * self.max_exposure_pct,
                BlockReason.MAX_EXPOSURE,
                "Position would exceed portfolio exposure limit",
            ),
        ]
        for blocked, reason, details in checks:
            if blocked:
                return Decision(False, reason.value, details)
        if quantity <= 0 or not math.isfinite(quantity):
            return Decision(
                False,
                BlockReason.POSITION_TOO_LARGE.value,
                "Position sizing produced no tradable quantity",
            )
        return Decision(True)
