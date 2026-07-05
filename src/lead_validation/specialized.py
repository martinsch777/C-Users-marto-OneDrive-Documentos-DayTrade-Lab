from __future__ import annotations

from pathlib import Path

import pandas as pd


TIMESTAMP_CANDIDATES = (
    "timestamp",
    "fundingTime",
    "funding_time",
    "time",
    "datetime",
)
FUNDING_CANDIDATES = ("funding_rate", "fundingRate", "rate")
OI_CANDIDATES = (
    "open_interest",
    "openInterest",
    "sumOpenInterest",
    "oi",
)


def _pick(frame: pd.DataFrame, candidates: tuple[str, ...], kind: str) -> str:
    column = next((name for name in candidates if name in frame.columns), None)
    if column is None:
        raise ValueError(f"No supported {kind} column; expected one of {candidates}")
    return column


def _timestamp(values: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    if numeric.notna().mean() >= 0.95:
        median = float(numeric.dropna().median())
        unit = "ms" if median > 10_000_000_000 else "s"
        return pd.to_datetime(numeric, unit=unit, utc=True, errors="coerce")
    return pd.to_datetime(values, utc=True, errors="coerce")


def _import_csv(
    path: str | Path,
    value_candidates: tuple[str, ...],
    output_name: str,
) -> tuple[pd.DataFrame, dict]:
    source = Path(path)
    raw = pd.read_csv(source)
    time_column = _pick(raw, TIMESTAMP_CANDIDATES, "timestamp")
    value_column = _pick(raw, value_candidates, output_name)
    normalized = pd.DataFrame(
        {
            "timestamp": _timestamp(raw[time_column]),
            output_name: pd.to_numeric(raw[value_column], errors="coerce"),
        }
    )
    source_rows = len(normalized)
    invalid = int(normalized.isna().any(axis=1).sum())
    duplicates = int(normalized["timestamp"].duplicated().sum())
    normalized = (
        normalized.dropna()
        .drop_duplicates("timestamp", keep="last")
        .sort_values("timestamp")
        .reset_index(drop=True)
    )
    report = {
        "path": str(source.resolve()),
        "dataset": output_name,
        "source_rows": source_rows,
        "valid_rows": len(normalized),
        "invalid_rows": invalid,
        "duplicate_timestamps": duplicates,
        "utc": True,
        "chronological": bool(normalized["timestamp"].is_monotonic_increasing),
        "first_timestamp_utc": (
            normalized["timestamp"].min().isoformat() if len(normalized) else ""
        ),
        "last_timestamp_utc": (
            normalized["timestamp"].max().isoformat() if len(normalized) else ""
        ),
    }
    return normalized, report


def import_funding_csv(path: str | Path) -> tuple[pd.DataFrame, dict]:
    return _import_csv(path, FUNDING_CANDIDATES, "funding_rate")


def import_open_interest_csv(path: str | Path) -> tuple[pd.DataFrame, dict]:
    return _import_csv(path, OI_CANDIDATES, "open_interest")


def align_specialized_data_causally(
    candles: pd.DataFrame,
    specialized: pd.DataFrame,
    value_column: str,
    *,
    max_staleness: str,
) -> pd.DataFrame:
    """Backward as-of join: a candle can only see values published at/before it."""
    left = candles.copy()
    left["timestamp"] = pd.to_datetime(left["timestamp"], utc=True)
    right = specialized[["timestamp", value_column]].copy()
    right["timestamp"] = pd.to_datetime(right["timestamp"], utc=True)
    right = right.sort_values("timestamp").rename(
        columns={"timestamp": "source_timestamp"}
    )
    aligned = pd.merge_asof(
        left.sort_values("timestamp"),
        right,
        left_on="timestamp",
        right_on="source_timestamp",
        direction="backward",
        tolerance=pd.Timedelta(max_staleness),
    )
    aligned[f"{value_column}_age_seconds"] = (
        aligned["timestamp"] - aligned["source_timestamp"]
    ).dt.total_seconds()
    return aligned


class OfflineFundingAdapter:
    provider = "offline_csv"

    def load(self, path: str | Path) -> tuple[pd.DataFrame, dict]:
        return import_funding_csv(path)


class OfflineOpenInterestAdapter:
    provider = "offline_csv"

    def load(self, path: str | Path) -> tuple[pd.DataFrame, dict]:
        return import_open_interest_csv(path)
