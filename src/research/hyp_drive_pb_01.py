from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, time
from enum import Enum
from math import isfinite
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import yaml


APPROVED_HYPOTHESIS_ID = "HYP-DRIVE-PB-01"
APPROVED_STATUS = "preregistered_not_executed"
APPROVED_DECISION_IDS = tuple(f"B{i}" for i in range(1, 16))

FROZEN_CONSTANT_NAMES = (
    "drive_start",
    "drive_end",
    "historical_atr_lookback",
    "minimum_normalized_drive",
    "minimum_initial_adverse_pullback_ticks",
    "maximum_normalized_pullback_depth",
    "maximum_post_drive_observation_bars",
    "latest_confirmation_executable_boundary",
    "maximum_events_per_symbol_session",
    "primary_horizon_minutes",
    "minimum_pooled_events",
    "minimum_events_per_symbol",
    "minimum_positive_discovery_years",
    "maximum_annual_effect_concentration",
    "bootstrap_confidence_level",
    "bootstrap_resamples",
    "bootstrap_seed",
)

APPROVED_GATE_CRITERION_IDS = (
    "minimum_pooled_events",
    "minimum_events_per_symbol",
    "continuation_long_positive_mean_and_median",
    "continuation_short_positive_mean_and_median",
    "qqq_and_spy_positive_primary_means",
    "gross_mean_positive_in_at_least_two_of_three_years",
    "pooled_incremental_mean_positive",
    "pooled_baseline_net_mean_positive",
    "pooled_stress_net_mean_non_negative",
    "annual_concentration_at_most_0_70",
    "leave_one_session_out_concentration_at_most_0_70",
    "annual_signs_positive_in_at_least_two_of_three_years_original_and_leave_one_out",
    "all_three_bootstrap_lower_bounds_strictly_positive",
    "no_lookahead_or_unresolved_data_quality_failure",
    "no_2025_or_2026_contamination",
    "one_variant_budget_respected",
)

REQUIRED_SAFETY_FLAG_NAMES = frozenset(
    {
        "strategy_created",
        "orders_created",
        "position_sizing_used",
        "broker_connected",
        "paper_broker_enabled",
        "live_trading",
        "orders_sent",
        "paper_eligible",
        "live_eligible",
    }
)

APPROVED_FORBIDDEN_ACTIONS = (
    "read_real_ohlc_during_materialization",
    "read_real_manifests_during_materialization",
    "execute_discovery",
    "execute_validation_2025",
    "execute_historical_2026",
    "create_strategy",
    "create_orders",
    "position_sizing",
    "connect_broker",
)

CANONICAL_SCHEMA_SIGNATURE = (
    "14b630bf442cb1f9c0dfd0fa73194571daf469ef705630509bc9529c9ef420af"
)
APPROVED_SINGLETON_VALUES_SIGNATURE = (
    "a3eb7c5d651a92068dc704cc4f5b05d5697d5a9de907da295486eb134c93ba3f"
)
DECLARED_INTEGRITY_METADATA = frozenset({"canonical_payload_hash"})
EXPLICIT_NON_METHODOLOGICAL_FIELDS = frozenset(
    {
        "generated_at",
        "generation_timestamp",
        "absolute_path",
        "user",
        "hostname",
        "working_tree",
        "future_execution_sha",
        "preregistration_commit",
        "results",
        "historical_counts",
        "run_derived_data",
    }
)

APPROVED_SEMANTIC_IDS = {
    "configuration_governance.single_source_of_truth": "yaml_v1",
    "pullback.minimum_distance_formula_id": "ticks_times_symbol_tick_size_v1",
    "pullback.post_drive_new_extreme_invalidation.rule_id": (
        "strict_post_drive_new_extreme_exclusion_v1"
    ),
    "pullback.post_drive_new_extreme_invalidation.intrabar_priority_rule_id": (
        "invalidation_before_pullback_and_confirmation_v1"
    ),
    "confirmation.confirmation_rule_id": (
        "strict_close_beyond_previous_bar_extreme_v1"
    ),
    "execution.executable_timestamp_rule_id": (
        "first_strictly_later_five_minute_label_v1"
    ),
    "horizons.primary_label_derivation_id": (
        "integer_minutes_plus_min_suffix_v1"
    ),
    "costs.round_trip_formula_id": (
        "two_sided_commission_plus_tick_slippage_v1"
    ),
    "annual_concentration.formula_id": (
        "max_abs_annual_contribution_over_sum_abs_v1"
    ),
    "bootstrap.method_id": "clustered_session_percentile_bilateral_v1",
    "discovery_gate.evaluation_rule_id": (
        "derive_all_required_from_metrics_v1"
    ),
}

EXCLUDED_POST_DRIVE_NEW_EXTREME = "EXCLUDED_POST_DRIVE_NEW_EXTREME"
EXCLUDED_DIRECTION_CONFLICT = "EXCLUDED_DIRECTION_CONFLICT"
EXCLUDED_INITIAL_PULLBACK = "EXCLUDED_INITIAL_PULLBACK"
EXCLUDED_MAXIMUM_PULLBACK = "EXCLUDED_MAXIMUM_PULLBACK"
EXCLUDED_NO_CONFIRMATION = "EXCLUDED_NO_CONFIRMATION"
EXCLUDED_EXECUTABLE_BAR = "EXCLUDED_EXECUTABLE_BAR"


class Direction(str, Enum):
    LONG = "continuation_long"
    SHORT = "continuation_short"


def _deep_freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _deep_freeze(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_deep_freeze(item) for item in value)
    return value


def _deep_thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _deep_thaw(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_deep_thaw(item) for item in value]
    return value


def _value_type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    return type(value).__name__


def _schema_tokens(value: Any, path: str = "$") -> list[str]:
    if isinstance(value, Mapping):
        tokens = [f"{path}:mapping"]
        for key in sorted(value):
            tokens.extend(_schema_tokens(value[key], f"{path}.{key}"))
        return tokens
    if isinstance(value, (list, tuple)):
        tokens = [f"{path}:list:{len(value)}"]
        for index, item in enumerate(value):
            tokens.extend(_schema_tokens(item, f"{path}[{index}]"))
        return tokens
    return [f"{path}:{_value_type_name(value)}"]


def _schema_signature(mapping: Mapping[str, Any]) -> str:
    encoded = "\n".join(_schema_tokens(mapping)).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def yaml_leaf_paths(value: Any, path: str = "$") -> dict[str, Any]:
    if isinstance(value, Mapping):
        leaves: dict[str, Any] = {}
        for key in sorted(value):
            leaves.update(yaml_leaf_paths(value[key], f"{path}.{key}"))
        return leaves
    if isinstance(value, (list, tuple)):
        leaves = {}
        for index, item in enumerate(value):
            leaves.update(yaml_leaf_paths(item, f"{path}[{index}]"))
        return leaves
    return {path: value}


