from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from src.research.hyp_first_candle_event_runner import (
    FcrEventStudyRunRequest,
    prepare_event_study_manifest,
    validate_event_study_request,
)
from src.research.hyp_first_candle_event_study import (
    EVENT_TYPES,
    FcrEventStudyConfig,
    aggregate_fcr_event_paths,
    assert_no_strategy_columns,
    build_opening_range,
    compute_fcr_event_paths,
    detect_fcr_event_study_events,
    load_approved_event_dataset,
    validate_event_study_period,
)


def ts(value: str) -> pd.Timestamp:
    return pd.Timestamp(value, tz="America/New_York").tz_convert("UTC")


def bar(value: str, open_: float, high: float, low: float, close: float) -> dict:
    return {
        "timestamp": ts(value),
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": 1000,
    }


def frame(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows).sort_values("timestamp").reset_index(drop=True)


def opening(date: str = "2024-07-01") -> list[dict]:
    rows = []
    for minute in ("09:30", "09:35", "09:40", "09:45", "09:50", "09:55"):
        rows.append(bar(f"{date} {minute}", 100.0, 101.0, 99.0, 100.0))
    return rows


def base_day(extra: list[dict], date: str = "2024-07-01") -> pd.DataFrame:
    return frame(opening(date) + extra)


