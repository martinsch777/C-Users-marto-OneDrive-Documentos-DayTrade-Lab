import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from src.cli import build_parser, command_backtest
from src.data.dataset_manifest import (
    APPROVED_FOR_OR_FVG_BACKTEST,
    FAILED_AUDIT,
    require_or_fvg_backtest_dataset_manifest,
    sha256_file,
)


def write_csv(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "timestamp,open,high,low,close,volume\n"
        "2024-07-01 09:30:00-04:00,100,101,99,100.5,1000\n",
        encoding="utf-8",
    )
    return path


def write_manifest(
    manifest_dir: Path,
    csv_path: Path,
    *,
    symbol: str = "QQQ",
    dataset_status: str = APPROVED_FOR_OR_FVG_BACKTEST,
    audit_apt_for_or_fvg_backtest: bool = True,
    audit_critical_warnings: list[str] | None = None,
    sha256: str | None = None,
    curated_file: str | None = None,
    output_file: str | None = None,
    broker_connected: bool = False,
    orders_sent: bool = False,
    live_trading_enabled: bool = False,
    paper_broker_enabled: bool = False,
) -> Path:
    manifest_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "adjustment": "raw",
        "asset_class": "equity",
        "audit_apt_for_or_fvg_backtest": audit_apt_for_or_fvg_backtest,
        "audit_critical_warnings": audit_critical_warnings or [],
        "audit_warnings": [],
        "broker_connected": broker_connected,
        "calendar_early_closes_loaded": 1,
        "calendar_holidays_loaded": 1,
        "calendar_loaded": True,
        "calendar_source": "builtin_us_equity_calendar_v1",
        "created_at": "2026-07-10T00:00:00+00:00",
        "curated_file": str(csv_path) if curated_file is None else curated_file,
        "dataset_status": dataset_status,
        "end": "2024-07-01",
        "excluded_sessions": [],
        "feed": "sip",
        "first_timestamp": "2024-07-01 09:30:00-04:00",
        "input_file": str(csv_path),
        "last_timestamp": "2024-07-01 09:30:00-04:00",
        "live_trading_enabled": live_trading_enabled,
        "orders_sent": orders_sent,
        "output_file": str(csv_path) if output_file is None else output_file,
        "paper_broker_enabled": paper_broker_enabled,
        "project_safety_state": {
            "broker_connected": False,
            "live_trading": False,
            "live_trading_enabled": False,
            "orders_sent": False,
            "paper_broker_enabled": False,
        },
        "provider": "alpaca",
        "raw_input_file": "data/raw/source.csv",
        "rows": 1,
        "rows_input": 1,
        "rows_output": 1,
        "rows_removed": 0,
        "rth_only": True,
        "sha256": sha256 or sha256_file(csv_path),
        "source_timezone": "America/New_York",
        "start": "2024-07-01",
        "symbol": symbol,
        "timeframe": "1min",
        "total_excluded_sessions": 0,
    }
    path = manifest_dir / f"{symbol}_1min_2024-07-01_2024-07-01_curated_manifest.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path


