from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, time
from pathlib import Path
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

import pandas as pd

from src.data.loader import CANONICAL_COLUMNS
from src.data.sessions import EquitySessionCalendar
from src.research.event_study import (
    DEFAULT_EVENT_STUDY_HORIZONS,
    EventStudyEvent,
)
from src.timeframes import parse_timeframe_timedelta


DEFAULT_HYP_GAP_CONFIG_PATH = Path("configs/research/hypotheses/HYP-GAP.yaml")
HYPOTHESIS_ID = "HYP-GAP"
PREREGISTERED_STATUS = "PREREGISTERED"
PREREGISTERED_TIMEFRAME = "1min"
PREREGISTERED_TIMEZONE = "America/New_York"
CONFIRMATION_TIME = time(9, 45)
WARMUP_SESSIONS = 20
SAFETY_FLAGS = {
    "live_trading": False,
    "broker_connected": False,
    "orders_sent": False,
    "paper_broker_enabled": False,
}
EXPECTED_VARIANT_IDS = tuple(f"HYP-GAP-{index:02d}" for index in range(1, 7))
EXPECTED_VARIANTS: dict[str, dict[str, Any]] = {
    "HYP-GAP-01": {
        "family": "continuation",
        "expected_direction": "gap_direction",
        "threshold": {"normalized_gap_min": 0.50},
    },
    "HYP-GAP-02": {
        "family": "continuation",
        "expected_direction": "gap_direction",
        "threshold": {"normalized_gap_min": 0.35},
    },
    "HYP-GAP-03": {
        "family": "continuation",
        "expected_direction": "gap_direction",
        "threshold": {
            "normalized_gap_min": 0.35,
            "opening_move_atr_min": 0.10,
        },
    },
    "HYP-GAP-04": {
        "family": "reversal",
        "expected_direction": "-gap_direction",
        "threshold": {"normalized_gap_min": 0.50},
    },
    "HYP-GAP-05": {
        "family": "reversal",
        "expected_direction": "-gap_direction",
        "threshold": {"normalized_gap_min": 0.35},
    },
    "HYP-GAP-06": {
        "family": "reversal",
        "expected_direction": "-gap_direction",
        "threshold": {
            "normalized_gap_min": 0.35,
            "relative_volume_0930_0945_max": 0.90,
        },
    },
}
INELIGIBLE_REASONS = (
    "missing_previous_session",
    "insufficient_atr_warmup",
    "insufficient_relative_volume_warmup",
    "opening_bar_missing",
    "confirmation_bar_missing",
    "incomplete_opening_window",
    "excluded_session",
    "invalid_gap_direction",
    "missing_required_variable",
)


@dataclass(frozen=True)
class HypGapVariant:
    variant_id: str
    name: str
    family: str
    threshold: dict[str, float]
    expected_direction: str
    event_conditions: tuple[str, ...]


@dataclass(frozen=True)
class HypGapPreregistration:
    schema_version: int
    hypothesis_id: str
    status: str
    symbols: tuple[str, ...]
    timeframe: str
    timezone: str
    discovery_start: date
    discovery_end: date
    confirmation_time: time
    horizons: tuple[str, ...]
    variants: tuple[HypGapVariant, ...]
    safety_flags: dict[str, bool]
    config_hash: str
    source_path: str


@dataclass(frozen=True)
class HypGapSessionVariables:
    symbol: str
    session_date: str
    previous_session_date: str
    previous_session_close: float
    current_session_open: float
    gap_return: float
    gap_direction: int
    prior_atr: float
    normalized_gap: float
    opening_return: float
    opening_move_atr: float
    confirmation_close: float
    confirmation_vwap: float
    volume_0930_0945: float
    relative_volume_0930_0945: float
    confirmation_timestamp: pd.Timestamp


@dataclass(frozen=True)
class _SessionMetric:
    session_date: str
    close: float
    high: float
    low: float
    volume_0930_0945: float
    true_range: float | None


@dataclass(frozen=True)
class HypGapDetectionSummary:
    total_sessions_examined: int
    eligible_sessions: int
    ineligible_sessions: int
    ineligible_reasons: dict[str, int]
    events_by_variant: dict[str, int]
    events_by_symbol: dict[str, int]
    first_date_examined: str
    last_date_examined: str
    config_hash: str
    safety_flags: dict[str, bool]


@dataclass(frozen=True)
class HypGapDetectionResult:
    events: tuple[EventStudyEvent, ...]
    summary: HypGapDetectionSummary
    session_variables: tuple[HypGapSessionVariables, ...] = field(default_factory=tuple)


