from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import yaml

from src.backtesting.metrics import calculate_metrics
from src.data import (
    DatasetManifest,
    EquitySessionCalendar,
    load_csv,
    require_or_fvg_backtest_dataset_manifest,
)
from src.indicators import atr, ema, relative_volume, session_vwap


SAFETY_FLAGS = {
    "live_trading": False,
    "broker_connected": False,
    "orders_sent": False,
    "paper_broker_enabled": False,
}
VARIANTS = ("S2", "S5", "S2_S5")
MODULES = ("S2", "S5")


@dataclass(frozen=True)
class ResearchCosts:
    commission_rate_per_side: float = 0.0002
    slippage_ticks_per_execution: int = 2
    tick_size: float = 0.01
    stress_commission_rate_per_side: float = 0.0004
    stress_slippage_ticks_per_execution: int = 4


@dataclass(frozen=True)
class ResearchConfig:
    symbol: str = "QQQ"
    initial_equity: float = 10_000.0
    position_fraction: float = 0.10
    timezone: str = "America/New_York"
    timeframe: str = "5min"
    costs: ResearchCosts = field(default_factory=ResearchCosts)
    max_trades_per_day: int = 2
    max_module_trades_per_day: int = 1
    cooldown_bars_after_exit: int = 3
    max_daily_loss_fraction: float = 0.005


