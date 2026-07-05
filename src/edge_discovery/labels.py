from __future__ import annotations

import numpy as np
import pandas as pd

from src.indicators import atr


EVENT_LABELS = (
    "EXTREME_UP_MOVE",
    "EXTREME_DOWN_MOVE",
    "HIGH_RELATIVE_VOLUME",
    "LARGE_WICK_REVERSAL",
    "VOLATILITY_EXPANSION",
    "VOLATILITY_COMPRESSION",
    "FUNDING_EXTREME_POSITIVE",
    "FUNDING_EXTREME_NEGATIVE",
    "OPEN_INTEREST_SPIKE",
    "SPREAD_WIDENING",
    "LIQUIDATION_CASCADE",
)


def add_event_labels(frame: pd.DataFrame) -> pd.DataFrame:
    """Add fixed, causal event labels without future-confirmed pivots."""
    data = frame.copy()
    data["timestamp"] = pd.to_datetime(data["timestamp"], utc=True)
    local_atr = atr(data, 14)
    prior_atr = local_atr.shift(1).replace(0, np.nan)
    atr_baseline = prior_atr.rolling(288, min_periods=96).median()
    prior_volume = data["volume"].shift(1).rolling(96, min_periods=48).mean()
    relative_volume = data["volume"] / prior_volume.replace(0, np.nan)
    move = data["close"] - data["close"].shift(3)
    move_atr = move.abs() / prior_atr

    candle_range = (data["high"] - data["low"]).replace(0, np.nan)
    body = (data["close"] - data["open"]).abs()
    upper_wick = data["high"] - data[["open", "close"]].max(axis=1)
    lower_wick = data[["open", "close"]].min(axis=1) - data["low"]
    close_location = (data["close"] - data["low"]) / candle_range
    large_lower = (lower_wick >= 1.5 * body.clip(lower=1e-12)) & (
        close_location >= 0.60
    )
    large_upper = (upper_wick >= 1.5 * body.clip(lower=1e-12)) & (
        close_location <= 0.40
    )

    data["atr_event"] = local_atr
    data["relative_volume_event"] = relative_volume
    data["move_3bar_atr"] = move_atr
    data["close_location"] = close_location
    data["lower_wick_ratio"] = lower_wick / candle_range
    data["upper_wick_ratio"] = upper_wick / candle_range
    data["EXTREME_UP_MOVE"] = (move > 0) & (move_atr >= 2.0)
    data["EXTREME_DOWN_MOVE"] = (move < 0) & (move_atr >= 2.0)
    data["HIGH_RELATIVE_VOLUME"] = relative_volume >= 3.0
    data["LARGE_WICK_REVERSAL"] = large_lower | large_upper
    data["VOLATILITY_EXPANSION"] = local_atr / atr_baseline >= 1.5
    data["VOLATILITY_COMPRESSION"] = local_atr / atr_baseline <= 0.70

    funding = pd.to_numeric(
        data.get("funding_rate", pd.Series(np.nan, index=data.index)),
        errors="coerce",
    )
    data["FUNDING_EXTREME_POSITIVE"] = funding >= 0.0005
    data["FUNDING_EXTREME_NEGATIVE"] = funding <= -0.0005

    open_interest = pd.to_numeric(
        data.get("open_interest", pd.Series(np.nan, index=data.index)),
        errors="coerce",
    )
    data["open_interest_change"] = open_interest.pct_change(fill_method=None)
    data["OPEN_INTEREST_SPIKE"] = data["open_interest_change"].abs() >= 0.05

    spread = pd.to_numeric(
        data.get("spread_bps", pd.Series(np.nan, index=data.index)),
        errors="coerce",
    )
    spread_baseline = spread.shift(1).rolling(288, min_periods=96).median()
    data["SPREAD_WIDENING"] = spread >= 2 * spread_baseline

    liquidations = pd.to_numeric(
        data.get("liquidation_usd", pd.Series(np.nan, index=data.index)),
        errors="coerce",
    )
    liquidation_baseline = (
        liquidations.shift(1).rolling(288, min_periods=48).median()
    )
    data["LIQUIDATION_CASCADE"] = (
        (liquidations >= 5 * liquidation_baseline)
        & (liquidations >= 100_000)
    )

    for label in EVENT_LABELS:
        data[label] = data[label].fillna(False).astype(bool)
    return data
