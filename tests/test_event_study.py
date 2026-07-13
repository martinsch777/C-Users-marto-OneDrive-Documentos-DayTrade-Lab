import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from src.data import EquitySessionCalendar
from src.research import (
    DEFAULT_EVENT_STUDY_HORIZONS,
    EventStudyEvent,
    EventStudyRunConfig,
    aggregate_event_results,
    compute_event_study,
    write_event_study_outputs,
)


def minute_session(date: str, symbol: str, *, start_price: float = 100.0) -> pd.DataFrame:
    timestamps = pd.date_range(
        f"{date} 09:30",
        f"{date} 15:59",
        freq="1min",
        tz="America/New_York",
    ).tz_convert("UTC")
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": [start_price + index for index in range(len(timestamps))],
            "high": [start_price + index + 0.5 for index in range(len(timestamps))],
            "low": [start_price + index - 0.5 for index in range(len(timestamps))],
            "close": [start_price + index for index in range(len(timestamps))],
            "volume": [1000.0] * len(timestamps),
            "symbol": [symbol] * len(timestamps),
        }
    )


def frame_two_years() -> pd.DataFrame:
    return pd.concat(
        [
            minute_session("2024-07-01", "QQQ", start_price=100.0),
            minute_session("2025-07-01", "QQQ", start_price=200.0),
        ],
        ignore_index=True,
    )


def ts(date: str, clock: str) -> pd.Timestamp:
    return pd.Timestamp(f"{date} {clock}", tz="America/New_York").tz_convert("UTC")


def event(
    event_id: str = "EVT-1",
    *,
    symbol: str = "QQQ",
    timestamp: pd.Timestamp | None = None,
    session_date: str = "2024-07-01",
    expected_direction: int | None = 1,
    hypothesis_id: str = "HYP-GAP-01",
    variant_id: str = "V01",
) -> EventStudyEvent:
    return EventStudyEvent(
        event_id=event_id,
        hypothesis_id=hypothesis_id,
        variant_id=variant_id,
        symbol=symbol,
        timestamp=timestamp or ts("2024-07-01", "10:00"),
        session_date=session_date,
        expected_direction=expected_direction,
        metadata={"fixture": True},
    )


