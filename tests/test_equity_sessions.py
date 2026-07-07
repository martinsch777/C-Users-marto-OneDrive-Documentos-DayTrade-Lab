import unittest
import json
import subprocess
import sys

import pandas as pd

from src.data import EquitySessionCalendar
from src.execution_simulator import ExecutionRequest, ExecutionSimulator


class EquitySessionTests(unittest.TestCase):
    @staticmethod
    def execution_config():
        return {
            "spread_bps": 0,
            "slippage_bps": 0,
            "commission_bps": 0,
            "max_volume_participation": 1,
            "same_bar_policy": "stop_first",
            "force_flat_before_session_end": True,
            "session_timezone": "America/New_York",
            "session_end": "16:00",
            "session_exit_buffer_minutes": 1,
        }

    @staticmethod
    def execution_frame(local_times):
        local = pd.DatetimeIndex(local_times).tz_localize("America/New_York")
        return pd.DataFrame(
            {
                "timestamp": local.tz_convert("UTC"),
                "open": [100.0] * len(local),
                "high": [100.5] * len(local),
                "low": [99.5] * len(local),
                "close": [100.0] * len(local),
                "volume": [10000.0] * len(local),
            }
        )

    def test_new_york_rth_handles_dst_and_excludes_extended_hours(self):
        calendar = EquitySessionCalendar()
        self.assertTrue(calendar.contains(pd.Timestamp("2025-01-02 14:30", tz="UTC")))
        self.assertTrue(calendar.contains(pd.Timestamp("2025-07-02 13:30", tz="UTC")))
        self.assertFalse(calendar.contains(pd.Timestamp("2025-07-02 13:29", tz="UTC")))
        self.assertFalse(calendar.contains(pd.Timestamp("2025-07-02 20:00", tz="UTC")))

    def test_holidays_and_early_closes_are_configurable(self):
        calendar = EquitySessionCalendar.from_config(
            {
                "holidays": ["2025-07-04"],
                "early_closes": {"2025-07-03": "13:00"},
            }
        )
        self.assertFalse(
            calendar.contains(pd.Timestamp("2025-07-04 14:30", tz="UTC"))
        )
        self.assertTrue(
            calendar.contains(pd.Timestamp("2025-07-03 16:59", tz="UTC"))
        )
        self.assertFalse(
            calendar.contains(pd.Timestamp("2025-07-03 17:00", tz="UTC"))
        )

    def test_builtin_us_equity_calendar_has_real_holidays_and_early_closes(self):
        calendar = EquitySessionCalendar.from_config()

        self.assertTrue(calendar.loaded)
        self.assertEqual(calendar.source, "builtin_us_equity_calendar_v1")
        self.assertFalse(
            calendar.contains(pd.Timestamp("2025-07-04 13:30", tz="UTC"))
        )
        self.assertTrue(
            calendar.contains(pd.Timestamp("2025-07-03 16:59", tz="UTC"))
        )
        self.assertFalse(
            calendar.contains(pd.Timestamp("2025-07-03 17:00", tz="UTC"))
        )

    def test_builtin_expected_timestamps_handle_dst_shift(self):
        calendar = EquitySessionCalendar.from_config()
        expected = calendar.expected_timestamps(
            pd.Timestamp("2026-03-06").date(),
            pd.Timestamp("2026-03-09").date(),
            "1min",
        )

        self.assertEqual(len(expected), 780)
        self.assertEqual(expected[0], pd.Timestamp("2026-03-06 14:30", tz="UTC"))
        self.assertEqual(expected[389], pd.Timestamp("2026-03-06 20:59", tz="UTC"))
        self.assertEqual(expected[390], pd.Timestamp("2026-03-09 13:30", tz="UTC"))
        self.assertEqual(expected[-1], pd.Timestamp("2026-03-09 19:59", tz="UTC"))

    def test_builtin_holiday_has_no_expected_bars(self):
        calendar = EquitySessionCalendar.from_config()
        expected = calendar.expected_timestamps(
            pd.Timestamp("2025-07-04").date(),
            pd.Timestamp("2025-07-04").date(),
            "1min",
        )

        self.assertEqual(len(expected), 0)

    def test_builtin_calendar_explicit_normal_sessions_2024(self):
        calendar = EquitySessionCalendar.from_config()
        cases = [
            ("2024-07-01", "2024-07-01 13:30", "2024-07-01 19:59"),
            ("2024-03-11", "2024-03-11 13:30", "2024-03-11 19:59"),
            ("2024-11-04", "2024-11-04 14:30", "2024-11-04 20:59"),
        ]

        for day, first_utc, last_utc in cases:
            with self.subTest(day=day):
                expected = calendar.expected_timestamps(
                    pd.Timestamp(day).date(),
                    pd.Timestamp(day).date(),
                    "1min",
                )
                diagnostic = calendar.diagnostics(
                    pd.Timestamp(day).date(),
                    pd.Timestamp(day).date(),
                )[0]

                self.assertEqual(len(expected), 390)
                self.assertEqual(expected[0], pd.Timestamp(first_utc, tz="UTC"))
                self.assertEqual(expected[-1], pd.Timestamp(last_utc, tz="UTC"))
                self.assertTrue(diagnostic["is_session"])
                self.assertFalse(diagnostic["is_early_close"])
                self.assertEqual(diagnostic["open"], "09:30")
                self.assertEqual(diagnostic["close"], "16:00")
                self.assertEqual(diagnostic["expected_1min_bars"], 390)
                self.assertEqual(diagnostic["reason"], "Regular session")

    def test_builtin_calendar_explicit_early_closes_2024(self):
        calendar = EquitySessionCalendar.from_config()
        first_utc_by_day = {
            "2024-07-03": "2024-07-03 13:30",
            "2024-11-29": "2024-11-29 14:30",
            "2024-12-24": "2024-12-24 14:30",
        }
        for day, first_utc in first_utc_by_day.items():
            with self.subTest(day=day):
                expected = calendar.expected_timestamps(
                    pd.Timestamp(day).date(),
                    pd.Timestamp(day).date(),
                    "1min",
                )
                diagnostic = calendar.diagnostics(
                    pd.Timestamp(day).date(),
                    pd.Timestamp(day).date(),
                )[0]

                self.assertEqual(len(expected), 210)
                self.assertEqual(
                    expected[0],
                    pd.Timestamp(first_utc, tz="UTC"),
                )
                self.assertTrue(diagnostic["is_session"])
                self.assertTrue(diagnostic["is_early_close"])
                self.assertEqual(diagnostic["open"], "09:30")
                self.assertEqual(diagnostic["close"], "13:00")
                self.assertEqual(diagnostic["expected_1min_bars"], 210)
                self.assertEqual(diagnostic["reason"], "Early close")

    def test_builtin_calendar_explicit_holidays_and_special_closure(self):
        calendar = EquitySessionCalendar.from_config()
        cases = {
            "2024-07-04": "Independence Day observed",
            "2024-12-25": "Christmas observed",
            "2025-01-01": "New Year observed",
            "2025-01-09": "National Day of Mourning for Jimmy Carter",
            "2025-06-19": "Juneteenth observed",
        }

        for day, reason in cases.items():
            with self.subTest(day=day):
                expected = calendar.expected_timestamps(
                    pd.Timestamp(day).date(),
                    pd.Timestamp(day).date(),
                    "1min",
                )
                diagnostic = calendar.diagnostics(
                    pd.Timestamp(day).date(),
                    pd.Timestamp(day).date(),
                )[0]

                self.assertEqual(len(expected), 0)
                self.assertFalse(diagnostic["is_session"])
                self.assertFalse(diagnostic["is_early_close"])
                self.assertEqual(diagnostic["open"], "")
                self.assertEqual(diagnostic["close"], "")
                self.assertEqual(diagnostic["expected_1min_bars"], 0)
                self.assertEqual(diagnostic["reason"], reason)

    def test_calendar_diagnostics_cli_prints_range_without_trading_surface(self):
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "src.cli",
                "calendar-diagnostics",
                "--calendar",
                "us_equity",
                "--start",
                "2024-07-01",
                "--end",
                "2024-07-05",
                "--format",
                "json",
            ],
            check=False,
            text=True,
            capture_output=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload_text = result.stdout.split("Safety state:")[0].strip()
        rows = json.loads(payload_text)
        by_date = {row["date"]: row for row in rows}
        self.assertEqual(by_date["2024-07-01"]["expected_1min_bars"], 390)
        self.assertEqual(by_date["2024-07-03"]["expected_1min_bars"], 210)
        self.assertFalse(by_date["2024-07-04"]["is_session"])
        self.assertEqual(
            by_date["2024-07-04"]["reason"],
            "Independence Day observed",
        )
        self.assertIn(
            "live trading=False, broker connected=False, orders sent=False",
            result.stdout,
        )

    def test_position_is_forced_flat_before_regular_close(self):
        local = pd.DatetimeIndex(
            [
                "2025-01-02 15:57",
                "2025-01-02 15:58",
                "2025-01-02 15:59",
                "2025-01-03 09:30",
            ]
        ).tz_localize("America/New_York")
        frame = pd.DataFrame(
            {
                "timestamp": local.tz_convert("UTC"),
                "open": [100.0, 100.0, 100.2, 105.0],
                "high": [100.5, 100.5, 100.6, 106.0],
                "low": [99.5, 99.5, 99.8, 104.0],
                "close": [100.0, 100.2, 100.4, 105.5],
                "volume": [10000.0] * 4,
            }
        )
        result = ExecutionSimulator(
            {
                "spread_bps": 0,
                "slippage_bps": 0,
                "commission_bps": 0,
                "max_volume_participation": 1,
                "same_bar_policy": "stop_first",
                "force_flat_before_session_end": True,
                "session_timezone": "America/New_York",
                "session_end": "16:00",
                "session_exit_buffer_minutes": 1,
            }
        ).simulate(
            frame,
            ExecutionRequest(
                signal_timestamp=frame.iloc[0]["timestamp"],
                side="long",
                quantity=10,
                stop_loss=90,
                take_profit=110,
            ),
        )
        self.assertEqual(result.exit_reason, "FORCED_SESSION_CLOSE")
        self.assertEqual(result.exit_timestamp, frame.iloc[1]["timestamp"])
        local_exit = result.exit_timestamp.tz_convert("America/New_York")
        self.assertLess(local_exit.time(), pd.Timestamp("16:00").time())
        self.assertEqual(local_exit.date(), local[0].date())

    def test_next_day_row_cancels_entry(self):
        frame = self.execution_frame(
            ["2025-01-02 15:30", "2025-01-03 09:30", "2025-01-03 15:58"]
        )
        result = ExecutionSimulator(self.execution_config()).simulate(
            frame,
            ExecutionRequest(
                signal_timestamp=frame.iloc[0]["timestamp"],
                side="long",
                quantity=10,
                stop_loss=90,
                take_profit=110,
            ),
        )
        self.assertEqual(result.status, "CANCELLED")
        self.assertEqual(
            result.exit_reason,
            "CANCELLED_NEXT_BAR_NOT_SAME_SESSION",
        )
        self.assertIsNone(result.entry_timestamp)

    def test_next_row_outside_rth_cancels_entry(self):
        frame = self.execution_frame(
            ["2025-01-02 15:59", "2025-01-02 16:00"]
        )
        result = ExecutionSimulator(self.execution_config()).simulate(
            frame,
            ExecutionRequest(
                signal_timestamp=frame.iloc[0]["timestamp"],
                side="long",
                quantity=10,
                stop_loss=90,
                take_profit=110,
            ),
        )
        self.assertEqual(result.status, "CANCELLED")
        self.assertEqual(
            result.exit_reason,
            "CANCELLED_NEXT_BAR_NOT_SAME_SESSION",
        )

    def test_valid_next_bar_in_same_rth_session_can_fill(self):
        frame = self.execution_frame(
            ["2025-01-02 10:00", "2025-01-02 10:01", "2025-01-02 15:58"]
        )
        result = ExecutionSimulator(self.execution_config()).simulate(
            frame,
            ExecutionRequest(
                signal_timestamp=frame.iloc[0]["timestamp"],
                side="long",
                quantity=10,
                stop_loss=90,
                take_profit=110,
            ),
        )
        self.assertEqual(result.status, "FILLED")
        self.assertEqual(result.entry_timestamp, frame.iloc[1]["timestamp"])


if __name__ == "__main__":
    unittest.main()
