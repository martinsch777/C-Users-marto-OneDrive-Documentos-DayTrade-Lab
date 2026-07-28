from __future__ import annotations

import unittest
from pathlib import Path

import pandas as pd
import yaml

from src.research.hyp_or_cont_event_01 import (
    HORIZONS,
    PRIMARY_HORIZON,
    OrContEventConfig,
    assert_no_strategy_columns,
    compute_or_continuation_paths,
    detect_or_continuation_events,
    frozen_cost_profiles,
    round_trip_cost_return,
    validate_or_cont_period,
)


CONFIG_PATH = Path("configs/research/hypotheses/HYP-OR-CONT-EVENT-01.yaml")


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


def opening(date: str = "2024-07-01") -> list[dict]:
    return [
        bar(f"{date} 09:30", 100.0, 101.0, 99.0, 100.0),
        bar(f"{date} 09:35", 100.0, 101.0, 99.0, 100.0),
        bar(f"{date} 09:40", 100.0, 101.0, 99.0, 100.0),
        bar(f"{date} 09:45", 100.0, 101.0, 99.0, 100.0),
        bar(f"{date} 09:50", 100.0, 101.0, 99.0, 100.0),
        bar(f"{date} 09:55", 100.0, 101.0, 99.0, 100.0),
    ]


def frame(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows).sort_values("timestamp").reset_index(drop=True)


def low_sweep_day(extra: list[dict] | None = None, date: str = "2024-07-01") -> pd.DataFrame:
    rows = opening(date)
    rows.extend(
        [
            bar(f"{date} 10:00", 100.0, 100.2, 98.8, 99.4),
            bar(f"{date} 10:05", 99.4, 100.1, 98.9, 99.5),
            bar(f"{date} 10:10", 99.5, 100.0, 98.9, 99.6),
            bar(f"{date} 10:15", 99.6, 100.3, 98.95, 99.7),
            bar(f"{date} 10:20", 100.0, 100.2, 99.4, 99.8),
        ]
    )
    rows.extend(extra or [])
    return frame(rows)


def high_sweep_day(extra: list[dict] | None = None, date: str = "2024-07-01") -> pd.DataFrame:
    rows = opening(date)
    rows.extend(
        [
            bar(f"{date} 10:00", 100.0, 101.2, 99.8, 100.6),
            bar(f"{date} 10:05", 100.6, 101.1, 99.8, 100.5),
            bar(f"{date} 10:10", 100.5, 101.0, 99.7, 100.4),
            bar(f"{date} 10:15", 100.4, 100.9, 99.6, 100.3),
            bar(f"{date} 10:20", 100.0, 100.8, 99.5, 100.2),
        ]
    )
    rows.extend(extra or [])
    return frame(rows)


