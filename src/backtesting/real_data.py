from __future__ import annotations

import json
from dataclasses import replace
from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd

from src.indicators import atr, ema
from src.strategies import Signal
from src.timeframes import parse_timeframe_timedelta

from .engine import BacktestEngine, BacktestResult
from .metrics import calculate_metrics


def invalidate_signals_after_gaps(
    frame: pd.DataFrame,
    signals: list[Signal],
    timeframe: str,
    *,
    warmup_bars: int = 200,
) -> list[Signal]:
    """Mark signals near discontinuities invalid without fabricating candles."""
    if len(frame) < 2 or not signals:
        return signals
    duration = parse_timeframe_timedelta(timeframe)
    gaps = frame.loc[
        frame["timestamp"].diff() > duration,
        "timestamp",
    ].tolist()
    if not gaps:
        return signals
    windows = [
        (gap_start, gap_start + duration * warmup_bars)
        for gap_start in gaps
    ]
    adjusted: list[Signal] = []
    for signal in signals:
        affected = any(start <= signal.timestamp <= end for start, end in windows)
        if affected:
            metadata = {
                **signal.metadata,
                "data_gap_warmup_block": True,
                "gap_warmup_bars": warmup_bars,
            }
            adjusted.append(
                replace(signal, data_valid=False, metadata=metadata)
            )
        else:
            adjusted.append(signal)
    return adjusted


def add_market_context(frame: pd.DataFrame) -> pd.DataFrame:
    """Create causal UTC time, trend-regime, and volatility labels."""
    context = frame[["timestamp", "close"]].copy()
    context["timestamp"] = pd.to_datetime(context["timestamp"], utc=True)
    context["year"] = context["timestamp"].dt.year
    context["utc_hour"] = context["timestamp"].dt.hour
    context["day_of_week"] = context["timestamp"].dt.day_name()
    fast = ema(frame["close"], 50)
    slow = ema(frame["close"], 200)
    true_range = atr(frame)
    separation = (fast - slow) / true_range.replace(0, np.nan)
    context["regime"] = np.select(
        [separation > 0.5, separation < -0.5],
        ["trend_up", "trend_down"],
        default="range",
    )
    realized = frame["close"].pct_change().rolling(96, min_periods=24).std()
    baseline = realized.shift(1).rolling(2_000, min_periods=200).median()
    ratio = realized / baseline.replace(0, np.nan)
    context["volatility_bucket"] = np.select(
        [ratio >= 1.25, ratio <= 0.75],
        ["high", "low"],
        default="normal",
    )
    return context.drop(columns=["close"])


def attach_market_context(
    records: pd.DataFrame,
    context: pd.DataFrame,
) -> pd.DataFrame:
    if records.empty:
        return records.copy()
    enriched = records.copy()
    enriched["timestamp"] = pd.to_datetime(enriched["timestamp"], utc=True)
    return enriched.merge(context, on="timestamp", how="left")


def metrics_by_dimension(
    trades: pd.DataFrame,
    dimension: str,
    *,
    initial_equity: float,
) -> pd.DataFrame:
    if trades.empty or dimension not in trades.columns:
        return pd.DataFrame(columns=[dimension, "trade_count", "total_return"])
    records = []
    for value, subset in trades.groupby(dimension, dropna=False):
        records.append(
            {
                dimension: value,
                **calculate_metrics(subset, initial_equity),
                "net_pnl": float(
                    subset.loc[subset["status"] == "FILLED", "net_pnl"].sum()
                ),
            }
        )
    return pd.DataFrame(records)


def out_of_sample_from_signals(
    frame: pd.DataFrame,
    signals: list[Signal],
    engine: BacktestEngine,
    *,
    train_fraction: float = 0.70,
    allow_fractional: bool = True,
) -> BacktestResult:
    if not 0.5 <= train_fraction < 1:
        raise ValueError("train_fraction must be in [0.5, 1)")
    split_position = max(1, int(len(frame) * train_fraction))
    split_time = frame.iloc[split_position]["timestamp"]
    selected = [signal for signal in signals if signal.timestamp >= split_time]
    return engine.run_signals(
        frame,
        selected,
        allow_fractional=allow_fractional,
        collect_blocked_records=False,
    )


