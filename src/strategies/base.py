from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

import pandas as pd

from src.indicators import add_indicators


Side = Literal["long", "short"]


@dataclass(frozen=True)
class Signal:
    timestamp: pd.Timestamp
    symbol: str
    timeframe: str
    strategy: str
    side: Side
    entry_price: float
    stop_price: float
    take_profit: float
    reason: str
    relative_volume: float = 0.0
    atr: float = 0.0
    spread_bps: float = 0.0
    data_valid: bool = True
    fomo_flag: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def risk_per_unit(self) -> float:
        return abs(self.entry_price - self.stop_price)

    @property
    def reward_per_unit(self) -> float:
        return abs(self.take_profit - self.entry_price)

    @property
    def risk_reward(self) -> float:
        if self.risk_per_unit <= 0:
            return 0.0
        return self.reward_per_unit / self.risk_per_unit

    def to_record(self) -> dict[str, Any]:
        record = asdict(self)
        record["timestamp"] = self.timestamp.isoformat()
        record["risk_reward"] = self.risk_reward
        record["metadata"] = json.dumps(self.metadata, default=str, sort_keys=True)
        return record


class Strategy(ABC):
    name: str

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}

    def prepare(self, frame: pd.DataFrame) -> pd.DataFrame:
        required = {"atr", "rsi", "vwap", "ema_9", "ema_20", "relative_volume"}
        if required.issubset(frame.columns):
            return frame.copy()
        return add_indicators(
            frame,
            timezone=str(
                self.config.get("session_timezone", "America/New_York")
            ),
        )

    @abstractmethod
    def generate_signals(
        self,
        frame: pd.DataFrame,
        symbol: str,
        timeframe: str,
    ) -> list[Signal]:
        raise NotImplementedError

    @staticmethod
    def _levels(
        entry: float,
        stop: float,
        side: Side,
        risk_reward: float,
    ) -> tuple[float, float]:
        risk = abs(entry - stop)
        if risk <= 0:
            raise ValueError("Entry and stop must differ")
        target = entry + risk * risk_reward if side == "long" else entry - risk * risk_reward
        return stop, target
