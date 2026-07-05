from __future__ import annotations

from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd


def ema(values: pd.Series, period: int) -> pd.Series:
    return values.ewm(span=period, adjust=False, min_periods=period).mean()


def atr(frame: pd.DataFrame, period: int = 14) -> pd.Series:
    previous_close = frame["close"].shift(1)
    true_range = pd.concat(
        [
            frame["high"] - frame["low"],
            (frame["high"] - previous_close).abs(),
            (frame["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return true_range.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def rsi(values: pd.Series, period: int = 14) -> pd.Series:
    delta = values.diff()
    gains = delta.clip(lower=0)
    losses = -delta.clip(upper=0)
    average_gain = gains.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    average_loss = losses.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    relative_strength = average_gain / average_loss.replace(0, np.nan)
    result = 100 - (100 / (1 + relative_strength))
    return result.fillna(50.0)


def session_vwap(
    frame: pd.DataFrame,
    timezone: str = "America/New_York",
) -> pd.Series:
    timestamps = pd.to_datetime(frame["timestamp"], utc=True)
    session = timestamps.dt.tz_convert(ZoneInfo(timezone)).dt.date
    typical_price = (frame["high"] + frame["low"] + frame["close"]) / 3
    cumulative_value = (typical_price * frame["volume"]).groupby(session).cumsum()
    cumulative_volume = frame["volume"].groupby(session).cumsum().replace(0, np.nan)
    return (cumulative_value / cumulative_volume).ffill()


def relative_volume(volume: pd.Series, lookback: int = 20) -> pd.Series:
    baseline = volume.shift(1).rolling(lookback, min_periods=max(3, lookback // 4)).mean()
    return (volume / baseline.replace(0, np.nan)).fillna(0.0)


def add_indicators(
    frame: pd.DataFrame,
    *,
    timezone: str = "America/New_York",
) -> pd.DataFrame:
    enriched = frame.copy()
    enriched["atr"] = atr(enriched)
    enriched["rsi"] = rsi(enriched["close"])
    enriched["ema_9"] = ema(enriched["close"], 9)
    enriched["ema_20"] = ema(enriched["close"], 20)
    enriched["vwap"] = session_vwap(enriched, timezone)
    enriched["relative_volume"] = relative_volume(enriched["volume"])
    enriched["bar_return"] = enriched["close"].pct_change()
    return enriched
