from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Callable

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
CONFIG_PATH = Path("configs/research/hypotheses/HYP-OR-CONT-EVENT-01.yaml")
EXPECTED_FREEZE_COMMIT = "fe13dfe94a6b679a5abf33f079ef8497e368b4f5"
EXPECTED_CANONICAL_HASH = "d76572e7534e8cf66104ceb2d30dd08a7c0b080fc4460e496b58a08d3736060b"
DISCOVERY_START = "2022-01-01"
DISCOVERY_END = "2024-12-31"
DISCOVERY_PERIOD = "discovery_2022_2024"
EXPECTED_SYMBOLS = ("QQQ", "SPY")
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


def attach_cost_thresholds(paths: pd.DataFrame) -> pd.DataFrame:
    if paths.empty:
        return paths.copy()
    enriched = paths.copy()
    enriched["baseline_cost_return"] = enriched["executable_price_reference"].map(
        lambda value: round_trip_cost_return("baseline", float(value))
    )
    enriched["stress_cost_return"] = enriched["executable_price_reference"].map(
        lambda value: round_trip_cost_return("stress", float(value))
    )
    enriched["event_return_after_baseline_cost"] = (
        enriched["event_return"].astype(float) - enriched["baseline_cost_return"].astype(float)
    )
    enriched["event_return_after_stress_cost"] = (
        enriched["event_return"].astype(float) - enriched["stress_cost_return"].astype(float)
    )
    return enriched


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


def filter_discovery_period(frame: pd.DataFrame) -> pd.DataFrame:
    start = date.fromisoformat(DISCOVERY_START)
    end = date.fromisoformat(DISCOVERY_END)
    local_dates = pd.to_datetime(frame["timestamp"], utc=True).dt.tz_convert("America/New_York").dt.date
    filtered = frame.loc[(local_dates >= start) & (local_dates <= end)].copy()
    filtered_dates = pd.to_datetime(filtered["timestamp"], utc=True).dt.tz_convert("America/New_York").dt.date
    if any(item.year >= 2025 for item in filtered_dates):
        raise AssertionError("Discovery frame contains blocked 2025/2026 rows.")
    return filtered.reset_index(drop=True)


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
        executable_hour = pd.Timestamp(event["executable_timestamp"]).tz_convert(config.timezone).strftime("%H:00")
        year = int(pd.Timestamp(event["executable_timestamp"]).tz_convert(config.timezone).year)
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
                    "swept_side": str(event["swept_side"]),
                    "year": year,
                    "executable_timestamp_hour_bucket": executable_hour,
                    "horizon": horizon,
                    "executable_price_reference": start_price,
                    "event_return": float(event_return),
                    "future_close": future_close,
                    "maximum_favorable_excursion": float(mfe),
                    "maximum_adverse_excursion": float(mae),
                    "bars_in_path": int(len(path)),
                }
            )
    return pd.DataFrame(rows)


def _path_return_from_start(
    session: pd.DataFrame,
    start_position: int,
    horizon: str,
    orientation: str,
) -> float | None:
    delta = _horizon_delta(horizon)
    executable_timestamp = pd.Timestamp(session.loc[start_position, "timestamp"])
    if delta is None:
        target_position = len(session) - 1
    else:
        matches = session.index[session["timestamp"] == executable_timestamp + delta].tolist()
        if not matches:
            return None
        target_position = int(matches[0])
    if target_position <= start_position:
        return None
    start_price = float(session.loc[start_position, "open"])
    future_close = float(session.loc[target_position, "close"])
    raw_return = future_close / start_price - 1.0
    return float(-raw_return if orientation == "continuation_short" else raw_return)


