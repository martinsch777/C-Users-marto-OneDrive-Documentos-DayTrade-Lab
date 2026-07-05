import inspect
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from src.config import load_config
from src.edge_discovery.labels import add_event_labels
from src.lead_validation import (
    align_specialized_data_causally,
    build_lead_strategies,
    detect_fvg_and_mss,
    import_funding_csv,
    import_open_interest_csv,
)
from src.microstructure_collector import (
    BybitMicrostructureCollector,
    OrderBookState,
    parse_bybit_message,
)
from src.utils.synthetic import generate_synthetic_intraday


ROOT = Path(__file__).resolve().parents[1]


class LeadAndMicrostructureTests(unittest.TestCase):
    def test_compression_and_fvg_rules_are_prefix_causal(self):
        frame = generate_synthetic_intraday(
            sessions=30, timeframe="15min", seed=901
        )
        cutoff = len(frame) * 2 // 3
        visible_end = frame.iloc[cutoff - 1]["timestamp"]
        for strategy in build_lead_strategies():
            with self.subTest(strategy=strategy.name):
                prefix = strategy.generate_signals(
                    frame.iloc[:cutoff].copy(), "TEST", "15min"
                )
                full = [
                    signal
                    for signal in strategy.generate_signals(
                        frame.copy(), "TEST", "15min"
                    )
                    if signal.timestamp <= visible_end
                ]
                self.assertEqual(
                    [(x.timestamp, x.side, x.entry_price) for x in prefix],
                    [(x.timestamp, x.side, x.entry_price) for x in full],
                )

    def test_fvg_and_mss_detection_uses_prior_structure_only(self):
        frame = pd.DataFrame(
            {
                "timestamp": pd.date_range(
                    "2025-01-01", periods=25, freq="5min", tz="UTC"
                ),
                "open": [100.0] * 25,
                "high": [101.0] * 25,
                "low": [99.0] * 25,
                "close": [100.0] * 25,
                "volume": [100.0] * 25,
                "atr": [1.0] * 25,
            }
        )
        frame.loc[22, ["open", "high", "low", "close"]] = [
            102.0,
            103.0,
            102.0,
            102.8,
        ]
        flags = detect_fvg_and_mss(frame, structure_lookback=20)
        self.assertTrue(bool(flags.loc[22, "bullish_fvg"]))
        self.assertTrue(bool(flags.loc[22, "bullish_mss"]))
        prefix_flags = detect_fvg_and_mss(
            frame.iloc[:23].copy(), structure_lookback=20
        )
        pd.testing.assert_frame_equal(
            flags.iloc[:23].reset_index(drop=True),
            prefix_flags.reset_index(drop=True),
        )

    def test_rvol_uses_only_prior_volume(self):
        frame = generate_synthetic_intraday(
            sessions=4, timeframe="15min", seed=42
        )
        frame.loc[100, "volume"] = frame.loc[:99, "volume"].mean() * 10
        labeled = add_event_labels(frame)
        expected = frame.loc[100, "volume"] / frame.loc[4:99, "volume"].mean()
        self.assertAlmostEqual(
            labeled.loc[100, "relative_volume_event"], expected, places=10
        )

    def test_offline_funding_oi_import_and_backward_alignment(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            funding_path = root / "funding.csv"
            oi_path = root / "oi.csv"
            pd.DataFrame(
                {
                    "fundingTime": [1735689600000, 1735718400000],
                    "fundingRate": ["0.0001", "-0.0006"],
                }
            ).to_csv(funding_path, index=False)
            pd.DataFrame(
                {
                    "datetime": [
                        "2025-01-01T00:00:00Z",
                        "2025-01-01T00:05:00Z",
                    ],
                    "sumOpenInterest": [1000, 1100],
                }
            ).to_csv(oi_path, index=False)
            funding, funding_report = import_funding_csv(funding_path)
            oi, oi_report = import_open_interest_csv(oi_path)
            self.assertEqual(funding_report["valid_rows"], 2)
            self.assertEqual(oi_report["valid_rows"], 2)
            candles = pd.DataFrame(
                {
                    "timestamp": pd.to_datetime(
                        [
                            "2024-12-31T23:59:00Z",
                            "2025-01-01T00:03:00Z",
                            "2025-01-01T00:06:00Z",
                        ],
                        utc=True,
                    ),
                    "close": [99, 100, 101],
                }
            )
            aligned = align_specialized_data_causally(
                candles, oi, "open_interest", max_staleness="10min"
            )
            self.assertTrue(pd.isna(aligned.iloc[0]["open_interest"]))
            self.assertEqual(aligned.iloc[1]["open_interest"], 1000)
            self.assertEqual(aligned.iloc[2]["open_interest"], 1100)
            valid = aligned.dropna(subset=["source_timestamp"])
            self.assertTrue(
                (valid["source_timestamp"] <= valid["timestamp"]).all()
            )

    def test_bybit_parsers_book_delta_liquidation_and_ticker(self):
        snapshot = {
            "topic": "orderbook.50.BTCUSDT",
            "type": "snapshot",
            "ts": 1735689600000,
            "data": {
                "s": "BTCUSDT",
                "u": 10,
                "seq": 100,
                "b": [["100", "2"], ["99", "3"]],
                "a": [["101", "4"], ["102", "5"]],
            },
        }
        event = parse_bybit_message(snapshot)[0]
        book = OrderBookState("BTCUSDT")
        self.assertFalse(book.update(event))
        metrics = book.metrics()
        self.assertEqual(metrics["best_bid"], 100)
        self.assertEqual(metrics["best_ask"], 101)
        self.assertAlmostEqual(
            metrics["spread_bps"], 1 / 100.5 * 10_000
        )
        self.assertLess(metrics["imbalance_l5"], 0)
        delta = {
            **snapshot,
            "type": "delta",
            "data": {
                "s": "BTCUSDT",
                "u": 11,
                "seq": 102,
                "b": [["100", "0"], ["100.5", "1"]],
                "a": [],
            },
        }
        self.assertTrue(book.update(parse_bybit_message(delta)[0]))
        liquidation = parse_bybit_message(
            {
                "topic": "allLiquidation.BTCUSDT",
                "type": "snapshot",
                "ts": 1735689600000,
                "data": [
                    {
                        "T": 1735689599990,
                        "s": "BTCUSDT",
                        "S": "Sell",
                        "v": "2",
                        "p": "100",
                    }
                ],
            }
        )[0]
        self.assertEqual(liquidation["kind"], "liquidation")
        self.assertEqual(liquidation["size"], 2)
        ticker = parse_bybit_message(
            {
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
        )[0]
        self.assertEqual(ticker["open_interest"], 1234)

    def test_collector_quality_dedup_and_no_trading_surface(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            collector = BybitMicrostructureCollector(
                ("BTCUSDT",),
                data_root=root / "data",
                output_root=root / "outputs",
                log_root=root / "logs",
            )
            payload = {
                "topic": "orderbook.50.BTCUSDT",
                "type": "snapshot",
                "ts": 1735689600000,
                "data": {
                    "s": "BTCUSDT",
                    "u": 1,
                    "seq": 1,
                    "b": [["100", "2"]],
                    "a": [["101", "2"]],
                },
            }
            self.assertEqual(
                collector.process_payload(
                    payload, received_at_ms=1735689600010
                ),
                1,
            )
            self.assertEqual(
                collector.process_payload(
                    payload, received_at_ms=1735689600011
                ),
                0,
            )
            collector.write_quality_reports("test_complete")
            quality = pd.read_csv(root / "outputs" / "data_quality.csv")
            orderbook = quality[quality["kind"] == "orderbook"].iloc[0]
            self.assertEqual(orderbook["messages"], 1)
            self.assertEqual(orderbook["duplicates"], 1)
            forbidden = {
                "place_order",
                "send_order",
                "connect_broker",
                "set_leverage",
                "api_key",
                "secret",
            }
            self.assertTrue(
                forbidden.isdisjoint(dir(BybitMicrostructureCollector))
            )
            parameters = inspect.signature(
                BybitMicrostructureCollector
            ).parameters
            self.assertNotIn("api_key", parameters)
            self.assertNotIn("secret", parameters)

    def test_global_safety_remains_locked(self):
        security = load_config(ROOT / "config.yaml").security
        self.assertFalse(security["live_trading_enabled"])
        self.assertFalse(security["broker_connected"])
        self.assertFalse(security["orders_sent"])
        self.assertFalse(security["paper_internal_enabled"])
        self.assertFalse(security["paper_broker_enabled"])


if __name__ == "__main__":
    unittest.main()
