import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from src.data import (
    EquitySessionCalendar,
    audit_equity_intraday_csv,
    write_equity_intraday_audit_report,
)


def minute_frame(local_start: str, local_end: str, *, tz="America/New_York"):
    timestamps = pd.date_range(local_start, local_end, freq="1min", tz=tz)
    return pd.DataFrame(
        {
            "timestamp": timestamps.astype(str),
            "open": [100.0] * len(timestamps),
            "high": [101.0] * len(timestamps),
            "low": [99.0] * len(timestamps),
            "close": [100.5] * len(timestamps),
            "volume": [1000.0] * len(timestamps),
        }
    )


def audit_calendar():
    return EquitySessionCalendar.from_config()


class EquityDataAuditTests(unittest.TestCase):
    def write_csv(self, frame: pd.DataFrame) -> Path:
        directory = Path(tempfile.mkdtemp())
        path = directory / "fixture.csv"
        frame.to_csv(path, index=False)
        return path

    def test_complete_one_minute_rth_dataset_is_fit_for_or_fvg(self):
        path = self.write_csv(minute_frame("2025-07-02 09:30", "2025-07-02 15:59"))
        report = audit_equity_intraday_csv(
            path,
            "QQQ",
            "1min",
            source_timezone=None,
            calendar=audit_calendar(),
        )

        self.assertTrue(report.apt_for_or_fvg_backtest)
        self.assertEqual(report.rows_total, 390)
        self.assertEqual(report.sessions_complete, 1)
        self.assertEqual(report.missing_bars, 0)
        self.assertEqual(report.outside_rth_bars, 0)
        self.assertEqual(report.duplicate_timestamps, 0)
        self.assertTrue(report.calendar_loaded)
        self.assertEqual(report.calendar_source, "builtin_us_equity_calendar_v1")
        self.assertNotIn(
            "CALENDAR_HAS_NO_HOLIDAYS_OR_EARLY_CLOSES_LOADED",
            report.critical_warnings,
        )
        self.assertNotIn(
            "REAL_MARKET_CALENDAR_NOT_LOADED",
            report.critical_warnings,
        )
        self.assertFalse(report.broker_connected)
        self.assertFalse(report.orders_sent)
        self.assertFalse(report.live_trading_enabled)
        self.assertFalse(report.api_keys_used)

    def test_naive_timestamps_require_source_timezone(self):
        frame = minute_frame("2025-07-02 09:30", "2025-07-02 09:31")
        frame["timestamp"] = ["2025-07-02 09:30:00", "2025-07-02 09:31:00"]
        path = self.write_csv(frame)

        with self.assertRaisesRegex(ValueError, "source_timezone"):
            audit_equity_intraday_csv(path, "SPY", "1min", calendar=audit_calendar())

    def test_missing_duplicate_premarket_afterhours_and_bad_prices_are_flagged(self):
        frame = minute_frame("2025-07-02 09:30", "2025-07-02 15:59")
        frame = frame.drop(index=[10]).reset_index(drop=True)
        extra = minute_frame("2025-07-02 08:00", "2025-07-02 08:00")
        after = minute_frame("2025-07-02 16:00", "2025-07-02 16:00")
        duplicate = frame.iloc[[0]].copy()
        duplicate.loc[:, "volume"] = 0
        frame.loc[1, "low"] = 102.0
        frame.loc[2, "close"] = 0.0
        bad = pd.concat([extra, frame, duplicate, after], ignore_index=True)
        path = self.write_csv(bad)

        report = audit_equity_intraday_csv(
            path,
            "SPY",
            "1min",
            calendar=audit_calendar(),
        )

        self.assertFalse(report.apt_for_or_fvg_backtest)
        self.assertEqual(report.missing_bars, 1)
        self.assertEqual(report.duplicate_timestamps, 1)
        self.assertEqual(report.premarket_bars, 1)
        self.assertEqual(report.after_hours_bars, 1)
        self.assertEqual(report.invalid_ohlc_rows, 2)
        self.assertEqual(report.nonpositive_price_rows, 1)
        self.assertEqual(report.nonpositive_volume_rows, 1)
        self.assertIn("MISSING_RTH_BARS", report.critical_warnings)
        self.assertIn("PREMARKET_BARS_PRESENT", report.critical_warnings)
        self.assertIn("AFTER_HOURS_BARS_PRESENT", report.critical_warnings)

    def test_early_close_uses_calendar_expected_bar_count(self):
        path = self.write_csv(minute_frame("2025-07-03 09:30", "2025-07-03 12:59"))
        report = audit_equity_intraday_csv(
            path,
            "QQQ",
            "1min",
            calendar=audit_calendar(),
        )

        self.assertEqual(report.expected_bars, 210)
        self.assertEqual(report.observed_rth_bars, 210)
        self.assertEqual(report.sessions_complete, 1)
        self.assertTrue(report.session_details[0].early_close)
        self.assertTrue(report.apt_for_or_fvg_backtest)

    def test_holiday_rows_are_rejected(self):
        path = self.write_csv(minute_frame("2025-07-04 09:30", "2025-07-04 09:31"))
        report = audit_equity_intraday_csv(
            path,
            "QQQ",
            "1min",
            calendar=audit_calendar(),
        )

        self.assertFalse(report.apt_for_or_fvg_backtest)
        self.assertEqual(report.holiday_or_closed_session_bars, 2)
        self.assertIn("HOLIDAY_OR_CLOSED_SESSION_BARS", report.critical_warnings)

    def test_naive_timestamps_with_source_timezone_are_localized(self):
        frame = minute_frame("2025-07-02 09:30", "2025-07-02 15:59")
        frame["timestamp"] = pd.date_range(
            "2025-07-02 09:30",
            "2025-07-02 15:59",
            freq="1min",
        ).astype(str)
        path = self.write_csv(frame)

        report = audit_equity_intraday_csv(
            path,
            "SPY",
            "1min",
            source_timezone="America/New_York",
            calendar=audit_calendar(),
        )

        self.assertTrue(report.apt_for_or_fvg_backtest)
        self.assertEqual(report.timestamp_timezone_status, "localized_from_source_timezone")
        self.assertEqual(report.first_timestamp_utc, "2025-07-02T13:30:00+00:00")

    def test_dataset_crossing_dst_uses_new_york_rth_not_fixed_utc_offset(self):
        before_dst = minute_frame("2026-03-06 09:30", "2026-03-06 15:59")
        after_dst = minute_frame("2026-03-09 09:30", "2026-03-09 15:59")
        path = self.write_csv(pd.concat([before_dst, after_dst], ignore_index=True))

        report = audit_equity_intraday_csv(
            path,
            "QQQ",
            "1min",
            calendar=audit_calendar(),
        )

        self.assertTrue(report.apt_for_or_fvg_backtest)
        self.assertEqual(report.sessions, 2)
        self.assertEqual(report.expected_bars, 780)
        self.assertEqual(report.missing_bars, 0)
        self.assertEqual(report.anomalous_time_gaps, 0)
        self.assertEqual(report.first_timestamp_utc, "2026-03-06T14:30:00+00:00")
        self.assertIn("2026-03-09T19:59:00+00:00", report.last_timestamp_utc)

    def test_manual_empty_calendar_fails_clearly(self):
        path = self.write_csv(minute_frame("2025-07-02 09:30", "2025-07-02 15:59"))
        report = audit_equity_intraday_csv(
            path,
            "QQQ",
            "1min",
            calendar=EquitySessionCalendar.from_config({"source": "manual"}),
        )

        self.assertFalse(report.apt_for_or_fvg_backtest)
        self.assertIn("REAL_MARKET_CALENDAR_NOT_LOADED", report.critical_warnings)

    def test_writes_json_csv_markdown_reports_without_sensitive_state(self):
        path = self.write_csv(minute_frame("2025-07-02 09:30", "2025-07-02 15:59"))
        report = audit_equity_intraday_csv(
            path,
            "QQQ",
            "1min",
            calendar=audit_calendar(),
        )
        output = Path(tempfile.mkdtemp())

        paths = write_equity_intraday_audit_report(report, output)

        self.assertTrue(paths["json"].exists())
        self.assertTrue(paths["csv"].exists())
        self.assertTrue(paths["sessions_csv"].exists())
        self.assertTrue(paths["markdown"].exists())
        data = json.loads(paths["json"].read_text(encoding="utf-8"))
        self.assertFalse(data["broker_connected"])
        self.assertFalse(data["orders_sent"])
        self.assertFalse(data["live_trading_enabled"])
        self.assertFalse(data["api_keys_used"])
        self.assertNotIn("api_key", paths["markdown"].read_text(encoding="utf-8").lower())

    def test_cli_audit_data_writes_reports_without_backtest(self):
        path = self.write_csv(minute_frame("2025-07-02 09:30", "2025-07-02 15:59"))
        output = Path(tempfile.mkdtemp())

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "src.cli",
                "audit-data",
                "--csv",
                str(path),
                "--symbol",
                "QQQ",
                "--timeframe",
                "1min",
                "--asset-class",
                "equity",
                "--output-dir",
                str(output),
            ],
            check=False,
            text=True,
            capture_output=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Dataset QQQ 1min", result.stdout)
        self.assertIn("Safety state", result.stdout)
        self.assertTrue((output / "QQQ_1min_data_audit.json").exists())
        payload = json.loads(
            (output / "QQQ_1min_data_audit.json").read_text(encoding="utf-8")
        )
        self.assertTrue(payload["calendar_loaded"])
        self.assertNotIn(
            "CALENDAR_HAS_NO_HOLIDAYS_OR_EARLY_CLOSES_LOADED",
            payload["critical_warnings"],
        )

    def test_cli_audit_data_missing_csv_fails_cleanly_without_traceback(self):
        directory = Path(tempfile.mkdtemp())
        missing = directory / "QQQ_1min_missing.csv"
        output = directory / "audit"

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "src.cli",
                "audit-data",
                "--csv",
                str(missing),
                "--symbol",
                "QQQ",
                "--timeframe",
                "1min",
                "--asset-class",
                "equity",
                "--source-timezone",
                "America/New_York",
                "--output-dir",
                str(output),
            ],
            check=False,
            text=True,
            capture_output=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Dataset QQQ 1min: NO APTO", result.stdout)
        self.assertIn("CSV_NOT_FOUND", result.stdout)
        self.assertIn(str(missing), result.stdout)
        self.assertIn("Safety state", result.stdout)
        self.assertNotIn("Traceback", result.stdout)
        self.assertNotIn("Traceback", result.stderr)
        payload = json.loads(
            (output / "QQQ_1min_data_audit.json").read_text(encoding="utf-8")
        )
        self.assertFalse(payload["apt_for_or_fvg_backtest"])
        self.assertEqual(payload["critical_warnings"], ["CSV_NOT_FOUND"])
        self.assertEqual(payload["rows_total"], 0)
        self.assertFalse(payload["broker_connected"])
        self.assertFalse(payload["orders_sent"])
        self.assertFalse(payload["live_trading_enabled"])


if __name__ == "__main__":
    unittest.main()