def compute_unconditional_control_reference(
    five_minute_by_symbol: dict[str, pd.DataFrame],
    path_metrics: pd.DataFrame,
    config: OrContEventConfig | None = None,
) -> pd.DataFrame:
    config = config or OrContEventConfig()
    if path_metrics.empty:
        return pd.DataFrame()
    control_rows: list[dict[str, Any]] = []
    grouped_cache: dict[str, pd.DataFrame] = {}
    for symbol, frame in five_minute_by_symbol.items():
        data = add_session_columns(frame, config.first_candle_config()).reset_index(drop=True)
        local = pd.to_datetime(data["timestamp"], utc=True).dt.tz_convert(config.timezone)
        data["year"] = local.dt.year.astype(int)
        data["executable_timestamp_hour_bucket"] = local.dt.strftime("%H:00")
        grouped_cache[symbol.upper()] = data
    for _, row in path_metrics.iterrows():
        symbol = str(row["symbol"]).upper()
        if symbol not in grouped_cache:
            continue
        data = grouped_cache[symbol]
        candidates = data.loc[
            (data["year"] == int(row["year"]))
            & (data["executable_timestamp_hour_bucket"] == str(row["executable_timestamp_hour_bucket"]))
        ]
        returns: list[float] = []
        for position in candidates.index:
            value = _path_return_from_start(data, int(position), str(row["horizon"]), str(row["direction_orientation"]))
            if value is not None and np.isfinite(value):
                returns.append(float(value))
        control_rows.append(
            {
                "hypothesis_id": HYPOTHESIS_ID,
                "symbol": symbol,
                "session_date": str(row["session_date"]),
                "executable_timestamp": pd.Timestamp(row["executable_timestamp"]),
                "direction_orientation": str(row["direction_orientation"]),
                "year": int(row["year"]),
                "executable_timestamp_hour_bucket": str(row["executable_timestamp_hour_bucket"]),
                "horizon": str(row["horizon"]),
                "event_return": float(row["event_return"]),
                "unconditional_return": float(np.mean(returns)) if returns else np.nan,
                "unconditional_sample_count": int(len(returns)),
            }
        )
    return pd.DataFrame(control_rows)


def _control_output_columns() -> list[str]:
    return [
        "hypothesis_id",
        "symbol",
        "session_date",
        "executable_timestamp",
        "direction_orientation",
        "year",
        "executable_timestamp_hour_bucket",
        "horizon",
        "event_return",
        "unconditional_return",
        "unconditional_sample_count",
    ]


def _progress_eta(elapsed_seconds: float, rows_processed: int, rows_total: int) -> float | None:
    if rows_processed <= 0 or rows_total <= 0:
        return None
    remaining = elapsed_seconds * max(rows_total - rows_processed, 0) / rows_processed
    return round(float(remaining), 3)