def classify_yaml_leaf_paths(mapping: Mapping[str, Any]) -> dict[str, str]:
    classifications: dict[str, str] = {}
    for path in yaml_leaf_paths(mapping):
        field_name = path.rsplit(".", 1)[-1]
        if path == "$.canonical_payload_hash":
            classifications[path] = "declared_integrity_metadata"
        elif field_name in EXPLICIT_NON_METHODOLOGICAL_FIELDS:
            classifications[path] = "explicitly_non_methodological_excluded"
        else:
            classifications[path] = "canonical_payload_included"
    return classifications


def _mutable_canonical_leaf_paths() -> frozenset[str]:
    research = {
        f"$.research_parameters.values.{name}"
        for name in FROZEN_CONSTANT_NAMES
        if name != "latest_confirmation_executable_boundary"
    }
    return frozenset(
        research
        | {
            "$.research_parameters.values.latest_confirmation_executable_boundary[0]",
            "$.research_parameters.values.latest_confirmation_executable_boundary[1]",
            "$.frozen_market_conventions.tick_size_by_symbol.QQQ",
            "$.frozen_market_conventions.tick_size_by_symbol.SPY",
            "$.costs.baseline.commission_per_side",
            "$.costs.baseline.slippage_ticks_per_execution",
            "$.costs.stress.commission_per_side",
            "$.costs.stress.slippage_ticks_per_execution",
        }
    )


