from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Literal

import numpy as np
import pandas as pd

from src.data import DatasetManifest
from src.research.event_study import DEFAULT_EVENT_STUDY_HORIZONS
from src.research.hyp_first_candle import (
    FirstCandleConfig,
    _as_time,
    _clock,
    _local,
    add_session_columns,
    bearish_fvg,
    bullish_fvg,
    close_strictly_inside,
    compute_opening_ranges,
    load_symbol_curated_1min,
)
from src.research.qqq_s2_s5 import resample_rth_1min_to_5min


HYPOTHESIS_ID = "HYP-FCR-EVENT-01"
EVENT_TYPES = tuple(f"EVENT-{index:02d}" for index in range(1, 11))
LOW_SIDE_EVENTS = {"EVENT-01", "EVENT-02", "EVENT-05", "EVENT-07", "EVENT-09"}
HIGH_SIDE_EVENTS = {"EVENT-03", "EVENT-04", "EVENT-06", "EVENT-08", "EVENT-10"}
BLOCKED_PERIODS = {"validation_2025", "parity_debug_2026", "holdout_2026", "holdout"}
SAFETY_FLAGS = {
    "live_trading": False,
    "broker_connected": False,
    "orders_sent": False,
    "paper_broker_enabled": False,
}
STRATEGY_FIELD_NAMES = {
    "entry_price",
    "entry_time",
    "stop",
    "target",
    "quantity",
    "position_size",
    "pnl",
    "net_pnl",
}


@dataclass(frozen=True)
class FcrEventStudyConfig:
    hypothesis_id: str = HYPOTHESIS_ID
    timezone: str = "America/New_York"
    source_timeframe: str = "1min"
    research_timeframe: str = "5min"
    opening_start: str = "09:30"
    opening_end_exclusive: str = "10:00"
    observation_start: str = "10:00"
    observation_end_exclusive: str = "16:00"
    tick_size: float = 0.01
    minimum_fvg_ticks: int = 0
    fvg_confirmation_bars_after_sweep: int = 3
    horizons: tuple[str, ...] = DEFAULT_EVENT_STUDY_HORIZONS
    allowed_periods: tuple[str, ...] = ("discovery_2022_2024",)
    blocked_periods: tuple[str, ...] = tuple(sorted(BLOCKED_PERIODS))
    safety_flags: dict[str, bool] = field(default_factory=lambda: dict(SAFETY_FLAGS))

    def first_candle_config(self) -> FirstCandleConfig:
        return FirstCandleConfig(
            hypothesis_id=self.hypothesis_id,
            timezone=self.timezone,
            source_timeframe=self.source_timeframe,
            signal_timeframe=self.research_timeframe,
            opening_start=self.opening_start,
            opening_end_exclusive=self.opening_end_exclusive,
            entry_start=self.observation_start,
            entry_end_exclusive=self.observation_end_exclusive,
            minimum_fvg_ticks=self.minimum_fvg_ticks,
        )


def canonical_event_config_hash(config_path: str | Path) -> str:
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - project dependency
        raise RuntimeError("PyYAML is required to hash event config files.") from exc
    payload = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        payload.pop("canonical_payload_hash", None)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def prepare_five_minute_frame(minute_frame: pd.DataFrame) -> pd.DataFrame:
    return resample_rth_1min_to_5min(minute_frame)


def build_opening_range(
    five_minute: pd.DataFrame,
    config: FcrEventStudyConfig | None = None,
) -> pd.DataFrame:
    config = config or FcrEventStudyConfig()
    return compute_opening_ranges(five_minute, config.first_candle_config())


def load_approved_event_dataset(
    symbol: str,
    csv_path: str | Path,
    manifest_path: str | Path,
    *,
    allowed_purpose: str = "OR_FVG_BACKTEST_RESEARCH",
) -> tuple[pd.DataFrame, DatasetManifest]:
    return load_symbol_curated_1min(
        symbol,
        csv_path=Path(csv_path),
        manifest_path=Path(manifest_path),
        allowed_purpose=allowed_purpose,
    )


