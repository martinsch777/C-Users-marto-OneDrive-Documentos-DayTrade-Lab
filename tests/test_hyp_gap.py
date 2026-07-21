import copy
import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from src.data import EquitySessionCalendar
from src.research import compute_event_study
from src.research.hypotheses import hyp_gap
from src.research.hypotheses.hyp_gap import (
    DEFAULT_HYP_GAP_CONFIG_PATH,
    detect_hyp_gap_events,
    load_hyp_gap_preregistration,
)


CALENDAR = EquitySessionCalendar.from_config({"source": "us_equity"})


def ts(day: str, clock: str) -> pd.Timestamp:
    return pd.Timestamp(f"{day} {clock}", tz="America/New_York").tz_convert("UTC")


def session_days(end: str, count: int) -> list[str]:
    cursor = pd.Timestamp(end).date()
    days: list[str] = []
    while len(days) < count:
        if CALENDAR.session_close(cursor) is not None:
            days.append(cursor.isoformat())
        cursor = cursor - pd.Timedelta(days=1)
    return list(reversed(days))


def make_session(day: str, *, profile: str = "prior") -> pd.DataFrame:
    expected = CALENDAR.expected_timestamps(
        pd.Timestamp(day).date(),
        pd.Timestamp(day).date(),
        "1min",
    )
    rows = []
    for index, timestamp in enumerate(expected):
        local_clock = timestamp.tz_convert("America/New_York").strftime("%H:%M")
        open_price = close = 100.0
        high = 101.0
        low = 99.0
        volume = 1000.0
        if profile == "positive_continuation":
            open_price = close = 101.2
            high = low = close
            if local_clock == "09:30":
                open_price = 101.2
            if local_clock == "09:45":
                close = high = low = 101.4
            if local_clock > "09:45":
                open_price = close = high = low = 101.4
        elif profile == "positive_reversal":
            open_price = close = 101.2
            high = low = close
            if local_clock <= "09:44":
                volume = 500.0
            if local_clock == "09:45":
                close = high = low = 99.5
                volume = 500.0
            if local_clock > "09:45":
                open_price = close = high = low = 99.5
        elif profile == "negative_continuation":
            open_price = close = 98.8
            high = low = close
            if local_clock == "09:45":
                close = high = low = 98.6
            if local_clock > "09:45":
                open_price = close = high = low = 98.6
        elif profile == "negative_reversal":
            open_price = close = 98.8
            high = low = close
            if local_clock == "09:45":
                close = high = low = 100.5
            if local_clock > "09:45":
                open_price = close = high = low = 100.5
        elif profile == "near_threshold":
            open_price = close = 100.69
            high = low = close
            if local_clock == "09:45":
                close = high = low = 100.70
            if local_clock > "09:45":
                open_price = close = high = low = 100.70
        elif profile == "zero_gap":
            open_price = close = 100.0
            high = low = close
        rows.append(
            {
                "timestamp": timestamp,
                "open": open_price,
                "high": max(high, open_price, close),
                "low": min(low, open_price, close),
                "close": close,
                "volume": volume,
            }
        )
    return pd.DataFrame(rows)


def synthetic_frame(
    *,
    event_day: str = "2024-08-01",
    profile: str = "positive_continuation",
    prior_count: int = 22,
) -> pd.DataFrame:
    days = session_days(event_day, prior_count + 1)
    frames = [
        make_session(day, profile=(profile if day == event_day else "prior"))
        for day in days
    ]
    return pd.concat(frames, ignore_index=True)


def write_config(payload: dict) -> Path:
    directory = Path(tempfile.mkdtemp())
    path = directory / "HYP-GAP.yaml"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def load_payload() -> dict:
    payload, _ = hyp_gap._read_yaml(DEFAULT_HYP_GAP_CONFIG_PATH)
    return payload


