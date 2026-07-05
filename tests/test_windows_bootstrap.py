import tempfile
import unittest
from pathlib import Path

import pandas as pd

from src.config import load_config
from src.microstructure_collector import (
    BybitMicrostructureCollector,
    initialize_collector_outputs,
)
from src.microstructure_collector_cli import parser


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


class WindowsBootstrapTests(unittest.TestCase):
    def test_required_powershell_scripts_exist_and_apply_thread_limits(self):
        names = {
            "setup_or_find_venv.ps1",
            "run_bybit_microstructure_collector.ps1",
            "smoke_test_bybit_collector.ps1",
            "diagnose_local_environment.ps1",
        }
        thread_variables = {
            "OPENBLAS_NUM_THREADS",
            "OMP_NUM_THREADS",
            "MKL_NUM_THREADS",
            "NUMEXPR_NUM_THREADS",
        }
        for name in names:
            with self.subTest(script=name):
                text = (SCRIPTS / name).read_text(encoding="utf-8")
                self.assertTrue(
                    all(variable in text for variable in thread_variables)
                )
                self.assertNotIn("src\\strategies", text.lower())
                self.assertNotIn("set_leverage", text.lower())

    def test_setup_discovers_or_creates_a_windows_venv(self):
        text = (SCRIPTS / "setup_or_find_venv.ps1").read_text(
            encoding="utf-8"
        )
        for name in (".venv", "venv", "env", ".env"):
            self.assertIn(f'"{name}"', text)
        self.assertIn("Scripts\\python.exe", text)
        self.assertIn("Scripts\\Activate.ps1", text)
        self.assertIn('"-m", "venv"', text)
        self.assertIn("requirements.txt", text)
        self.assertIn("pyproject.toml", text)

    def test_runner_and_smoke_are_bounded_and_public_only(self):
        runner = (
            SCRIPTS / "run_bybit_microstructure_collector.ps1"
        ).read_text(encoding="utf-8")
        smoke = (SCRIPTS / "smoke_test_bybit_collector.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn("DurationMinutes", runner)
        self.assertIn("--duration-seconds", runner)
        self.assertIn("--confirm-public-data-only", runner)
        self.assertIn("diagnose_bybit_connection", smoke)
        self.assertIn("orders_sent", smoke)
        self.assertIn("broker_connected", smoke)
        self.assertIn("live_trading_enabled", smoke)

    def test_cli_accepts_limited_duration(self):
        args = parser().parse_args(
            [
                "run",
                "--duration-seconds",
                "300",
                "--confirm-public-data-only",
            ]
        )
        self.assertEqual(args.duration_seconds, 300)
        self.assertTrue(args.confirm_public_data_only)

    def test_collector_initialization_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "outputs"
            initialize_collector_outputs(output)
            initialize_collector_outputs(output)
            status = pd.read_csv(output / "collector_status.csv")
            self.assertEqual(len(status), 1)
            self.assertFalse(bool(status.iloc[0]["orders_sent"]))
            self.assertFalse(bool(status.iloc[0]["broker_connected"]))
            self.assertFalse(bool(status.iloc[0]["api_keys_used"]))

    def test_deduplication_survives_collector_restart(self):
        payload = {
            "topic": "orderbook.50.BTCUSDT",
            "type": "snapshot",
            "ts": 1735689600000,
            "data": {
                "s": "BTCUSDT",
                "u": 1,
                "seq": 991,
                "b": [["100", "2"]],
                "a": [["101", "2"]],
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            kwargs = {
                "data_root": root / "data",
                "output_root": root / "outputs",
                "log_root": root / "logs",
            }
            first = BybitMicrostructureCollector(("BTCUSDT",), **kwargs)
            self.assertEqual(
                first.process_payload(
                    payload, received_at_ms=1735689600010
                ),
                1,
            )
            restarted = BybitMicrostructureCollector(("BTCUSDT",), **kwargs)
            self.assertEqual(
                restarted.process_payload(
                    payload, received_at_ms=1735689600020
                ),
                0,
            )
            stored = pd.read_csv(root / "data" / "orderbook.csv")
            self.assertEqual(len(stored), 1)

    def test_all_trading_and_private_access_locks_remain_off(self):
        security = load_config(ROOT / "config.yaml").security
        for field in (
            "orders_sent",
            "broker_connected",
            "live_trading_enabled",
            "paper_internal_enabled",
            "paper_broker_enabled",
        ):
            self.assertFalse(security[field])


if __name__ == "__main__":
    unittest.main()
