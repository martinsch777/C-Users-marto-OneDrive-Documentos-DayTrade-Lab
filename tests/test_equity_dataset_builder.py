import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from src.data import build_equity_dataset
from src.data.dataset_manifest import (
    APPROVED_FOR_OR_FVG_BACKTEST,
    NOT_AUDITED,
    require_approved_dataset_manifest,
)


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


def spy_missing_provider_bars() -> pd.DataFrame:
    frame = minute_frame("2023-06-05 09:30", "2023-06-05 15:59")
    missing = {
        "2023-06-05 09:52:00-04:00",
        "2023-06-05 09:53:00-04:00",
        "2023-06-05 09:54:00-04:00",
        "2023-06-05 09:55:00-04:00",
    }
    return frame.loc[~frame["timestamp"].isin(missing)].reset_index(drop=True)


def write_csv(frame: pd.DataFrame, directory: Path, name: str = "SPY_1min.csv") -> Path:
    path = directory / name
    frame.to_csv(path, index=False)
    return path


def write_override(directory: Path) -> Path:
    path = directory / "excluded_sessions.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "excluded_sessions": [
                    {
                        "symbol": "SPY",
                        "date": "2023-06-05",
                        "reason": "MISSING_RTH_BARS_FROM_PROVIDER",
                        "missing_timestamps": [
                            "2023-06-05 09:52:00-04:00",
                            "2023-06-05 09:53:00-04:00",
                            "2023-06-05 09:54:00-04:00",
                            "2023-06-05 09:55:00-04:00",
                        ],
                        "source": "alpaca_sip_raw_rth",
                        "policy": "exclude_entire_session",
                        "created_by": "data_quality_audit",
                    }
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


