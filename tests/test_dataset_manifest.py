import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from src.data import audit_equity_intraday_csv
from src.data.alpaca_equity_downloader import DownloadResult
from src.data.dataset_manifest import (
    APPROVED_FOR_OR_FVG_BACKTEST,
    FAILED_AUDIT,
    build_dataset_manifest,
    sha256_file,
    write_dataset_manifest,
)


def write_csv(frame: pd.DataFrame) -> Path:
    path = Path(tempfile.mkdtemp()) / "QQQ_1min.csv"
    frame.to_csv(path, index=False)
    return path


def minute_frame(local_start: str, local_end: str) -> pd.DataFrame:
    timestamps = pd.date_range(
        local_start,
        local_end,
        freq="1min",
        tz="America/New_York",
    )
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


def result_for(path: Path, *, rows: int = 390) -> DownloadResult:
    return DownloadResult(
        symbol="QQQ",
        provider="alpaca",
        feed="sip",
        interval="1min",
        adjustment="raw",
        start="2024-07-01",
        end="2024-07-01",
        rows=rows,
        first_timestamp="2024-07-01 09:30:00-04:00",
        last_timestamp="2024-07-01 15:59:00-04:00",
        output_file=str(path),
        sha256=sha256_file(path),
        rth_only=True,
        pages_downloaded=1,
    )


class DatasetManifestTests(unittest.TestCase):
    def test_sha256_file_is_stable(self):
        path = Path(tempfile.mkdtemp()) / "sample.csv"
        path.write_text("timestamp,open\n2024-01-01,1\n", encoding="utf-8")

        expected = hashlib.sha256(path.read_bytes()).hexdigest()

        self.assertEqual(sha256_file(path), expected)
        self.assertEqual(sha256_file(path), sha256_file(path))

    def test_manifest_is_approved_when_audit_passes(self):
        path = write_csv(minute_frame("2024-07-01 09:30", "2024-07-01 15:59"))
        audit = audit_equity_intraday_csv(path, "QQQ", "1min")

        manifest = build_dataset_manifest(
            result_for(path),
            audit_report=audit,
            source_timezone="America/New_York",
            created_at="2026-07-07T00:00:00+00:00",
        )

        self.assertEqual(manifest.dataset_status, APPROVED_FOR_OR_FVG_BACKTEST)
        self.assertTrue(manifest.audit_apt_for_or_fvg_backtest)
        self.assertEqual(manifest.audit_critical_warnings, [])
        self.assertEqual(manifest.symbol, "QQQ")
        self.assertEqual(manifest.asset_class, "equity")
        self.assertEqual(manifest.provider, "alpaca")
        self.assertEqual(manifest.feed, "sip")
        self.assertEqual(manifest.adjustment, "raw")
        self.assertEqual(manifest.source_timezone, "America/New_York")
        self.assertTrue(manifest.rth_only)
        self.assertEqual(manifest.rows, 390)
        self.assertEqual(manifest.input_file, str(path))
        self.assertEqual(manifest.sha256, sha256_file(path))
        self.assertEqual(manifest.calendar_source, "builtin_us_equity_calendar_v1")
        self.assertTrue(manifest.calendar_loaded)
        self.assertGreater(manifest.calendar_holidays_loaded, 0)
        self.assertGreater(manifest.calendar_early_closes_loaded, 0)
        self.assertFalse(manifest.project_safety_state["live_trading"])
        self.assertFalse(manifest.project_safety_state["broker_connected"])
        self.assertFalse(manifest.project_safety_state["orders_sent"])

    def test_manifest_failed_audit_when_audit_fails(self):
        frame = minute_frame("2024-07-01 09:30", "2024-07-01 15:59")
        frame = frame.drop(index=[10]).reset_index(drop=True)
        path = write_csv(frame)
        audit = audit_equity_intraday_csv(path, "QQQ", "1min")

        manifest = build_dataset_manifest(
            result_for(path, rows=len(frame)),
            audit_report=audit,
            source_timezone="America/New_York",
        )

        self.assertEqual(manifest.dataset_status, FAILED_AUDIT)
        self.assertFalse(manifest.audit_apt_for_or_fvg_backtest)
        self.assertIn("MISSING_RTH_BARS", manifest.audit_critical_warnings)

    def test_write_dataset_manifest_uses_reproducible_filename(self):
        path = write_csv(minute_frame("2024-07-01 09:30", "2024-07-01 15:59"))
        audit = audit_equity_intraday_csv(path, "QQQ", "1min")
        manifest = build_dataset_manifest(
            result_for(path),
            audit_report=audit,
            source_timezone="America/New_York",
        )
        output_dir = Path(tempfile.mkdtemp())

        manifest_path = write_dataset_manifest(manifest, output_dir)

        self.assertEqual(
            manifest_path.name,
            "QQQ_1min_2024-07-01_2024-07-01_alpaca_sip_raw_rth_manifest.json",
        )
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["dataset_status"], APPROVED_FOR_OR_FVG_BACKTEST)
        self.assertEqual(payload["sha256"], sha256_file(path))

    def test_manifest_layer_does_not_import_backtests_brokers_or_orders(self):
        source = Path("src/data/dataset_manifest.py").read_text(encoding="utf-8")
        sanitized = (
            source.lower()
            .replace('"broker_connected"', "")
            .replace('"orders_sent"', "")
        )

        self.assertNotIn("src.backtesting", source)
        self.assertNotIn("BacktestEngine", source)
        self.assertNotIn("broker", sanitized)
        self.assertNotIn("orders", sanitized)
        self.assertNotIn("alpaca.trading", source)


if __name__ == "__main__":
    unittest.main()
