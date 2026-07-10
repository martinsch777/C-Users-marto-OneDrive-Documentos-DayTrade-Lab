from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from .alpaca_equity_downloader import DownloadResult
from .dataset_manifest import (
    NOT_AUDITED,
    build_dataset_manifest,
    sha256_file,
    write_curated_dataset_manifest,
)
from .equity_audit import (
    _timestamp_column,
    audit_equity_intraday_csv,
)
from .quality_overrides import QualityOverrides, load_quality_overrides
from .sessions import EquitySessionCalendar


class EquityDatasetBuildError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class CuratedDatasetBuildResult:
    symbol: str
    timeframe: str
    input_file: str
    output_file: str
    rows_input: int
    rows_output: int
    rows_removed: int
    total_excluded_sessions: int
    excluded_sessions: list[dict[str, Any]] = field(default_factory=list)
    audit_apt_for_or_fvg_backtest: bool = False
    audit_critical_warnings: list[str] = field(default_factory=list)
    dataset_status: str = NOT_AUDITED
    audit_skipped: bool = False
    manifest_skipped: bool = False
    manifest_file: str = ""
    broker_connected: bool = False
    orders_sent: bool = False
    live_trading_enabled: bool = False
    paper_internal_enabled: bool = False
    paper_broker_enabled: bool = False

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


def curated_dataset_filename(
    *,
    symbol: str,
    timeframe: str,
    start: str,
    end: str,
    range_filenames: bool,
) -> str:
    if range_filenames:
        return f"{symbol.upper()}_{timeframe}_{start}_{end}_curated.csv"
    return f"{symbol.upper()}_{timeframe}_curated.csv"


def _log_verbose(enabled: bool, stage: str, detail: str = "") -> None:
    if not enabled:
        return
    stamp = datetime.now(timezone.utc).isoformat()
    suffix = f" | {detail}" if detail else ""
    print(f"[{stamp}] {stage}{suffix}", file=sys.stderr, flush=True)


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _parse_timestamps_vectorized(
    frame: pd.DataFrame,
    *,
    source_timezone: str,
) -> tuple[str, pd.Series]:
    timestamp_column = _timestamp_column(frame)
    values = frame[timestamp_column]
    text = values.astype("string")
    timezone_hints = text.str.contains(r"(?:Z|[+-]\d{2}:?\d{2})$", regex=True, na=False)
    if bool(timezone_hints.all()):
        parsed_index = pd.to_datetime(values, utc=True, errors="raise")
    elif bool((~timezone_hints).all()):
        parsed_naive = pd.to_datetime(values, errors="raise")
        parsed_index = parsed_naive.dt.tz_localize(
            source_timezone,
            ambiguous="raise",
            nonexistent="raise",
        ).dt.tz_convert("UTC")
    else:
        parsed_index = pd.to_datetime(values, utc=True, errors="raise")
    return timestamp_column, pd.Series(parsed_index, index=frame.index)


def _local_date_strings(parsed_utc: pd.Series, timezone_name: str) -> pd.Series:
    return parsed_utc.dt.tz_convert(ZoneInfo(timezone_name)).dt.date.astype(str)


def _rth_mask(
    parsed_utc: pd.Series,
    *,
    calendar: EquitySessionCalendar,
) -> pd.Series:
    if parsed_utc.empty:
        return pd.Series([], index=parsed_utc.index, dtype=bool)
    local = parsed_utc.dt.tz_convert(ZoneInfo(calendar.timezone))
    dates = local.dt.date.astype(str)
    close_by_date = {
        date_text: calendar.session_close(pd.Timestamp(date_text).date())
        for date_text in dates.unique()
    }
    close_minutes_by_date = {
        date_text: (
            close.hour * 60 + close.minute
            if close is not None
            else -1
        )
        for date_text, close in close_by_date.items()
    }
    close_minutes = dates.map(close_minutes_by_date).astype(int)
    open_minutes = calendar.regular_open.hour * 60 + calendar.regular_open.minute
    bar_minutes = local.dt.hour * 60 + local.dt.minute
    return (close_minutes >= 0) & (bar_minutes >= open_minutes) & (
        bar_minutes < close_minutes
    )


