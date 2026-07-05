import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from src.data import BinancePublicDataProvider, audit_crypto_csv


def kline(open_time_ms: int, interval_ms: int) -> list:
    return [
        open_time_ms,
        "100.0",
        "101.0",
        "99.0",
        "100.5",
        "10.0",
        open_time_ms + interval_ms - 1,
        "0",
        1,
        "0",
        "0",
        "0",
    ]


class FakePagedBinance(BinancePublicDataProvider):
    def __init__(self, pages):
        super().__init__(request_pause_seconds=0)
        self.pages = list(pages)
        self.urls = []

    def _request_json(self, url):
        self.urls.append(url)
        return self.pages.pop(0), {"x-mbx-used-weight-1m": "4"}, 0


class Sprint2DataTests(unittest.TestCase):
    def test_paginated_download_is_deduplicated_ordered_and_audited(self):
        interval_ms = 300_000
        start = pd.Timestamp("2024-01-01 00:00:00+00:00")
        start_ms = int(start.timestamp() * 1000)
        page_one = [kline(start_ms + i * interval_ms, interval_ms) for i in range(1000)]
        page_two = [
            kline(start_ms + i * interval_ms, interval_ms)
            for i in range(1000, 1002)
        ]
        provider = FakePagedBinance([page_one, page_two])
        end = start + pd.Timedelta(minutes=5 * 1002)
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "BTCUSDT_5min.csv"
            metadata = provider.download_history(
                "BTCUSDT",
                "5min",
                start,
                end,
                destination,
            )
            frame = pd.read_csv(destination)
            self.assertEqual(len(provider.urls), 2)
            self.assertEqual(len(frame), 1002)
            self.assertEqual(frame["timestamp"].nunique(), 1002)
            self.assertTrue(pd.to_datetime(frame["timestamp"], utc=True).is_monotonic_increasing)
            self.assertEqual(metadata["missing_bars"], 0)
            self.assertTrue(metadata["quality_valid"])
            self.assertFalse(metadata["uses_api_key"])
            stored = json.loads(
                destination.with_suffix(".metadata.json").read_text(encoding="utf-8")
            )
            self.assertEqual(stored["status"], "complete")
            self.assertEqual(stored["requests"], 2)

    def test_audit_detects_duplicates_missing_bar_and_non_utc_text(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "BTCUSDT_5min.csv"
            pd.DataFrame(
                {
                    "timestamp": [
                        "2024-01-01 00:00:00",
                        "2024-01-01 00:00:00",
                        "2024-01-01 00:10:00",
                    ],
                    "open": [100, 100, 100],
                    "high": [101, 101, 101],
                    "low": [99, 99, 99],
                    "close": [100, 100, 100],
                    "volume": [10, 10, 10],
                }
            ).to_csv(path, index=False)
            audit = audit_crypto_csv(
                path,
                "BTCUSDT",
                "5min",
                reference_time=pd.Timestamp("2024-01-02", tz="UTC"),
            )
            self.assertEqual(audit.source_duplicates, 1)
            self.assertEqual(audit.missing_bars, 1)
            self.assertFalse(audit.timezone_utc)
            self.assertFalse(audit.quality_valid)


if __name__ == "__main__":
    unittest.main()