def _parse_scalar(value: str) -> Any:
    text = value.strip()
    if text == "":
        return ""
    if text[0:1] in {'"', "'"} and text[-1:] == text[0]:
        return text[1:-1]
    if text == "true":
        return True
    if text == "false":
        return False
    if text == "null":
        return None
    if text.startswith("[") and text.endswith("]"):
        inner = text[1:-1].strip()
        if not inner:
            return []
        return [_parse_scalar(item.strip()) for item in inner.split(",")]
    try:
        if "." not in text:
            return int(text)
        return float(text)
    except ValueError:
        return text


def _line_indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _split_key_value(text: str) -> tuple[str, str]:
    key, separator, value = text.partition(":")
    if not separator:
        raise ValueError(f"Invalid YAML line: {text!r}")
    return key.strip(), value.strip()


def _parse_yaml_subset_lines(lines: list[str], index: int, indent: int) -> tuple[Any, int]:
    if index >= len(lines):
        return {}, index
    current_indent = _line_indent(lines[index])
    if current_indent < indent:
        return {}, index
    if lines[index].lstrip().startswith("- "):
        values: list[Any] = []
        while index < len(lines) and _line_indent(lines[index]) == indent:
            stripped = lines[index].strip()
            if not stripped.startswith("- "):
                break
            item_text = stripped[2:].strip()
            index += 1
            if not item_text:
                nested, index = _parse_yaml_subset_lines(lines, index, indent + 2)
                values.append(nested)
                continue
            if ":" in item_text:
                key, value = _split_key_value(item_text)
                item: dict[str, Any] = {}
                if value:
                    item[key] = _parse_scalar(value)
                else:
                    nested, index = _parse_yaml_subset_lines(lines, index, indent + 2)
                    item[key] = nested
                while index < len(lines) and _line_indent(lines[index]) > indent:
                    nested_indent = _line_indent(lines[index])
                    nested, index = _parse_yaml_subset_lines(lines, index, nested_indent)
                    if isinstance(nested, dict):
                        item.update(nested)
                    else:
                        raise ValueError("List item continuation must be a mapping")
                values.append(item)
            else:
                values.append(_parse_scalar(item_text))
        return values, index
    values: dict[str, Any] = {}
    while index < len(lines) and _line_indent(lines[index]) == indent:
        stripped = lines[index].strip()
        if stripped.startswith("- "):
            break
        key, value = _split_key_value(stripped)
        index += 1
        if value:
            values[key] = _parse_scalar(value)
        else:
            nested, index = _parse_yaml_subset_lines(lines, index, indent + 2)
            values[key] = nested
    return values, index


