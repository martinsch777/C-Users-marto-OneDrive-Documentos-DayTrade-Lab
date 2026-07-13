import warnings
import unittest

import pandas as pd

from src.timeframes import parse_timeframe_timedelta


class TimeframeParsingTests(unittest.TestCase):
    def test_parses_1min(self):
        self.assertEqual(parse_timeframe_timedelta("1min"), pd.Timedelta(minutes=1))

    def test_parses_all_supported_timeframes(self):
        expected = {
            "1min": pd.Timedelta(minutes=1),
            "5min": pd.Timedelta(minutes=5),
            "15min": pd.Timedelta(minutes=15),
            "30min": pd.Timedelta(minutes=30),
            "1h": pd.Timedelta(hours=1),
        }

        for timeframe, duration in expected.items():
            with self.subTest(timeframe=timeframe):
                self.assertEqual(parse_timeframe_timedelta(timeframe), duration)

    def test_rejects_invalid_timeframe(self):
        with self.assertRaisesRegex(ValueError, "Unsupported timeframe '2min'"):
            parse_timeframe_timedelta("2min")

    def test_parse_does_not_emit_deprecation_warning(self):
        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter("always")
            parse_timeframe_timedelta("1min")

        deprecation_warnings = [
            item for item in captured if issubclass(item.category, DeprecationWarning)
        ]
        self.assertEqual(deprecation_warnings, [])

    def test_valid_timeframes_preserve_bar_count_behavior(self):
        session = pd.Timedelta(hours=6, minutes=30)
        expected_bars = {
            "1min": 390,
            "5min": 78,
            "15min": 26,
            "30min": 13,
            "1h": 6,
        }

        for timeframe, bars in expected_bars.items():
            with self.subTest(timeframe=timeframe):
                self.assertEqual(int(session / parse_timeframe_timedelta(timeframe)), bars)


if __name__ == "__main__":
    unittest.main()
