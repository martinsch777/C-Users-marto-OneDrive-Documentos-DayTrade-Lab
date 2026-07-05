from __future__ import annotations

import numpy as np
import pandas as pd


def generate_synthetic_intraday(
    *,
    start: str = "2024-01-02",
    sessions: int = 90,
    timeframe: str = "15min",
    seed: int = 7,
    initial_price: float = 100.0,
) -> pd.DataFrame:
    """Generate deterministic research fixtures, never market-like evidence."""
    if timeframe not in {"5min", "15min", "30min"}:
        raise ValueError("Synthetic generator supports 5min, 15min, and 30min")
    rng = np.random.default_rng(seed)
    frequency = pd.Timedelta(timeframe)
    bars_per_day = int(pd.Timedelta(hours=6, minutes=30) / frequency)
    days = pd.bdate_range(start=start, periods=sessions)
    records: list[dict] = []
    previous_close = initial_price
    for day_number, day in enumerate(days):
        local_open = pd.Timestamp(
            year=day.year,
            month=day.month,
            day=day.day,
            hour=9,
            minute=30,
            tz="America/New_York",
        )
        gap = rng.normal(0, 0.0025)
        price = previous_close * (1 + gap)
        regime = rng.choice(
            ["range", "trend_up", "trend_down", "momentum"],
            p=[0.50, 0.20, 0.20, 0.10],
        )
        daily_direction = 1 if regime in {"trend_up", "momentum"} else -1
        for bar in range(bars_per_day):
            timestamp = (local_open + bar * frequency).tz_convert("UTC")
            u_shape = 1.0 + 1.8 * abs(bar - (bars_per_day - 1) / 2) / bars_per_day
            drift = 0.0
            if regime == "trend_up":
                drift = 0.00045
            elif regime == "trend_down":
                drift = -0.00045
            elif regime == "momentum" and bar >= bars_per_day // 3:
                drift = 0.0010 * daily_direction
            shock = rng.normal(drift, 0.0018)
            if regime == "momentum" and bar == bars_per_day // 3:
                shock += 0.009 * daily_direction
            open_price = price
            close_price = max(1.0, open_price * (1 + shock))
            wick = abs(rng.normal(0.0010, 0.00045))
            high = max(open_price, close_price) * (1 + wick)
            low = min(open_price, close_price) * (1 - wick)
            volume_boost = 3.2 if regime == "momentum" and bar >= bars_per_day // 3 else 1.0
            volume = max(
                100.0,
                rng.lognormal(mean=11.2, sigma=0.35) * u_shape * volume_boost,
            )
            records.append(
                {
                    "timestamp": timestamp,
                    "open": open_price,
                    "high": high,
                    "low": low,
                    "close": close_price,
                    "volume": volume,
                }
            )
            price = close_price
        previous_close = price
    return pd.DataFrame(records)