class ORFVGBacktestGateTests(unittest.TestCase):
    def test_fails_when_manifest_is_missing(self):
        directory = Path(tempfile.mkdtemp())
        csv_path = write_csv(directory / "data" / "curated" / "QQQ_1min.csv")

        with self.assertRaisesRegex(FileNotFoundError, "No approved dataset manifest"):
            require_or_fvg_backtest_dataset_manifest(
                csv_path,
                "QQQ",
                "1min",
                manifest_dir=directory / "manifests",
            )

    def test_fails_when_manifest_is_not_approved(self):
        directory = Path(tempfile.mkdtemp())
        csv_path = write_csv(directory / "data" / "curated" / "QQQ_1min.csv")
        write_manifest(
            directory / "manifests",
            csv_path,
            dataset_status=FAILED_AUDIT,
            audit_apt_for_or_fvg_backtest=False,
        )

        with self.assertRaisesRegex(ValueError, "approved_for_or_fvg_backtest"):
            require_or_fvg_backtest_dataset_manifest(
                csv_path,
                "QQQ",
                "1min",
                manifest_dir=directory / "manifests",
            )

    def test_fails_when_csv_is_data_raw(self):
        directory = Path(tempfile.mkdtemp())
        csv_path = write_csv(directory / "data" / "raw" / "QQQ_1min.csv")
        write_manifest(directory / "manifests", csv_path)

        with self.assertRaisesRegex(ValueError, "data/raw"):
            require_or_fvg_backtest_dataset_manifest(
                csv_path,
                "QQQ",
                "1min",
                manifest_dir=directory / "manifests",
            )

    def test_fails_when_sha256_does_not_match(self):
        directory = Path(tempfile.mkdtemp())
        csv_path = write_csv(directory / "data" / "curated" / "QQQ_1min.csv")
        write_manifest(directory / "manifests", csv_path, sha256="bad_hash")

        with self.assertRaisesRegex(ValueError, "sha256"):
            require_or_fvg_backtest_dataset_manifest(
                csv_path,
                "QQQ",
                "1min",
                manifest_dir=directory / "manifests",
            )

    def test_fails_when_csv_is_not_manifest_curated_or_output_file(self):
        directory = Path(tempfile.mkdtemp())
        csv_path = write_csv(directory / "data" / "curated" / "QQQ_1min.csv")
        other_path = directory / "data" / "curated" / "other.csv"
        write_manifest(
            directory / "manifests",
            csv_path,
            curated_file=str(other_path),
            output_file=str(other_path),
        )

        with self.assertRaisesRegex(ValueError, "curated_file or output_file"):
            require_or_fvg_backtest_dataset_manifest(
                csv_path,
                "QQQ",
                "1min",
                manifest_dir=directory / "manifests",
            )

    def test_accepts_qqq_and_spy_curated_with_approved_manifests_and_false_safety(self):
        directory = Path(tempfile.mkdtemp())
        for symbol in ("QQQ", "SPY"):
            with self.subTest(symbol=symbol):
                csv_path = write_csv(
                    directory / "data" / "curated" / f"{symbol}_1min.csv"
                )
                write_manifest(directory / "manifests", csv_path, symbol=symbol)

                manifest = require_or_fvg_backtest_dataset_manifest(
                    csv_path,
                    symbol,
                    "1min",
                    manifest_dir=directory / "manifests",
                )

                self.assertEqual(manifest.dataset_status, APPROVED_FOR_OR_FVG_BACKTEST)
                self.assertTrue(manifest.audit_apt_for_or_fvg_backtest)
                self.assertEqual(manifest.audit_critical_warnings, [])
                self.assertFalse(manifest.broker_connected)
                self.assertFalse(manifest.orders_sent)
                self.assertFalse(manifest.live_trading_enabled)
                self.assertFalse(manifest.paper_broker_enabled)

    def test_fails_when_any_safety_state_is_true(self):
        safety_fields = (
            "broker_connected",
            "orders_sent",
            "live_trading_enabled",
            "paper_broker_enabled",
        )
        for field in safety_fields:
            with self.subTest(field=field):
                directory = Path(tempfile.mkdtemp())
                csv_path = write_csv(directory / "data" / "curated" / "QQQ_1min.csv")
                write_manifest(directory / "manifests", csv_path, **{field: True})

                with self.assertRaisesRegex(ValueError, field):
                    require_or_fvg_backtest_dataset_manifest(
                        csv_path,
                        "QQQ",
                        "1min",
                        manifest_dir=directory / "manifests",
                    )

    def test_cli_backtest_stops_before_loading_csv_when_or_fvg_gate_fails(self):
        directory = Path(tempfile.mkdtemp())
        csv_path = write_csv(directory / "data" / "curated" / "QQQ_1min.csv")
        args = build_parser().parse_args(
            [
                "backtest",
                "--csv",
                str(csv_path),
                "--symbol",
                "QQQ",
                "--timeframe",
                "1min",
                "--asset-class",
                "equity",
                "--manifest-dir",
                str(directory / "manifests"),
            ]
        )

        output = io.StringIO()
        with patch("src.cli.load_csv") as load_csv, redirect_stdout(output):
            exit_code = command_backtest(args)

        self.assertEqual(exit_code, 2)
        self.assertIn("OR_FVG_DATASET_GATE_FAILED", output.getvalue())
        load_csv.assert_not_called()


if __name__ == "__main__":
    unittest.main()
