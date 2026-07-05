from __future__ import annotations

import math

import numpy as np
import pandas as pd


def _loss_streak(values: pd.Series) -> int:
    maximum = current = 0
    for value in values:
        if value < 0:
            current += 1
            maximum = max(maximum, current)
        else:
            current = 0
    return maximum


def _label_extreme(
    frame: pd.DataFrame,
    group_column: str,
    *,
    best: bool,
) -> str:
    if group_column not in frame.columns or frame.empty:
        return ""
    grouped = frame.groupby(group_column)["net_pnl"].sum()
    if grouped.empty:
        return ""
    return str(grouped.idxmax() if best else grouped.idxmin())


def calculate_metrics(
    trades: pd.DataFrame,
    initial_equity: float = 100_000.0,
) -> dict:
    if trades.empty or "status" not in trades.columns:
        return {
            "total_return": 0.0,
            "average_daily_return": 0.0,
            "max_drawdown": 0.0,
            "profit_factor": 0.0,
            "win_rate": 0.0,
            "expectancy": 0.0,
            "sharpe": 0.0,
            "sortino": 0.0,
            "calmar": 0.0,
            "trade_count": 0,
            "trades_per_day": 0.0,
            "best_trade": 0.0,
            "worst_trade": 0.0,
            "max_losing_streak": 0,
            "average_minutes_in_trade": 0.0,
            "total_cost": 0.0,
            "cost_pct_gross_profit": 0.0,
            "estimated_slippage": 0.0,
            "maximum_daily_loss": 0.0,
            "positive_days": 0,
            "negative_days": 0,
            "best_hour": "",
            "worst_hour": "",
            "best_setup": "",
            "worst_setup": "",
            "best_asset": "",
            "worst_asset": "",
            "best_timeframe": "",
            "worst_timeframe": "",
        }
    filled = trades[trades["status"] == "FILLED"].copy()
    if filled.empty:
        return calculate_metrics(pd.DataFrame(), initial_equity)
    filled["exit_timestamp"] = pd.to_datetime(filled["exit_timestamp"], utc=True)
    filled["day"] = filled["exit_timestamp"].dt.date
    filled["hour"] = filled["exit_timestamp"].dt.hour
    daily_pnl = filled.groupby("day")["net_pnl"].sum()
    daily_returns = daily_pnl / initial_equity
    equity_curve = initial_equity + filled["net_pnl"].cumsum()
    peaks = equity_curve.cummax()
    drawdowns = (equity_curve - peaks) / peaks
    gross_profit = float(filled.loc[filled["net_pnl"] > 0, "net_pnl"].sum())
    gross_loss = abs(float(filled.loc[filled["net_pnl"] < 0, "net_pnl"].sum()))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else (
        float("inf") if gross_profit > 0 else 0.0
    )
    daily_std = float(daily_returns.std(ddof=1)) if len(daily_returns) > 1 else 0.0
    sharpe = (
        float(daily_returns.mean()) / daily_std * math.sqrt(252)
        if daily_std > 0
        else 0.0
    )
    downside = daily_returns[daily_returns < 0]
    downside_std = float(downside.std(ddof=1)) if len(downside) > 1 else 0.0
    sortino = (
        float(daily_returns.mean()) / downside_std * math.sqrt(252)
        if downside_std > 0
        else 0.0
    )
    total_return = float(filled["net_pnl"].sum()) / initial_equity
    max_drawdown = abs(float(drawdowns.min()))
    annualized_return = float(daily_returns.mean()) * 252
    total_cost = float(filled.get("total_cost", pd.Series(dtype=float)).sum())
    return {
        "total_return": total_return,
        "average_daily_return": float(daily_returns.mean()),
        "max_drawdown": max_drawdown,
        "profit_factor": profit_factor,
        "win_rate": float((filled["net_pnl"] > 0).mean()),
        "expectancy": float(filled["net_pnl"].mean()),
        "sharpe": sharpe,
        "sortino": sortino,
        "calmar": annualized_return / max_drawdown if max_drawdown > 0 else 0.0,
        "trade_count": int(len(filled)),
        "trades_per_day": float(len(filled) / max(1, len(daily_pnl))),
        "best_trade": float(filled["net_pnl"].max()),
        "worst_trade": float(filled["net_pnl"].min()),
        "max_losing_streak": _loss_streak(filled["net_pnl"]),
        "average_minutes_in_trade": float(filled["duration_minutes"].mean()),
        "total_cost": total_cost,
        "cost_pct_gross_profit": total_cost / gross_profit if gross_profit > 0 else 0.0,
        "estimated_slippage": float(
            filled.get("slippage_cost", pd.Series(dtype=float)).sum()
        ),
        "maximum_daily_loss": float(min(0.0, daily_pnl.min())),
        "positive_days": int((daily_pnl > 0).sum()),
        "negative_days": int((daily_pnl < 0).sum()),
        "best_hour": _label_extreme(filled, "hour", best=True),
        "worst_hour": _label_extreme(filled, "hour", best=False),
        "best_setup": _label_extreme(filled, "strategy", best=True),
        "worst_setup": _label_extreme(filled, "strategy", best=False),
        "best_asset": _label_extreme(filled, "symbol", best=True),
        "worst_asset": _label_extreme(filled, "symbol", best=False),
        "best_timeframe": _label_extreme(filled, "timeframe", best=True),
        "worst_timeframe": _label_extreme(filled, "timeframe", best=False),
    }


def compare_strategies(
    trades: pd.DataFrame,
    initial_equity: float = 100_000.0,
) -> pd.DataFrame:
    if trades.empty or "strategy" not in trades.columns:
        return pd.DataFrame(columns=["strategy", "trade_count", "total_return"])
    records = []
    for strategy, subset in trades.groupby("strategy"):
        records.append({"strategy": strategy, **calculate_metrics(subset, initial_equity)})
    return pd.DataFrame(records).sort_values(
        ["profit_factor", "total_return"],
        ascending=False,
    )