class HypFirstCandleEventStudyTests(unittest.TestCase):
    def test_01_opening_range_uses_six_bars(self):
        ranges = build_opening_range(base_day([bar("2024-07-01 10:00", 100, 100.5, 99.5, 100)]))
        self.assertEqual(len(ranges), 1)
        self.assertEqual(ranges.iloc[0]["opening_high"], 101.0)
        self.assertEqual(ranges.iloc[0]["opening_low"], 99.0)

    def test_02_opening_range_rejects_incomplete_or(self):
        incomplete = frame(opening()[:5] + [bar("2024-07-01 10:00", 100, 100.5, 99.5, 100)])
        self.assertTrue(build_opening_range(incomplete).empty)

    def test_03_event_01_detects_first_low_touch(self):
        events = detect_fcr_event_study_events(
            base_day(
                [
                    bar("2024-07-01 10:00", 100, 100.3, 99.0, 99.6),
                    bar("2024-07-01 10:05", 99.6, 100, 98.8, 99.4),
                ]
            ),
            "QQQ",
        )
        event_01 = events.loc[events["event_type"] == "EVENT-01"]
        self.assertEqual(len(event_01), 1)
        self.assertEqual(event_01.iloc[0]["event_time"], ts("2024-07-01 10:00"))

    def test_04_event_02_requires_one_tick_strict_break(self):
        no_break = detect_fcr_event_study_events(base_day([bar("2024-07-01 10:00", 100, 100.3, 99.0, 99.6)]), "QQQ")
        strict = detect_fcr_event_study_events(base_day([bar("2024-07-01 10:00", 100, 100.3, 98.99, 99.6)]), "QQQ")
        self.assertNotIn("EVENT-02", set(no_break["event_type"]))
        self.assertIn("EVENT-02", set(strict["event_type"]))

    def test_05_event_03_detects_first_high_touch(self):
        events = detect_fcr_event_study_events(base_day([bar("2024-07-01 10:00", 100, 101.0, 99.8, 100.4)]), "QQQ")
        self.assertIn("EVENT-03", set(events["event_type"]))

    def test_06_event_04_requires_one_tick_strict_break(self):
        no_break = detect_fcr_event_study_events(base_day([bar("2024-07-01 10:00", 100, 101.0, 99.8, 100.4)]), "QQQ")
        strict = detect_fcr_event_study_events(base_day([bar("2024-07-01 10:00", 100, 101.01, 99.8, 100.4)]), "QQQ")
        self.assertNotIn("EVENT-04", set(no_break["event_type"]))
        self.assertIn("EVENT-04", set(strict["event_type"]))

    def test_07_event_05_uses_latest_low_sweep_before_bullish_fvg(self):
        events = detect_fcr_event_study_events(
            base_day(
                [
                    bar("2024-07-01 10:00", 100, 100.0, 98.8, 99.4),
                    bar("2024-07-01 10:05", 99.4, 100.1, 98.7, 99.5),
                    bar("2024-07-01 10:10", 99.5, 100.8, 100.2, 100.5),
                ]
            ),
            "QQQ",
        )
        event = events.loc[events["event_type"] == "EVENT-05"].iloc[0]
        self.assertEqual(event["last_sweep_time"], ts("2024-07-01 10:05"))
        self.assertEqual(event["bars_since_sweep"], 1)

    def test_08_event_06_uses_latest_high_sweep_before_bearish_fvg(self):
        events = detect_fcr_event_study_events(
            base_day(
                [
                    bar("2024-07-01 10:00", 100, 101.2, 100.0, 100.6),
                    bar("2024-07-01 10:05", 100.6, 101.3, 99.9, 100.4),
                    bar("2024-07-01 10:10", 100.4, 99.7, 99.2, 99.5),
                ]
            ),
            "QQQ",
        )
        event = events.loc[events["event_type"] == "EVENT-06"].iloc[0]
        self.assertEqual(event["last_sweep_time"], ts("2024-07-01 10:05"))

    def test_09_event_07_low_sweep_without_next_three_bar_bullish_fvg(self):
        events = detect_fcr_event_study_events(
            base_day(
                [
                    bar("2024-07-01 10:00", 100, 100.2, 98.9, 99.4),
                    bar("2024-07-01 10:05", 99.4, 100.1, 99.2, 99.7),
                    bar("2024-07-01 10:10", 99.7, 100.2, 99.3, 99.8),
                    bar("2024-07-01 10:15", 99.8, 100.2, 99.4, 99.9),
                ]
            ),
            "QQQ",
        )
        self.assertIn("EVENT-07", set(events["event_type"]))

    def test_10_event_08_high_sweep_without_next_three_bar_bearish_fvg(self):
        events = detect_fcr_event_study_events(
            base_day(
                [
                    bar("2024-07-01 10:00", 100, 101.2, 99.8, 100.7),
                    bar("2024-07-01 10:05", 100.7, 101.0, 99.8, 100.6),
                    bar("2024-07-01 10:10", 100.6, 100.9, 99.9, 100.4),
                    bar("2024-07-01 10:15", 100.4, 100.8, 99.8, 100.3),
                ]
            ),
            "QQQ",
        )
        self.assertIn("EVENT-08", set(events["event_type"]))

    def test_11_event_09_bullish_fvg_inside_range_without_prior_low_sweep(self):
        events = detect_fcr_event_study_events(
            base_day(
                [
                    bar("2024-07-01 10:00", 100, 100.0, 99.6, 99.8),
                    bar("2024-07-01 10:05", 99.8, 100.0, 99.5, 99.7),
                    bar("2024-07-01 10:10", 99.7, 100.8, 100.2, 100.4),
                ]
            ),
            "QQQ",
        )
        self.assertIn("EVENT-09", set(events["event_type"]))

    def test_12_event_10_bearish_fvg_inside_range_without_prior_high_sweep(self):
        events = detect_fcr_event_study_events(
            base_day(
                [
                    bar("2024-07-01 10:00", 100, 100.6, 100.1, 100.3),
                    bar("2024-07-01 10:05", 100.3, 100.4, 99.8, 100.2),
                    bar("2024-07-01 10:10", 100.2, 99.7, 99.4, 99.6),
                ]
            ),
            "QQQ",
        )
        self.assertIn("EVENT-10", set(events["event_type"]))

    def test_13_all_ten_event_types_are_declared(self):
        self.assertEqual(EVENT_TYPES, tuple(f"EVENT-{index:02d}" for index in range(1, 11)))

    def test_14_path_uses_5_15_30_60_and_session_close_horizons(self):
        rows = opening()
        rows += [bar(f"2024-07-01 {minute}", 100, 100.5, 99.0, 100 + index) for index, minute in enumerate(["10:00", "10:05", "10:10", "10:15", "10:20", "10:25", "10:30", "10:35", "10:40", "10:45", "10:50", "10:55", "11:00", "11:05"])]
        data = frame(rows)
        events = detect_fcr_event_study_events(data, "QQQ")
        paths = compute_fcr_event_paths(data, events.loc[events["event_type"] == "EVENT-01"], horizons=("5min", "15min", "30min", "60min", "session_close"))
        self.assertEqual(set(paths["horizon"]), {"5min", "15min", "30min", "60min", "session_close"})

    def test_15_session_close_uses_last_available_bar(self):
        data = base_day(
            [
                bar("2024-07-03 10:00", 100, 100.5, 99.0, 100),
                bar("2024-07-03 10:05", 100, 100.5, 99.4, 101),
                bar("2024-07-03 13:00", 101, 101.5, 100.5, 102),
            ],
            date="2024-07-03",
        )
        events = detect_fcr_event_study_events(data, "QQQ")
        paths = compute_fcr_event_paths(data, events.loc[events["event_type"] == "EVENT-01"], horizons=("session_close",))
        self.assertEqual(paths.iloc[0]["future_close"], 102)

    def test_16_paths_include_mfe_mae(self):
        data = base_day(
            [
                bar("2024-07-01 10:00", 100, 100.2, 99.0, 100),
                bar("2024-07-01 10:05", 100, 103.0, 98.0, 101),
            ]
        )
        events = detect_fcr_event_study_events(data, "QQQ")
        result = compute_fcr_event_paths(data, events.loc[events["event_type"] == "EVENT-01"], horizons=("5min",)).iloc[0]
        self.assertGreater(result["maximum_favorable_excursion"], 0)
        self.assertLess(result["maximum_adverse_excursion"], 0)

    def test_17_low_events_orient_reversal_as_long(self):
        data = base_day([bar("2024-07-01 10:00", 100, 100.2, 99.0, 100), bar("2024-07-01 10:05", 100, 101, 99.5, 101)])
        events = detect_fcr_event_study_events(data, "QQQ")
        result = compute_fcr_event_paths(data, events.loc[events["event_type"] == "EVENT-01"], horizons=("5min",)).iloc[0]
        self.assertGreater(result["reversal_return"], 0)
        self.assertLess(result["continuation_return"], 0)

    def test_18_high_events_orient_reversal_as_short(self):
        data = base_day([bar("2024-07-01 10:00", 100, 101.0, 99.8, 100), bar("2024-07-01 10:05", 100, 100, 98, 99)])
        events = detect_fcr_event_study_events(data, "QQQ")
        result = compute_fcr_event_paths(data, events.loc[events["event_type"] == "EVENT-03"], horizons=("5min",)).iloc[0]
        self.assertGreater(result["reversal_return"], 0)
        self.assertLess(result["continuation_return"], 0)

    def test_19_path_does_not_look_beyond_horizon(self):
        data = base_day(
            [
                bar("2024-07-01 10:00", 100, 100.2, 99.0, 100),
                bar("2024-07-01 10:05", 100, 101, 99.5, 101),
                bar("2024-07-01 10:10", 101, 150, 50, 120),
            ]
        )
        events = detect_fcr_event_study_events(data, "QQQ")
        first = compute_fcr_event_paths(data, events.loc[events["event_type"] == "EVENT-01"], horizons=("5min",)).iloc[0]
        changed = data.copy()
        changed.loc[changed["timestamp"] == ts("2024-07-01 10:10"), ["high", "low", "close"]] = [300, 10, 200]
        second = compute_fcr_event_paths(changed, events.loc[events["event_type"] == "EVENT-01"], horizons=("5min",)).iloc[0]
        self.assertEqual(first["future_close"], second["future_close"])
        self.assertEqual(first["maximum_favorable_excursion"], second["maximum_favorable_excursion"])

    def test_20_invalid_period_blocks_validation_2025(self):
        with self.assertRaises(PermissionError):
            validate_event_study_period("validation_2025")

    def test_21_invalid_period_blocks_2026(self):
        with self.assertRaises(PermissionError):
            validate_event_study_period("parity_debug_2026")

    def test_22_invalid_manifest_is_rejected_without_real_history(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            csv_path = root / "QQQ.csv"
            manifest_path = root / "manifest.json"
            csv_path.write_text("timestamp,open,high,low,close,volume\n2024-01-02T14:30:00Z,1,1,1,1,1\n", encoding="utf-8")
            manifest_path.write_text(json.dumps({"symbol": "QQQ", "status": "failed"}), encoding="utf-8")
            with self.assertRaises(Exception):
                load_approved_event_dataset("QQQ", csv_path, manifest_path)

    def test_23_bootstrap_by_session_is_deterministic(self):
        data = base_day([bar("2024-07-01 10:00", 100, 100.2, 99.0, 100), bar("2024-07-01 10:05", 100, 101, 99.5, 101)])
        events = detect_fcr_event_study_events(data, "QQQ")
        paths = compute_fcr_event_paths(data, events.loc[events["event_type"] == "EVENT-01"], horizons=("5min",))
        first = aggregate_fcr_event_paths(paths, n_bootstrap=50, seed=3)
        second = aggregate_fcr_event_paths(paths, n_bootstrap=50, seed=3)
        pd.testing.assert_frame_equal(first, second)

    def test_24_runner_prepare_only_manifest(self):
        manifest = prepare_event_study_manifest(FcrEventStudyRunRequest())
        self.assertEqual(manifest["mode"], "prepare_only")
        self.assertFalse(manifest["event_study_executed"])
        self.assertFalse(manifest["orders_sent"])

    def test_25_runner_rejects_non_prepare_modes(self):
        with self.assertRaises(PermissionError):
            validate_event_study_request(FcrEventStudyRunRequest(mode="run"))  # type: ignore[arg-type]

    def test_26_runner_run_discovery_requires_freeze_commit(self):
        with self.assertRaises(PermissionError):
            validate_event_study_request(
                FcrEventStudyRunRequest(
                    mode="run_discovery",
                    expected_canonical_hash="f" * 64,
                )
            )

    def test_27_outputs_do_not_include_order_or_position_sizing_columns(self):
        data = base_day([bar("2024-07-01 10:00", 100, 100.2, 99.0, 100), bar("2024-07-01 10:05", 100, 101, 99.5, 101)])
        events = detect_fcr_event_study_events(data, "QQQ")
        paths = compute_fcr_event_paths(data, events.loc[events["event_type"] == "EVENT-01"], horizons=("5min",))
        assert_no_strategy_columns(events)
        assert_no_strategy_columns(paths)

    def test_28_event_detection_is_deterministic(self):
        data = base_day([bar("2024-07-01 10:00", 100, 100.2, 99.0, 100), bar("2024-07-01 10:05", 100, 101, 99.5, 101)])
        first = detect_fcr_event_study_events(data, "QQQ")
        second = detect_fcr_event_study_events(data, "QQQ")
        pd.testing.assert_frame_equal(first, second)

    def test_29_config_declares_no_strategy_intent(self):
        config = FcrEventStudyConfig()
        self.assertEqual(config.allowed_periods, ("discovery_2022_2024",))
        self.assertFalse(any(config.safety_flags.values()))


if __name__ == "__main__":
    unittest.main()
