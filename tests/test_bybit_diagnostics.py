import inspect
import json
import socket
import ssl
import tempfile
import unittest
from pathlib import Path
from urllib.error import URLError

import pandas as pd

from src.bybit_diagnostics import (
    ERROR_CODES,
    BybitRestFallback,
    DiagnosticResult,
    classify_exception,
    sanitize_message,
    write_diagnostic_report,
)
from src.config import load_config
from src.microstructure_collector import BybitMicrostructureCollector


ROOT = Path(__file__).resolve().parents[1]


class BybitDiagnosticTests(unittest.TestCase):
    def test_error_classification_distinguishes_network_layers(self):
        cases = [
            (socket.gaierror(11001, "name failed"), "dns", "DNS_FAILED"),
            (PermissionError(10013, "socket denied"), "tcp", "TCP_443_BLOCKED"),
            (ssl.SSLError("handshake failed"), "tls", "TLS_HANDSHAKE_FAILED"),
            (
                URLError(PermissionError(10013, "socket denied")),
                "https",
                "HTTPS_BLOCKED",
            ),
            (
                ConnectionError("upgrade rejected"),
                "websocket",
                "WEBSOCKET_HANDSHAKE_FAILED",
            ),
            (
                PermissionError(10013, "socket denied"),
                "websocket",
                "TCP_443_BLOCKED",
            ),
            (OSError("read-only"), "file", "FILE_WRITE_FAILED"),
            (RuntimeError("unknown"), "other", "UNKNOWN_NETWORK_ERROR"),
        ]
        for exc, stage, expected in cases:
            with self.subTest(stage=stage):
                self.assertEqual(classify_exception(exc, stage), expected)
                self.assertIn(expected, ERROR_CODES)

    def test_rest_fallback_probes_only_public_get_market_endpoints(self):
        urls = []

        def transport(url):
            urls.append(url)
            if url.endswith("/time"):
                return {"retCode": 0, "result": {"timeSecond": "1"}, "time": 1}
            return {"retCode": 0, "result": {"list": [{"ok": True}]}, "time": 1}

        results = BybitRestFallback(transport=transport).probe("BTCUSDT")
        self.assertEqual(len(results), 5)
        self.assertTrue(all(result.status == "PASS" for result in results))
        self.assertTrue(all(url.startswith("https://api.bybit.com/v5/market/") for url in urls))
        self.assertFalse(any("/order" in url or "/position" in url for url in urls))
        parameters = inspect.signature(BybitRestFallback).parameters
        self.assertNotIn("api_key", parameters)
        self.assertNotIn("secret", parameters)

    def test_sanitizer_and_collector_logs_do_not_expose_secrets(self):
        raw = (
            "api_key=VISIBLE secret:ALSO_VISIBLE token=TOKEN123 "
            "Authorization=AUTH Bearer abc.def.ghi"
        )
        sanitized = sanitize_message(raw)
        for secret in ("VISIBLE", "ALSO_VISIBLE", "TOKEN123", "AUTH", "abc.def.ghi"):
            self.assertNotIn(secret, sanitized)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            collector = BybitMicrostructureCollector(
                ("BTCUSDT",),
                data_root=root / "data",
                output_root=root / "outputs",
                log_root=root / "logs",
            )
            collector._log("UNKNOWN_NETWORK_ERROR", raw)
            logged = (root / "logs" / "collector.log").read_text(encoding="utf-8")
            for secret in ("VISIBLE", "ALSO_VISIBLE", "TOKEN123", "AUTH", "abc.def.ghi"):
                self.assertNotIn(secret, logged)

    def test_diagnostic_report_has_explicit_safe_state(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "diagnostic.json"
            write_diagnostic_report(
                [
                    DiagnosticResult(
                        "tcp_443",
                        "stream.bybit.com:443",
                        "FAIL",
                        "TCP_443_BLOCKED",
                        1.0,
                        "PermissionError",
                    )
                ],
                {"private_values_logged": False},
                destination,
            )
            payload = json.loads(destination.read_text(encoding="utf-8"))
            safety = payload["safety"]
            self.assertFalse(safety["api_keys_used"])
            self.assertFalse(safety["broker_connected"])
            self.assertFalse(safety["orders_sent"])
            self.assertFalse(safety["live_trading_enabled"])
            self.assertFalse(safety["real_leverage_used"])

    def test_collector_status_preserves_no_broker_order_or_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            collector = BybitMicrostructureCollector(
                ("BTCUSDT",),
                data_root=root / "data",
                output_root=root / "outputs",
                log_root=root / "logs",
            )
            collector._record_error("TCP_443_BLOCKED", "socket denied")
            collector.write_quality_reports("reconnecting")
            status = pd.read_csv(root / "outputs" / "collector_status.csv").iloc[0]
            self.assertEqual(status["last_error_code"], "TCP_443_BLOCKED")
            self.assertFalse(bool(status["orders_sent"]))
            self.assertFalse(bool(status["broker_connected"]))
            self.assertFalse(bool(status["api_keys_used"]))

    def test_global_live_paper_and_broker_locks_remain_false(self):
        config = load_config(ROOT / "config.yaml")
        self.assertTrue(all(value is False for value in config.security.values()))
        edge = config.section("edge_discovery")
        self.assertFalse(edge["allow_private_api_keys"])
        self.assertFalse(edge["allow_real_leverage"])


if __name__ == "__main__":
    unittest.main()
