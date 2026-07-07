from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from .loader import CANONICAL_COLUMNS, TIMESTAMP_ALIASES, _rename_columns
from .sessions import EquitySessionCalendar


SUPPORTED_EQUITY_SYMBOLS = {"QQQ", "SPY"}
MIN_BARS_FOR_STRATEGY_DAY = 300


def _sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class SessionAudit:
    session_date: str
    expected_bars: int
    observed_rth_bars: int
    missing_bars: int
    extra_off_schedule_bars: int
    duplicate_bars: int
    outside_rth_bars: int
    complete: bool
    early_close: bool
    discarded: bool
    discard_reason: str

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EquityIntradayAuditReport:
    symbol: str
    asset_class: str
    timeframe: str
    path: str
    source_timezone: str | None
    timestamp_timezone_status: str
    rows_total: int
    rows_after_normalization: int
    first_timestamp_utc: str
    last_timestamp_utc: str
    first_session_date: str
    last_session_date: str
    sessions: int
    sessions_complete: int
    sessions_incomplete: int
    expected_bars: int
    observed_rth_bars: int
    missing_bars: int
    duplicate_timestamps: int
    chronological_order_valid: bool
    outside_rth_bars: int
    premarket_bars: int
    after_hours_bars: int
    holiday_or_closed_session_bars: int
    off_schedule_rth_bars: int
    anomalous_time_gaps: int
    max_gap_minutes: float
    invalid_ohlc_rows: int
    nonpositive_price_rows: int
    nonpositive_volume_rows: int
    sessions_with_too_few_bars: int
    sessions_with_unexpected_bar_count: int
    discarded_days: int
    critical_warnings: list[str] = field(default_factory=list)
    calendar_name: str = ""
    calendar_source: str = ""
    calendar_loaded: bool = False
    calendar_supported_start: str = ""
    calendar_supported_end: str = ""
    calendar_holidays_loaded: int = 0
    calendar_early_closes_loaded: int = 0
    apt_for_or_fvg_backtest: bool = False
    broker_connected: bool = False
    orders_sent: bool = False
    live_trading_enabled: bool = False
    api_keys_used: bool = False
    sha256: str = ""
    file_bytes: int = 0
    session_details: list[SessionAudit] = field(default_factory=list)

    def to_record(self) -> dict[str, Any]:
        data = asdict(self)
        data["session_details"] = [
            session.to_record() for session in self.session_details
        ]
        return data

    def summary_record(self) -> dict[str, Any]:
        data = self.to_record()
        data.pop("session_details", None)
        data["critical_warnings"] = ";".join(self.critical_warnings)
        return data


def _timestamp_column(raw: pd.DataFrame) -> str:
    lowered = {str(column).strip().lower(): column for column in raw.columns}
    timestamp_name = next((name for name in TIMESTAMP_ALIASES if name in lowered), None)
    if timestamp_name is None:
        raise ValueError(f"Missing timestamp column; accepted: {TIMESTAMP_ALIASES}")
    return str(lowered[timestamp_name])