def _load_yaml_mapping(text: str, path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = None
    if payload is None:
        try:
            import yaml  # type: ignore
        except ModuleNotFoundError:
            lines = [
                line.rstrip()
                for line in text.splitlines()
                if line.strip() and not line.lstrip().startswith("#")
            ]
            payload, index = _parse_yaml_subset_lines(lines, 0, 0)
            if index != len(lines):
                raise ValueError(f"Could not parse complete YAML file: {path}")
        else:
            payload = yaml.safe_load(text)
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return payload


def _read_yaml(path: Path) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    payload = _load_yaml_mapping(raw.decode("utf-8"), path)
    return payload, hashlib.sha256(raw).hexdigest()


def _require_equal(actual: Any, expected: Any, field: str) -> None:
    if actual != expected:
        raise ValueError(
            f"HYP-GAP preregistration field {field} is {actual!r}; "
            f"expected {expected!r}"
        )


def _require_safety_false(flags: Mapping[str, Any], field: str) -> None:
    for key, expected in SAFETY_FLAGS.items():
        if flags.get(key) is not expected:
            raise ValueError(f"{field}.{key} must be false")


def _date_from_mapping(values: Mapping[str, Any], key: str) -> date:
    return date.fromisoformat(str(values[key]))


def _validate_variant(record: Mapping[str, Any]) -> HypGapVariant:
    variant_id = str(record.get("variant_id"))
    if variant_id not in EXPECTED_VARIANTS:
        raise ValueError(f"Unexpected HYP-GAP variant_id: {variant_id}")
    expected = EXPECTED_VARIANTS[variant_id]
    _require_equal(record.get("hypothesis_id"), HYPOTHESIS_ID, f"{variant_id}.hypothesis_id")
    _require_equal(record.get("family"), expected["family"], f"{variant_id}.family")
    _require_equal(
        record.get("expected_direction"),
        expected["expected_direction"],
        f"{variant_id}.expected_direction",
    )
    threshold = record.get("threshold")
    if not isinstance(threshold, dict):
        raise ValueError(f"{variant_id}.threshold must be present")
    actual_threshold = {str(key): float(value) for key, value in threshold.items()}
    if actual_threshold != expected["threshold"]:
        raise ValueError(
            f"{variant_id}.threshold is {actual_threshold!r}; "
            f"expected {expected['threshold']!r}"
        )
    _require_equal(
        record.get("confirmation_timestamp"),
        "09:45 America/New_York",
        f"{variant_id}.confirmation_timestamp",
    )
    _require_equal(
        tuple(record.get("horizons", ())),
        DEFAULT_EVENT_STUDY_HORIZONS,
        f"{variant_id}.horizons",
    )
    _require_equal(tuple(record.get("symbols", ())), ("QQQ", "SPY"), f"{variant_id}.symbols")
    period = record.get("discovery_period")
    if not isinstance(period, dict):
        raise ValueError(f"{variant_id}.discovery_period must be present")
    _require_equal(period.get("start"), "2022-01-01", f"{variant_id}.discovery_period.start")
    _require_equal(period.get("end"), "2024-12-31", f"{variant_id}.discovery_period.end")
    _require_equal(record.get("initial_status"), PREREGISTERED_STATUS, f"{variant_id}.initial_status")
    safety = record.get("safety_flags")
    if not isinstance(safety, dict):
        raise ValueError(f"{variant_id}.safety_flags must be present")
    _require_safety_false(safety, f"{variant_id}.safety_flags")
    conditions = record.get("event_conditions")
    if not isinstance(conditions, list) or not conditions:
        raise ValueError(f"{variant_id}.event_conditions must be present")
    return HypGapVariant(
        variant_id=variant_id,
        name=str(record.get("name", "")),
        family=str(record["family"]),
        threshold=actual_threshold,
        expected_direction=str(record["expected_direction"]),
        event_conditions=tuple(str(item) for item in conditions),
    )


def load_hyp_gap_preregistration(
    path: str | Path = DEFAULT_HYP_GAP_CONFIG_PATH,
) -> HypGapPreregistration:
    source = Path(path)
    payload, config_hash = _read_yaml(source)
    _require_equal(payload.get("schema_version"), 1, "schema_version")
    _require_equal(payload.get("hypothesis_id"), HYPOTHESIS_ID, "hypothesis_id")
    _require_equal(payload.get("status"), PREREGISTERED_STATUS, "status")
    _require_equal(payload.get("timeframe"), PREREGISTERED_TIMEFRAME, "timeframe")
    _require_equal(payload.get("timezone"), PREREGISTERED_TIMEZONE, "timezone")
    _require_equal(tuple(payload.get("symbols", ())), ("QQQ", "SPY"), "symbols")
    _require_equal(tuple(payload.get("horizons", ())), DEFAULT_EVENT_STUDY_HORIZONS, "horizons")
    safety = payload.get("safety_flags")
    if not isinstance(safety, dict):
        raise ValueError("safety_flags must be present")
    _require_safety_false(safety, "safety_flags")
    confirmation = payload.get("confirmation")
    if not isinstance(confirmation, dict):
        raise ValueError("confirmation must be present")
    _require_equal(confirmation.get("timestamp_local"), "09:45", "confirmation.timestamp_local")
    splits = payload.get("splits")
    if not isinstance(splits, dict):
        raise ValueError("splits must be present")
    discovery = splits.get("discovery")
    validation = splits.get("validation")
    holdout = splits.get("final_holdout")
    if not all(isinstance(item, dict) for item in (discovery, validation, holdout)):
        raise ValueError("discovery, validation and final_holdout splits must be present")
    if date.fromisoformat(str(discovery["end"])) >= date.fromisoformat(str(validation["start"])):
        raise ValueError("discovery split must not include validation")
    if date.fromisoformat(str(discovery["end"])) >= date.fromisoformat(str(holdout["start"])):
        raise ValueError("discovery split must not include final holdout")
    _require_equal(discovery.get("start"), "2022-01-01", "splits.discovery.start")
    _require_equal(discovery.get("end"), "2024-12-31", "splits.discovery.end")
    _require_equal(validation.get("status"), "closed", "splits.validation.status")
    _require_equal(holdout.get("status"), "closed", "splits.final_holdout.status")
    variants_raw = payload.get("variants")
    if not isinstance(variants_raw, list):
        raise ValueError("variants must be present")
    if len(variants_raw) != 6:
        raise ValueError("HYP-GAP preregistration must contain exactly six variants")
    raw_ids = [str(record.get("variant_id")) for record in variants_raw]
    if len(raw_ids) != len(set(raw_ids)):
        raise ValueError("HYP-GAP variant IDs must be unique")
    variants = tuple(_validate_variant(record) for record in variants_raw)
    ids = [variant.variant_id for variant in variants]
    _require_equal(tuple(ids), EXPECTED_VARIANT_IDS, "variants.variant_id")
    family_counts = Counter(variant.family for variant in variants)
    _require_equal(family_counts["continuation"], 3, "variant_budget.continuation_variants")
    _require_equal(family_counts["reversal"], 3, "variant_budget.reversal_variants")
    return HypGapPreregistration(
        schema_version=int(payload["schema_version"]),
        hypothesis_id=str(payload["hypothesis_id"]),
        status=str(payload["status"]),
        symbols=tuple(str(item) for item in payload["symbols"]),
        timeframe=str(payload["timeframe"]),
        timezone=str(payload["timezone"]),
        discovery_start=_date_from_mapping(discovery, "start"),
        discovery_end=_date_from_mapping(discovery, "end"),
        confirmation_time=CONFIRMATION_TIME,
        horizons=tuple(str(item) for item in payload["horizons"]),
        variants=variants,
        safety_flags={key: bool(value) for key, value in safety.items()},
        config_hash=config_hash,
        source_path=str(source),
    )


def _to_utc_timestamp(value: Any) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if pd.isna(timestamp):
        raise ValueError("Timestamp could not be parsed")
    if timestamp.tzinfo is None:
        raise ValueError("HYP-GAP timestamps must be timezone-aware")
    return timestamp.tz_convert("UTC")


def _normalize_input_frame(
    frame: pd.DataFrame,
    *,
    calendar: EquitySessionCalendar,
) -> pd.DataFrame:
    required = set(CANONICAL_COLUMNS)
    if not required.issubset(frame.columns):
        missing = sorted(required.difference(frame.columns))
        raise ValueError(f"Missing OHLCV columns for HYP-GAP detection: {missing}")
    data = frame.loc[:, CANONICAL_COLUMNS].copy()
    data["timestamp"] = [_to_utc_timestamp(value) for value in data["timestamp"]]
    if data["timestamp"].duplicated().any():
        raise ValueError("HYP-GAP dataset has duplicate timestamps")
    if not data["timestamp"].is_monotonic_increasing:
        raise ValueError("HYP-GAP dataset timestamps must be sorted ascending")
    for column in CANONICAL_COLUMNS[1:]:
        data[column] = pd.to_numeric(data[column], errors="raise")
    invalid_ohlc = (
        (data["high"] < data[["open", "close", "low"]].max(axis=1))
        | (data["low"] > data[["open", "close", "high"]].min(axis=1))
    )
    if invalid_ohlc.any():
        raise ValueError("HYP-GAP dataset contains invalid OHLC rows")
    if (data[["open", "high", "low", "close"]] <= 0).any().any():
        raise ValueError("HYP-GAP dataset contains nonpositive prices")
    if (data["volume"] < 0).any():
        raise ValueError("HYP-GAP dataset contains negative volume")
    outside = [timestamp for timestamp in data["timestamp"] if not calendar.contains(timestamp)]
    if outside:
        raise ValueError(f"HYP-GAP dataset contains timestamps outside RTH: {outside[0]}")
    return data


def _local_session_date(timestamp: pd.Timestamp, timezone: str) -> str:
    return timestamp.tz_convert(ZoneInfo(timezone)).date().isoformat()


def _local_timestamp(session_date: str, clock: time, timezone: str) -> pd.Timestamp:
    return pd.Timestamp(
        datetime.combine(date.fromisoformat(session_date), clock),
        tz=ZoneInfo(timezone),
    ).tz_convert("UTC")


def _expected_opening_timestamps(
    session_date: str,
    *,
    calendar: EquitySessionCalendar,
    timeframe: str,
) -> pd.DatetimeIndex:
    duration = parse_timeframe_timedelta(timeframe)
    local_zone = ZoneInfo(calendar.timezone)
    current_date = date.fromisoformat(session_date)
    local_open = pd.Timestamp(datetime.combine(current_date, calendar.regular_open), tz=local_zone)
    local_confirmation = pd.Timestamp(
        datetime.combine(current_date, CONFIRMATION_TIME),
        tz=local_zone,
    )
    return pd.date_range(local_open, local_confirmation, freq=duration).tz_convert("UTC")


def _required_session_timestamps(
    session_date: str,
    *,
    calendar: EquitySessionCalendar,
    timeframe: str,
) -> pd.DatetimeIndex:
    expected = calendar.expected_timestamps(
        date.fromisoformat(session_date),
        date.fromisoformat(session_date),
        timeframe,
    )
    if expected.empty:
        raise ValueError(f"HYP-GAP session {session_date} is not recognized by the calendar")
    return expected


def _has_all_timestamps(timestamps: set[pd.Timestamp], expected: Sequence[pd.Timestamp]) -> bool:
    return all(timestamp in timestamps for timestamp in expected)


def _session_rows(data: pd.DataFrame, session_date: str) -> pd.DataFrame:
    return data.loc[data["_session_date"] == session_date]


def _volume_weighted_typical_price(rows: pd.DataFrame) -> float:
    volume = rows["volume"].sum()
    if volume <= 0:
        raise ValueError("HYP-GAP VWAP requires positive cumulative volume")
    typical_price = (rows["high"] + rows["low"] + rows["close"]) / 3.0
    return float((typical_price * rows["volume"]).sum() / volume)


def _session_is_complete(
    session_date: str,
    *,
    timestamps: set[pd.Timestamp],
    calendar: EquitySessionCalendar,
    timeframe: str,
) -> bool:
    return _has_all_timestamps(
        timestamps,
        _required_session_timestamps(
            session_date,
            calendar=calendar,
            timeframe=timeframe,
        ),
    )


def _opening_window_status(
    session_date: str,
    *,
    timestamps: set[pd.Timestamp],
    calendar: EquitySessionCalendar,
    timeframe: str,
) -> str:
    open_timestamp = _local_timestamp(session_date, calendar.regular_open, calendar.timezone)
    confirmation_timestamp = _local_timestamp(session_date, CONFIRMATION_TIME, calendar.timezone)
    if open_timestamp not in timestamps:
        return "opening_bar_missing"
    if confirmation_timestamp not in timestamps:
        return "confirmation_bar_missing"
    opening = _expected_opening_timestamps(
        session_date,
        calendar=calendar,
        timeframe=timeframe,
    )
    if not _has_all_timestamps(timestamps, opening):
        return "incomplete_opening_window"
    return ""


def _build_prior_metric(
    session_date: str,
    *,
    data: pd.DataFrame,
    timestamps: set[pd.Timestamp],
    calendar: EquitySessionCalendar,
    timeframe: str,
    previous_close: float | None,
) -> _SessionMetric | None:
    if not _session_is_complete(
        session_date,
        timestamps=timestamps,
        calendar=calendar,
        timeframe=timeframe,
    ):
        return None
    rows = _session_rows(data, session_date)
    opening = _expected_opening_timestamps(
        session_date,
        calendar=calendar,
        timeframe=timeframe,
    )
    opening_rows = rows.loc[rows["timestamp"].isin(set(opening))]
    if len(opening_rows) != len(opening):
        return None
    high = float(rows["high"].max())
    low = float(rows["low"].min())
    close_timestamp = _required_session_timestamps(
        session_date,
        calendar=calendar,
        timeframe=timeframe,
    )[-1]
    close = float(rows.loc[rows["timestamp"] == close_timestamp, "close"].iloc[0])
    true_range = None
    if previous_close is not None:
        true_range = max(
            high - low,
            abs(high - previous_close),
            abs(low - previous_close),
        )
    return _SessionMetric(
        session_date=session_date,
        close=close,
        high=high,
        low=low,
        volume_0930_0945=float(opening_rows["volume"].sum()),
        true_range=true_range,
    )


def _on_gap_side(value: float, reference: float, gap_direction: int) -> bool:
    return value > reference if gap_direction == 1 else value < reference


def _opposite_gap_side(value: float, reference: float, gap_direction: int) -> bool:
    return value < reference if gap_direction == 1 else value > reference


def _same_sign(value: float, direction: int) -> bool:
    return value * direction > 0


def _opposite_sign(value: float, direction: int) -> bool:
    return value * direction < 0


def _evaluate_variant(
    variant: HypGapVariant,
    variables: HypGapSessionVariables,
) -> tuple[bool, dict[str, bool]]:
    threshold = variant.threshold
    conditions: dict[str, bool] = {}
    if variant.variant_id == "HYP-GAP-01":
        conditions = {
            "normalized_gap >= 0.50": variables.normalized_gap >= threshold["normalized_gap_min"],
            "gap_direction != 0": variables.gap_direction != 0,
            "confirmation_close_remains_on_gap_side_of_previous_session_close": _on_gap_side(
                variables.confirmation_close,
                variables.previous_session_close,
                variables.gap_direction,
            ),
        }
    elif variant.variant_id == "HYP-GAP-02":
        conditions = {
            "normalized_gap >= 0.35": variables.normalized_gap >= threshold["normalized_gap_min"],
            "confirmation_close_remains_on_gap_side_of_previous_session_close": _on_gap_side(
                variables.confirmation_close,
                variables.previous_session_close,
                variables.gap_direction,
            ),
            "confirmation_close_is_on_gap_side_of_confirmation_vwap": _on_gap_side(
                variables.confirmation_close,
                variables.confirmation_vwap,
                variables.gap_direction,
            ),
        }
    elif variant.variant_id == "HYP-GAP-03":
        conditions = {
            "normalized_gap >= 0.35": variables.normalized_gap >= threshold["normalized_gap_min"],
            "open_to_confirmation_return_has_same_sign_as_gap_direction": _same_sign(
                variables.opening_return,
                variables.gap_direction,
            ),
            "opening_move_atr >= 0.10": variables.opening_move_atr >= threshold["opening_move_atr_min"],
        }
    elif variant.variant_id == "HYP-GAP-04":
        conditions = {
            "normalized_gap >= 0.50": variables.normalized_gap >= threshold["normalized_gap_min"],
            "gap_direction != 0": variables.gap_direction != 0,
            "confirmation_close_is_on_opposite_side_of_previous_session_close_from_gap": _opposite_gap_side(
                variables.confirmation_close,
                variables.previous_session_close,
                variables.gap_direction,
            ),
        }
    elif variant.variant_id == "HYP-GAP-05":
        conditions = {
            "normalized_gap >= 0.35": variables.normalized_gap >= threshold["normalized_gap_min"],
            "open_to_confirmation_return_has_opposite_sign_from_gap_direction": _opposite_sign(
                variables.opening_return,
                variables.gap_direction,
            ),
            "confirmation_close_is_on_opposite_side_of_confirmation_vwap_from_gap": _opposite_gap_side(
                variables.confirmation_close,
                variables.confirmation_vwap,
                variables.gap_direction,
            ),
        }
    elif variant.variant_id == "HYP-GAP-06":
        conditions = {
            "normalized_gap >= 0.35": variables.normalized_gap >= threshold["normalized_gap_min"],
            "open_to_confirmation_return_has_opposite_sign_from_gap_direction": _opposite_sign(
                variables.opening_return,
                variables.gap_direction,
            ),
            "relative_volume_0930_0945 <= 0.90": variables.relative_volume_0930_0945
            <= threshold["relative_volume_0930_0945_max"],
        }
    else:
        raise ValueError(f"Unsupported HYP-GAP variant: {variant.variant_id}")
    return all(conditions.values()), conditions


def _event_metadata(
    variables: HypGapSessionVariables,
    *,
    variant: HypGapVariant,
    conditions: Mapping[str, bool],
    preregistration: HypGapPreregistration,
) -> dict[str, Any]:
    return {
        "gap_return": variables.gap_return,
        "gap_direction": variables.gap_direction,
        "previous_session_date": variables.previous_session_date,
        "previous_session_close": variables.previous_session_close,
        "current_session_open": variables.current_session_open,
        "normalized_gap": variables.normalized_gap,
        "prior_atr": variables.prior_atr,
        "opening_return": variables.opening_return,
        "opening_move_atr": variables.opening_move_atr,
        "confirmation_close": variables.confirmation_close,
        "confirmation_vwap": variables.confirmation_vwap,
        "vwap_price_convention": "bar_typical_price_volume_weighted",
        "opening_window": "09:30_through_09:45_inclusive_bar_opens",
        "relative_volume_0930_0945": variables.relative_volume_0930_0945,
        "variant_conditions_evaluated": dict(conditions),
        "config_schema_version": preregistration.schema_version,
        "config_hash": preregistration.config_hash,
        "safety_flags": dict(SAFETY_FLAGS),
    }


def _build_session_variables(
    *,
    symbol: str,
    session_date: str,
    data: pd.DataFrame,
    timestamps: set[pd.Timestamp],
    history: Sequence[_SessionMetric],
    preregistration: HypGapPreregistration,
    calendar: EquitySessionCalendar,
    timeframe: str,
) -> tuple[HypGapSessionVariables | None, str]:
    opening_status = _opening_window_status(
        session_date,
        timestamps=timestamps,
        calendar=calendar,
        timeframe=timeframe,
    )
    if opening_status:
        return None, opening_status
    if not history:
        return None, "missing_previous_session"
    previous_session = history[-1]
    atr_values = [metric.true_range for metric in history if metric.true_range is not None]
    if len(atr_values) < WARMUP_SESSIONS:
        return None, "insufficient_atr_warmup"
    volume_values = [metric.volume_0930_0945 for metric in history]
    if len(volume_values) < WARMUP_SESSIONS:
        return None, "insufficient_relative_volume_warmup"
    current_rows = _session_rows(data, session_date)
    opening = _expected_opening_timestamps(
        session_date,
        calendar=calendar,
        timeframe=timeframe,
    )
    opening_rows = current_rows.loc[current_rows["timestamp"].isin(set(opening))]
    if len(opening_rows) != len(opening):
        return None, "incomplete_opening_window"
    open_timestamp = _local_timestamp(session_date, calendar.regular_open, calendar.timezone)
    confirmation_timestamp = _local_timestamp(
        session_date,
        preregistration.confirmation_time,
        calendar.timezone,
    )
    current_open = float(current_rows.loc[current_rows["timestamp"] == open_timestamp, "open"].iloc[0])
    confirmation_close = float(
        current_rows.loc[current_rows["timestamp"] == confirmation_timestamp, "close"].iloc[0]
    )
    previous_close = previous_session.close
    gap_return = current_open / previous_close - 1.0
    if gap_return > 0:
        gap_direction = 1
    elif gap_return < 0:
        gap_direction = -1
    else:
        return None, "invalid_gap_direction"
    prior_atr = float(pd.Series(atr_values[-WARMUP_SESSIONS:]).mean())
    if prior_atr <= 0:
        return None, "missing_required_variable"
    normalized_gap = abs(current_open - previous_close) / prior_atr
    opening_return = confirmation_close / current_open - 1.0
    opening_move_atr = abs(confirmation_close - current_open) / prior_atr
    current_volume = float(opening_rows["volume"].sum())
    median_volume = float(pd.Series(volume_values[-WARMUP_SESSIONS:]).median())
    if median_volume <= 0:
        return None, "missing_required_variable"
    return (
        HypGapSessionVariables(
            symbol=symbol,
            session_date=session_date,
            previous_session_date=previous_session.session_date,
            previous_session_close=previous_close,
            current_session_open=current_open,
            gap_return=gap_return,
            gap_direction=gap_direction,
            prior_atr=prior_atr,
            normalized_gap=normalized_gap,
            opening_return=opening_return,
            opening_move_atr=opening_move_atr,
            confirmation_close=confirmation_close,
            confirmation_vwap=_volume_weighted_typical_price(opening_rows),
            volume_0930_0945=current_volume,
            relative_volume_0930_0945=current_volume / median_volume,
            confirmation_timestamp=confirmation_timestamp,
        ),
        "",
    )


def detect_hyp_gap_events(
    frame: pd.DataFrame,
    *,
    symbol: str,
    timeframe: str,
    start_date: str | date,
    end_date: str | date,
    event_start_date: str | date | None = None,
    calendar: EquitySessionCalendar | None = None,
    excluded_session_dates: set[str] | None = None,
    config_path: str | Path = DEFAULT_HYP_GAP_CONFIG_PATH,
) -> HypGapDetectionResult:
    preregistration = load_hyp_gap_preregistration(config_path)
    wanted_symbol = str(symbol).upper()
    if wanted_symbol not in preregistration.symbols:
        raise ValueError(f"Symbol {wanted_symbol!r} is not preregistered for HYP-GAP")
    if str(timeframe) != preregistration.timeframe:
        raise ValueError(
            f"HYP-GAP timeframe must be {preregistration.timeframe!r}; "
            f"got {timeframe!r}"
        )
    parse_timeframe_timedelta(timeframe)
    requested_start = date.fromisoformat(str(start_date))
    requested_end = date.fromisoformat(str(end_date))
    effective_event_start = (
        date.fromisoformat(str(event_start_date))
        if event_start_date is not None
        else requested_start
    )
    if requested_start < preregistration.discovery_start:
        raise ValueError("HYP-GAP detection request starts before discovery")
    if requested_end > preregistration.discovery_end:
        raise ValueError("HYP-GAP detection request must not open validation or holdout")
    if requested_start > requested_end:
        raise ValueError("HYP-GAP detection start_date must be on or before end_date")
    if effective_event_start < requested_start or effective_event_start > requested_end:
        raise ValueError("HYP-GAP event_start_date must be inside the detection range")
    study_calendar = calendar or EquitySessionCalendar.from_config({"source": "us_equity"})
    if study_calendar.timezone != preregistration.timezone:
        raise ValueError(
            f"HYP-GAP calendar timezone must be {preregistration.timezone!r}; "
            f"got {study_calendar.timezone!r}"
        )
    data = _normalize_input_frame(frame, calendar=study_calendar)
    data = data.assign(
        _session_date=[
            _local_session_date(timestamp, study_calendar.timezone)
            for timestamp in data["timestamp"]
        ]
    )
    timestamps = set(data["timestamp"])
    excluded = {str(item) for item in (excluded_session_dates or set())}
    session_dates = [
        item.date().isoformat()
        for item in pd.date_range(requested_start, requested_end, freq="D")
        if study_calendar.session_close(item.date()) is not None
    ]
    present_sessions = set(data["_session_date"])
    ineligible_reasons: Counter[str] = Counter()
    events: list[EventStudyEvent] = []
    variables_by_session: list[HypGapSessionVariables] = []
    history: list[_SessionMetric] = []
    previous_approved_close: float | None = None
    eligible_session_keys: set[str] = set()

    for session_date in session_dates:
        is_event_candidate = date.fromisoformat(session_date) >= effective_event_start
        session_present = session_date in present_sessions
        session_excluded = session_date in excluded
        if is_event_candidate and session_present and not session_excluded:
            variables, reason = _build_session_variables(
                symbol=wanted_symbol,
                session_date=session_date,
                data=data,
                timestamps=timestamps,
                history=history,
                preregistration=preregistration,
                calendar=study_calendar,
                timeframe=timeframe,
            )
            if variables is None:
                ineligible_reasons[reason] += 1
            else:
                eligible_session_keys.add(session_date)
                variables_by_session.append(variables)
                for variant in preregistration.variants:
                    matched, conditions = _evaluate_variant(variant, variables)
                    if not matched:
                        continue
                    expected_direction = (
                        variables.gap_direction
                        if variant.family == "continuation"
                        else -variables.gap_direction
                    )
                    events.append(
                        EventStudyEvent(
                            event_id=(
                                f"{preregistration.hypothesis_id}:"
                                f"{variant.variant_id}:{wanted_symbol}:{session_date}"
                            ),
                            hypothesis_id=preregistration.hypothesis_id,
                            variant_id=variant.variant_id,
                            symbol=wanted_symbol,
                            timestamp=variables.confirmation_timestamp,
                            session_date=session_date,
                            expected_direction=expected_direction,
                            metadata=_event_metadata(
                                variables,
                                variant=variant,
                                conditions=conditions,
                                preregistration=preregistration,
                            ),
                        )
                    )
        elif is_event_candidate and session_excluded:
            ineligible_reasons["excluded_session"] += 1
        elif is_event_candidate and not session_present:
            ineligible_reasons["missing_required_variable"] += 1

        if session_present and not session_excluded:
            metric = _build_prior_metric(
                session_date,
                data=data,
                timestamps=timestamps,
                calendar=study_calendar,
                timeframe=timeframe,
                previous_close=previous_approved_close,
            )
            if metric is not None:
                history.append(metric)
                previous_approved_close = metric.close

    events.sort(key=lambda item: (item.session_date, item.symbol, item.variant_id))
    events_by_variant = {variant_id: 0 for variant_id in EXPECTED_VARIANT_IDS}
    events_by_variant.update(Counter(event.variant_id for event in events))
    events_by_symbol = {wanted_symbol: len(events)}
    for reason in INELIGIBLE_REASONS:
        ineligible_reasons.setdefault(reason, 0)
    summary = HypGapDetectionSummary(
        total_sessions_examined=sum(
            date.fromisoformat(item) >= effective_event_start for item in session_dates
        ),
        eligible_sessions=len(eligible_session_keys),
        ineligible_sessions=sum(
            date.fromisoformat(item) >= effective_event_start for item in session_dates
        )
        - len(eligible_session_keys),
        ineligible_reasons=dict(sorted(ineligible_reasons.items())),
        events_by_variant=dict(sorted(events_by_variant.items())),
        events_by_symbol=events_by_symbol,
        first_date_examined=requested_start.isoformat(),
        last_date_examined=requested_end.isoformat(),
        config_hash=preregistration.config_hash,
        safety_flags=dict(SAFETY_FLAGS),
    )
    return HypGapDetectionResult(
        events=tuple(events),
        summary=summary,
        session_variables=tuple(variables_by_session),
    )
