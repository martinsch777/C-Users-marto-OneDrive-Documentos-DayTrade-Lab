from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass

import pandas as pd

from src.strategies import Strategy

from .engine import BacktestEngine, BacktestResult
from .metrics import calculate_metrics


def out_of_sample_backtest(
    frame: pd.DataFrame,
    strategy: Strategy,
    symbol: str,
    timeframe: str,
    engine: BacktestEngine,
    *,
    train_fraction: float = 0.70,
) -> BacktestResult:
    if not 0.5 <= train_fraction < 1:
        raise ValueError("train_fraction must be in [0.5, 1)")
    split_position = max(1, int(len(frame) * train_fraction))
    split_timestamp = frame.iloc[split_position]["timestamp"]
    signals = [
        signal
        for signal in strategy.generate_signals(frame, symbol, timeframe)
        if signal.timestamp >= split_timestamp
    ]
    return engine.run_signals(frame, signals)


def walk_forward_backtest(
    frame: pd.DataFrame,
    strategy: Strategy,
    symbol: str,
    timeframe: str,
    engine: BacktestEngine,
    *,
    minimum_training_bars: int = 200,
    test_bars: int = 100,
) -> pd.DataFrame:
    records: list[dict] = []
    fold = 0
    test_start = minimum_training_bars
    while test_start < len(frame):
        test_end = min(test_start + test_bars, len(frame))
        visible = frame.iloc[:test_end].copy()
        first_test_time = frame.iloc[test_start]["timestamp"]
        signals = [
            signal
            for signal in strategy.generate_signals(visible, symbol, timeframe)
            if signal.timestamp >= first_test_time
        ]
        result = engine.run_signals(visible, signals)
        records.append(
            {
                "fold": fold,
                "train_bars": test_start,
                "test_start": first_test_time,
                "test_end": frame.iloc[test_end - 1]["timestamp"],
                **result.metrics,
            }
        )
        fold += 1
        test_start = test_end
    return pd.DataFrame(records)


def cost_sensitivity(
    frame: pd.DataFrame,
    strategy: Strategy,
    symbol: str,
    timeframe: str,
    raw_config: dict,
    *,
    multipliers: tuple[float, ...] = (0.5, 1.0, 2.0),
) -> pd.DataFrame:
    records: list[dict] = []
    for multiplier in multipliers:
        execution = deepcopy(raw_config.get("execution", {}))
        for key in ("spread_bps", "slippage_bps", "commission_bps"):
            execution[key] = float(execution.get(key, 0.0)) * multiplier
        engine = BacktestEngine(
            raw_config.get("risk", {}),
            execution,
            raw_config.get("psychology_guard", {}),
        )
        result = engine.run(frame, strategy, symbol, timeframe)
        records.append({"cost_multiplier": multiplier, **result.metrics})
    return pd.DataFrame(records)


@dataclass(frozen=True)
class ApprovalDecision:
    approved_for_internal_paper: bool
    reasons: tuple[str, ...]


def approval_decision(
    out_of_sample_trades: pd.DataFrame,
    metrics: dict | None = None,
) -> ApprovalDecision:
    metrics = metrics or calculate_metrics(out_of_sample_trades)
    reasons: list[str] = []
    if metrics["total_return"] <= 0:
        reasons.append("Out-of-sample return is not positive")
    if metrics["profit_factor"] <= 1.25:
        reasons.append("Profit factor is not above 1.25")
    if metrics["trade_count"] < 100:
        reasons.append("Fewer than 100 out-of-sample trades")
    if metrics["max_drawdown"] > 0.20:
        reasons.append("Maximum drawdown exceeds the conservative 20% ceiling")
    filled = (
        out_of_sample_trades[out_of_sample_trades["status"] == "FILLED"].copy()
        if not out_of_sample_trades.empty and "status" in out_of_sample_trades
        else pd.DataFrame()
    )
    if not filled.empty:
        for column, label in (
            ("symbol", "asset"),
            ("strategy", "setup"),
        ):
            pnl = filled.groupby(column)["net_pnl"].sum().clip(lower=0)
            if pnl.sum() > 0 and pnl.max() / pnl.sum() > 0.70:
                reasons.append(f"More than 70% of positive PnL depends on one {label}")
        timestamps = pd.to_datetime(filled["exit_timestamp"], utc=True)
        daily = filled.assign(day=timestamps.dt.date).groupby("day")["net_pnl"].sum()
        positive = daily.clip(lower=0)
        if positive.sum() > 0 and positive.max() / positive.sum() > 0.35:
            reasons.append("More than 35% of positive PnL depends on one day")
        hours = filled.assign(hour=timestamps.dt.hour).groupby("hour")["net_pnl"].sum()
        positive_hours = hours.clip(lower=0)
        if (
            positive_hours.sum() > 0
            and positive_hours.max() / positive_hours.sum() > 0.70
        ):
            reasons.append("More than 70% of positive PnL depends on one hour")
    if metrics["cost_pct_gross_profit"] > 0.50:
        reasons.append("Trading costs consume more than 50% of gross profit")
    return ApprovalDecision(not reasons, tuple(reasons))
