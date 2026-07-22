from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from src.data import (
    DatasetManifest,
    EquitySessionCalendar,
    load_csv,
    require_or_fvg_backtest_dataset_manifest,
)
from src.research.qqq_s2_s5 import resample_rth_1min_to_5min


HYPOTHESIS_ID = "HYP-FCR-01"
SOURCE_VERSION = "FIRST_CANDLE_RULE_TV_V1"
SOURCE_PINE_PATH = Path("docs") / "research" / "source_pine" / f"{SOURCE_VERSION}.pine"
EXPECTED_CANONICAL_PAYLOAD_SHA256 = (
    "bac53f3ff97176b9be5bd5b52a9d6589747587a313b34f24644e1d99bb4cd2ab"
)
DISCOVERY_START = date(2022, 1, 1)
DISCOVERY_END = date(2024, 12, 31)
VALIDATION_START = date(2025, 1, 1)
VALIDATION_END = date(2025, 12, 31)
CONTAMINATED_2026_START = date(2026, 1, 1)
CONTAMINATED_2026_END = date(2026, 12, 31)
SAFETY_FLAGS = {
    "live_trading": False,
    "broker_connected": False,
    "orders_sent": False,
    "paper_broker_enabled": False,
}
PARITY_COLUMNS = [
    "symbol",
    "session_date",
    "direction",
    "opening_high",
    "opening_low",
    "last_sweep_time",
    "signal_time",
    "signal_close",
    "fvg_size",
    "stop",
    "target",
    "intended_quantity",
    "actual_quantity",
    "entry_time",
    "entry_price",
    "exit_time",
    "exit_price",
    "exit_reason",
    "gross_pnl",
    "commission",
    "slippage_cost",
    "net_pnl",
    "intended_R",
    "realized_R",
]
PARITY_DIFFERENCE_TYPES = {
    "DATA_FEED_DIFFERENCE",
    "SESSION_ALIGNMENT_DIFFERENCE",
    "SIGNAL_LOGIC_DIFFERENCE",
    "POSITION_SIZING_DIFFERENCE",
    "INTRABAR_EXECUTION_DIFFERENCE",
    "UNEXPLAINED_DIFFERENCE",
}


@dataclass(frozen=True)
class CostModel:
    name: str
    commission_rate_per_side: float
    slippage_ticks_per_execution: int
    tick_size: float = 0.01

    @property
    def slippage_value(self) -> float:
        return self.slippage_ticks_per_execution * self.tick_size


@dataclass(frozen=True)
class FirstCandleConfig:
    hypothesis_id: str = HYPOTHESIS_ID
    timezone: str = "America/New_York"
    signal_timeframe: str = "5min"
    source_timeframe: str = "1min"
    opening_start: str = "09:30"
    opening_end_exclusive: str = "10:00"
    entry_start: str = "10:00"
    entry_end_exclusive: str = "15:55"
    exit_session_start: str = "15:55"
    exit_session_end: str = "16:00"
    symbols: tuple[str, ...] = ("QQQ", "SPY")
    reward_risk: float = 2.0
    sweep_tolerance_ticks: int = 0
    minimum_fvg_ticks: int = 0
    stop_buffer_ticks: int = 1
    initial_equity: float = 1000.0
    risk_percent: float = 0.005
    max_notional_percent: float = 1.0
    quantity_step: int = 1
    minimum_quantity: int = 1
    point_value: float = 1.0
    one_trade_per_symbol_session: bool = True
    confirmation_mode: str = "Solo FVG"
    allow_same_bar_confirmation: bool = False
    costs: tuple[CostModel, ...] = field(
        default_factory=lambda: (
            CostModel("baseline", 0.0001, 1),
            CostModel("stress", 0.0002, 2),
            CostModel("severe", 0.0003, 3),
        )
    )

    def cost(self, name: str) -> CostModel:
        for item in self.costs:
            if item.name == name:
                return item
        raise ValueError(f"Unknown cost model: {name}")


@dataclass(frozen=True)
class SizeDecision:
    intended_quantity: int
    actual_quantity: int
    intended_risk: float
    realized_risk: float
    risk_percent_intended: float
    risk_percent_realized: float
    rejection_reason: str = ""

    @property
    def accepted(self) -> bool:
        return self.actual_quantity >= 1 and not self.rejection_reason


