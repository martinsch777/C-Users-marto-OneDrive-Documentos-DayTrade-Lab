from __future__ import annotations

import copy
import inspect
import unittest
from dataclasses import MISSING, replace
from datetime import date, timedelta
from functools import partial
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
import src.research.hyp_drive_pb_01 as drive_module

from src.research.hyp_drive_pb_01 import (
    APPROVED_GATE_CRITERION_IDS,
    FROZEN_CONSTANT_NAMES,
    EXCLUDED_DIRECTION_CONFLICT,
    EXCLUDED_POST_DRIVE_NEW_EXTREME,
    Bar,
    ConcentrationResult,
    DailyRTHSession,
    Direction,
    DrivePullbackConfig,
    GateMetrics,
    LeaveOneSessionOutResult,
    annual_concentration,
    atr20_prior,
    bootstrap_gate,
    build_drive,
    canonical_payload,
    canonical_payload_hash,
    classify_yaml_leaf_paths,
    clustered_percentile_bootstrap,
    config_from_mapping,
    deduplicate_events,
    detect_event,
    detect_event_outcome,
    derive_gate_criteria,
    evaluate_gate,
    leave_one_largest_session_out_concentration,
    matched_unconditional_control,
    net_return,
    oriented_return,
    pullback_depth,
    round_trip_cost,
    rvol_descriptive,
    true_range,
    validate_drive_window,
    validate_research_parameters,
    yaml_leaf_paths,
)


ROOT = Path(__file__).resolve().parents[1]
YAML_PATH = ROOT / "configs/research/hypotheses/HYP-DRIVE-PB-01.yaml"
YAML_MAPPING = yaml.safe_load(YAML_PATH.read_text(encoding="utf-8"))
CONFIG = config_from_mapping(YAML_MAPPING)

# Existing behavioral tests bind the same explicit YAML-derived configuration.
_round_trip_cost = round_trip_cost
_net_return = net_return
_canonical_payload_hash = canonical_payload_hash


def mapping_with_recomputed_hash(mapping):
    changed = copy.deepcopy(mapping)
    changed["canonical_payload_hash"] = "0" * 64
    unchecked = drive_module._build_config(changed)
    changed["canonical_payload_hash"] = _canonical_payload_hash(
        drive_module.canonical_payload(unchecked)
    )
    return changed


def leaf_key_paths(value, path=()):
    if isinstance(value, dict):
        for key in sorted(value):
            yield from leaf_key_paths(value[key], (*path, key))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from leaf_key_paths(item, (*path, index))
    else:
        yield path, value


def set_nested(value, path, replacement):
    cursor = value
    for key in path[:-1]:
        cursor = cursor[key]
    cursor[path[-1]] = replacement


def changed_same_type(value):
    if isinstance(value, bool):
        return not value
    if isinstance(value, int):
        return value + 1
    if isinstance(value, float):
        return value + 0.001
    if isinstance(value, str):
        return value + "_changed"
    if value is None:
        return "changed"
    raise TypeError(type(value))


def dotted_leaf_path(path):
    rendered = "$"
    for key in path:
        rendered += f"[{key}]" if isinstance(key, int) else f".{key}"
    return rendered
validate_drive_window = partial(validate_drive_window, config=CONFIG)
atr20_prior = partial(atr20_prior, config=CONFIG)
build_drive = partial(build_drive, config=CONFIG)
detect_event = partial(detect_event, config=CONFIG)
detect_event_outcome = partial(detect_event_outcome, config=CONFIG)
deduplicate_events = partial(deduplicate_events, config=CONFIG)
rvol_descriptive = partial(rvol_descriptive, config=CONFIG)
matched_unconditional_control = partial(matched_unconditional_control, config=CONFIG)
annual_concentration = partial(annual_concentration, config=CONFIG)
leave_one_largest_session_out_concentration = partial(
    leave_one_largest_session_out_concentration, config=CONFIG
)
clustered_percentile_bootstrap = partial(clustered_percentile_bootstrap, config=CONFIG)
derive_gate_criteria = partial(derive_gate_criteria, config=CONFIG)
evaluate_gate = partial(evaluate_gate, config=CONFIG)
canonical_payload = partial(canonical_payload, config=CONFIG)


def round_trip_cost(executable_price, profile, config=CONFIG, symbol="QQQ"):
    return _round_trip_cost(symbol, executable_price, profile, config)


def net_return(event_return, executable_price, profile, config=CONFIG, symbol="QQQ"):
    return _net_return(symbol, event_return, executable_price, profile, config)


def canonical_payload_hash(payload=None):
    return _canonical_payload_hash(canonical_payload() if payload is None else payload)


def ts(clock: str, day: str = "2024-06-03") -> pd.Timestamp:
    return pd.Timestamp(f"{day} {clock}", tz="America/New_York")


def bar(
    clock: str,
    open_: float,
    high: float,
    low: float,
    close: float,
    *,
    day: str = "2024-06-03",
    complete: bool = True,
    volume: float = 100.0,
) -> Bar:
    return Bar(ts(clock, day), open_, high, low, close, volume, complete)


def long_drive(displacement: float = 10.0) -> list[Bar]:
    return [
        bar("09:30", 100, 104, 99.5, 103),
        bar("09:35", 103, 108, 102, 107),
        bar("09:40", 107, 111, 106, 100 + displacement),
    ]


def short_drive(displacement: float = -10.0) -> list[Bar]:
    return [
        bar("09:30", 100, 100.5, 96, 97),
        bar("09:35", 97, 98, 92, 93),
        bar("09:40", 93, 94, 89, 100 + displacement),
    ]


def long_post(confirm_at: str = "09:50") -> list[Bar]:
    clocks = ["09:45", "09:50", "09:55", "10:00", "10:05"]
    bars = [bar("09:45", 110, 110.5, 109.99, 110.2)]
    for clock in clocks[1:]:
        if clock == confirm_at:
            bars.append(bar(clock, 110.5, 110.9, 110.0, 110.7))
        else:
            bars.append(bar(clock, 110.4, 110.6, 110.0, 110.5))
    return bars


def short_post() -> list[Bar]:
    return [
        bar("09:45", 90, 90.01, 89.5, 89.8),
        bar("09:50", 89.8, 90.0, 89.1, 89.3),
    ]


class ConfigurationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.mapping = copy.deepcopy(YAML_MAPPING)
        cls.config = CONFIG

    def test_identity_status_freeze_and_variant(self) -> None:
        self.assertEqual(self.config.hypothesis_id, "HYP-DRIVE-PB-01")
        self.assertEqual(self.config.status, "preregistered_not_executed")
        self.assertEqual(
            self.config.conceptual_design_freeze_commit,
            "925cede00f3d9c1b4de46e225f98d4636c19a831",
        )
        self.assertEqual(
            self.config.implementation_clarification_freeze_commit,
            "764478b86a01619620166848204e527f2fb55c55",
        )
        self.assertEqual(self.config.decision_variants, 1)

    def test_all_decisions_approved(self) -> None:
        approved = self.config.canonical_spec["approval"]["approved_decisions"]
        self.assertEqual(len(approved), 15)
        self.assertEqual(
            self.mapping["approval"]["approved_decisions"], list(approved)
        )
        self.assertEqual(self.mapping["approval"]["status"], "approved")

    def test_exactly_seventeen_named_constants(self) -> None:
        self.assertEqual(len(FROZEN_CONSTANT_NAMES), 17)
        self.assertEqual(set(FROZEN_CONSTANT_NAMES), set(CONFIG.research_parameters()))
        self.assertNotIn("tick_size_by_symbol", FROZEN_CONSTANT_NAMES)
        loaded = CONFIG.research_parameters()
        validate_research_parameters(loaded, CONFIG)

    def test_missing_or_extra_constant_fails(self) -> None:
        values = CONFIG.research_parameters()
        values.pop("drive_start")
        with self.assertRaises(ValueError):
            validate_research_parameters(values, CONFIG)
        values = CONFIG.research_parameters()
        values["unapproved"] = 1
        with self.assertRaises(ValueError):
            validate_research_parameters(values, CONFIG)

    def test_yaml_is_single_source_and_config_has_no_decisional_defaults(self) -> None:
        for field_name in FROZEN_CONSTANT_NAMES:
            self.assertEqual(
                DrivePullbackConfig.__dataclass_fields__[field_name].default,
                MISSING,
            )
        self.assertFalse(hasattr(CONFIG, "primary_horizon"))
        self.assertFalse(hasattr(CONFIG, "tick_size"))
        self.assertEqual(CONFIG.primary_horizon_label, "30min")
        self.assertEqual(dict(CONFIG.tick_size_by_symbol), {"QQQ": 0.01, "SPY": 0.01})
        self.assertEqual(self.mapping["research_parameters"]["count"], 17)
        self.assertEqual(self.mapping["frozen_market_conventions"]["count"], 1)

    def test_missing_or_unknown_research_field_is_rejected(self) -> None:
        missing = copy.deepcopy(self.mapping)
        missing["research_parameters"]["values"].pop("drive_start")
        with self.assertRaises(ValueError):
            config_from_mapping(missing)
        unknown = copy.deepcopy(self.mapping)
        unknown["research_parameters"]["values"]["unapproved"] = 1
        with self.assertRaises(ValueError):
            config_from_mapping(unknown)
        unknown_top_level = copy.deepcopy(self.mapping)
        unknown_top_level["tick_size"] = 0.02
        with self.assertRaises(ValueError):
            config_from_mapping(unknown_top_level)

    def test_wrong_type_range_and_tick_symbol_are_rejected(self) -> None:
        wrong_type = copy.deepcopy(self.mapping)
        wrong_type["research_parameters"]["values"]["bootstrap_resamples"] = "10000"
        with self.assertRaises(ValueError):
            config_from_mapping(wrong_type)
        out_of_range = copy.deepcopy(self.mapping)
        out_of_range["research_parameters"]["values"][
            "maximum_normalized_pullback_depth"
        ] = 1.1
        with self.assertRaises(ValueError):
            config_from_mapping(mapping_with_recomputed_hash(out_of_range))
        unknown_tick = copy.deepcopy(self.mapping)
        unknown_tick["frozen_market_conventions"]["tick_size_by_symbol"][
            "IWM"
        ] = 0.01
        with self.assertRaises(ValueError):
            config_from_mapping(unknown_tick)

    def test_no_second_value_table_and_explicit_config_signatures(self) -> None:
        self.assertFalse(hasattr(drive_module, "FROZEN_CONSTANTS"))
        for function in (
            drive_module.build_drive,
            drive_module.detect_event,
            drive_module.clustered_percentile_bootstrap,
            drive_module.evaluate_gate,
            drive_module.canonical_payload,
        ):
            self.assertIs(
                inspect.signature(function).parameters["config"].default,
                inspect.Parameter.empty,
            )

    def test_modified_mapping_changes_config_label_and_hash(self) -> None:
        changed_mapping = copy.deepcopy(self.mapping)
        changed_mapping["research_parameters"]["values"][
            "primary_horizon_minutes"
        ] = 15
        changed = config_from_mapping(mapping_with_recomputed_hash(changed_mapping))
        self.assertEqual(changed.primary_horizon_label, "15min")
        self.assertNotEqual(
            canonical_payload_hash(),
            _canonical_payload_hash(drive_module.canonical_payload(changed)),
        )

    def test_independent_primary_label_is_rejected(self) -> None:
        changed_mapping = copy.deepcopy(self.mapping)
        changed_mapping["horizons"]["primary"] = "30min"
        with self.assertRaises(ValueError):
            config_from_mapping(changed_mapping)

    def test_all_safety_flags_false(self) -> None:
        self.assertTrue(self.config.safety_flags)
        self.assertTrue(
            all(value is False for value in self.config.safety_flags.values())
        )
        self.assertEqual(
            self.mapping["safety_flags"], dict(self.config.safety_flags)
        )

    def test_temporal_state_is_locked(self) -> None:
        splits = self.mapping["temporal_splits"]
        self.assertEqual(splits["discovery"]["start"], "2022-01-01")
        self.assertEqual(splits["discovery"]["end"], "2024-12-31")
        self.assertFalse(splits["validation_2025"]["unlocked"])
        self.assertTrue(splits["historical_2026"]["contaminated"])
        self.assertFalse(splits["historical_2026"]["decisional"])

    def test_declared_hash_is_required_and_strictly_validated(self) -> None:
        wrong = copy.deepcopy(self.mapping)
        wrong["canonical_payload_hash"] = "0" * 64
        with self.assertRaises(ValueError):
            config_from_mapping(wrong)
        missing = copy.deepcopy(self.mapping)
        missing.pop("canonical_payload_hash")
        with self.assertRaises(ValueError):
            config_from_mapping(missing)
        self.assertNotIn("canonical_payload_hash", canonical_payload())

    def test_previous_audit_bypasses_are_rejected(self) -> None:
        mutations = (
            ("status", lambda value: value.__setitem__("status", "executed")),
            (
                "single_source_of_truth",
                lambda value: value["configuration_governance"].__setitem__(
                    "single_source_of_truth", "csv_v1"
                ),
            ),
            (
                "pullback_formula",
                lambda value: value["pullback"].__setitem__(
                    "minimum_distance_formula_id", "unknown"
                ),
            ),
            (
                "horizon_derivation",
                lambda value: value["horizons"].__setitem__(
                    "primary_label_derivation_id", "unknown"
                ),
            ),
            (
                "cost_formula",
                lambda value: value["costs"].__setitem__(
                    "round_trip_formula_id", "unknown"
                ),
            ),
            (
                "safety",
                lambda value: value["safety_flags"].__setitem__(
                    "broker_connected", True
                ),
            ),
            (
                "forbidden_action",
                lambda value: value["forbidden_actions"].pop(),
            ),
        )
        for label, mutate in mutations:
            changed = copy.deepcopy(self.mapping)
            mutate(changed)
            with self.assertRaises(ValueError, msg=label):
                config_from_mapping(changed)

    def test_gate_list_is_exact_unique_and_ordered(self) -> None:
        mutations = []
        missing = copy.deepcopy(self.mapping)
        missing["discovery_gate"]["criteria"].pop()
        mutations.append(missing)
        duplicate = copy.deepcopy(self.mapping)
        duplicate["discovery_gate"]["criteria"][-1] = duplicate[
            "discovery_gate"
        ]["criteria"][0]
        mutations.append(duplicate)
        unknown = copy.deepcopy(self.mapping)
        unknown["discovery_gate"]["criteria"][-1] = "unknown"
        mutations.append(unknown)
        reordered = copy.deepcopy(self.mapping)
        reordered["discovery_gate"]["criteria"][0:2] = reversed(
            reordered["discovery_gate"]["criteria"][0:2]
        )
        mutations.append(reordered)
        for changed in mutations:
            with self.assertRaises(ValueError):
                config_from_mapping(changed)

    def test_cost_values_are_configured_and_hash_sensitive(self) -> None:
        commission_mapping = copy.deepcopy(self.mapping)
        commission_mapping["costs"]["baseline"]["commission_per_side"] = 0.00015
        commission = config_from_mapping(
            mapping_with_recomputed_hash(commission_mapping)
        )
        slippage_mapping = copy.deepcopy(self.mapping)
        slippage_mapping["costs"]["baseline"][
            "slippage_ticks_per_execution"
        ] = 2
        slippage = config_from_mapping(mapping_with_recomputed_hash(slippage_mapping))
        baseline_hash = canonical_payload_hash()
        self.assertNotEqual(
            _round_trip_cost("QQQ", 100, "baseline", CONFIG),
            _round_trip_cost("QQQ", 100, "baseline", commission),
        )
        self.assertNotEqual(
            _round_trip_cost("QQQ", 100, "baseline", CONFIG),
            _round_trip_cost("QQQ", 100, "baseline", slippage),
        )
        self.assertNotEqual(
            baseline_hash,
            _canonical_payload_hash(drive_module.canonical_payload(commission)),
        )
        self.assertNotEqual(
            baseline_hash,
            _canonical_payload_hash(drive_module.canonical_payload(slippage)),
        )

    def test_every_yaml_leaf_is_classified_and_payload_covered(self) -> None:
        source_leaves = yaml_leaf_paths(self.mapping)
        classifications = classify_yaml_leaf_paths(self.mapping)
        payload_leaves = yaml_leaf_paths(canonical_payload())
        self.assertEqual(set(source_leaves), set(classifications))
        self.assertEqual(
            {
                path
                for path, classification in classifications.items()
                if classification == "declared_integrity_metadata"
            },
            {"$.canonical_payload_hash"},
        )
        included = {
            path
            for path, classification in classifications.items()
            if classification == "canonical_payload_included"
        }
        self.assertTrue(included.issubset(payload_leaves))
        self.assertFalse(
            set(classifications.values())
            - {
                "canonical_payload_included",
                "declared_integrity_metadata",
                "explicitly_non_methodological_excluded",
            }
        )

    def test_config_isolated_from_source_mapping_mutation(self) -> None:
        source = copy.deepcopy(self.mapping)
        config = config_from_mapping(source)
        source["frozen_market_conventions"]["tick_size_by_symbol"]["QQQ"] = 9.99
        self.assertEqual(config.tick_size_for_symbol("QQQ"), 0.01)

    def test_every_frozen_yaml_leaf_rejects_same_type_mutation(self) -> None:
        mutable = drive_module._mutable_canonical_leaf_paths()
        for key_path, value in leaf_key_paths(self.mapping):
            dotted = dotted_leaf_path(key_path)
            if dotted in mutable or dotted == "$.canonical_payload_hash":
                continue
            changed = copy.deepcopy(self.mapping)
            set_nested(changed, key_path, changed_same_type(value))
            with self.assertRaises(ValueError, msg=dotted):
                config_from_mapping(changed)


