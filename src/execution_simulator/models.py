from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

import pandas as pd


OrderType = Literal["market", "limit"]


@dataclass(frozen=True)
class EntryPreview:
    status: str
    position: int | None = None
    timestamp: pd.Timestamp | None = None
    price: float = 0.0
    exit_reason: str = ""


@dataclass(frozen=True)
class ExecutionRequest:
    signal_timestamp: pd.Timestamp
    side: Literal["long", "short"]
    quantity: float
    stop_loss: float
    take_profit: float
    order_type: OrderType = "market"
    limit_price: float | None = None
    trailing_stop_pct: float | None = None
    partial_exit_fraction: float = 1.0


@dataclass
class TradeResult:
    status: str
    side: str
    requested_quantity: float
    filled_quantity: float = 0.0
    entry_timestamp: pd.Timestamp | None = None
    exit_timestamp: pd.Timestamp | None = None
    entry_price: float = 0.0
    exit_price: float = 0.0
    gross_pnl: float = 0.0
    commission: float = 0.0
    spread_cost: float = 0.0
    slippage_cost: float = 0.0
    net_pnl: float = 0.0
    exit_reason: str = ""
    partial_fill: bool = False
    partial_exit: bool = False
    bars_held: int = 0

    @property
    def total_cost(self) -> float:
        return self.commission + self.spread_cost + self.slippage_cost

    @property
    def duration_minutes(self) -> float:
        if self.entry_timestamp is None or self.exit_timestamp is None:
            return 0.0
        return (self.exit_timestamp - self.entry_timestamp).total_seconds() / 60

    def to_record(self) -> dict:
        record = asdict(self)
        for key in ("entry_timestamp", "exit_timestamp"):
            if record[key] is not None:
                record[key] = record[key].isoformat()
        record["total_cost"] = self.total_cost
        record["duration_minutes"] = self.duration_minutes
        return record
