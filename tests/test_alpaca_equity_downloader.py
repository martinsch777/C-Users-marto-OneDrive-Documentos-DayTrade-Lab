import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pandas as pd

from src.data.alpaca_equity_downloader import (
    AlpacaDownloadError,
    AlpacaEquityIntradayDownloader,
    DownloadRequest,
    classify_alpaca_http_error,
    download_output_filename,
    normalize_alpaca_bars,
)


def alpaca_bar(timestamp: str, close: float = 100.5):
    return {
        "t": timestamp,
        "o": 100.0,
        "h": 101.0,
        "l": 99.0,
        "c": close,
        "v": 1000,
    }


def local_rth_bars(day: str, close: str = "15:59"):
    local = pd.date_range(
        f"{day} 09:30",
        f"{day} {close}",
        freq="1min",
        tz="America/New_York",
    )
    return [alpaca_bar(ts.tz_convert("UTC").isoformat()) for ts in local]


class AlpacaEquityDownloaderTests(unittest.TestCase):
    def test_missing_api_key_is_clean_error(self):
        downloader = AlpacaEquityIntradayDownloader(api_key_id="", api_secret_key="secret")

        with self.assertRaises(AlpacaDownloadError) as context:
            downloader.download(
                DownloadRequest(
                    symbol="QQQ",
                    start="2024-01-01",
                    end="2024-01-02",
                    output_dir=Path(tempfile.mkdtemp()),
                )
            )

        self.assertEqual(context.exception.code, "APCA_API_KEY_ID_MISSING")

    def test_missing_secret_key_is_clean_error(self):
        downloader = AlpacaEquityIntradayDownloader(api_key_id="key", api_secret_key="")

        with self.assertRaises(AlpacaDownloadError) as context:
            downloader.download(
                DownloadRequest(
                    symbol="QQQ",
                    start="2024-01-01",
                    end="2024-01-02",
                    output_dir=Path(tempfile.mkdtemp()),
                )
            )

        self.assertEqual(context.exception.code, "APCA_API_SECRET_KEY_MISSING")

    def test_dry_run_cli_uses_no_network_and_requires_no_credentials(self):
        env = os.environ.copy()
        env.pop("APCA_API_KEY_ID", None)
        env.pop("APCA_API_SECRET_KEY", None)
        output = Path(tempfile.mkdtemp())

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "src.cli",
                "download-equity-intraday",
                "--provider",
                "alpaca",
                "--symbols",
                "QQQ",
                "SPY",
                "--start",
                "2024-01-01",
                "--end",
                "2024-01-31",
                "--interval",
                "1min",
                "--feed",
                "sip",
                "--output-dir",
                str(output),
                "--dry-run",
            ],
            check=False,
            text=True,
            capture_output=True,
            env=env,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("DRY_RUN endpoint=https://data.alpaca.markets/v2/stocks/QQQ/bars", result.stdout)
        self.assertIn("DRY_RUN output_file=", result.stdout)
        self.assertIn("Safety state", result.stdout)
        self.assertFalse((output / "QQQ_1min.csv").exists())

    def test_download_cli_help_shows_range_and_overwrite_flags(self):
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "src.cli",
                "download-equity-intraday",
                "--help",
            ],
            check=False,
            text=True,
            capture_output=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--range-filenames", result.stdout)
        self.assertIn("--overwrite", result.stdout)

    def test_url_and_headers_are_market_data_only_and_secret_not_logged(self):
        captured = {}

        def fake_request(url, headers):
            captured["url"] = url
            captured["headers"] = headers
            return {"bars": [], "next_page_token": None}

        output = Path(tempfile.mkdtemp())
        downloader = AlpacaEquityIntradayDownloader(
            api_key_id="key-id",
            api_secret_key="super-secret",
            request_json=fake_request,
        )
        downloader.download(
            DownloadRequest(
                symbol="QQQ",
                start="2024-01-01",
                end="2024-01-02",
                feed="iex",
                output_dir=output,
            )
        )

        parsed = urlparse(captured["url"])
        params = parse_qs(parsed.query)
        self.assertEqual(parsed.netloc, "data.alpaca.markets")
        self.assertEqual(parsed.path, "/v2/stocks/QQQ/bars")
        self.assertEqual(params["timeframe"], ["1Min"])
        self.assertEqual(params["adjustment"], ["raw"])
        self.assertEqual(params["feed"], ["iex"])
        self.assertEqual(captured["headers"]["APCA-API-KEY-ID"], "key-id")
        self.assertEqual(captured["headers"]["APCA-API-SECRET-KEY"], "super-secret")
        self.assertNotIn("super-secret", json.dumps(downloader.last_headers))

    def test_pagination_and_output_summary(self):
        pages = {
            None: {
                "bars": [alpaca_bar("2024-07-01T13:30:00Z")],
                "next_page_token": "next",
            },
            "next": {
                "bars": [alpaca_bar("2024-07-01T13:31:00Z")],
                "next_page_token": None,
            },
        }

        def fake_request(url, _headers):
            token = parse_qs(urlparse(url).query).get("page_token", [None])[0]
            return pages[token]

        output = Path(tempfile.mkdtemp())
        result = AlpacaEquityIntradayDownloader(
            api_key_id="key",
            api_secret_key="secret",
            request_json=fake_request,
        ).download(
            DownloadRequest(
                symbol="QQQ",
                start="2024-07-01",
                end="2024-07-01",
                output_dir=output,
            )
        )

        self.assertEqual(result.pages_downloaded, 2)
        self.assertEqual(result.rows, 2)
        self.assertTrue(Path(result.output_file).exists())
        self.assertTrue(result.sha256)

    def test_range_filename_correct_for_downloader(self):
        request = DownloadRequest(
            symbol="QQQ",
            start="2022-01-01",
            end="2026-07-06",
            feed="sip",
            adjustment="raw",
            rth_only=True,
            range_filenames=True,
        )

        self.assertEqual(
            download_output_filename(request),
            "QQQ_1min_2022-01-01_2026-07-06_alpaca_sip_raw_rth.csv",
        )

    def test_legacy_filename_is_preserved_without_range_filenames(self):
        request = DownloadRequest(
            symbol="SPY",
            start="2022-01-01",
            end="2026-07-06",
            feed="sip",
            adjustment="raw",
            rth_only=True,
        )

        self.assertEqual(download_output_filename(request), "SPY_1min.csv")

    def test_existing_output_without_overwrite_fails_before_network(self):
        calls = {"count": 0}

        def fake_request(_url, _headers):
            calls["count"] += 1
            return {"bars": [alpaca_bar("2024-07-01T13:30:00Z")]}

        output = Path(tempfile.mkdtemp())
        existing = output / "QQQ_1min.csv"
        existing.write_text("existing", encoding="utf-8")

        with self.assertRaises(AlpacaDownloadError) as context:
            AlpacaEquityIntradayDownloader(
                api_key_id="key",
                api_secret_key="secret",
                request_json=fake_request,
            ).download(
                DownloadRequest(
                    symbol="QQQ",
                    start="2024-07-01",
                    end="2024-07-01",
                    output_dir=output,
                )
            )

        self.assertEqual(context.exception.code, "OUTPUT_FILE_ALREADY_EXISTS")
        self.assertEqual(calls["count"], 0)

    def test_existing_output_with_overwrite_allows_regeneration(self):
        output = Path(tempfile.mkdtemp())
        existing = output / "QQQ_1min.csv"
        existing.write_text("existing", encoding="utf-8")

        result = AlpacaEquityIntradayDownloader(
            api_key_id="key",
            api_secret_key="secret",
            request_json=lambda _url, _headers: {
                "bars": [alpaca_bar("2024-07-01T13:30:00Z")],
                "next_page_token": None,
            },
        ).download(
            DownloadRequest(
                symbol="QQQ",
                start="2024-07-01",
                end="2024-07-01",
                output_dir=output,
                overwrite=True,
            )
        )

        self.assertEqual(result.output_file, str(existing))
        self.assertIn("timestamp,open,high,low,close,volume", existing.read_text(encoding="utf-8"))
        self.assertEqual(result.rows, 1)

    def test_manifest_input_file_uses_actual_range_output_file(self):
        from src.data import audit_equity_intraday_csv
        from src.data.dataset_manifest import build_dataset_manifest

        output = Path(tempfile.mkdtemp())
        result = AlpacaEquityIntradayDownloader(
            api_key_id="key",
            api_secret_key="secret",
            request_json=lambda _url, _headers: {
                "bars": local_rth_bars("2024-07-01"),
                "next_page_token": None,
            },
        ).download(
            DownloadRequest(
                symbol="QQQ",
                start="2024-07-01",
                end="2024-07-01",
                feed="sip",
                adjustment="raw",
                output_dir=output,
                rth_only=True,
                range_filenames=True,
            )
        )
        audit = audit_equity_intraday_csv(result.output_file, "QQQ", "1min")

        manifest = build_dataset_manifest(
            result,
            audit_report=audit,
            source_timezone="America/New_York",
        )

        self.assertEqual(
            Path(manifest.input_file).name,
            "QQQ_1min_2024-07-01_2024-07-01_alpaca_sip_raw_rth.csv",
        )
        self.assertEqual(manifest.input_file, result.output_file)

    def test_repeated_page_token_is_rejected(self):
        def fake_request(_url, _headers):
            return {
                "bars": [alpaca_bar("2024-07-01T13:30:00Z")],
                "next_page_token": "same",
            }

        with self.assertRaises(AlpacaDownloadError) as context:
            AlpacaEquityIntradayDownloader(
                api_key_id="key",
                api_secret_key="secret",
                request_json=fake_request,
            ).download(
                DownloadRequest(
                    symbol="QQQ",
                    start="2024-07-01",
                    end="2024-07-01",
                    output_dir=Path(tempfile.mkdtemp()),
                )
            )

        self.assertEqual(context.exception.code, "ALPACA_PAGE_TOKEN_LOOP_DETECTED")

    def test_normalization_orders_deduplicates_and_converts_to_new_york(self):
        frame = normalize_alpaca_bars(
            [
                alpaca_bar("2024-07-01T13:31:00Z", close=101.0),
                alpaca_bar("2024-07-01T13:30:00Z", close=100.0),
                alpaca_bar("2024-07-01T13:30:00Z", close=100.25),
            ]
        )

        self.assertEqual(
            list(frame.columns),
            ["timestamp", "open", "high", "low", "close", "volume"],
        )
        self.assertEqual(len(frame), 2)
        self.assertEqual(frame.iloc[0]["timestamp"], "2024-07-01 09:30:00-04:00")
        self.assertEqual(float(frame.iloc[0]["close"]), 100.25)
        self.assertTrue(frame["timestamp"].is_monotonic_increasing)

    def test_rth_filter_keeps_normal_390_bars(self):
        frame = normalize_alpaca_bars(
            [
                alpaca_bar("2024-07-01T12:00:00Z"),
                *local_rth_bars("2024-07-01"),
                alpaca_bar("2024-07-01T20:00:00Z"),
            ],
            rth_only=True,
        )

        self.assertEqual(len(frame), 390)
        self.assertEqual(frame.iloc[0]["timestamp"], "2024-07-01 09:30:00-04:00")
        self.assertEqual(frame.iloc[-1]["timestamp"], "2024-07-01 15:59:00-04:00")

    def test_rth_filter_keeps_early_close_210_bars(self):
        frame = normalize_alpaca_bars(
            local_rth_bars("2024-07-03") + [alpaca_bar("2024-07-03T17:00:00Z")],
            rth_only=True,
        )

        self.assertEqual(len(frame), 210)
        self.assertEqual(frame.iloc[-1]["timestamp"], "2024-07-03 12:59:00-04:00")

    def test_sip_subscription_required_error(self):
        error = classify_alpaca_http_error(
            403,
            "subscription does not permit SIP feed",
        )

        self.assertEqual(error.code, "ALPACA_SIP_SUBSCRIPTION_REQUIRED")
        self.assertNotIn("secret", str(error).lower())

    def test_module_does_not_import_trading_or_order_surfaces(self):
        source = Path("src/data/alpaca_equity_downloader.py").read_text(encoding="utf-8")

        self.assertNotIn("alpaca.trading", source)
        self.assertNotIn("/v2/orders", source)
        self.assertNotIn("/v2/account", source)
        self.assertNotIn("/v2/positions", source)


if __name__ == "__main__":
    unittest.main()
