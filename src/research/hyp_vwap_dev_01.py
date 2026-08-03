"""Pure methodology for HYP-VWAP-DEV-01.

The module contains no filesystem, network, broker, or process access.  Inputs
are explicit mappings and synthetic/data frames; every selection is causal and
deterministic under the frozen preregistration.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time
from enum import Enum
import hashlib
import json
from math import isfinite
from typing import Any, Callable, Mapping, Sequence

import numpy as np
import pandas as pd


HYPOTHESIS_ID = "HYP-VWAP-DEV-01"
CONCEPTUAL_DESIGN_FREEZE_COMMIT = "5a0c3dee3af99093fb5ff5eb2ab641767d1e086f"
CLARIFICATION_FREEZE_COMMIT = "9d2bbf721c70da7a4b02df49d9973cffc77c09f6"
PRIOR_PREREGISTRATION_FREEZE_COMMIT = "6fbd8f09b279c0b83d31602c7c75a42787c70b42"
ACTIVE_AMENDMENT_FREEZE_COMMIT = "bc51e384d015ab258fa8b21a553bc2e7457d9a9d"
EXPECTED_CANONICAL_HASH = "8420c66ffb97da893a9dcd3ebbc4903af116a4104891204397f554a0d12118eb"
AMENDMENT_ID = "HYP-VWAP-DEV-01-AMD-01"
SYMBOLS = ("QQQ", "SPY")
TIMEZONE = "America/New_York"
TAU = 0.005
PRIMARY_HORIZON = "30min"
HORIZONS = ("15min", "30min", "60min", "session_close")
BOOTSTRAP_REPLICATES = 10_000
BOOTSTRAP_SEED = 20_260_802
SUBSTANTIVE_CRITERION_IDS = (
    "INT-01", "INT-02", "INT-03", "INT-04", "INT-05", "INT-06",
    "INT-07", "INT-08", "SMP-01", "SMP-02", "SMP-03", "REP-01",
    "ECO-01", "ECO-02", "ECO-03", "ECO-04", "ECO-05", "INC-01",
    "UNC-01", "STB-01", "STB-02", "CON-01", "CON-02", "CON-03",
    "CON-04",
)
ALL_CRITERION_IDS = (*SUBSTANTIVE_CRITERION_IDS, "PRO-01")
_FIVE_MINUTES = pd.offsets.Minute(5)
_TEN_MINUTES = pd.offsets.Minute(10)
_SIXTY_FIVE_MINUTES = pd.offsets.Minute(65)
_HORIZON_OFFSETS = {
    "15min": pd.offsets.Minute(15),
    "30min": pd.offsets.Minute(30),
    "60min": pd.offsets.Minute(60),
}


class Direction(str, Enum):
    """Favorable return orientation fixed at the breach."""

    LONG = "long"
    SHORT = "short"


@dataclass(frozen=True)
class Candidate:
    """First eligible strict breach for one symbol-session."""

    symbol: str
    session_date: date
    breach_timestamp: pd.Timestamp
    direction: Direction
    deviation: float


@dataclass(frozen=True)
class Event:
    """Confirmed and executable event."""

    symbol: str
    session_date: date
    direction: Direction
    breach_timestamp: pd.Timestamp
    confirmation_timestamp: pd.Timestamp
    executable_timestamp: pd.Timestamp
    executable_price: float
    executable_vwap: float


@dataclass(frozen=True)
class EventDetection:
    """Terminal state for a symbol-session event scan."""

    candidate: Candidate | None
    event: Event | None
    status: str


@dataclass(frozen=True)
class ConcentrationResult:
    """Annual incremental concentration result."""

    value: float
    passed: bool
    status: str


@dataclass(frozen=True)
class LeaveOneOutResult:
    """Metrics after removing the single selected session date."""

    removed_session_date: date
    concentration: ConcentrationResult
    pooled_incremental_mean: float
    positive_incremental_years: int
    annual_event_counts: Mapping[int, int]
    passed: bool


@dataclass(frozen=True)
class GateResult:
    """Exact 25+1 gate classification."""

    criteria: Mapping[str, str]
    pro_01: bool
    classification: str
    validation_2025_unlocked: bool


def canonical_payload_bytes(mapping: Mapping[str, Any]) -> bytes:
    """Serialize every YAML field except the self-referential hash."""

    payload = dict(mapping)
    payload.pop("canonical_payload_sha256", None)
    return json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def canonical_payload_hash(mapping: Mapping[str, Any]) -> str:
    """Return the canonical SHA-256 for a preregistration mapping."""

    return hashlib.sha256(canonical_payload_bytes(mapping)).hexdigest()


def _require(mapping: Mapping[str, Any], key: str) -> Any:
    if key not in mapping:
        raise ValueError(f"CONFIG_SCHEMA_MISMATCH: missing {key}")
    return mapping[key]


def validate_frozen_config(mapping: Mapping[str, Any]) -> Mapping[str, Any]:
    """Validate identity, freezes, hash, state, criteria, and safety flags."""

    expected = {
        "hypothesis_id": HYPOTHESIS_ID,
        "conceptual_design_freeze_commit": CONCEPTUAL_DESIGN_FREEZE_COMMIT,
        "clarification_freeze_commit": CLARIFICATION_FREEZE_COMMIT,
        "amendment_id": AMENDMENT_ID,
        "amendment_parent_commit": "236ca1c6c83695962b51f4ed67b57898130d8f6e",
        "preregistration_frozen": True,
        "methodology_frozen": True,
        "human_approved": True,
        "implementation_allowed": True,
        "implementation_started": False,
        "historical_data_access_allowed": False,
        "discovery_execution_allowed": False,
        "decision_variants": 1,
    }
    for key, value in expected.items():
        if _require(mapping, key) != value:
            raise PermissionError(f"CONFIG_STATE_MISMATCH: {key}")
    if mapping.get("hypothesis_name") != mapping.get("name"):
        raise ValueError("CONFIG_SCHEMA_MISMATCH: hypothesis name alias")
    if mapping.get("research_type") != mapping.get("type"):
        raise ValueError("CONFIG_SCHEMA_MISMATCH: research type alias")
    actual_hash = canonical_payload_hash(mapping)
    if actual_hash != EXPECTED_CANONICAL_HASH:
        raise PermissionError("CANONICAL_HASH_MISMATCH")
    if mapping.get("canonical_payload_sha256") != EXPECTED_CANONICAL_HASH:
        raise PermissionError("CANONICAL_HASH_MISMATCH")
    safety = _require(mapping, "safety_flags")
    if not isinstance(safety, Mapping) or any(value is not False for value in safety.values()):
        raise PermissionError("SAFETY_FLAG_TRUE")
    criteria = _require(_require(mapping, "discovery_gate"), "criteria")
    ids = tuple(item.get("criterion_id") for item in criteria)
    if ids != ALL_CRITERION_IDS:
        raise ValueError("CRITERION_ID_ORDER_MISMATCH")
    pro = criteria[-1]
    if tuple(pro.get("input_criterion_ids", ())) != SUBSTANTIVE_CRITERION_IDS:
        raise ValueError("PRO_INPUT_SET_MISMATCH")
    if pro.get("self_inclusion") is not False or "PRO-01" in pro["input_criterion_ids"]:
        raise ValueError("PRO_DIRECT_RECURSION")
    loo = _require(_require(mapping, "concentration"), "leave_one_largest_session_out")
    loo_expected = {
        "selection_metric": "absolute_session_incremental_contribution",
        "aggregation_unit": "session_date",
        "cross_symbol_grouping": True,
        "remove_exactly_one_session_date": True,
        "row_order_independent": True,
        "random_tie_break": False,
        "numeric_tolerance": "none",
        "non_finite_policy": "fail",
    }
    if any(loo.get(key) != value for key, value in loo_expected.items()):
        raise ValueError("LOO_CONFIG_MISMATCH")
    if loo.get("selection_order") != {
        "primary": "absolute_contribution_descending",
        "tie_break": "session_date_ascending_oldest_first",
    }:
        raise ValueError("LOO_CONFIG_MISMATCH")
    return mapping


def typical_price(high: float, low: float, close: float) -> float:
    """Return `(high + low + close) / 3` for finite OHLC values."""

    values = np.asarray([high, low, close], dtype=float)
    if not np.isfinite(values).all() or high < low:
        raise ValueError("OHLC values must be finite and high >= low.")
    return float(values.mean())


def attach_causal_session_vwap(frame: pd.DataFrame) -> pd.DataFrame:
    """Attach completed-bar typical price and causal session VWAP."""

    required = {"session_date", "high", "low", "close", "volume"}
    if not required.issubset(frame.columns):
        raise ValueError(f"VWAP frame requires {sorted(required)}")
    work = frame.copy()
    order = [column for column in ("symbol", "session_date", "timestamp") if column in work]
    if order:
        work = work.sort_values(order, kind="stable").reset_index(drop=True)
    numeric = work[["high", "low", "close", "volume"]].apply(pd.to_numeric, errors="coerce")
    if not np.isfinite(numeric.to_numpy(dtype=float)).all():
        raise ValueError("VWAP inputs must be finite.")
    if (numeric["volume"] < 0).any() or (numeric["high"] < numeric["low"]).any():
        raise ValueError("VWAP volume must be non-negative and high >= low.")
    work[["high", "low", "close", "volume"]] = numeric
    work["typical_price"] = (work["high"] + work["low"] + work["close"]) / 3.0
    groups = [column for column in ("symbol", "session_date") if column in work]
    numerator = work["typical_price"] * work["volume"]
    work["cumulative_vwap_numerator"] = numerator.groupby(
        [work[column] for column in groups], sort=False
    ).cumsum()
    work["cumulative_volume"] = work["volume"].groupby(
        [work[column] for column in groups], sort=False
    ).cumsum()
    work["session_vwap"] = work["cumulative_vwap_numerator"].div(
        work["cumulative_volume"].where(work["cumulative_volume"] > 0)
    )
    return work


def signed_deviation(close: float, session_vwap: float) -> float:
    """Return signed proportional distance from causal session VWAP."""

    if not isfinite(close) or not isfinite(session_vwap) or close <= 0 or session_vwap <= 0:
        raise ValueError("Close and VWAP must be positive and finite.")
    return float(close / session_vwap - 1.0)


def breach_orientation(deviation: float, tau: float = TAU) -> Direction | None:
    """Classify a strict symmetric breach; equality is not a breach."""

    if not isfinite(deviation) or tau != TAU:
        raise ValueError("Deviation must be finite and tau must remain frozen.")
    if deviation < -tau:
        return Direction.LONG
    if deviation > tau:
        return Direction.SHORT
    return None


def breach_close_is_eligible(
    breach_close: pd.Timestamp,
    session_close: pd.Timestamp,
) -> bool:
    """Apply the inclusive 10:00 through close-minus-65-minute window."""

    breach = pd.Timestamp(breach_close)
    close = pd.Timestamp(session_close)
    if breach.tzinfo is None or close.tzinfo is None:
        raise ValueError("Window timestamps must be timezone-aware.")
    local = breach.tz_convert(TIMEZONE)
    return bool(local.time() >= time(10, 0) and breach <= close - _SIXTY_FIVE_MINUTES)


def evaluate_immediate_confirmation(
    direction: Direction,
    breach_deviation: float,
    confirmation_deviation: float,
) -> bool:
    """Evaluate only the immediate completed bar after a breach."""

    if not isfinite(breach_deviation) or not isfinite(confirmation_deviation):
        return False
    if direction is Direction.LONG:
        same_side = breach_deviation < 0 and confirmation_deviation < 0
    else:
        same_side = breach_deviation > 0 and confirmation_deviation > 0
    return bool(same_side and abs(confirmation_deviation) < abs(breach_deviation))


def execution_is_canceled(
    direction: Direction,
    executable_price: float,
    executable_vwap: float,
) -> bool:
    """Apply direction-specific crossing cancellation, including equality."""

    if not all(isfinite(value) and value > 0 for value in (executable_price, executable_vwap)):
        raise ValueError("Execution price and VWAP must be positive and finite.")
    if direction is Direction.LONG:
        return executable_price >= executable_vwap
    return executable_price <= executable_vwap


def detect_session_event(
    bars: pd.DataFrame,
    *,
    symbol: str,
    session_date: date,
    session_close: pd.Timestamp,
) -> EventDetection:
    """Run the first-breach, immediate-confirmation, no-rescan state machine."""

    required = {"timestamp", "open", "close", "session_vwap"}
    if not required.issubset(bars.columns):
        raise ValueError(f"Event bars require {sorted(required)}")
    work = bars.sort_values("timestamp", kind="stable").reset_index(drop=True)
    times = pd.to_datetime(work["timestamp"])
    if any(timestamp.tzinfo is None for timestamp in times):
        raise ValueError("Event timestamps must be timezone-aware.")
    candidate: Candidate | None = None
    candidate_index: int | None = None
    for index, row in work.iterrows():
        vwap = float(row["session_vwap"]) if pd.notna(row["session_vwap"]) else np.nan
        if not isfinite(vwap):
            continue
        deviation = signed_deviation(float(row["close"]), vwap)
        direction = breach_orientation(deviation)
        close_timestamp = pd.Timestamp(row["timestamp"]) + _FIVE_MINUTES
        if direction is not None and breach_close_is_eligible(close_timestamp, session_close):
            candidate = Candidate(symbol, session_date, close_timestamp, direction, deviation)
            candidate_index = index
            break
    if candidate is None or candidate_index is None:
        return EventDetection(None, None, "NO_ELIGIBLE_BREACH")
    if candidate_index + 2 >= len(work):
        return EventDetection(candidate, None, "INCOMPLETE_EVENT_PATH")
    breach_open = pd.Timestamp(work.loc[candidate_index, "timestamp"])
    confirmation = work.loc[candidate_index + 1]
    execution = work.loc[candidate_index + 2]
    if pd.Timestamp(confirmation["timestamp"]) != breach_open + _FIVE_MINUTES:
        return EventDetection(candidate, None, "IMMEDIATE_CONFIRMATION_MISSING")
    if pd.Timestamp(execution["timestamp"]) != breach_open + _TEN_MINUTES:
        return EventDetection(candidate, None, "EXECUTION_BAR_MISSING")
    confirmation_vwap = float(confirmation["session_vwap"])
    if not isfinite(confirmation_vwap):
        return EventDetection(candidate, None, "CONFIRMATION_VWAP_UNDEFINED")
    confirmation_deviation = signed_deviation(float(confirmation["close"]), confirmation_vwap)
    if not evaluate_immediate_confirmation(
        candidate.direction, candidate.deviation, confirmation_deviation
    ):
        return EventDetection(candidate, None, "CONFIRMATION_FAILED")
    executable_vwap = confirmation_vwap
    executable_price = float(execution["open"])
    if execution_is_canceled(candidate.direction, executable_price, executable_vwap):
        return EventDetection(candidate, None, "EXECUTION_CANCELED")
    event = Event(
        symbol=symbol,
        session_date=session_date,
        direction=candidate.direction,
        breach_timestamp=candidate.breach_timestamp,
        confirmation_timestamp=pd.Timestamp(confirmation["timestamp"]) + _FIVE_MINUTES,
        executable_timestamp=pd.Timestamp(execution["timestamp"]),
        executable_price=executable_price,
        executable_vwap=executable_vwap,
    )
    return EventDetection(candidate, event, "CONFIRMED")


def resample_complete_rth_1m_to_5m(frame: pd.DataFrame) -> pd.DataFrame:
    """Aggregate complete contiguous same-session one-minute bars to five minutes."""

    required = {"symbol", "session_date", "timestamp", "open", "high", "low", "close", "volume"}
    if not required.issubset(frame.columns):
        raise ValueError(f"Minute frame requires {sorted(required)}")
    work = frame.copy()
    work["timestamp"] = pd.to_datetime(work["timestamp"], utc=True).dt.tz_convert(TIMEZONE)
    work["session_date"] = pd.to_datetime(work["session_date"]).dt.date
    numeric_columns = ["open", "high", "low", "close", "volume"]
    work[numeric_columns] = work[numeric_columns].apply(pd.to_numeric, errors="coerce")
    if not np.isfinite(work[numeric_columns].to_numpy(dtype=float)).all():
        raise ValueError("Minute OHLCV must be finite.")
    work["bucket"] = work["timestamp"].dt.floor("5min")
    output: list[dict[str, Any]] = []
    for (symbol, session, bucket), group in work.groupby(
        ["symbol", "session_date", "bucket"], sort=True
    ):
        ordered = group.sort_values("timestamp", kind="stable")
        expected = pd.date_range(bucket, periods=5, freq="1min", tz=TIMEZONE)
        if len(ordered) != 5 or not ordered["timestamp"].reset_index(drop=True).equals(pd.Series(expected)):
            continue
        output.append({
            "symbol": symbol,
            "session_date": session,
            "timestamp": bucket,
            "close_timestamp": bucket + _FIVE_MINUTES,
            "open": float(ordered.iloc[0]["open"]),
            "high": float(ordered["high"].max()),
            "low": float(ordered["low"].min()),
            "close": float(ordered.iloc[-1]["close"]),
            "volume": float(ordered["volume"].sum()),
        })
    return pd.DataFrame(output)


def oriented_return(direction: Direction | str, executable_price: float, future_price: float) -> float:
    """Return favorable-positive gross return."""

    direction = Direction(direction)
    if not all(isfinite(value) and value > 0 for value in (executable_price, future_price)):
        raise ValueError("Return prices must be positive and finite.")
    if direction is Direction.LONG:
        return float(future_price / executable_price - 1.0)
    return float(executable_price / future_price - 1.0)


def path_excursions(
    direction: Direction | str,
    executable_price: float,
    path_highs: Sequence[float],
    path_lows: Sequence[float],
) -> tuple[float, float]:
    """Return exact MFE and MAE over one complete horizon path."""

    direction = Direction(direction)
    highs = np.asarray(path_highs, dtype=float)
    lows = np.asarray(path_lows, dtype=float)
    if not isfinite(executable_price) or executable_price <= 0 or highs.size == 0:
        raise ValueError("Excursion path must be non-empty and finite.")
    if highs.shape != lows.shape or not np.isfinite(highs).all() or not np.isfinite(lows).all():
        raise ValueError("Excursion highs/lows must be aligned and finite.")
    if direction is Direction.LONG:
        return float(np.max(highs / executable_price - 1)), float(np.min(lows / executable_price - 1))
    return float(np.max(executable_price / lows - 1)), float(np.min(executable_price / highs - 1))


def round_trip_cost(executable_price: float, profile: str) -> float:
    """Return the frozen baseline or stress round-trip return cost."""

    if not isfinite(executable_price) or executable_price <= 0:
        raise ValueError("Executable price must be positive and finite.")
    if profile == "baseline":
        return float(0.0002 + 0.02 / executable_price)
    if profile == "stress":
        return float(0.0004 + 0.04 / executable_price)
    raise ValueError(f"Unknown cost profile: {profile}")


def compute_path_metrics(events: pd.DataFrame, bars: pd.DataFrame) -> pd.DataFrame:
    """Compute required same-session horizons, returns, excursions, and costs."""

    event_required = {"symbol", "session_date", "direction", "executable_timestamp", "executable_price"}
    bar_required = {"symbol", "session_date", "timestamp", "high", "low", "close"}
    if not event_required.issubset(events.columns) or not bar_required.issubset(bars.columns):
        raise ValueError("Path inputs are missing required columns.")
    bar_work = bars.copy()
    bar_work["timestamp"] = pd.to_datetime(bar_work["timestamp"], utc=True).dt.tz_convert(TIMEZONE)
    output: list[dict[str, Any]] = []
    for event in events.itertuples(index=False):
        start = pd.Timestamp(event.executable_timestamp)
        if start.tzinfo is None:
            raise ValueError("Executable timestamp must be timezone-aware.")
        session_bars = bar_work[
            (bar_work["symbol"] == event.symbol)
            & (pd.to_datetime(bar_work["session_date"]).dt.date == pd.Timestamp(event.session_date).date())
            & (bar_work["timestamp"] >= start)
        ].sort_values("timestamp")
        if session_bars.empty:
            raise ValueError("Required path is unavailable.")
        session_close = session_bars["timestamp"].max() + _FIVE_MINUTES
        for horizon in HORIZONS:
            target = session_close if horizon == "session_close" else start + _HORIZON_OFFSETS[horizon]
            path = session_bars[(session_bars["timestamp"] >= start) & (session_bars["timestamp"] < target)]
            if target > session_close or path.empty or path["timestamp"].iloc[-1] + _FIVE_MINUTES != target:
                raise ValueError(f"Required horizon path is incomplete: {horizon}")
            future_price = float(path.iloc[-1]["close"])
            gross = oriented_return(event.direction, float(event.executable_price), future_price)
            mfe, mae = path_excursions(event.direction, float(event.executable_price), path["high"], path["low"])
            baseline = round_trip_cost(float(event.executable_price), "baseline")
            stress = round_trip_cost(float(event.executable_price), "stress")
            output.append({
                "symbol": event.symbol,
                "session_date": pd.Timestamp(event.session_date).date(),
                "year": pd.Timestamp(event.session_date).year,
                "direction": Direction(event.direction).value,
                "executable_timestamp": start,
                "executable_price": float(event.executable_price),
                "horizon": horizon,
                "future_price": future_price,
                "gross_return": gross,
                "mfe": mfe,
                "mae": mae,
                "baseline_cost": baseline,
                "stress_cost": stress,
                "baseline_net_return": gross - baseline,
                "stress_net_return": gross - stress,
                "path_complete": True,
            })
    return pd.DataFrame(output)


def build_exact_time_control(events: pd.DataFrame, controls: pd.DataFrame) -> pd.DataFrame:
    """Attach exact symbol/year/HH:MM/horizon oriented unconditional controls."""

    required = {"symbol", "session_date", "executable_timestamp", "horizon", "direction", "gross_return"}
    if not required.issubset(events.columns) or not required.issubset(controls.columns):
        raise ValueError(f"Control inputs require {sorted(required)}")
    event_work = events.copy()
    control_work = controls.copy()
    for frame in (event_work, control_work):
        frame["session_date"] = pd.to_datetime(frame["session_date"]).dt.date
        frame["year"] = frame["session_date"].map(lambda value: value.year)
        timestamps = pd.to_datetime(frame["executable_timestamp"], utc=True).dt.tz_convert(TIMEZONE)
        frame["executable_hhmm"] = timestamps.dt.strftime("%H:%M")
    values: list[float] = []
    counts: list[int] = []
    for row in event_work.itertuples(index=False):
        pool = control_work[
            (control_work["symbol"] == row.symbol)
            & (control_work["year"] == row.year)
            & (control_work["executable_hhmm"] == row.executable_hhmm)
            & (control_work["horizon"] == row.horizon)
            & (control_work["session_date"] != row.session_date)
            & (control_work["session_date"].map(lambda value: value.year) <= 2024)
        ]
        if pool.empty:
            raise ValueError("EMPTY_EXACT_TIME_CONTROL")
        raw = pd.to_numeric(pool["gross_return"], errors="coerce").to_numpy(dtype=float)
        if not np.isfinite(raw).all():
            raise ValueError("NONFINITE_EXACT_TIME_CONTROL")
        oriented = raw if Direction(row.direction) is Direction.LONG else -raw / (1.0 + raw)
        if not np.isfinite(oriented).all():
            raise ValueError("NONFINITE_EXACT_TIME_CONTROL")
        values.append(float(oriented.mean()))
        counts.append(int(oriented.size))
    event_work["unconditional_return"] = values
    event_work["unconditional_sample_count"] = counts
    event_work["incremental_return"] = event_work["gross_return"] - event_work["unconditional_return"]
    return event_work


def build_unconditional_candidates(events: pd.DataFrame, bars: pd.DataFrame) -> pd.DataFrame:
    """Build raw exact-time returns from every eligible discovery session."""

    event_required = {"symbol", "session_date", "executable_timestamp"}
    bar_required = {"symbol", "session_date", "timestamp", "open", "close"}
    if not event_required.issubset(events.columns) or not bar_required.issubset(bars.columns):
        raise ValueError("Unconditional-candidate inputs are missing required columns.")
    event_work = events.copy()
    event_work["session_date"] = pd.to_datetime(event_work["session_date"]).dt.date
    event_work["executable_timestamp"] = pd.to_datetime(
        event_work["executable_timestamp"], utc=True
    ).dt.tz_convert(TIMEZONE)
    bar_work = bars.copy()
    bar_work["session_date"] = pd.to_datetime(bar_work["session_date"]).dt.date
    bar_work["timestamp"] = pd.to_datetime(bar_work["timestamp"], utc=True).dt.tz_convert(TIMEZONE)
    output: list[dict[str, Any]] = []
    keys = event_work.assign(
        year=event_work["session_date"].map(lambda value: value.year),
        executable_hhmm=event_work["executable_timestamp"].dt.strftime("%H:%M"),
    )[["symbol", "year", "executable_hhmm"]].drop_duplicates()
    for key in keys.itertuples(index=False):
        sessions = bar_work[
            (bar_work["symbol"] == key.symbol)
            & (bar_work["session_date"].map(lambda value: value.year) == key.year)
        ]
        for session, group in sessions.groupby("session_date", sort=True):
            ordered = group.sort_values("timestamp", kind="stable")
            starts = ordered[ordered["timestamp"].dt.strftime("%H:%M") == key.executable_hhmm]
            if len(starts) != 1:
                continue
            start_row = starts.iloc[0]
            start = pd.Timestamp(start_row["timestamp"])
            executable_price = float(start_row["open"])
            session_close = ordered["timestamp"].max() + _FIVE_MINUTES
            for horizon in HORIZONS:
                target = session_close if horizon == "session_close" else start + _HORIZON_OFFSETS[horizon]
                path = ordered[(ordered["timestamp"] >= start) & (ordered["timestamp"] < target)]
                if target > session_close or path.empty or path["timestamp"].iloc[-1] + _FIVE_MINUTES != target:
                    continue
                future_price = float(path.iloc[-1]["close"])
                output.append({
                    "symbol": key.symbol,
                    "session_date": session,
                    "executable_timestamp": start,
                    "horizon": horizon,
                    "direction": Direction.LONG.value,
                    "gross_return": oriented_return(Direction.LONG, executable_price, future_price),
                })
    return pd.DataFrame(output)


def clustered_percentile_bootstrap(
    rows: pd.DataFrame,
    *,
    replicates: int = BOOTSTRAP_REPLICATES,
    seed: int = BOOTSTRAP_SEED,
    progress: Callable[[int, int], None] | None = None,
) -> Mapping[str, tuple[float, float]]:
    """Bootstrap pooled means by indivisible session-date clusters."""

    columns = ("gross_return", "incremental_return", "baseline_net_return")
    if "session_date" not in rows or not set(columns).issubset(rows.columns):
        raise ValueError("Bootstrap rows are missing required columns.")
    if not isinstance(replicates, int) or replicates <= 0:
        raise ValueError("Bootstrap replicates must be positive.")
    work = rows.copy()
    work["session_date"] = pd.to_datetime(work["session_date"]).dt.date
    values = work[list(columns)].apply(pd.to_numeric, errors="coerce")
    if not np.isfinite(values.to_numpy(dtype=float)).all():
        raise ValueError("Bootstrap inputs must be finite.")
    grouped = []
    for _, group in work.assign(**values).groupby("session_date", sort=True):
        grouped.append((group[list(columns)].sum().to_numpy(float), len(group)))
    if len(grouped) < 2:
        raise ValueError("Bootstrap requires at least two session clusters.")
    sums = np.stack([item[0] for item in grouped])
    counts = np.asarray([item[1] for item in grouped], dtype=float)
    rng = np.random.default_rng(seed)
    statistics = np.empty((replicates, len(columns)), dtype=float)
    for index in range(replicates):
        selected = rng.integers(0, len(grouped), size=len(grouped))
        statistics[index] = sums[selected].sum(axis=0) / counts[selected].sum()
        if progress is not None:
            progress(index + 1, replicates)
    lower, upper = np.quantile(statistics, [0.025, 0.975], axis=0)
    return {column: (float(lower[i]), float(upper[i])) for i, column in enumerate(columns)}


def annual_stability(rows: pd.DataFrame) -> Mapping[str, Any]:
    """Calculate frozen annual counts and positive-mean year counts."""

    required = {"session_date", "gross_return", "incremental_return"}
    if not required.issubset(rows.columns):
        raise ValueError("Annual stability rows are incomplete.")
    work = rows.copy()
    work["year"] = pd.to_datetime(work["session_date"]).dt.year
    if not np.isfinite(work[["gross_return", "incremental_return"]].to_numpy(float)).all():
        raise ValueError("Annual stability inputs must be finite.")
    grouped = work.groupby("year", sort=True)
    counts = grouped.size().to_dict()
    gross = grouped["gross_return"].mean().to_dict()
    incremental = grouped["incremental_return"].mean().to_dict()
    required_years = (2022, 2023, 2024)
    sufficient = all(counts.get(year, 0) >= 40 for year in required_years)
    return {
        "event_counts": counts,
        "gross_means": gross,
        "incremental_means": incremental,
        "all_years_sufficient": sufficient,
        "positive_gross_years": sum(counts.get(y, 0) >= 40 and gross.get(y, 0) > 0 for y in required_years),
        "positive_incremental_years": sum(counts.get(y, 0) >= 40 and incremental.get(y, 0) > 0 for y in required_years),
    }


def annual_concentration(rows: pd.DataFrame) -> ConcentrationResult:
    """Calculate `max(abs(C_y))/sum(abs(C_y))` for required years."""

    required = {"session_date", "incremental_return"}
    if rows.empty or not required.issubset(rows.columns):
        return ConcentrationResult(np.nan, False, "MISSING_REQUIRED_DATA")
    work = rows.copy()
    work["year"] = pd.to_datetime(work["session_date"]).dt.year
    values = pd.to_numeric(work["incremental_return"], errors="coerce")
    if not np.isfinite(values.to_numpy(float)).all():
        return ConcentrationResult(np.nan, False, "NONFINITE_INCREMENTAL_RETURN")
    contributions = values.groupby(work["year"]).sum()
    if set(contributions.index) != {2022, 2023, 2024}:
        return ConcentrationResult(np.nan, False, "MISSING_REQUIRED_YEAR")
    denominator = float(contributions.abs().sum())
    if denominator == 0 or not isfinite(denominator):
        return ConcentrationResult(np.nan, False, "ZERO_OR_NONFINITE_DENOMINATOR")
    value = float(contributions.abs().max() / denominator)
    return ConcentrationResult(value, value <= 0.70, "PASS" if value <= 0.70 else "ABOVE_LIMIT")


def select_leave_one_out_session(session_contributions: Mapping[date | str, float]) -> date:
    """Select exactly one date by `(-abs(contribution), ISO date)`."""

    if not session_contributions:
        raise ValueError("LOO requires at least one session contribution.")
    normalized: dict[date, float] = {}
    for raw_date, raw_value in session_contributions.items():
        session = raw_date if isinstance(raw_date, date) else date.fromisoformat(str(raw_date))
        value = float(raw_value)
        if not isfinite(value):
            raise ValueError("LOO session contributions must be finite.")
        if session in normalized:
            raise ValueError("LOO session contribution dates must be unique.")
        normalized[session] = value
    return sorted(normalized, key=lambda session: (-abs(normalized[session]), session))[0]


def leave_one_largest_session_out(rows: pd.DataFrame) -> LeaveOneOutResult:
    """Remove one complete selected date and recompute CON-02 through CON-04."""

    required = {"session_date", "incremental_return"}
    if rows.empty or not required.issubset(rows.columns):
        raise ValueError("LOO rows are missing required data.")
    work = rows.copy()
    work["session_date"] = pd.to_datetime(work["session_date"]).dt.date
    work["incremental_return"] = pd.to_numeric(work["incremental_return"], errors="coerce")
    if not np.isfinite(work["incremental_return"].to_numpy(float)).all():
        raise ValueError("LOO incremental returns must be finite.")
    contributions = work.groupby("session_date", sort=True)["incremental_return"].sum().to_dict()
    removed = select_leave_one_out_session(contributions)
    residual = work[work["session_date"] != removed].copy()
    if residual.empty or residual["session_date"].nunique() < 2:
        raise ValueError("LOO residual requires at least two session clusters.")
    concentration = annual_concentration(residual)
    stability = annual_stability(
        residual.assign(gross_return=residual.get("gross_return", residual["incremental_return"]))
    )
    pooled = float(residual["incremental_return"].mean())
    positive = int(stability["positive_incremental_years"])
    passed = concentration.passed and pooled > 0 and positive >= 2
    return LeaveOneOutResult(
        removed,
        concentration,
        pooled,
        positive,
        stability["event_counts"],
        passed,
    )


def _all_values(value: Any) -> list[Any]:
    if isinstance(value, Mapping):
        return [item for nested in value.values() for item in _all_values(nested)]
    if isinstance(value, (list, tuple, np.ndarray, pd.Series)):
        return [item for nested in value for item in _all_values(nested)]
    return [value]


def _compare(values: Any, operator: str, threshold: Any) -> bool:
    items = _all_values(values)
    if not items:
        return False
    for value in items:
        if value is None or (isinstance(value, (float, np.floating)) and not isfinite(float(value))):
            return False
        if operator == "=" and value != threshold:
            return False
        if operator == ">" and not value > threshold:
            return False
        if operator == ">=" and not value >= threshold:
            return False
        if operator == "<=" and not value <= threshold:
            return False
    return True


def derive_substantive_criteria(
    metrics: Mapping[str, Any],
    criteria_spec: Sequence[Mapping[str, Any]],
) -> Mapping[str, str]:
    """Derive the exact 25 terminal criterion states from metric values."""

    output: dict[str, str] = {}
    specs = [item for item in criteria_spec if item.get("criterion_id") != "PRO-01"]
    if tuple(item.get("criterion_id") for item in specs) != SUBSTANTIVE_CRITERION_IDS:
        raise ValueError("PRO_INPUT_SET_MISMATCH")
    for item in specs:
        criterion_id = str(item["criterion_id"])
        metric = str(item["metric"])
        value = metrics.get(criterion_id, metrics.get(metric))
        structure_valid = True
        if criterion_id in {"SMP-02", "ECO-02"}:
            structure_valid = isinstance(value, Mapping) and set(value) == set(SYMBOLS)
        elif criterion_id == "SMP-03":
            structure_valid = isinstance(value, Mapping) and set(value) == {2022, 2023, 2024}
        elif criterion_id == "REP-01":
            structure_valid = isinstance(value, Mapping) and set(value) == {"long", "short"}
        elif criterion_id == "ECO-03":
            structure_valid = len(_all_values(value)) == 4
        elif criterion_id == "ECO-04":
            structure_valid = isinstance(value, Mapping) and set(value) == {"pooled", "QQQ", "SPY"}
        elif criterion_id == "UNC-01":
            structure_valid = len(_all_values(value)) == 3
        output[criterion_id] = (
            "passed"
            if structure_valid and _compare(value, str(item["operator"]), item["threshold"])
            else "failed"
        )
    return output


def evaluate_pro_01(statuses: Mapping[str, str]) -> bool:
    """Evaluate PRO-01 after all exact substantive statuses are terminal."""

    if tuple(statuses.keys()) != SUBSTANTIVE_CRITERION_IDS:
        raise ValueError("PRO_INPUT_SET_MISMATCH")
    terminal = {"passed", "failed", "false", "missing", "non-finite", "insufficient", "non-estimable", "unavailable"}
    if any(status not in terminal for status in statuses.values()):
        raise ValueError("PRO_NONTERMINAL_INPUT")
    return all(status == "passed" for status in statuses.values())


def classify_gate(statuses: Mapping[str, str]) -> GateResult:
    """Return the frozen non-discretionary discovery classification."""

    pro = evaluate_pro_01(statuses)
    criteria = {**statuses, "PRO-01": "passed" if pro else "failed"}
    return GateResult(
        criteria=criteria,
        pro_01=pro,
        classification="discovery_passed" if pro else "discovery_failed",
        validation_2025_unlocked=pro,
    )
