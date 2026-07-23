from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import pandas as pd

from src.research.hyp_first_candle import (
    FirstCandleConfig,
    _as_time,
    _bar_close,
    _clock,
    _local,
    bearish_fvg,
    bullish_fvg,
    calculate_position_size,
    close_strictly_inside,
    compute_opening_ranges,
    target_from_signal_close,
)


VariantId = Literal["HYP-FCR-02", "HYP-FCR-03", "HYP-FCR-04"]
StopPolicy = Literal["body_3bar", "structural_from_sweep"]


@dataclass(frozen=True)
class FirstCandleVariantSpec:
    hypothesis_id: VariantId
    maximum_confirmation_bars_after_sweep: int | None = None
    strict_sweep_minimum_ticks: int = 0
    stop_policy: StopPolicy = "body_3bar"

    @property
    def uses_near_sweep_window(self) -> bool:
        return self.maximum_confirmation_bars_after_sweep is not None


FCR_02 = FirstCandleVariantSpec(
    hypothesis_id="HYP-FCR-02",
    maximum_confirmation_bars_after_sweep=3,
)
FCR_03 = FirstCandleVariantSpec(
    hypothesis_id="HYP-FCR-03",
    strict_sweep_minimum_ticks=1,
)
FCR_04 = FirstCandleVariantSpec(
    hypothesis_id="HYP-FCR-04",
    stop_policy="structural_from_sweep",
)
VARIANT_SPECS: dict[str, FirstCandleVariantSpec] = {
    item.hypothesis_id: item for item in (FCR_02, FCR_03, FCR_04)
}


def config_for_variant(spec: FirstCandleVariantSpec) -> FirstCandleConfig:
    return FirstCandleConfig(hypothesis_id=spec.hypothesis_id)


def _body_stop(
    session: pd.DataFrame,
    position: int,
    direction: Literal["long", "short"],
    *,
    tick_size: float,
    buffer_ticks: int,
) -> float:
    if position < 2:
        raise ValueError("FCR stop requires signal bar and two previous bars")
    window = session.iloc[position - 2 : position + 1]
    if direction == "long":
        body_extreme = window[["open", "close"]].astype(float).min(axis=1).min()
        return float(body_extreme - buffer_ticks * tick_size)
    body_extreme = window[["open", "close"]].astype(float).max(axis=1).max()
    return float(body_extreme + buffer_ticks * tick_size)


def structural_stop_from_sweep(
    session: pd.DataFrame,
    sweep_position: int,
    signal_position: int,
    direction: Literal["long", "short"],
    *,
    tick_size: float = 0.01,
    buffer_ticks: int = 1,
) -> float:
    if sweep_position > signal_position:
        raise ValueError("sweep_position must be on or before signal_position")
    window = session.iloc[sweep_position : signal_position + 1]
    if window.empty:
        raise ValueError("structural stop window is empty")
    if direction == "long":
        return float(window["low"].astype(float).min() - buffer_ticks * tick_size)
    return float(window["high"].astype(float).max() + buffer_ticks * tick_size)


def _stop_for_variant(
    session: pd.DataFrame,
    sweep_position: int,
    signal_position: int,
    direction: Literal["long", "short"],
    spec: FirstCandleVariantSpec,
    config: FirstCandleConfig,
) -> tuple[float, dict[str, Any]]:
    tick_size = config.cost("baseline").tick_size
    if spec.stop_policy == "structural_from_sweep":
        structural = structural_stop_from_sweep(
            session,
            sweep_position,
            signal_position,
            direction,
            tick_size=tick_size,
            buffer_ticks=config.stop_buffer_ticks,
        )
        body = _body_stop(
            session,
            signal_position,
            direction,
            tick_size=tick_size,
            buffer_ticks=config.stop_buffer_ticks,
        )
        return structural, {
            "original_body_stop": float(body),
            "structural_stop_distance_from_original": float(abs(structural - body)),
            "structural_segment_bars": int(signal_position - sweep_position + 1),
        }
    return (
        _body_stop(
            session,
            signal_position,
            direction,
            tick_size=tick_size,
            buffer_ticks=config.stop_buffer_ticks,
        ),
        {},
    )


def _sweep_depth_ticks(row: pd.Series, opening_extreme: float, direction: Literal["long", "short"], tick_size: float) -> float:
    if direction == "long":
        return float((opening_extreme - float(row["low"])) / tick_size)
    return float((float(row["high"]) - opening_extreme) / tick_size)