def _singleton_values_signature(mapping: Mapping[str, Any]) -> str:
    excluded = _mutable_canonical_leaf_paths() | {"$.canonical_payload_hash"}
    fixed_leaves = [
        (path, value)
        for path, value in yaml_leaf_paths(mapping).items()
        if path not in excluded
    ]
    encoded = json.dumps(
        fixed_leaves,
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class DrivePullbackConfig:
    canonical_spec: Mapping[str, Any]
    declared_canonical_payload_hash: str
    drive_start: str
    drive_end: str
    historical_atr_lookback: int
    minimum_normalized_drive: float
    minimum_initial_adverse_pullback_ticks: int
    maximum_normalized_pullback_depth: float
    maximum_post_drive_observation_bars: int
    latest_confirmation_executable_boundary: tuple[str, str]
    maximum_events_per_symbol_session: int
    primary_horizon_minutes: int
    minimum_pooled_events: int
    minimum_events_per_symbol: int
    minimum_positive_discovery_years: int
    maximum_annual_effect_concentration: float
    bootstrap_confidence_level: float
    bootstrap_resamples: int
    bootstrap_seed: int
    tick_size_by_symbol: Mapping[str, float]
    symbols: tuple[str, ...]
    secondary_horizons: tuple[str, ...]
    timezone: str
    baseline_commission_per_side: float
    baseline_slippage_ticks_per_execution: int
    stress_commission_per_side: float
    stress_slippage_ticks_per_execution: int
    conceptual_design_freeze_commit: str
    implementation_clarification_freeze_commit: str
    decision_variants: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "canonical_spec", _deep_freeze(self.canonical_spec))
        for field_name in (
            "historical_atr_lookback",
            "minimum_initial_adverse_pullback_ticks",
            "maximum_post_drive_observation_bars",
            "maximum_events_per_symbol_session",
            "primary_horizon_minutes",
            "minimum_pooled_events",
            "minimum_events_per_symbol",
            "minimum_positive_discovery_years",
            "bootstrap_resamples",
            "bootstrap_seed",
            "baseline_slippage_ticks_per_execution",
            "stress_slippage_ticks_per_execution",
            "decision_variants",
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{field_name} must be a positive integer.")
        for field_name in (
            "minimum_normalized_drive",
            "maximum_normalized_pullback_depth",
            "maximum_annual_effect_concentration",
            "bootstrap_confidence_level",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, (int, float)) or not isfinite(float(value)):
                raise ValueError(f"{field_name} must be finite.")
        if self.minimum_normalized_drive <= 0:
            raise ValueError("minimum_normalized_drive must be positive.")
        if not 0 < self.maximum_normalized_pullback_depth <= 1:
            raise ValueError("maximum_normalized_pullback_depth must be in (0, 1].")
        if not 0 < self.maximum_annual_effect_concentration <= 1:
            raise ValueError("maximum_annual_effect_concentration must be in (0, 1].")
        if not 0 < self.bootstrap_confidence_level < 1:
            raise ValueError("bootstrap_confidence_level must be in (0, 1).")
        for value in (self.drive_start, self.drive_end, *self.latest_confirmation_executable_boundary):
            time.fromisoformat(value)
        if len(self.latest_confirmation_executable_boundary) != 2:
            raise ValueError("latest_confirmation_executable_boundary requires two times.")
        if not self.symbols or len(set(self.symbols)) != len(self.symbols):
            raise ValueError("symbols must be non-empty and unique.")
        ticks = {str(symbol).upper(): float(value) for symbol, value in self.tick_size_by_symbol.items()}
        if set(ticks) != set(self.symbols):
            raise ValueError("tick_size_by_symbol must match the declared symbols exactly.")
        if not all(isfinite(value) and value > 0 for value in ticks.values()):
            raise ValueError("Every tick size must be positive and finite.")
        object.__setattr__(self, "tick_size_by_symbol", MappingProxyType(ticks))
        ZoneInfo(self.timezone)
        for field_name in ("baseline_commission_per_side", "stress_commission_per_side"):
            value = getattr(self, field_name)
            if not isinstance(value, (int, float)) or not isfinite(float(value)) or value < 0:
                raise ValueError(f"{field_name} must be non-negative and finite.")
        for field_name in (
            "conceptual_design_freeze_commit",
            "implementation_clarification_freeze_commit",
        ):
            value = getattr(self, field_name)
            if len(value) != 40 or any(character not in "0123456789abcdef" for character in value):
                raise ValueError(f"{field_name} must be a full lowercase Git SHA.")

    @property
    def primary_horizon_label(self) -> str:
        if (
            self.semantic_id("horizons.primary_label_derivation_id")
            != "integer_minutes_plus_min_suffix_v1"
        ):
            raise ValueError("Unsupported primary-horizon label derivation ID.")
        return f"{self.primary_horizon_minutes}min"

    @property
    def hypothesis_id(self) -> str:
        return str(self.canonical_spec["hypothesis_id"])

    @property
    def name(self) -> str:
        return str(self.canonical_spec["name"])

    @property
    def status(self) -> str:
        return str(self.canonical_spec["status"])

    @property
    def gate_criteria(self) -> tuple[str, ...]:
        return tuple(self.canonical_spec["discovery_gate"]["criteria"])

    @property
    def gate_all_required(self) -> bool:
        return bool(self.canonical_spec["discovery_gate"]["all_required"])

    @property
    def safety_flags(self) -> Mapping[str, bool]:
        return self.canonical_spec["safety_flags"]

    @property
    def forbidden_actions(self) -> tuple[str, ...]:
        return tuple(self.canonical_spec["forbidden_actions"])

    def semantic_id(self, dotted_path: str) -> str:
        value: Any = self.canonical_spec
        for key in dotted_path.split("."):
            if not isinstance(value, Mapping) or key not in value:
                raise ValueError(f"Missing semantic ID: {dotted_path}")
            value = value[key]
        return str(value)

    def tick_size_for_symbol(self, symbol: str) -> float:
        normalized = symbol.upper()
        if normalized not in self.tick_size_by_symbol:
            raise ValueError("Symbol is outside the frozen tick-size convention.")
        return self.tick_size_by_symbol[normalized]

    def research_parameters(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in FROZEN_CONSTANT_NAMES}

    def canonical_mapping(self) -> dict[str, Any]:
        mapping = _deep_thaw(self.canonical_spec)
        mapping["canonical_payload_hash"] = self.declared_canonical_payload_hash
        mapping["conceptual_design_freeze_commit"] = (
            self.conceptual_design_freeze_commit
        )
        mapping["implementation_clarification_freeze_commit"] = (
            self.implementation_clarification_freeze_commit
        )
        mapping["research_parameters"]["count"] = len(FROZEN_CONSTANT_NAMES)
        mapping["research_parameters"]["values"] = self.research_parameters()
        mapping["research_parameters"]["values"][
            "latest_confirmation_executable_boundary"
        ] = list(self.latest_confirmation_executable_boundary)
        mapping["frozen_market_conventions"]["tick_size_by_symbol"] = dict(
            self.tick_size_by_symbol
        )
        mapping["universe"]["symbols"] = list(self.symbols)
        mapping["horizons"]["secondary"] = list(self.secondary_horizons)
        mapping["session"]["timezone"] = self.timezone
        mapping["costs"]["baseline"]["commission_per_side"] = (
            self.baseline_commission_per_side
        )
        mapping["costs"]["baseline"]["slippage_ticks_per_execution"] = (
            self.baseline_slippage_ticks_per_execution
        )
        mapping["costs"]["stress"]["commission_per_side"] = (
            self.stress_commission_per_side
        )
        mapping["costs"]["stress"]["slippage_ticks_per_execution"] = (
            self.stress_slippage_ticks_per_execution
        )
        mapping["approval"]["decision_variants"] = self.decision_variants
        mapping["multiplicity"]["decision_variants"] = self.decision_variants
        return mapping


def _required_mapping(mapping: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = mapping.get(key)
    if not isinstance(value, Mapping):
        raise ValueError(f"{key} must be a mapping.")
    return value


def _validate_full_mapping(mapping: Mapping[str, Any]) -> None:
    if _schema_signature(mapping) != CANONICAL_SCHEMA_SIGNATURE:
        raise ValueError(
            "Canonical YAML schema, types, list lengths, or nested fields differ "
            "from the approved strict schema."
        )
    if _singleton_values_signature(mapping) != APPROVED_SINGLETON_VALUES_SIGNATURE:
        raise ValueError(
            "A frozen metadata, policy, formula ID, gate, safety, or governance "
            "value differs from the approved specification."
        )
    if mapping["hypothesis_id"] != APPROVED_HYPOTHESIS_ID:
        raise ValueError("Unexpected hypothesis_id.")
    if mapping["status"] != APPROVED_STATUS:
        raise ValueError("Only preregistered_not_executed is allowed.")
    approval = _required_mapping(mapping, "approval")
    if tuple(approval["approved_decisions"]) != APPROVED_DECISION_IDS:
        raise ValueError("B1-B15 must be approved in canonical order.")
    if approval["parameters_frozen"] != len(FROZEN_CONSTANT_NAMES):
        raise ValueError("Approval must freeze exactly 17 research parameters.")
    for path, expected in APPROVED_SEMANTIC_IDS.items():
        value: Any = mapping
        for key in path.split("."):
            value = _required_mapping(value, key) if key != path.split(".")[-1] else value.get(key)
        if value != expected:
            raise ValueError(f"Unknown or unapproved semantic ID at {path}.")
    gate = _required_mapping(mapping, "discovery_gate")
    criteria = gate["criteria"]
    if (
        not isinstance(criteria, list)
        or tuple(criteria) != APPROVED_GATE_CRITERION_IDS
        or len(criteria) != len(set(criteria))
        or gate["all_required"] is not True
    ):
        raise ValueError(
            "Gate criteria must contain the 16 approved IDs once, in canonical order."
        )
    safety = _required_mapping(mapping, "safety_flags")
    if set(safety) != REQUIRED_SAFETY_FLAG_NAMES or any(
        value is not False for value in safety.values()
    ):
        raise ValueError("Every required safety flag must be explicitly false.")
    forbidden = mapping["forbidden_actions"]
    if not isinstance(forbidden, list) or tuple(forbidden) != APPROVED_FORBIDDEN_ACTIONS:
        raise ValueError("Forbidden actions differ from the approved canonical set.")
    payload_policy = _required_mapping(mapping, "canonical_payload")
    if payload_policy["declared_integrity_metadata"] != ["canonical_payload_hash"]:
        raise ValueError("canonical_payload_hash must be declared integrity metadata.")
    if set(payload_policy["explicitly_non_methodological_excluded"]) != set(
        EXPLICIT_NON_METHODOLOGICAL_FIELDS
    ):
        raise ValueError("Non-methodological payload exclusions differ from policy.")
    declared_hash = mapping["canonical_payload_hash"]
    if (
        not isinstance(declared_hash, str)
        or len(declared_hash) != 64
        or any(character not in "0123456789abcdef" for character in declared_hash)
    ):
        raise ValueError("canonical_payload_hash must be a lowercase SHA-256.")


def _build_config(mapping: Mapping[str, Any]) -> DrivePullbackConfig:
    _validate_full_mapping(mapping)
    research = _required_mapping(mapping, "research_parameters")
    values = _required_mapping(research, "values")
    if research.get("count") != len(FROZEN_CONSTANT_NAMES):
        raise ValueError("research_parameters.count must be exactly 17.")
    if set(values) != set(FROZEN_CONSTANT_NAMES):
        raise ValueError("research parameter names must match the approved 17 exactly.")
    conventions = _required_mapping(mapping, "frozen_market_conventions")
    if set(conventions) != {"count", "classification", "tick_size_by_symbol"}:
        raise ValueError("Unknown or missing frozen market-convention field.")
    if conventions.get("count") != 1:
        raise ValueError("There must be exactly one frozen market convention.")
    if conventions.get("classification") != "frozen_market_convention":
        raise ValueError("Tick size must be classified as frozen_market_convention.")
    ticks = _required_mapping(conventions, "tick_size_by_symbol")
    universe = _required_mapping(mapping, "universe")
    horizons = _required_mapping(mapping, "horizons")
    if "primary" in horizons or "primary_horizon" in horizons:
        raise ValueError("Primary horizon labels must be derived, not configured.")
    session = _required_mapping(mapping, "session")
    costs = _required_mapping(mapping, "costs")
    baseline = _required_mapping(costs, "baseline")
    stress = _required_mapping(costs, "stress")
    multiplicity = _required_mapping(mapping, "multiplicity")
    boundary = values["latest_confirmation_executable_boundary"]
    if not isinstance(boundary, (list, tuple)) or len(boundary) != 2:
        raise ValueError("latest_confirmation_executable_boundary requires two values.")
    return DrivePullbackConfig(
        canonical_spec=mapping,
        declared_canonical_payload_hash=str(mapping["canonical_payload_hash"]),
        **{
            **values,
            "latest_confirmation_executable_boundary": tuple(boundary),
        },
        tick_size_by_symbol=ticks,
        symbols=tuple(universe["symbols"]),
        secondary_horizons=tuple(horizons["secondary"]),
        timezone=str(session["timezone"]),
        baseline_commission_per_side=baseline["commission_per_side"],
        baseline_slippage_ticks_per_execution=baseline["slippage_ticks_per_execution"],
        stress_commission_per_side=stress["commission_per_side"],
        stress_slippage_ticks_per_execution=stress["slippage_ticks_per_execution"],
        conceptual_design_freeze_commit=str(mapping["conceptual_design_freeze_commit"]),
        implementation_clarification_freeze_commit=str(
            mapping["implementation_clarification_freeze_commit"]
        ),
        decision_variants=multiplicity["decision_variants"],
    )


def config_from_mapping(mapping: Mapping[str, Any]) -> DrivePullbackConfig:
    config = _build_config(mapping)
    recomputed = canonical_payload_hash(canonical_payload(config))
    if recomputed != config.declared_canonical_payload_hash:
        raise ValueError(
            "Declared canonical_payload_hash does not match the validated payload."
        )
    return config


def load_config_yaml(path: str | Path) -> DrivePullbackConfig:
    with Path(path).open("r", encoding="utf-8") as stream:
        mapping = yaml.safe_load(stream)
    if not isinstance(mapping, Mapping):
        raise ValueError("Canonical YAML root must be a mapping.")
    return config_from_mapping(mapping)


@dataclass(frozen=True)
class Bar:
    timestamp: pd.Timestamp
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    complete: bool = True

    def __post_init__(self) -> None:
        ts = pd.Timestamp(self.timestamp)
        if ts.tzinfo is None:
            raise ValueError("Bar timestamps must be timezone-aware.")
        object.__setattr__(self, "timestamp", ts)
        values = (self.open, self.high, self.low, self.close, self.volume)
        if not all(isfinite(float(value)) for value in values):
            raise ValueError("Bar values must be finite.")
        if self.high < max(self.open, self.close, self.low):
            raise ValueError("Bar high is inconsistent.")
        if self.low > min(self.open, self.close, self.high):
            raise ValueError("Bar low is inconsistent.")


@dataclass(frozen=True)
class DailyRTHSession:
    session_date: date
    high: float
    low: float
    close: float
    approved: bool = True
    complete: bool = True


@dataclass(frozen=True)
class Drive:
    direction: Direction
    displacement: float
    oriented_displacement: float
    score: float
    initial_price: float
    final_price: float
    extreme: float
    excursion: float
    frozen_at: pd.Timestamp


@dataclass(frozen=True)
class Event:
    hypothesis_id: str
    symbol: str
    session_date: date
    direction: Direction
    drive: Drive
    pullback_depth: float
    pullback_depth_ratio: float
    confirmation_timestamp: pd.Timestamp
    executable_timestamp: pd.Timestamp
    executable_price: float


@dataclass(frozen=True)
class GateResult:
    criteria: Mapping[str, bool]
    all_required: bool
    passed: bool
    classification: str
    validation_2025_unlocked: bool
    paper_eligible: bool
    live_eligible: bool


@dataclass(frozen=True)
class EventDetectionResult:
    event: Event | None
    exclusion_reason: str | None


@dataclass(frozen=True)
class DeduplicationResult:
    events: tuple[Event, ...]
    exclusions: Mapping[tuple[str, date], str]


@dataclass(frozen=True)
class ConcentrationResult:
    value: float
    passed: bool
    validation_status: str


@dataclass(frozen=True)
class LeaveOneSessionOutResult:
    value: float
    passed: bool
    removed_session_date: date | None
    validation_status: str


@dataclass(frozen=True)
class GateMetrics:
    primary_horizon_minutes: int
    pooled_event_count: int
    event_count_by_symbol: Mapping[str, int]
    direction_mean: Mapping[str, float]
    direction_median: Mapping[str, float]
    symbol_mean: Mapping[str, float]
    annual_gross_mean: Mapping[int, float]
    pooled_incremental_mean: float
    pooled_baseline_net_mean: float
    pooled_stress_net_mean: float
    annual_concentration: ConcentrationResult
    leave_one_session_out_concentration: LeaveOneSessionOutResult
    annual_incremental_signs: Mapping[int, float]
    leave_one_out_annual_incremental_signs: Mapping[int, float]
    bootstrap_intervals: Mapping[str, tuple[float, float]]
    causal_integrity_passed: bool
    temporal_contamination_absent: bool
    decision_variants: int


def _ny(timestamp: pd.Timestamp, config: DrivePullbackConfig) -> pd.Timestamp:
    return pd.Timestamp(timestamp).tz_convert(ZoneInfo(config.timezone))


def _clock(timestamp: pd.Timestamp, config: DrivePullbackConfig) -> time:
    return _ny(timestamp, config).time().replace(tzinfo=None)


def validate_drive_window(
    bars: Sequence[Bar],
    config: DrivePullbackConfig,
) -> tuple[Bar, Bar, Bar]:
    if len(bars) != 3:
        raise ValueError("The drive requires exactly three complete five-minute bars.")
    ordered = tuple(sorted(bars, key=lambda bar: bar.timestamp))
    start = pd.Timestamp(f"2000-01-01 {config.drive_start}")
    expected = tuple((start + pd.Timedelta(5 * index, unit="min")).time() for index in range(3))
    session_dates = {_ny(bar.timestamp, config).date() for bar in ordered}
    if len(session_dates) != 1 or tuple(
        _clock(bar.timestamp, config) for bar in ordered
    ) != expected:
        raise ValueError("Drive bars must be [09:30,09:35), [09:35,09:40), [09:40,09:45).")
    if not all(bar.complete for bar in ordered):
        raise ValueError("All drive bars must be complete.")
    for previous, current in zip(ordered, ordered[1:]):
        if current.timestamp - previous.timestamp != pd.Timedelta(5, unit="min"):
            raise ValueError("Drive bars must be contiguous.")
    return ordered


def true_range(high: float, low: float, previous_close: float) -> float:
    values = (high, low, previous_close)
    if not all(isfinite(float(value)) for value in values) or high < low:
        raise ValueError("True-range inputs must be finite and high must be >= low.")
    return float(max(high - low, abs(high - previous_close), abs(low - previous_close)))


def atr20_prior(
    sessions: Sequence[DailyRTHSession],
    current_session: date,
    config: DrivePullbackConfig,
) -> float | None:
    session_dates = [session.session_date for session in sessions]
    if len(session_dates) != len(set(session_dates)):
        raise ValueError("Daily RTH sessions must contain exactly one row per session_date.")
    approved = sorted(
        (
            session
            for session in sessions
            if session.approved and session.complete and session.session_date < current_session
        ),
        key=lambda session: session.session_date,
    )
    true_ranges: list[tuple[date, float]] = []
    previous_close: float | None = None
    for session in approved:
        if previous_close is not None:
            true_ranges.append(
                (session.session_date, true_range(session.high, session.low, previous_close))
            )
        previous_close = session.close
    if len(true_ranges) < config.historical_atr_lookback:
        return None
    selected = true_ranges[-config.historical_atr_lookback :]
    return float(
        sum(value for _, value in selected) / config.historical_atr_lookback
    )


def build_drive(
    bars: Sequence[Bar],
    atr20: float,
    config: DrivePullbackConfig,
) -> Drive | None:
    ordered = validate_drive_window(bars, config)
    if not isfinite(atr20) or atr20 <= 0:
        raise ValueError("ATR20 must be positive and finite.")
    initial = float(ordered[0].open)
    final = float(ordered[-1].close)
    displacement = final - initial
    score = displacement / atr20
    if score >= config.minimum_normalized_drive:
        direction = Direction.LONG
        extreme = max(float(bar.high) for bar in ordered)
        excursion = extreme - initial
        oriented = displacement
    elif score <= -config.minimum_normalized_drive:
        direction = Direction.SHORT
        extreme = min(float(bar.low) for bar in ordered)
        excursion = initial - extreme
        oriented = -displacement
    else:
        return None
    if excursion <= 0:
        return None
    frozen_at = _ny(ordered[-1].timestamp, config) + pd.Timedelta(5, unit="min")
    return Drive(
        direction=direction,
        displacement=displacement,
        oriented_displacement=oriented,
        score=score,
        initial_price=initial,
        final_price=final,
        extreme=extreme,
        excursion=excursion,
        frozen_at=frozen_at,
    )


def pullback_depth(drive: Drive, bars: Sequence[Bar]) -> tuple[float, float]:
    if not bars:
        return 0.0, 0.0
    if drive.direction is Direction.LONG:
        depth = drive.extreme - min(float(bar.low) for bar in bars)
    else:
        depth = max(float(bar.high) for bar in bars) - drive.extreme
    depth = max(0.0, depth)
    return depth, depth / drive.excursion


def _validate_post_drive_bars(
    bars: Sequence[Bar],
    config: DrivePullbackConfig,
) -> tuple[Bar, ...]:
    if not 1 <= len(bars) <= config.maximum_post_drive_observation_bars:
        raise ValueError("There are exactly five eligible post-drive bar slots.")
    ordered = tuple(sorted(bars, key=lambda bar: bar.timestamp))
    start = pd.Timestamp(f"2000-01-01 {config.drive_end}")
    expected = tuple(
        (start + pd.Timedelta(5 * index, unit="min")).time()
        for index in range(config.maximum_post_drive_observation_bars)
    )
    if tuple(_clock(bar.timestamp, config) for bar in ordered) != expected[: len(ordered)]:
        raise ValueError("Post-drive bars must begin at 09:45 and remain contiguous.")
    if not all(bar.complete for bar in ordered):
        raise ValueError("Post-drive decision bars must be complete.")
    return ordered


def _has_post_drive_new_extreme(drive: Drive, bars: Sequence[Bar]) -> bool:
    if drive.direction is Direction.LONG:
        return any(float(bar.high) > drive.extreme for bar in bars)
    return any(float(bar.low) < drive.extreme for bar in bars)


def detect_event_outcome(
    symbol: str,
    drive_bars: Sequence[Bar],
    post_drive_bars: Sequence[Bar],
    executable_bars: Sequence[Bar],
    atr20: float,
    config: DrivePullbackConfig,
) -> EventDetectionResult:
    if (
        config.semantic_id("pullback.minimum_distance_formula_id")
        != "ticks_times_symbol_tick_size_v1"
    ):
        raise ValueError("Unsupported minimum pullback-distance formula ID.")
    if (
        config.semantic_id("pullback.post_drive_new_extreme_invalidation.rule_id")
        != "strict_post_drive_new_extreme_exclusion_v1"
        or config.semantic_id(
            "pullback.post_drive_new_extreme_invalidation.intrabar_priority_rule_id"
        )
        != "invalidation_before_pullback_and_confirmation_v1"
    ):
        raise ValueError("Unsupported post-drive invalidation policy ID.")
    if (
        config.semantic_id("confirmation.confirmation_rule_id")
        != "strict_close_beyond_previous_bar_extreme_v1"
        or config.semantic_id("execution.executable_timestamp_rule_id")
        != "first_strictly_later_five_minute_label_v1"
    ):
        raise ValueError("Unsupported confirmation or execution rule ID.")
    tick_size = config.tick_size_for_symbol(symbol)
    drive = build_drive(drive_bars, atr20, config)
    if drive is None:
        return EventDetectionResult(None, "EXCLUDED_DRIVE_THRESHOLD")
    post = _validate_post_drive_bars(post_drive_bars, config)
    if _has_post_drive_new_extreme(drive, post[:1]):
        return EventDetectionResult(None, EXCLUDED_POST_DRIVE_NEW_EXTREME)
    first_depth, first_ratio = pullback_depth(drive, post[:1])
    minimum_pullback_distance = (
        config.minimum_initial_adverse_pullback_ticks * tick_size
    )
    if first_depth + 1e-12 < minimum_pullback_distance:
        return EventDetectionResult(None, EXCLUDED_INITIAL_PULLBACK)
    if first_ratio > config.maximum_normalized_pullback_depth:
        return EventDetectionResult(None, EXCLUDED_MAXIMUM_PULLBACK)
    session_date = _ny(drive_bars[0].timestamp, config).date()
    execution_by_timestamp = {
        _ny(bar.timestamp, config): bar for bar in executable_bars
    }
    for index in range(1, len(post)):
        if _has_post_drive_new_extreme(drive, post[: index + 1]):
            return EventDetectionResult(None, EXCLUDED_POST_DRIVE_NEW_EXTREME)
        depth, ratio = pullback_depth(drive, post[: index + 1])
        if ratio > config.maximum_normalized_pullback_depth:
            return EventDetectionResult(None, EXCLUDED_MAXIMUM_PULLBACK)
        current = post[index]
        previous = post[index - 1]
        confirmed = (
            current.close > previous.high
            if drive.direction is Direction.LONG
            else current.close < previous.low
        )
        if not confirmed:
            continue
        confirmation_timestamp = _ny(current.timestamp, config) + pd.Timedelta(
            5, unit="min"
        )
        latest_confirmation = time.fromisoformat(
            config.latest_confirmation_executable_boundary[0]
        )
        if _clock(confirmation_timestamp, config) > latest_confirmation:
            return EventDetectionResult(None, EXCLUDED_NO_CONFIRMATION)
        # Project convention freezes the next executable bar at the following
        # five-minute label (latest confirmation 10:10 -> latest execution 10:15).
        executable_timestamp = confirmation_timestamp + pd.Timedelta(5, unit="min")
        executable = execution_by_timestamp.get(executable_timestamp)
        latest_executable = time.fromisoformat(
            config.latest_confirmation_executable_boundary[1]
        )
        if (
            executable is None
            or not executable.complete
            or _ny(executable.timestamp, config).date() != session_date
            or _clock(executable.timestamp, config) > latest_executable
        ):
            return EventDetectionResult(None, EXCLUDED_EXECUTABLE_BAR)
        return EventDetectionResult(
            Event(
                hypothesis_id=config.hypothesis_id,
                symbol=symbol.upper(),
                session_date=session_date,
                direction=drive.direction,
                drive=drive,
                pullback_depth=depth,
                pullback_depth_ratio=ratio,
                confirmation_timestamp=confirmation_timestamp,
                executable_timestamp=executable_timestamp,
                executable_price=float(executable.open),
            ),
            None,
        )
    return EventDetectionResult(None, EXCLUDED_NO_CONFIRMATION)


def detect_event(
    symbol: str,
    drive_bars: Sequence[Bar],
    post_drive_bars: Sequence[Bar],
    executable_bars: Sequence[Bar],
    atr20: float,
    config: DrivePullbackConfig,
) -> Event | None:
    return detect_event_outcome(
        symbol,
        drive_bars,
        post_drive_bars,
        executable_bars,
        atr20,
        config,
    ).event


def deduplicate_events(
    events: Iterable[Event],
    config: DrivePullbackConfig,
) -> DeduplicationResult:
    if config.maximum_events_per_symbol_session != 1:
        raise ValueError("Only the approved one-event deduplication policy is supported.")
    grouped: dict[tuple[str, date], list[Event]] = {}
    for event in events:
        grouped.setdefault((event.symbol, event.session_date), []).append(event)
    selected: list[Event] = []
    exclusions: dict[tuple[str, date], str] = {}
    for key, candidates in grouped.items():
        earliest_timestamp = min(event.executable_timestamp for event in candidates)
        earliest = [
            event for event in candidates if event.executable_timestamp == earliest_timestamp
        ]
        if len({event.direction for event in earliest}) > 1:
            exclusions[key] = EXCLUDED_DIRECTION_CONFLICT
            continue
        selected.append(earliest[0])
    return DeduplicationResult(
        events=tuple(sorted(selected, key=lambda item: (item.symbol, item.session_date))),
        exclusions=exclusions,
    )


def oriented_return(direction: Direction, executable_price: float, future_price: float) -> float:
    if executable_price <= 0 or future_price <= 0:
        raise ValueError("Prices must be positive.")
    if direction is Direction.LONG:
        return float(future_price / executable_price - 1)
    return float(executable_price / future_price - 1)


def round_trip_cost(
    symbol: str,
    executable_price: float,
    profile: str,
    config: DrivePullbackConfig,
) -> float:
    if (
        config.semantic_id("costs.round_trip_formula_id")
        != "two_sided_commission_plus_tick_slippage_v1"
    ):
        raise ValueError("Unsupported round-trip cost formula ID.")
    if executable_price <= 0 or not isfinite(executable_price):
        raise ValueError("Executable price must be positive and finite.")
    tick_size = config.tick_size_for_symbol(symbol)
    if profile == "baseline":
        return float(
            2 * config.baseline_commission_per_side
            + 2
            * config.baseline_slippage_ticks_per_execution
            * tick_size
            / executable_price
        )
    if profile == "stress":
        return float(
            2 * config.stress_commission_per_side
            + 2
            * config.stress_slippage_ticks_per_execution
            * tick_size
            / executable_price
        )
    raise ValueError(f"Unknown cost profile: {profile}")


def net_return(
    symbol: str,
    event_return: float,
    executable_price: float,
    profile: str,
    config: DrivePullbackConfig,
) -> float:
    return float(
        event_return - round_trip_cost(symbol, executable_price, profile, config)
    )


def rvol_descriptive(
    current_volume: float,
    prior_approved_volumes: Sequence[float],
    config: DrivePullbackConfig,
) -> float | None:
    if len(prior_approved_volumes) != config.historical_atr_lookback:
        return None
    values = np.asarray(prior_approved_volumes, dtype=float)
    if not np.isfinite(values).all() or np.median(values) <= 0:
        return None
    return float(current_volume / np.median(values))


def matched_unconditional_control(
    events: pd.DataFrame,
    controls: pd.DataFrame,
    config: DrivePullbackConfig,
) -> pd.DataFrame:
    required = {"symbol", "session_date", "executable_timestamp", "horizon", "event_return"}
    if not required.issubset(events.columns) or not required.issubset(controls.columns):
        raise ValueError(f"Events and controls require columns: {sorted(required)}")
    event_rows = events.copy()
    control_rows = controls.copy()
    for frame in (event_rows, control_rows):
        frame["session_date"] = pd.to_datetime(frame["session_date"]).dt.date
        timestamps = pd.to_datetime(frame["executable_timestamp"], utc=True).dt.tz_convert(
            config.timezone
        )
        frame["year"] = frame["session_date"].map(lambda value: value.year)
        frame["executable_hhmm"] = timestamps.dt.strftime("%H:%M")
    values: list[float] = []
    for row in event_rows.itertuples(index=False):
        pool = control_rows[
            (control_rows["symbol"] == row.symbol)
            & (control_rows["year"] == row.year)
            & (control_rows["executable_hhmm"] == row.executable_hhmm)
            & (control_rows["horizon"] == row.horizon)
            & (control_rows["session_date"] != row.session_date)
        ]
        values.append(float(pool["event_return"].mean()) if not pool.empty else np.nan)
    event_rows["unconditional_return"] = values
    event_rows["incremental_return"] = (
        event_rows["event_return"].astype(float) - event_rows["unconditional_return"]
    )
    return event_rows


def _validated_concentration_rows(
    rows: pd.DataFrame,
) -> tuple[pd.DataFrame | None, str | None]:
    required = {"session_date", "incremental_return"}
    if not required.issubset(rows.columns):
        raise ValueError(f"Rows require columns: {sorted(required)}")
    if rows.empty:
        return None, "EMPTY_DECISIONAL_SET"
    if rows["session_date"].isna().any():
        return None, "MISSING_SESSION_DATE"
    try:
        dates = pd.to_datetime(rows["session_date"], errors="raise").dt.date
    except (TypeError, ValueError):
        return None, "INVALID_SESSION_DATE"
    returns = pd.to_numeric(rows["incremental_return"], errors="coerce")
    if not np.isfinite(returns.to_numpy(dtype=float)).all():
        return None, "NONFINITE_INCREMENTAL_RETURN"
    work = rows.copy()
    work["session_date"] = dates
    work["incremental_return"] = returns.astype(float)
    derived_year = work["session_date"].map(lambda value: value.year)
    if "year" in work.columns:
        supplied_year = pd.to_numeric(work["year"], errors="coerce")
        if (
            not np.isfinite(supplied_year.to_numpy(dtype=float)).all()
            or not np.array_equal(supplied_year.to_numpy(dtype=int), derived_year.to_numpy())
        ):
            return None, "INVALID_YEAR"
    work["year"] = derived_year
    return work, None


def annual_concentration(
    rows: pd.DataFrame,
    config: DrivePullbackConfig,
) -> ConcentrationResult:
    if (
        config.semantic_id("annual_concentration.formula_id")
        != "max_abs_annual_contribution_over_sum_abs_v1"
    ):
        raise ValueError("Unsupported annual-concentration formula ID.")
    work, error = _validated_concentration_rows(rows)
    if error is not None or work is None:
        return ConcentrationResult(np.nan, False, error or "INVALID_DATA")
    contributions = work.groupby("year", sort=True)["incremental_return"].sum()
    if set(contributions.index) != {2022, 2023, 2024}:
        return ConcentrationResult(np.nan, False, "MISSING_REQUIRED_YEAR")
    if not np.isfinite(contributions.to_numpy(dtype=float)).all():
        return ConcentrationResult(np.nan, False, "NONFINITE_ANNUAL_CONTRIBUTION")
    denominator = float(contributions.abs().sum())
    if denominator == 0 or not isfinite(denominator):
        return ConcentrationResult(np.nan, False, "ZERO_OR_NONFINITE_DENOMINATOR")
    value = float(contributions.abs().max() / denominator)
    if not isfinite(value):
        return ConcentrationResult(np.nan, False, "NONFINITE_CONCENTRATION")
    passed = value <= config.maximum_annual_effect_concentration
    return ConcentrationResult(
        value,
        passed,
        "PASS" if passed else "ABOVE_CONCENTRATION_LIMIT",
    )


def leave_one_largest_session_out_concentration(
    rows: pd.DataFrame,
    config: DrivePullbackConfig,
) -> LeaveOneSessionOutResult:
    work, error = _validated_concentration_rows(rows)
    if error is not None or work is None:
        return LeaveOneSessionOutResult(np.nan, False, None, error or "INVALID_DATA")
    by_session = work.groupby("session_date", sort=True)["incremental_return"].sum()
    if not np.isfinite(by_session.to_numpy(dtype=float)).all():
        return LeaveOneSessionOutResult(
            np.nan, False, None, "NONFINITE_SESSION_CONTRIBUTION"
        )
    removed = sorted(by_session.index, key=lambda key: (-abs(by_session.loc[key]), key))[0]
    concentration = annual_concentration(
        work[work["session_date"] != removed],
        config,
    )
    return LeaveOneSessionOutResult(
        concentration.value,
        concentration.passed,
        removed,
        concentration.validation_status,
    )


def clustered_percentile_bootstrap(
    rows: pd.DataFrame,
    config: DrivePullbackConfig,
) -> dict[str, tuple[float, float]]:
    if (
        config.semantic_id("bootstrap.method_id")
        != "clustered_session_percentile_bilateral_v1"
    ):
        raise ValueError("Unsupported bootstrap method ID.")
    columns = ("event_return", "incremental_return", "net_return_baseline")
    if "session_date" not in rows.columns or not set(columns).issubset(rows.columns):
        raise ValueError("Bootstrap rows are missing required columns.")
    if (
        rows.empty
        or config.bootstrap_resamples <= 0
        or not 0 < config.bootstrap_confidence_level < 1
    ):
        raise ValueError("Bootstrap requires rows, positive resamples, and 0 < confidence < 1.")
    work = rows.copy()
    work["session_date"] = pd.to_datetime(work["session_date"]).dt.date
    if not np.isfinite(work[list(columns)].to_numpy(dtype=float)).all():
        raise ValueError("Bootstrap inputs must be finite.")
    clusters = [group for _, group in work.groupby("session_date", sort=True)]
    rng = np.random.default_rng(config.bootstrap_seed)
    statistics = {
        column: np.empty(config.bootstrap_resamples, dtype=float) for column in columns
    }
    for index in range(config.bootstrap_resamples):
        sampled_indices = rng.integers(0, len(clusters), size=len(clusters))
        sampled = pd.concat([clusters[item] for item in sampled_indices], ignore_index=True)
        for column in columns:
            statistics[column][index] = float(sampled[column].mean())
    alpha = (1 - config.bootstrap_confidence_level) / 2
    return {
        column: (
            float(np.quantile(values, alpha)),
            float(np.quantile(values, 1 - alpha)),
        )
        for column, values in statistics.items()
    }


def bootstrap_gate(intervals: Mapping[str, tuple[float, float]]) -> bool:
    required = ("event_return", "incremental_return", "net_return_baseline")
    return all(name in intervals and intervals[name][0] > 0 for name in required)


def _finite_positive(value: Any, *, allow_zero: bool = False) -> bool:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return False
    return isfinite(numeric) and (numeric >= 0 if allow_zero else numeric > 0)


def _exact_years(values: Mapping[int, float]) -> bool:
    return set(values) == {2022, 2023, 2024} and all(
        isfinite(float(value)) for value in values.values()
    )


def _minimum_pooled_events(metrics: GateMetrics, config: DrivePullbackConfig) -> bool:
    return metrics.pooled_event_count >= config.minimum_pooled_events


def _minimum_events_per_symbol(
    metrics: GateMetrics, config: DrivePullbackConfig
) -> bool:
    return all(
        metrics.event_count_by_symbol.get(symbol, -1)
        >= config.minimum_events_per_symbol
        for symbol in config.symbols
    )


def _long_positive(metrics: GateMetrics, config: DrivePullbackConfig) -> bool:
    del config
    key = Direction.LONG.value
    return _finite_positive(metrics.direction_mean.get(key)) and _finite_positive(
        metrics.direction_median.get(key)
    )


def _short_positive(metrics: GateMetrics, config: DrivePullbackConfig) -> bool:
    del config
    key = Direction.SHORT.value
    return _finite_positive(metrics.direction_mean.get(key)) and _finite_positive(
        metrics.direction_median.get(key)
    )


def _symbol_means_positive(
    metrics: GateMetrics, config: DrivePullbackConfig
) -> bool:
    return all(
        _finite_positive(metrics.symbol_mean.get(symbol)) for symbol in config.symbols
    )


def _gross_years_positive(
    metrics: GateMetrics, config: DrivePullbackConfig
) -> bool:
    return _exact_years(metrics.annual_gross_mean) and sum(
        value > 0 for value in metrics.annual_gross_mean.values()
    ) >= config.minimum_positive_discovery_years


def _incremental_positive(metrics: GateMetrics, config: DrivePullbackConfig) -> bool:
    del config
    return _finite_positive(metrics.pooled_incremental_mean)


def _baseline_positive(metrics: GateMetrics, config: DrivePullbackConfig) -> bool:
    del config
    return _finite_positive(metrics.pooled_baseline_net_mean)


def _stress_non_negative(metrics: GateMetrics, config: DrivePullbackConfig) -> bool:
    del config
    return _finite_positive(metrics.pooled_stress_net_mean, allow_zero=True)


def _annual_concentration_passes(
    metrics: GateMetrics, config: DrivePullbackConfig
) -> bool:
    return (
        metrics.annual_concentration.passed
        and isfinite(metrics.annual_concentration.value)
        and metrics.annual_concentration.value
        <= config.maximum_annual_effect_concentration
    )


def _loo_concentration_passes(
    metrics: GateMetrics, config: DrivePullbackConfig
) -> bool:
    return (
        metrics.leave_one_session_out_concentration.passed
        and isfinite(metrics.leave_one_session_out_concentration.value)
        and metrics.leave_one_session_out_concentration.value
        <= config.maximum_annual_effect_concentration
    )


def _annual_signs_robust(
    metrics: GateMetrics, config: DrivePullbackConfig
) -> bool:
    return (
        _exact_years(metrics.annual_incremental_signs)
        and _exact_years(metrics.leave_one_out_annual_incremental_signs)
        and sum(value > 0 for value in metrics.annual_incremental_signs.values())
        >= config.minimum_positive_discovery_years
        and sum(
            value > 0
            for value in metrics.leave_one_out_annual_incremental_signs.values()
        )
        >= config.minimum_positive_discovery_years
    )


def _bootstrap_passes(metrics: GateMetrics, config: DrivePullbackConfig) -> bool:
    del config
    return bootstrap_gate(metrics.bootstrap_intervals)


def _causal_integrity(metrics: GateMetrics, config: DrivePullbackConfig) -> bool:
    del config
    return metrics.causal_integrity_passed is True


def _temporal_integrity(metrics: GateMetrics, config: DrivePullbackConfig) -> bool:
    del config
    return metrics.temporal_contamination_absent is True


def _variant_budget(metrics: GateMetrics, config: DrivePullbackConfig) -> bool:
    return metrics.decision_variants == config.decision_variants == 1


CRITERION_IMPLEMENTATIONS = MappingProxyType(
    {
        "minimum_pooled_events": _minimum_pooled_events,
        "minimum_events_per_symbol": _minimum_events_per_symbol,
        "continuation_long_positive_mean_and_median": _long_positive,
        "continuation_short_positive_mean_and_median": _short_positive,
        "qqq_and_spy_positive_primary_means": _symbol_means_positive,
        "gross_mean_positive_in_at_least_two_of_three_years": _gross_years_positive,
        "pooled_incremental_mean_positive": _incremental_positive,
        "pooled_baseline_net_mean_positive": _baseline_positive,
        "pooled_stress_net_mean_non_negative": _stress_non_negative,
        "annual_concentration_at_most_0_70": _annual_concentration_passes,
        "leave_one_session_out_concentration_at_most_0_70": (
            _loo_concentration_passes
        ),
        "annual_signs_positive_in_at_least_two_of_three_years_original_and_leave_one_out": (
            _annual_signs_robust
        ),
        "all_three_bootstrap_lower_bounds_strictly_positive": _bootstrap_passes,
        "no_lookahead_or_unresolved_data_quality_failure": _causal_integrity,
        "no_2025_or_2026_contamination": _temporal_integrity,
        "one_variant_budget_respected": _variant_budget,
    }
)


def derive_gate_criteria(
    metrics: GateMetrics,
    config: DrivePullbackConfig,
) -> dict[str, bool]:
    if not isinstance(metrics, GateMetrics):
        raise TypeError("Gate decisions require GateMetrics, not caller-supplied booleans.")
    if metrics.primary_horizon_minutes != config.primary_horizon_minutes:
        raise ValueError(
            "Gate metrics must match the configured indivisible primary horizon "
            f"of {config.primary_horizon_minutes} minutes."
        )
    if (
        config.semantic_id("discovery_gate.evaluation_rule_id")
        != "derive_all_required_from_metrics_v1"
    ):
        raise ValueError("Unsupported gate evaluation-rule ID.")
    return {
        criterion_id: bool(CRITERION_IMPLEMENTATIONS[criterion_id](metrics, config))
        for criterion_id in config.gate_criteria
    }


def evaluate_gate(
    metrics: GateMetrics,
    config: DrivePullbackConfig,
) -> GateResult:
    normalized = derive_gate_criteria(metrics, config)
    gate = config.canonical_spec["discovery_gate"]
    passed = all(normalized.values()) if config.gate_all_required else any(normalized.values())
    return GateResult(
        criteria=normalized,
        all_required=config.gate_all_required,
        passed=passed,
        classification=(
            str(gate["pass_classification"])
            if passed
            else str(gate["failure_classification"])
        ),
        validation_2025_unlocked=bool(
            gate[
                "pass_validation_2025_unlocked"
                if passed
                else "fail_validation_2025_unlocked"
            ]
        ),
        paper_eligible=bool(gate["paper_eligible"]),
        live_eligible=bool(gate["live_eligible"]),
    )


def validate_research_parameters(
    values: Mapping[str, Any],
    config: DrivePullbackConfig,
) -> None:
    if set(values) != set(FROZEN_CONSTANT_NAMES):
        raise ValueError("Research parameters must contain exactly the 17 approved names.")
    if dict(values) != config.research_parameters():
        raise ValueError("Research parameters differ from the validated configuration.")


def canonical_payload(config: DrivePullbackConfig) -> dict[str, Any]:
    payload = config.canonical_mapping()
    payload.pop("canonical_payload_hash")
    return payload


def _without_external_fields(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            key: _without_external_fields(item)
            for key, item in value.items()
            if key not in EXPLICIT_NON_METHODOLOGICAL_FIELDS
        }
    if isinstance(value, (list, tuple)):
        return [_without_external_fields(item) for item in value]
    return value


def canonical_payload_bytes(payload: Mapping[str, Any]) -> bytes:
    value = _without_external_fields(payload)
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def canonical_payload_hash(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_payload_bytes(payload)).hexdigest()
