from __future__ import annotations

from datetime import date, timedelta
import math
from pathlib import Path
import unittest

import numpy as np
import pandas as pd
import yaml

from src.research.hyp_vwap_dev_01 import (
    ALL_CRITERION_IDS,
    BOOTSTRAP_REPLICATES,
    Direction,
    EXPECTED_CANONICAL_HASH,
    SUBSTANTIVE_CRITERION_IDS,
    annual_concentration,
    annual_stability,
    attach_causal_session_vwap,
    breach_close_is_eligible,
    breach_orientation,
    build_exact_time_control,
    build_unconditional_candidates,
    canonical_payload_hash,
    classify_gate,
    clustered_percentile_bootstrap,
    compute_path_metrics,
    derive_integrity_criteria,
    derive_substantive_criteria,
    detect_session_event,
    evaluate_immediate_confirmation,
    evaluate_pro_01,
    execution_is_canceled,
    leave_one_largest_session_out,
    oriented_return,
    path_excursions,
    resample_complete_rth_1m_to_5m,
    round_trip_cost,
    select_leave_one_out_session,
    signed_deviation,
    typical_price,
    validate_frozen_config,
)


CORE_ID_COUNTS = {
    "GOV": 15,
    "RSM": 5,
    "VWP": 7,
    "THR": 12,
    "EVT": 13,
    "EXE": 11,
    "PTH": 14,
    "CTL": 12,
    "BST": 15,
    "GAT": 39,
    "PRO": 9,
    "CON": 8,
    "LOO": 22,
}
_CORE_METHOD_BY_PREFIX = {
    **{prefix: f"test_contract_{prefix.lower()}" for prefix in CORE_ID_COUNTS},
    "GAT": "test_contract_gat_and_pro",
    "PRO": "test_contract_gat_and_pro",
}
CORE_TEST_ID_COVERAGE = {
    f"{prefix}-{index:02d}": _CORE_METHOD_BY_PREFIX[prefix]
    for prefix, count in CORE_ID_COUNTS.items()
    for index in range(1, count + 1)
}
FIX_TEST_ID_COVERAGE = {
    **{f"SC-{index:02d}": "test_official_session_close_contracts" for index in range(1, 11)},
    **{f"INTFIX-{index:02d}": "test_integrity_evidence_contracts" for index in range(1, 16)},
}


def _config() -> dict:
    path = Path("configs/research/hypotheses/HYP-VWAP-DEV-01.yaml")
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _minute_frame(*, missing_index: int | None = None) -> pd.DataFrame:
    timestamps = pd.date_range("2024-01-03 09:30", periods=5, freq="1min", tz="America/New_York")
    rows = []
    for index, timestamp in enumerate(timestamps):
        if index == missing_index:
            continue
        rows.append({
            "symbol": "QQQ",
            "session_date": date(2024, 1, 3),
            "timestamp": timestamp,
            "open": 100.0 + index,
            "high": 101.0 + index,
            "low": 99.0 + index,
            "close": 100.5 + index,
            "volume": 10.0 + index,
        })
    return pd.DataFrame(rows)


def _event_bars(direction: Direction = Direction.LONG) -> pd.DataFrame:
    if direction is Direction.LONG:
        close_values = [99.4, 99.6, 99.7, 99.8]
        opens = [99.5, 99.5, 99.5, 99.7]
    else:
        close_values = [100.6, 100.4, 100.3, 100.2]
        opens = [100.5, 100.5, 100.5, 100.3]
    return pd.DataFrame({
        "timestamp": pd.date_range("2024-01-03 09:55", periods=4, freq="5min", tz="America/New_York"),
        "open": opens,
        "high": [101.0] * 4,
        "low": [99.0] * 4,
        "close": close_values,
        "session_vwap": [100.0] * 4,
    })


