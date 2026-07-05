from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

import pandas as pd


class BlockReason(str, Enum):
    KILL_SWITCH = "BLOCKED_KILL_SWITCH"
    DAILY_LOSS_LIMIT = "BLOCKED_DAILY_LOSS_LIMIT"
    WEEKLY_LOSS_LIMIT = "BLOCKED_WEEKLY_LOSS_LIMIT"
    MAX_CONSECUTIVE_LOSSES = "BLOCKED_MAX_CONSECUTIVE_LOSSES"
    NO_VALID_SETUP = "BLOCKED_NO_VALID_SETUP"
    BAD_RISK_REWARD = "BLOCKED_BAD_RISK_REWARD"
    SPREAD_TOO_HIGH = "BLOCKED_SPREAD_TOO_HIGH"
    AFTER_LOSS_COOLDOWN = "BLOCKED_AFTER_LOSS_COOLDOWN"
    OUTSIDE_TRADING_WINDOW = "BLOCKED_OUTSIDE_TRADING_WINDOW"
    OVERTRADING = "BLOCKED_OVERTRADING"
    ABNORMAL_VOLATILITY = "BLOCKED_ABNORMAL_VOLATILITY"
    LOW_VOLUME = "BLOCKED_LOW_VOLUME"
    MISSING_DATA = "BLOCKED_MISSING_DATA"
    STOP_REQUIRED = "BLOCKED_STOP_REQUIRED"
    MAX_EXPOSURE = "BLOCKED_MAX_EXPOSURE"
    POSITION_TOO_LARGE = "BLOCKED_POSITION_TOO_LARGE"
    STOP_MOVED_AWAY = "BLOCKED_STOP_MOVED_AWAY"
    SIZE_INCREASED_AFTER_LOSS = "BLOCKED_SIZE_INCREASED_AFTER_LOSS"
    FOMO = "BLOCKED_FOMO"
    UNFAVORABLE_REGIME = "BLOCKED_UNFAVORABLE_REGIME"


@dataclass(frozen=True)
class Decision:
    approved: bool
    reason: str = "APPROVED"
    details: str = ""


@dataclass
class TradingState:
    initial_equity: float
    equity: float
    daily_pnl: dict[str, float] = field(default_factory=dict)
    weekly_pnl: dict[str, float] = field(default_factory=dict)
    consecutive_losses: int = 0
    trades_by_day: dict[str, int] = field(default_factory=dict)
    trade_timestamps: list[pd.Timestamp] = field(default_factory=list)
    last_loss_timestamp: pd.Timestamp | None = None
    last_trade_quantity: float = 0.0
    last_trade_was_loss: bool = False
    open_exposure: float = 0.0

    @staticmethod
    def day_key(timestamp: pd.Timestamp) -> str:
        return timestamp.strftime("%Y-%m-%d")

    @staticmethod
    def week_key(timestamp: pd.Timestamp) -> str:
        iso = timestamp.isocalendar()
        return f"{iso.year}-W{iso.week:02d}"

    def record_trade(
        self,
        timestamp: pd.Timestamp,
        pnl: float,
        quantity: float,
    ) -> None:
        day = self.day_key(timestamp)
        week = self.week_key(timestamp)
        self.equity += pnl
        self.daily_pnl[day] = self.daily_pnl.get(day, 0.0) + pnl
        self.weekly_pnl[week] = self.weekly_pnl.get(week, 0.0) + pnl
        self.trades_by_day[day] = self.trades_by_day.get(day, 0) + 1
        self.trade_timestamps.append(timestamp)
        self.last_trade_quantity = quantity
        self.last_trade_was_loss = pnl < 0
        if pnl < 0:
            self.consecutive_losses += 1
            self.last_loss_timestamp = timestamp
        else:
            self.consecutive_losses = 0
