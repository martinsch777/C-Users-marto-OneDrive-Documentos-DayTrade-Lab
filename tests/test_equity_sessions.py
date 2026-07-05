import unittest

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
