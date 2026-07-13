import unittest

import pandas as pd

from src.data import EquitySessionCalendar, normalize_ohlcv, validate_ohlcv


def raw_frame(timestamps):
    return pd.DataFrame(
        {
            "datetime": timestamps,
            "Open": [100.0] * len(timestamps),
            "High": [101.0] * len(timestamps),
            "Low": [99.0] * len(timestamps),
            "Close": [100.5] * len(timestamps),
            "Volume": [1000.0] * len(timestamps),
        }
    )


def rth_session_frame(date: str, *, missing: set[str] | None = None) -> pd.DataFrame:
    missing = missing or set()
    timestamps = pd.date_range(
        f"{date} 09:30",
        f"{date} 15:30",
        freq="30min",
        tz="America/New_York",
    )
    kept = [stamp for stamp in timestamps if stamp.strftime("%H:%M") not in missing]
    return pd.DataFrame(
        {
            "timestamp": pd.DatetimeIndex(kept).tz_convert("UTC"),
            "open": [100.0] * len(kept),
            "high": [101.0] * len(kept),
            "low": [99.0] * len(kept),
            "close": [100.5] * len(kept),
            "volume": [1000.0] * len(kept),
        }
    )


def concat_sessions(*frames: pd.DataFrame) -> pd.DataFrame:
    return pd.concat(frames, ignore_index=True)