def _path_fixture() -> tuple[pd.DataFrame, pd.DataFrame]:
    start = pd.Timestamp("2024-01-03 10:05", tz="America/New_York")
    events = pd.DataFrame([{
        "symbol": "QQQ",
        "session_date": date(2024, 1, 3),
        "direction": "long",
        "executable_timestamp": start,
        "executable_price": 100.0,
    }])
    timestamps = pd.date_range(start, pd.Timestamp("2024-01-03 15:55", tz="America/New_York"), freq="5min")
    bars = pd.DataFrame({
        "symbol": "QQQ",
        "session_date": date(2024, 1, 3),
        "timestamp": timestamps,
        "open": 100.0,
        "high": np.linspace(100.2, 102.0, len(timestamps)),
        "low": np.linspace(99.8, 100.5, len(timestamps)),
        "close": np.linspace(100.1, 101.5, len(timestamps)),
    })
    return events, bars


def _official_closes(close: str = "2024-01-03 16:00") -> dict[date, pd.Timestamp]:
    return {date(2024, 1, 3): pd.Timestamp(close, tz="America/New_York")}


def _integrity_inputs(paths: pd.DataFrame) -> dict[str, object]:
    return {
        "causal_integrity_report": {
            "causal_integrity_passed": True,
            "lookahead_violations": 0,
            "unresolved_data_quality_failures": 0,
        },
        "dataset_contract_report": {"dataset_contract_passed": True},
        "manifest_validation_report": {"manifest_validation_passed": True},
        "temporal_access_report": {
            "materialized_rows_after_discovery_end": 0,
            "historical_2025_rows_materialized": 0,
            "historical_2026_rows_materialized": 0,
            "event_rows_outside_discovery": 0,
            "control_rows_outside_discovery": 0,
            "horizons_crossing_session_or_period": 0,
        },
        "path_metrics": paths,
        "decision_variants": 1,
    }


def _annual_rows() -> pd.DataFrame:
    rows = []
    for year, value in ((2022, 0.001), (2023, 0.0012), (2024, 0.0008)):
        for offset in range(41):
            rows.append({
                "symbol": "QQQ" if offset % 2 == 0 else "SPY",
                "session_date": date(year, 1, 1) + timedelta(days=offset),
                "gross_return": value + 0.001,
                "incremental_return": value,
                "baseline_net_return": value + 0.0005,
            })
    return pd.DataFrame(rows)


def _passing_metrics() -> dict[str, object]:
    return {
        "INT-01": True, "INT-02": True, "INT-03": True, "INT-04": 0,
        "INT-05": 0, "INT-06": False, "INT-07": True, "INT-08": 1,
        "SMP-01": 150, "SMP-02": {"QQQ": 50, "SPY": 50},
        "SMP-03": {2022: 40, 2023: 40, 2024: 40},
        "REP-01": {"long": 40, "short": 40},
        "ECO-01": 0.001, "ECO-02": {"QQQ": 0.001, "SPY": 0.001},
        "ECO-03": [0.001, 0.001, 0.001, 0.001],
        "ECO-04": {"pooled": 0.001, "QQQ": 0.001, "SPY": 0.001},
        "ECO-05": 0.0, "INC-01": 0.001, "UNC-01": [0.001, 0.001, 0.001],
        "STB-01": 2, "STB-02": 2, "CON-01": 0.7, "CON-02": 0.7,
        "CON-03": 0.001, "CON-04": 2,
    }


class GovernanceTests(unittest.TestCase):
    def test_contract_gov(self) -> None:
        config = _config()
        self.assertIs(validate_frozen_config(config), config)
        self.assertEqual(canonical_payload_hash(config), EXPECTED_CANONICAL_HASH)
        self.assertEqual(tuple(item["criterion_id"] for item in config["discovery_gate"]["criteria"]), ALL_CRITERION_IDS)
        mutations = [
            ("methodology_frozen", False),
            ("preregistration_frozen", False),
            ("decision_variants", 2),
            ("historical_data_access_allowed", True),
        ]
        for key, value in mutations:
            with self.subTest(key=key), self.assertRaises((PermissionError, ValueError)):
                changed = yaml.safe_load(yaml.safe_dump(config))
                changed[key] = value
                validate_frozen_config(changed)

    def test_core_coverage_has_182_unique_ids(self) -> None:
        self.assertEqual(len(CORE_TEST_ID_COVERAGE), 182)
        self.assertEqual(len(set(CORE_TEST_ID_COVERAGE)), 182)
        method_names = {
            name
            for case in (
                GovernanceTests, ResampleAndVwapTests, EventTests,
                PathAndControlTests, RobustnessAndGateTests,
            )
            for name in unittest.defaultTestLoader.getTestCaseNames(case)
        }
        self.assertTrue(set(CORE_TEST_ID_COVERAGE.values()).issubset(method_names))


