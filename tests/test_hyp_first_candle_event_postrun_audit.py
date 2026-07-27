from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from src.research.hyp_first_candle_event_discovery import _economic_threshold_comparison
from src.research.hyp_first_candle_event_postrun_audit import (
    EXPECTED_HORIZONS,
    _bootstrap_mean_ci_by_session,
    audit_classification,
    audit_economic_thresholds,
    audit_event_07_08,
    audit_events,
    audit_paths,
    friction_threshold_return,
    one_tick_return,
    recompute_and_compare,
    two_tick_return,
)
from src.research.hyp_first_candle_event_study import aggregate_fcr_event_paths, attach_bootstrap_intervals


def event_row(symbol: str, event_type: str, session_date: str, event_time: str) -> dict:
    side = "low" if event_type in {"EVENT-05", "EVENT-07"} else "high"
    return {
        "hypothesis_id": "HYP-FCR-EVENT-01",
        "symbol": symbol,
        "session_date": session_date,
        "event_type": event_type,
        "event_side": side,
        "event_time": event_time,
        "event_price": 100.0,
    }


def path_rows_for_event(row: dict, returns: dict[str, float] | None = None) -> list[dict]:
    returns = returns or {horizon: -0.001 for horizon in EXPECTED_HORIZONS}
    rows = []
    for horizon in EXPECTED_HORIZONS:
        reversal = returns[horizon]
        rows.append(
            {
                **row,
                "year": int(str(row["session_date"])[:4]),
                "orientation": "long_reversal" if row["event_side"] == "low" else "short_reversal",
                "horizon": horizon,
                "availability_status": "available",
                "future_close": 99.9,
                "horizon_close": 99.9,
                "raw_return": reversal,
                "future_return": reversal,
                "reversal_return": reversal,
                "continuation_return": -reversal,
                "maximum_favorable_excursion": 0.001,
                "MFE": 0.001,
                "maximum_adverse_excursion": -0.001,
                "MAE": -0.001,
                "time_to_mfe": row["event_time"],
                "time_to_MFE": row["event_time"],
                "time_to_mae": row["event_time"],
                "time_to_MAE": row["event_time"],
                "path_high": 101.0,
                "path_low": 99.0,
                "returned_to_or_center": False,
                "return_to_OR_midpoint": False,
                "reached_opposite_or_extreme": False,
                "reached_opposite_OR_extreme": False,
                "broke_same_or_extreme": False,
                "rebreak_same_extreme": False,
                "bars_in_path": 1,
            }
        )
    return rows


def add_derived_ids(events: pd.DataFrame, paths: pd.DataFrame):
    from src.research.hyp_first_candle_event_postrun_audit import _derive_event_id

    events = events.copy()
    paths = paths.copy()
    events["derived_event_id"] = _derive_event_id(events)
    paths["derived_event_id"] = _derive_event_id(paths)
    return events, paths


def classification_fixture():
    events = []
    paths = []
    for year in (2022, 2023, 2024):
        for symbol in ("QQQ", "SPY"):
            for event_type in ("EVENT-07", "EVENT-08"):
                date = f"{year}-01-03"
                row = event_row(symbol, event_type, date, f"{date}T15:00:00+00:00")
                events.append(row)
                paths.extend(path_rows_for_event(row))
    events_frame = pd.DataFrame(events)
    paths_frame = pd.DataFrame(paths)
    return add_derived_ids(events_frame, paths_frame)