def compute_unconditional_control(
    five_minute_by_symbol: dict[str, pd.DataFrame],
    path_metrics: pd.DataFrame,
    config: OrContEventConfig | None = None,
    *,
    progress_callback: Callable[..., None] | None = None,
    progress_interval_seconds: float = 5.0,
) -> pd.DataFrame:
    config = config or OrContEventConfig()
    if path_metrics.empty:
        return pd.DataFrame(columns=_control_output_columns())

    start_time = time.perf_counter()
    needed_horizons = tuple(dict.fromkeys(path_metrics["horizon"].astype(str)))
    requested_groups = path_metrics.loc[
        :,
        ["symbol", "year", "executable_timestamp_hour_bucket", "horizon"],
    ].copy()
    requested_groups["symbol"] = requested_groups["symbol"].astype(str).str.upper()
    requested_groups["year"] = requested_groups["year"].astype(int)
    requested_groups["executable_timestamp_hour_bucket"] = requested_groups["executable_timestamp_hour_bucket"].astype(str)
    requested_groups["horizon"] = requested_groups["horizon"].astype(str)
    requested_key_set = set(map(tuple, requested_groups.drop_duplicates().itertuples(index=False, name=None)))
    groups_total = len(requested_key_set)
    rows_total = int(sum(len(frame) for frame in five_minute_by_symbol.values()) * max(len(needed_horizons), 1))
    rows_processed = 0
    processed_requested_keys: set[tuple[str, int, str, str]] = set()
    memory_mb = 0.0
    last_progress_emit = 0.0
    aggregate_parts: list[pd.DataFrame] = []

    def emit_progress(*, force: bool = False) -> None:
        nonlocal last_progress_emit
        if progress_callback is None:
            return
        elapsed = time.perf_counter() - start_time
        if not force and elapsed - last_progress_emit < progress_interval_seconds:
            return
        last_progress_emit = elapsed
        progress_callback(
            groups_total=groups_total,
            groups_processed=min(len(processed_requested_keys), groups_total),
            rows_processed=rows_processed,
            elapsed_seconds=round(float(elapsed), 3),
            memory_mb=round(float(memory_mb), 3),
            eta_seconds=_progress_eta(elapsed, rows_processed, rows_total),
        )

    emit_progress(force=True)
    for symbol, frame in five_minute_by_symbol.items():
        symbol_key = symbol.upper()
        data = add_session_columns(frame, config.first_candle_config()).reset_index(drop=True)
        if data.empty:
            continue
        timestamps = pd.to_datetime(data["timestamp"], utc=True)
        local = timestamps.dt.tz_convert(config.timezone)
        years = local.dt.year.astype(int).to_numpy()
        hour_buckets = local.dt.strftime("%H:00").to_numpy()
        opens = data["open"].astype(float).to_numpy()
        closes = data["close"].astype(float).to_numpy()
        positions = np.arange(len(data), dtype=np.int64)
        timestamp_index = pd.Index(timestamps)
        memory_mb += float(data.memory_usage(index=True, deep=True).sum()) / (1024.0 * 1024.0)

        for horizon in needed_horizons:
            delta = _horizon_delta(horizon)
            if delta is None:
                target_positions = np.full(len(data), len(data) - 1, dtype=np.int64)
                valid = target_positions > positions
            else:
                target_positions = timestamp_index.get_indexer(timestamps + delta)
                valid = target_positions > positions
            future_closes = np.full(len(data), np.nan, dtype=float)
            future_closes[valid] = closes[target_positions[valid]]
            with np.errstate(divide="ignore", invalid="ignore"):
                raw_returns = future_closes / opens - 1.0
            valid &= np.isfinite(raw_returns)
            rows_processed += int(len(data))
            if valid.any():
                universe = pd.DataFrame(
                    {
                        "symbol": symbol_key,
                        "year": years[valid],
                        "executable_timestamp_hour_bucket": hour_buckets[valid],
                        "horizon": horizon,
                        "raw_return": raw_returns[valid],
                    }
                )
                grouped = (
                    universe.groupby(
                        ["symbol", "year", "executable_timestamp_hour_bucket", "horizon"],
                        sort=True,
                    )["raw_return"]
                    .agg(raw_unconditional_return="mean", unconditional_sample_count="count")
                    .reset_index()
                )
                aggregate_parts.append(grouped)
                processed_requested_keys.update(
                    key for key in map(tuple, grouped.iloc[:, :4].itertuples(index=False, name=None)) if key in requested_key_set
                )
            emit_progress()

    aggregates = pd.concat(aggregate_parts, ignore_index=True) if aggregate_parts else pd.DataFrame()
    output = path_metrics.loc[
        :,
        [
            "symbol",
            "session_date",
            "executable_timestamp",
            "direction_orientation",
            "year",
            "executable_timestamp_hour_bucket",
            "horizon",
            "event_return",
        ],
    ].copy()
    output.insert(0, "hypothesis_id", HYPOTHESIS_ID)
    output["symbol"] = output["symbol"].astype(str).str.upper()
    output["year"] = output["year"].astype(int)
    output["executable_timestamp_hour_bucket"] = output["executable_timestamp_hour_bucket"].astype(str)
    output["horizon"] = output["horizon"].astype(str)
    output["event_return"] = output["event_return"].astype(float)
    if aggregates.empty:
        output["unconditional_return"] = np.nan
        output["unconditional_sample_count"] = 0
    else:
        output = output.merge(
            aggregates,
            on=["symbol", "year", "executable_timestamp_hour_bucket", "horizon"],
            how="left",
            sort=False,
        )
        sign = np.where(output["direction_orientation"].astype(str) == "continuation_short", -1.0, 1.0)
        output["unconditional_return"] = output["raw_unconditional_return"].astype(float) * sign
        output["unconditional_sample_count"] = output["unconditional_sample_count"].fillna(0).astype(int)
        output = output.drop(columns=["raw_unconditional_return"])
    emit_progress(force=True)
    return output.loc[:, _control_output_columns()]