class DriveAndAtrTests(unittest.TestCase):
    def test_exact_drive_window_and_three_bars(self) -> None:
        self.assertEqual(len(validate_drive_window(long_drive())), 3)
        with self.assertRaises(ValueError):
            validate_drive_window(long_drive()[:2])

    def test_missing_or_incomplete_drive_bar_rejected(self) -> None:
        missing = [long_drive()[0], long_drive()[2]]
        with self.assertRaises(ValueError):
            validate_drive_window(missing)
        bars = long_drive()
        bars[1] = replace(bars[1], complete=False)
        with self.assertRaises(ValueError):
            validate_drive_window(bars)

    def test_long_short_displacement_symmetry(self) -> None:
        long = build_drive(long_drive(), 40)
        short = build_drive(short_drive(), 40)
        assert long and short
        self.assertEqual(long.displacement, -short.displacement)
        self.assertEqual(long.oriented_displacement, short.oriented_displacement)
        self.assertEqual(long.direction, Direction.LONG)
        self.assertEqual(short.direction, Direction.SHORT)

    def test_drive_threshold_boundaries(self) -> None:
        self.assertIsNone(build_drive(long_drive(9.99), 40))
        self.assertIsNotNone(build_drive(long_drive(10.0), 40))
        self.assertIsNotNone(build_drive(long_drive(10.01), 40))
        self.assertIsNone(build_drive(short_drive(-9.99), 40))
        self.assertIsNotNone(build_drive(short_drive(-10.0), 40))

    def test_true_range(self) -> None:
        self.assertEqual(true_range(12, 8, 9), 4)
        self.assertEqual(true_range(12, 10, 8), 4)
        self.assertEqual(true_range(10, 8, 12), 4)

    def test_atr20_arithmetic_mean_and_shift(self) -> None:
        sessions = [
            DailyRTHSession(date(2024, 1, index + 1), 11 + index, 9 + index, 10 + index)
            for index in range(21)
        ]
        self.assertEqual(atr20_prior(sessions, date(2024, 2, 1)), 2.0)

    def test_atr_current_session_excluded(self) -> None:
        sessions = [
            DailyRTHSession(date(2024, 1, index + 1), 11 + index, 9 + index, 10 + index)
            for index in range(21)
        ]
        sessions.append(DailyRTHSession(date(2024, 2, 1), 1000, 0, 500))
        self.assertEqual(atr20_prior(sessions, date(2024, 2, 1)), 2.0)

    def test_excluded_sessions_omitted_without_imputation(self) -> None:
        sessions = [
            DailyRTHSession(date(2024, 1, index + 1), 11 + index, 9 + index, 10 + index)
            for index in range(22)
        ]
        sessions[5] = replace(sessions[5], approved=False, high=1000, low=0)
        # The omitted session contributes nothing. The next approved session
        # correctly spans from the prior approved close, producing one TR of 3.
        self.assertEqual(atr20_prior(sessions, date(2024, 2, 1)), 2.05)

    def test_fewer_than_twenty_true_ranges_excludes(self) -> None:
        sessions = [
            DailyRTHSession(date(2024, 1, index + 1), 11 + index, 9 + index, 10 + index)
            for index in range(20)
        ]
        self.assertIsNone(atr20_prior(sessions, date(2024, 2, 1)))

    def test_previous_close_is_derived_and_row_order_is_irrelevant(self) -> None:
        start = date(2024, 1, 1)
        sessions = [
            DailyRTHSession(
                start + timedelta(days=index),
                11 + index,
                9 + index,
                10 + index,
            )
            for index in range(21)
        ]
        self.assertEqual(atr20_prior(sessions, date(2024, 2, 1)), 2.0)
        self.assertEqual(atr20_prior(list(reversed(sessions)), date(2024, 2, 1)), 2.0)

    def test_previous_close_override_is_not_accepted(self) -> None:
        with self.assertRaises(TypeError):
            DailyRTHSession(
                date(2024, 1, 1),
                101,
                99,
                100,
                previous_approved_close=1000,  # type: ignore[call-arg]
            )

    def test_duplicate_or_contradictory_daily_rows_are_rejected(self) -> None:
        sessions = [
            DailyRTHSession(date(2024, 1, 1), 101, 99, 100),
            DailyRTHSession(date(2024, 1, 1), 1000, 1, 500),
        ]
        with self.assertRaises(ValueError):
            atr20_prior(sessions, date(2024, 2, 1))

    def test_audited_extreme_injection_cannot_change_atr20(self) -> None:
        start = date(2024, 1, 1)
        sessions = [
            DailyRTHSession(start + timedelta(days=index), 101, 99, 100)
            for index in range(21)
        ]
        self.assertEqual(atr20_prior(sessions, date(2024, 2, 1)), 2.0)


