import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from src.bybit_diagnostics import classify_websocket_exception
from src.config import load_config
from src.microstructure_collector import (
    FAIL_NO_MARKET_DATA,
    FAIL_WEBSOCKET_UNSTABLE,
    PASS_REST_ONLY_FALLBACK,
    PASS_WEBSOCKET_STABLE,
    BybitMicrostructureCollector,
    StabilityMetrics,
    build_stability_report,
    classify_stability,
    parse_bybit_message,
    reconnect_backoff,
)
from src.microstructure_collector_cli import parser


ROOT = Path(__file__).resolve().parents[1]


class InvalidHandshake(Exception):
    pass


class ConnectionClosedError(Exception):
    pass


class MicrostructureStabilityTests(unittest.TestCase):
    def test_kline_symbol_is_derived_from_topic(self):
        payload = {
            "topic": "kline.1.BTCUSDT",
            "type": "snapshot",
            "ts": 1735689600000,
            "data": [
                {
                    "start": 1735689600000,
                    "end": 1735689659999,
                    "interval": "1",
                    "open": "100",
                    "high": "102",
                    "low": "99",
                    "close": "101",
                    "volume": "4",
                    "confirm": False,
                }
            ],
        }
        event = parse_bybit_message(payload)[0]
        self.assertEqual(event["symbol"], "BTCUSDT")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            collector = BybitMicrostructureCollector(
                ("BTCUSDT",),
                data_root=root / "data",
                output_root=root / "outputs",
                log_root=root / "logs",
                enabled_topics=("kline",),
            )
            self.assertEqual(collector.process_payload(payload), 1)
            stored = pd.read_csv(root / "data" / "kline.csv")
            self.assertEqual(stored.iloc[0]["symbol"], "BTCUSDT")

    def test_websocket_error_classification_uses_actual_stage(self):
        cases = (
            (
                ConnectionError("socket denied"),
                "connect",
                "WEBSOCKET_CONNECT_FAILED",
            ),
            (
                InvalidHandshake("HTTP upgrade rejected"),
                "connect",
                "WEBSOCKET_HANDSHAKE_FAILED",
            ),
            (
                TimeoutError(),
                "recv",
                "WEBSOCKET_RECV_TIMEOUT",
            ),
            (
                ConnectionClosedError("closed by peer"),
                "recv",
                "WEBSOCKET_CLOSED_BY_REMOTE",
            ),
            (
                ValueError("bad json"),
                "parse",
                "WEBSOCKET_PARSE_ERROR",
            ),
            (
                OSError("disk full"),
                "persistence",
                "WEBSOCKET_PERSISTENCE_ERROR",
            ),
        )
        for exc, stage, expected in cases:
            with self.subTest(stage=stage, expected=expected):
                self.assertEqual(
                    classify_websocket_exception(exc, stage), expected
                )

    def test_backoff_is_progressive_and_capped(self):
        values = [reconnect_backoff(index, 10) for index in range(7)]
        self.assertEqual(values, [1, 2, 5, 10, 10, 10, 10])

    def test_stability_outcomes_are_separate(self):
        stable = StabilityMetrics(
            websocket_connected=1,
            websocket_subscription_acknowledged=True,
            websocket_messages_received=100,
            websocket_messages_persisted=95,
            websocket_errors=2,
            websocket_reconnects=2,
        )
        self.assertEqual(
            classify_stability(stable), PASS_WEBSOCKET_STABLE
        )
        rest_only = StabilityMetrics(
            rest_requests_ok=5,
            fallback_rest_messages_received=4,
        )
        self.assertEqual(
            classify_stability(rest_only), PASS_REST_ONLY_FALLBACK
        )
        unstable = StabilityMetrics(
            websocket_connected=20,
            websocket_messages_received=100,
            websocket_messages_persisted=90,
            websocket_errors=10,
            websocket_reconnects=10,
        )
        self.assertEqual(
            classify_stability(unstable), FAIL_WEBSOCKET_UNSTABLE
        )
        self.assertEqual(
            classify_stability(StabilityMetrics()), FAIL_NO_MARKET_DATA
        )

    def test_rest_and_websocket_metrics_are_not_mixed(self):
        metrics = StabilityMetrics(
            rest_requests_ok=5,
            rest_requests_failed=1,
            websocket_messages_received=20,
            websocket_messages_persisted=18,
            fallback_rest_messages_received=4,
            total_messages_received=24,
        )
        report = build_stability_report(
            metrics,
            duration_seconds=600,
            topics=["tickers.BTCUSDT"],
        )
        values = report["metrics"]
        self.assertEqual(values["rest_requests_ok"], 5)
        self.assertEqual(values["rest_requests_failed"], 1)
        self.assertEqual(values["websocket_messages_received"], 20)
        self.assertEqual(values["websocket_messages_persisted"], 18)
        self.assertEqual(values["fallback_rest_messages_received"], 4)
        self.assertEqual(values["total_messages_received"], 24)

    def test_persistence_and_status_are_counted_by_topic(self):
        payload = {
            "topic": "tickers.BTCUSDT",
            "type": "snapshot",
            "ts": 1735689600000,
            "data": {
                "symbol": "BTCUSDT",
                "bid1Price": "100",
                "ask1Price": "101",
                "markPrice": "100.5",
                "indexPrice": "100.4",
                "fundingRate": "0.0001",
                "openInterest": "1234",
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            collector = BybitMicrostructureCollector(
                ("BTCUSDT",),
                data_root=root / "data",
                output_root=root / "outputs",
                log_root=root / "logs",
                enabled_topics=("ticker",),
            )
            collector.websocket_connected = 1
            collector.subscription_acknowledged = True
            collector.websocket_messages_received = 1
            collector.messages_by_topic["tickers.BTCUSDT"] = 1
            self.assertEqual(collector.process_payload(payload), 1)
            collector.write_quality_reports("completed")
            status = pd.read_csv(
                root / "outputs" / "collector_status.csv"
            ).iloc[0]
            self.assertEqual(status["rest_requests_ok"], 0)
            self.assertEqual(status["websocket_messages_received"], 1)
            self.assertEqual(status["websocket_messages_persisted"], 1)
            persisted = json.loads(status["persisted_by_topic"])
            self.assertEqual(persisted["tickers.BTCUSDT"], 1)
            self.assertGreaterEqual(int(status["files_written"]), 2)

    def test_topic_selection_and_topic_smoke_phases_exist(self):
        args = parser().parse_args(
            [
                "run",
                "--topics",
                "ticker",
                "trades",
                "--duration-seconds",
                "60",
                "--confirm-public-data-only",
            ]
        )
        self.assertEqual(args.topics, ["ticker", "trades"])
        script = (
            ROOT / "scripts" / "smoke_test_bybit_topics.ps1"
        ).read_text(encoding="utf-8")
        for phase in (
            "ticker",
            "trades",
            "orderbook",
            "liquidation",
            "ticker_trades",
            "ticker_trades_orderbook",
            "all_topics",
        ):
            self.assertIn(f'"{phase}"', script)

    def test_report_and_global_safety_locks_are_explicit(self):
        report = build_stability_report(
            StabilityMetrics(),
            duration_seconds=60,
            topics=[],
        )
        self.assertFalse(any(report["safety"].values()))
        security = load_config(ROOT / "config.yaml").security
        self.assertFalse(any(security.values()))


if __name__ == "__main__":
    unittest.main()
