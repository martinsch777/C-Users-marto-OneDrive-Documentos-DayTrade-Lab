from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence
from zoneinfo import ZoneInfo

import pandas as pd

from src.data.loader import CANONICAL_COLUMNS
from src.data.sessions import EquitySessionCalendar
from src.timeframes import parse_timeframe_timedelta


DEFAULT_EVENT_STUDY_HORIZONS: tuple[str, ...] = (
    "5min",
    "15min",
    "30min",
    "60min",
    "session_close",
)
DEFAULT_EVENT_STUDY_TIMEFRAME = "1min"
MINUTE_HORIZONS: dict[str, pd.Timedelta] = {
    "5min": pd.Timedelta(minutes=5),
    "15min": pd.Timedelta(minutes=15),
    "30min": pd.Timedelta(minutes=30),
    "60min": pd.Timedelta(minutes=60),
}
SUPPORTED_GROUP_FIELDS = {
    "symbol",
    "year",
    "hypothesis_id",
    "variant_id",
    "expected_direction",
    "horizon",
}
SAFETY_FLAGS = {
    "live_trading": False,
    "broker_connected": False,
    "orders_sent": False,
    "paper_broker_enabled": False,
}


@dataclass(frozen=True)
class EventStudyEvent:
    event_id: str
    hypothesis_id: str
    variant_id: str
    symbol: str
    timestamp: pd.Timestamp
    session_date: str
    expected_direction: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EventStudyRunConfig:
    run_id: str
    hypothesis_id: str
    variant_id: str
    dataset_path: str
    manifest_path: str
    dataset_sha256: str
    requested_start: str
    requested_end: str
    timeframe: str = DEFAULT_EVENT_STUDY_TIMEFRAME
    horizons: tuple[str, ...] = DEFAULT_EVENT_STUDY_HORIZONS
    schema_version: int = 1
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    safety_flags: dict[str, bool] = field(default_factory=lambda: dict(SAFETY_FLAGS))

    def to_record(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "horizons": list(self.horizons),
        }


def _to_utc_timestamp(value: Any) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if pd.isna(timestamp):
        raise ValueError("Timestamp could not be parsed")
    if timestamp.tzinfo is None:
        raise ValueError("Event study timestamps must be timezone-aware")
    return timestamp.tz_convert("UTC")


def _normalize_frame(frame: pd.DataFrame) -> pd.DataFrame:
    required = set(CANONICAL_COLUMNS)
    if not required.issubset(frame.columns):
        missing = sorted(required.difference(frame.columns))
        raise ValueError(f"Missing OHLCV columns for event study: {missing}")
    data = frame.loc[:, CANONICAL_COLUMNS].copy()
    data["timestamp"] = [_to_utc_timestamp(value) for value in data["timestamp"]]
    if data["timestamp"].duplicated().any():
        raise ValueError("Event study dataset has duplicate timestamps")
    if not data["timestamp"].is_monotonic_increasing:
        raise ValueError("Event study dataset timestamps must be sorted ascending")
    for column in CANONICAL_COLUMNS[1:]:
        data[column] = pd.to_numeric(data[column], errors="raise")
    return data


def _normalize_events(events: Iterable[EventStudyEvent | dict[str, Any]]) -> list[EventStudyEvent]:
    normalized: list[EventStudyEvent] = []
    for raw in events:
        if isinstance(raw, EventStudyEvent):
            event = raw
        else:
            event = EventStudyEvent(**raw)
        direction = event.expected_direction
        if direction is not None and direction not in {-1, 0, 1}:
            raise ValueError(
                f"Event {event.event_id} has invalid expected_direction: {direction}"
            )
        normalized.append(
            EventStudyEvent(
                event_id=str(event.event_id),
                hypothesis_id=str(event.hypothesis_id),
                variant_id=str(event.variant_id),
                symbol=str(event.symbol).upper(),
                timestamp=_to_utc_timestamp(event.timestamp),
                session_date=str(event.session_date),
                expected_direction=direction,
                metadata=dict(event.metadata or {}),
            )
        )
    event_ids = [event.event_id for event in normalized]
    if len(event_ids) != len(set(event_ids)):
        raise ValueError("Event study events contain duplicate event_id values")
    return normalized


def _validate_horizons(horizons: Sequence[str]) -> tuple[str, ...]:
    values = tuple(str(item) for item in horizons)
    unsupported = sorted(set(values).difference(DEFAULT_EVENT_STUDY_HORIZONS))
    if unsupported:
        raise ValueError(
            "Unsupported event-study horizon(s): " + ", ".join(unsupported)
        )
    return values


def _session_date(timestamp: pd.Timestamp, calendar: EquitySessionCalendar) -> str:
    return timestamp.tz_convert(ZoneInfo(calendar.timezone)).date().isoformat()


