from __future__ import annotations

from dataclasses import dataclass, field
from datetime import time
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from .sessions import EquitySessionCalendar


CANONICAL_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]
TIMESTAMP_ALIASES = ("timestamp", "datetime", "date", "time", "open_time")


@dataclass
class DataQualityReport:
    rows: int
    duplicate_timestamps: int = 0
    invalid_ohlc_rows: int = 0
    nonpositive_price_rows: int = 0
    negative_volume_rows: int = 0
    missing_bars: list[pd.Timestamp] = field(default_factory=list)
    outside_session_rows: int = 0
    incomplete_candle_dropped: bool = False

    @property
    def is_valid(self) -> bool:
        return (
            self.rows > 0
            and self.duplicate_timestamps == 0
            and self.invalid_ohlc_rows == 0
            and self.nonpositive_price_rows == 0
            and self.negative_volume_rows == 0
            and not self.missing_bars
        )


def _rename_columns(frame: pd.DataFrame) -> pd.DataFrame:
    lowered = {str(column).strip().lower(): column for column in frame.columns}
    timestamp_name = next((name for name in TIMESTAMP_ALIASES if name in lowered), None)
    if timestamp_name is None:
        raise ValueError(f"Missing timestamp column; accepted: {TIMESTAMP_ALIASES}")
    mapping = {lowered[timestamp_name]: "timestamp"}
    for name in ("open", "high", "low", "close", "volume"):
        if name not in lowered:
            raise ValueError(f"Missing required OHLCV column: {name}")
        mapping[lowered[name]] = name
    return frame.rename(columns=mapping)


def normalize_ohlcv(
    frame: pd.DataFrame,
    timeframe: str = "15min",
    *,
    drop_incomplete: bool = True,
    reference_time: pd.Timestamp | None = None,
    source_timezone: str | None = None,
) -> tuple[pd.DataFrame, bool]:
    """Return sorted, UTC, numeric OHLCV data without duplicate timestamps."""
    normalized = _rename_columns(frame).loc[:, CANONICAL_COLUMNS].copy()
    parsed_timestamps: list[pd.Timestamp] = []
    for value in normalized["timestamp"]:
        try:
            timestamp = pd.Timestamp(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Timestamp could not be parsed: {value!r}") from exc
        if pd.isna(timestamp):
            raise ValueError("One or more timestamps could not be parsed")
        if timestamp.tzinfo is None:
            if source_timezone is None:
                raise ValueError(
                    "Naive timestamps are ambiguous; provide source_timezone "
                    "explicitly or use timezone-aware timestamps"
                )
            try:
                timestamp = timestamp.tz_localize(
                    source_timezone,
                    ambiguous="raise",
                    nonexistent="raise",
                )
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"Timestamp {value!r} is invalid in source_timezone "
                    f"{source_timezone!r}"
                ) from exc
        parsed_timestamps.append(timestamp.tz_convert("UTC"))
    normalized["timestamp"] = pd.DatetimeIndex(parsed_timestamps)
    for column in CANONICAL_COLUMNS[1:]:
        normalized[column] = pd.to_numeric(normalized[column], errors="coerce")
    if normalized[CANONICAL_COLUMNS[1:]].isna().any().any():
        raise ValueError("OHLCV contains missing or non-numeric values")
    normalized = (
        normalized.sort_values("timestamp")
        .drop_duplicates(subset=["timestamp"], keep="last")
        .reset_index(drop=True)
    )

    dropped = False
    if drop_incomplete and not normalized.empty:
        duration = pd.Timedelta(timeframe)
        now = reference_time or pd.Timestamp.now(tz="UTC")
        if now.tzinfo is None:
            now = now.tz_localize("UTC")
        else:
            now = now.tz_convert("UTC")
        if normalized.iloc[-1]["timestamp"] + duration > now:
            normalized = normalized.iloc[:-1].reset_index(drop=True)
            dropped = True
    return normalized, dropped


