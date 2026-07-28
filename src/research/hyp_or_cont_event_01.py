from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.research.hyp_first_candle import (
    FirstCandleConfig,
    _as_time,
    _clock,
    add_session_columns,
    compute_opening_ranges,
)
from src.research.hyp_first_candle_event_study import (
    _qualifies_bearish_fvg,
    _qualifies_bullish_fvg,
)


HYPOTHESIS_ID = "HYP-OR-CONT-EVENT-01"
PRIMARY_HORIZON = "30min"
SECONDARY_HORIZONS = ("15min", "60min", "session_close")
HORIZONS = (PRIMARY_HORIZON, *SECONDARY_HORIZONS)
BLOCKED_PERIODS = {"validation_2025", "parity_debug_2026", "holdout", "holdout_2026"}
SAFETY_FLAGS = {
    "live_trading": False,
    "broker_connected": False,
    "orders_sent": False,
    "paper_broker_enabled": False,
}
FORBIDDEN_STRATEGY_COLUMNS = {
    "entry_price",
    "entry_time",
    "stop",
    "target",
    "quantity",
    "position_size",
    "order_id",
    "pnl",
    "net_pnl",
}


@dataclass(frozen=True)
class OrContEventConfig:
    hypothesis_id: str = HYPOTHESIS_ID
    timezone: str = "America/New_York"
    research_timeframe: str = "5min"
    opening_start: str = "09:30"
    opening_end_exclusive: str = "10:00"
    observation_start: str = "10:00"
    observation_end_exclusive: str = "16:00"
    confirmation_bar_count: int = 3
    tick_size: float = 0.01
    minimum_fvg_ticks: int = 0
    primary_horizon: str = PRIMARY_HORIZON
    secondary_horizons: tuple[str, ...] = SECONDARY_HORIZONS

    def first_candle_config(self) -> FirstCandleConfig:
        return FirstCandleConfig(
            hypothesis_id=self.hypothesis_id,
            timezone=self.timezone,
            signal_timeframe=self.research_timeframe,
            opening_start=self.opening_start,
            opening_end_exclusive=self.opening_end_exclusive,
            entry_start=self.observation_start,
            entry_end_exclusive=self.observation_end_exclusive,
            minimum_fvg_ticks=self.minimum_fvg_ticks,
        )


def canonical_or_cont_config_hash(config_path: str | Path) -> str:
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - project dependency
        raise RuntimeError("PyYAML is required to hash OR continuation config files.") from exc
    payload = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        payload.pop("canonical_payload_hash", None)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def frozen_cost_profiles() -> dict[str, dict[str, float]]:
    config = FirstCandleConfig()
    profiles: dict[str, dict[str, float]] = {}
    for name in ("baseline", "stress"):
        cost = config.cost(name)
        profiles[name] = {
            "commission_rate_per_side": float(cost.commission_rate_per_side),
            "slippage_ticks_per_execution": float(cost.slippage_ticks_per_execution),
            "tick_size": float(cost.tick_size),
            "round_trip_commission_rate": float(2 * cost.commission_rate_per_side),
            "round_trip_slippage_ticks": float(2 * cost.slippage_ticks_per_execution),
            "round_trip_slippage_dollars_per_share": float(2 * cost.slippage_value),
        }
    return profiles


def round_trip_cost_return(profile_name: str, executable_price: float) -> float:
    profiles = frozen_cost_profiles()
    if profile_name not in profiles:
        raise ValueError(f"Unknown cost profile: {profile_name}")
    if executable_price <= 0 or not np.isfinite(executable_price):
        raise ValueError("executable_price must be positive and finite")
    profile = profiles[profile_name]
    return float(profile["round_trip_commission_rate"] + profile["round_trip_slippage_dollars_per_share"] / executable_price)


def validate_or_cont_period(period: str) -> None:
    if period in BLOCKED_PERIODS or "2025" in period or "2026" in period:
        raise PermissionError(f"{HYPOTHESIS_ID} period is blocked: {period}")
    if period != "discovery_2022_2024":
        raise PermissionError(f"{HYPOTHESIS_ID} only preregisters discovery_2022_2024 for a future run.")


