from __future__ import annotations

import pandas as pd


SUPPORTED_TIMEFRAME_DURATIONS: dict[str, pd.Timedelta] = {
    "1min": pd.Timedelta(minutes=1),
    "5min": pd.Timedelta(minutes=5),
    "15min": pd.Timedelta(minutes=15),
    "30min": pd.Timedelta(minutes=30),
    "1h": pd.Timedelta(hours=1),
}


def parse_timeframe_timedelta(timeframe: str) -> pd.Timedelta:
    try:
        return SUPPORTED_TIMEFRAME_DURATIONS[str(timeframe)]
    except KeyError as exc:
        supported = ", ".join(SUPPORTED_TIMEFRAME_DURATIONS)
        raise ValueError(
            f"Unsupported timeframe {timeframe!r}; supported values: {supported}"
        ) from exc