def _validate_event(
    event: EventStudyEvent,
    timestamps: set[pd.Timestamp],
    calendar: EquitySessionCalendar,
) -> None:
    if event.timestamp not in timestamps:
        raise ValueError(
            f"Event {event.event_id} timestamp is outside the dataset: "
            f"{event.timestamp}"
        )
    if not calendar.contains(event.timestamp):
        raise ValueError(
            f"Event {event.event_id} timestamp is outside Regular Trading Hours: "
            f"{event.timestamp}"
        )
    actual_session_date = _session_date(event.timestamp, calendar)
    if event.session_date != actual_session_date:
        raise ValueError(
            f"Event {event.event_id} session_date {event.session_date!r} "
            f"does not match timestamp session {actual_session_date!r}"
        )


def _metadata_json(metadata: dict[str, Any]) -> str:
    return json.dumps(metadata, sort_keys=True, default=str)


def _event_result_record(
    *,
    event: EventStudyEvent,
    event_price: float,
    horizon: str,
    future_timestamp: pd.Timestamp | None,
    future_price: float | None,
    availability_status: str,
    missing_reason: str,
    expected_session_close_timestamp: pd.Timestamp | None = None,
) -> dict[str, Any]:
    raw_return = (
        future_price / event_price - 1.0
        if future_price is not None and event_price != 0
        else None
    )
    directional_return = (
        raw_return * event.expected_direction
        if raw_return is not None and event.expected_direction in {-1, 1}
        else None
    )
    analysis_return = directional_return if directional_return is not None else raw_return
    return {
        "event_id": event.event_id,
        "hypothesis_id": event.hypothesis_id,
        "variant_id": event.variant_id,
        "symbol": event.symbol,
        "timestamp": event.timestamp,
        "session_date": event.session_date,
        "year": event.timestamp.year,
        "expected_direction": event.expected_direction,
        "event_price": event_price,
        "future_timestamp": future_timestamp,
        "expected_session_close_timestamp": expected_session_close_timestamp,
        "future_price": future_price,
        "horizon": horizon,
        "raw_return": raw_return,
        "directional_return": directional_return,
        "analysis_return": analysis_return,
        "availability_status": availability_status,
        "missing_reason": missing_reason,
        "metadata": _metadata_json(event.metadata),
    }


def _future_for_minute_horizon(
    *,
    event: EventStudyEvent,
    horizon: str,
    close_by_timestamp: dict[pd.Timestamp, float],
    calendar: EquitySessionCalendar,
) -> tuple[pd.Timestamp | None, float | None, str, str]:
    future_timestamp = event.timestamp + MINUTE_HORIZONS[horizon]
    if _session_date(future_timestamp, calendar) != event.session_date:
        return future_timestamp, None, "missing", "horizon_crosses_session"
    if not calendar.contains(future_timestamp):
        return future_timestamp, None, "missing", "horizon_crosses_session"
    future_price = close_by_timestamp.get(future_timestamp)
    if future_price is None:
        return future_timestamp, None, "missing", "future_bar_missing"
    return future_timestamp, future_price, "available", ""


def _future_for_session_close(
    *,
    event: EventStudyEvent,
    close_by_timestamp: dict[pd.Timestamp, float],
    calendar: EquitySessionCalendar,
    timeframe: str,
) -> tuple[pd.Timestamp | None, float | None, str, str]:
    try:
        session_date = date.fromisoformat(event.session_date)
    except ValueError as exc:
        raise ValueError(
            f"Event {event.event_id} has invalid session_date: "
            f"{event.session_date!r}"
        ) from exc
    expected = calendar.expected_timestamps(
        session_date,
        session_date,
        timeframe,
    )
    if expected.empty:
        raise ValueError(
            f"Event {event.event_id} session {event.session_date!r} is not "
            "recognized by the event-study calendar"
        )
    expected_close_timestamp = expected[-1]
    future_price = close_by_timestamp.get(expected_close_timestamp)
    if future_price is None:
        return (
            expected_close_timestamp,
            None,
            "missing",
            "expected_session_close_bar_missing",
        )
    return expected_close_timestamp, future_price, "available", ""


def compute_event_study(
    frame: pd.DataFrame,
    events: Iterable[EventStudyEvent | dict[str, Any]],
    *,
    calendar: EquitySessionCalendar | None = None,
    timeframe: str = DEFAULT_EVENT_STUDY_TIMEFRAME,
    horizons: Sequence[str] = DEFAULT_EVENT_STUDY_HORIZONS,
) -> pd.DataFrame:
    data = _normalize_frame(frame)
    normalized_events = _normalize_events(events)
    parse_timeframe_timedelta(timeframe)
    selected_horizons = _validate_horizons(horizons)
    study_calendar = calendar or EquitySessionCalendar.from_config({"source": "us_equity"})
    timestamps = set(data["timestamp"])
    for event in normalized_events:
        _validate_event(event, timestamps, study_calendar)
    close_by_timestamp = {
        row["timestamp"]: float(row["close"])
        for _, row in data.iterrows()
    }
    data = data.assign(
        _session_date=[
            _session_date(timestamp, study_calendar) for timestamp in data["timestamp"]
        ]
    )

    records: list[dict[str, Any]] = []
    for event in normalized_events:
        event_price = close_by_timestamp[event.timestamp]
        for horizon in selected_horizons:
            expected_session_close_timestamp = None
            if horizon == "session_close":
                future_timestamp, future_price, status, reason = _future_for_session_close(
                    event=event,
                    close_by_timestamp=close_by_timestamp,
                    calendar=study_calendar,
                    timeframe=timeframe,
                )
                expected_session_close_timestamp = future_timestamp
            else:
                future_timestamp, future_price, status, reason = _future_for_minute_horizon(
                    event=event,
                    horizon=horizon,
                    close_by_timestamp=close_by_timestamp,
                    calendar=study_calendar,
                )
            records.append(
                _event_result_record(
                    event=event,
                    event_price=event_price,
                    horizon=horizon,
                    future_timestamp=future_timestamp,
                    future_price=future_price,
                    availability_status=status,
                    missing_reason=reason,
                    expected_session_close_timestamp=expected_session_close_timestamp,
                )
            )
    return pd.DataFrame(records)