class ExtremePullbackAndTimingTests(unittest.TestCase):
    @staticmethod
    def exact_long_pullback(depth: float) -> list[Bar]:
        first_high = 111 - depth / 2
        return [
            bar("09:45", first_high, first_high, 111 - depth, first_high),
            bar("09:50", first_high, 111, 111 - depth, first_high + depth / 4),
        ]

    @staticmethod
    def exact_short_pullback(depth: float) -> list[Bar]:
        first_low = 89 + depth / 2
        return [
            bar("09:45", first_low, 89 + depth, first_low, first_low),
            bar("09:50", first_low, 89 + depth, 89, first_low - depth / 4),
        ]

    def detect_exact_pullback(
        self,
        symbol: str,
        depth: float,
        config: DrivePullbackConfig,
        direction: Direction = Direction.LONG,
    ):
        if direction is Direction.LONG:
            drive_bars = long_drive()
            posts = self.exact_long_pullback(depth)
            execution = bar("10:00", 111, 112, 110, 111)
        else:
            drive_bars = short_drive()
            posts = self.exact_short_pullback(depth)
            execution = bar("10:00", 89, 90, 88, 89)
        return detect_event.func(
            symbol,
            drive_bars,
            posts,
            [execution],
            40,
            config,
        )

    def test_minimum_pullback_ticks_control_behavior_and_boundaries(self) -> None:
        two_ticks = replace(CONFIG, minimum_initial_adverse_pullback_ticks=2)
        self.assertIsNotNone(self.detect_exact_pullback("QQQ", 0.01, CONFIG))
        self.assertIsNone(self.detect_exact_pullback("QQQ", 0.009, CONFIG))
        self.assertIsNone(self.detect_exact_pullback("QQQ", 0.01, two_ticks))
        self.assertIsNotNone(self.detect_exact_pullback("QQQ", 0.02, two_ticks))
        self.assertIsNotNone(self.detect_exact_pullback("QQQ", 0.03, two_ticks))

    def test_minimum_pullback_ticks_are_long_short_symmetric(self) -> None:
        two_ticks = replace(CONFIG, minimum_initial_adverse_pullback_ticks=2)
        self.assertIsNotNone(
            self.detect_exact_pullback(
                "SPY", 0.02, two_ticks, direction=Direction.SHORT
            )
        )
        self.assertIsNone(
            self.detect_exact_pullback(
                "SPY", 0.01, two_ticks, direction=Direction.SHORT
            )
        )

    def test_tick_convention_resolves_symbols_and_rejects_unknown(self) -> None:
        self.assertEqual(CONFIG.tick_size_for_symbol("QQQ"), 0.01)
        self.assertEqual(CONFIG.tick_size_for_symbol("SPY"), 0.01)
        with self.assertRaises(ValueError):
            CONFIG.tick_size_for_symbol("IWM")
        with self.assertRaises(ValueError):
            self.detect_exact_pullback("IWM", 0.01, CONFIG)

    def test_changed_minimum_ticks_changes_behavior_and_hash(self) -> None:
        changed = replace(CONFIG, minimum_initial_adverse_pullback_ticks=2)
        self.assertIsNotNone(self.detect_exact_pullback("QQQ", 0.01, CONFIG))
        self.assertIsNone(self.detect_exact_pullback("QQQ", 0.01, changed))
        self.assertNotEqual(
            canonical_payload_hash(),
            _canonical_payload_hash(drive_module.canonical_payload(changed)),
        )

    def test_extreme_frozen_and_excursion_from_open(self) -> None:
        long = build_drive(long_drive(), 40)
        short = build_drive(short_drive(), 40)
        assert long and short
        self.assertEqual(long.extreme, 111)
        self.assertEqual(long.excursion, 11)
        self.assertEqual(short.extreme, 89)
        self.assertEqual(short.excursion, 11)
        self.assertEqual(long.frozen_at.strftime("%H:%M"), "09:45")

    def test_later_post_drive_extreme_does_not_change_drive(self) -> None:
        drive = build_drive(long_drive(), 40)
        assert drive
        original = drive.extreme
        pullback_depth(drive, [bar("09:45", 110, 200, 109.99, 110)])
        self.assertEqual(drive.extreme, original)

    def test_minimum_tick_and_half_depth_boundaries(self) -> None:
        drive = build_drive(long_drive(), 40)
        assert drive
        depth, ratio = pullback_depth(drive, [bar("09:45", 111, 111, 110.99, 111)])
        self.assertAlmostEqual(depth, 0.01)
        self.assertLess(ratio, 0.50)
        half = bar("09:45", 108, 108, 105.5, 106)
        self.assertEqual(pullback_depth(drive, [half])[1], 0.50)

    def test_less_than_tick_rejected(self) -> None:
        posts = [bar("09:45", 111, 111, 110.995, 111), *long_post()[1:2]]
        self.assertIsNone(detect_event("QQQ", long_drive(), posts, [bar("10:00", 111, 112, 110, 111)], 40))

    def test_more_than_half_invalidates_immediately(self) -> None:
        posts = [bar("09:45", 106, 106, 105.49, 106), *long_post()[1:2]]
        self.assertIsNone(detect_event("QQQ", long_drive(), posts, [bar("10:00", 111, 112, 110, 111)], 40))

    def test_later_half_depth_violation_is_permanent(self) -> None:
        posts = long_post()
        posts[1] = bar("09:50", 106, 110.9, 105.49, 110.7)
        self.assertIsNone(detect_event("QQQ", long_drive(), posts[:2], [bar("10:00", 111, 112, 110, 111)], 40))

    def test_first_post_drive_bar_cannot_confirm(self) -> None:
        self.assertIsNone(
            detect_event("QQQ", long_drive(), long_post()[:1], [bar("09:55", 111, 112, 110, 111)], 40)
        )

    def test_strict_long_confirmation_and_next_open_execution(self) -> None:
        event = detect_event(
            "QQQ",
            long_drive(),
            long_post()[:2],
            [bar("10:00", 111.25, 112, 111, 111.5)],
            40,
        )
        assert event
        self.assertEqual(event.confirmation_timestamp.strftime("%H:%M"), "09:55")
        self.assertEqual(event.executable_timestamp.strftime("%H:%M"), "10:00")
        self.assertEqual(event.executable_price, 111.25)

    def test_long_equality_does_not_confirm(self) -> None:
        posts = long_post()[:2]
        posts[1] = replace(posts[1], close=posts[0].high, high=posts[0].high)
        self.assertIsNone(detect_event("QQQ", long_drive(), posts, [bar("10:00", 111, 112, 110, 111)], 40))

    def test_strict_short_confirmation_and_symmetry(self) -> None:
        event = detect_event(
            "SPY",
            short_drive(),
            short_post(),
            [bar("10:00", 88.8, 89, 88, 88.5)],
            40,
        )
        assert event
        self.assertEqual(event.direction, Direction.SHORT)
        posts = short_post()
        posts[1] = replace(posts[1], close=posts[0].low, low=posts[0].low)
        self.assertIsNone(detect_event("SPY", short_drive(), posts, [bar("10:00", 89, 90, 88, 89)], 40))

    def test_long_new_extreme_strict_boundary_and_counterexample(self) -> None:
        equal_posts = long_post()[:2]
        equal_posts[0] = replace(equal_posts[0], high=111)
        equal_outcome = detect_event_outcome(
            "QQQ",
            long_drive(),
            equal_posts,
            [bar("10:00", 111, 112, 110, 111)],
            40,
        )
        self.assertNotEqual(
            equal_outcome.exclusion_reason,
            EXCLUDED_POST_DRIVE_NEW_EXTREME,
        )
        higher_posts = long_post()[:2]
        higher_posts[0] = replace(higher_posts[0], high=112)
        outcome = detect_event_outcome(
            "QQQ",
            long_drive(),
            higher_posts,
            [bar("10:00", 111, 112, 110, 111)],
            40,
        )
        self.assertIsNone(outcome.event)
        self.assertEqual(outcome.exclusion_reason, EXCLUDED_POST_DRIVE_NEW_EXTREME)

    def test_short_new_extreme_strict_boundary(self) -> None:
        equal_posts = short_post()
        equal_posts[0] = replace(equal_posts[0], low=89)
        equal_outcome = detect_event_outcome(
            "SPY",
            short_drive(),
            equal_posts,
            [bar("10:00", 89, 90, 88, 89)],
            40,
        )
        self.assertNotEqual(
            equal_outcome.exclusion_reason,
            EXCLUDED_POST_DRIVE_NEW_EXTREME,
        )
        lower_posts = short_post()
        lower_posts[0] = replace(lower_posts[0], low=88.99)
        outcome = detect_event_outcome(
            "SPY",
            short_drive(),
            lower_posts,
            [bar("10:00", 89, 90, 88, 89)],
            40,
        )
        self.assertIsNone(outcome.event)
        self.assertEqual(outcome.exclusion_reason, EXCLUDED_POST_DRIVE_NEW_EXTREME)

    def test_new_extreme_has_priority_over_pullback_and_confirmation(self) -> None:
        first_bar_ambiguous = long_post()[:2]
        first_bar_ambiguous[0] = bar("09:45", 110, 112, 109, 110.2)
        first = detect_event_outcome(
            "QQQ",
            long_drive(),
            first_bar_ambiguous,
            [bar("10:00", 111, 112, 110, 111)],
            40,
        )
        self.assertEqual(first.exclusion_reason, EXCLUDED_POST_DRIVE_NEW_EXTREME)

        confirmation_ambiguous = long_post()[:2]
        confirmation_ambiguous[1] = bar("09:50", 110.2, 112, 110, 111.5)
        second = detect_event_outcome(
            "QQQ",
            long_drive(),
            confirmation_ambiguous,
            [bar("10:00", 111, 112, 110, 111)],
            40,
        )
        self.assertEqual(second.exclusion_reason, EXCLUDED_POST_DRIVE_NEW_EXTREME)

    def test_five_bars_allowed_six_rejected_and_latest_execution_1015(self) -> None:
        event = detect_event(
            "QQQ",
            long_drive(),
            long_post("10:05"),
            [bar("10:15", 112, 113, 111, 112)],
            40,
        )
        assert event
        self.assertEqual(event.confirmation_timestamp.strftime("%H:%M"), "10:10")
        self.assertEqual(event.executable_timestamp.strftime("%H:%M"), "10:15")
        with self.assertRaises(ValueError):
            detect_event(
                "QQQ",
                long_drive(),
                [*long_post("10:05"), bar("10:10", 112, 113, 111, 112)],
                [bar("10:20", 112, 113, 111, 112)],
                40,
            )

    def test_missing_incomplete_or_overnight_execution_excludes(self) -> None:
        posts = long_post()[:2]
        self.assertIsNone(detect_event("QQQ", long_drive(), posts, [], 40))
        incomplete = bar("10:00", 111, 112, 110, 111, complete=False)
        self.assertIsNone(detect_event("QQQ", long_drive(), posts, [incomplete], 40))
        next_day = bar("10:00", 111, 112, 110, 111, day="2024-06-04")
        self.assertIsNone(detect_event("QQQ", long_drive(), posts, [next_day], 40))

    def test_project_label_convention_executes_at_t_plus_ten_minutes(self) -> None:
        event = detect_event(
            "QQQ",
            long_drive(),
            long_post()[:2],
            [bar("10:00", 111, 112, 110, 111)],
            40,
        )
        assert event
        confirmation_bar_open = long_post()[1].timestamp
        self.assertEqual(
            event.executable_timestamp,
            confirmation_bar_open + pd.Timedelta(10, unit="min"),
        )


