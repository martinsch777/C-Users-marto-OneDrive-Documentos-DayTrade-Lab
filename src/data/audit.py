from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd

from src.timeframes import parse_timeframe_timedelta

from .loader import normalize_ohlcv, validate_ohlcv


def _sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class DatasetAudit:
    provider: str
    symbol: str
    timeframe: str
    path: str
    rows: int
    first_timestamp_utc: str
    last_timestamp_utc: str
    expected_bars_between_first_last: int
    coverage_ratio: float
    source_duplicates: int
    temporal_order_valid: bool
    timezone_utc: bool
    missing_bars: int
    invalid_ohlc_rows: int
    nonpositive_price_rows: int
    negative_volume_rows: int
    incomplete_candle_present: bool
    sha256: str
    file_bytes: int
    quality_valid: bool
    research_usable: bool
    metadata_status: str

    def to_record(self) -> dict:
        return asdict(self)


def audit_crypto_csv(
    path: str | Path,
    symbol: str,
    timeframe: str,
    *,
    provider: str = "binance",
    reference_time: pd.Timestamp | None = None,
) -> DatasetAudit:
    source = Path(path)
    raw = pd.read_csv(source)
    timestamp_column = next(
        (
            column
            for column in raw.columns
            if str(column).strip().lower()
            in {"timestamp", "datetime", "date", "time", "open_time"}
        ),
        None,
    )
    if timestamp_column is None:
        raise ValueError(f"No timestamp column found in {source}")
    original_text = raw[timestamp_column].astype(str)
    parsed = pd.to_datetime(raw[timestamp_column], utc=True, errors="raise")
    source_duplicates = int(parsed.duplicated().sum())
    temporal_order = bool(parsed.is_monotonic_increasing)
    timezone_utc = bool(
        original_text.str.contains(r"(?:\+00:00|Z)$", regex=True).all()
    )
    now = reference_time or pd.Timestamp.now(tz="UTC")
    normalized, dropped = normalize_ohlcv(
        raw,
        timeframe,
        drop_incomplete=False,
        reference_time=now,
        source_timezone="UTC",
    )
    quality = validate_ohlcv(
        normalized,
        timeframe,
        asset_class="crypto",
        timezone="UTC",
    )
    duration = parse_timeframe_timedelta(timeframe)
    incomplete_present = bool(
        not normalized.empty and normalized.iloc[-1]["timestamp"] + duration > now
    )
    expected = (
        int(
            (
                normalized.iloc[-1]["timestamp"]
                - normalized.iloc[0]["timestamp"]
            )
            / duration
        )
        + 1
        if len(normalized) > 1
        else len(normalized)
    )
    metadata_path = source.with_suffix(".metadata.json")
    metadata_status = "missing"
    if metadata_path.exists():
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata_status = str(metadata.get("status", "unknown"))
    quality_valid = (
        quality.is_valid
        and source_duplicates == 0
        and temporal_order
        and timezone_utc
        and not incomplete_present
    )
    maximum_tolerated_gaps = max(10, int(expected * 0.0001))
    research_usable = (
        quality.invalid_ohlc_rows == 0
        and quality.nonpositive_price_rows == 0
        and quality.negative_volume_rows == 0
        and source_duplicates == 0
        and temporal_order
        and timezone_utc
        and not incomplete_present
        and len(quality.missing_bars) <= maximum_tolerated_gaps
    )
    return DatasetAudit(
        provider=provider,
        symbol=symbol,
        timeframe=timeframe,
        path=str(source.resolve()),
        rows=len(normalized),
        first_timestamp_utc=(
            normalized.iloc[0]["timestamp"].isoformat() if not normalized.empty else ""
        ),
        last_timestamp_utc=(
            normalized.iloc[-1]["timestamp"].isoformat() if not normalized.empty else ""
        ),
        expected_bars_between_first_last=expected,
        coverage_ratio=len(normalized) / expected if expected else 0.0,
        source_duplicates=source_duplicates,
        temporal_order_valid=temporal_order,
        timezone_utc=timezone_utc,
        missing_bars=len(quality.missing_bars),
        invalid_ohlc_rows=quality.invalid_ohlc_rows,
        nonpositive_price_rows=quality.nonpositive_price_rows,
        negative_volume_rows=quality.negative_volume_rows,
        incomplete_candle_present=incomplete_present,
        sha256=_sha256_file(source),
        file_bytes=source.stat().st_size,
        quality_valid=quality_valid,
        research_usable=research_usable,
        metadata_status=metadata_status,
    )