class HypOrContEvent01Tests(unittest.TestCase):
    def test_event_does_not_exist_before_third_confirmation_bar_closes(self):
        data = frame(opening() + low_sweep_day().iloc[6:9].to_dict("records"))
        events, exclusions = detect_or_continuation_events(data, "QQQ")
        self.assertTrue(events.empty)
        self.assertIn("insufficient_confirmation_bars", set(exclusions["reason_for_exclusion"]))

    def test_executable_timestamp_is_open_after_third_confirmation_bar(self):
        events, _ = detect_or_continuation_events(low_sweep_day(), "QQQ")
        event = events.iloc[0]
        self.assertEqual(event["confirmation_timestamp"], ts("2024-07-01 10:20"))
        self.assertEqual(event["executable_timestamp"], ts("2024-07-01 10:20"))
        self.assertEqual(event["confirmation_bar_count"], 3)

    def test_future_prices_after_executable_do_not_select_event(self):
        base_events, _ = detect_or_continuation_events(
            low_sweep_day([bar("2024-07-01 10:25", 100.0, 100.1, 99.6, 99.8)]),
            "QQQ",
        )
        changed = low_sweep_day([bar("2024-07-01 10:25", 100.0, 150.0, 50.0, 140.0)])
        changed_events, _ = detect_or_continuation_events(changed, "QQQ")
        pd.testing.assert_frame_equal(base_events, changed_events)

    def test_exactly_three_confirmation_bars_are_used(self):
        data = low_sweep_day([bar("2024-07-01 10:25", 102.0, 103.0, 102.0, 100.2)])
        events, _ = detect_or_continuation_events(data, "QQQ")
        self.assertEqual(events.iloc[0]["confirmation_bar_count"], 3)
        self.assertEqual(len(events), 1)

    def test_first_signal_per_session_wins_independent_of_side(self):
        data = low_sweep_day(
            [
                bar("2024-07-01 10:25", 100.0, 101.4, 99.7, 100.8),
                bar("2024-07-01 10:30", 100.8, 101.2, 99.8, 100.7),
                bar("2024-07-01 10:35", 100.7, 101.0, 99.6, 100.6),
                bar("2024-07-01 10:40", 100.6, 100.9, 99.6, 100.5),
                bar("2024-07-01 10:45", 100.5, 100.8, 99.5, 100.4),
            ]
        )
        events, _ = detect_or_continuation_events(data, "QQQ")
        self.assertEqual(len(events), 1)
        self.assertEqual(events.iloc[0]["swept_side"], "low")

    def test_maximum_one_event_per_session(self):
        data = pd.concat([low_sweep_day(date="2024-07-01"), high_sweep_day(date="2024-07-02")])
        events, _ = detect_or_continuation_events(data, "SPY")
        self.assertEqual(events.groupby("session_date").size().max(), 1)
        self.assertEqual(len(events), 2)

    def test_low_sweep_orientation_is_continuation_short(self):
        events, _ = detect_or_continuation_events(low_sweep_day(), "QQQ")
        self.assertEqual(events.iloc[0]["swept_side"], "low")
        self.assertEqual(events.iloc[0]["direction_orientation"], "continuation_short")

    def test_high_sweep_orientation_is_continuation_long(self):
        events, _ = detect_or_continuation_events(high_sweep_day(), "QQQ")
        self.assertEqual(events.iloc[0]["swept_side"], "high")
        self.assertEqual(events.iloc[0]["direction_orientation"], "continuation_long")

    def test_horizons_are_measured_from_executable_timestamp(self):
        data = low_sweep_day(
            [
                bar("2024-07-01 10:25", 100.0, 100.2, 98.0, 99.0),
                bar("2024-07-01 10:30", 99.0, 99.2, 97.8, 98.0),
                bar("2024-07-01 10:35", 98.0, 98.2, 97.0, 97.5),
                bar("2024-07-01 10:40", 97.5, 98.0, 96.8, 97.2),
                bar("2024-07-01 10:45", 97.2, 97.4, 96.5, 96.8),
                bar("2024-07-01 10:50", 96.8, 97.0, 96.0, 97.0),
            ]
        )
        events, _ = detect_or_continuation_events(data, "QQQ")
        paths = compute_or_continuation_paths(data, events, horizons=("30min",))
        self.assertEqual(paths.iloc[0]["horizon"], "30min")
        self.assertEqual(paths.iloc[0]["future_close"], 97.0)
        self.assertAlmostEqual(paths.iloc[0]["event_return"], 0.03)

    def test_paths_do_not_cross_overnight(self):
        data = low_sweep_day(
            [
                bar("2024-07-01 10:25", 100.0, 100.1, 99.8, 100.0),
                bar("2024-07-02 09:30", 200.0, 201.0, 199.0, 200.0),
                bar("2024-07-02 09:35", 200.0, 201.0, 199.0, 200.0),
                bar("2024-07-02 09:40", 200.0, 201.0, 199.0, 200.0),
                bar("2024-07-02 09:45", 200.0, 201.0, 199.0, 200.0),
                bar("2024-07-02 09:50", 200.0, 201.0, 199.0, 200.0),
                bar("2024-07-02 09:55", 200.0, 201.0, 199.0, 200.0),
                bar("2024-07-02 10:00", 200.0, 200.5, 199.5, 200.0),
            ]
        )
        events, _ = detect_or_continuation_events(data, "QQQ")
        paths = compute_or_continuation_paths(data, events, horizons=("60min",))
        self.assertTrue(paths.empty)

    def test_validation_2025_is_blocked(self):
        with self.assertRaises(PermissionError):
            validate_or_cont_period("validation_2025")

    def test_2026_is_blocked(self):
        with self.assertRaises(PermissionError):
            validate_or_cont_period("parity_debug_2026")

    def test_primary_horizon_is_fixed_at_30min(self):
        payload = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
        self.assertEqual(PRIMARY_HORIZON, "30min")
        self.assertEqual(payload["horizons"]["primary"], "30min")
        self.assertNotEqual(payload["horizons"]["primary"], "5min")
        self.assertEqual(HORIZONS[0], "30min")

    def test_costs_are_explicit_and_match_fcr_source(self):
        costs = frozen_cost_profiles()
        self.assertEqual(costs["baseline"]["commission_rate_per_side"], 0.0001)
        self.assertEqual(costs["baseline"]["slippage_ticks_per_execution"], 1.0)
        self.assertEqual(costs["baseline"]["round_trip_slippage_dollars_per_share"], 0.02)
        self.assertEqual(costs["stress"]["commission_rate_per_side"], 0.0002)
        self.assertEqual(costs["stress"]["slippage_ticks_per_execution"], 2.0)
        self.assertAlmostEqual(round_trip_cost_return("baseline", 100.0), 0.0004)

    def test_no_orders_no_strategy_no_position_sizing(self):
        payload = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
        self.assertTrue(payload["blocked_actions"]["create_strategy"])
        self.assertTrue(payload["blocked_actions"]["create_orders"])
        self.assertTrue(payload["blocked_actions"]["backtest_pnl"])
        events, _ = detect_or_continuation_events(low_sweep_day(), "QQQ")
        paths = compute_or_continuation_paths(low_sweep_day(), events, horizons=("15min",))
        assert_no_strategy_columns(events)
        assert_no_strategy_columns(paths)

    def test_safety_flags_remain_false(self):
        config = OrContEventConfig()
        self.assertEqual(config.confirmation_bar_count, 3)
        payload = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
        self.assertFalse(any(payload["safety_flags"].values()))


if __name__ == "__main__":
    unittest.main()
