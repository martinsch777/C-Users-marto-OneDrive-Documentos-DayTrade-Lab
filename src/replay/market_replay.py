from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterator

import pandas as pd

from src.psychology_guard import PsychologyGuard
from src.risk import PositionSizer, RiskManager, TradingState
from src.strategies import Strategy


@dataclass(frozen=True)
class ReplayEvent:
    session_id: str
    timestamp: pd.Timestamp
    symbol: str
    setup: str
    side: str
    entry: float
    stop: float
    take_profit: float
    size: float
    valid: bool
    decision_reason: str

    def to_record(self) -> dict:
        record = asdict(self)
        record["timestamp"] = self.timestamp.isoformat()
        return record


class MarketReplay:
    """Candle-by-candle replay; strategies only receive data visible at each step."""

    def __init__(
        self,
        risk_config: dict | None = None,
        psychology_config: dict | None = None,
    ) -> None:
        self.risk_manager = RiskManager(risk_config)
        self.sizer = PositionSizer(risk_config)
        self.guard = PsychologyGuard(psychology_config)

    def iter_events(
        self,
        frame: pd.DataFrame,
        strategy: Strategy,
        symbol: str,
        timeframe: str,
        *,
        session_id: str,
        warmup_bars: int = 20,
    ) -> Iterator[ReplayEvent]:
        state = TradingState(
            initial_equity=self.risk_manager.initial_equity,
            equity=self.risk_manager.initial_equity,
        )
        for position in range(warmup_bars, len(frame)):
            visible = frame.iloc[: position + 1].copy()
            current_time = visible.iloc[-1]["timestamp"]
            current_signals = [
                signal
                for signal in strategy.generate_signals(visible, symbol, timeframe)
                if signal.timestamp == current_time
            ]
            for signal in current_signals:
                size = self.sizer.calculate(signal, state.equity)
                guard_decision = self.guard.evaluate(signal, state)
                risk_decision = self.risk_manager.evaluate(signal, size, state)
                decision = guard_decision if not guard_decision.approved else risk_decision
                yield ReplayEvent(
                    session_id=session_id,
                    timestamp=signal.timestamp,
                    symbol=symbol,
                    setup=signal.strategy,
                    side=signal.side,
                    entry=signal.entry_price,
                    stop=signal.stop_price,
                    take_profit=signal.take_profit,
                    size=size,
                    valid=decision.approved,
                    decision_reason=decision.reason,
                )

    def run(self, *args, **kwargs) -> pd.DataFrame:
        records = [event.to_record() for event in self.iter_events(*args, **kwargs)]
        return pd.DataFrame(records)