class ResampleAndVwapTests(unittest.TestCase):
    def test_contract_rsm(self) -> None:
        result = resample_complete_rth_1m_to_5m(_minute_frame())
        self.assertEqual(len(result), 1)
        row = result.iloc[0]
        self.assertEqual(row["open"], 100.0)
        self.assertEqual(row["high"], 105.0)
        self.assertEqual(row["low"], 99.0)
        self.assertEqual(row["close"], 104.5)
        self.assertEqual(row["volume"], 60.0)
        self.assertTrue(resample_complete_rth_1m_to_5m(_minute_frame(missing_index=2)).empty)

    def test_contract_vwp(self) -> None:
        self.assertEqual(typical_price(102, 99, 100), 301 / 3)
        frame = pd.DataFrame({
            "symbol": ["QQQ"] * 4,
            "session_date": [date(2024, 1, 3)] * 3 + [date(2024, 1, 4)],
            "timestamp": pd.to_datetime([
                "2024-01-03 09:30-05:00", "2024-01-03 09:35-05:00",
                "2024-01-03 09:40-05:00", "2024-01-04 09:30-05:00",
            ]),
            "high": [101, 103, 110, 201], "low": [99, 101, 90, 199],
            "close": [100, 102, 100, 200], "volume": [0, 10, 0, 10],
        })
        result = attach_causal_session_vwap(frame)
        self.assertTrue(math.isnan(result.loc[0, "session_vwap"]))
        self.assertEqual(result.loc[1, "session_vwap"], 102.0)
        self.assertEqual(result.loc[2, "session_vwap"], 102.0)
        self.assertEqual(result.loc[3, "session_vwap"], 200.0)


class EventTests(unittest.TestCase):
    def test_contract_thr(self) -> None:
        cases = [(-0.0051, Direction.LONG), (-0.005, None), (0.0051, Direction.SHORT), (0.005, None)]
        for value, expected in cases:
            with self.subTest(value=value):
                self.assertEqual(breach_orientation(value), expected)
        close = pd.Timestamp("2024-01-03 16:00", tz="America/New_York")
        self.assertTrue(breach_close_is_eligible(pd.Timestamp("2024-01-03 10:00", tz="America/New_York"), close))
        self.assertTrue(breach_close_is_eligible(pd.Timestamp("2024-01-03 14:55", tz="America/New_York"), close))
        self.assertFalse(breach_close_is_eligible(pd.Timestamp("2024-01-03 09:55", tz="America/New_York"), close))
        self.assertFalse(breach_close_is_eligible(pd.Timestamp("2024-01-03 15:00", tz="America/New_York"), close))

    def test_contract_evt(self) -> None:
        close = pd.Timestamp("2024-01-03 16:00", tz="America/New_York")
        for direction in (Direction.LONG, Direction.SHORT):
            with self.subTest(direction=direction):
                result = detect_session_event(_event_bars(direction), symbol="QQQ", session_date=date(2024, 1, 3), session_close=close)
                self.assertEqual(result.status, "CONFIRMED")
                self.assertEqual(result.event.direction, direction)
        self.assertTrue(evaluate_immediate_confirmation(Direction.LONG, -0.006, -0.004))
        self.assertFalse(evaluate_immediate_confirmation(Direction.LONG, -0.006, -0.006))
        failed = _event_bars(); failed.loc[1, "close"] = 99.3
        failed.loc[3, "close"] = 99.8
        self.assertEqual(detect_session_event(failed, symbol="QQQ", session_date=date(2024, 1, 3), session_close=close).status, "CONFIRMATION_FAILED")

    def test_contract_exe(self) -> None:
        cases = [
            (Direction.LONG, 99.9, False), (Direction.LONG, 100.0, True),
            (Direction.LONG, 100.1, True), (Direction.SHORT, 100.1, False),
            (Direction.SHORT, 100.0, True), (Direction.SHORT, 99.9, True),
        ]
        for direction, price, canceled in cases:
            with self.subTest(direction=direction, price=price):
                self.assertEqual(execution_is_canceled(direction, price, 100.0), canceled)