def _aggregate_subset(subset: pd.DataFrame, return_column: str) -> dict[str, Any]:
    available = subset.loc[
        (subset["availability_status"] == "available")
        & subset[return_column].notna(),
        return_column,
    ].astype(float)
    event_count = int(len(subset))
    available_count = int(len(available))
    missing_count = event_count - available_count
    if available_count == 0:
        return {
            "event_count": event_count,
            "available_count": available_count,
            "missing_count": missing_count,
            "mean_return": None,
            "median_return": None,
            "positive_rate": None,
            "standard_deviation": None,
            "standard_error": None,
            "confidence_interval_95_lower": None,
            "confidence_interval_95_upper": None,
            "minimum": None,
            "maximum": None,
        }
    mean = float(available.mean())
    standard_deviation = (
        float(available.std(ddof=1)) if available_count > 1 else 0.0
    )
    standard_error = (
        standard_deviation / (available_count ** 0.5)
        if available_count > 1
        else 0.0
    )
    return {
        "event_count": event_count,
        "available_count": available_count,
        "missing_count": missing_count,
        "mean_return": mean,
        "median_return": float(available.median()),
        "positive_rate": float((available > 0).mean()),
        "standard_deviation": standard_deviation,
        "standard_error": standard_error,
        "confidence_interval_95_lower": mean - 1.96 * standard_error,
        "confidence_interval_95_upper": mean + 1.96 * standard_error,
        "minimum": float(available.min()),
        "maximum": float(available.max()),
    }


def aggregate_event_results(
    event_results: pd.DataFrame,
    *,
    group_by: Sequence[str] = ("horizon",),
    return_column: str = "analysis_return",
) -> pd.DataFrame:
    if return_column not in event_results.columns:
        raise ValueError(f"Return column not found: {return_column}")
    grouping = tuple(group_by)
    unsupported = sorted(set(grouping).difference(SUPPORTED_GROUP_FIELDS))
    if unsupported:
        raise ValueError("Unsupported group field(s): " + ", ".join(unsupported))
    if not grouping:
        return pd.DataFrame([_aggregate_subset(event_results, return_column)])
    records: list[dict[str, Any]] = []
    grouped = event_results.groupby(list(grouping), dropna=False, sort=True)
    for keys, subset in grouped:
        if not isinstance(keys, tuple):
            keys = (keys,)
        record = dict(zip(grouping, keys))
        record.update(_aggregate_subset(subset, return_column))
        records.append(record)
    return pd.DataFrame(records)


def _serializable_event_results(frame: pd.DataFrame) -> pd.DataFrame:
    serializable = frame.copy()
    for column in (
        "timestamp",
        "future_timestamp",
        "expected_session_close_timestamp",
    ):
        if column not in serializable.columns:
            continue
        serializable[column] = serializable[column].map(
            lambda value: value.isoformat() if pd.notna(value) else ""
        )
    return serializable


def write_event_study_outputs(
    output_dir: str | Path,
    config: EventStudyRunConfig,
    event_results: pd.DataFrame,
    aggregate_results: pd.DataFrame,
) -> dict[str, Path]:
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    config_path = destination / "run_config.json"
    events_path = destination / "event_results.csv"
    aggregates_path = destination / "aggregate_results.csv"
    config_payload = {
        **config.to_record(),
        "event_count": int(event_results["event_id"].nunique())
        if not event_results.empty
        else 0,
        "result_row_count": int(len(event_results)),
        "aggregate_row_count": int(len(aggregate_results)),
        "safety_flags": dict(SAFETY_FLAGS),
        "confidence_interval_method": (
            "normal_approximation_mean_plus_minus_1.96_standard_error; "
            "does_not_assume_perfect_event_independence"
        ),
    }
    config_path.write_text(
        json.dumps(config_payload, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    _serializable_event_results(event_results).to_csv(events_path, index=False)
    aggregate_results.to_csv(aggregates_path, index=False)
    return {
        "config": config_path,
        "events": events_path,
        "aggregates": aggregates_path,
    }