class DedupControlCostTests(unittest.TestCase):
    def make_event(self):
        event = detect_event(
            "QQQ",
            long_drive(),
            long_post()[:2],
            [bar("10:00", 111, 112, 110, 111)],
            40,
        )
        assert event
        return event

    def test_dedup_keeps_earliest_per_symbol_session(self) -> None:
        first = self.make_event()
        later = replace(
            first,
            direction=Direction.SHORT,
            executable_timestamp=first.executable_timestamp + pd.Timedelta(5, unit="min"),
        )
        selected = deduplicate_events([later, first])
        self.assertEqual(selected.events, (first,))
        self.assertFalse(selected.exclusions)

    def test_dedup_keeps_symbols_separate(self) -> None:
        first = self.make_event()
        spy = replace(first, symbol="SPY")
        self.assertEqual(len(deduplicate_events([first, spy]).events), 2)

    def test_dedup_short_before_long_keeps_short(self) -> None:
        long = self.make_event()
        short = replace(
            long,
            direction=Direction.SHORT,
            executable_timestamp=long.executable_timestamp - pd.Timedelta(5, unit="min"),
        )
        self.assertEqual(deduplicate_events([long, short]).events, (short,))

    def test_simultaneous_direction_conflict_excludes_independent_of_order(self) -> None:
        long = self.make_event()
        short = replace(long, direction=Direction.SHORT)
        for candidates in ([long, short], [short, long]):
            result = deduplicate_events(candidates)
            self.assertEqual(result.events, ())
            self.assertEqual(
                result.exclusions[(long.symbol, long.session_date)],
                EXCLUDED_DIRECTION_CONFLICT,
            )

    def test_oriented_return_symmetry(self) -> None:
        self.assertAlmostEqual(oriented_return(Direction.LONG, 100, 110), 0.10)
        self.assertAlmostEqual(oriented_return(Direction.SHORT, 100, 100 / 1.10), 0.10)

    def test_costs_and_net_returns(self) -> None:
        self.assertAlmostEqual(round_trip_cost(100, "baseline"), 0.0004)
        self.assertAlmostEqual(round_trip_cost(100, "stress"), 0.0008)
        self.assertAlmostEqual(net_return(0.01, 100, "baseline"), 0.0096)
        self.assertAlmostEqual(net_return(0.01, 100, "stress"), 0.0092)

    def test_costs_resolve_frozen_tick_by_symbol(self) -> None:
        for symbol in ("QQQ", "SPY"):
            self.assertAlmostEqual(
                _round_trip_cost(symbol, 100, "baseline", CONFIG), 0.0004
            )
            self.assertAlmostEqual(
                _round_trip_cost(symbol, 100, "stress", CONFIG), 0.0008
            )
        with self.assertRaises(ValueError):
            _round_trip_cost("IWM", 100, "baseline", CONFIG)

    def test_changed_tick_convention_changes_costs_and_hash(self) -> None:
        changed = replace(
            CONFIG,
            tick_size_by_symbol={"QQQ": 0.02, "SPY": 0.01},
        )
        self.assertNotEqual(
            _round_trip_cost("QQQ", 100, "baseline", CONFIG),
            _round_trip_cost("QQQ", 100, "baseline", changed),
        )
        self.assertNotEqual(
            canonical_payload_hash(),
            _canonical_payload_hash(drive_module.canonical_payload(changed)),
        )

    def test_rvol_requires_exactly_twenty_prior_values_and_is_descriptive(self) -> None:
        self.assertIsNone(rvol_descriptive(200, [100] * 19))
        self.assertEqual(rvol_descriptive(200, [100] * 20), 2.0)
        self.assertEqual(canonical_payload()["descriptives"]["rvol_role"], "descriptive_only")
        self.assertEqual(canonical_payload()["descriptives"]["vwap_role"], "descriptive_only")

    def test_control_exact_matching_and_own_date_exclusion(self) -> None:
        events = pd.DataFrame(
            [{
                "symbol": "QQQ",
                "session_date": "2024-06-03",
                "executable_timestamp": "2024-06-03T14:00:00Z",
                "horizon": "30min",
                "event_return": 0.03,
            }]
        )
        controls = pd.DataFrame(
            [
                {"symbol": "QQQ", "session_date": "2024-06-03", "executable_timestamp": "2024-06-03T14:00:00Z", "horizon": "30min", "event_return": 0.99},
                {"symbol": "QQQ", "session_date": "2024-06-04", "executable_timestamp": "2024-06-04T14:00:00Z", "horizon": "30min", "event_return": 0.01},
                {"symbol": "SPY", "session_date": "2024-06-04", "executable_timestamp": "2024-06-04T14:00:00Z", "horizon": "30min", "event_return": 0.50},
                {"symbol": "QQQ", "session_date": "2023-06-04", "executable_timestamp": "2023-06-04T14:00:00Z", "horizon": "30min", "event_return": 0.50},
                {"symbol": "QQQ", "session_date": "2024-06-05", "executable_timestamp": "2024-06-05T14:05:00Z", "horizon": "30min", "event_return": 0.50},
                {"symbol": "QQQ", "session_date": "2024-06-06", "executable_timestamp": "2024-06-06T14:00:00Z", "horizon": "15min", "event_return": 0.50},
            ]
        )
        result = matched_unconditional_control(events, controls)
        self.assertAlmostEqual(result.loc[0, "unconditional_return"], 0.01)
        self.assertAlmostEqual(result.loc[0, "incremental_return"], 0.02)