def _touches_sweep(
    row: pd.Series,
    *,
    opening_low: float,
    opening_high: float,
    spec: FirstCandleVariantSpec,
    tick_size: float,
) -> tuple[bool, bool, dict[str, float]]:
    strict = spec.strict_sweep_minimum_ticks * tick_size
    low_depth = _sweep_depth_ticks(row, opening_low, "long", tick_size)
    high_depth = _sweep_depth_ticks(row, opening_high, "short", tick_size)
    low_touch = float(row["low"]) <= opening_low - strict
    high_touch = float(row["high"]) >= opening_high + strict
    return low_touch, high_touch, {"low_sweep_depth_ticks": low_depth, "high_sweep_depth_ticks": high_depth}


def _eligible_after_sweep(
    *,
    position: int,
    sweep_position: int | None,
    spec: FirstCandleVariantSpec,
) -> bool:
    if sweep_position is None or position <= sweep_position:
        return False
    if spec.maximum_confirmation_bars_after_sweep is None:
        return True
    return position - sweep_position <= spec.maximum_confirmation_bars_after_sweep


def detect_first_candle_variant_signals(
    five_minute: pd.DataFrame,
    symbol: str,
    spec: FirstCandleVariantSpec,
    config: FirstCandleConfig | None = None,
    *,
    equity: float | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    config = config or config_for_variant(spec)
    sizing_equity = config.initial_equity if equity is None else float(equity)
    if config.confirmation_mode != "Solo FVG":
        raise ValueError("FCR variants inherit confirmation_mode='Solo FVG'")
    data = five_minute.copy()
    ranges = compute_opening_ranges(data, config)
    if ranges.empty:
        return pd.DataFrame(), pd.DataFrame(
            [{"symbol": symbol.upper(), "hypothesis_id": spec.hypothesis_id, "diagnostic": "no_complete_opening_ranges"}]
        )
    enriched = data.merge(ranges, on="session_date", how="left") if "session_date" in data.columns else data
    if "session_date" not in enriched.columns:
        from src.research.hyp_first_candle import add_session_columns

        enriched = add_session_columns(five_minute, config).merge(ranges, on="session_date", how="left")
    entry_start = _as_time(config.entry_start)
    entry_end = _as_time(config.entry_end_exclusive)
    tick_size = config.cost("baseline").tick_size
    diagnostics: list[dict[str, Any]] = []
    signals: list[dict[str, Any]] = []

    for session_date, session in enriched.groupby("session_date", sort=True):
        if session["opening_high"].isna().all():
            diagnostics.append(
                {
                    "symbol": symbol.upper(),
                    "hypothesis_id": spec.hypothesis_id,
                    "session_date": session_date,
                    "diagnostic": "missing_six_bar_opening_range",
                }
            )
            continue
        opening_high = float(session["opening_high"].iloc[0])
        opening_low = float(session["opening_low"].iloc[0])
        low_sweep_position: int | None = None
        high_sweep_position: int | None = None
        low_sweep_time: pd.Timestamp | None = None
        high_sweep_time: pd.Timestamp | None = None
        low_expired_position: int | None = None
        high_expired_position: int | None = None
        low_depth_at_sweep = 0.0
        high_depth_at_sweep = 0.0
        traded = False
        session = session.reset_index(drop=True)
        for position, row in session.iterrows():
            ts = pd.Timestamp(row["timestamp"])
            clock = _clock(ts, config)
            if not (entry_start <= clock < entry_end):
                continue
            if traded and config.one_trade_per_symbol_session:
                continue
            low_touch, high_touch, depths = _touches_sweep(
                row,
                opening_low=opening_low,
                opening_high=opening_high,
                spec=spec,
                tick_size=tick_size,
            )
            exact_low_rejected = (
                spec.strict_sweep_minimum_ticks > 0
                and float(row["low"]) <= opening_low
                and not low_touch
            )
            exact_high_rejected = (
                spec.strict_sweep_minimum_ticks > 0
                and float(row["high"]) >= opening_high
                and not high_touch
            )
            if exact_low_rejected:
                diagnostics.append(
                    {
                        "symbol": symbol.upper(),
                        "hypothesis_id": spec.hypothesis_id,
                        "session_date": session_date,
                        "timestamp": ts.isoformat(),
                        "diagnostic": "low_exact_or_subtick_touch_rejected_by_strict_sweep",
                        "sweep_depth_ticks": depths["low_sweep_depth_ticks"],
                    }
                )
            if exact_high_rejected:
                diagnostics.append(
                    {
                        "symbol": symbol.upper(),
                        "hypothesis_id": spec.hypothesis_id,
                        "session_date": session_date,
                        "timestamp": ts.isoformat(),
                        "diagnostic": "high_exact_or_subtick_touch_rejected_by_strict_sweep",
                        "sweep_depth_ticks": depths["high_sweep_depth_ticks"],
                    }
                )
            if low_touch:
                low_sweep_position = int(position)
                low_sweep_time = ts
                low_expired_position = None
                low_depth_at_sweep = depths["low_sweep_depth_ticks"]
            if high_touch:
                high_sweep_position = int(position)
                high_sweep_time = ts
                high_expired_position = None
                high_depth_at_sweep = depths["high_sweep_depth_ticks"]
            if spec.maximum_confirmation_bars_after_sweep is not None:
                if (
                    low_sweep_position is not None
                    and position - low_sweep_position > spec.maximum_confirmation_bars_after_sweep
                    and low_expired_position != low_sweep_position
                ):
                    diagnostics.append(
                        {
                            "symbol": symbol.upper(),
                            "hypothesis_id": spec.hypothesis_id,
                            "session_date": session_date,
                            "timestamp": ts.isoformat(),
                            "diagnostic": "low_sweep_window_expired",
                            "expired_sweep_time": low_sweep_time.isoformat() if low_sweep_time is not None else "",
                        }
                    )
                    low_expired_position = low_sweep_position
                if (
                    high_sweep_position is not None
                    and position - high_sweep_position > spec.maximum_confirmation_bars_after_sweep
                    and high_expired_position != high_sweep_position
                ):
                    diagnostics.append(
                        {
                            "symbol": symbol.upper(),
                            "hypothesis_id": spec.hypothesis_id,
                            "session_date": session_date,
                            "timestamp": ts.isoformat(),
                            "diagnostic": "high_sweep_window_expired",
                            "expired_sweep_time": high_sweep_time.isoformat() if high_sweep_time is not None else "",
                        }
                    )
                    high_expired_position = high_sweep_position
            if position < 2:
                continue
            two_back = session.iloc[position - 2]
            bull, bull_gap = bullish_fvg(row, two_back, tick_size, config.minimum_fvg_ticks)
            bear, bear_gap = bearish_fvg(row, two_back, tick_size, config.minimum_fvg_ticks)
            inside = close_strictly_inside(float(row["close"]), opening_low, opening_high)
            long_signal = bool(
                _eligible_after_sweep(position=int(position), sweep_position=low_sweep_position, spec=spec)
                and bull
                and inside
            )
            short_signal = bool(
                _eligible_after_sweep(position=int(position), sweep_position=high_sweep_position, spec=spec)
                and bear
                and inside
            )
            if long_signal and short_signal:
                diagnostics.append(
                    {
                        "symbol": symbol.upper(),
                        "hypothesis_id": spec.hypothesis_id,
                        "session_date": session_date,
                        "timestamp": ts.isoformat(),
                        "diagnostic": "simultaneous_long_short_signal_no_trade",
                    }
                )
                continue
            if not (long_signal or short_signal):
                continue
            direction: Literal["long", "short"] = "long" if long_signal else "short"
            sweep_position = low_sweep_position if direction == "long" else high_sweep_position
            if sweep_position is None:
                continue
            stop, stop_fields = _stop_for_variant(session, sweep_position, int(position), direction, spec, config)
            signal_close = float(row["close"])
            target = target_from_signal_close(signal_close, stop, direction, config.reward_risk)
            risk_per_unit = signal_close - stop if direction == "long" else stop - signal_close
            if risk_per_unit <= 0:
                diagnostics.append(
                    {
                        "symbol": symbol.upper(),
                        "hypothesis_id": spec.hypothesis_id,
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
                        "hypothesis_id": spec.hypothesis_id,
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
            sweep_depth = low_depth_at_sweep if direction == "long" else high_depth_at_sweep
            bars_since = int(position - int(last_sweep_position))
            signals.append(
                {
                    "hypothesis_id": spec.hypothesis_id,
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
                    "fvg_size_ticks": float(fvg_size / tick_size),
                    "stop": float(stop),
                    "target": float(target),
                    "risk_per_unit": float(risk_per_unit),
                    "bars_since_last_sweep": bars_since,
                    "confirmation_offset_bars": bars_since,
                    "sweep_depth_ticks": float(sweep_depth),
                    "entry_hour": _local(ts, config).strftime("%H:00"),
                    **stop_fields,
                }
            )
            traded = True
            if config.one_trade_per_symbol_session:
                break
    return pd.DataFrame(signals), pd.DataFrame(diagnostics)