class EventStudyTests(unittest.TestCase):
    def test_computes_all_required_horizons_for_bullish_event(self):
        frame = minute_session("2024-07-01", "QQQ")
        results = compute_event_study(frame, [event()])
        by_horizon = results.set_index("horizon")
        event_price = 130.0

        self.assertEqual(tuple(results["horizon"]), DEFAULT_EVENT_STUDY_HORIZONS)
        self.assertAlmostEqual(
            by_horizon.loc["5min", "raw_return"],
            135.0 / event_price - 1.0,
        )
        self.assertAlmostEqual(
            by_horizon.loc["15min", "raw_return"],
            145.0 / event_price - 1.0,
        )
        self.assertAlmostEqual(
            by_horizon.loc["30min", "raw_return"],
            160.0 / event_price - 1.0,
        )
        self.assertAlmostEqual(
            by_horizon.loc["60min", "raw_return"],
            190.0 / event_price - 1.0,
        )
        self.assertAlmostEqual(
            by_horizon.loc["session_close", "raw_return"],
            489.0 / event_price - 1.0,
        )
        self.assertEqual(set(results["availability_status"]), {"available"})

    def test_bearish_and_non_directional_events(self):
        frame = minute_session("2024-07-01", "QQQ")
        results = compute_event_study(
            frame,
            [
                event("BEAR", expected_direction=-1),
                event("NONE", expected_direction=0),
            ],
            horizons=("5min",),
        ).set_index("event_id")

        self.assertLess(results.loc["BEAR", "directional_return"], 0)
        self.assertTrue(pd.isna(results.loc["NONE", "directional_return"]))
        self.assertAlmostEqual(
            results.loc["NONE", "analysis_return"],
            results.loc["NONE", "raw_return"],
        )

    def test_missing_future_bar_is_explicit_result(self):
        frame = minute_session("2024-07-01", "QQQ")
        frame = frame.loc[frame["timestamp"] != ts("2024-07-01", "10:05")].reset_index(drop=True)

        result = compute_event_study(frame, [event()], horizons=("5min",)).iloc[0]

        self.assertEqual(result["availability_status"], "missing")
        self.assertEqual(result["missing_reason"], "future_bar_missing")
        self.assertTrue(pd.isna(result["raw_return"]))

    def test_horizon_crosses_session_near_close(self):
        frame = minute_session("2024-07-01", "QQQ")

        result = compute_event_study(
            frame,
            [
                event(
                    "CLOSE",
                    timestamp=ts("2024-07-01", "15:58"),
                    session_date="2024-07-01",
                )
            ],
            horizons=("5min",),
        ).iloc[0]

        self.assertEqual(result["availability_status"], "missing")
        self.assertEqual(result["missing_reason"], "horizon_crosses_session")

    def test_event_outside_dataset_rejected(self):
        with self.assertRaisesRegex(ValueError, "outside the dataset"):
            compute_event_study(
                minute_session("2024-07-01", "QQQ"),
                [event(timestamp=ts("2024-07-02", "10:00"), session_date="2024-07-02")],
                horizons=("5min",),
            )

    def test_duplicate_dataset_timestamp_rejected(self):
        frame = minute_session("2024-07-01", "QQQ")
        frame = pd.concat([frame, frame.iloc[[0]]], ignore_index=True)

        with self.assertRaisesRegex(ValueError, "duplicate timestamps"):
            compute_event_study(frame, [event()], horizons=("5min",))

    def test_unsorted_dataset_timestamp_rejected(self):
        frame = minute_session("2024-07-01", "QQQ")
        frame = frame.iloc[::-1].reset_index(drop=True)

        with self.assertRaisesRegex(ValueError, "sorted ascending"):
            compute_event_study(frame, [event()], horizons=("5min",))

    def test_duplicate_event_id_rejected(self):
        with self.assertRaisesRegex(ValueError, "duplicate event_id"):
            compute_event_study(
                minute_session("2024-07-01", "QQQ"),
                [event("DUP"), event("DUP")],
                horizons=("5min",),
            )

    def test_invalid_direction_rejected(self):
        with self.assertRaisesRegex(ValueError, "invalid expected_direction"):
            compute_event_study(
                minute_session("2024-07-01", "QQQ"),
                [event(expected_direction=2)],
                horizons=("5min",),
            )

    def test_event_outside_rth_rejected(self):
        frame = minute_session("2024-07-01", "QQQ")
        outside = pd.DataFrame(
            {
                "timestamp": [ts("2024-07-01", "08:00")],
                "open": [1.0],
                "high": [1.0],
                "low": [1.0],
                "close": [1.0],
                "volume": [1.0],
            }
        )
        frame = pd.concat([outside, frame], ignore_index=True).sort_values("timestamp").reset_index(drop=True)

        with self.assertRaisesRegex(ValueError, "outside Regular Trading Hours"):
            compute_event_study(
                frame,
                [
                    event(
                        timestamp=ts("2024-07-01", "08:00"),
                        session_date="2024-07-01",
                    )
                ],
                horizons=("5min",),
            )

    def test_session_date_mismatch_rejected(self):
        with self.assertRaisesRegex(ValueError, "does not match"):
            compute_event_study(
                minute_session("2024-07-01", "QQQ"),
                [event(session_date="2024-07-02")],
                horizons=("5min",),
            )

    def test_unsupported_horizon_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unsupported event-study horizon"):
            compute_event_study(
                minute_session("2024-07-01", "QQQ"),
                [event()],
                horizons=("10min",),
            )

    def test_aggregate_by_symbol_and_year(self):
        frame = frame_two_years()
        events = [
            event("E2024", timestamp=ts("2024-07-01", "10:00"), session_date="2024-07-01"),
            event("E2025", timestamp=ts("2025-07-01", "10:00"), session_date="2025-07-01"),
        ]
        results = compute_event_study(frame, events, horizons=("5min",))

        by_symbol = aggregate_event_results(results, group_by=("symbol", "horizon"))
        by_year = aggregate_event_results(results, group_by=("year", "horizon"))

        self.assertEqual(by_symbol.iloc[0]["symbol"], "QQQ")
        self.assertEqual(int(by_symbol.iloc[0]["event_count"]), 2)
        self.assertEqual(set(by_year["year"]), {2024, 2025})

    def test_aggregate_by_hypothesis_variant_direction_and_horizon(self):
        frame = minute_session("2024-07-01", "QQQ")
        results = compute_event_study(
            frame,
            [
                event(
                    "E1",
                    hypothesis_id="HYP-GAP-01",
                    variant_id="V01",
                    expected_direction=1,
                )
            ],
            horizons=("5min",),
        )

        summary = aggregate_event_results(
            results,
            group_by=(
                "hypothesis_id",
                "variant_id",
                "expected_direction",
                "horizon",
            ),
        ).iloc[0]

        self.assertEqual(summary["hypothesis_id"], "HYP-GAP-01")
        self.assertEqual(summary["variant_id"], "V01")
        self.assertEqual(int(summary["expected_direction"]), 1)
        self.assertEqual(summary["horizon"], "5min")

    def test_aggregate_statistics_and_confidence_interval(self):
        frame = minute_session("2024-07-01", "QQQ")
        results = compute_event_study(
            frame,
            [
                event("E1", timestamp=ts("2024-07-01", "10:00")),
                event("E2", timestamp=ts("2024-07-01", "10:01")),
            ],
            horizons=("5min",),
        )

        summary = aggregate_event_results(results).iloc[0]
        values = results["analysis_return"].astype(float)
        expected_mean = float(values.mean())
        expected_se = float(values.std(ddof=1) / (len(values) ** 0.5))

        self.assertAlmostEqual(summary["mean_return"], expected_mean)
        self.assertAlmostEqual(summary["median_return"], float(values.median()))
        self.assertAlmostEqual(summary["positive_rate"], 1.0)
        self.assertAlmostEqual(summary["standard_error"], expected_se)
        self.assertAlmostEqual(
            summary["confidence_interval_95_lower"],
            expected_mean - 1.96 * expected_se,
        )
        self.assertAlmostEqual(
            summary["confidence_interval_95_upper"],
            expected_mean + 1.96 * expected_se,
        )

    def test_serialization_reproducible_and_safety_flags_false(self):
        frame = minute_session("2024-07-01", "QQQ")
        results = compute_event_study(frame, [event()], horizons=("5min",))
        aggregates = aggregate_event_results(results)
        config = EventStudyRunConfig(
            run_id="RUN-GAP-01-EVENT-20260713-001",
            hypothesis_id="HYP-GAP-01",
            variant_id="V01",
            dataset_path="synthetic.csv",
            manifest_path="synthetic_manifest.json",
            dataset_sha256="synthetic-sha",
            requested_start="2024-07-01",
            requested_end="2024-07-01",
            horizons=("5min",),
            created_at="2026-07-13T00:00:00+00:00",
        )
        output = Path(tempfile.mkdtemp())

        paths = write_event_study_outputs(output, config, results, aggregates)
        payload = json.loads(paths["config"].read_text(encoding="utf-8"))
        stored_events = pd.read_csv(paths["events"])
        stored_aggregates = pd.read_csv(paths["aggregates"])

        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["event_count"], 1)
        self.assertFalse(payload["safety_flags"]["live_trading"])
        self.assertFalse(payload["safety_flags"]["broker_connected"])
        self.assertFalse(payload["safety_flags"]["orders_sent"])
        self.assertFalse(payload["safety_flags"]["paper_broker_enabled"])
        self.assertEqual(len(stored_events), 1)
        self.assertEqual(len(stored_aggregates), 1)

    def test_no_lookahead_from_bars_outside_horizon_or_before_event(self):
        frame = minute_session("2024-07-01", "QQQ")
        base = compute_event_study(frame, [event()], horizons=("5min",)).iloc[0]
        changed = frame.copy()
        changed.loc[changed["timestamp"] == ts("2024-07-01", "09:59"), "close"] = -999.0
        changed.loc[changed["timestamp"] == ts("2024-07-01", "10:10"), "close"] = 99999.0

        after = compute_event_study(changed, [event()], horizons=("5min",)).iloc[0]

        self.assertEqual(after["event_price"], base["event_price"])
        self.assertEqual(after["future_timestamp"], base["future_timestamp"])
        self.assertEqual(after["future_price"], base["future_price"])
        self.assertEqual(after["raw_return"], base["raw_return"])


if __name__ == "__main__":
    unittest.main()