class HypGapConfigTests(unittest.TestCase):
    def test_loads_valid_yaml_with_exact_six_variants(self):
        config = load_hyp_gap_preregistration()

        self.assertEqual(config.hypothesis_id, "HYP-GAP")
        self.assertEqual(len(config.variants), 6)
        self.assertEqual(
            [variant.variant_id for variant in config.variants],
            [f"HYP-GAP-{index:02d}" for index in range(1, 7)],
        )
        self.assertEqual(
            [variant.family for variant in config.variants].count("continuation"),
            3,
        )
        self.assertEqual(
            [variant.family for variant in config.variants].count("reversal"),
            3,
        )
        self.assertFalse(config.safety_flags["live_trading"])
        self.assertEqual(config.timeframe, "1min")
        self.assertEqual(config.validation_start.isoformat(), "2025-01-01")
        self.assertEqual(config.validation_end.isoformat(), "2025-12-31")
        self.assertEqual(config.final_holdout_start.isoformat(), "2026-01-01")
        self.assertEqual(config.final_holdout_end.isoformat(), "2026-07-06")

    def test_rejects_missing_variant(self):
        payload = load_payload()
        payload["variants"] = payload["variants"][:-1]

        with self.assertRaisesRegex(ValueError, "exactly six variants"):
            load_hyp_gap_preregistration(write_config(payload))

    def test_rejects_additional_variant(self):
        payload = load_payload()
        payload["variants"].append(copy.deepcopy(payload["variants"][-1]))
        payload["variants"][-1]["variant_id"] = "HYP-GAP-07"

        with self.assertRaisesRegex(ValueError, "exactly six variants"):
            load_hyp_gap_preregistration(write_config(payload))

    def test_rejects_duplicate_variant_id(self):
        payload = load_payload()
        payload["variants"][1]["variant_id"] = "HYP-GAP-01"

        with self.assertRaisesRegex(ValueError, "unique|variant_id"):
            load_hyp_gap_preregistration(write_config(payload))

    def test_rejects_missing_threshold(self):
        payload = load_payload()
        del payload["variants"][0]["threshold"]

        with self.assertRaisesRegex(ValueError, "threshold"):
            load_hyp_gap_preregistration(write_config(payload))

    def test_rejects_altered_threshold(self):
        payload = load_payload()
        payload["variants"][0]["threshold"]["normalized_gap_min"] = 0.49

        with self.assertRaisesRegex(ValueError, "threshold"):
            load_hyp_gap_preregistration(write_config(payload))

    def test_rejects_invalid_status(self):
        payload = load_payload()
        payload["status"] = "DRAFT"

        with self.assertRaisesRegex(ValueError, "status"):
            load_hyp_gap_preregistration(write_config(payload))

    def test_rejects_enabled_safety_flag(self):
        payload = load_payload()
        payload["safety_flags"]["paper_broker_enabled"] = True

        with self.assertRaisesRegex(ValueError, "paper_broker_enabled"):
            load_hyp_gap_preregistration(write_config(payload))

    def test_rejects_discovery_that_opens_validation(self):
        payload = load_payload()
        payload["splits"]["discovery"]["end"] = "2025-01-01"

        with self.assertRaisesRegex(ValueError, "validation"):
            load_hyp_gap_preregistration(write_config(payload))

    def test_rejects_discovery_that_opens_holdout(self):
        payload = load_payload()
        payload["splits"]["discovery"]["end"] = "2026-01-01"

        with self.assertRaisesRegex(ValueError, "validation|holdout"):
            load_hyp_gap_preregistration(write_config(payload))