def walk_forward_yearly_from_signals(
    frame: pd.DataFrame,
    signals: list[Signal],
    engine: BacktestEngine,
    *,
    allow_fractional: bool = True,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    timestamps = pd.to_datetime(frame["timestamp"], utc=True)
    years = sorted(timestamps.dt.year.unique())
    summaries: list[dict] = []
    fold_trades: list[pd.DataFrame] = []
    for fold, test_year in enumerate(years[1:]):
        # Years are already chronological. A positional slice shares the
        # underlying blocks instead of materializing the indicator matrix for
        # every fold, which is important for multi-year 1m research.
        year_positions = np.flatnonzero((timestamps.dt.year <= test_year).to_numpy())
        visible = frame.iloc[: int(year_positions[-1]) + 1]
        test_signals = [
            signal for signal in signals if signal.timestamp.year == test_year
        ]
        result = engine.run_signals(
            visible,
            test_signals,
            allow_fractional=allow_fractional,
            collect_blocked_records=False,
        )
        summaries.append(
            {
                "fold": fold,
                "train_start_year": years[0],
                "train_end_year": test_year - 1,
                "test_year": test_year,
                "test_signals": len(test_signals),
                "blocked_signals": result.blocked_count,
                **result.metrics,
            }
        )
        if not result.trades.empty:
            fold_trades.append(result.trades.assign(walk_forward_year=test_year))
    return (
        pd.DataFrame(summaries),
        pd.concat(fold_trades, ignore_index=True)
        if fold_trades
        else pd.DataFrame(),
    )


def permissive_psychology_config(
    original: dict,
    setup_name: str,
) -> dict:
    config = dict(original)
    config["allowed_setups"] = list(
        set(config.get("allowed_setups", [])) | {setup_name}
    )
    config["loss_cooldown_minutes"] = 0
    config["trading_window_start"] = "00:00"
    config["trading_window_end"] = "23:59"
    config["max_trades_per_hour"] = 100_000
    config["block_fomo"] = False
    return config


PROTECTIVE_BLOCK_REASONS = {
    "BLOCKED_DAILY_LOSS_LIMIT",
    "BLOCKED_MAX_CONSECUTIVE_LOSSES",
    "BLOCKED_NO_VALID_SETUP",
    "BLOCKED_BAD_RISK_REWARD",
    "BLOCKED_SPREAD_TOO_HIGH",
    "BLOCKED_AFTER_LOSS_COOLDOWN",
    "BLOCKED_OUTSIDE_TRADING_WINDOW",
    "BLOCKED_OVERTRADING",
    "BLOCKED_FOMO",
    "BLOCKED_POSITION_OPEN",
}


def psychology_impact(
    generated_signals: int,
    guarded: BacktestResult,
    permissive: BacktestResult,
) -> tuple[dict, pd.DataFrame]:
    blocked = guarded.blocked_trades.copy()
    if blocked.empty:
        reasons = pd.DataFrame(columns=["block_reason", "count", "counterfactual_pnl"])
    else:
        counts = (
            blocked.groupby("block_reason")
            .size()
            .rename("count")
            .reset_index()
        )
        counterfactual = permissive.trades.copy()
        if not counterfactual.empty:
            counterfactual["timestamp"] = pd.to_datetime(
                counterfactual["timestamp"], utc=True
            )
            counterfactual = (
                counterfactual[counterfactual["status"] == "FILLED"]
                .groupby("timestamp", as_index=False)["net_pnl"]
                .sum()
            )
            blocked["timestamp"] = pd.to_datetime(blocked["timestamp"], utc=True)
            matched = blocked.merge(counterfactual, on="timestamp", how="left")
            by_reason = (
                matched.groupby("block_reason")["net_pnl"]
                .sum(min_count=1)
                .fillna(0.0)
                .rename("counterfactual_pnl")
                .reset_index()
            )
            reasons = counts.merge(by_reason, on="block_reason", how="left")
        else:
            reasons = counts.assign(counterfactual_pnl=0.0)
    guarded_pnl = (
        float(guarded.trades.loc[guarded.trades["status"] == "FILLED", "net_pnl"].sum())
        if not guarded.trades.empty
        else 0.0
    )
    permissive_pnl = (
        float(
            permissive.trades.loc[
                permissive.trades["status"] == "FILLED", "net_pnl"
            ].sum()
        )
        if not permissive.trades.empty
        else 0.0
    )
    protective_count = (
        int(blocked["block_reason"].isin(PROTECTIVE_BLOCK_REASONS).sum())
        if not blocked.empty
        else 0
    )
    summary = {
        "generated_signals": generated_signals,
        "allowed_attempts": len(guarded.trades),
        "blocked_signals": len(blocked),
        "allowed_rate": (
            len(guarded.trades) / generated_signals if generated_signals else 0.0
        ),
        "protective_block_count": protective_count,
        "guarded_net_pnl": guarded_pnl,
        "permissive_net_pnl": permissive_pnl,
        "guard_pnl_delta": guarded_pnl - permissive_pnl,
        "overtrading_blocks": (
            int((blocked["block_reason"] == "BLOCKED_OVERTRADING").sum())
            if not blocked.empty
            else 0
        ),
        "after_loss_blocks": (
            int(
                blocked["block_reason"]
                .isin(
                    {
                        "BLOCKED_AFTER_LOSS_COOLDOWN",
                        "BLOCKED_MAX_CONSECUTIVE_LOSSES",
                    }
                )
                .sum()
            )
            if not blocked.empty
            else 0
        ),
        "bad_risk_reward_blocks": (
            int((blocked["block_reason"] == "BLOCKED_BAD_RISK_REWARD").sum())
            if not blocked.empty
            else 0
        ),
    }
    return summary, reasons


def random_entry_signals(
    frame: pd.DataFrame,
    templates: Iterable[Signal],
    symbol: str,
    timeframe: str,
    *,
    seed: int,
    count: int | None = None,
) -> list[Signal]:
    template_list = list(templates)
    if not template_list:
        return []
    rng = np.random.default_rng(seed)
    target_count = min(
        count if count is not None else len(template_list),
        max(0, len(frame) - 22),
    )
    if target_count <= 0:
        return []
    positions = np.sort(
        rng.choice(np.arange(20, len(frame) - 1), size=target_count, replace=False)
    )
    template_indices = rng.integers(0, len(template_list), size=target_count)
    signals: list[Signal] = []
    for position, template_index in zip(positions, template_indices):
        row = frame.iloc[int(position)]
        template = template_list[int(template_index)]
        entry = float(row["close"])
        stop_pct = min(0.10, max(0.0001, template.risk_per_unit / template.entry_price))
        risk = entry * stop_pct
        side = template.side
        stop = entry - risk if side == "long" else entry + risk
        target = (
            entry + risk * template.risk_reward
            if side == "long"
            else entry - risk * template.risk_reward
        )
        signals.append(
            Signal(
                timestamp=row["timestamp"],
                symbol=symbol,
                timeframe=timeframe,
                strategy="benchmark_random_entry",
                side=side,
                entry_price=entry,
                stop_price=stop,
                take_profit=target,
                reason="Deterministic random timestamp with sampled strategy levels",
                relative_volume=1.0,
                atr=risk,
                metadata={"seed": seed, "template_strategy": template.strategy},
            )
        )
    return signals


def momentum_benchmark_signals(
    frame: pd.DataFrame,
    symbol: str,
    timeframe: str,
) -> list[Signal]:
    local_atr = atr(frame)
    prior_high = frame["high"].shift(1).rolling(20, min_periods=20).max()
    prior_low = frame["low"].shift(1).rolling(20, min_periods=20).min()
    long_mask = (frame["close"] > prior_high) & (frame["close"] > frame["open"])
    short_mask = (frame["close"] < prior_low) & (frame["close"] < frame["open"])
    signals: list[Signal] = []
    for position in np.flatnonzero((long_mask | short_mask).to_numpy()):
        if pd.isna(local_atr.iloc[position]) or local_atr.iloc[position] <= 0:
            continue
        row = frame.iloc[position]
        side = "long" if long_mask.iloc[position] else "short"
        entry = float(row["close"])
        risk = float(local_atr.iloc[position])
        signals.append(
            Signal(
                timestamp=row["timestamp"],
                symbol=symbol,
                timeframe=timeframe,
                strategy="benchmark_simple_momentum",
                side=side,
                entry_price=entry,
                stop_price=entry - risk if side == "long" else entry + risk,
                take_profit=entry + 2 * risk if side == "long" else entry - 2 * risk,
                reason="Unfiltered 20-bar breakout benchmark",
                relative_volume=1.0,
                atr=risk,
            )
        )
    return signals


def intraday_buy_hold_trades(
    frame: pd.DataFrame,
    symbol: str,
    timeframe: str,
    execution_config: dict,
    *,
    notional: float = 25_000.0,
) -> pd.DataFrame:
    data = frame.copy()
    data["_day"] = pd.to_datetime(data["timestamp"], utc=True).dt.date
    spread = float(execution_config.get("spread_bps", 0.0))
    slippage = float(execution_config.get("slippage_bps", 0.0))
    commission_bps = float(execution_config.get("commission_bps", 0.0))
    adverse = spread / 2 + slippage
    records: list[dict] = []
    for _, session in data.groupby("_day", sort=True):
        first = session.iloc[0]
        last = session.iloc[-1]
        reference_entry = float(first["open"])
        reference_exit = float(last["close"])
        entry = reference_entry * (1 + adverse / 10_000)
        exit_price = reference_exit * (1 - adverse / 10_000)
        quantity = notional / entry
        commission = (
            (entry + exit_price) * quantity * commission_bps / 10_000
        )
        gross_pnl = (exit_price - entry) * quantity
        spread_cost = (
            (reference_entry + reference_exit)
            * quantity
            * (spread / 2)
            / 10_000
        )
        slippage_cost = (
            (reference_entry + reference_exit)
            * quantity
            * slippage
            / 10_000
        )
        records.append(
            {
                "timestamp": first["timestamp"],
                "symbol": symbol,
                "timeframe": timeframe,
                "strategy": "benchmark_intraday_buy_hold",
                "status": "FILLED",
                "entry_timestamp": first["timestamp"],
                "exit_timestamp": last["timestamp"],
                "entry_price": entry,
                "exit_price": exit_price,
                "gross_pnl": gross_pnl,
                "commission": commission,
                "spread_cost": spread_cost,
                "slippage_cost": slippage_cost,
                "total_cost": commission + spread_cost + slippage_cost,
                "net_pnl": gross_pnl - commission,
                "duration_minutes": (
                    last["timestamp"] - first["timestamp"]
                ).total_seconds()
                / 60,
                "exit_reason": "UTC_DAY_CLOSE",
            }
        )
    return pd.DataFrame(records)


@dataclass(frozen=True)
class ReplayCandidateDecision:
    strategy: str
    status: str
    candidate_for_replay: bool
    candidate_for_internal_paper: bool
    reasons: tuple[str, ...]
    metrics: dict

    def to_record(self) -> dict:
        return {
            "strategy": self.strategy,
            "status": self.status,
            "candidate_for_replay": self.candidate_for_replay,
            "candidate_for_internal_paper": False,
            "reasons": json.dumps(self.reasons, ensure_ascii=False),
            **self.metrics,
        }


ECONOMIC_RATIONALES = {
    "opening_range_breakout": "Tests information discovery after the UTC session boundary.",
    "vwap_pullback": "Tests continuation after reversion toward volume-weighted fair value.",
    "relative_volume_momentum": "Tests price discovery supported by unusual participation.",
    "extreme_mean_reversion": "Tests exhaustion after statistically large VWAP displacement.",
    "trend_day_continuation": "Tests continuation after an orderly pullback in an aligned trend.",
}


def evaluate_replay_candidate(
    strategy: str,
    normal_oos_trades: pd.DataFrame,
    high_cost_oos_trades: pd.DataFrame,
    *,
    dataset_count: int,
    initial_equity: float,
    guard_allowed_rate: float,
    maximum_dataset_drawdown: float,
) -> ReplayCandidateDecision:
    capital_base = initial_equity * max(1, dataset_count)
    metrics = calculate_metrics(normal_oos_trades, capital_base)
    high_metrics = calculate_metrics(high_cost_oos_trades, capital_base)
    metrics = {
        **metrics,
        "high_cost_total_return": high_metrics["total_return"],
        "high_cost_profit_factor": high_metrics["profit_factor"],
        "guard_allowed_rate": guard_allowed_rate,
        "maximum_dataset_drawdown": maximum_dataset_drawdown,
        "economic_rationale": ECONOMIC_RATIONALES.get(strategy, ""),
    }
    reasons: list[str] = []
    if metrics["total_return"] <= 0:
        reasons.append("OOS net result is not positive")
    if metrics["profit_factor"] <= 1.25:
        reasons.append("OOS profit factor is not above 1.25")
    if metrics["trade_count"] < 100:
        reasons.append("Fewer than 100 real historical OOS trades")
    if metrics["expectancy"] <= 0:
        reasons.append("OOS expectancy is not positive")
    if metrics["high_cost_total_return"] <= 0:
        reasons.append("High costs destroy the OOS result")
    if maximum_dataset_drawdown > 0.20:
        reasons.append("A dataset drawdown exceeds 20%")
    if guard_allowed_rate < 0.50:
        reasons.append("Psychology Guard blocks a majority of signals")
    if not ECONOMIC_RATIONALES.get(strategy):
        reasons.append("No explicit economic rationale is documented")

    filled = (
        normal_oos_trades[normal_oos_trades["status"] == "FILLED"].copy()
        if not normal_oos_trades.empty
        else pd.DataFrame()
    )
    if not filled.empty:
        timestamp = pd.to_datetime(filled["exit_timestamp"], utc=True)
        filled["year"] = timestamp.dt.year
        filled["utc_hour"] = timestamp.dt.hour
        positive_total = float(filled["net_pnl"].clip(lower=0).sum())
        for column, label, threshold in (
            ("symbol", "asset", 0.70),
            ("year", "year", 0.50),
            ("utc_hour", "UTC hour", 0.50),
        ):
            positive = filled.groupby(column)["net_pnl"].sum().clip(lower=0)
            if (
                positive_total > 0
                and not positive.empty
                and positive.max() / positive_total > threshold
            ):
                reasons.append(f"Positive OOS PnL depends too much on one {label}")
        if positive_total > 0:
            largest_trade_share = (
                float(filled["net_pnl"].clip(lower=0).max()) / positive_total
            )
            metrics["largest_positive_trade_share"] = largest_trade_share
            if largest_trade_share > 0.25:
                reasons.append("One trade contributes more than 25% of positive OOS PnL")
    candidate = not reasons
    if candidate:
        status = "candidate_for_replay"
    elif metrics["total_return"] <= 0 or metrics["profit_factor"] < 1.0:
        status = "discarded"
    else:
        status = "needs_more_testing"
    return ReplayCandidateDecision(
        strategy=strategy,
        status=status,
        candidate_for_replay=candidate,
        candidate_for_internal_paper=False,
        reasons=tuple(reasons),
        metrics=metrics,
    )