def _bar_close(timestamp: pd.Timestamp, minutes: int = 5) -> pd.Timestamp:
    return pd.Timestamp(timestamp) + pd.Timedelta(value=minutes, unit="min")


def _candidate_from_sweep(
    session: pd.DataFrame,
    position: int,
    *,
    swept_side: str,
    opening_low: float,
    opening_high: float,
    symbol: str,
    session_date: str,
    config: OrContEventConfig,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    required = config.confirmation_bar_count
    confirmation_positions = list(range(position + 1, position + 1 + required))
    if confirmation_positions[-1] >= len(session):
        return None, {
            "symbol": symbol.upper(),
            "session_date": session_date,
            "sweep_timestamp": pd.Timestamp(session.loc[position, "timestamp"]),
            "swept_side": swept_side,
            "reason_for_exclusion": "insufficient_confirmation_bars",
        }
    executable_position = position + required + 1
    if executable_position >= len(session):
        return None, {
            "symbol": symbol.upper(),
            "session_date": session_date,
            "sweep_timestamp": pd.Timestamp(session.loc[position, "timestamp"]),
            "confirmation_timestamp": _bar_close(session.loc[confirmation_positions[-1], "timestamp"]),
            "swept_side": swept_side,
            "reason_for_exclusion": "no_executable_bar_before_session_close",
        }
    if swept_side == "low":
        has_opposing_fvg = any(
            _qualifies_bullish_fvg(session, candidate, opening_low, opening_high, config)[0]
            for candidate in confirmation_positions
        )
        orientation = "continuation_short"
    elif swept_side == "high":
        has_opposing_fvg = any(
            _qualifies_bearish_fvg(session, candidate, opening_low, opening_high, config)[0]
            for candidate in confirmation_positions
        )
        orientation = "continuation_long"
    else:
        raise ValueError(f"Unsupported swept_side: {swept_side}")
    if has_opposing_fvg:
        return None, {
            "symbol": symbol.upper(),
            "session_date": session_date,
            "sweep_timestamp": pd.Timestamp(session.loc[position, "timestamp"]),
            "confirmation_timestamp": _bar_close(session.loc[confirmation_positions[-1], "timestamp"]),
            "swept_side": swept_side,
            "reason_for_exclusion": "opposing_fvg_present_in_confirmation_window",
        }
    confirmation_timestamp = _bar_close(session.loc[confirmation_positions[-1], "timestamp"])
    executable_timestamp = pd.Timestamp(session.loc[executable_position, "timestamp"])
    if executable_timestamp != confirmation_timestamp:
        return None, {
            "symbol": symbol.upper(),
            "session_date": session_date,
            "sweep_timestamp": pd.Timestamp(session.loc[position, "timestamp"]),
            "confirmation_timestamp": confirmation_timestamp,
            "executable_timestamp": executable_timestamp,
            "swept_side": swept_side,
            "reason_for_exclusion": "non_contiguous_executable_bar",
        }
    return {
        "hypothesis_id": HYPOTHESIS_ID,
        "symbol": symbol.upper(),
        "session_date": session_date,
        "sweep_timestamp": pd.Timestamp(session.loc[position, "timestamp"]),
        "confirmation_timestamp": confirmation_timestamp,
        "executable_timestamp": executable_timestamp,
        "swept_side": swept_side,
        "direction_orientation": orientation,
        "confirmation_bar_count": int(required),
        "reason_for_exclusion": "",
        "opening_high": float(opening_high),
        "opening_low": float(opening_low),
        "executable_price_reference": float(session.loc[executable_position, "open"]),
    }, None


def detect_or_continuation_events(
    five_minute: pd.DataFrame,
    symbol: str,
    config: OrContEventConfig | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    config = config or OrContEventConfig()
    fcr_config = config.first_candle_config()
    data = add_session_columns(five_minute, fcr_config)
    ranges = compute_opening_ranges(data, fcr_config)
    if ranges.empty:
        return pd.DataFrame(), pd.DataFrame()
    enriched = data.merge(ranges, on="session_date", how="left")
    observation_start = _as_time(config.observation_start)
    observation_end = _as_time(config.observation_end_exclusive)
    events: list[dict[str, Any]] = []
    exclusions: list[dict[str, Any]] = []

    for session_date, session in enriched.groupby("session_date", sort=True):
        session = session.reset_index(drop=True)
        if session["opening_high"].isna().all():
            continue
        opening_high = float(session["opening_high"].iloc[0])
        opening_low = float(session["opening_low"].iloc[0])
        for position, row in session.iterrows():
            clock = _clock(row["timestamp"], fcr_config)
            if not (observation_start <= clock < observation_end):
                continue
            candidates: list[tuple[str, bool]] = [
                ("low", float(row["low"]) <= opening_low),
                ("high", float(row["high"]) >= opening_high),
            ]
            for swept_side, touched in candidates:
                if not touched:
                    continue
                event, exclusion = _candidate_from_sweep(
                    session,
                    int(position),
                    swept_side=swept_side,
                    opening_low=opening_low,
                    opening_high=opening_high,
                    symbol=symbol,
                    session_date=str(session_date),
                    config=config,
                )
                if exclusion is not None:
                    exclusions.append(exclusion)
                if event is not None:
                    events.append(event)
                    break
            if events and events[-1]["session_date"] == str(session_date):
                break
    return pd.DataFrame(events), pd.DataFrame(exclusions)


def _horizon_delta(horizon: str) -> pd.Timedelta | None:
    if horizon == "session_close":
        return None
    if not horizon.endswith("min"):
        raise ValueError(f"Unsupported horizon: {horizon}")
    return pd.Timedelta(value=int(horizon[:-3]), unit="min")


def compute_or_continuation_paths(
    five_minute: pd.DataFrame,
    events: pd.DataFrame,
    *,
    horizons: tuple[str, ...] = HORIZONS,
    config: OrContEventConfig | None = None,
) -> pd.DataFrame:
    config = config or OrContEventConfig()
    if events.empty:
        return pd.DataFrame()
    data = add_session_columns(five_minute, config.first_candle_config()).reset_index(drop=True)
    rows: list[dict[str, Any]] = []
    for _, event in events.iterrows():
        session = data.loc[data["session_date"] == str(event["session_date"])].reset_index(drop=True)
        executable_timestamp = pd.Timestamp(event["executable_timestamp"])
        start_positions = session.index[session["timestamp"] == executable_timestamp].tolist()
        if not start_positions:
            continue
        start_position = int(start_positions[0])
        start_price = float(session.loc[start_position, "open"])
        for horizon in horizons:
            delta = _horizon_delta(horizon)
            if delta is None:
                target_position = len(session) - 1
            else:
                target_timestamp = executable_timestamp + delta
                matches = session.index[session["timestamp"] == target_timestamp].tolist()
                if not matches:
                    continue
                target_position = int(matches[0])
            if target_position <= start_position:
                continue
            path = session.iloc[start_position : target_position + 1]
            future_close = float(session.loc[target_position, "close"])
            raw_return = future_close / start_price - 1.0
            orientation = str(event["direction_orientation"])
            event_return = -raw_return if orientation == "continuation_short" else raw_return
            if orientation == "continuation_short":
                mfe = start_price / path["low"].astype(float).min() - 1.0
                mae = 1.0 - start_price / path["high"].astype(float).max()
            else:
                mfe = path["high"].astype(float).max() / start_price - 1.0
                mae = path["low"].astype(float).min() / start_price - 1.0
            rows.append(
                {
                    "hypothesis_id": HYPOTHESIS_ID,
                    "symbol": str(event["symbol"]),
                    "session_date": str(event["session_date"]),
                    "sweep_timestamp": pd.Timestamp(event["sweep_timestamp"]),
                    "confirmation_timestamp": pd.Timestamp(event["confirmation_timestamp"]),
                    "executable_timestamp": executable_timestamp,
                    "direction_orientation": orientation,
                    "horizon": horizon,
                    "event_return": float(event_return),
                    "future_close": future_close,
                    "maximum_favorable_excursion": float(mfe),
                    "maximum_adverse_excursion": float(mae),
                    "bars_in_path": int(len(path)),
                }
            )
    return pd.DataFrame(rows)


def assert_no_strategy_columns(frame: pd.DataFrame) -> None:
    forbidden = FORBIDDEN_STRATEGY_COLUMNS.intersection(set(frame.columns))
    if forbidden:
        raise AssertionError(f"Forbidden strategy columns present: {sorted(forbidden)}")