class ConcentrationBootstrapGateTests(unittest.TestCase):
    def rows(self, contributions=(7.0, 2.0, 1.0)) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "session_date": ["2022-01-03", "2023-01-03", "2024-01-03"],
                "incremental_return": contributions,
            }
        )

    def test_concentration_equal_limit_passes_above_fails(self) -> None:
        result = annual_concentration(self.rows())
        self.assertAlmostEqual(result.value, 0.70)
        self.assertTrue(result.passed)
        result = annual_concentration(self.rows((7.01, 2.0, 0.99)))
        self.assertGreater(result.value, 0.70)
        self.assertFalse(result.passed)

    def test_concentration_missing_year_and_zero_denominator_fail(self) -> None:
        self.assertFalse(annual_concentration(self.rows().iloc[:2]).passed)
        self.assertFalse(annual_concentration(self.rows((0, 0, 0))).passed)

    def test_nonfinite_concentration_inputs_fail_explicitly(self) -> None:
        for value in (np.nan, np.inf, -np.inf):
            result = annual_concentration(self.rows((value, 1, 1)))
            self.assertFalse(result.passed)
            self.assertEqual(result.validation_status, "NONFINITE_INCREMENTAL_RETURN")
        missing_date = self.rows()
        missing_date.loc[0, "session_date"] = None
        self.assertEqual(
            annual_concentration(missing_date).validation_status,
            "MISSING_SESSION_DATE",
        )
        invalid_year = self.rows()
        invalid_year["year"] = [2021, 2023, 2024]
        self.assertEqual(
            annual_concentration(invalid_year).validation_status,
            "INVALID_YEAR",
        )

    def test_leave_one_largest_session_out(self) -> None:
        rows = pd.DataFrame(
            {
                "session_date": [
                    "2022-01-03", "2022-01-04",
                    "2023-01-03", "2023-01-04",
                    "2024-01-03", "2024-01-04",
                ],
                "incremental_return": [4.0, 3.0, 1.0, 1.0, 0.5, 0.5],
            }
        )
        result = leave_one_largest_session_out_concentration(rows)
        self.assertEqual(result.removed_session_date, date(2022, 1, 3))
        self.assertTrue(np.isfinite(result.value))
        self.assertIsInstance(result.passed, bool)

    def test_leave_one_out_rejects_nonfinite_before_session_selection(self) -> None:
        rows = self.rows((np.nan, 1, 1))
        result = leave_one_largest_session_out_concentration(rows)
        self.assertFalse(result.passed)
        self.assertIsNone(result.removed_session_date)
        self.assertEqual(result.validation_status, "NONFINITE_INCREMENTAL_RETURN")

    def test_bootstrap_defaults_cluster_and_determinism(self) -> None:
        rows = pd.DataFrame(
            {
                "session_date": ["2024-01-02", "2024-01-02", "2024-01-03", "2024-01-03"],
                "symbol": ["QQQ", "SPY", "QQQ", "SPY"],
                "event_return": [0.01, 0.02, 0.03, 0.04],
                "incremental_return": [0.005, 0.01, 0.02, 0.03],
                "net_return_baseline": [0.004, 0.009, 0.019, 0.029],
            }
        )
        first = clustered_percentile_bootstrap(rows)
        second = clustered_percentile_bootstrap(rows)
        self.assertEqual(first, second)

    def test_bootstrap_overrides_are_rejected(self) -> None:
        rows = pd.DataFrame(
            {
                "session_date": ["2024-01-02"],
                "event_return": [0.01],
                "incremental_return": [0.01],
                "net_return_baseline": [0.01],
            }
        )
        with self.assertRaises(TypeError):
            clustered_percentile_bootstrap(rows, resamples=200)  # type: ignore[call-arg]
        with self.assertRaises(TypeError):
            clustered_percentile_bootstrap(rows, seed=1)  # type: ignore[call-arg]
        with self.assertRaises(TypeError):
            clustered_percentile_bootstrap(rows, confidence=0.90)  # type: ignore[call-arg]

    def test_bootstrap_gate_strict_zero_and_negative_fail(self) -> None:
        positive = {
            "event_return": (0.01, 0.02),
            "incremental_return": (0.01, 0.02),
            "net_return_baseline": (0.01, 0.02),
        }
        self.assertTrue(bootstrap_gate(positive))
        zero = dict(positive, event_return=(0.0, 0.02))
        negative = dict(positive, incremental_return=(-0.01, 0.02))
        self.assertFalse(bootstrap_gate(zero))
        self.assertFalse(bootstrap_gate(negative))

    def valid_gate_metrics(self) -> GateMetrics:
        return GateMetrics(
            primary_horizon_minutes=30,
            pooled_event_count=150,
            event_count_by_symbol={"QQQ": 75, "SPY": 75},
            direction_mean={
                Direction.LONG.value: 0.01,
                Direction.SHORT.value: 0.01,
            },
            direction_median={
                Direction.LONG.value: 0.005,
                Direction.SHORT.value: 0.005,
            },
            symbol_mean={"QQQ": 0.01, "SPY": 0.01},
            annual_gross_mean={2022: 0.01, 2023: 0.01, 2024: -0.001},
            pooled_incremental_mean=0.005,
            pooled_baseline_net_mean=0.004,
            pooled_stress_net_mean=0.0,
            annual_concentration=ConcentrationResult(0.50, True, "PASS"),
            leave_one_session_out_concentration=LeaveOneSessionOutResult(
                0.50, True, date(2022, 1, 3), "PASS"
            ),
            annual_incremental_signs={2022: 1.0, 2023: 1.0, 2024: -1.0},
            leave_one_out_annual_incremental_signs={
                2022: 1.0,
                2023: 1.0,
                2024: -1.0,
            },
            bootstrap_intervals={
                "event_return": (0.001, 0.02),
                "incremental_return": (0.001, 0.02),
                "net_return_baseline": (0.001, 0.02),
            },
            causal_integrity_passed=True,
            temporal_contamination_absent=True,
            decision_variants=1,
        )

    def test_gate_has_sixteen_derived_required_conditions(self) -> None:
        self.assertEqual(len(CONFIG.gate_criteria), 16)
        self.assertEqual(CONFIG.gate_criteria, APPROVED_GATE_CRITERION_IDS)
        result = evaluate_gate(self.valid_gate_metrics())
        self.assertTrue(result.all_required)
        self.assertTrue(result.passed)
        self.assertEqual(result.classification, "discovery_passed")
        self.assertTrue(result.validation_2025_unlocked)
        self.assertFalse(result.paper_eligible)
        self.assertFalse(result.live_eligible)

    def test_each_derived_gate_criterion_can_fail_individually(self) -> None:
        base = self.valid_gate_metrics()
        failures = {
            "minimum_pooled_events": replace(base, pooled_event_count=149),
            "minimum_events_per_symbol": replace(
                base, event_count_by_symbol={"QQQ": 49, "SPY": 101}
            ),
            "continuation_long_positive_mean_and_median": replace(
                base,
                direction_mean={
                    Direction.LONG.value: 0.0,
                    Direction.SHORT.value: 0.01,
                },
            ),
            "continuation_short_positive_mean_and_median": replace(
                base,
                direction_median={
                    Direction.LONG.value: 0.01,
                    Direction.SHORT.value: 0.0,
                },
            ),
            "qqq_and_spy_positive_primary_means": replace(
                base, symbol_mean={"QQQ": 0.0, "SPY": 0.02}
            ),
            "gross_mean_positive_in_at_least_two_of_three_years": replace(
                base, annual_gross_mean={2022: 0.01, 2023: -0.01, 2024: -0.01}
            ),
            "pooled_incremental_mean_positive": replace(
                base, pooled_incremental_mean=0.0
            ),
            "pooled_baseline_net_mean_positive": replace(
                base, pooled_baseline_net_mean=0.0
            ),
            "pooled_stress_net_mean_non_negative": replace(
                base, pooled_stress_net_mean=-0.0001
            ),
            "annual_concentration_at_most_0_70": replace(
                base,
                annual_concentration=ConcentrationResult(
                    0.71, False, "ABOVE_CONCENTRATION_LIMIT"
                ),
            ),
            "leave_one_session_out_concentration_at_most_0_70": replace(
                base,
                leave_one_session_out_concentration=LeaveOneSessionOutResult(
                    0.71,
                    False,
                    date(2022, 1, 3),
                    "ABOVE_CONCENTRATION_LIMIT",
                ),
            ),
            "annual_signs_positive_in_at_least_two_of_three_years_original_and_leave_one_out": replace(
                base,
                annual_incremental_signs={2022: 1.0, 2023: -1.0, 2024: -1.0},
            ),
            "all_three_bootstrap_lower_bounds_strictly_positive": replace(
                base,
                bootstrap_intervals={
                    **base.bootstrap_intervals,
                    "event_return": (0.0, 0.02),
                },
            ),
            "no_lookahead_or_unresolved_data_quality_failure": replace(
                base, causal_integrity_passed=False
            ),
            "no_2025_or_2026_contamination": replace(
                base, temporal_contamination_absent=False
            ),
            "one_variant_budget_respected": replace(base, decision_variants=2),
        }
        self.assertEqual(tuple(failures), CONFIG.gate_criteria)
        for criterion, metrics in failures.items():
            criteria = derive_gate_criteria(metrics)
            self.assertFalse(criteria[criterion], criterion)
            result = evaluate_gate(metrics)
            self.assertFalse(result.passed, criterion)
            self.assertEqual(result.classification, "discovery_failed")
            self.assertFalse(result.validation_2025_unlocked)
            self.assertFalse(result.paper_eligible)
            self.assertFalse(result.live_eligible)

    def test_external_booleans_cannot_force_gate_pass(self) -> None:
        with self.assertRaises(TypeError):
            evaluate_gate(
                {name: True for name in CONFIG.gate_criteria}
            )  # type: ignore[arg-type]

    def test_exact_sample_boundaries_and_primary_horizon(self) -> None:
        base = self.valid_gate_metrics()
        self.assertTrue(derive_gate_criteria(base)["minimum_pooled_events"])
        self.assertFalse(
            derive_gate_criteria(replace(base, pooled_event_count=149))[
                "minimum_pooled_events"
            ]
        )
        with self.assertRaises(ValueError):
            evaluate_gate(replace(base, primary_horizon_minutes=15))

    def test_primary_horizon_has_one_source_and_counterexamples_fail(self) -> None:
        base = self.valid_gate_metrics()
        config_15 = replace(CONFIG, primary_horizon_minutes=15)
        self.assertEqual(CONFIG.primary_horizon_label, "30min")
        self.assertEqual(config_15.primary_horizon_label, "15min")
        self.assertTrue(evaluate_gate(base).passed)
        with self.assertRaises(ValueError):
            evaluate_gate.func(base, config_15)
        with self.assertRaises(ValueError):
            evaluate_gate(replace(base, primary_horizon_minutes=15))
        self.assertNotEqual(
            canonical_payload_hash(),
            _canonical_payload_hash(drive_module.canonical_payload(config_15)),
        )

    def test_secondary_descriptive_symbol_direction_or_year_cannot_rescue(self) -> None:
        payload = canonical_payload()
        self.assertTrue(payload["horizons"]["secondary_cannot_rescue_primary"])
        self.assertFalse(payload["discovery_gate"]["diagnostic_or_secondary_rescue"])
        self.assertNotIn("vwap", CONFIG.gate_criteria)
        self.assertNotIn("rvol", CONFIG.gate_criteria)