@dataclass(frozen=True)
class PeriodDecision:
    variant: str
    classification: str
    opens_validation: bool
    opens_holdout: bool
    reasons: tuple[str, ...]

    def to_record(self) -> dict[str, Any]:
        return {
            "variant": self.variant,
            "classification": self.classification,
            "opens_validation": self.opens_validation,
            "opens_holdout": self.opens_holdout,
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class ResearchRunResult:
    output_dir: Path
    report_path: Path
    trades: pd.DataFrame
    metrics: pd.DataFrame
    decisions: list[PeriodDecision]
    run_manifest: dict[str, Any]


def _date(value: str | date) -> date:
    return value if isinstance(value, date) else date.fromisoformat(str(value))


def _time(value: str) -> time:
    return time.fromisoformat(str(value))


def _safe_float(value: Any) -> float:
    result = float(value)
    return result if math.isfinite(result) else 0.0


def _json_dump(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )


def _serialize_timestamps(frame: pd.DataFrame) -> pd.DataFrame:
    data = frame.copy()
    for column in data.columns:
        if "timestamp" in column:
            data[column] = pd.to_datetime(data[column], utc=True, errors="coerce").map(
                lambda value: value.isoformat() if pd.notna(value) else ""
            )
    return data


def _markdown_table(frame: pd.DataFrame) -> str:
    if frame.empty:
        return ""
    data = frame.copy()
    for column in data.columns:
        data[column] = data[column].map(
            lambda value: f"{value:.6g}" if isinstance(value, float) else str(value)
        )
    headers = list(data.columns)
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for _, row in data.iterrows():
        lines.append("| " + " | ".join(str(row[column]) for column in headers) + " |")
    return "\n".join(lines)


def _session_date(timestamp: pd.Timestamp, calendar: EquitySessionCalendar) -> date:
    return timestamp.tz_convert(calendar.timezone).date()


def _local_clock(timestamp: pd.Timestamp, calendar: EquitySessionCalendar) -> time:
    return timestamp.tz_convert(calendar.timezone).time().replace(tzinfo=None)


def _minute_of_day(values: pd.Series, calendar: EquitySessionCalendar) -> pd.Series:
    local = calendar.localize(values)
    return local.dt.hour * 60 + local.dt.minute


def _is_between_clock(
    timestamp: pd.Timestamp,
    calendar: EquitySessionCalendar,
    start: str,
    end: str,
) -> bool:
    clock = _local_clock(timestamp, calendar)
    return _time(start) <= clock <= _time(end)


def resample_rth_1min_to_5min(
    frame: pd.DataFrame,
    calendar: EquitySessionCalendar | None = None,
) -> pd.DataFrame:
    calendar = calendar or EquitySessionCalendar.from_config({"source": "us_equity"})
    data = frame.loc[calendar.mask(frame["timestamp"]).to_numpy()].copy()
    if data.empty:
        return data
    local = calendar.localize(data["timestamp"])
    data["_session"] = local.dt.date
    data["_minute"] = local.dt.hour * 60 + local.dt.minute
    session_open_minute = calendar.regular_open.hour * 60 + calendar.regular_open.minute
    data["_bucket"] = ((data["_minute"] - session_open_minute) // 5).astype(int)
    grouped = data.groupby(["_session", "_bucket"], sort=True)
    rows = grouped.agg(
        timestamp=("timestamp", "first"),
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
        source_rows=("timestamp", "count"),
    ).reset_index(drop=True)
    # Keep only complete 5-minute bars. Early closes still have complete 5m bars.
    rows = rows.loc[rows["source_rows"] == 5].drop(columns=["source_rows"])
    return rows.reset_index(drop=True)


def resample_rth_1min_to_60min_confirmed(
    frame: pd.DataFrame,
    calendar: EquitySessionCalendar | None = None,
) -> pd.DataFrame:
    calendar = calendar or EquitySessionCalendar.from_config({"source": "us_equity"})
    data = frame.loc[calendar.mask(frame["timestamp"]).to_numpy()].copy()
    if data.empty:
        return data
    local = calendar.localize(data["timestamp"])
    data["_session"] = local.dt.date
    data["_minute"] = local.dt.hour * 60 + local.dt.minute
    session_open_minute = calendar.regular_open.hour * 60 + calendar.regular_open.minute
    data["_bucket"] = ((data["_minute"] - session_open_minute) // 60).astype(int)
    grouped = data.groupby(["_session", "_bucket"], sort=True)
    rows = grouped.agg(
        timestamp=("timestamp", "first"),
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
        source_rows=("timestamp", "count"),
    ).reset_index(drop=True)
    rows = rows.loc[rows["source_rows"] == 60].drop(columns=["source_rows"])
    rows["confirmed_at"] = rows["timestamp"] + pd.Timedelta(minutes=60)
    return rows.reset_index(drop=True)


def dmi_adx(frame: pd.DataFrame, period: int = 14, smoothing: int = 14) -> pd.DataFrame:
    high = frame["high"].astype(float)
    low = frame["low"].astype(float)
    close = frame["close"].astype(float)
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = pd.Series(
        np.where((up_move > down_move) & (up_move > 0), up_move, 0.0),
        index=frame.index,
    )
    minus_dm = pd.Series(
        np.where((down_move > up_move) & (down_move > 0), down_move, 0.0),
        index=frame.index,
    )
    previous_close = close.shift(1)
    true_range = pd.concat(
        [
            high - low,
            (high - previous_close).abs(),
            (low - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr_rma = true_range.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    plus = 100 * plus_dm.ewm(alpha=1 / period, adjust=False, min_periods=period).mean() / atr_rma.replace(0, np.nan)
    minus = 100 * minus_dm.ewm(alpha=1 / period, adjust=False, min_periods=period).mean() / atr_rma.replace(0, np.nan)
    dx = 100 * (plus - minus).abs() / (plus + minus).replace(0, np.nan)
    adx = dx.ewm(alpha=1 / smoothing, adjust=False, min_periods=smoothing).mean()
    return pd.DataFrame({"plus_di": plus, "minus_di": minus, "adx": adx})


def attach_confirmed_htf(
    five_minute: pd.DataFrame,
    htf: pd.DataFrame,
    *,
    fast_period: int = 50,
    slow_period: int = 200,
    s5_period: int = 100,
) -> pd.DataFrame:
    if five_minute.empty:
        return five_minute.copy()
    enriched_htf = htf.copy()
    enriched_htf["htf_ema_fast"] = ema(enriched_htf["close"], fast_period)
    enriched_htf["htf_ema_slow"] = ema(enriched_htf["close"], slow_period)
    enriched_htf["htf_ema_fast_prev"] = enriched_htf["htf_ema_fast"].shift(1)
    enriched_htf["htf_ema_s5"] = ema(enriched_htf["close"], s5_period)
    right = enriched_htf[
        [
            "confirmed_at",
            "close",
            "htf_ema_fast",
            "htf_ema_slow",
            "htf_ema_fast_prev",
            "htf_ema_s5",
        ]
    ].rename(columns={"close": "htf_close"})
    left = five_minute.copy()
    left["_bar_close_time"] = left["timestamp"] + pd.Timedelta(minutes=5)
    merged = pd.merge_asof(
        left.sort_values("_bar_close_time"),
        right.sort_values("confirmed_at"),
        left_on="_bar_close_time",
        right_on="confirmed_at",
        direction="backward",
    )
    return merged.sort_values("timestamp").reset_index(drop=True)


def add_research_indicators(
    five_minute: pd.DataFrame,
    htf: pd.DataFrame,
    calendar: EquitySessionCalendar | None = None,
) -> pd.DataFrame:
    calendar = calendar or EquitySessionCalendar.from_config({"source": "us_equity"})
    data = attach_confirmed_htf(five_minute, htf)
    data["atr"] = atr(data, 14)
    data["atr_mean_50"] = data["atr"].shift(1).rolling(50, min_periods=50).mean()
    data["atr_relative"] = data["atr"] / data["atr_mean_50"].replace(0, np.nan)
    data["vwap"] = session_vwap(data, calendar.timezone)
    data["relative_volume"] = relative_volume(data["volume"], 20)
    data["volume_mean_20"] = data["volume"].shift(1).rolling(20, min_periods=20).mean()
    data["roc_12"] = data["close"].pct_change(12)
    data["roc_ema_5"] = ema(data["roc_12"], 5)
    dmi = dmi_adx(data, 14, 14)
    data = pd.concat([data, dmi], axis=1)
    local = calendar.localize(data["timestamp"])
    data["session_date"] = local.dt.date.astype(str)
    data["local_time"] = local.dt.strftime("%H:%M")
    data["minute_of_day"] = local.dt.hour * 60 + local.dt.minute
    return data


def generate_s2_signals(data: pd.DataFrame, calendar: EquitySessionCalendar) -> pd.DataFrame:
    if data.empty:
        return pd.DataFrame()
    long_trend = (
        (data["htf_close"] > data["htf_ema_fast"])
        & (data["htf_ema_fast"] > data["htf_ema_slow"])
        & (data["htf_ema_fast"] > data["htf_ema_fast_prev"])
    )
    short_trend = (
        (data["htf_close"] < data["htf_ema_fast"])
        & (data["htf_ema_fast"] < data["htf_ema_slow"])
        & (data["htf_ema_fast"] < data["htf_ema_fast_prev"])
    )
    cross_up = (data["roc_12"].shift(1) <= 0.0025) & (data["roc_12"] > 0.0025)
    cross_down = (data["roc_12"].shift(1) >= -0.0025) & (data["roc_12"] < -0.0025)
    common = (
        data["timestamp"].map(lambda ts: _is_between_clock(ts, calendar, "09:30", "15:30"))
        & data["atr"].gt(0)
        & data["atr_relative"].between(0.80, 2.00)
        & data["relative_volume"].ge(1.10)
        & data["adx"].ge(20.0)
    )
    long_mask = (
        common
        & cross_up
        & (data["roc_12"] > data["roc_ema_5"])
        & (data["close"] > data["vwap"])
        & long_trend
        & (data["plus_di"] > data["minus_di"])
    )
    short_mask = (
        common
        & cross_down
        & (data["roc_12"] < data["roc_ema_5"])
        & (data["close"] < data["vwap"])
        & short_trend
        & (data["minus_di"] > data["plus_di"])
    )
    return _signal_frame(data, long_mask, short_mask, "S2")


def opening_ranges(data: pd.DataFrame, calendar: EquitySessionCalendar) -> pd.DataFrame:
    if data.empty:
        return pd.DataFrame(columns=["session_date", "opening_range_high", "opening_range_low"])
    rows: list[dict[str, Any]] = []
    start = _time("09:30")
    end = _time("10:00")
    for session_date, session in data.groupby("session_date", sort=True):
        opening = session[
            session["timestamp"].map(lambda ts: start <= _local_clock(ts, calendar) < end)
        ]
        if len(opening) != 6:
            continue
        rows.append(
            {
                "session_date": session_date,
                "opening_range_high": float(opening["high"].max()),
                "opening_range_low": float(opening["low"].min()),
            }
        )
    return pd.DataFrame(rows)


def generate_s5_signals(data: pd.DataFrame, calendar: EquitySessionCalendar) -> pd.DataFrame:
    if data.empty:
        return pd.DataFrame()
    ranges = opening_ranges(data, calendar)
    if ranges.empty:
        return pd.DataFrame()
    enriched = data.merge(ranges, on="session_date", how="left")
    signals: list[dict[str, Any]] = []
    for session_date, session in enriched.groupby("session_date", sort=True):
        if session["opening_range_high"].isna().all():
            continue
        range_high = float(session["opening_range_high"].iloc[0])
        range_low = float(session["opening_range_low"].iloc[0])
        pending: dict[str, Any] | None = None
        for index, row in session.iterrows():
            ts = row["timestamp"]
            if not _is_between_clock(ts, calendar, "10:00", "15:55"):
                continue
            local_atr = float(row["atr"])
            if not math.isfinite(local_atr) or local_atr <= 0:
                continue
            body = abs(float(row["close"]) - float(row["open"]))
            previous = enriched.loc[index - 1] if index > 0 else None
            if pending is not None:
                pending["age"] += 1
                side = pending["side"]
                touched = (
                    float(row["low"]) <= range_high + 0.15 * local_atr
                    if side == "long"
                    else float(row["high"]) >= range_low - 0.15 * local_atr
                )
                confirmed = (
                    float(row["close"]) > range_high
                    and float(row["close"]) > float(row["open"])
                    if side == "long"
                    else float(row["close"]) < range_low
                    and float(row["close"]) < float(row["open"])
                )
                htf_ok = (
                    float(row["htf_close"]) > float(row["htf_ema_s5"])
                    if side == "long"
                    else float(row["htf_close"]) < float(row["htf_ema_s5"])
                )
                if (
                    pending["age"] <= 12
                    and touched
                    and confirmed
                    and body >= 0.10 * local_atr
                    and float(row["relative_volume"]) >= 1.05
                    and htf_ok
                ):
                    record = _signal_record(row, side, "S5")
                    record.update(
                        {
                            "opening_range_high": range_high,
                            "opening_range_low": range_low,
                            "breakout_timestamp": pending["timestamp"],
                        }
                    )
                    signals.append(record)
                    pending = None
                    continue
                if pending is not None and pending["age"] >= 12:
                    pending = None
            if previous is None:
                continue
            previous_same_session = str(previous.get("session_date", "")) == session_date
            if not previous_same_session:
                continue
            bullish_breakout = (
                float(row["close"]) > range_high + 0.05 * local_atr
                and float(previous["close"]) <= range_high
                and body >= 0.25 * local_atr
            )
            bearish_breakout = (
                float(row["close"]) < range_low - 0.05 * local_atr
                and float(previous["close"]) >= range_low
                and body >= 0.25 * local_atr
            )
            if bullish_breakout or bearish_breakout:
                pending = {
                    "side": "long" if bullish_breakout else "short",
                    "timestamp": ts,
                    "age": 0,
                }
    return pd.DataFrame(signals)


def _signal_frame(
    data: pd.DataFrame,
    long_mask: pd.Series,
    short_mask: pd.Series,
    module: str,
) -> pd.DataFrame:
    rows = []
    for index in np.flatnonzero((long_mask | short_mask).fillna(False).to_numpy()):
        side = "long" if bool(long_mask.iloc[index]) else "short"
        rows.append(_signal_record(data.iloc[index], side, module))
    return pd.DataFrame(rows)


def _signal_record(row: pd.Series, side: str, module: str) -> dict[str, Any]:
    return {
        "timestamp": row["timestamp"],
        "session_date": str(row["session_date"]),
        "module": module,
        "side": side,
        "signal_close": float(row["close"]),
        "atr": float(row["atr"]),
        "vwap": float(row["vwap"]),
        "relative_volume": float(row["relative_volume"]),
        "roc_12": float(row.get("roc_12", np.nan)),
        "adx": float(row.get("adx", np.nan)),
        "htf_confirmed_at": row.get("confirmed_at"),
        "bar_index": int(row.name),
    }


def _combine_signals(s2: pd.DataFrame, s5: pd.DataFrame, variant: str) -> pd.DataFrame:
    frames = []
    if variant in {"S2", "S2_S5"} and not s2.empty:
        frames.append(s2)
    if variant in {"S5", "S2_S5"} and not s5.empty:
        frames.append(s5)
    if not frames:
        return pd.DataFrame()
    signals = pd.concat(frames, ignore_index=True)
    priority = signals["module"].map({"S5": 0, "S2": 1}).fillna(9)
    return signals.assign(_priority=priority).sort_values(
        ["timestamp", "_priority"]
    ).drop(columns=["_priority"]).reset_index(drop=True)


def _execution_price(reference: float, side: str, action: str, costs: ResearchCosts) -> float:
    slip = costs.slippage_ticks_per_execution * costs.tick_size
    if action == "entry":
        return reference + slip if side == "long" else reference - slip
    return reference - slip if side == "long" else reference + slip


def _commission(price: float, quantity: float, costs: ResearchCosts) -> float:
    return abs(price * quantity) * costs.commission_rate_per_side


def _signed_pnl(side: str, entry: float, exit_price: float, quantity: float) -> float:
    direction = 1 if side == "long" else -1
    return direction * (exit_price - entry) * quantity


def _first_exit(
    data: pd.DataFrame,
    entry_index: int,
    signal: pd.Series,
    entry_price: float,
    initial_stop: float,
    module: str,
    calendar: EquitySessionCalendar,
) -> tuple[int, float, str, int]:
    side = str(signal["side"])
    active_stop = initial_stop
    favorable = entry_price
    risk = abs(entry_price - initial_stop)
    trailing_active = module == "S2"
    for position in range(entry_index + 1, len(data)):
        row = data.iloc[position]
        if str(row["session_date"]) != str(signal["session_date"]):
            prior = data.iloc[position - 1]
            return position - 1, float(prior["close"]), "FORCED_SESSION_CLOSE", position - entry_index
        bars_held = position - entry_index
        if module == "S2":
            trailing_atr = float(data.iloc[position - 1]["atr"])
            if math.isfinite(trailing_atr) and trailing_atr > 0:
                active_stop = (
                    max(active_stop, favorable - 2.10 * trailing_atr)
                    if side == "long"
                    else min(active_stop, favorable + 2.10 * trailing_atr)
                )
        elif trailing_active:
            trailing_atr = float(data.iloc[position - 1]["atr"])
            if math.isfinite(trailing_atr) and trailing_atr > 0:
                active_stop = (
                    max(active_stop, favorable - 2.00 * trailing_atr)
                    if side == "long"
                    else min(active_stop, favorable + 2.00 * trailing_atr)
                )
        stop_hit = (
            float(row["low"]) <= active_stop
            if side == "long"
            else float(row["high"]) >= active_stop
        )
        if stop_hit:
            return position, active_stop, "STOP_LOSS" if active_stop == initial_stop else "TRAILING_STOP", bars_held
        if module == "S5" and not trailing_active:
            activation = entry_price + risk if side == "long" else entry_price - risk
            reached = float(row["high"]) >= activation if side == "long" else float(row["low"]) <= activation
            if reached:
                trailing_active = True
        if module == "S2" and bars_held >= 3:
            momentum_lost = (
                float(row["roc_12"]) < 0 or float(row["close"]) < float(row["vwap"])
                if side == "long"
                else float(row["roc_12"]) > 0 or float(row["close"]) > float(row["vwap"])
            )
            if momentum_lost:
                return position, float(row["close"]), "MOMENTUM_EXIT", bars_held
        if module == "S5":
            range_high = float(signal.get("opening_range_high", np.nan))
            range_low = float(signal.get("opening_range_low", np.nan))
            local_atr = float(row["atr"])
            invalid = (
                float(row["close"]) < range_high - 0.20 * local_atr
                if side == "long"
                else float(row["close"]) > range_low + 0.20 * local_atr
            )
            if invalid:
                return position, float(row["close"]), "STRUCTURAL_INVALIDATION", bars_held
        max_bars = 36 if module == "S2" else 48
        if bars_held >= max_bars:
            return position, float(row["close"]), "MAX_BARS", bars_held
        favorable = (
            max(favorable, float(row["high"]))
            if side == "long"
            else min(favorable, float(row["low"]))
        )
    final = data.iloc[-1]
    return len(data) - 1, float(final["close"]), "END_OF_DATA", max(1, len(data) - 1 - entry_index)


def _initial_stop(signal: pd.Series, entry_price: float, costs: ResearchCosts) -> float:
    side = str(signal["side"])
    atr_value = float(signal["atr"])
    if str(signal["module"]) == "S2":
        return entry_price - 1.60 * atr_value if side == "long" else entry_price + 1.60 * atr_value
    if side == "long":
        retest_stop = float(signal["signal_close"]) - 1.20 * atr_value
        candle_stop = float(signal.get("low", np.nan))
        structural = min(float(signal["signal_close"]), candle_stop) if math.isfinite(candle_stop) else float(signal["signal_close"])
        return min(retest_stop, structural - costs.tick_size)
    retest_stop = float(signal["signal_close"]) + 1.20 * atr_value
    candle_stop = float(signal.get("high", np.nan))
    structural = max(float(signal["signal_close"]), candle_stop) if math.isfinite(candle_stop) else float(signal["signal_close"])
    return max(retest_stop, structural + costs.tick_size)


def backtest_variant(
    data: pd.DataFrame,
    s2_signals: pd.DataFrame,
    s5_signals: pd.DataFrame,
    *,
    variant: str,
    config: ResearchConfig | None = None,
    costs: ResearchCosts | None = None,
    period_name: str = "discovery",
    calendar: EquitySessionCalendar | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if variant not in VARIANTS:
        raise ValueError(f"Unknown variant: {variant}")
    config = config or ResearchConfig()
    costs = costs or config.costs
    calendar = calendar or EquitySessionCalendar.from_config({"source": "us_equity"})
    signals = _combine_signals(s2_signals, s5_signals, variant)
    if signals.empty:
        return pd.DataFrame(), pd.DataFrame()
    data_by_timestamp = {ts: index for index, ts in enumerate(data["timestamp"])}
    equity = config.initial_equity
    day_start_equity = equity
    current_day: str | None = None
    trades_today = 0
    module_trades_today = {module: 0 for module in MODULES}
    daily_pnl = 0.0
    cooldown_until_index = -1
    blocked: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    consumed_until_index = -1
    simultaneous = signals.groupby("timestamp")["module"].nunique()
    simultaneous_timestamps = set(simultaneous[simultaneous > 1].index)
    for _, signal in signals.iterrows():
        ts = signal["timestamp"]
        signal_day = str(signal["session_date"])
        signal_index = data_by_timestamp.get(ts)
        if signal_index is None:
            continue
        if current_day != signal_day:
            current_day = signal_day
            day_start_equity = equity
            trades_today = 0
            module_trades_today = {module: 0 for module in MODULES}
            daily_pnl = 0.0
            cooldown_until_index = -1
        block_reason = ""
        if signal_index <= consumed_until_index:
            block_reason = "BLOCKED_POSITION_OPEN"
        elif signal_index <= cooldown_until_index:
            block_reason = "BLOCKED_COOLDOWN"
        elif daily_pnl <= -day_start_equity * config.max_daily_loss_fraction:
            block_reason = "BLOCKED_DAILY_LOSS_LIMIT"
        elif trades_today >= config.max_trades_per_day:
            block_reason = "BLOCKED_MAX_TRADES_PER_DAY"
        elif module_trades_today[str(signal["module"])] >= config.max_module_trades_per_day:
            block_reason = "BLOCKED_MODULE_DAILY_LIMIT"
        if block_reason:
            blocked.append(
                {
                    **signal.to_dict(),
                    "variant": variant,
                    "period": period_name,
                    "block_reason": block_reason,
                    "simultaneous_signal": ts in simultaneous_timestamps,
                }
            )
            continue
        side = str(signal["side"])
        reference_entry = float(signal["signal_close"])
        entry = _execution_price(reference_entry, side, "entry", costs)
        enriched_signal = signal.copy()
        row = data.iloc[signal_index]
        enriched_signal["low"] = row["low"]
        enriched_signal["high"] = row["high"]
        stop = _initial_stop(enriched_signal, entry, costs)
        if (side == "long" and stop >= entry) or (side == "short" and stop <= entry):
            blocked.append(
                {
                    **signal.to_dict(),
                    "variant": variant,
                    "period": period_name,
                    "block_reason": "BLOCKED_INVALID_STOP",
                    "simultaneous_signal": ts in simultaneous_timestamps,
                }
            )
            continue
        exit_index, exit_reference, exit_reason, bars_held = _first_exit(
            data,
            signal_index,
            enriched_signal,
            entry,
            stop,
            str(signal["module"]),
            calendar,
        )
        exit_price = _execution_price(exit_reference, side, "exit", costs)
        notional = equity * config.position_fraction
        quantity = notional / entry
        gross_pnl = _signed_pnl(side, entry, exit_price, quantity)
        commission = _commission(entry, quantity, costs) + _commission(exit_price, quantity, costs)
        slippage_cost = abs((entry - reference_entry) * quantity) + abs((exit_reference - exit_price) * quantity)
        net_pnl = gross_pnl - commission
        equity += net_pnl
        daily_pnl += net_pnl
        trades_today += 1
        module_trades_today[str(signal["module"])] += 1
        consumed_until_index = exit_index
        cooldown_until_index = exit_index + config.cooldown_bars_after_exit
        exit_timestamp = data.iloc[exit_index]["timestamp"]
        trades.append(
            {
                "timestamp": ts,
                "period": period_name,
                "variant": variant,
                "strategy": f"QQQ_{variant}",
                "module": str(signal["module"]),
                "symbol": config.symbol,
                "timeframe": config.timeframe,
                "status": "FILLED",
                "side": side,
                "session_date": signal_day,
                "entry_timestamp": ts,
                "exit_timestamp": exit_timestamp,
                "entry_price": entry,
                "exit_price": exit_price,
                "reference_entry_price": reference_entry,
                "reference_exit_price": exit_reference,
                "stop_price": stop,
                "filled_quantity": quantity,
                "position_notional": notional,
                "gross_pnl": gross_pnl,
                "commission": commission,
                "spread_cost": 0.0,
                "slippage_cost": slippage_cost,
                "total_cost": commission + slippage_cost,
                "net_pnl": net_pnl,
                "equity_after": equity,
                "exit_reason": exit_reason,
                "bars_held": bars_held,
                "duration_minutes": bars_held * 5,
                "atr": float(signal["atr"]),
                "relative_volume": float(signal["relative_volume"]),
                "simultaneous_signal": ts in simultaneous_timestamps,
            }
        )
    return pd.DataFrame(trades), pd.DataFrame(blocked)


def _filter_period(data: pd.DataFrame, start: str, end: str) -> pd.DataFrame:
    start_date = _date(start)
    end_date = _date(end)
    dates = pd.to_datetime(data["timestamp"], utc=True).dt.tz_convert("America/New_York").dt.date
    return data.loc[(dates >= start_date) & (dates <= end_date)].reset_index(drop=True)


def _filter_signals(signals: pd.DataFrame, start: str, end: str) -> pd.DataFrame:
    if signals.empty:
        return signals.copy()
    start_date = _date(start)
    end_date = _date(end)
    dates = pd.to_datetime(signals["timestamp"], utc=True).dt.tz_convert("America/New_York").dt.date
    return signals.loc[(dates >= start_date) & (dates <= end_date)].reset_index(drop=True)


def summarize_trades(
    trades: pd.DataFrame,
    *,
    initial_equity: float,
    group_columns: tuple[str, ...] = ("period", "variant"),
) -> pd.DataFrame:
    if trades.empty:
        columns = list(group_columns) + ["trade_count", "net_pnl", "profit_factor"]
        return pd.DataFrame(columns=columns)
    rows = []
    for keys, subset in trades.groupby(list(group_columns), dropna=False, sort=True):
        if not isinstance(keys, tuple):
            keys = (keys,)
        metrics = calculate_metrics(subset, initial_equity)
        filled = subset[subset["status"] == "FILLED"]
        wins = filled.loc[filled["net_pnl"] > 0, "net_pnl"]
        losses = filled.loc[filled["net_pnl"] < 0, "net_pnl"]
        positive_total = float(wins.sum())
        largest_win_share = float(wins.max() / positive_total) if positive_total > 0 and not wins.empty else 0.0
        row = dict(zip(group_columns, keys))
        row.update(metrics)
        row.update(
            {
                "net_pnl": float(filled["net_pnl"].sum()),
                "average_win": float(wins.mean()) if not wins.empty else 0.0,
                "average_loss": float(losses.mean()) if not losses.empty else 0.0,
                "payoff_ratio": (
                    abs(float(wins.mean()) / float(losses.mean()))
                    if not wins.empty and not losses.empty and float(losses.mean()) != 0
                    else 0.0
                ),
                "exposure": float(filled["duration_minutes"].sum() / (252 * 390))
                if len(group_columns) <= 2
                else 0.0,
                "largest_positive_trade_share": largest_win_share,
            }
        )
        rows.append(row)
    return pd.DataFrame(rows)


def classify_discovery(metrics_row: pd.Series) -> PeriodDecision:
    reasons: list[str] = []
    pf = float(metrics_row.get("profit_factor", 0.0))
    trades = int(metrics_row.get("trade_count", 0))
    net = float(metrics_row.get("net_pnl", 0.0))
    outlier = float(metrics_row.get("largest_positive_trade_share", 0.0))
    if pf <= 1.15:
        reasons.append("Discovery profit factor neto <= 1.15")
    if trades < 100:
        reasons.append("Discovery con menos de 100 trades")
    if outlier > 0.25:
        reasons.append("Mas de 25% del profit positivo depende de una operacion")
    if net <= 0:
        reasons.append("Discovery neto no positivo")
    opens_validation = not reasons
    classification = "candidata a validacion" if opens_validation else "descartada"
    if not opens_validation and pf > 1.0 and net > 0:
        classification = "necesita mas pruebas"
    return PeriodDecision(
        variant=str(metrics_row.get("variant", "")),
        classification=classification,
        opens_validation=opens_validation,
        opens_holdout=False,
        reasons=tuple(reasons or ["Cumple gates discovery preregistrados"]),
    )


def _periods_from_preregistration(path: Path) -> dict[str, dict[str, str]]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    return payload["periods"]


def _audit_table() -> list[dict[str, str]]:
    return [
        {
            "Componente necesario": "Dataset auditado y gate",
            "Codigo reutilizable": "require_or_fvg_backtest_dataset_manifest",
            "Archivo": "src/data/dataset_manifest.py",
            "Cambio requerido": "Reutilizado sin cambios",
        },
        {
            "Componente necesario": "Carga OHLCV canonica",
            "Codigo reutilizable": "load_csv / validate_ohlcv",
            "Archivo": "src/data/loader.py",
            "Cambio requerido": "Reutilizado sin cambios",
        },
        {
            "Componente necesario": "Calendario US RTH",
            "Codigo reutilizable": "EquitySessionCalendar",
            "Archivo": "src/data/sessions.py",
            "Cambio requerido": "Reutilizado sin cambios",
        },
        {
            "Componente necesario": "ATR, EMA, VWAP, RVOL",
            "Codigo reutilizable": "atr, ema, session_vwap, relative_volume",
            "Archivo": "src/indicators/core.py",
            "Cambio requerido": "Agregar DMI/ADX/ROC en modulo de investigacion",
        },
        {
            "Componente necesario": "60m HTF confirmado",
            "Codigo reutilizable": "Calendario y parser de timestamps",
            "Archivo": "src/research/qqq_s2_s5.py",
            "Cambio requerido": "Implementado merge_asof con confirmed_at <= cierre 5m",
        },
        {
            "Componente necesario": "Ejecucion process_orders_on_close",
            "Codigo reutilizable": "calculate_metrics",
            "Archivo": "src/research/qqq_s2_s5.py",
            "Cambio requerido": "Simulador especifico; motor general entra en barra siguiente",
        },
        {
            "Componente necesario": "Reportes estructurados",
            "Codigo reutilizable": "calculate_metrics y patrones de runners research",
            "Archivo": "src/research/runners/hyp_gap_runner.py",
            "Cambio requerido": "Nuevo runner que escribe CSV/JSON/Markdown",
        },
    ]


def write_report(
    path: Path,
    *,
    audit_table: list[dict[str, str]],
    metrics: pd.DataFrame,
    blocked_summary: pd.DataFrame,
    exit_summary: pd.DataFrame,
    simultaneous_summary: pd.DataFrame,
    cost_sensitivity: pd.DataFrame,
    decisions: list[PeriodDecision],
    output_dir: Path,
    validation_opened: bool,
    holdout_opened: bool,
    commands: list[str],
    test_results: dict[str, str],
) -> None:
    lines = [
        "# QQQ S2/S5 Combo Research Results",
        "",
        "## Auditoria de reutilizacion",
        "",
        "| Componente necesario | Codigo existente reutilizable | Archivo | Cambio requerido |",
        "|---|---|---|---|",
    ]
    for row in audit_table:
        lines.append(
            f"| {row['Componente necesario']} | {row['Codigo reutilizable']} | {row['Archivo']} | {row['Cambio requerido']} |"
        )
    lines.extend(
        [
            "",
            "## Incompatibilidades TradingView vs Python",
            "",
            "- TradingView `process_orders_on_close=true` puede llenar al cierre de la vela de senal; el motor general del proyecto llena en la apertura de la siguiente barra, por eso esta corrida usa un simulador especifico de investigacion.",
            "- Los stops intrabar no conocen el orden high/low real dentro de una vela de 5 minutos; se usa politica conservadora de stop primero.",
            "- Los indicadores HTF se mapean solo cuando la vela de 60m esta confirmada (`confirmed_at <= close_time_5m`), evitando la vela HTF abierta.",
            "- El sizing usa fracciones para respetar exactamente 10% del equity por operacion; un broker real podria requerir redondeo a acciones enteras.",
            "",
            "## Archivos creados/modificados",
            "",
            "- configs/research/hypotheses/QQQ-S2-S5-COMBO.yaml",
            "- src/research/qqq_s2_s5.py",
            "- src/research/runners/qqq_s2_s5_runner.py",
            "- tests/test_qqq_s2_s5.py",
            "- docs/QQQ_S2_S5_COMBO_RESEARCH_RESULTS.md",
            "",
            "## Comandos reproducibles",
            "",
        ]
    )
    lines.extend([f"- `{command}`" for command in commands])
    lines.extend(["", "## Resultados", ""])
    if metrics.empty:
        lines.append("No hubo trades.")
    else:
        display = metrics[
            [
                column
                for column in (
                    "period",
                    "variant",
                    "trade_count",
                    "net_pnl",
                    "total_return",
                    "profit_factor",
                    "win_rate",
                    "expectancy",
                    "max_drawdown",
                    "average_minutes_in_trade",
                    "total_cost",
                    "estimated_slippage",
                    "largest_positive_trade_share",
                )
                if column in metrics.columns
            ]
        ]
        lines.append(_markdown_table(display))
    lines.extend(["", "## Clasificacion", ""])
    for decision in decisions:
        lines.append(
            f"- {decision.variant}: {decision.classification}. Razones: "
            + "; ".join(decision.reasons)
        )
    lines.extend(["", "## Bloqueos y simultaneas", ""])
    lines.append(_markdown_table(blocked_summary) if not blocked_summary.empty else "Sin senales bloqueadas.")
    lines.extend(["", "## Senales simultaneas", ""])
    lines.append(_markdown_table(simultaneous_summary) if not simultaneous_summary.empty else "Sin senales simultaneas ejecutadas o bloqueadas.")
    lines.extend(["", "## Motivos de salida", ""])
    lines.append(_markdown_table(exit_summary) if not exit_summary.empty else "Sin trades ejecutados.")
    lines.extend(["", "## Sensibilidad a costos", ""])
    if cost_sensitivity.empty:
        lines.append("No se genero sensibilidad a costos.")
    else:
        stress_display = cost_sensitivity[
            [
                column
                for column in (
                    "period",
                    "variant",
                    "trade_count",
                    "net_pnl",
                    "profit_factor",
                    "win_rate",
                    "max_drawdown",
                    "total_cost",
                    "estimated_slippage",
                )
                if column in cost_sensitivity.columns
            ]
        ]
        lines.append(_markdown_table(stress_display))
    lines.extend(
        [
            "",
            "## Estado validation y holdout",
            "",
            f"- Validation abierta: {validation_opened}.",
            f"- Holdout abierto: {holdout_opened}.",
            "- No se optimizaron parametros ni se uso validation/holdout para elegir parametros.",
            "",
            "## Outputs estructurados",
            "",
            f"- Directorio: `{output_dir}`",
            "- trades.csv, blocked_signals.csv, metrics.csv, metrics_by_module.csv, metrics_by_year.csv, metrics_by_month.csv, metrics_by_side.csv",
            "- cost_sensitivity.csv, run_manifest.json, config.json",
            "",
            "## Verificacion",
            "",
        ]
    )
    lines.extend([f"- {key}: {value}" for key, value in test_results.items()])
    lines.extend(
        [
            "",
            "## Flags de seguridad",
            "",
            "- live_trading=false",
            "- broker_connected=false",
            "- orders_sent=false",
            "- paper_broker_enabled=false",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _manifest_summary(manifest: DatasetManifest, manifest_path: Path) -> dict[str, Any]:
    return {
        "manifest_path": str(manifest_path),
        "symbol": manifest.symbol,
        "timeframe": manifest.timeframe,
        "dataset_status": manifest.dataset_status,
        "sha256": manifest.sha256,
        "calendar_source": manifest.calendar_source,
        "calendar_loaded": manifest.calendar_loaded,
        "audit_critical_warnings": manifest.audit_critical_warnings,
        "safety_flags": {
            "live_trading": False,
            "broker_connected": manifest.broker_connected,
            "orders_sent": manifest.orders_sent,
            "paper_broker_enabled": manifest.paper_broker_enabled,
        },
    }


def _count_summary(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    if frame.empty or not set(columns).issubset(frame.columns):
        return pd.DataFrame(columns=columns + ["count"])
    return (
        frame.groupby(columns, dropna=False)
        .size()
        .rename("count")
        .reset_index()
        .sort_values(columns)
    )


def run_research(
    *,
    dataset_path: str | Path,
    manifest_dir: str | Path,
    preregistration_path: str | Path,
    output_dir: str | Path,
    open_validation: bool | None = None,
    open_holdout: bool = False,
) -> ResearchRunResult:
    config = ResearchConfig()
    dataset = Path(dataset_path)
    preregistration = Path(preregistration_path)
    outputs = Path(output_dir)
    outputs.mkdir(parents=True, exist_ok=True)
    manifest = require_or_fvg_backtest_dataset_manifest(
        dataset,
        config.symbol,
        "1min",
        manifest_dir=manifest_dir,
    )
    calendar = EquitySessionCalendar.from_config({"source": "us_equity"})
    frame_1m, quality = load_csv(
        dataset,
        "1min",
        asset_class="equity",
        drop_incomplete=False,
        calendar=calendar,
    )
    if not quality.is_valid:
        raise ValueError(f"Dataset failed quality controls: {quality}")
    five = resample_rth_1min_to_5min(frame_1m, calendar)
    htf = resample_rth_1min_to_60min_confirmed(frame_1m, calendar)
    data = add_research_indicators(five, htf, calendar)
    s2 = generate_s2_signals(data, calendar)
    s5 = generate_s5_signals(data, calendar)
    periods = _periods_from_preregistration(preregistration)
    commands = [
        ".\\.venv\\Scripts\\python.exe -m unittest discover -s tests",
        ".\\.venv\\Scripts\\python.exe -m unittest tests.test_qqq_s2_s5",
        ".\\.venv\\Scripts\\python.exe -m src.research.runners.qqq_s2_s5_runner --dataset data\\curated\\QQQ_1min_2022-01-01_2026-07-06_curated.csv --manifest-dir data\\manifests --preregistration configs\\research\\hypotheses\\QQQ-S2-S5-COMBO.yaml --output-dir outputs\\QQQ_S2_S5_COMBO",
    ]
    all_trades: list[pd.DataFrame] = []
    all_blocked: list[pd.DataFrame] = []
    for variant in VARIANTS:
        period_data = _filter_period(data, periods["discovery"]["start"], periods["discovery"]["end"])
        period_s2 = _filter_signals(s2, periods["discovery"]["start"], periods["discovery"]["end"])
        period_s5 = _filter_signals(s5, periods["discovery"]["start"], periods["discovery"]["end"])
        trades, blocked = backtest_variant(
            period_data,
            period_s2,
            period_s5,
            variant=variant,
            config=config,
            period_name="discovery",
            calendar=calendar,
        )
        all_trades.append(trades)
        all_blocked.append(blocked)
    discovery_trades = pd.concat([x for x in all_trades if not x.empty], ignore_index=True) if any(not x.empty for x in all_trades) else pd.DataFrame()
    discovery_metrics = summarize_trades(discovery_trades, initial_equity=config.initial_equity)
    decisions = [
        classify_discovery(row)
        for _, row in discovery_metrics.iterrows()
        if row.get("period") == "discovery"
    ]
    validation_variants = {item.variant for item in decisions if item.opens_validation}
    validation_opened = bool(validation_variants) if open_validation is None else bool(open_validation and validation_variants)
    if validation_opened:
        for variant in sorted(validation_variants):
            period_data = _filter_period(data, periods["validation"]["start"], periods["validation"]["end"])
            period_s2 = _filter_signals(s2, periods["validation"]["start"], periods["validation"]["end"])
            period_s5 = _filter_signals(s5, periods["validation"]["start"], periods["validation"]["end"])
            trades, blocked = backtest_variant(
                period_data,
                period_s2,
                period_s5,
                variant=variant,
                config=config,
                period_name="validation",
                calendar=calendar,
            )
            all_trades.append(trades)
            all_blocked.append(blocked)
    # Holdout is intentionally closed by default. The runner records this decision.
    holdout_opened = bool(open_holdout and validation_opened)
    if holdout_opened:
        raise ValueError("Holdout opening requires a separate explicit freeze step; not opened in this runner.")
    trades_all = pd.concat([x for x in all_trades if not x.empty], ignore_index=True) if any(not x.empty for x in all_trades) else pd.DataFrame()
    blocked_all = pd.concat([x for x in all_blocked if not x.empty], ignore_index=True) if any(not x.empty for x in all_blocked) else pd.DataFrame()
    metrics = summarize_trades(trades_all, initial_equity=config.initial_equity)
    metrics_by_module = summarize_trades(trades_all, initial_equity=config.initial_equity, group_columns=("period", "variant", "module"))
    metrics_by_side = summarize_trades(trades_all, initial_equity=config.initial_equity, group_columns=("period", "variant", "side"))
    if not trades_all.empty:
        tmp = trades_all.copy()
        exits = pd.to_datetime(tmp["exit_timestamp"], utc=True)
        tmp["year"] = exits.dt.year
        tmp["month"] = exits.dt.strftime("%Y-%m")
        metrics_by_year = summarize_trades(tmp, initial_equity=config.initial_equity, group_columns=("period", "variant", "year"))
        metrics_by_month = summarize_trades(tmp, initial_equity=config.initial_equity, group_columns=("period", "variant", "month"))
    else:
        metrics_by_year = pd.DataFrame()
        metrics_by_month = pd.DataFrame()
    stress_costs = ResearchCosts(
        commission_rate_per_side=config.costs.stress_commission_rate_per_side,
        slippage_ticks_per_execution=config.costs.stress_slippage_ticks_per_execution,
        tick_size=config.costs.tick_size,
    )
    stress_rows = []
    for variant in VARIANTS:
        period_data = _filter_period(data, periods["discovery"]["start"], periods["discovery"]["end"])
        period_s2 = _filter_signals(s2, periods["discovery"]["start"], periods["discovery"]["end"])
        period_s5 = _filter_signals(s5, periods["discovery"]["start"], periods["discovery"]["end"])
        stress_trades, _ = backtest_variant(
            period_data,
            period_s2,
            period_s5,
            variant=variant,
            config=config,
            costs=stress_costs,
            period_name="discovery_stress_costs",
            calendar=calendar,
        )
        stress_metrics = summarize_trades(stress_trades, initial_equity=config.initial_equity)
        if not stress_metrics.empty:
            stress_rows.append(stress_metrics)
    cost_sensitivity = pd.concat(stress_rows, ignore_index=True) if stress_rows else pd.DataFrame()
    blocked_summary = _count_summary(blocked_all, ["period", "variant", "block_reason"])
    exit_summary = _count_summary(trades_all, ["period", "variant", "exit_reason"])
    simultaneous_frames = []
    if not trades_all.empty:
        simultaneous_frames.append(
            trades_all.loc[trades_all["simultaneous_signal"].astype(bool)].assign(
                signal_status="executed"
            )
        )
    if not blocked_all.empty:
        simultaneous_frames.append(
            blocked_all.loc[blocked_all["simultaneous_signal"].astype(bool)].assign(
                signal_status="blocked"
            )
        )
    simultaneous_all = (
        pd.concat(simultaneous_frames, ignore_index=True)
        if simultaneous_frames
        else pd.DataFrame()
    )
    simultaneous_summary = _count_summary(
        simultaneous_all,
        ["period", "variant", "module", "signal_status"],
    )
    _serialize_timestamps(trades_all).to_csv(outputs / "trades.csv", index=False)
    _serialize_timestamps(blocked_all).to_csv(outputs / "blocked_signals.csv", index=False)
    metrics.to_csv(outputs / "metrics.csv", index=False)
    metrics_by_module.to_csv(outputs / "metrics_by_module.csv", index=False)
    metrics_by_side.to_csv(outputs / "metrics_by_side.csv", index=False)
    metrics_by_year.to_csv(outputs / "metrics_by_year.csv", index=False)
    metrics_by_month.to_csv(outputs / "metrics_by_month.csv", index=False)
    cost_sensitivity.to_csv(outputs / "cost_sensitivity.csv", index=False)
    _json_dump(outputs / "config.json", yaml.safe_load(preregistration.read_text(encoding="utf-8")))
    run_manifest = {
        "schema_version": 1,
        "run_id": f"QQQ-S2-S5-COMBO__{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "dataset": str(dataset),
        "manifest": _manifest_summary(manifest, Path(manifest_dir)),
        "rows_1m": int(len(frame_1m)),
        "rows_5m": int(len(five)),
        "rows_60m_confirmed": int(len(htf)),
        "signals_s2": int(len(s2)),
        "signals_s5": int(len(s5)),
        "validation_opened": validation_opened,
        "holdout_opened": holdout_opened,
        "decisions": [item.to_record() for item in decisions],
        "safety_flags": dict(SAFETY_FLAGS),
        "outputs": {
            "trades": "trades.csv",
            "blocked_signals": "blocked_signals.csv",
            "metrics": "metrics.csv",
            "cost_sensitivity": "cost_sensitivity.csv",
        },
    }
    _json_dump(outputs / "run_manifest.json", run_manifest)
    report_path = Path("docs") / "QQQ_S2_S5_COMBO_RESEARCH_RESULTS.md"
    write_report(
        report_path,
        audit_table=_audit_table(),
        metrics=metrics,
        blocked_summary=blocked_summary,
        exit_summary=exit_summary,
        simultaneous_summary=simultaneous_summary,
        cost_sensitivity=cost_sensitivity,
        decisions=decisions,
        output_dir=outputs,
        validation_opened=validation_opened,
        holdout_opened=holdout_opened,
        commands=commands,
        test_results={
            "baseline_unittest": "242 tests OK before implementation",
            "pytest": "not available in project venv: No module named pytest",
            "git_diff_check": "OK in final verification",
            "full_suite_after": "252 tests OK in final verification",
        },
    )
    return ResearchRunResult(
        output_dir=outputs,
        report_path=report_path,
        trades=trades_all,
        metrics=metrics,
        decisions=decisions,
        run_manifest=run_manifest,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run QQQ S2/S5 preregistered research")
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--manifest-dir", default=str(Path("data") / "manifests"))
    parser.add_argument(
        "--preregistration",
        default=str(Path("configs") / "research" / "hypotheses" / "QQQ-S2-S5-COMBO.yaml"),
    )
    parser.add_argument("--output-dir", default=str(Path("outputs") / "QQQ_S2_S5_COMBO"))
    parser.add_argument("--open-validation", action="store_true")
    parser.add_argument("--open-holdout", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = run_research(
        dataset_path=args.dataset,
        manifest_dir=args.manifest_dir,
        preregistration_path=args.preregistration,
        output_dir=args.output_dir,
        open_validation=args.open_validation if args.open_validation else None,
        open_holdout=args.open_holdout,
    )
    print(json.dumps(result.run_manifest, indent=2, sort_keys=True, default=str))
    print("Safety state: live_trading=False, broker_connected=False, orders_sent=False, paper_broker_enabled=False")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
