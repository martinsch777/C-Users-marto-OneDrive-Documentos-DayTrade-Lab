from __future__ import annotations

from dataclasses import dataclass, replace
from collections import Counter
from itertools import groupby
import math

import pandas as pd

from src.execution_simulator import ExecutionRequest, ExecutionSimulator, TradeResult
from src.psychology_guard import PsychologyGuard
from src.risk import PositionSizer, RiskManager, TradingState
from src.strategies import Signal, Strategy

from .metrics import calculate_metrics


@dataclass
class BacktestResult:
    trades: pd.DataFrame
    blocked_trades: pd.DataFrame
    metrics: dict
    final_equity: float
    blocked_count: int = 0
    block_reason_counts: dict[str, int] | None = None


class BacktestEngine:
    def __init__(
        self,
        risk_config: dict | None = None,
        execution_config: dict | None = None,
        psychology_config: dict | None = None,
    ) -> None:
        self.risk_config = risk_config or {}
        self.execution_config = execution_config or {}
        self.psychology_config = psychology_config or {}

    def run(
        self,
        frame: pd.DataFrame,
        strategy: Strategy,
        symbol: str,
        timeframe: str,
        *,
        allow_fractional: bool = False,
    ) -> BacktestResult:
        signals = strategy.generate_signals(frame, symbol, timeframe)
        return self.run_signals(
            frame,
            signals,
            allow_fractional=allow_fractional,
        )

    def run_signals(
        self,
        frame: pd.DataFrame,
        signals: list[Signal],
        *,
        allow_fractional: bool = False,
        collect_blocked_records: bool = True,
    ) -> BacktestResult:
        risk_manager = RiskManager(self.risk_config)
        sizer = PositionSizer(self.risk_config)
        guard = PsychologyGuard(self.psychology_config)
        simulator = ExecutionSimulator(self.execution_config)
        state = TradingState(
            initial_equity=risk_manager.initial_equity,
            equity=risk_manager.initial_equity,
        )
        trade_records: list[dict] = []
        blocked_records: list[dict] = []
        blocked_count = 0
        block_reason_counts: Counter[str] = Counter()
        position_open_until: pd.Timestamp | None = None

        def record_block(signal: Signal, reason: str, details: str) -> None:
            nonlocal blocked_count
            blocked_count += 1
            block_reason_counts[reason] += 1
            if collect_blocked_records:
                blocked_records.append(
                    {
                        **signal.to_record(),
                        "block_reason": reason,
                        "block_details": details,
                    }
                )

        ordered = sorted(signals, key=lambda item: item.timestamp)
        for signal_day, day_group in groupby(
            ordered,
            key=lambda item: state.day_key(item.timestamp),
        ):
            daily_signals = list(day_group)
            # Three losses stop the current session, not the laboratory forever.
            state.consecutive_losses = 0
            for index, raw_signal in enumerate(daily_signals):
                signal = (
                    replace(raw_signal, spread_bps=simulator.spread_bps)
                    if raw_signal.spread_bps == 0
                    else raw_signal
                )
                if (
                    position_open_until is not None
                    and signal.timestamp <= position_open_until
                ):
                    record_block(
                        signal,
                        "BLOCKED_POSITION_OPEN",
                        "Only one position at a time is allowed",
                    )
                    continue
                if not collect_blocked_records:
                    # Once a hard session stop is active, every later signal in
                    # this UTC day is outcome-irrelevant. Count them in one batch.
                    hard_stop: tuple[str, str] | None = None
                    if (
                        state.trades_by_day.get(signal_day, 0)
                        >= risk_manager.max_trades_per_day
                    ):
                        hard_stop = (
                            "BLOCKED_OVERTRADING",
                            "Maximum trades per day reached",
                        )
                    elif (
                        state.consecutive_losses
                        >= risk_manager.max_consecutive_losses
                    ):
                        hard_stop = (
                            "BLOCKED_MAX_CONSECUTIVE_LOSSES",
                            "Maximum consecutive losses reached",
                        )
                    elif (
                        state.daily_pnl.get(signal_day, 0.0)
                        <= -risk_manager.initial_equity
                        * risk_manager.max_daily_loss_pct
                    ):
                        hard_stop = (
                            "BLOCKED_DAILY_LOSS_LIMIT",
                            "Daily loss limit reached",
                        )
                    if hard_stop is not None:
                        remaining = len(daily_signals) - index
                        blocked_count += remaining
                        block_reason_counts[hard_stop[0]] += remaining
                        break
                guard_decision = guard.evaluate(signal, state)
                if not guard_decision.approved:
                    record_block(
                        signal,
                        guard_decision.reason,
                        guard_decision.details,
                    )
                    continue

                execution_signal = signal
                entry_preview = None
                recalculate_from_fill = bool(
                    signal.metadata.get(
                        "recalculate_risk_from_fill",
                        False,
                    )
                )
                if recalculate_from_fill:
                    preview_request = ExecutionRequest(
                        signal_timestamp=signal.timestamp,
                        side=signal.side,
                        quantity=1.0,
                        stop_loss=signal.stop_price,
                        take_profit=signal.take_profit,
                    )
                    entry_preview = simulator.preview_entry(
                        frame,
                        preview_request,
                    )
                    if entry_preview.status != "READY":
                        result = simulator.simulate(
                            frame,
                            preview_request,
                            entry_preview=entry_preview,
                        )
                        trade_records.append(
                            {
                                **signal.to_record(),
                                **result.to_record(),
                                "position_size": 0.0,
                                "risk_amount": 0.0,
                            }
                        )
                        continue

                    fill_price = float(entry_preview.price)
                    reference_price = float(signal.entry_price)
                    gap_pct = (
                        abs(fill_price - reference_price) / reference_price
                        if reference_price > 0
                        else math.inf
                    )
                    max_gap_pct = float(
                        signal.metadata.get(
                            "max_entry_gap_pct",
                            self.execution_config.get(
                                "max_entry_gap_pct",
                                math.inf,
                            ),
                        )
                    )
                    invalid_stop_side = (
                        signal.side == "long"
                        and fill_price <= signal.stop_price
                    ) or (
                        signal.side == "short"
                        and fill_price >= signal.stop_price
                    )
                    real_risk = abs(fill_price - signal.stop_price)
                    cancellation_reason = ""
                    if invalid_stop_side:
                        cancellation_reason = "CANCELLED_FILL_BEYOND_STOP"
                    elif not math.isfinite(real_risk) or real_risk <= 0:
                        cancellation_reason = "CANCELLED_INVALID_FILL_RISK"
                    elif not math.isfinite(gap_pct) or gap_pct > max_gap_pct:
                        cancellation_reason = "CANCELLED_ENTRY_GAP_LIMIT"
                    reward_r = float(
                        signal.metadata.get(
                            "reward_r",
                            signal.risk_reward,
                        )
                    )
                    if not math.isfinite(reward_r) or reward_r <= 0:
                        cancellation_reason = "CANCELLED_INVALID_REWARD_R"
                    if cancellation_reason:
                        result = TradeResult(
                            status="CANCELLED",
                            side=signal.side,
                            requested_quantity=0.0,
                            exit_reason=cancellation_reason,
                        )
                        trade_records.append(
                            {
                                **signal.to_record(),
                                **result.to_record(),
                                "position_size": 0.0,
                                "risk_amount": 0.0,
                            }
                        )
                        continue

                    target = (
                        fill_price + reward_r * real_risk
                        if signal.side == "long"
                        else fill_price - reward_r * real_risk
                    )
                    metadata = dict(signal.metadata)
                    metadata.update(
                        {
                            "signal_reference_price": reference_price,
                            "entry_gap_pct": gap_pct,
                            "reward_r": reward_r,
                        }
                    )
                    execution_signal = replace(
                        signal,
                        entry_price=fill_price,
                        take_profit=target,
                        metadata=metadata,
                    )

                quantity = sizer.calculate(
                    execution_signal,
                    state.equity,
                    allow_fractional=allow_fractional,
                )
                risk_decision = risk_manager.evaluate(
                    execution_signal,
                    quantity,
                    state,
                )
                if not risk_decision.approved:
                    record_block(
                        execution_signal,
                        risk_decision.reason,
                        risk_decision.details,
                    )
                    continue
                result = simulator.simulate(
                    frame,
                    ExecutionRequest(
                        signal_timestamp=execution_signal.timestamp,
                        side=execution_signal.side,
                        quantity=quantity,
                        stop_loss=execution_signal.stop_price,
                        take_profit=execution_signal.take_profit,
                    ),
                    entry_preview=entry_preview,
                )
                record = {
                    **execution_signal.to_record(),
                    **result.to_record(),
                    "position_size": quantity,
                    "risk_amount": quantity * execution_signal.risk_per_unit,
                }
                trade_records.append(record)
                if result.status == "FILLED" and result.exit_timestamp is not None:
                    position_open_until = result.exit_timestamp
                    state.record_trade(
                        result.exit_timestamp,
                        result.net_pnl,
                        result.filled_quantity,
                    )

        trades = pd.DataFrame(trade_records)
        blocked = pd.DataFrame(blocked_records)
        metrics = calculate_metrics(trades, risk_manager.initial_equity)
        return BacktestResult(
            trades=trades,
            blocked_trades=blocked,
            metrics=metrics,
            final_equity=state.equity,
            blocked_count=blocked_count,
            block_reason_counts=dict(block_reason_counts),
        )