def _add_atr_14(data: pd.DataFrame) -> pd.DataFrame:
    enriched = data.copy()
    previous_close = enriched.groupby("session_date")["close"].shift(1).astype(float)
    high = enriched["high"].astype(float)
    low = enriched["low"].astype(float)
    true_range = pd.concat(
        [
            high - low,
            (high - previous_close).abs(),
            (low - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    enriched["atr_14"] = true_range.groupby(enriched["session_date"]).transform(
        lambda values: values.rolling(14, min_periods=1).mean()
    )
    return enriched


def _event_side(event_type: str) -> Literal["low", "high"]:
    if event_type in LOW_SIDE_EVENTS:
        return "low"
    if event_type in HIGH_SIDE_EVENTS:
        return "high"
    raise ValueError(f"Unsupported event_type: {event_type}")


def _base_event_record(
    *,
    symbol: str,
    session_date: str,
    row: pd.Series,
    event_type: str,
    opening_low: float,
    opening_high: float,
    prior_close: float | None,
    event_index: int,
    sweep_row: pd.Series | None = None,
    sweep_index: int | None = None,
    fvg_size: float = 0.0,
) -> dict[str, Any]:
    side = _event_side(event_type)
    timestamp = pd.Timestamp(row["timestamp"])
    atr = float(row.get("atr_14", np.nan))
    opening_width = float(opening_high - opening_low)
    if side == "low":
        sweep_depth = max(0.0, (opening_low - float(row["low"])) / 0.01)
        same_extreme = opening_low
        reversal_direction = "long"
        continuation_direction = "short"
    else:
        sweep_depth = max(0.0, (float(row["high"]) - opening_high) / 0.01)
        same_extreme = opening_high
        reversal_direction = "short"
        continuation_direction = "long"
    if sweep_row is not None:
        if side == "low":
            sweep_depth = max(0.0, (opening_low - float(sweep_row["low"])) / 0.01)
            same_extreme = min(opening_low, float(sweep_row["low"]))
        else:
            sweep_depth = max(0.0, (float(sweep_row["high"]) - opening_high) / 0.01)
            same_extreme = max(opening_high, float(sweep_row["high"]))
    prior_open = float(row["open"])
    gap_direction = "unknown"
    if prior_close is not None and np.isfinite(prior_close):
        if prior_open > prior_close:
            gap_direction = "gap_up"
        elif prior_open < prior_close:
            gap_direction = "gap_down"
        else:
            gap_direction = "flat"
    return {
        "hypothesis_id": HYPOTHESIS_ID,
        "symbol": symbol.upper(),
        "session_date": session_date,
        "event_type": event_type,
        "event_side": side,
        "event_time": timestamp,
        "event_bar_index": int(event_index),
        "event_price": float(row["close"]),
        "opening_high": float(opening_high),
        "opening_low": float(opening_low),
        "opening_midpoint": float((opening_high + opening_low) / 2.0),
        "opening_range_width": opening_width,
        "atr_14": atr,
        "opening_range_width_over_atr": opening_width / atr if atr > 0 else np.nan,
        "same_side_extreme": float(same_extreme),
        "last_sweep_time": pd.Timestamp(sweep_row["timestamp"]) if sweep_row is not None else pd.NaT,
        "bars_since_sweep": int(event_index - int(sweep_index)) if sweep_index is not None else np.nan,
        "sweep_depth_ticks": float(sweep_depth),
        "sweep_depth_over_atr": (sweep_depth * 0.01 / atr) if atr > 0 else np.nan,
        "fvg_size": float(fvg_size),
        "fvg_size_ticks": float(fvg_size / 0.01),
        "fvg_size_over_atr": (float(fvg_size) / atr) if atr > 0 else np.nan,
        "gap_direction": gap_direction,
        "event_hour": _local(timestamp, FirstCandleConfig()).strftime("%H:00"),
        "year": int(_local(timestamp, FirstCandleConfig()).year),
        "day_of_week": _local(timestamp, FirstCandleConfig()).day_name(),
        "reversal_direction": reversal_direction,
        "continuation_direction": continuation_direction,
    }


def _qualifies_bullish_fvg(
    session: pd.DataFrame,
    position: int,
    opening_low: float,
    opening_high: float,
    config: FcrEventStudyConfig,
) -> tuple[bool, float]:
    if position < 2:
        return False, 0.0
    bull, gap = bullish_fvg(
        session.iloc[position],
        session.iloc[position - 2],
        config.tick_size,
        config.minimum_fvg_ticks,
    )
    inside = close_strictly_inside(float(session.iloc[position]["close"]), opening_low, opening_high)
    return bool(bull and inside), float(gap if bull else 0.0)


def _qualifies_bearish_fvg(
    session: pd.DataFrame,
    position: int,
    opening_low: float,
    opening_high: float,
    config: FcrEventStudyConfig,
) -> tuple[bool, float]:
    if position < 2:
        return False, 0.0
    bear, gap = bearish_fvg(
        session.iloc[position],
        session.iloc[position - 2],
        config.tick_size,
        config.minimum_fvg_ticks,
    )
    inside = close_strictly_inside(float(session.iloc[position]["close"]), opening_low, opening_high)
    return bool(bear and inside), float(gap if bear else 0.0)


def detect_fcr_event_study_events(
    five_minute: pd.DataFrame,
    symbol: str,
    config: FcrEventStudyConfig | None = None,
) -> pd.DataFrame:
    config = config or FcrEventStudyConfig()
    fcr_config = config.first_candle_config()
    data = add_session_columns(five_minute, fcr_config)
    ranges = compute_opening_ranges(data, fcr_config)
    if ranges.empty:
        return pd.DataFrame()
    enriched = _add_atr_14(data.merge(ranges, on="session_date", how="left"))
    observation_start = _as_time(config.observation_start)
    observation_end = _as_time(config.observation_end_exclusive)
    rows: list[dict[str, Any]] = []
    previous_session_close: float | None = None

    for session_date, session in enriched.groupby("session_date", sort=True):
        session = session.reset_index(drop=True)
        if session["opening_high"].isna().all():
            previous_session_close = float(session["close"].iloc[-1]) if not session.empty else previous_session_close
            continue
        opening_high = float(session["opening_high"].iloc[0])
        opening_low = float(session["opening_low"].iloc[0])
        seen: set[str] = set()
        low_sweep_position: int | None = None
        high_sweep_position: int | None = None
        low_sweep_row: pd.Series | None = None
        high_sweep_row: pd.Series | None = None

        for position, row in session.iterrows():
            clock = _clock(row["timestamp"], fcr_config)
            if not (observation_start <= clock < observation_end):
                continue
            low_touch = float(row["low"]) <= opening_low
            high_touch = float(row["high"]) >= opening_high
            low_strict = float(row["low"]) <= opening_low - config.tick_size
            high_strict = float(row["high"]) >= opening_high + config.tick_size

            if low_touch and "EVENT-01" not in seen:
                rows.append(
                    _base_event_record(
                        symbol=symbol,
                        session_date=session_date,
                        row=row,
                        event_type="EVENT-01",
                        opening_low=opening_low,
                        opening_high=opening_high,
                        prior_close=previous_session_close,
                        event_index=int(position),
                    )
                )
                seen.add("EVENT-01")
            if low_strict and "EVENT-02" not in seen:
                rows.append(
                    _base_event_record(
                        symbol=symbol,
                        session_date=session_date,
                        row=row,
                        event_type="EVENT-02",
                        opening_low=opening_low,
                        opening_high=opening_high,
                        prior_close=previous_session_close,
                        event_index=int(position),
                    )
                )
                seen.add("EVENT-02")
            if high_touch and "EVENT-03" not in seen:
                rows.append(
                    _base_event_record(
                        symbol=symbol,
                        session_date=session_date,
                        row=row,
                        event_type="EVENT-03",
                        opening_low=opening_low,
                        opening_high=opening_high,
                        prior_close=previous_session_close,
                        event_index=int(position),
                    )
                )
                seen.add("EVENT-03")
            if high_strict and "EVENT-04" not in seen:
                rows.append(
                    _base_event_record(
                        symbol=symbol,
                        session_date=session_date,
                        row=row,
                        event_type="EVENT-04",
                        opening_low=opening_low,
                        opening_high=opening_high,
                        prior_close=previous_session_close,
                        event_index=int(position),
                    )
                )
                seen.add("EVENT-04")

            if low_touch:
                low_sweep_position = int(position)
                low_sweep_row = row
            if high_touch:
                high_sweep_position = int(position)
                high_sweep_row = row

            bull, bull_gap = _qualifies_bullish_fvg(session, int(position), opening_low, opening_high, config)
            bear, bear_gap = _qualifies_bearish_fvg(session, int(position), opening_low, opening_high, config)
            if (
                bull
                and low_sweep_position is not None
                and int(position) > low_sweep_position
                and int(position) - low_sweep_position <= config.fvg_confirmation_bars_after_sweep
                and "EVENT-05" not in seen
            ):
                rows.append(
                    _base_event_record(
                        symbol=symbol,
                        session_date=session_date,
                        row=row,
                        event_type="EVENT-05",
                        opening_low=opening_low,
                        opening_high=opening_high,
                        prior_close=previous_session_close,
                        event_index=int(position),
                        sweep_row=low_sweep_row,
                        sweep_index=low_sweep_position,
                        fvg_size=bull_gap,
                    )
                )
                seen.add("EVENT-05")
            if (
                bear
                and high_sweep_position is not None
                and int(position) > high_sweep_position
                and int(position) - high_sweep_position <= config.fvg_confirmation_bars_after_sweep
                and "EVENT-06" not in seen
            ):
                rows.append(
                    _base_event_record(
                        symbol=symbol,
                        session_date=session_date,
                        row=row,
                        event_type="EVENT-06",
                        opening_low=opening_low,
                        opening_high=opening_high,
                        prior_close=previous_session_close,
                        event_index=int(position),
                        sweep_row=high_sweep_row,
                        sweep_index=high_sweep_position,
                        fvg_size=bear_gap,
                    )
                )
                seen.add("EVENT-06")
            if bull and low_sweep_position is None and "EVENT-09" not in seen:
                rows.append(
                    _base_event_record(
                        symbol=symbol,
                        session_date=session_date,
                        row=row,
                        event_type="EVENT-09",
                        opening_low=opening_low,
                        opening_high=opening_high,
                        prior_close=previous_session_close,
                        event_index=int(position),
                        fvg_size=bull_gap,
                    )
                )
                seen.add("EVENT-09")
            if bear and high_sweep_position is None and "EVENT-10" not in seen:
                rows.append(
                    _base_event_record(
                        symbol=symbol,
                        session_date=session_date,
                        row=row,
                        event_type="EVENT-10",
                        opening_low=opening_low,
                        opening_high=opening_high,
                        prior_close=previous_session_close,
                        event_index=int(position),
                        fvg_size=bear_gap,
                    )
                )
                seen.add("EVENT-10")

            if low_touch and "EVENT-07" not in seen:
                next_positions = range(int(position) + 1, min(len(session), int(position) + 4))
                future_bull = any(
                    _qualifies_bullish_fvg(session, candidate, opening_low, opening_high, config)[0]
                    for candidate in next_positions
                )
                if not future_bull:
                    rows.append(
                        _base_event_record(
                            symbol=symbol,
                            session_date=session_date,
                            row=row,
                            event_type="EVENT-07",
                            opening_low=opening_low,
                            opening_high=opening_high,
                            prior_close=previous_session_close,
                            event_index=int(position),
                            sweep_row=row,
                            sweep_index=int(position),
                        )
                    )
                    seen.add("EVENT-07")
            if high_touch and "EVENT-08" not in seen:
                next_positions = range(int(position) + 1, min(len(session), int(position) + 4))
                future_bear = any(
                    _qualifies_bearish_fvg(session, candidate, opening_low, opening_high, config)[0]
                    for candidate in next_positions
                )
                if not future_bear:
                    rows.append(
                        _base_event_record(
                            symbol=symbol,
                            session_date=session_date,
                            row=row,
                            event_type="EVENT-08",
                            opening_low=opening_low,
                            opening_high=opening_high,
                            prior_close=previous_session_close,
                            event_index=int(position),
                            sweep_row=row,
                            sweep_index=int(position),
                        )
                    )
                    seen.add("EVENT-08")
        previous_session_close = float(session["close"].iloc[-1]) if not session.empty else previous_session_close

    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values(["event_time", "event_type"]).reset_index(drop=True)


def _horizon_delta(horizon: str) -> pd.Timedelta | None:
    if horizon == "session_close":
        return None
    if not horizon.endswith("min"):
        raise ValueError(f"Unsupported event horizon: {horizon}")
    return pd.Timedelta(value=int(horizon[:-3]), unit="min")


def compute_fcr_event_paths(
    five_minute: pd.DataFrame,
    events: pd.DataFrame,
    config: FcrEventStudyConfig | None = None,
    *,
    horizons: tuple[str, ...] | None = None,
) -> pd.DataFrame:
    config = config or FcrEventStudyConfig()
    horizons = horizons or config.horizons
    if events.empty:
        return pd.DataFrame()
    data = add_session_columns(five_minute, config.first_candle_config()).sort_values("timestamp").reset_index(drop=True)
    event_data = events.copy()
    rows: list[dict[str, Any]] = []

    for _, event in event_data.iterrows():
        session = data.loc[data["session_date"] == str(event["session_date"])].reset_index(drop=True)
        event_time = pd.Timestamp(event["event_time"])
        event_positions = session.index[session["timestamp"] == event_time].tolist()
        if not event_positions:
            continue
        event_position = int(event_positions[0])
        event_close = float(session.loc[event_position, "close"])
        for horizon in horizons:
            delta = _horizon_delta(horizon)
            if delta is None:
                horizon_position = len(session) - 1
            else:
                target = event_time + delta
                candidates = session.index[session["timestamp"] == target].tolist()
                if not candidates:
                    continue
                horizon_position = int(candidates[0])
            if horizon_position <= event_position:
                continue
            path = session.iloc[event_position + 1 : horizon_position + 1]
            future_close = float(session.loc[horizon_position, "close"])
            raw_return = future_close / event_close - 1.0
            side = str(event["event_side"])
            high_path = path["high"].astype(float)
            low_path = path["low"].astype(float)
            if side == "low":
                reversal_return = raw_return
                continuation_return = -raw_return
                mfe = high_path.max() / event_close - 1.0
                mae = low_path.min() / event_close - 1.0
                time_to_mfe = pd.Timestamp(path.loc[high_path.idxmax(), "timestamp"])
                time_to_mae = pd.Timestamp(path.loc[low_path.idxmin(), "timestamp"])
                returned_center = bool(high_path.max() >= float(event["opening_midpoint"]))
                reached_opposite = bool(high_path.max() >= float(event["opening_high"]))
                broke_same = bool(low_path.min() < float(event["opening_low"]))
            else:
                reversal_return = -raw_return
                continuation_return = raw_return
                mfe = event_close / low_path.min() - 1.0
                mae = 1.0 - event_close / high_path.max()
                time_to_mfe = pd.Timestamp(path.loc[low_path.idxmin(), "timestamp"])
                time_to_mae = pd.Timestamp(path.loc[high_path.idxmax(), "timestamp"])
                returned_center = bool(low_path.min() <= float(event["opening_midpoint"]))
                reached_opposite = bool(low_path.min() <= float(event["opening_low"]))
                broke_same = bool(high_path.max() > float(event["opening_high"]))
            rows.append(
                {
                    "hypothesis_id": str(event.get("hypothesis_id", HYPOTHESIS_ID)),
                    "symbol": str(event["symbol"]),
                    "session_date": str(event["session_date"]),
                    "event_type": str(event["event_type"]),
                    "event_side": side,
                    "event_time": event_time,
                    "horizon": horizon,
                    "event_price": event_close,
                    "future_close": future_close,
                    "raw_return": float(raw_return),
                    "reversal_return": float(reversal_return),
                    "continuation_return": float(continuation_return),
                    "maximum_favorable_excursion": float(mfe),
                    "maximum_adverse_excursion": float(mae),
                    "time_to_mfe": time_to_mfe,
                    "time_to_mae": time_to_mae,
                    "returned_to_or_center": returned_center,
                    "reached_opposite_or_extreme": reached_opposite,
                    "broke_same_or_extreme": broke_same,
                    "bars_in_path": int(len(path)),
                }
            )
    return pd.DataFrame(rows).sort_values(["event_time", "event_type", "horizon"]).reset_index(drop=True)


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
    rng = np.random.default_rng(seed)
    sampled_means: list[float] = []
    for _ in range(n_bootstrap):
        sampled_sessions = rng.choice(sessions, size=len(sessions), replace=True)
        sample = pd.concat([frame.loc[frame["session_date"].astype(str) == item] for item in sampled_sessions])
        sampled_means.append(float(sample[value_column].mean()))
    return float(np.percentile(sampled_means, 2.5)), float(np.percentile(sampled_means, 97.5))


def aggregate_fcr_event_paths(
    paths: pd.DataFrame,
    *,
    group_by: tuple[str, ...] = ("event_type", "horizon"),
    n_bootstrap: int = 500,
    seed: int = 17,
) -> pd.DataFrame:
    if paths.empty:
        return pd.DataFrame()
    rows: list[dict[str, Any]] = []
    for key, group in paths.groupby(list(group_by), sort=True):
        if not isinstance(key, tuple):
            key = (key,)
        ci_low, ci_high = bootstrap_mean_by_session(
            group,
            value_column="reversal_return",
            n_bootstrap=n_bootstrap,
            seed=seed,
        )
        record = {column: value for column, value in zip(group_by, key)}
        record.update(
            {
                "event_count": int(len(group)),
                "session_count": int(group["session_date"].nunique()),
                "mean_reversal_return": float(group["reversal_return"].mean()),
                "median_reversal_return": float(group["reversal_return"].median()),
                "mean_continuation_return": float(group["continuation_return"].mean()),
                "median_continuation_return": float(group["continuation_return"].median()),
                "mean_mfe": float(group["maximum_favorable_excursion"].mean()),
                "mean_mae": float(group["maximum_adverse_excursion"].mean()),
                "bootstrap_reversal_mean_ci_low": ci_low,
                "bootstrap_reversal_mean_ci_high": ci_high,
            }
        )
        rows.append(record)
    return pd.DataFrame(rows)


def validate_event_study_period(period: str) -> None:
    if period in BLOCKED_PERIODS or "2025" in period or "2026" in period:
        raise PermissionError(f"{HYPOTHESIS_ID} is prepare-only; period is blocked: {period}")
    if period != "discovery_2022_2024":
        raise PermissionError(f"{HYPOTHESIS_ID} only allows preregistered discovery preparation.")


def assert_no_strategy_columns(frame: pd.DataFrame) -> None:
    forbidden = STRATEGY_FIELD_NAMES.intersection(set(frame.columns))
    if forbidden:
        raise AssertionError(f"Event study output contains strategy fields: {sorted(forbidden)}")