def _inside_equity_session(
    timestamp: pd.Timestamp,
    timezone: str,
    session_start: time,
    session_end: time,
) -> bool:
    local = timestamp.tz_convert(ZoneInfo(timezone))
    return (
        local.weekday() < 5
        and session_start <= local.time().replace(tzinfo=None) < session_end
    )


def _find_missing_bars(
    frame: pd.DataFrame,
    timeframe: str,
    asset_class: str,
    timezone: str,
    calendar: EquitySessionCalendar | None = None,
    excluded_session_dates: set[str] | None = None,
) -> list[pd.Timestamp]:
    if len(frame) < 2:
        return []
    duration = pd.Timedelta(timeframe)
    timestamps = set(frame["timestamp"])
    equity_calendar = calendar or EquitySessionCalendar(timezone=timezone)
    approved_excluded = excluded_session_dates or set()
    missing: list[pd.Timestamp] = []
    cursor = frame.iloc[0]["timestamp"] + duration
    last = frame.iloc[-1]["timestamp"]
    while cursor < last:
        expected = (
            asset_class == "crypto"
            or equity_calendar.contains(cursor)
        )
        if expected and cursor not in timestamps:
            local_session_date = (
                str(cursor.tz_convert(ZoneInfo(equity_calendar.timezone)).date())
                if asset_class == "equity"
                else ""
            )
            if local_session_date not in approved_excluded:
                missing.append(cursor)
        cursor += duration
    return missing


def validate_ohlcv(
    frame: pd.DataFrame,
    timeframe: str = "15min",
    *,
    asset_class: str = "equity",
    timezone: str = "America/New_York",
    incomplete_candle_dropped: bool = False,
    calendar: EquitySessionCalendar | None = None,
    excluded_session_dates: set[str] | None = None,
) -> DataQualityReport:
    required = set(CANONICAL_COLUMNS)
    if not required.issubset(frame.columns):
        missing = sorted(required.difference(frame.columns))
        raise ValueError(f"Missing canonical columns: {missing}")
    duplicate_count = int(frame["timestamp"].duplicated().sum())
    invalid_ohlc = (
        (frame["high"] < frame[["open", "close", "low"]].max(axis=1))
        | (frame["low"] > frame[["open", "close", "high"]].min(axis=1))
    )
    prices = frame[["open", "high", "low", "close"]]
    nonpositive = (prices <= 0).any(axis=1)
    negative_volume = frame["volume"] < 0
    outside = 0
    if asset_class == "equity":
        equity_calendar = calendar or EquitySessionCalendar(timezone=timezone)
        outside = sum(
            not equity_calendar.contains(ts)
            for ts in frame["timestamp"]
        )
    return DataQualityReport(
        rows=len(frame),
        duplicate_timestamps=duplicate_count,
        invalid_ohlc_rows=int(invalid_ohlc.sum()),
        nonpositive_price_rows=int(nonpositive.sum()),
        negative_volume_rows=int(negative_volume.sum()),
        missing_bars=_find_missing_bars(
            frame,
            timeframe,
            asset_class,
            timezone,
            calendar,
            excluded_session_dates,
        ),
        outside_session_rows=outside,
        incomplete_candle_dropped=incomplete_candle_dropped,
    )


def load_csv(
    path: str | Path,
    timeframe: str = "15min",
    *,
    asset_class: str = "equity",
    drop_incomplete: bool = True,
    reference_time: pd.Timestamp | None = None,
    source_timezone: str | None = None,
    calendar: EquitySessionCalendar | None = None,
    excluded_session_dates: set[str] | None = None,
) -> tuple[pd.DataFrame, DataQualityReport]:
    raw = pd.read_csv(Path(path))
    frame, dropped = normalize_ohlcv(
        raw,
        timeframe,
        drop_incomplete=drop_incomplete,
        reference_time=reference_time,
        source_timezone=source_timezone,
    )
    report = validate_ohlcv(
        frame,
        timeframe,
        asset_class=asset_class,
        incomplete_candle_dropped=dropped,
        calendar=calendar,
        excluded_session_dates=excluded_session_dates,
    )
    return frame, report