@dataclass(frozen=True)
class ResearchPeriodRequest:
    period: Literal["discovery", "validation", "holdout", "parity_debug_2026"]
    start: date
    end: date
    canonical_payload_sha256: str = EXPECTED_CANONICAL_PAYLOAD_SHA256
    discovery_approval_path: str | Path | None = None
    non_decisional: bool = False


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_config_hash(payload: dict[str, Any]) -> str:
    cleaned = json.loads(json.dumps(payload, sort_keys=True, default=str))
    for key in ("configuration_hash", "yaml_sha256", "yaml_sha256_excluding_self"):
        cleaned.pop(key, None)
    encoded = json.dumps(cleaned, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _coerce_date(value: str | date) -> date:
    return value if isinstance(value, date) else date.fromisoformat(str(value))


def _load_discovery_approval(path: str | Path | None) -> dict[str, Any]:
    if path is None:
        raise PermissionError(
            "HYP-FCR-01 validation is blocked until a discovery approval artifact exists."
        )
    candidate = Path(path)
    if not candidate.exists():
        raise FileNotFoundError(f"Discovery approval artifact not found: {candidate}")
    payload = json.loads(candidate.read_text(encoding="utf-8"))
    if payload.get("hypothesis_id") != HYPOTHESIS_ID:
        raise ValueError("Discovery approval artifact hypothesis_id mismatch.")
    if payload.get("discovery_gate_passed") is not True:
        raise PermissionError("Discovery gate has not passed; validation remains blocked.")
    return payload


def validate_research_period_request(request: ResearchPeriodRequest) -> None:
    start = _coerce_date(request.start)
    end = _coerce_date(request.end)
    if start > end:
        raise ValueError("requested start must be on or before end")
    if request.canonical_payload_sha256 != EXPECTED_CANONICAL_PAYLOAD_SHA256:
        raise ValueError(
            "HYP-FCR-01 canonical payload hash mismatch; freeze cannot be opened."
        )
    if request.period == "discovery":
        if (start, end) != (DISCOVERY_START, DISCOVERY_END):
            raise PermissionError(
                "HYP-FCR-01 discovery is frozen to 2022-01-01 through 2024-12-31."
            )
        return
    if request.period == "validation":
        if (start, end) != (VALIDATION_START, VALIDATION_END):
            raise PermissionError(
                "HYP-FCR-01 validation is frozen to 2025-01-01 through 2025-12-31."
            )
        approval = _load_discovery_approval(request.discovery_approval_path)
        if approval.get("canonical_payload_sha256") != EXPECTED_CANONICAL_PAYLOAD_SHA256:
            raise ValueError("Discovery approval canonical payload hash mismatch.")
        return
    if request.period == "parity_debug_2026":
        if not request.non_decisional:
            raise PermissionError("2026 parity debug must be explicitly non-decisional.")
        if start < CONTAMINATED_2026_START or end > CONTAMINATED_2026_END:
            raise PermissionError("2026 parity debug is limited to the contaminated 2026 year.")
        return
    if request.period == "holdout":
        raise PermissionError("HYP-FCR-01 holdout has no executable implementation yet.")
    raise ValueError(f"Unsupported HYP-FCR-01 period: {request.period}")


def _as_time(value: str) -> time:
    return time.fromisoformat(value)


def _local(timestamp: pd.Timestamp, config: FirstCandleConfig) -> pd.Timestamp:
    return pd.Timestamp(timestamp).tz_convert(ZoneInfo(config.timezone))


def _clock(timestamp: pd.Timestamp, config: FirstCandleConfig) -> time:
    return _local(timestamp, config).time().replace(tzinfo=None)


def _session_date(timestamp: pd.Timestamp, config: FirstCandleConfig) -> str:
    return _local(timestamp, config).date().isoformat()


def _bar_close(timestamp: pd.Timestamp) -> pd.Timestamp:
    base = pd.Timestamp(timestamp)
    if base.tzinfo is None:
        base = base.tz_localize("UTC")
    else:
        base = base.tz_convert("UTC")
    return pd.Timestamp(base.to_pydatetime()) + pd.Timedelta(5, unit="min")


def _adverse_entry_price(reference: float, direction: str, costs: CostModel) -> float:
    return reference + costs.slippage_value if direction == "long" else reference - costs.slippage_value


def _adverse_exit_price(reference: float, direction: str, costs: CostModel) -> float:
    return reference - costs.slippage_value if direction == "long" else reference + costs.slippage_value


def _gross_pnl(direction: str, entry: float, exit_price: float, quantity: int) -> float:
    sign = 1 if direction == "long" else -1
    return sign * (exit_price - entry) * quantity


def _commission(entry: float, exit_price: float, quantity: int, costs: CostModel) -> float:
    return (abs(entry * quantity) + abs(exit_price * quantity)) * costs.commission_rate_per_side


def _slippage_cost(signal_close: float, entry: float, exit_reference: float, exit_price: float, quantity: int) -> float:
    return (abs(entry - signal_close) + abs(exit_price - exit_reference)) * quantity


def add_session_columns(
    five_minute: pd.DataFrame,
    config: FirstCandleConfig | None = None,
) -> pd.DataFrame:
    config = config or FirstCandleConfig()
    data = five_minute.copy()
    local = pd.to_datetime(data["timestamp"], utc=True).dt.tz_convert(config.timezone)
    data["session_date"] = local.dt.date.astype(str)
    data["local_time"] = local.dt.strftime("%H:%M")
    data["minute_of_day"] = local.dt.hour * 60 + local.dt.minute
    data["session_bar_index"] = data.groupby("session_date").cumcount()
    return data


def compute_opening_ranges(
    five_minute: pd.DataFrame,
    config: FirstCandleConfig | None = None,
) -> pd.DataFrame:
    config = config or FirstCandleConfig()
    data = add_session_columns(five_minute, config)
    start = _as_time(config.opening_start)
    end = _as_time(config.opening_end_exclusive)
    rows: list[dict[str, Any]] = []
    for session_date, session in data.groupby("session_date", sort=True):
        opening = session[
            session["timestamp"].map(lambda value: start <= _clock(value, config) < end)
        ]
        if len(opening) != 6:
            continue
        rows.append(
            {
                "session_date": session_date,
                "opening_high": float(opening["high"].max()),
                "opening_low": float(opening["low"].min()),
                "opening_bar_count": int(len(opening)),
                "available_from": f"{session_date}T{config.opening_end_exclusive}",
            }
        )
    return pd.DataFrame(rows)


def bullish_fvg(current: pd.Series, two_back: pd.Series, tick_size: float = 0.01, minimum_ticks: int = 0) -> tuple[bool, float]:
    gap = float(current["low"]) - float(two_back["high"])
    return bool(gap > 0 and gap >= minimum_ticks * tick_size), gap


def bearish_fvg(current: pd.Series, two_back: pd.Series, tick_size: float = 0.01, minimum_ticks: int = 0) -> tuple[bool, float]:
    gap = float(two_back["low"]) - float(current["high"])
    return bool(gap > 0 and gap >= minimum_ticks * tick_size), gap


def close_strictly_inside(close: float, opening_low: float, opening_high: float) -> bool:
    return opening_low < close < opening_high


def stop_from_bodies(
    session: pd.DataFrame,
    position: int,
    direction: Literal["long", "short"],
    *,
    tick_size: float = 0.01,
    buffer_ticks: int = 1,
) -> float:
    if position < 2:
        raise ValueError("FCR stop requires signal bar and two previous bars")
    window = session.iloc[position - 2 : position + 1]
    if direction == "long":
        body_extreme = np.minimum(window["open"].astype(float), window["close"].astype(float)).min()
        return float(body_extreme - buffer_ticks * tick_size)
    body_extreme = np.maximum(window["open"].astype(float), window["close"].astype(float)).max()
    return float(body_extreme + buffer_ticks * tick_size)


def target_from_signal_close(
    signal_close: float,
    stop: float,
    direction: Literal["long", "short"],
    reward_risk: float = 2.0,
) -> float:
    if direction == "long":
        return signal_close + reward_risk * (signal_close - stop)
    return signal_close - reward_risk * (stop - signal_close)


def calculate_position_size(
    *,
    equity: float,
    signal_close: float,
    risk_per_unit: float,
    config: FirstCandleConfig | None = None,
) -> SizeDecision:
    config = config or FirstCandleConfig()
    risk_capital = equity * config.risk_percent
    if risk_per_unit <= 0 or not math.isfinite(risk_per_unit):
        return SizeDecision(0, 0, risk_capital, 0.0, config.risk_percent, 0.0, "invalid_risk_per_unit")
    risk_quantity = risk_capital / (risk_per_unit * config.point_value)
    maximum_quantity_by_notional = (equity * config.max_notional_percent) / (signal_close * config.point_value)
    raw_quantity = min(risk_quantity, maximum_quantity_by_notional)
    quantity = int(math.floor(raw_quantity / config.quantity_step) * config.quantity_step)
    realized_risk = quantity * risk_per_unit * config.point_value
    if quantity < config.minimum_quantity:
        return SizeDecision(
            quantity,
            0,
            risk_capital,
            realized_risk,
            config.risk_percent,
            realized_risk / equity if equity > 0 else 0.0,
            "quantity_below_minimum",
        )
    return SizeDecision(
        quantity,
        quantity,
        risk_capital,
        realized_risk,
        config.risk_percent,
        realized_risk / equity if equity > 0 else 0.0,
    )


def detect_first_candle_signals(
    five_minute: pd.DataFrame,
    symbol: str,
    config: FirstCandleConfig | None = None,
    *,
    equity: float | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    config = config or FirstCandleConfig()
    sizing_equity = config.initial_equity if equity is None else float(equity)
    if config.confirmation_mode != "Solo FVG":
        raise ValueError("HYP-FCR-01 is frozen to confirmation_mode='Solo FVG'")
    data = add_session_columns(five_minute, config)
    ranges = compute_opening_ranges(data, config)
    if ranges.empty:
        return pd.DataFrame(), pd.DataFrame(
            [{"symbol": symbol.upper(), "diagnostic": "no_complete_opening_ranges"}]
        )
    enriched = data.merge(ranges, on="session_date", how="left")
    entry_start = _as_time(config.entry_start)
    entry_end = _as_time(config.entry_end_exclusive)
    diagnostics: list[dict[str, Any]] = []
    signals: list[dict[str, Any]] = []

    for session_date, session in enriched.groupby("session_date", sort=True):
        if session["opening_high"].isna().all():
            diagnostics.append(
                {
                    "symbol": symbol.upper(),
                    "session_date": session_date,
                    "diagnostic": "missing_six_bar_opening_range",
                }
            )
            continue
        opening_high = float(session["opening_high"].iloc[0])
        opening_low = float(session["opening_low"].iloc[0])
        low_swept = False
        high_swept = False
        low_sweep_position: int | None = None
        high_sweep_position: int | None = None
        low_sweep_time: pd.Timestamp | None = None
        high_sweep_time: pd.Timestamp | None = None
        traded = False
        session = session.reset_index(drop=True)
        for position, row in session.iterrows():
            ts = pd.Timestamp(row["timestamp"])
            clock = _clock(ts, config)
            if not (entry_start <= clock < entry_end):
                continue
            if traded and config.one_trade_per_symbol_session:
                continue
            low_touch_now = float(row["low"]) <= opening_low + config.sweep_tolerance_ticks * config.cost("baseline").tick_size
            high_touch_now = float(row["high"]) >= opening_high - config.sweep_tolerance_ticks * config.cost("baseline").tick_size
            if low_touch_now:
                low_swept = True
                low_sweep_position = int(position)
                low_sweep_time = ts
            if high_touch_now:
                high_swept = True
                high_sweep_position = int(position)
                high_sweep_time = ts
            if position < 2:
                continue
            two_back = session.iloc[position - 2]
            bull, bull_gap = bullish_fvg(row, two_back, config.cost("baseline").tick_size, config.minimum_fvg_ticks)
            bear, bear_gap = bearish_fvg(row, two_back, config.cost("baseline").tick_size, config.minimum_fvg_ticks)
            inside = close_strictly_inside(float(row["close"]), opening_low, opening_high)
            long_delay = low_swept and low_sweep_position is not None and int(position) > low_sweep_position
            short_delay = high_swept and high_sweep_position is not None and int(position) > high_sweep_position
            long_signal = bool(long_delay and bull and inside)
            short_signal = bool(short_delay and bear and inside)
            if long_signal and short_signal:
                diagnostics.append(
                    {
                        "symbol": symbol.upper(),
                        "session_date": session_date,
                        "timestamp": ts.isoformat(),
                        "diagnostic": "simultaneous_long_short_signal_no_trade",
                    }
                )
                continue
            if not (long_signal or short_signal):
                continue
            direction: Literal["long", "short"] = "long" if long_signal else "short"
            stop = stop_from_bodies(
                session,
                int(position),
                direction,
                tick_size=config.cost("baseline").tick_size,
                buffer_ticks=config.stop_buffer_ticks,
            )
            signal_close = float(row["close"])
            target = target_from_signal_close(signal_close, stop, direction, config.reward_risk)
            risk_per_unit = signal_close - stop if direction == "long" else stop - signal_close
            if risk_per_unit <= 0:
                diagnostics.append(
                    {
                        "symbol": symbol.upper(),
                        "session_date": session_date,
                        "timestamp": ts.isoformat(),
                        "diagnostic": "invalid_stop_side_no_trade",
                    }
                )
                continue
            size = calculate_position_size(
                equity=sizing_equity,
                signal_close=signal_close,
                risk_per_unit=float(risk_per_unit),
                config=config,
            )
            if not size.accepted:
                diagnostics.append(
                    {
                        "symbol": symbol.upper(),
                        "session_date": session_date,
                        "timestamp": ts.isoformat(),
                        "direction": direction,
                        "diagnostic": size.rejection_reason,
                        "risk_per_unit": float(risk_per_unit),
                        "intended_quantity": int(size.intended_quantity),
                        "actual_quantity": int(size.actual_quantity),
                    }
                )
                continue
            last_sweep_time = low_sweep_time if direction == "long" else high_sweep_time
            last_sweep_position = low_sweep_position if direction == "long" else high_sweep_position
            fvg_size = bull_gap if direction == "long" else bear_gap
            signals.append(
                {
                    "hypothesis_id": config.hypothesis_id,
                    "symbol": symbol.upper(),
                    "session_date": session_date,
                    "direction": direction,
                    "opening_high": opening_high,
                    "opening_low": opening_low,
                    "last_sweep_time": last_sweep_time,
                    "signal_time": ts,
                    "signal_bar_close_time": _bar_close(ts),
                    "signal_close": signal_close,
                    "fvg_size": float(fvg_size),
                    "fvg_size_ticks": float(fvg_size / config.cost("baseline").tick_size),
                    "stop": float(stop),
                    "target": float(target),
                    "risk_per_unit": float(risk_per_unit),
                    "bars_since_last_sweep": int(position - int(last_sweep_position)),
                    "entry_hour": _local(ts, config).strftime("%H:00"),
                }
            )
            traded = True
            if config.one_trade_per_symbol_session:
                break
    return pd.DataFrame(signals), pd.DataFrame(diagnostics)


def _minute_slice_for_session(
    minute_data: pd.DataFrame,
    session_date: str,
    config: FirstCandleConfig,
) -> pd.DataFrame:
    if minute_data.empty:
        return minute_data.copy()
    local = pd.to_datetime(minute_data["timestamp"], utc=True).dt.tz_convert(config.timezone)
    mask = local.dt.date.astype(str) == session_date
    return minute_data.loc[mask].sort_values("timestamp").reset_index(drop=True)


def _last_executable_minute(
    minute_session: pd.DataFrame,
    session_date: str,
    calendar: EquitySessionCalendar,
    config: FirstCandleConfig,
) -> int | None:
    close = calendar.session_close(date.fromisoformat(session_date))
    if close is None:
        return None
    close_ts = pd.Timestamp(
        datetime.combine(date.fromisoformat(session_date), close),
        tz=ZoneInfo(config.timezone),
    ).tz_convert("UTC")
    eligible = minute_session.loc[minute_session["timestamp"] < close_ts]
    if eligible.empty:
        return None
    return int(eligible.index[-1])


def simulate_research_primary_trade(
    signal: pd.Series,
    minute_data: pd.DataFrame,
    *,
    equity: float = 1000.0,
    costs: CostModel | None = None,
    config: FirstCandleConfig | None = None,
    calendar: EquitySessionCalendar | None = None,
) -> dict[str, Any]:
    config = config or FirstCandleConfig()
    costs = costs or config.cost("baseline")
    calendar = calendar or EquitySessionCalendar.from_config({"source": "us_equity"})
    size = calculate_position_size(
        equity=equity,
        signal_close=float(signal["signal_close"]),
        risk_per_unit=float(signal["risk_per_unit"]),
        config=config,
    )
    base_record = _base_trade_record(signal, size)
    if not size.accepted:
        return {**base_record, "exit_reason": size.rejection_reason}
    session_minutes = _minute_slice_for_session(minute_data, str(signal["session_date"]), config)
    if session_minutes.empty:
        return {**base_record, "exit_reason": "no_minute_data_for_session"}
    entry_not_before = pd.Timestamp(signal["signal_bar_close_time"])
    candidates = session_minutes.loc[session_minutes["timestamp"] >= entry_not_before]
    if candidates.empty:
        return {**base_record, "exit_reason": "no_next_minute_entry"}
    entry_index = int(candidates.index[0])
    entry_row = session_minutes.loc[entry_index]
    direction = str(signal["direction"])
    stop = float(signal["stop"])
    target = float(signal["target"])
    entry_reference = float(entry_row["open"])
    entry_price = _adverse_entry_price(entry_reference, direction, costs)
    last_index = _last_executable_minute(session_minutes, str(signal["session_date"]), calendar, config)
    if last_index is None:
        return {**base_record, "exit_reason": "no_session_close"}
    if entry_index > last_index:
        return {**base_record, "exit_reason": "entry_after_session_close"}

    exit_index = last_index
    exit_reference = float(session_minutes.loc[last_index, "close"])
    exit_price = _adverse_exit_price(exit_reference, direction, costs)
    exit_reason = "FORCED_SESSION_CLOSE"

    for index in range(entry_index, last_index + 1):
        row = session_minutes.loc[index]
        open_price = float(row["open"])
        if direction == "long":
            if open_price <= stop:
                exit_index = index
                exit_reference = min(stop, open_price)
                exit_price = exit_reference - costs.slippage_value
                exit_reason = "GAP_THROUGH_STOP"
                break
            if open_price >= target:
                exit_index = index
                exit_reference = target
                exit_price = target
                exit_reason = "GAP_THROUGH_TARGET_NO_IMPROVEMENT"
                break
            stop_touched = float(row["low"]) <= stop
            target_touched = float(row["high"]) >= target
            if stop_touched:
                exit_index = index
                exit_reference = stop
                exit_price = _adverse_exit_price(stop, direction, costs)
                exit_reason = "STOP_FIRST_AMBIGUOUS_BAR" if target_touched else "STOP_LOSS"
                break
            if target_touched:
                exit_index = index
                exit_reference = target
                exit_price = _adverse_exit_price(target, direction, costs)
                exit_reason = "TAKE_PROFIT"
                break
        else:
            if open_price >= stop:
                exit_index = index
                exit_reference = max(stop, open_price)
                exit_price = exit_reference + costs.slippage_value
                exit_reason = "GAP_THROUGH_STOP"
                break
            if open_price <= target:
                exit_index = index
                exit_reference = target
                exit_price = target
                exit_reason = "GAP_THROUGH_TARGET_NO_IMPROVEMENT"
                break
            stop_touched = float(row["high"]) >= stop
            target_touched = float(row["low"]) <= target
            if stop_touched:
                exit_index = index
                exit_reference = stop
                exit_price = _adverse_exit_price(stop, direction, costs)
                exit_reason = "STOP_FIRST_AMBIGUOUS_BAR" if target_touched else "STOP_LOSS"
                break
            if target_touched:
                exit_index = index
                exit_reference = target
                exit_price = _adverse_exit_price(target, direction, costs)
                exit_reason = "TAKE_PROFIT"
                break

    return _finalize_trade_record(
        base_record,
        direction=direction,
        signal_close=float(signal["signal_close"]),
        entry_time=session_minutes.loc[entry_index, "timestamp"],
        entry_price=entry_price,
        exit_time=session_minutes.loc[exit_index, "timestamp"],
        exit_price=exit_price,
        exit_reference=exit_reference,
        exit_reason=exit_reason,
        quantity=size.actual_quantity,
        risk_per_unit=float(signal["risk_per_unit"]),
        costs=costs,
    )


def simulate_tradingview_parity_trade(
    signal: pd.Series,
    five_minute: pd.DataFrame,
    *,
    equity: float = 1000.0,
    costs: CostModel | None = None,
    config: FirstCandleConfig | None = None,
) -> dict[str, Any]:
    config = config or FirstCandleConfig()
    costs = costs or config.cost("baseline")
    size = calculate_position_size(
        equity=equity,
        signal_close=float(signal["signal_close"]),
        risk_per_unit=float(signal["risk_per_unit"]),
        config=config,
    )
    base_record = _base_trade_record(signal, size)
    if not size.accepted:
        return {**base_record, "exit_reason": size.rejection_reason}
    data = add_session_columns(five_minute, config)
    session = data.loc[data["session_date"] == str(signal["session_date"])].reset_index(drop=True)
    if session.empty:
        return {**base_record, "exit_reason": "no_5min_data_for_session"}
    signal_positions = session.index[session["timestamp"] == pd.Timestamp(signal["signal_time"])].tolist()
    if not signal_positions:
        return {**base_record, "exit_reason": "signal_time_missing"}
    entry_index = int(signal_positions[0])
    direction = str(signal["direction"])
    stop = float(signal["stop"])
    target = float(signal["target"])
    signal_close = float(signal["signal_close"])
    entry_price = _adverse_entry_price(signal_close, direction, costs)
    exit_index = entry_index
    exit_reference = signal_close
    exit_price = _adverse_exit_price(signal_close, direction, costs)
    exit_reason = "END_OF_DATA_OR_OVERNIGHT_RISK_SOURCE_SEMANTICS"
    exit_start = _as_time(config.exit_session_start)
    exit_end = _as_time(config.exit_session_end)

    for index in range(entry_index, len(session)):
        row = session.loc[index]
        clock = _clock(row["timestamp"], config)
        if direction == "long":
            stop_touched = float(row["low"]) <= stop
            target_touched = float(row["high"]) >= target
        else:
            stop_touched = float(row["high"]) >= stop
            target_touched = float(row["low"]) <= target
        if stop_touched:
            exit_index = index
            exit_reference = stop
            exit_price = _adverse_exit_price(stop, direction, costs)
            exit_reason = "STOP_FIRST_AMBIGUOUS_BAR" if target_touched else "STOP_LOSS"
            break
        if target_touched:
            exit_index = index
            exit_reference = target
            exit_price = _adverse_exit_price(target, direction, costs)
            exit_reason = "TAKE_PROFIT"
            break
        if exit_start <= clock < exit_end:
            exit_index = index
            exit_reference = float(row["close"])
            exit_price = _adverse_exit_price(exit_reference, direction, costs)
            exit_reason = "PINE_FIXED_1555_CLOSE"
            break

    return _finalize_trade_record(
        base_record,
        direction=direction,
        signal_close=signal_close,
        entry_time=session.loc[entry_index, "timestamp"],
        entry_price=entry_price,
        exit_time=session.loc[exit_index, "timestamp"],
        exit_price=exit_price,
        exit_reference=exit_reference,
        exit_reason=exit_reason,
        quantity=size.actual_quantity,
        risk_per_unit=float(signal["risk_per_unit"]),
        costs=costs,
    )


def _base_trade_record(signal: pd.Series, size: SizeDecision) -> dict[str, Any]:
    return {
        "symbol": str(signal["symbol"]),
        "session_date": str(signal["session_date"]),
        "direction": str(signal["direction"]),
        "opening_high": float(signal["opening_high"]),
        "opening_low": float(signal["opening_low"]),
        "last_sweep_time": signal["last_sweep_time"],
        "signal_time": signal["signal_time"],
        "signal_close": float(signal["signal_close"]),
        "fvg_size": float(signal["fvg_size"]),
        "stop": float(signal["stop"]),
        "target": float(signal["target"]),
        "intended_quantity": int(size.intended_quantity),
        "actual_quantity": int(size.actual_quantity),
        "entry_time": "",
        "entry_price": np.nan,
        "exit_time": "",
        "exit_price": np.nan,
        "exit_reason": "",
        "gross_pnl": 0.0,
        "commission": 0.0,
        "slippage_cost": 0.0,
        "net_pnl": 0.0,
        "intended_R": 0.0,
        "realized_R": 0.0,
        "intended_risk": float(size.intended_risk),
        "realized_risk": float(size.realized_risk),
        "risk_percent_intended": float(size.risk_percent_intended),
        "risk_percent_realized": float(size.risk_percent_realized),
        "quantity_rejection_reason": size.rejection_reason,
    }


def _finalize_trade_record(
    record: dict[str, Any],
    *,
    direction: str,
    signal_close: float,
    entry_time: pd.Timestamp,
    entry_price: float,
    exit_time: pd.Timestamp,
    exit_price: float,
    exit_reference: float,
    exit_reason: str,
    quantity: int,
    risk_per_unit: float,
    costs: CostModel,
) -> dict[str, Any]:
    gross = _gross_pnl(direction, entry_price, exit_price, quantity)
    commission = _commission(entry_price, exit_price, quantity, costs)
    slippage_cost = _slippage_cost(signal_close, entry_price, exit_reference, exit_price, quantity)
    net = gross - commission
    risk_amount = risk_per_unit * quantity
    return {
        **record,
        "actual_quantity": int(quantity),
        "entry_time": entry_time,
        "entry_price": float(entry_price),
        "exit_time": exit_time,
        "exit_price": float(exit_price),
        "exit_reason": exit_reason,
        "gross_pnl": float(gross),
        "commission": float(commission),
        "slippage_cost": float(slippage_cost),
        "net_pnl": float(net),
        "intended_R": float(gross / risk_amount) if risk_amount > 0 else 0.0,
        "realized_R": float(net / risk_amount) if risk_amount > 0 else 0.0,
    }


def serialize_trade_frame(frame: pd.DataFrame) -> pd.DataFrame:
    data = frame.copy()
    for column in ("last_sweep_time", "signal_time", "entry_time", "exit_time"):
        if column in data.columns:
            data[column] = pd.to_datetime(data[column], utc=True, errors="coerce").map(
                lambda value: value.isoformat() if pd.notna(value) else ""
            )
    return data


def summarize_trades(trades: pd.DataFrame, *, initial_equity: float = 1000.0) -> dict[str, float]:
    if trades.empty:
        return {
            "completed_trades": 0,
            "net_expectancy_R": 0.0,
            "profit_factor_net": 0.0,
            "total_net_pnl": 0.0,
            "maximum_drawdown": 0.0,
        }
    completed = trades.loc[trades["actual_quantity"].astype(float) > 0].copy()
    if completed.empty:
        return {
            "completed_trades": 0,
            "net_expectancy_R": 0.0,
            "profit_factor_net": 0.0,
            "total_net_pnl": 0.0,
            "maximum_drawdown": 0.0,
        }
    gains = completed.loc[completed["net_pnl"] > 0, "net_pnl"].sum()
    losses = completed.loc[completed["net_pnl"] < 0, "net_pnl"].sum()
    equity = initial_equity + completed["net_pnl"].cumsum()
    peak = equity.cummax()
    drawdown = ((equity - peak) / peak).min()
    return {
        "completed_trades": int(len(completed)),
        "net_expectancy_R": float(completed["realized_R"].mean()),
        "gross_expectancy_R": float(completed["intended_R"].mean()),
        "profit_factor_net": float(gains / abs(losses)) if losses < 0 else math.inf,
        "total_net_pnl": float(completed["net_pnl"].sum()),
        "maximum_drawdown": float(abs(drawdown)) if math.isfinite(drawdown) else 0.0,
        "win_rate": float((completed["net_pnl"] > 0).mean()),
        "average_win_R": float(completed.loc[completed["realized_R"] > 0, "realized_R"].mean()) if (completed["realized_R"] > 0).any() else 0.0,
        "average_loss_R": float(completed.loc[completed["realized_R"] < 0, "realized_R"].mean()) if (completed["realized_R"] < 0).any() else 0.0,
        "median_trade_R": float(completed["realized_R"].median()),
    }


def load_symbol_curated_1min(
    csv_path: str | Path,
    symbol: str,
    *,
    manifest_dir: str | Path = Path("data") / "manifests",
    calendar: EquitySessionCalendar | None = None,
) -> tuple[pd.DataFrame, DatasetManifest]:
    calendar = calendar or EquitySessionCalendar.from_config({"source": "us_equity"})
    manifest = require_or_fvg_backtest_dataset_manifest(
        csv_path,
        symbol.upper(),
        "1min",
        manifest_dir=manifest_dir,
    )
    excluded = {
        str(item.get("date"))
        for item in manifest.excluded_sessions
        if str(item.get("symbol", symbol)).upper() == symbol.upper()
    }
    frame, report = load_csv(
        csv_path,
        "1min",
        asset_class="equity",
        drop_incomplete=False,
        calendar=calendar,
        excluded_session_dates=excluded,
    )
    if not report.is_valid:
        raise ValueError(f"{symbol.upper()} dataset failed OHLCV quality validation")
    return frame, manifest


def prepare_signal_frame(
    minute_data: pd.DataFrame,
    symbol: str,
    *,
    config: FirstCandleConfig | None = None,
    calendar: EquitySessionCalendar | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    config = config or FirstCandleConfig()
    calendar = calendar or EquitySessionCalendar.from_config({"source": "us_equity"})
    five = resample_rth_1min_to_5min(minute_data, calendar)
    signals, diagnostics = detect_first_candle_signals(five, symbol, config)
    return five, signals, diagnostics


def compare_tradingview_export(
    tradingview_csv: str | Path,
    parity_csv: str | Path,
    output_csv: str | Path | None = None,
    *,
    price_tolerance: float = 0.01,
    pnl_tolerance: float = 0.01,
) -> pd.DataFrame:
    tv = pd.read_csv(tradingview_csv)
    py = pd.read_csv(parity_csv)
    key = ["symbol", "session_date", "direction"]
    missing = [column for column in key if column not in tv.columns or column not in py.columns]
    if missing:
        raise ValueError(f"Parity comparison requires columns: {missing}")
    joined = tv.merge(py, on=key, how="outer", suffixes=("_tv", "_py"), indicator=True)
    rows: list[dict[str, Any]] = []
    numeric_checks = {
        "opening_high": price_tolerance,
        "opening_low": price_tolerance,
        "signal_close": price_tolerance,
        "entry_price": price_tolerance,
        "exit_price": price_tolerance,
        "stop": price_tolerance,
        "target": price_tolerance,
        "actual_quantity": 0.0,
        "net_pnl": pnl_tolerance,
        "realized_R": pnl_tolerance,
    }
    for _, row in joined.iterrows():
        diffs: dict[str, Any] = {column: row[column] for column in key}
        diffs["match_status"] = row["_merge"]
        if row["_merge"] == "left_only":
            diffs.update(
                {
                    "parity_bucket": "missing_in_python",
                    "difference_type": "SIGNAL_LOGIC_DIFFERENCE",
                    "max_abs_diff": np.nan,
                    "failed_fields": "",
                }
            )
            rows.append(diffs)
            continue
        if row["_merge"] == "right_only":
            diffs.update(
                {
                    "parity_bucket": "missing_in_tradingview",
                    "difference_type": "SIGNAL_LOGIC_DIFFERENCE",
                    "max_abs_diff": np.nan,
                    "failed_fields": "",
                }
            )
            rows.append(diffs)
            continue
        max_abs_diff = 0.0
        failed: list[str] = []
        for column, tolerance in numeric_checks.items():
            left = row.get(f"{column}_tv")
            right = row.get(f"{column}_py")
            if pd.isna(left) or pd.isna(right):
                continue
            diff = abs(float(left) - float(right))
            diffs[f"{column}_abs_diff"] = diff
            max_abs_diff = max(max_abs_diff, diff)
            if diff > tolerance:
                failed.append(column)
        diffs["max_abs_diff"] = max_abs_diff
        diffs["failed_fields"] = ",".join(failed)
        difference_type = _classify_parity_difference(failed, row)
        diffs["difference_type"] = difference_type
        diffs["parity_bucket"] = (
            "matched_trades"
            if not failed
            else "unexplained_mismatches"
            if difference_type == "UNEXPLAINED_DIFFERENCE"
            else "field_mismatches"
        )
        rows.append(diffs)
    result = pd.DataFrame(rows)
    if output_csv is not None:
        result.to_csv(output_csv, index=False, quoting=csv.QUOTE_MINIMAL)
    return result


def _classify_parity_difference(failed_fields: list[str], row: pd.Series) -> str:
    if not failed_fields:
        return ""
    failed = set(failed_fields)
    if failed.intersection({"opening_high", "opening_low", "signal_close"}):
        return "DATA_FEED_DIFFERENCE"
    signal_times = (row.get("signal_time_tv"), row.get("signal_time_py"))
    if all(pd.notna(value) for value in signal_times) and signal_times[0] != signal_times[1]:
        return "SESSION_ALIGNMENT_DIFFERENCE"
    if failed.intersection({"stop", "target"}):
        return "SIGNAL_LOGIC_DIFFERENCE"
    if "actual_quantity" in failed:
        return "POSITION_SIZING_DIFFERENCE"
    if failed.intersection({"entry_price", "exit_price", "net_pnl", "realized_R"}):
        return "INTRABAR_EXECUTION_DIFFERENCE"
    return "UNEXPLAINED_DIFFERENCE"


def audit_components() -> list[dict[str, str]]:
    return [
        {
            "need": "Pine source lock",
            "reuse": "sha256_file",
            "file": "src/research/hyp_first_candle.py",
            "decision": "Created for HYP-FCR-01",
        },
        {
            "need": "Approved curated OHLCV manifests",
            "reuse": "require_or_fvg_backtest_dataset_manifest",
            "file": "src/data/dataset_manifest.py",
            "decision": "Reused unchanged",
        },
        {
            "need": "US equity RTH calendar, holidays, DST, early closes",
            "reuse": "EquitySessionCalendar",
            "file": "src/data/sessions.py",
            "decision": "Reused unchanged",
        },
        {
            "need": "1m to 5m RTH signal bars",
            "reuse": "resample_rth_1min_to_5min",
            "file": "src/research/qqq_s2_s5.py",
            "decision": "Reused unchanged",
        },
        {
            "need": "Existing OR/FVG strategy",
            "reuse": "OpeningRangeFVGStrategy",
            "file": "src/strategies/opening_range_fvg.py",
            "decision": "Audited but not reused as strategy logic because it is breakout, not FCR reentry",
        },
        {
            "need": "Intrabar execution",
            "reuse": "ExecutionSimulator concepts",
            "file": "src/execution_simulator/engine.py",
            "decision": "Audited; HYP-FCR-01 needs frozen target from signal_close and two modes, so execution is implemented locally",
        },
    ]


def build_prepare_manifest(
    *,
    config_path: str | Path,
    pine_path: str | Path = SOURCE_PINE_PATH,
) -> dict[str, Any]:
    return {
        "hypothesis_id": HYPOTHESIS_ID,
        "status": "preregistered_not_run",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "pine_sha256": sha256_file(pine_path),
        "config_sha256": sha256_file(config_path) if Path(config_path).exists() else "",
        "source_pine_path": str(pine_path),
        "config_path": str(config_path),
        "research_periods_executed": False,
        "discovery_executed": False,
        "validation_executed": False,
        "holdout_2026_executed": False,
        "safety_flags": dict(SAFETY_FLAGS),
        "component_audit": audit_components(),
    }


def write_prepare_manifest(path: str | Path, payload: dict[str, Any]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare HYP-FCR-01 without running research periods")
    parser.add_argument(
        "--config",
        default=str(Path("configs") / "research" / "hypotheses" / "HYP-FCR-01.yaml"),
    )
    parser.add_argument("--pine", default=str(SOURCE_PINE_PATH))
    parser.add_argument("--prepare-manifest", default="")
    parser.add_argument(
        "--run-period",
        choices=("discovery", "validation", "holdout", "parity_debug_2026"),
        help="Disabled in this preregistration task; kept to reserve the future runner interface.",
    )
    parser.add_argument("--start", default="")
    parser.add_argument("--end", default="")
    parser.add_argument(
        "--canonical-payload-sha256",
        default=EXPECTED_CANONICAL_PAYLOAD_SHA256,
    )
    parser.add_argument("--discovery-approval", default="")
    parser.add_argument("--non-decisional", action="store_true")
    parser.add_argument("--compare-tradingview-csv", default="")
    parser.add_argument("--compare-parity-csv", default="")
    parser.add_argument("--parity-output-csv", default="")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    compare_args = (args.compare_tradingview_csv, args.compare_parity_csv)
    if any(compare_args):
        if not all(compare_args):
            raise SystemExit(
                "Parity comparison requires both --compare-tradingview-csv and --compare-parity-csv."
            )
        result = compare_tradingview_export(
            args.compare_tradingview_csv,
            args.compare_parity_csv,
            args.parity_output_csv or None,
        )
        print(json.dumps(result.to_dict(orient="records"), indent=2, sort_keys=True, default=str))
        return 0
    if args.run_period:
        if not args.start or not args.end:
            raise SystemExit("HYP-FCR-01 period requests require --start and --end.")
        validate_research_period_request(
            ResearchPeriodRequest(
                period=args.run_period,
                start=_coerce_date(args.start),
                end=_coerce_date(args.end),
                canonical_payload_sha256=args.canonical_payload_sha256,
                discovery_approval_path=args.discovery_approval or None,
                non_decisional=bool(args.non_decisional),
            )
        )
        raise SystemExit(
            "HYP-FCR-01 research periods are intentionally disabled in this task. "
            "Do not run discovery, validation, or 2026 holdout."
        )
    payload = build_prepare_manifest(config_path=args.config, pine_path=args.pine)
    if args.prepare_manifest:
        write_prepare_manifest(args.prepare_manifest, payload)
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    print("Safety state: live_trading=False, broker_connected=False, orders_sent=False, paper_broker_enabled=False")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