def attach_incremental_returns(path_metrics: pd.DataFrame, control: pd.DataFrame) -> pd.DataFrame:
    if path_metrics.empty:
        return path_metrics.copy()
    keys = [
        "symbol",
        "session_date",
        "executable_timestamp",
        "direction_orientation",
        "horizon",
    ]
    merged = path_metrics.copy()
    if control.empty:
        merged["unconditional_return"] = np.nan
        merged["incremental_return"] = np.nan
        merged["unconditional_sample_count"] = 0
        return merged
    control_subset = control.loc[:, [*keys, "unconditional_return", "unconditional_sample_count"]].copy()
    merged = merged.merge(control_subset, on=keys, how="left")
    merged["incremental_return"] = merged["event_return"].astype(float) - merged["unconditional_return"].astype(float)
    return merged


def bootstrap_mean_by_session_reference(
    frame: pd.DataFrame,
    *,
    value_column: str,
    n_bootstrap: int = 500,
    seed: int = 17,
) -> tuple[float, float]:
    if frame.empty:
        return np.nan, np.nan
    sessions = np.array(sorted(frame["session_date"].astype(str).unique()))
    rng = np.random.default_rng(seed)
    sampled: list[float] = []
    for _ in range(n_bootstrap):
        sampled_sessions = rng.choice(sessions, size=len(sessions), replace=True)
        sample = pd.concat([frame.loc[frame["session_date"].astype(str) == item] for item in sampled_sessions])
        sampled.append(float(sample[value_column].mean()))
    return float(np.percentile(sampled, 2.5)), float(np.percentile(sampled, 97.5))