def _atomic_write_csv(frame: pd.DataFrame, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f"{destination.name}.tmp")
    temporary.unlink(missing_ok=True)
    frame.to_csv(temporary, index=False)
    try:
        temporary.replace(destination)
    except PermissionError:
        if destination.exists():
            destination.unlink()
        temporary.replace(destination)


def build_equity_dataset(
    *,
    csv_path: str | Path,
    symbol: str,
    timeframe: str = "1min",
    asset_class: str = "equity",
    source_timezone: str = "America/New_York",
    output_dir: str | Path = Path("data") / "curated",
    output_file: str | Path | None = None,
    start: str,
    end: str,
    provider: str = "alpaca",
    feed: str = "sip",
    adjustment: str = "raw",
    rth_only: bool = True,
    excluded_sessions: str | Path | QualityOverrides | None = None,
    manifest_dir: str | Path = Path("data") / "manifests",
    range_filenames: bool = False,
    overwrite: bool = False,
    calendar: EquitySessionCalendar | None = None,
    verbose: bool = False,
    skip_audit: bool = False,
    skip_manifest: bool = False,
) -> CuratedDatasetBuildResult:
    _log_verbose(verbose, "START", f"symbol={symbol.upper()} start={start} end={end}")
    if asset_class != "equity":
        raise EquityDatasetBuildError(
            "UNSUPPORTED_ASSET_CLASS",
            "build_equity_dataset only supports asset_class='equity'",
        )
    if timeframe != "1min":
        raise EquityDatasetBuildError(
            "UNSUPPORTED_TIMEFRAME",
            "build_equity_dataset only supports timeframe='1min'",
        )
    source = Path(csv_path)
    destination = (
        Path(output_file)
        if output_file is not None
        else Path(output_dir)
        / curated_dataset_filename(
            symbol=symbol,
            timeframe=timeframe,
            start=start,
            end=end,
            range_filenames=range_filenames,
        )
    )
    manifest_destination = Path(manifest_dir)
    _log_verbose(
        verbose,
        "validating output paths",
        f"output={destination} manifest_dir={manifest_destination}",
    )
    if destination.exists() and not overwrite:
        raise EquityDatasetBuildError(
            "OUTPUT_FILE_ALREADY_EXISTS",
            f"Output file already exists: {destination}",
        )
    if destination.suffix.lower() != ".csv":
        raise EquityDatasetBuildError(
            "OUTPUT_FILE_MUST_BE_CSV",
            f"Output file must end with .csv: {destination}",
        )
    if _is_relative_to(destination, manifest_destination):
        raise EquityDatasetBuildError(
            "OUTPUT_CSV_INSIDE_MANIFEST_DIR",
            f"Refusing to write curated CSV inside manifest directory: {destination}",
        )
    if not source.exists():
        raise EquityDatasetBuildError(
            "CSV_NOT_FOUND",
            f"Input CSV not found: {source}",
        )
    overrides = (
        excluded_sessions
        if isinstance(excluded_sessions, QualityOverrides)
        else load_quality_overrides(excluded_sessions)
    )

    _log_verbose(verbose, "reading CSV", str(source))
    frame = pd.read_csv(source)
    _log_verbose(verbose, "rows loaded", str(len(frame)))
    _log_verbose(verbose, "parsing timestamps")
    timestamp_column, parsed = _parse_timestamps_vectorized(
        frame,
        source_timezone=source_timezone,
    )
    equity_calendar = calendar or EquitySessionCalendar.from_config(
        {"source": "us_equity"}
    )
    _log_verbose(verbose, "filtering start/end", f"{start} to {end}")
    local_dates = parsed.dt.tz_convert(ZoneInfo(source_timezone)).dt.date.astype(str)
    keep_mask = (local_dates >= start) & (local_dates <= end)
    _log_verbose(verbose, "applying RTH filter", f"rth_only={rth_only}")
    if rth_only:
        keep_mask = keep_mask & _rth_mask(parsed, calendar=equity_calendar)
    working_dates = local_dates.loc[keep_mask]
    matching = overrides.matching_sessions(
        symbol=symbol,
        dates=set(working_dates),
    )
    _log_verbose(verbose, "applying excluded sessions", f"count={len(matching)}")
    excluded_dates = {session.date for session in matching}
    keep_mask = keep_mask & ~local_dates.isin(excluded_dates)
    excluded_session_records: list[dict[str, Any]] = []
    date_counts = local_dates.value_counts()
    for session in matching:
        expected_count = len(
            equity_calendar.expected_timestamps(
                pd.Timestamp(session.date).date(),
                pd.Timestamp(session.date).date(),
                timeframe,
            )
        )
        bars_removed = int(date_counts.get(session.date, 0))
        excluded_session_records.append(
            {
                **session.to_record(),
                "expected_bars": expected_count,
                "bars_removed": bars_removed,
            }
        )
    curated = frame.loc[keep_mask].copy()
    parsed_curated = parsed.loc[keep_mask]
    if not curated.empty:
        curated = curated.assign(_timestamp_utc=parsed_curated.to_numpy())
        curated = curated.sort_values("_timestamp_utc").drop(columns=["_timestamp_utc"])
    if timestamp_column != "timestamp":
        if "timestamp" in curated.columns:
            curated = curated.drop(columns=["timestamp"])
        curated = curated.rename(columns={timestamp_column: "timestamp"})

    _log_verbose(verbose, "writing curated CSV", str(destination))
    _atomic_write_csv(curated, destination)
    audit = None
    if skip_audit:
        _log_verbose(verbose, "running audit", "SKIPPED")
    else:
        _log_verbose(verbose, "running audit")
        audit = audit_equity_intraday_csv(
            destination,
            symbol,
            timeframe,
            asset_class=asset_class,
            source_timezone=source_timezone,
            calendar=equity_calendar,
            excluded_sessions=overrides,
            expected_start=start,
            expected_end=end,
        )
    _log_verbose(verbose, "calculating sha256", str(destination))
    digest = sha256_file(destination)
    first = str(curated.iloc[0]["timestamp"]) if not curated.empty else ""
    last = str(curated.iloc[-1]["timestamp"]) if not curated.empty else ""
    download_like_result = DownloadResult(
        symbol=symbol.upper(),
        provider=provider,
        feed=feed,
        interval=timeframe,
        adjustment=adjustment,
        start=start,
        end=end,
        rows=len(curated),
        first_timestamp=first,
        last_timestamp=last,
        output_file=str(destination),
        sha256=digest,
        rth_only=rth_only,
        pages_downloaded=0,
        audit_apt_for_or_fvg_backtest=(
            audit.apt_for_or_fvg_backtest if audit is not None else None
        ),
        audit_critical_warnings=(
            audit.critical_warnings if audit is not None else None
        ),
    )
    manifest = build_dataset_manifest(
        download_like_result,
        audit_report=audit,
        source_timezone=source_timezone,
        asset_class=asset_class,
        excluded_sessions=excluded_session_records,
        raw_input_file=str(source),
        curated_file=str(destination),
        rows_input=len(frame),
        rows_output=len(curated),
        rows_removed=len(frame) - len(curated),
    )
    manifest_path: Path | None = None
    if skip_manifest:
        _log_verbose(verbose, "writing manifest", "SKIPPED")
    else:
        _log_verbose(verbose, "writing manifest", str(manifest_destination))
        manifest_path = write_curated_dataset_manifest(manifest, manifest_destination)
    sidecar = destination.with_suffix(".build.json")
    result = CuratedDatasetBuildResult(
        symbol=symbol.upper(),
        timeframe=timeframe,
        input_file=str(source),
        output_file=str(destination),
        rows_input=len(frame),
        rows_output=len(curated),
        rows_removed=len(frame) - len(curated),
        total_excluded_sessions=len(matching),
        excluded_sessions=excluded_session_records,
        audit_apt_for_or_fvg_backtest=(
            audit.apt_for_or_fvg_backtest if audit is not None else False
        ),
        audit_critical_warnings=(
            list(audit.critical_warnings) if audit is not None else []
        ),
        dataset_status=manifest.dataset_status,
        audit_skipped=skip_audit,
        manifest_skipped=skip_manifest,
        manifest_file=str(manifest_path) if manifest_path is not None else "",
    )
    sidecar.write_text(
        json.dumps(result.to_record(), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    _log_verbose(verbose, "DONE", f"rows_output={len(curated)}")
    return result