class PathAndControlTests(unittest.TestCase):
    def test_contract_pth(self) -> None:
        self.assertAlmostEqual(oriented_return(Direction.LONG, 100, 101), 0.01)
        self.assertAlmostEqual(oriented_return(Direction.SHORT, 100, 99), 100 / 99 - 1)
        self.assertAlmostEqual(round_trip_cost(100, "baseline"), 0.0004)
        self.assertAlmostEqual(round_trip_cost(100, "stress"), 0.0008)
        mfe, mae = path_excursions(Direction.LONG, 100, [101, 102], [99, 98])
        self.assertAlmostEqual(mfe, 0.02)
        self.assertAlmostEqual(mae, -0.02)
        events, bars = _path_fixture()
        metrics = compute_path_metrics(events, bars, _official_closes())
        self.assertEqual(set(metrics["horizon"]), {"15min", "30min", "60min", "session_close"})
        self.assertTrue(metrics["path_complete"].all())
        self.assertTrue(np.allclose(metrics["baseline_net_return"], metrics["gross_return"] - metrics["baseline_cost"]))

    def test_contract_ctl(self) -> None:
        timestamp = pd.Timestamp("2024-01-03 10:05", tz="America/New_York")
        events = pd.DataFrame([{
            "symbol": "QQQ", "session_date": date(2024, 1, 3),
            "executable_timestamp": timestamp, "horizon": "30min",
            "direction": "long", "gross_return": 0.02,
        }])
        controls = pd.DataFrame([
            {"symbol": "QQQ", "session_date": date(2024, 1, 4), "executable_timestamp": timestamp + pd.offsets.Day(), "horizon": "30min", "direction": "long", "gross_return": 0.01},
            {"symbol": "SPY", "session_date": date(2024, 1, 4), "executable_timestamp": timestamp + pd.offsets.Day(), "horizon": "30min", "direction": "long", "gross_return": 9.0},
        ])
        result = build_exact_time_control(events, controls)
        self.assertAlmostEqual(result.loc[0, "unconditional_return"], 0.01)
        self.assertAlmostEqual(result.loc[0, "incremental_return"], 0.01)
        with self.assertRaises(ValueError):
            build_exact_time_control(events, controls[controls["symbol"] == "SPY"])
        path_events, path_bars = _path_fixture()
        candidates = build_unconditional_candidates(path_events, path_bars, _official_closes())
        self.assertEqual(set(candidates["horizon"]), {"15min", "30min", "60min", "session_close"})

    def test_official_session_close_contracts(self) -> None:
        events, bars = _path_fixture()
        complete = compute_path_metrics(events, bars, _official_closes())
        self.assertTrue(complete["path_complete"].all())  # SC-01

        incomplete_bars = bars[bars["timestamp"] <= pd.Timestamp("2024-01-03 15:25", tz="America/New_York")]
        incomplete = compute_path_metrics(events, incomplete_bars, _official_closes())
        close_row = incomplete[incomplete["horizon"] == "session_close"].iloc[0]
        self.assertEqual(close_row["horizon_target_timestamp"], _official_closes()[date(2024, 1, 3)])  # SC-02
        self.assertFalse(close_row["horizon_available"])
        self.assertFalse(close_row["path_complete"])  # SC-03

        early_events = events.copy()
        early_events["executable_timestamp"] = pd.Timestamp("2024-01-03 10:05", tz="America/New_York")
        early_bars = bars[bars["timestamp"] <= pd.Timestamp("2024-01-03 12:55", tz="America/New_York")]
        early = compute_path_metrics(early_events, early_bars, _official_closes("2024-01-03 13:00"))
        self.assertTrue(early["path_complete"].all())
        self.assertEqual(early.loc[early["horizon"] == "session_close", "horizon_target_timestamp"].iloc[0], _official_closes("2024-01-03 13:00")[date(2024, 1, 3)])  # SC-04

        extra = pd.concat([bars, bars.tail(1).assign(timestamp=pd.Timestamp("2024-01-03 16:00", tz="America/New_York"), close=999.0)])
        extra_result = compute_path_metrics(events, extra, _official_closes())
        self.assertEqual(extra_result.loc[extra_result["horizon"] == "session_close", "horizon_target_timestamp"].iloc[0], _official_closes()[date(2024, 1, 3)])  # SC-05
        with self.assertRaisesRegex(ValueError, "OFFICIAL_SESSION_CLOSE_MISSING"):
            compute_path_metrics(events, bars, {})  # SC-06
        with self.assertRaisesRegex(ValueError, "OFFICIAL_SESSION_CLOSE_NAIVE"):
            compute_path_metrics(events, bars, {date(2024, 1, 3): pd.Timestamp("2024-01-03 16:00")})  # SC-07
        early_close = _official_closes("2024-01-03 13:00")[date(2024, 1, 3)]
        self.assertTrue(breach_close_is_eligible(pd.Timestamp("2024-01-03 11:55", tz="America/New_York"), early_close))
        self.assertFalse(breach_close_is_eligible(pd.Timestamp("2024-01-03 12:00", tz="America/New_York"), early_close))  # SC-08
        integrity = derive_integrity_criteria(**_integrity_inputs(incomplete))
        self.assertFalse(integrity["INT-07"].passed)  # SC-09
        late_events = events.copy()
        late_events["executable_timestamp"] = pd.Timestamp("2024-01-03 15:15", tz="America/New_York")
        late = compute_path_metrics(late_events, bars, _official_closes())
        self.assertFalse(late.loc[late["horizon"] == "60min", "horizon_available"].iloc[0])  # SC-10

    def test_integrity_evidence_contracts(self) -> None:
        events, bars = _path_fixture()
        paths = compute_path_metrics(events, bars, _official_closes())
        base = _integrity_inputs(paths)
        valid = derive_integrity_criteria(**base)
        self.assertTrue(all(result.passed for result in valid.values()))  # INTFIX-01

        mutations = [
            ("INT-01", "causal_integrity_report", "causal_integrity_passed", False),
            ("INT-02", "dataset_contract_report", "dataset_contract_passed", False),
            ("INT-03", "manifest_validation_report", "manifest_validation_passed", False),
            ("INT-04", "causal_integrity_report", "lookahead_violations", 1),
            ("INT-05", "causal_integrity_report", "unresolved_data_quality_failures", 1),
            ("INT-06", "temporal_access_report", "historical_2025_rows_materialized", 1),
        ]
        failed_results = {}
        for criterion_id, report_name, field, value in mutations:
            inputs = {**base, report_name: {**base[report_name], field: value}}
            failed_results[criterion_id] = derive_integrity_criteria(**inputs)[criterion_id]
            self.assertFalse(failed_results[criterion_id].passed, criterion_id)  # INTFIX-02..07
        incomplete = paths.copy(); incomplete.loc[0, "path_complete"] = False
        self.assertFalse(derive_integrity_criteria(**{**base, "path_metrics": incomplete})["INT-07"].passed)  # INTFIX-08
        unavailable = paths.copy(); unavailable.loc[0, "horizon_available"] = False
        self.assertFalse(derive_integrity_criteria(**{**base, "path_metrics": unavailable})["INT-07"].passed)  # INTFIX-09
        self.assertFalse(derive_integrity_criteria(**{**base, "decision_variants": 2})["INT-08"].passed)  # INTFIX-10
        self.assertFalse(derive_integrity_criteria(**{**base, "manifest_validation_report": None})["INT-03"].passed)  # INTFIX-11
        self.assertFalse(derive_integrity_criteria(**{**base, "decision_variants": np.nan})["INT-08"].passed)  # INTFIX-12

        metrics = _passing_metrics()
        metrics["INT-01"] = failed_results["INT-01"].value
        statuses = derive_substantive_criteria(metrics, _config()["discovery_gate"]["criteria"])
        self.assertFalse(evaluate_pro_01(statuses))  # INTFIX-13
        gate = classify_gate(statuses)
        self.assertFalse(gate.validation_2025_unlocked)  # INTFIX-14