def _parse_source_timestamps(
    values: pd.Series,
    *,
    source_timezone: str | None,
) -> tuple[pd.Series, str]:
    parsed: list[pd.Timestamp] = []
    naive_count = 0
    aware_count = 0
    for value in values:
        try:
            timestamp = pd.Timestamp(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Timestamp could not be parsed: {value!r}") from exc
        if pd.isna(timestamp):
            raise ValueError("One or more timestamps could not be parsed")
        if timestamp.tzinfo is None:
            naive_count += 1
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
        else:
            aware_count += 1
        parsed.append(timestamp.tz_convert("UTC"))
    if naive_count and aware_count:
        status = "mixed_timezone_aware_and_localized"
    elif naive_count:
        status = "localized_from_source_timezone"
    else:
        status = "timezone_aware"
    return pd.Series(pd.DatetimeIndex(parsed), index=values.index), status


def _classify_outside_rth(
    timestamp: pd.Timestamp,
    calendar: EquitySessionCalendar,
) -> str:
    local = timestamp.tz_convert(ZoneInfo(calendar.timezone))
    close = calendar.session_close(local.date())
    if close is None:
        return "holiday_or_closed"
    clock = local.time().replace(tzinfo=None)
    if clock < calendar.regular_open:
        return "premarket"
    if clock >= close:
        return "after_hours"
    return "inside"


def _build_markdown_report(report: EquityIntradayAuditReport) -> str:
    verdict = "APTO" if report.apt_for_or_fvg_backtest else "NO APTO"
    warnings = (
        "\n".join(f"- {warning}" for warning in report.critical_warnings)
        if report.critical_warnings
        else "- Sin advertencias críticas."
    )
    return "\n".join(
        [
            f"# Auditoría intradiaria 1 minuto - {report.symbol}",
            "",
            f"Veredicto OR/FVG: **{verdict}**",
            "",
            "## Resumen",
            "",
            f"- Filas totales: {report.rows_total}",
            f"- Rango UTC: {report.first_timestamp_utc} a {report.last_timestamp_utc}",
            f"- Sesiones: {report.sessions}",
            f"- Sesiones completas: {report.sessions_complete}",
            f"- Sesiones incompletas: {report.sessions_incomplete}",
            f"- Barras esperadas RTH: {report.expected_bars}",
            f"- Barras observadas RTH: {report.observed_rth_bars}",
            f"- Barras faltantes: {report.missing_bars}",
            f"- Duplicados: {report.duplicate_timestamps}",
            f"- Barras fuera de RTH: {report.outside_rth_bars}",
            f"- Gaps anormales: {report.anomalous_time_gaps}",
            "",
            "## Advertencias críticas",
            "",
            warnings,
            "",
            "## Seguridad",
            "",
            "- broker_connected=False",
            "- orders_sent=False",
            "- live_trading_enabled=False",
            "- private_credentials_used=False",
        ]
    )


def _warning(condition: bool, code: str, warnings: list[str]) -> None:
    if condition:
        warnings.append(code)


def audit_equity_intraday_csv(
    path: str | Path,
    symbol: str,
    timeframe: str = "1min",
    *,
    asset_class: str = "equity",
    source_timezone: str | None = None,
    calendar: EquitySessionCalendar | None = None,
) -> EquityIntradayAuditReport:
    if asset_class != "equity":
        raise ValueError("audit_equity_intraday_csv only supports asset_class='equity'")

    source = Path(path)
    equity_calendar = calendar or EquitySessionCalendar.us_equity()
    if not source.exists():
        return EquityIntradayAuditReport(
            symbol=symbol.upper(),
            asset_class=asset_class,
            timeframe=timeframe,
            path=str(source.resolve()),
            source_timezone=source_timezone,
            timestamp_timezone_status="not_loaded",
            rows_total=0,
            rows_after_normalization=0,
            first_timestamp_utc="",
            last_timestamp_utc="",
            first_session_date="",
            last_session_date="",
            sessions=0,
            sessions_complete=0,
            sessions_incomplete=0,
            expected_bars=0,
            observed_rth_bars=0,
            missing_bars=0,
            duplicate_timestamps=0,
            chronological_order_valid=False,
            outside_rth_bars=0,
            premarket_bars=0,
            after_hours_bars=0,
            holiday_or_closed_session_bars=0,
            off_schedule_rth_bars=0,
            anomalous_time_gaps=0,
            max_gap_minutes=0.0,
            invalid_ohlc_rows=0,
            nonpositive_price_rows=0,
            nonpositive_volume_rows=0,
            sessions_with_too_few_bars=0,
            sessions_with_unexpected_bar_count=0,
            discarded_days=0,
            critical_warnings=["CSV_NOT_FOUND"],
            calendar_name=equity_calendar.name,
            calendar_source=equity_calendar.source,
            calendar_loaded=equity_calendar.loaded,
            calendar_supported_start=(
                equity_calendar.supported_start.isoformat()
                if equity_calendar.supported_start
                else ""
            ),
            calendar_supported_end=(
                equity_calendar.supported_end.isoformat()
                if equity_calendar.supported_end
                else ""
            ),
            calendar_holidays_loaded=len(equity_calendar.holidays),
            calendar_early_closes_loaded=len(equity_calendar.early_closes),
            apt_for_or_fvg_backtest=False,
            sha256="",
            file_bytes=0,
            session_details=[],
        )
    raw = pd.read_csv(source)
    timestamp_column = _timestamp_column(raw)
    parsed_timestamps, timezone_status = _parse_source_timestamps(
        raw[timestamp_column],
        source_timezone=source_timezone,
    )
    chronological_order_valid = bool(parsed_timestamps.is_monotonic_increasing)
    duplicate_timestamps = int(parsed_timestamps.duplicated().sum())

    normalized = _rename_columns(raw).loc[:, CANONICAL_COLUMNS].copy()
    normalized["timestamp"] = parsed_timestamps
    for column in CANONICAL_COLUMNS[1:]:
        normalized[column] = pd.to_numeric(normalized[column], errors="coerce")
    if normalized[CANONICAL_COLUMNS[1:]].isna().any().any():
        raise ValueError("OHLCV contains missing or non-numeric values")

    normalized = normalized.sort_values("timestamp").reset_index(drop=True)
    unique = normalized.drop_duplicates(subset=["timestamp"], keep="last").copy()
    unique = unique.reset_index(drop=True)

    duration = pd.Timedelta(timeframe)
    local_times = unique["timestamp"].dt.tz_convert(ZoneInfo(equity_calendar.timezone))
    first_session_date = local_times.dt.date.min() if not unique.empty else None
    last_session_date = local_times.dt.date.max() if not unique.empty else None
    expected_index = (
        equity_calendar.expected_timestamps(
            first_session_date,
            last_session_date,
            timeframe,
        )
        if first_session_date is not None and last_session_date is not None
        else pd.DatetimeIndex([], tz="UTC")
    )
    expected_set = set(expected_index)
    observed_set = set(unique["timestamp"])
    missing = sorted(expected_set.difference(observed_set))

    outside_labels = unique["timestamp"].map(
        lambda ts: _classify_outside_rth(ts, equity_calendar)
    )
    inside_mask = outside_labels == "inside"
    premarket_bars = int((outside_labels == "premarket").sum())
    after_hours_bars = int((outside_labels == "after_hours").sum())
    holiday_or_closed = int((outside_labels == "holiday_or_closed").sum())
    outside_rth_bars = premarket_bars + after_hours_bars + holiday_or_closed
    off_schedule_rth = int(
        (inside_mask & ~unique["timestamp"].isin(expected_set)).sum()
    )

    local_session_dates = unique["timestamp"].dt.tz_convert(
        ZoneInfo(equity_calendar.timezone)
    ).dt.date
    same_session = local_session_dates.eq(local_session_dates.shift(1))
    inside_series = pd.Series(inside_mask.to_numpy(), index=unique.index)
    consecutive_inside_same_session = (
        inside_series & inside_series.shift(1, fill_value=False) & same_session
    )
    diffs = unique["timestamp"].diff()
    anomalous_gaps = diffs[consecutive_inside_same_session & (diffs > duration)]
    max_gap_minutes = (
        float(anomalous_gaps.max() / pd.Timedelta(minutes=1))
        if not anomalous_gaps.empty
        else 0.0
    )

    invalid_ohlc = (
        (normalized["high"] < normalized[["open", "close", "low"]].max(axis=1))
        | (normalized["low"] > normalized[["open", "close", "high"]].min(axis=1))
    )
    prices = normalized[["open", "high", "low", "close"]]
    nonpositive_price = (prices <= 0).any(axis=1)
    nonpositive_volume = normalized["volume"] <= 0

    session_details: list[SessionAudit] = []
    if first_session_date is not None and last_session_date is not None:
        expected_by_session = pd.Series(expected_index).dt.tz_convert(
            ZoneInfo(equity_calendar.timezone)
        )
        expected_dates = (
            expected_by_session.dt.date.value_counts().to_dict()
            if len(expected_by_session)
            else {}
        )
        observed_inside = unique.loc[inside_mask].copy()
        observed_inside["_session_date"] = observed_inside["timestamp"].dt.tz_convert(
            ZoneInfo(equity_calendar.timezone)
        ).dt.date
        outside = unique.loc[~inside_mask].copy()
        outside["_session_date"] = outside["timestamp"].dt.tz_convert(
            ZoneInfo(equity_calendar.timezone)
        ).dt.date
        duplicate_dates = parsed_timestamps[parsed_timestamps.duplicated()]
        duplicate_dates = duplicate_dates.dt.tz_convert(
            ZoneInfo(equity_calendar.timezone)
        ).dt.date

        for day in pd.date_range(first_session_date, last_session_date, freq="D"):
            session_date = day.date()
            close = equity_calendar.session_close(session_date)
            expected_count = int(expected_dates.get(session_date, 0))
            if expected_count == 0:
                continue
            observed_count = int(
                (observed_inside["_session_date"] == session_date).sum()
            )
            missing_count = int(
                sum(
                    ts.tz_convert(ZoneInfo(equity_calendar.timezone)).date()
                    == session_date
                    for ts in missing
                )
            )
            extra_count = int(
                (
                    (observed_inside["_session_date"] == session_date)
                    & ~observed_inside["timestamp"].isin(expected_set)
                ).sum()
            )
            outside_count = int((outside["_session_date"] == session_date).sum())
            duplicate_count = int((duplicate_dates == session_date).sum())
            complete = (
                observed_count == expected_count
                and missing_count == 0
                and extra_count == 0
                and duplicate_count == 0
                and outside_count == 0
            )
            too_few = (
                expected_count >= MIN_BARS_FOR_STRATEGY_DAY
                and observed_count < MIN_BARS_FOR_STRATEGY_DAY
            )
            unexpected = observed_count != expected_count
            discarded = not complete or too_few
            reasons: list[str] = []
            if missing_count:
                reasons.append("missing_bars")
            if unexpected:
                reasons.append("unexpected_bar_count")
            if too_few:
                reasons.append("too_few_bars")
            if outside_count:
                reasons.append("outside_rth")
            if duplicate_count:
                reasons.append("duplicates")
            if extra_count:
                reasons.append("off_schedule")
            session_details.append(
                SessionAudit(
                    session_date=session_date.isoformat(),
                    expected_bars=expected_count,
                    observed_rth_bars=observed_count,
                    missing_bars=missing_count,
                    extra_off_schedule_bars=extra_count,
                    duplicate_bars=duplicate_count,
                    outside_rth_bars=outside_count,
                    complete=complete,
                    early_close=bool(close and close != equity_calendar.regular_close),
                    discarded=discarded,
                    discard_reason=";".join(reasons),
                )
            )

    sessions_complete = sum(session.complete for session in session_details)
    sessions_incomplete = len(session_details) - sessions_complete
    sessions_too_few = sum(
        session.expected_bars >= MIN_BARS_FOR_STRATEGY_DAY
        and session.observed_rth_bars < MIN_BARS_FOR_STRATEGY_DAY
        for session in session_details
    )
    sessions_unexpected = sum(
        session.observed_rth_bars != session.expected_bars
        for session in session_details
    )
    discarded_days = sum(session.discarded for session in session_details)

    critical_warnings: list[str] = []
    calendar_range_supported = bool(
        first_session_date is None
        or last_session_date is None
        or (
            equity_calendar.supports(first_session_date)
            and equity_calendar.supports(last_session_date)
        )
    )
    _warning(
        symbol.upper() not in SUPPORTED_EQUITY_SYMBOLS,
        "UNSUPPORTED_INITIAL_SYMBOL",
        critical_warnings,
    )
    _warning(timeframe != "1min", "TIMEFRAME_NOT_1MIN", critical_warnings)
    _warning(duplicate_timestamps > 0, "DUPLICATE_TIMESTAMPS", critical_warnings)
    _warning(not chronological_order_valid, "NON_CHRONOLOGICAL_ROWS", critical_warnings)
    _warning(len(missing) > 0, "MISSING_RTH_BARS", critical_warnings)
    _warning(outside_rth_bars > 0, "OUTSIDE_RTH_BARS", critical_warnings)
    _warning(premarket_bars > 0, "PREMARKET_BARS_PRESENT", critical_warnings)
    _warning(after_hours_bars > 0, "AFTER_HOURS_BARS_PRESENT", critical_warnings)
    _warning(holiday_or_closed > 0, "HOLIDAY_OR_CLOSED_SESSION_BARS", critical_warnings)
    _warning(off_schedule_rth > 0, "OFF_SCHEDULE_RTH_BARS", critical_warnings)
    _warning(len(anomalous_gaps) > 0, "ANOMALOUS_TIME_GAPS", critical_warnings)
    _warning(int(invalid_ohlc.sum()) > 0, "INVALID_OHLC", critical_warnings)
    _warning(int(nonpositive_price.sum()) > 0, "NONPOSITIVE_PRICES", critical_warnings)
    _warning(int(nonpositive_volume.sum()) > 0, "NONPOSITIVE_VOLUME", critical_warnings)
    _warning(sessions_too_few > 0, "TOO_FEW_BARS_IN_SESSION", critical_warnings)
    _warning(sessions_unexpected > 0, "UNEXPECTED_SESSION_BAR_COUNT", critical_warnings)
    _warning(not equity_calendar.loaded, "REAL_MARKET_CALENDAR_NOT_LOADED", critical_warnings)
    _warning(not calendar_range_supported, "CALENDAR_DATE_OUT_OF_SUPPORTED_RANGE", critical_warnings)

    apt = (
        symbol.upper() in SUPPORTED_EQUITY_SYMBOLS
        and timeframe == "1min"
        and timezone_status in {
            "timezone_aware",
            "localized_from_source_timezone",
            "mixed_timezone_aware_and_localized",
        }
        and duplicate_timestamps == 0
        and chronological_order_valid
        and len(missing) == 0
        and outside_rth_bars == 0
        and off_schedule_rth == 0
        and len(anomalous_gaps) == 0
        and int(invalid_ohlc.sum()) == 0
        and int(nonpositive_price.sum()) == 0
        and int(nonpositive_volume.sum()) == 0
        and sessions_incomplete == 0
        and sessions_too_few == 0
        and len(session_details) > 0
        and equity_calendar.loaded
        and calendar_range_supported
    )

    return EquityIntradayAuditReport(
        symbol=symbol.upper(),
        asset_class=asset_class,
        timeframe=timeframe,
        path=str(source.resolve()),
        source_timezone=source_timezone,
        timestamp_timezone_status=timezone_status,
        rows_total=len(raw),
        rows_after_normalization=len(unique),
        first_timestamp_utc=(
            unique.iloc[0]["timestamp"].isoformat() if not unique.empty else ""
        ),
        last_timestamp_utc=(
            unique.iloc[-1]["timestamp"].isoformat() if not unique.empty else ""
        ),
        first_session_date=first_session_date.isoformat() if first_session_date else "",
        last_session_date=last_session_date.isoformat() if last_session_date else "",
        sessions=len(session_details),
        sessions_complete=sessions_complete,
        sessions_incomplete=sessions_incomplete,
        expected_bars=len(expected_index),
        observed_rth_bars=int(inside_mask.sum()),
        missing_bars=len(missing),
        duplicate_timestamps=duplicate_timestamps,
        chronological_order_valid=chronological_order_valid,
        outside_rth_bars=outside_rth_bars,
        premarket_bars=premarket_bars,
        after_hours_bars=after_hours_bars,
        holiday_or_closed_session_bars=holiday_or_closed,
        off_schedule_rth_bars=off_schedule_rth,
        anomalous_time_gaps=len(anomalous_gaps),
        max_gap_minutes=max_gap_minutes,
        invalid_ohlc_rows=int(invalid_ohlc.sum()),
        nonpositive_price_rows=int(nonpositive_price.sum()),
        nonpositive_volume_rows=int(nonpositive_volume.sum()),
        sessions_with_too_few_bars=sessions_too_few,
        sessions_with_unexpected_bar_count=sessions_unexpected,
        discarded_days=discarded_days,
        critical_warnings=critical_warnings,
        calendar_name=equity_calendar.name,
        calendar_source=equity_calendar.source,
        calendar_loaded=equity_calendar.loaded,
        calendar_supported_start=(
            equity_calendar.supported_start.isoformat()
            if equity_calendar.supported_start
            else ""
        ),
        calendar_supported_end=(
            equity_calendar.supported_end.isoformat()
            if equity_calendar.supported_end
            else ""
        ),
        calendar_holidays_loaded=len(equity_calendar.holidays),
        calendar_early_closes_loaded=len(equity_calendar.early_closes),
        apt_for_or_fvg_backtest=apt,
        sha256=_sha256_file(source),
        file_bytes=source.stat().st_size,
        session_details=session_details,
    )


def write_equity_intraday_audit_report(
    report: EquityIntradayAuditReport,
    output_dir: str | Path,
) -> dict[str, Path]:
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    stem = f"{report.symbol}_{report.timeframe}_data_audit"
    json_path = destination / f"{stem}.json"
    csv_path = destination / f"{stem}.csv"
    sessions_path = destination / f"{stem}_sessions.csv"
    md_path = destination / f"{stem}.md"

    json_path.write_text(
        json.dumps(report.to_record(), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    pd.DataFrame([report.summary_record()]).to_csv(csv_path, index=False)
    pd.DataFrame([session.to_record() for session in report.session_details]).to_csv(
        sessions_path,
        index=False,
    )
    md_path.write_text(_build_markdown_report(report), encoding="utf-8")
    return {
        "json": json_path,
        "csv": csv_path,
        "sessions_csv": sessions_path,
        "markdown": md_path,
    }