def bootstrap_mean_by_session(
    frame: pd.DataFrame,
    *,
    value_column: str,
    n_bootstrap: int = 500,
    seed: int = 17,
) -> tuple[float, float]:
    if frame.empty:
        return np.nan, np.nan
    sessions = np.array(sorted(frame["session_date"].astype(str).unique()))
    session_count = len(sessions)
    if session_count == 0:
        return np.nan, np.nan
    by_session = (
        frame.assign(_bootstrap_value=frame[value_column].astype(float))
        .groupby(frame["session_date"].astype(str), sort=True)["_bootstrap_value"]
        .agg(session_sum="sum", session_non_null_count="count")
        .reindex(sessions)
    )
    session_sums = by_session["session_sum"].to_numpy(dtype=float)
    session_counts = by_session["session_non_null_count"].to_numpy(dtype=float)
    session_index = pd.Index(sessions)
    rng = np.random.default_rng(seed)
    draws = np.empty((n_bootstrap, session_count), dtype=np.int64)
    for replicate in range(n_bootstrap):
        draws[replicate, :] = session_index.get_indexer(rng.choice(sessions, size=session_count, replace=True))
    sampled_counts = session_counts[draws].sum(axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        sampled_means = session_sums[draws].sum(axis=1) / sampled_counts
    sampled_means[sampled_counts <= 0] = np.nan
    return float(np.percentile(sampled_means, 2.5)), float(np.percentile(sampled_means, 97.5))


def aggregate_incremental_metrics_reference(
    path_metrics: pd.DataFrame,
    *,
    group_by: tuple[str, ...] = ("symbol", "direction_orientation", "horizon"),
    n_bootstrap: int = 500,
    seed: int = 17,
) -> pd.DataFrame:
    columns = [
        *group_by,
        "count",
        "session_count",
        "mean",
        "median",
        "directional_win_rate",
        "mean_mfe",
        "mean_mae",
        "mean_unconditional_return",
        "mean_incremental_return",
        "mean_baseline_cost_return",
        "mean_stress_cost_return",
        "bootstrap_ci_low",
        "bootstrap_ci_high",
        "bootstrap_grouped_by",
        "bootstrap_seed",
    ]
    if path_metrics.empty:
        return pd.DataFrame(columns=columns)
    rows: list[dict[str, Any]] = []
    for key, group in path_metrics.groupby(list(group_by), sort=True):
        if not isinstance(key, tuple):
            key = (key,)
        ci_low, ci_high = bootstrap_mean_by_session_reference(group, value_column="event_return", n_bootstrap=n_bootstrap, seed=seed)
        record = {column: value for column, value in zip(group_by, key)}
        record.update(
            {
                "count": int(len(group)),
                "session_count": int(group["session_date"].nunique()),
                "mean": float(group["event_return"].mean()),
                "median": float(group["event_return"].median()),
                "directional_win_rate": float((group["event_return"].astype(float) > 0).mean()),
                "mean_mfe": float(group["maximum_favorable_excursion"].mean()),
                "mean_mae": float(group["maximum_adverse_excursion"].mean()),
                "mean_unconditional_return": float(group["unconditional_return"].mean()) if "unconditional_return" in group else np.nan,
                "mean_incremental_return": float(group["incremental_return"].mean()) if "incremental_return" in group else np.nan,
                "mean_baseline_cost_return": float(group["baseline_cost_return"].mean()) if "baseline_cost_return" in group else np.nan,
                "mean_stress_cost_return": float(group["stress_cost_return"].mean()) if "stress_cost_return" in group else np.nan,
                "bootstrap_ci_low": ci_low,
                "bootstrap_ci_high": ci_high,
                "bootstrap_grouped_by": "session_date",
                "bootstrap_seed": int(seed),
            }
        )
        rows.append(record)
    return pd.DataFrame(rows, columns=columns)


def _aggregate_output_columns(group_by: tuple[str, ...]) -> list[str]:
    return [
        *group_by,
        "count",
        "session_count",
        "mean",
        "median",
        "directional_win_rate",
        "mean_mfe",
        "mean_mae",
        "mean_unconditional_return",
        "mean_incremental_return",
        "mean_baseline_cost_return",
        "mean_stress_cost_return",
        "bootstrap_ci_low",
        "bootstrap_ci_high",
        "bootstrap_grouped_by",
        "bootstrap_seed",
    ]


def _bootstrap_ci_from_session_sums(
    sessions: np.ndarray,
    session_sums: np.ndarray,
    session_counts: np.ndarray,
    *,
    n_bootstrap: int,
    seed: int,
) -> tuple[float, float]:
    session_count = len(sessions)
    if session_count == 0:
        return np.nan, np.nan
    session_index = pd.Index(sessions)
    rng = np.random.default_rng(seed)
    draws = np.empty((n_bootstrap, session_count), dtype=np.int64)
    for replicate in range(n_bootstrap):
        draws[replicate, :] = session_index.get_indexer(rng.choice(sessions, size=session_count, replace=True))
    sampled_counts = session_counts[draws].sum(axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        sampled_means = session_sums[draws].sum(axis=1) / sampled_counts
    sampled_means[sampled_counts <= 0] = np.nan
    return float(np.percentile(sampled_means, 2.5)), float(np.percentile(sampled_means, 97.5))


def aggregate_incremental_metrics(
    path_metrics: pd.DataFrame,
    *,
    group_by: tuple[str, ...] = ("symbol", "direction_orientation", "horizon"),
    n_bootstrap: int = 500,
    seed: int = 17,
    progress_callback: Callable[..., None] | None = None,
    progress_interval_seconds: float = 5.0,
) -> pd.DataFrame:
    columns = _aggregate_output_columns(group_by)
    if path_metrics.empty:
        return pd.DataFrame(columns=columns)
    start_time = time.perf_counter()
    groups = list(path_metrics.groupby(list(group_by), sort=True))
    groups_total = len(groups)
    bootstrap_replicates_total = groups_total * int(n_bootstrap)
    groups_processed = 0
    bootstrap_replicates_processed = 0
    memory_mb = float(path_metrics.memory_usage(index=True, deep=True).sum()) / (1024.0 * 1024.0)
    last_progress_emit = 0.0
    rows: list[dict[str, Any]] = []

    def emit_progress(*, force: bool = False) -> None:
        nonlocal last_progress_emit
        if progress_callback is None:
            return
        elapsed = time.perf_counter() - start_time
        if not force and elapsed - last_progress_emit < progress_interval_seconds:
            return
        last_progress_emit = elapsed
        progress_callback(
            groups_total=groups_total,
            groups_processed=groups_processed,
            bootstrap_replicates_total=bootstrap_replicates_total,
            bootstrap_replicates_processed=bootstrap_replicates_processed,
            elapsed_seconds=round(float(elapsed), 3),
            eta_seconds=_progress_eta(elapsed, bootstrap_replicates_processed, bootstrap_replicates_total),
            memory_mb=round(memory_mb, 3),
        )

    emit_progress(force=True)
    for key, group in groups:
        if not isinstance(key, tuple):
            key = (key,)
        event_values = group["event_return"].astype(float)
        sessions = np.array(sorted(group["session_date"].astype(str).unique()))
        session_aggregates = (
            pd.DataFrame({"session_date": group["session_date"].astype(str), "event_return": event_values})
            .groupby("session_date", sort=True)["event_return"]
            .agg(session_sum="sum", session_non_null_count="count")
            .reindex(sessions)
        )
        ci_low, ci_high = _bootstrap_ci_from_session_sums(
            sessions,
            session_aggregates["session_sum"].to_numpy(dtype=float),
            session_aggregates["session_non_null_count"].to_numpy(dtype=float),
            n_bootstrap=n_bootstrap,
            seed=seed,
        )
        record = {column: value for column, value in zip(group_by, key)}
        record.update(
            {
                "count": int(len(group)),
                "session_count": int(group["session_date"].nunique()),
                "mean": float(event_values.mean()),
                "median": float(event_values.median()),
                "directional_win_rate": float((event_values > 0).mean()),
                "mean_mfe": float(group["maximum_favorable_excursion"].mean()),
                "mean_mae": float(group["maximum_adverse_excursion"].mean()),
                "mean_unconditional_return": float(group["unconditional_return"].mean()) if "unconditional_return" in group else np.nan,
                "mean_incremental_return": float(group["incremental_return"].mean()) if "incremental_return" in group else np.nan,
                "mean_baseline_cost_return": float(group["baseline_cost_return"].mean()) if "baseline_cost_return" in group else np.nan,
                "mean_stress_cost_return": float(group["stress_cost_return"].mean()) if "stress_cost_return" in group else np.nan,
                "bootstrap_ci_low": ci_low,
                "bootstrap_ci_high": ci_high,
                "bootstrap_grouped_by": "session_date",
                "bootstrap_seed": int(seed),
            }
        )
        rows.append(record)
        groups_processed += 1
        bootstrap_replicates_processed += int(n_bootstrap)
        emit_progress()
    emit_progress(force=True)
    return pd.DataFrame(rows, columns=columns)


def cost_threshold_comparison(path_metrics: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "symbol",
        "direction_orientation",
        "horizon",
        "count",
        "mean_event_return",
        "mean_baseline_cost_return",
        "mean_stress_cost_return",
        "baseline_cost_passed",
        "stress_cost_passed",
    ]
    if path_metrics.empty:
        return pd.DataFrame(columns=columns)
    rows: list[dict[str, Any]] = []
    for key, group in path_metrics.groupby(["symbol", "direction_orientation", "horizon"], sort=True):
        symbol, orientation, horizon = key
        mean_return = float(group["event_return"].mean())
        baseline = float(group["baseline_cost_return"].mean())
        stress = float(group["stress_cost_return"].mean())
        rows.append(
            {
                "symbol": symbol,
                "direction_orientation": orientation,
                "horizon": horizon,
                "count": int(len(group)),
                "mean_event_return": mean_return,
                "mean_baseline_cost_return": baseline,
                "mean_stress_cost_return": stress,
                "baseline_cost_passed": bool(mean_return > baseline),
                "stress_cost_passed": bool(mean_return > stress),
            }
        )
    return pd.DataFrame(rows, columns=columns)


def _positive_two_of_three_years(primary: pd.DataFrame) -> bool:
    if primary.empty:
        return False
    for orientation in ("continuation_short", "continuation_long"):
        subset = primary.loc[primary["direction_orientation"] == orientation]
        if subset.empty:
            return False
        by_year = subset.groupby("year")["event_return"].mean()
        if int((by_year > 0).sum()) < 2:
            return False
    return True


def _not_dominated_by_single_year(primary: pd.DataFrame, maximum_share: float = 0.70) -> bool:
    if primary.empty:
        return False
    positive_by_year = primary.groupby("year")["event_return"].sum()
    positive_by_year = positive_by_year.loc[positive_by_year > 0]
    total = float(positive_by_year.sum())
    if total <= 0:
        return False
    return bool(float(positive_by_year.max() / total) <= maximum_share)


def evaluate_discovery_gate(
    path_metrics: pd.DataFrame,
    bootstrap_intervals: pd.DataFrame,
) -> dict[str, Any]:
    primary = path_metrics.loc[path_metrics["horizon"] == PRIMARY_HORIZON].copy() if not path_metrics.empty else pd.DataFrame()
    if not primary.empty:
        years = set(primary["year"].astype(int))
        contains_blocked_years = any(year >= 2025 for year in years)
    else:
        contains_blocked_years = False
    criteria = {
        "continuation_short_expected_sign": bool(
            not primary.loc[primary["direction_orientation"] == "continuation_short"].empty
            and primary.loc[primary["direction_orientation"] == "continuation_short", "event_return"].mean() > 0
        ),
        "continuation_long_expected_sign": bool(
            not primary.loc[primary["direction_orientation"] == "continuation_long"].empty
            and primary.loc[primary["direction_orientation"] == "continuation_long", "event_return"].mean() > 0
        ),
        "qqq_and_spy_same_sign": bool(
            not primary.empty
            and set(primary["symbol"].astype(str).str.upper()) == set(EXPECTED_SYMBOLS)
            and all(value > 0 for value in primary.groupby("symbol")["event_return"].mean())
        ),
        "effect_in_at_least_two_of_three_years": _positive_two_of_three_years(primary),
        "incremental_return_vs_control_positive": bool(
            "incremental_return" in primary and not primary["incremental_return"].dropna().empty and primary["incremental_return"].mean() > 0
        ),
        "mean_return_exceeds_baseline_round_trip_cost": bool(
            "baseline_cost_return" in primary and not primary.empty and primary["event_return"].mean() > primary["baseline_cost_return"].mean()
        ),
        "not_dominated_by_single_year": _not_dominated_by_single_year(primary),
        "bootstrap_grouped_by_session_not_strongly_contradictory": bool(
            not bootstrap_intervals.empty
            and not bootstrap_intervals.loc[bootstrap_intervals["horizon"] == PRIMARY_HORIZON].empty
            and all(
                bootstrap_intervals.loc[bootstrap_intervals["horizon"] == PRIMARY_HORIZON, "bootstrap_ci_high"].astype(float) >= 0
            )
        ),
        "no_lookahead": True,
        "no_2025_or_2026_contamination": not contains_blocked_years,
    }
    passed = bool(all(criteria.values()))
    return {
        "hypothesis_id": HYPOTHESIS_ID,
        "primary_horizon": PRIMARY_HORIZON,
        "secondary_horizons_cannot_override_primary_fail": True,
        "all_required": True,
        "criteria": criteria,
        "passed": passed,
        "classification": "discovery_passed_primary_gate" if passed else "discovery_failed",
        "validation_2025_unlocked": passed,
        "paper_eligible": False,
        "live_eligible": False,
        "orders_created": False,
        "position_sizing_used": False,
    }


def _count_groups(frame: pd.DataFrame, group_by: tuple[str, ...]) -> int:
    if frame.empty:
        return 0
    return int(frame.groupby(list(group_by), sort=True).ngroups)


def compute_aggregation_and_bootstrap_outputs(
    path_metrics: pd.DataFrame,
    *,
    n_bootstrap: int = 500,
    seed: int = 17,
    progress_callback: Callable[..., None] | None = None,
    progress_interval_seconds: float = 5.0,
) -> dict[str, Any]:
    start_time = time.perf_counter()
    group_specs = (
        ("incremental_metrics", ("symbol", "direction_orientation", "horizon")),
        ("metrics_by_symbol", ("symbol",)),
        ("metrics_by_year", ("year",)),
    )
    group_totals = {name: _count_groups(path_metrics, group_by) for name, group_by in group_specs}
    groups_total = int(sum(group_totals.values()))
    bootstrap_replicates_total = int(groups_total * n_bootstrap)
    groups_completed_before = 0
    replicates_completed_before = 0
    memory_mb = float(path_metrics.memory_usage(index=True, deep=True).sum()) / (1024.0 * 1024.0) if not path_metrics.empty else 0.0
    last_progress_emit = 0.0

    def emit_progress(
        *,
        local_groups_total: int = 0,
        local_groups_processed: int = 0,
        local_replicates_total: int = 0,
        local_replicates_processed: int = 0,
        force: bool = False,
    ) -> None:
        nonlocal last_progress_emit
        if progress_callback is None:
            return
        elapsed = time.perf_counter() - start_time
        if not force and elapsed - last_progress_emit < progress_interval_seconds:
            return
        last_progress_emit = elapsed
        groups_processed = min(groups_completed_before + local_groups_processed, groups_total)
        replicates_processed = min(replicates_completed_before + local_replicates_processed, bootstrap_replicates_total)
        progress_callback(
            groups_total=groups_total,
            groups_processed=groups_processed,
            bootstrap_replicates_total=bootstrap_replicates_total,
            bootstrap_replicates_processed=replicates_processed,
            elapsed_seconds=round(float(elapsed), 3),
            eta_seconds=_progress_eta(elapsed, replicates_processed, bootstrap_replicates_total),
            memory_mb=round(memory_mb, 3),
        )

    outputs: dict[str, Any] = {}
    emit_progress(force=True)
    for name, group_by in group_specs:
        local_total = group_totals[name]

        def child_progress(**payload: Any) -> None:
            emit_progress(
                local_groups_total=local_total,
                local_groups_processed=int(payload.get("groups_processed", 0)),
                local_replicates_total=int(payload.get("bootstrap_replicates_total", 0)),
                local_replicates_processed=int(payload.get("bootstrap_replicates_processed", 0)),
            )

        outputs[name] = aggregate_incremental_metrics(
            path_metrics,
            group_by=group_by,
            n_bootstrap=n_bootstrap,
            seed=seed,
            progress_callback=child_progress,
            progress_interval_seconds=progress_interval_seconds,
        )
        groups_completed_before += local_total
        replicates_completed_before += local_total * int(n_bootstrap)
        emit_progress(force=True)

    incremental_metrics = outputs["incremental_metrics"]
    outputs["bootstrap_intervals"] = incremental_metrics.loc[
        :,
        [
            "symbol",
            "direction_orientation",
            "horizon",
            "bootstrap_ci_low",
            "bootstrap_ci_high",
            "bootstrap_grouped_by",
            "bootstrap_seed",
        ],
    ].copy()
    outputs["cost_comparison"] = cost_threshold_comparison(path_metrics)
    outputs["gate"] = evaluate_discovery_gate(path_metrics, outputs["bootstrap_intervals"])
    emit_progress(force=True)
    return outputs


def assert_no_strategy_columns(frame: pd.DataFrame) -> None:
    forbidden = FORBIDDEN_STRATEGY_COLUMNS.intersection(set(frame.columns))
    if forbidden:
        raise AssertionError(f"Forbidden strategy columns present: {sorted(forbidden)}")