class HypGapDetectionTests(unittest.TestCase):
    def detect(self, frame: pd.DataFrame, **kwargs):
        if "start_date" in kwargs and "end_date" in kwargs:
            days = [kwargs["start_date"], kwargs["end_date"]]
        else:
            days = sorted(
                {
                    item.tz_convert("America/New_York").date().isoformat()
                    for item in frame["timestamp"]
                }
            )
        return detect_hyp_gap_events(
            frame,
            symbol=kwargs.pop("symbol", "QQQ"),
            timeframe=kwargs.pop("timeframe", "1min"),
            start_date=kwargs.pop("start_date", days[0]),
            end_date=kwargs.pop("end_date", days[-1]),
            calendar=CALENDAR,
            **kwargs,
        )

    def test_positive_gap_variables_are_computed_causally(self):
        result = self.detect(synthetic_frame())
        variables = result.session_variables[-1]

        self.assertEqual(variables.previous_session_close, 100.0)
        self.assertAlmostEqual(variables.current_session_open, 101.2)
        self.assertAlmostEqual(variables.gap_return, 0.012)
        self.assertEqual(variables.gap_direction, 1)
        self.assertAlmostEqual(variables.prior_atr, 2.0)
        self.assertAlmostEqual(variables.normalized_gap, 0.6)
        self.assertAlmostEqual(variables.opening_return, 101.4 / 101.2 - 1.0)
        self.assertAlmostEqual(variables.opening_move_atr, 0.1)
        self.assertAlmostEqual(variables.relative_volume_0930_0945, 1.0)
        self.assertEqual(variables.confirmation_timestamp, ts("2024-08-01", "09:45"))

    def test_negative_gap_and_zero_gap_handling(self):
        negative = self.detect(synthetic_frame(profile="negative_continuation"))
        neg_vars = negative.session_variables[-1]
        self.assertEqual(neg_vars.gap_direction, -1)
        self.assertLess(neg_vars.gap_return, 0)

        zero = self.detect(synthetic_frame(profile="zero_gap"))
        self.assertGreaterEqual(zero.summary.ineligible_reasons["invalid_gap_direction"], 1)
        self.assertEqual(len(zero.events), 0)

    def test_vwap_until_confirmation_uses_typical_price_and_opening_move(self):
        result = self.detect(synthetic_frame(profile="positive_continuation"))
        variables = result.session_variables[-1]
        opening_rows = make_session("2024-08-01", profile="positive_continuation").iloc[:16]
        typical = (opening_rows["high"] + opening_rows["low"] + opening_rows["close"]) / 3.0
        expected_vwap = float((typical * opening_rows["volume"]).sum() / opening_rows["volume"].sum())

        self.assertAlmostEqual(variables.confirmation_vwap, expected_vwap)
        self.assertGreater(variables.confirmation_close, variables.confirmation_vwap)

    def test_relative_volume_uses_prior_20_session_median(self):
        frame = synthetic_frame(profile="positive_reversal")
        result = self.detect(frame)
        variables = result.session_variables[-1]

        self.assertAlmostEqual(variables.volume_0930_0945, 8000.0)
        self.assertAlmostEqual(variables.relative_volume_0930_0945, 0.5)

    def test_warmup_insufficient(self):
        result = self.detect(synthetic_frame(prior_count=5))

        self.assertGreaterEqual(result.summary.ineligible_reasons["insufficient_atr_warmup"], 1)
        self.assertEqual(len(result.events), 0)

    def test_each_preregistered_variant_can_emit_event(self):
        continuation = self.detect(synthetic_frame(profile="positive_continuation"))
        reversal = self.detect(synthetic_frame(profile="positive_reversal"))
        variant_ids = {event.variant_id for event in continuation.events + reversal.events}

        self.assertEqual(
            variant_ids,
            {f"HYP-GAP-{index:02d}" for index in range(1, 7)},
        )

    def test_variant_threshold_miss_emits_no_event(self):
        result = self.detect(synthetic_frame(profile="near_threshold"))

        self.assertEqual(len(result.events), 0)

    def test_continuation_and_reversal_support_gap_signs(self):
        negative_continuation = self.detect(synthetic_frame(profile="negative_continuation"))
        negative_reversal = self.detect(synthetic_frame(profile="negative_reversal"))

        self.assertTrue(
            {"HYP-GAP-01", "HYP-GAP-02", "HYP-GAP-03"}.issubset(
                {event.variant_id for event in negative_continuation.events}
            )
        )
        self.assertTrue(
            {"HYP-GAP-04", "HYP-GAP-05"}.issubset(
                {event.variant_id for event in negative_reversal.events}
            )
        )

    def test_multiple_variants_event_ids_metadata_and_order_are_deterministic(self):
        result = self.detect(synthetic_frame(profile="positive_continuation"))
        event_ids = [event.event_id for event in result.events]

        self.assertEqual(event_ids, sorted(event_ids))
        self.assertEqual(
            event_ids,
            [
                "HYP-GAP:HYP-GAP-01:QQQ:2024-08-01",
                "HYP-GAP:HYP-GAP-02:QQQ:2024-08-01",
                "HYP-GAP:HYP-GAP-03:QQQ:2024-08-01",
            ],
        )
        metadata = result.events[0].metadata
        self.assertIn("gap_return", metadata)
        self.assertIn("variant_conditions_evaluated", metadata)
        self.assertFalse(metadata["safety_flags"]["orders_sent"])
        self.assertEqual(metadata["opening_window"], "09:30_through_09:45_inclusive_bar_opens")

    def test_early_close_previous_session_and_holiday_gap(self):
        days = session_days("2024-07-05", 23)
        frame = pd.concat(
            [
                make_session(day, profile=("positive_continuation" if day == "2024-07-05" else "prior"))
                for day in days
            ],
            ignore_index=True,
        )

        result = self.detect(frame)
        variables = result.session_variables[-1]

        self.assertEqual(variables.session_date, "2024-07-05")
        self.assertEqual(variables.previous_session_date, "2024-07-03")

    def test_excluded_session_is_not_current_or_previous_or_warmup(self):
        days = session_days("2024-08-01", 24)
        excluded_day = days[-2]
        frame = pd.concat(
            [
                make_session(day, profile=("positive_continuation" if day == "2024-08-01" else "prior"))
                for day in days
            ],
            ignore_index=True,
        )

        result = self.detect(frame, excluded_session_dates={excluded_day})
        variables = result.session_variables[-1]

        self.assertNotEqual(variables.previous_session_date, excluded_day)
        self.assertEqual(result.summary.ineligible_reasons["excluded_session"], 1)

    def test_rejects_incomplete_current_session_and_missing_opening_bars(self):
        frame = synthetic_frame()
        truncated = frame.loc[frame["timestamp"] <= ts("2024-08-01", "09:40")]
        result = self.detect(truncated)
        self.assertEqual(result.summary.ineligible_reasons["confirmation_bar_missing"], 1)

        missing_open = frame.loc[frame["timestamp"] != ts("2024-08-01", "09:30")]
        result = self.detect(missing_open)
        self.assertEqual(result.summary.ineligible_reasons["opening_bar_missing"], 1)

        missing_inside = frame.loc[frame["timestamp"] != ts("2024-08-01", "09:37")]
        result = self.detect(missing_inside)
        self.assertEqual(result.summary.ineligible_reasons["incomplete_opening_window"], 1)

    def test_rejects_bad_input_shape_time_and_symbol(self):
        frame = synthetic_frame()
        naive = frame.copy()
        naive["timestamp"] = naive["timestamp"].dt.tz_localize(None)
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            self.detect(naive, start_date="2024-07-01", end_date="2024-08-01")

        duplicate = pd.concat([frame, frame.iloc[[0]]], ignore_index=True).sort_values("timestamp")
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.detect(duplicate)

        with self.assertRaisesRegex(ValueError, "timeframe"):
            self.detect(frame, timeframe="5min")

        with self.assertRaisesRegex(ValueError, "not preregistered"):
            self.detect(frame, symbol="IWM")

    def test_modifying_bars_after_confirmation_does_not_change_detection(self):
        frame = synthetic_frame(profile="positive_continuation")
        base = self.detect(frame)
        changed = frame.copy()
        changed.loc[changed["timestamp"] > ts("2024-08-01", "09:45"), ["open", "high", "low", "close"]] = [
            499.5,
            500.0,
            499.0,
            499.5,
        ]

        after = self.detect(changed)

        self.assertEqual([event.event_id for event in after.events], [event.event_id for event in base.events])
        self.assertEqual(after.events[0].metadata["prior_atr"], base.events[0].metadata["prior_atr"])

    def test_future_sessions_do_not_change_prior_detection_or_features(self):
        frame = synthetic_frame(event_day="2024-08-01", profile="positive_continuation")
        future = make_session("2024-08-02", profile="negative_reversal")
        with_future = pd.concat([frame, future], ignore_index=True)

        base = self.detect(frame, end_date="2024-08-01")
        after = self.detect(with_future, end_date="2024-08-01")

        self.assertEqual([event.event_id for event in after.events], [event.event_id for event in base.events])
        self.assertEqual(after.session_variables[-1].prior_atr, base.session_variables[-1].prior_atr)
        changed_future = with_future.copy()
        changed_future.loc[
            changed_future["timestamp"] == ts("2024-08-02", "15:59"),
            ["open", "high", "low", "close"],
        ] = [9999.0, 10000.0, 9998.0, 9999.0]
        changed = self.detect(changed_future, end_date="2024-08-01")
        self.assertEqual(changed.session_variables[-1].relative_volume_0930_0945, base.session_variables[-1].relative_volume_0930_0945)

    def test_current_session_does_not_participate_in_own_atr(self):
        frame = synthetic_frame(profile="positive_continuation")
        base = self.detect(frame)
        changed = frame.copy()
        current = changed["timestamp"].map(lambda value: value.tz_convert("America/New_York").date().isoformat()) == "2024-08-01"
        changed.loc[current & (changed["timestamp"] > ts("2024-08-01", "09:45")), "high"] = 10000.0
        changed.loc[current & (changed["timestamp"] > ts("2024-08-01", "09:45")), "low"] = 1.0

        after = self.detect(changed)

        self.assertEqual(after.session_variables[-1].prior_atr, base.session_variables[-1].prior_atr)
        self.assertEqual(after.session_variables[-1].normalized_gap, base.session_variables[-1].normalized_gap)

    def test_events_are_compatible_with_generic_event_study_schema(self):
        frame = synthetic_frame(profile="positive_continuation")
        result = self.detect(frame)
        event_results = compute_event_study(
            frame,
            result.events,
            calendar=CALENDAR,
            timeframe="1min",
            horizons=("5min",),
        )

        self.assertEqual(len(event_results), len(result.events))
        self.assertEqual(set(event_results["availability_status"]), {"available"})
        self.assertFalse(result.summary.safety_flags["paper_broker_enabled"])
        self.assertEqual(result.summary.events_by_symbol["QQQ"], len(result.events))

    def test_validation_phase_is_allowed_only_before_holdout_with_frozen_variant(self):
        frame = synthetic_frame(event_day="2025-01-02", profile="positive_continuation")

        result = self.detect(
            frame,
            start_date="2024-12-02",
            end_date="2025-01-02",
            event_start_date="2025-01-02",
            research_phase="validation",
            variant_ids=("HYP-GAP-03",),
        )

        self.assertEqual([event.variant_id for event in result.events], ["HYP-GAP-03"])
        with self.assertRaisesRegex(ValueError, "holdout"):
            self.detect(
                frame,
                start_date="2024-12-02",
                end_date="2026-01-02",
                event_start_date="2025-01-02",
                research_phase="validation",
                variant_ids=("HYP-GAP-03",),
            )
        with self.assertRaisesRegex(ValueError, "inside validation"):
            self.detect(
                frame,
                start_date="2024-12-02",
                end_date="2025-01-02",
                event_start_date="2024-12-31",
                research_phase="validation",
                variant_ids=("HYP-GAP-03",),
            )


if __name__ == "__main__":
    unittest.main()