class EquityDatasetBuilderTests(unittest.TestCase):
    def test_build_removes_excluded_session_and_manifest_records_it(self):
        directory = Path(tempfile.mkdtemp())
        source = write_csv(spy_missing_provider_bars(), directory)
        overrides = write_override(directory)
        curated_dir = directory / "curated"
        manifest_dir = directory / "manifests"

        result = build_equity_dataset(
            csv_path=source,
            symbol="SPY",
            timeframe="1min",
            start="2023-06-05",
            end="2023-06-05",
            source_timezone="America/New_York",
            output_dir=curated_dir,
            excluded_sessions=overrides,
            manifest_dir=manifest_dir,
            range_filenames=True,
            rth_only=True,
        )

        curated = pd.read_csv(result.output_file)
        self.assertEqual(len(curated), 0)
        self.assertEqual(result.rows_input, 386)
        self.assertEqual(result.rows_removed, 386)
        self.assertEqual(result.total_excluded_sessions, 1)
        self.assertTrue(result.audit_apt_for_or_fvg_backtest)
        self.assertEqual(result.audit_critical_warnings, [])
        self.assertTrue(Path(result.manifest_file).exists())
        manifest = json.loads(Path(result.manifest_file).read_text(encoding="utf-8"))
        self.assertTrue(result.manifest_file.endswith("_curated_manifest.json"))
        self.assertEqual(manifest["dataset_status"], APPROVED_FOR_OR_FVG_BACKTEST)
        self.assertEqual(manifest["raw_input_file"], str(source))
        self.assertEqual(manifest["curated_file"], result.output_file)
        self.assertEqual(manifest["input_file"], result.output_file)
        self.assertEqual(manifest["output_file"], result.output_file)
        self.assertEqual(manifest["rows_input"], 386)
        self.assertEqual(manifest["rows_output"], 0)
        self.assertEqual(manifest["rows_removed"], 386)
        self.assertEqual(manifest["total_excluded_sessions"], 1)
        self.assertEqual(manifest["excluded_sessions"][0]["date"], "2023-06-05")
        self.assertFalse(manifest["project_safety_state"]["live_trading"])
        self.assertFalse(manifest["project_safety_state"]["live_trading_enabled"])
        self.assertFalse(manifest["project_safety_state"]["broker_connected"])
        self.assertFalse(manifest["project_safety_state"]["orders_sent"])
        self.assertFalse(manifest["project_safety_state"]["paper_broker_enabled"])
        self.assertIs(manifest["broker_connected"], False)
        self.assertIs(manifest["orders_sent"], False)
        self.assertIs(manifest["live_trading_enabled"], False)
        self.assertIs(manifest["paper_broker_enabled"], False)

    def test_build_does_not_fill_missing_bars_from_provider(self):
        directory = Path(tempfile.mkdtemp())
        source = write_csv(spy_missing_provider_bars(), directory)
        overrides = write_override(directory)

        result = build_equity_dataset(
            csv_path=source,
            symbol="SPY",
            start="2023-06-05",
            end="2023-06-05",
            output_dir=directory / "curated",
            excluded_sessions=overrides,
            manifest_dir=directory / "manifests",
            overwrite=True,
            rth_only=True,
        )

        curated = pd.read_csv(result.output_file)
        self.assertEqual(len(curated), 0)
        self.assertNotIn("2023-06-05 09:52:00-04:00", curated.to_string())
        self.assertEqual(result.rows_input - result.rows_output, 386)

    def test_build_anti_overwrite_returns_clean_cli_error(self):
        directory = Path(tempfile.mkdtemp())
        source = write_csv(spy_missing_provider_bars(), directory)
        overrides = write_override(directory)
        output = directory / "curated" / "SPY_1min_curated.csv"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("existing", encoding="utf-8")

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "src.cli",
                "build-equity-dataset",
                "--csv",
                str(source),
                "--symbol",
                "SPY",
                "--start",
                "2023-06-05",
                "--end",
                "2023-06-05",
                "--output-dir",
                str(output.parent),
                "--excluded-sessions",
                str(overrides),
            ],
            check=False,
            text=True,
            capture_output=True,
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn("OUTPUT_FILE_ALREADY_EXISTS", result.stdout)
        self.assertIn("Safety state", result.stdout)
        self.assertNotIn("Traceback", result.stderr)

    def test_build_range_filenames_cli(self):
        directory = Path(tempfile.mkdtemp())
        source = write_csv(spy_missing_provider_bars(), directory)
        overrides = write_override(directory)
        output_dir = directory / "curated"

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "src.cli",
                "build-equity-dataset",
                "--csv",
                str(source),
                "--symbol",
                "SPY",
                "--start",
                "2023-06-05",
                "--end",
                "2023-06-05",
                "--output-dir",
                str(output_dir),
                "--manifest-dir",
                str(directory / "manifests"),
                "--excluded-sessions",
                str(overrides),
                "--range-filenames",
                "--overwrite",
                "--rth-only",
            ],
            check=False,
            text=True,
            capture_output=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        expected = output_dir / "SPY_1min_2023-06-05_2023-06-05_curated.csv"
        self.assertTrue(expected.exists())
        payload = json.loads(result.stdout.split("Safety state")[0])
        self.assertEqual(payload["output_file"], str(expected))
        self.assertEqual(payload["total_excluded_sessions"], 1)

    def test_require_approved_dataset_manifest_checks_hash_status_and_identity(self):
        directory = Path(tempfile.mkdtemp())
        source = write_csv(minute_frame("2024-07-01 09:30", "2024-07-01 15:59"), directory)
        overrides = write_override(directory)
        result = build_equity_dataset(
            csv_path=source,
            symbol="SPY",
            start="2024-07-01",
            end="2024-07-01",
            output_dir=directory / "curated",
            excluded_sessions=overrides,
            manifest_dir=directory / "manifests",
            overwrite=True,
            rth_only=True,
        )

        manifest = require_approved_dataset_manifest(
            result.output_file,
            "SPY",
            "1min",
            manifest_dir=directory / "manifests",
        )

        self.assertEqual(manifest.dataset_status, APPROVED_FOR_OR_FVG_BACKTEST)
        self.assertEqual(manifest.symbol, "SPY")
        self.assertEqual(manifest.timeframe, "1min")
        self.assertIs(manifest.broker_connected, False)
        self.assertIs(manifest.orders_sent, False)
        self.assertIs(manifest.live_trading_enabled, False)
        self.assertIs(manifest.paper_broker_enabled, False)

    def test_require_approved_dataset_manifest_rejects_true_safety_fields(self):
        safety_fields = (
            "broker_connected",
            "orders_sent",
            "live_trading_enabled",
            "paper_broker_enabled",
        )
        for safety_field in safety_fields:
            with self.subTest(safety_field=safety_field):
                directory = Path(tempfile.mkdtemp())
                source = write_csv(
                    minute_frame("2024-07-01 09:30", "2024-07-01 15:59"),
                    directory,
                )
                overrides = write_override(directory)
                result = build_equity_dataset(
                    csv_path=source,
                    symbol="SPY",
                    start="2024-07-01",
                    end="2024-07-01",
                    output_dir=directory / "curated",
                    excluded_sessions=overrides,
                    manifest_dir=directory / "manifests",
                    overwrite=True,
                    rth_only=True,
                )
                manifest_path = Path(result.manifest_file)
                payload = json.loads(manifest_path.read_text(encoding="utf-8"))
                payload[safety_field] = True
                manifest_path.write_text(
                    json.dumps(payload, indent=2, sort_keys=True),
                    encoding="utf-8",
                )

                with self.assertRaisesRegex(ValueError, safety_field):
                    require_approved_dataset_manifest(
                        result.output_file,
                        "SPY",
                        "1min",
                        manifest_dir=directory / "manifests",
                    )

    def test_require_approved_dataset_manifest_keeps_legacy_raw_manifest_compatible(self):
        directory = Path(tempfile.mkdtemp())
        source = write_csv(
            minute_frame("2024-07-01 09:30", "2024-07-01 15:59"),
            directory,
        )
        overrides = write_override(directory)
        result = build_equity_dataset(
            csv_path=source,
            symbol="SPY",
            start="2024-07-01",
            end="2024-07-01",
            output_dir=directory / "curated",
            excluded_sessions=overrides,
            manifest_dir=directory / "manifests",
            overwrite=True,
            rth_only=True,
        )
        curated_manifest_path = Path(result.manifest_file)
        payload = json.loads(curated_manifest_path.read_text(encoding="utf-8"))
        for safety_field in (
            "broker_connected",
            "orders_sent",
            "live_trading_enabled",
            "paper_broker_enabled",
        ):
            payload.pop(safety_field)
        legacy_manifest_path = (
            curated_manifest_path.parent
            / "SPY_1min_2024-07-01_2024-07-01_alpaca_sip_raw_rth_manifest.json"
        )
        legacy_manifest_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        curated_manifest_path.unlink()

        manifest = require_approved_dataset_manifest(
            result.output_file,
            "SPY",
            "1min",
            manifest_dir=directory / "manifests",
        )

        self.assertEqual(manifest.dataset_status, APPROVED_FOR_OR_FVG_BACKTEST)
        self.assertIs(manifest.broker_connected, False)
        self.assertIs(manifest.orders_sent, False)
        self.assertIs(manifest.live_trading_enabled, False)
        self.assertIs(manifest.paper_broker_enabled, False)

    def test_require_approved_dataset_manifest_rejects_hash_mismatch(self):
        directory = Path(tempfile.mkdtemp())
        source = write_csv(minute_frame("2024-07-01 09:30", "2024-07-01 15:59"), directory)
        overrides = write_override(directory)
        result = build_equity_dataset(
            csv_path=source,
            symbol="SPY",
            start="2024-07-01",
            end="2024-07-01",
            output_dir=directory / "curated",
            excluded_sessions=overrides,
            manifest_dir=directory / "manifests",
            overwrite=True,
            rth_only=True,
        )
        Path(result.output_file).write_text("tampered\n", encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "sha256"):
            require_approved_dataset_manifest(
                result.output_file,
                "SPY",
                "1min",
                manifest_dir=directory / "manifests",
            )

    def test_skip_audit_writes_not_audited_manifest(self):
        directory = Path(tempfile.mkdtemp())
        source = write_csv(minute_frame("2024-07-01 09:30", "2024-07-01 15:59"), directory)
        overrides = write_override(directory)

        result = build_equity_dataset(
            csv_path=source,
            symbol="SPY",
            start="2024-07-01",
            end="2024-07-01",
            output_dir=directory / "curated",
            excluded_sessions=overrides,
            manifest_dir=directory / "manifests",
            overwrite=True,
            rth_only=True,
            skip_audit=True,
        )

        self.assertTrue(result.audit_skipped)
        self.assertEqual(result.dataset_status, NOT_AUDITED)
        manifest = json.loads(Path(result.manifest_file).read_text(encoding="utf-8"))
        self.assertEqual(manifest["dataset_status"], NOT_AUDITED)
        self.assertIsNone(manifest["audit_apt_for_or_fvg_backtest"])

    def test_skip_manifest_does_not_write_manifest(self):
        directory = Path(tempfile.mkdtemp())
        source = write_csv(minute_frame("2024-07-01 09:30", "2024-07-01 15:59"), directory)
        overrides = write_override(directory)
        manifest_dir = directory / "manifests"

        result = build_equity_dataset(
            csv_path=source,
            symbol="SPY",
            start="2024-07-01",
            end="2024-07-01",
            output_dir=directory / "curated",
            excluded_sessions=overrides,
            manifest_dir=manifest_dir,
            overwrite=True,
            rth_only=True,
            skip_manifest=True,
        )

        self.assertTrue(result.manifest_skipped)
        self.assertEqual(result.manifest_file, "")
        self.assertFalse(list(manifest_dir.glob("*.json")) if manifest_dir.exists() else False)

    def test_output_csv_and_manifest_stay_in_separate_directories(self):
        directory = Path(tempfile.mkdtemp())
        source = write_csv(minute_frame("2024-07-01 09:30", "2024-07-01 15:59"), directory)
        overrides = write_override(directory)
        output_dir = directory / "curated"
        manifest_dir = directory / "manifests"

        result = build_equity_dataset(
            csv_path=source,
            symbol="SPY",
            start="2024-07-01",
            end="2024-07-01",
            output_dir=output_dir,
            excluded_sessions=overrides,
            manifest_dir=manifest_dir,
            overwrite=True,
            rth_only=True,
        )

        self.assertEqual(Path(result.output_file).parent, output_dir)
        self.assertEqual(Path(result.manifest_file).parent, manifest_dir)
        self.assertEqual(Path(result.output_file).suffix, ".csv")
        self.assertFalse(list(manifest_dir.glob("*.csv")))

    def test_output_existing_without_overwrite_fails_before_reading(self):
        directory = Path(tempfile.mkdtemp())
        missing_source = directory / "missing.csv"
        output = directory / "curated" / "SPY_1min_curated.csv"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("existing", encoding="utf-8")

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "src.cli",
                "build-equity-dataset",
                "--csv",
                str(missing_source),
                "--symbol",
                "SPY",
                "--start",
                "2024-07-01",
                "--end",
                "2024-07-01",
                "--output-dir",
                str(output.parent),
                "--excluded-sessions",
                str(write_override(directory)),
            ],
            check=False,
            text=True,
            capture_output=True,
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn("OUTPUT_FILE_ALREADY_EXISTS", result.stdout)
        self.assertNotIn("CSV_NOT_FOUND", result.stdout)

    def test_verbose_cli_keeps_json_stdout_parseable_and_logs_stages_to_stderr(self):
        directory = Path(tempfile.mkdtemp())
        source = write_csv(minute_frame("2024-07-01 09:30", "2024-07-01 15:59"), directory)
        overrides = write_override(directory)

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "src.cli",
                "build-equity-dataset",
                "--csv",
                str(source),
                "--symbol",
                "SPY",
                "--start",
                "2024-07-01",
                "--end",
                "2024-07-01",
                "--output-dir",
                str(directory / "curated"),
                "--manifest-dir",
                str(directory / "manifests"),
                "--excluded-sessions",
                str(overrides),
                "--overwrite",
                "--verbose",
            ],
            check=False,
            text=True,
            capture_output=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout.split("Safety state")[0])
        self.assertEqual(payload["symbol"], "SPY")
        self.assertIn("START", result.stderr)
        self.assertIn("reading CSV", result.stderr)
        self.assertIn("DONE", result.stderr)

    def test_builder_layer_does_not_import_backtests_brokers_or_orders(self):
        source = Path("src/data/equity_dataset_builder.py").read_text(encoding="utf-8")
        sanitized = (
            source.lower()
            .replace('"broker_connected"', "")
            .replace('"orders_sent"', "")
            .replace('"live_trading_enabled"', "")
            .replace('"paper_broker_enabled"', "")
            .replace("broker_connected", "")
            .replace("paper_broker_enabled", "")
            .replace("orders_sent", "")
        )

        self.assertNotIn("src.backtesting", source)
        self.assertNotIn("BacktestEngine", source)
        self.assertNotIn("broker", sanitized)
        self.assertNotIn("orders", sanitized)
        self.assertNotIn("alpaca.trading", source)


if __name__ == "__main__":
    unittest.main()
