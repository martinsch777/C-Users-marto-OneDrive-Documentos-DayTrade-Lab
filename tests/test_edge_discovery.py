import inspect
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from src.config import load_config
from src.edge_discovery import (
    EVENT_LABELS,
    ForwardMarketCollector,
    add_event_labels,
    build_edge_strategies,
    parse_funding_payload,
    parse_open_interest_payload,
)
from src.edge_discovery.specialized_data import PublicSpecializedDataClient
from src.utils.synthetic import generate_synthetic_intraday


ROOT = Path(__file__).resolve().parents[1]


def fixture_frame(rows=140):
    timestamp = pd.date_range("2025-01-01", periods=rows, freq="5min", tz="UTC")
    close = np.full(rows, 100.0)
    close += np.sin(np.arange(rows) / 4) * 0.05
    frame = pd.DataFrame(
        {
            "timestamp": timestamp,
            "open": close - 0.01,
            "high": close + 0.10,
            "low": close - 0.10,
            "close": close,
            "volume": np.full(rows, 100.0),
        }
    )
    frame.loc[120, ["open", "high", "low", "close", "volume"]] = [
        100.0,
        104.2,
        99.9,
        104.0,
        1000.0,
    ]
    frame.loc[121, ["open", "high", "low", "close", "volume"]] = [
        100.0,
        100.2,
        95.0,
        100.1,
        900.0,
    ]
    return frame


class EdgeDiscoveryTests(unittest.TestCase):
    def test_event_labels_detect_extreme_volume_and_wick(self):
        labeled = add_event_labels(fixture_frame())
        self.assertTrue(set(EVENT_LABELS).issubset(labeled.columns))
        self.assertTrue(bool(labeled.loc[120, "EXTREME_UP_MOVE"]))
        self.assertTrue(bool(labeled.loc[120, "HIGH_RELATIVE_VOLUME"]))
        self.assertTrue(bool(labeled.loc[121, "LARGE_WICK_REVERSAL"]))

    def test_funding_and_open_interest_parsers_normalize_utc(self):
        funding = parse_funding_payload(
            [
                {
                    "symbol": "BTCUSDT",
                    "fundingTime": 1735689600000,
                    "fundingRate": "-0.0007",
                }
            ],
            "binance",
        )
        self.assertEqual(float(funding.iloc[0]["funding_rate"]), -0.0007)
        self.assertIsNotNone(funding.iloc[0]["timestamp"].tzinfo)
        oi = parse_open_interest_payload(
            {
                "result": {
                    "list": [
                        {
                            "symbol": "BTCUSDT",
                            "timestamp": "1735689600000",
                            "openInterest": "12345.6",
                        }
                    ]
                }
            },
            "bybit",
        )
        self.assertEqual(float(oi.iloc[0]["open_interest"]), 12345.6)

    def test_event_strategies_do_not_change_visible_prefix(self):
        frame = generate_synthetic_intraday(
            sessions=25, timeframe="15min", seed=212
        )
        cutoff = len(frame) * 2 // 3
        end = frame.iloc[cutoff - 1]["timestamp"]
        for strategy in build_edge_strategies():
            with self.subTest(strategy=strategy.name):
                prefix = strategy.generate_signals(
                    frame.iloc[:cutoff].copy(), "TEST", "15min"
                )
                full = [
                    signal
                    for signal in strategy.generate_signals(
                        frame.copy(), "TEST", "15min"
                    )
                    if signal.timestamp <= end
                ]
                self.assertEqual(
                    [(x.timestamp, x.side, x.entry_price) for x in prefix],
                    [(x.timestamp, x.side, x.entry_price) for x in full],
                )

    def test_forward_collector_uses_public_get_data_only(self):
        def transport(url):
            if "/depth?" in url:
                return {
                    "lastUpdateId": 1,
                    "bids": [["100", "2"]],
                    "asks": [["101", "3"]],
                }
            if "/aggTrades?" in url:
                return [
                    {
                        "a": 1,
                        "p": "100.5",
                        "q": "0.2",
                        "T": 1735689600000,
                        "m": False,
                    }
                ]
            if "/openInterest?" in url:
                return {
                    "openInterest": "1234",
                    "symbol": "BTCUSDT",
                    "time": 1735689600000,
                }
            if "/premiumIndex?" in url:
                return {
                    "markPrice": "100.5",
                    "indexPrice": "100.4",
                    "lastFundingRate": "0.0001",
                    "nextFundingTime": 1735718400000,
                }
            raise AssertionError(url)

        with tempfile.TemporaryDirectory() as directory:
            collector = ForwardMarketCollector(directory, transport=transport)
            status = collector.collect_once(("BTCUSDT",))
            self.assertEqual(status.iloc[0]["status"], "collected")
            self.assertFalse(bool(status.iloc[0]["orders_sent"]))
            self.assertTrue((Path(directory) / "orderbook_snapshots.csv").exists())
        forbidden = {
            "place_order",
            "submit_order",
            "send_order",
            "connect_broker",
            "set_leverage",
        }
        self.assertTrue(forbidden.isdisjoint(dir(ForwardMarketCollector)))

    def test_public_clients_accept_no_api_key_or_secret(self):
        collector_parameters = inspect.signature(
            ForwardMarketCollector
        ).parameters
        specialized_parameters = inspect.signature(
            PublicSpecializedDataClient
        ).parameters
        for parameters in (collector_parameters, specialized_parameters):
            self.assertNotIn("api_key", parameters)
            self.assertNotIn("secret", parameters)

    def test_edge_security_defaults_are_locked(self):
        config = load_config(ROOT / "config.yaml")
        edge = config.section("edge_discovery")
        self.assertFalse(edge["forward_collection_enabled"])
        self.assertFalse(edge["allow_private_api_keys"])
        self.assertFalse(edge["allow_real_leverage"])
        self.assertTrue(edge["public_market_data_only"])
        self.assertTrue(all(value is False for value in config.security.values()))


if __name__ == "__main__":
    unittest.main()