class DataTests(unittest.TestCase):
    def test_rejects_naive_timestamp_without_source_timezone(self):
        with self.assertRaisesRegex(ValueError, "source_timezone"):
            normalize_ohlcv(
                raw_frame(["2025-07-02 09:30:00"]),
                "1min",
                drop_incomplete=False,
            )

    def test_localizes_naive_timestamp_from_explicit_source_timezone(self):
        normalized, _ = normalize_ohlcv(
            raw_frame(["2025-07-02 09:30:00"]),
            "1min",
            drop_incomplete=False,
            source_timezone="America/New_York",
        )
        self.assertEqual(
            normalized.iloc[0]["timestamp"],
            pd.Timestamp("2025-07-02 13:30:00+00:00"),
        )

    def test_normalizes_timezone_aware_timestamp_to_utc(self):
        normalized, _ = normalize_ohlcv(
            raw_frame(["2025-07-02 09:30:00-04:00"]),
            "1min",
            drop_incomplete=False,
        )
        self.assertEqual(
            normalized.iloc[0]["timestamp"],
            pd.Timestamp("2025-07-02 13:30:00+00:00"),
        )

    def test_normalizes_schema_timezone_sorting_and_duplicates(self):
        frame = raw_frame(
            [
                "2024-01-02 14:45:00+00:00",
                "2024-01-02 14:30:00+00:00",
                "2024-01-02 14:30:00+00:00",
            ]
        )
        normalized, dropped = normalize_ohlcv(
            frame,
            "15min",
            drop_incomplete=False,
        )
        self.assertFalse(dropped)
        self.assertEqual(len(normalized), 2)
        self.assertEqual(
            list(normalized.columns),
            ["timestamp", "open", "high", "low", "close", "volume"],
        )
        self.assertEqual(str(normalized["timestamp"].dt.tz), "UTC")
        self.assertTrue(normalized["timestamp"].is_monotonic_increasing)

    def test_detects_missing_expected_equity_bar(self):
        frame, _ = normalize_ohlcv(
            raw_frame(
                [
                    "2024-01-02 14:30:00+00:00",
                    "2024-01-02 15:00:00+00:00",
                ]
            ),
            "15min",
            drop_incomplete=False,
        )
        report = validate_ohlcv(frame, "15min", asset_class="equity")
        self.assertEqual(
            report.missing_bars,
            [pd.Timestamp("2024-01-02 14:45:00+00:00")],
        )
        self.assertFalse(report.is_valid)

    def test_drops_incomplete_last_candle(self):
        frame, dropped = normalize_ohlcv(
            raw_frame(
                [
                    "2024-01-02 14:30:00+00:00",
                    "2024-01-02 14:45:00+00:00",
                ]
            ),
            "15min",
            drop_incomplete=True,
            reference_time=pd.Timestamp("2024-01-02 14:50:00+00:00"),
        )
        self.assertTrue(dropped)
        self.assertEqual(len(frame), 1)

    def test_holiday_does_not_create_missing_equity_bars(self):
        frame, _ = normalize_ohlcv(
            raw_frame(
                [
                    "2025-07-03 19:30:00+00:00",
                    "2025-07-07 13:30:00+00:00",
                ]
            ),
            "30min",
            drop_incomplete=False,
        )
        calendar = EquitySessionCalendar.from_config(
            {"holidays": ["2025-07-04"]}
        )
        report = validate_ohlcv(
            frame,
            "30min",
            asset_class="equity",
            calendar=calendar,
        )
        self.assertEqual(report.missing_bars, [])

    def test_early_close_does_not_require_afternoon_bars(self):
        frame, _ = normalize_ohlcv(
            raw_frame(
                [
                    "2025-07-03 16:30:00+00:00",
                    "2025-07-04 13:30:00+00:00",
                ]
            ),
            "30min",
            drop_incomplete=False,
        )
        calendar = EquitySessionCalendar.from_config(
            {"early_closes": {"2025-07-03": "13:00"}}
        )
        report = validate_ohlcv(
            frame,
            "30min",
            asset_class="equity",
            calendar=calendar,
        )
        self.assertEqual(report.missing_bars, [])

    def test_duplicate_detection_remains_active_with_calendar(self):
        timestamp = pd.Timestamp("2025-07-02 13:30:00+00:00")
        frame = pd.DataFrame(
            {
                "timestamp": [timestamp, timestamp],
                "open": [100.0, 100.0],
                "high": [101.0, 101.0],
                "low": [99.0, 99.0],
                "close": [100.5, 100.5],
                "volume": [1000.0, 1000.0],
            }
        )
        report = validate_ohlcv(
            frame,
            "1min",
            asset_class="equity",
            calendar=EquitySessionCalendar(),
        )
        self.assertEqual(report.duplicate_timestamps, 1)
        self.assertFalse(report.is_valid)

    def test_approved_excluded_session_does_not_create_missing_bars(self):
        frame = concat_sessions(
            rth_session_frame("2023-06-02"),
            rth_session_frame("2023-06-06"),
        )

        report = validate_ohlcv(
            frame,
            "30min",
            asset_class="equity",
            calendar=EquitySessionCalendar(),
            excluded_session_dates={"2023-06-05"},
        )

        self.assertEqual(report.missing_bars, [])
        self.assertTrue(report.is_valid)

    def test_missing_bars_inside_approved_excluded_session_do_not_block(self):
        frame = rth_session_frame("2023-06-05", missing={"10:30"})

        report = validate_ohlcv(
            frame,
            "30min",
            asset_class="equity",
            calendar=EquitySessionCalendar(),
            excluded_session_dates={"2023-06-05"},
        )

        self.assertEqual(report.missing_bars, [])
        self.assertTrue(report.is_valid)

    def test_missing_bars_outside_excluded_sessions_still_block(self):
        frame = concat_sessions(
            rth_session_frame("2023-06-02"),
            rth_session_frame("2023-06-06"),
        )

        report = validate_ohlcv(
            frame,
            "30min",
            asset_class="equity",
            calendar=EquitySessionCalendar(),
            excluded_session_dates={"2023-06-01"},
        )

        self.assertIn(
            pd.Timestamp("2023-06-05 13:30:00+00:00"),
            report.missing_bars,
        )
        self.assertFalse(report.is_valid)

    def test_partial_missing_unapproved_session_still_blocks(self):
        frame = concat_sessions(
            rth_session_frame("2023-06-05"),
            rth_session_frame("2023-06-06", missing={"10:30"}),
        )

        report = validate_ohlcv(
            frame,
            "30min",
            asset_class="equity",
            calendar=EquitySessionCalendar(),
            excluded_session_dates={"2023-06-05"},
        )

        self.assertEqual(
            report.missing_bars,
            [pd.Timestamp("2023-06-06 14:30:00+00:00")],
        )
        self.assertFalse(report.is_valid)

    def test_without_excluded_sessions_missing_bars_remain_required(self):
        frame = concat_sessions(
            rth_session_frame("2023-06-02"),
            rth_session_frame("2023-06-06"),
        )

        report = validate_ohlcv(
            frame,
            "30min",
            asset_class="equity",
            calendar=EquitySessionCalendar(),
        )

        self.assertGreater(len(report.missing_bars), 0)
        self.assertFalse(report.is_valid)


if __name__ == "__main__":
    unittest.main()