class HashTests(unittest.TestCase):
    def test_hash_is_deterministic_and_matches_yaml(self) -> None:
        first = canonical_payload_hash()
        self.assertEqual(first, canonical_payload_hash())
        self.assertEqual(first, YAML_MAPPING["canonical_payload_hash"])
        config = yaml.safe_load(YAML_PATH.read_text(encoding="utf-8"))
        self.assertEqual(config["canonical_payload_hash"], first)

    def test_methodological_change_changes_hash(self) -> None:
        payload = canonical_payload()
        changed = copy.deepcopy(payload)
        changed["research_parameters"]["values"]["minimum_normalized_drive"] = 0.26
        self.assertNotEqual(canonical_payload_hash(payload), canonical_payload_hash(changed))

    def test_each_research_parameter_mapping_changes_hash(self) -> None:
        replacements = {
            "drive_start": "09:25",
            "drive_end": "09:50",
            "historical_atr_lookback": 21,
            "minimum_normalized_drive": 0.26,
            "minimum_initial_adverse_pullback_ticks": 2,
            "maximum_normalized_pullback_depth": 0.40,
            "maximum_post_drive_observation_bars": 4,
            "latest_confirmation_executable_boundary": ["10:05", "10:10"],
            "maximum_events_per_symbol_session": 2,
            "primary_horizon_minutes": 15,
            "minimum_pooled_events": 151,
            "minimum_events_per_symbol": 51,
            "minimum_positive_discovery_years": 3,
            "maximum_annual_effect_concentration": 0.69,
            "bootstrap_confidence_level": 0.90,
            "bootstrap_resamples": 9999,
            "bootstrap_seed": 20260729,
        }
        baseline = canonical_payload_hash()
        self.assertEqual(set(replacements), set(FROZEN_CONSTANT_NAMES))
        for name, value in replacements.items():
            changed = copy.deepcopy(YAML_MAPPING)
            changed["research_parameters"]["values"][name] = value
            config = config_from_mapping(mapping_with_recomputed_hash(changed))
            self.assertNotEqual(
                baseline,
                _canonical_payload_hash(drive_module.canonical_payload(config)),
                name,
            )

    def test_decisional_overrides_require_configuration(self) -> None:
        with self.assertRaises(TypeError):
            build_drive(long_drive(), 40, threshold=0.20)  # type: ignore[call-arg]
        with self.assertRaises(TypeError):
            detect_event(
                "QQQ",
                long_drive(),
                long_post()[:2],
                [bar("10:00", 111, 112, 110, 111)],
                40,
                tick_size=0.02,  # type: ignore[call-arg]
            )

    def test_changed_configuration_changes_payload_hash(self) -> None:
        changed_config = replace(
            CONFIG,
            minimum_normalized_drive=0.26,
        )
        self.assertNotEqual(
            canonical_payload_hash(),
            canonical_payload_hash(
                canonical_payload.func(changed_config)
            ),
        )

    def test_external_timestamp_and_absolute_path_do_not_change_hash(self) -> None:
        payload = canonical_payload()
        changed = copy.deepcopy(payload)
        changed["generated_at"] = "2099-01-01T00:00:00Z"
        changed["absolute_path"] = "C:/private/location"
        self.assertEqual(canonical_payload_hash(payload), canonical_payload_hash(changed))

    def test_freeze_constants_and_gate_participate(self) -> None:
        payload = canonical_payload()
        freeze = copy.deepcopy(payload)
        freeze["conceptual_design_freeze_commit"] = "0" * 40
        constant = copy.deepcopy(payload)
        constant["research_parameters"]["values"]["bootstrap_seed"] = 1
        gate = copy.deepcopy(payload)
        gate["discovery_gate"]["criteria"] = gate["discovery_gate"]["criteria"][:-1]
        baseline = canonical_payload_hash(payload)
        self.assertNotEqual(baseline, canonical_payload_hash(freeze))
        self.assertNotEqual(baseline, canonical_payload_hash(constant))
        self.assertNotEqual(baseline, canonical_payload_hash(gate))

    def test_clarification_freeze_and_tick_convention_participate(self) -> None:
        clarification = replace(
            CONFIG,
            implementation_clarification_freeze_commit="0" * 40,
        )
        tick = replace(
            CONFIG,
            tick_size_by_symbol={"QQQ": 0.02, "SPY": 0.01},
        )
        baseline = canonical_payload_hash()
        self.assertNotEqual(
            baseline,
            _canonical_payload_hash(drive_module.canonical_payload(clarification)),
        )
        self.assertNotEqual(
            baseline,
            _canonical_payload_hash(drive_module.canonical_payload(tick)),
        )

    def test_corrected_governance_rules_participate_in_hash(self) -> None:
        payload = canonical_payload()
        paths = [
            ("pullback", "post_drive_new_extreme_invalidation"),
            ("deduplication", "direction_conflict_exclusion_reason"),
            ("annual_concentration", "nonfinite_incremental_return"),
            ("discovery_gate", "evaluation_rule_id"),
        ]
        baseline = canonical_payload_hash(payload)
        for section, field in paths:
            changed = copy.deepcopy(payload)
            changed[section][field] = "changed"
            self.assertNotEqual(baseline, canonical_payload_hash(changed))


if __name__ == "__main__":
    unittest.main()