class RobustnessAndGateTests(unittest.TestCase):
    def test_contract_bst(self) -> None:
        rows = _annual_rows().iloc[:8].copy()
        first = clustered_percentile_bootstrap(rows, replicates=25)
        second = clustered_percentile_bootstrap(rows.sample(frac=1, random_state=7), replicates=25)
        self.assertEqual(first, second)
        self.assertEqual(BOOTSTRAP_REPLICATES, 10_000)
        with self.assertRaises(ValueError):
            clustered_percentile_bootstrap(rows.iloc[:1], replicates=5)
        bad = rows.copy(); bad.loc[0, "gross_return"] = np.nan
        with self.assertRaises(ValueError):
            clustered_percentile_bootstrap(bad, replicates=5)

    def test_contract_con(self) -> None:
        rows = _annual_rows()
        stability = annual_stability(rows)
        self.assertEqual(stability["positive_incremental_years"], 3)
        concentration = annual_concentration(rows)
        self.assertTrue(concentration.passed)
        zero = rows.copy(); zero["incremental_return"] = 0.0
        self.assertFalse(annual_concentration(zero).passed)

    def test_contract_loo(self) -> None:
        same_sign = {date(2024, 1, 3): 2.0, date(2024, 1, 2): 2.0}
        opposite = {date(2024, 1, 3): -2.0, date(2024, 1, 2): 2.0}
        three_way = {date(2024, 1, 4): 2.0, date(2024, 1, 3): -2.0, date(2024, 1, 2): 2.0}
        for contributions in (same_sign, opposite, three_way):
            with self.subTest(contributions=contributions):
                self.assertEqual(select_leave_one_out_session(contributions), date(2024, 1, 2))
                self.assertEqual(select_leave_one_out_session(dict(reversed(list(contributions.items())))), date(2024, 1, 2))
        self.assertEqual(select_leave_one_out_session({date(2024, 1, 2): 1, date(2024, 1, 3): 3}), date(2024, 1, 3))
        for bad in (math.nan, math.inf, -math.inf):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                select_leave_one_out_session({date(2024, 1, 2): bad})
        rows = _annual_rows()
        result = leave_one_largest_session_out(rows)
        removed_rows = rows[pd.to_datetime(rows["session_date"]).dt.date == result.removed_session_date]
        self.assertEqual(set(removed_rows["symbol"]), {"QQQ", "SPY"} if len(removed_rows) > 1 else set(removed_rows["symbol"]))

    def test_contract_gat_and_pro(self) -> None:
        criteria = _config()["discovery_gate"]["criteria"]
        passing = _passing_metrics()
        statuses = derive_substantive_criteria(passing, criteria)
        self.assertEqual(tuple(statuses), SUBSTANTIVE_CRITERION_IDS)
        self.assertTrue(all(value == "passed" for value in statuses.values()))
        self.assertTrue(evaluate_pro_01(statuses))
        gate = classify_gate(statuses)
        self.assertEqual(gate.classification, "discovery_passed")
        for criterion_id in SUBSTANTIVE_CRITERION_IDS:
            with self.subTest(criterion_id=criterion_id):
                failed = dict(statuses); failed[criterion_id] = "failed"
                self.assertFalse(evaluate_pro_01(failed))
                self.assertEqual(classify_gate(failed).classification, "discovery_failed")
        with self.assertRaises(ValueError):
            evaluate_pro_01({**statuses, "PRO-01": "passed"})
        pending = dict(statuses); pending["INT-01"] = "pending"
        with self.assertRaises(ValueError):
            evaluate_pro_01(pending)
        missing_symbol = _passing_metrics(); missing_symbol["SMP-02"] = {"QQQ": 150}
        self.assertEqual(derive_substantive_criteria(missing_symbol, criteria)["SMP-02"], "failed")


if __name__ == "__main__":
    unittest.main()