class HypFirstCandleEventPostrunAuditTests(unittest.TestCase):
    def test_event_counts_sum_and_qqq_event_05_is_present(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            events = pd.DataFrame(
                [
                    event_row("QQQ", "EVENT-05", "2024-01-03", "2024-01-03T15:00:00+00:00"),
                    event_row("SPY", "EVENT-05", "2024-01-03", "2024-01-03T15:00:00+00:00"),
                ]
            )
            events, _ = add_derived_ids(events, events.copy())
            with patch("src.research.hyp_first_candle_event_postrun_audit.EXPECTED_EVENT_ROWS", 2):
                report = audit_events(events, root)
            self.assertEqual(report["qqq_event_05_count"], 1)
            self.assertEqual(report["counts_total"], 2)
            self.assertTrue(report["total_matches_expected"])

    def test_each_event_has_five_horizons_and_no_2025_2026(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            event = event_row("QQQ", "EVENT-07", "2024-01-03", "2024-01-03T15:00:00+00:00")
            events = pd.DataFrame([event])
            paths = pd.DataFrame(path_rows_for_event(event))
            events, paths = add_derived_ids(events, paths)
            with patch("src.research.hyp_first_candle_event_postrun_audit.EXPECTED_EVENT_ROWS", 1), patch(
                "src.research.hyp_first_candle_event_postrun_audit.EXPECTED_PATH_ROWS", 5
            ):
                report = audit_paths(events, paths, root)
            self.assertTrue(report["integrity_passed"])
            self.assertEqual(report["blocked_2025_2026_rows"], 0)

    def test_recomputed_metrics_match_persisted_metrics(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "postrun_integrity"
            output.mkdir()
            _events, paths = classification_fixture()
            persisted_paths = paths.drop(columns=["derived_event_id"])
            persisted_paths.to_csv(root / "path_metrics.csv", index=False)
            groups = {
                "aggregate_metrics.csv": ("event_type", "horizon", "symbol", "orientation", "year"),
                "metrics_by_symbol.csv": ("symbol",),
                "metrics_by_year.csv": ("year",),
                "metrics_by_event.csv": ("event_type",),
                "metrics_by_horizon.csv": ("horizon",),
            }
            frames = {}
            for filename, group_by in groups.items():
                base = aggregate_fcr_event_paths(persisted_paths, group_by=group_by, include_bootstrap=False)
                frames[filename] = attach_bootstrap_intervals(base, persisted_paths, group_by=group_by)
                frames[filename].to_csv(root / filename, index=False)
            frames["aggregate_metrics.csv"].loc[
                :,
                [
                    "event_type",
                    "horizon",
                    "symbol",
                    "orientation",
                    "year",
                    "bootstrap_reversal_mean_ci_low",
                    "bootstrap_reversal_mean_ci_high",
                    "bootstrap_grouped_by",
                    "bootstrap_seed",
                ],
            ].to_csv(root / "bootstrap_intervals.csv", index=False)
            _economic_threshold_comparison(frames["aggregate_metrics.csv"]).to_csv(
                root / "economic_threshold_comparison.csv", index=False
            )
            report = recompute_and_compare(paths, root, output)
            self.assertTrue(report["all_files_match_tolerance"])

    def test_classification_identifies_explicit_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _events, paths = classification_fixture()
            aggregate = aggregate_fcr_event_paths(
                paths.drop(columns=["derived_event_id"]),
                group_by=("event_type", "horizon", "symbol", "orientation", "year"),
            )
            report = audit_classification(paths, aggregate, root)
            self.assertEqual(report["classification_audit_status"], "passed")
            self.assertTrue(report["causing_combinations"])

    def test_classification_cannot_pass_without_justifying_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            event = event_row("QQQ", "EVENT-01", "2024-01-03", "2024-01-03T15:00:00+00:00")
            events = pd.DataFrame([event])
            paths = pd.DataFrame(path_rows_for_event(event, {horizon: 0.0 for horizon in EXPECTED_HORIZONS}))
            events, paths = add_derived_ids(events, paths)
            aggregate = aggregate_fcr_event_paths(
                paths.drop(columns=["derived_event_id"]),
                group_by=("event_type", "horizon", "symbol", "orientation", "year"),
            )
            report = audit_classification(paths, aggregate, root)
            self.assertEqual(report["classification_audit_status"], "failed")

    def test_continuation_is_opposite_of_reversal_and_no_strategy_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _events, paths = classification_fixture()
            aggregate = aggregate_fcr_event_paths(
                paths.drop(columns=["derived_event_id"]),
                group_by=("event_type", "horizon", "symbol", "orientation", "year"),
            )
            evidence = pd.DataFrame(
                [{"event_type": "EVENT-07", "classification_individual": "hypothesis_generating_signal"}]
            )
            report = audit_event_07_08(paths, aggregate, evidence, root)
            self.assertTrue(report["continuation_is_negative_reversal"])
            self.assertFalse({"order", "position_size", "quantity"}.intersection(paths.columns))

    def test_tick_thresholds_are_event_price_dependent_returns(self):
        self.assertAlmostEqual(one_tick_return(100.0, 0.01), 0.0001)
        self.assertAlmostEqual(two_tick_return(50.0, 0.01), 0.0004)
        self.assertGreater(one_tick_return(50.0, 0.01), one_tick_return(100.0, 0.01))

    def test_baseline_and_stress_friction_threshold_formula(self):
        baseline = friction_threshold_return(
            100.0,
            tick_size=0.01,
            commission_rate_per_side=0.0001,
            slippage_ticks_per_execution=1,
        )
        stress = friction_threshold_return(
            100.0,
            tick_size=0.01,
            commission_rate_per_side=0.0002,
            slippage_ticks_per_execution=2,
        )
        self.assertAlmostEqual(baseline, 0.0004)
        self.assertAlmostEqual(stress, 0.0008)

    def test_bootstrap_net_threshold_is_grouped_by_session(self):
        frame = pd.DataFrame(
            {
                "session_date": ["2024-01-02", "2024-01-02", "2024-01-03"],
                "net_return": [0.001, 0.003, -0.001],
            }
        )
        low, high = _bootstrap_mean_ci_by_session(frame, value_column="net_return", seed=17, n_bootstrap=50)
        self.assertLessEqual(low, high)
        self.assertGreater(high, -0.001)

    def test_stable_signal_without_preregistered_threshold_is_not_hypothesis_generating(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _events, paths = classification_fixture()
            report = audit_economic_thresholds(paths, root)
            self.assertEqual(report["final_classification"], "stable_but_not_economic")
            self.assertEqual(report["candidate_combinations_passing_all_preregistered_criteria"], 0)

    def test_hypothesis_generating_requires_economic_threshold_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _events, paths = classification_fixture()
            report = audit_economic_thresholds(paths, root)
            rows = pd.read_csv(root / "economic_threshold_by_candidate.csv")
            self.assertTrue(rows["one_tick_magnitude_pass"].all())
            self.assertFalse(rows["preregistered_economic_threshold_pass"].any())
            self.assertNotEqual(report["final_classification"], "hypothesis_generating_signal")

    def test_qqq_and_spy_must_share_effect_sign(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            events = []
            paths = []
            for year in (2022, 2023, 2024):
                qqq = event_row("QQQ", "EVENT-07", f"{year}-01-03", f"{year}-01-03T15:00:00+00:00")
                spy = event_row("SPY", "EVENT-07", f"{year}-01-03", f"{year}-01-03T15:05:00+00:00")
                events.extend([qqq, spy])
                paths.extend(path_rows_for_event(qqq, {horizon: -0.001 for horizon in EXPECTED_HORIZONS}))
                paths.extend(path_rows_for_event(spy, {horizon: 0.001 for horizon in EXPECTED_HORIZONS}))
            events_frame, paths_frame = add_derived_ids(pd.DataFrame(events), pd.DataFrame(paths))
            report = audit_economic_thresholds(paths_frame, root)
            rows = pd.read_csv(root / "economic_threshold_by_candidate.csv")
            event_07_rows = rows.loc[rows["event_type"] == "EVENT-07"]
            self.assertFalse(event_07_rows["same_sign_in_QQQ_and_SPY"].any())
            self.assertNotEqual(report["final_classification"], "hypothesis_generating_signal")

    def test_annual_consistency_is_required(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            events = []
            paths = []
            returns_by_year = {2022: -0.001, 2023: -0.001, 2024: 0.004}
            for year, reversal_return in returns_by_year.items():
                for symbol in ("QQQ", "SPY"):
                    event = event_row(symbol, "EVENT-07", f"{year}-01-03", f"{year}-01-03T15:00:00+00:00")
                    events.append(event)
                    paths.extend(path_rows_for_event(event, {horizon: reversal_return for horizon in EXPECTED_HORIZONS}))
            events_frame, paths_frame = add_derived_ids(pd.DataFrame(events), pd.DataFrame(paths))
            audit_economic_thresholds(paths_frame, root)
            rows = pd.read_csv(root / "economic_threshold_by_candidate.csv")
            self.assertFalse(rows.loc[rows["event_type"] == "EVENT-07", "annual_consistency_pass"].any())

    def test_economic_audit_does_not_create_strategy_or_unlock_2025_2026(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _events, paths = classification_fixture()
            report = audit_economic_thresholds(paths, root)
            self.assertFalse(report["strategy_created"])
            self.assertFalse(report["orders_sent"])
            self.assertFalse(report["position_sizing_used"])
            self.assertFalse(report["validation_2025_unlocked"])


if __name__ == "__main__":
    unittest.main()
