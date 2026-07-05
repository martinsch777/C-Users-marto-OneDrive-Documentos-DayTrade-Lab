from __future__ import annotations

import hashlib
import io
import json
import random
import shutil
import time
import urllib.parse
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError

import pandas as pd

from .loader import load_csv, normalize_ohlcv, validate_ohlcv


def _sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass
class LocalCSVProvider:
    path: Path

    def fetch(
        self,
        timeframe: str,
        *,
        asset_class: str = "equity",
    ) -> pd.DataFrame:
        frame, report = load_csv(
            self.path,
            timeframe,
            asset_class=asset_class,
            drop_incomplete=True,
        )
        if not report.is_valid:
            raise ValueError(f"CSV data quality check failed: {report}")
        return frame


@dataclass
class BinancePublicDataProvider:
    """Read-only public kline downloader. It has no order or account methods."""

    base_url: str = "https://data-api.binance.vision"

    _INTERVALS = {
        "1min": "1m",
        "5min": "5m",
        "15min": "15m",
        "30min": "30m",
        "1h": "1h",
    }
    _INTERVAL_MILLISECONDS = {
        "1min": 60_000,
        "5min": 300_000,
        "15min": 900_000,
        "30min": 1_800_000,
        "1h": 3_600_000,
    }

    request_pause_seconds: float = 0.08
    max_retries: int = 7

    @staticmethod
    def _utc_timestamp(value: pd.Timestamp | str | None) -> pd.Timestamp:
        timestamp = pd.Timestamp.now(tz="UTC") if value is None else pd.Timestamp(value)
        if timestamp.tzinfo is None:
            return timestamp.tz_localize("UTC")
        return timestamp.tz_convert("UTC")

    def _request_json(self, url: str) -> tuple[list, dict[str, str], int]:
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "DayTrade-Lab/0.2 research-only"},
            method="GET",
        )
        retries = 0
        while True:
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    headers = {key.lower(): value for key, value in response.headers.items()}
                    payload = json.loads(response.read().decode("utf-8"))
                if not isinstance(payload, list):
                    raise RuntimeError(f"Unexpected Binance response: {payload}")
                return payload, headers, retries
            except HTTPError as exc:
                retryable = exc.code in {418, 429, 500, 502, 503, 504}
                if not retryable or retries >= self.max_retries:
                    raise
                retry_after = exc.headers.get("Retry-After")
                delay = (
                    float(retry_after)
                    if retry_after
                    else min(60.0, 2**retries + random.random())
                )
            except (URLError, TimeoutError):
                if retries >= self.max_retries:
                    raise
                delay = min(60.0, 2**retries + random.random())
            retries += 1
            time.sleep(delay)

    @staticmethod
    def _rows(payload: list) -> pd.DataFrame:
        rows = [
            {
                "timestamp": item[0],
                "open": item[1],
                "high": item[2],
                "low": item[3],
                "close": item[4],
                "volume": item[5],
                "_close_time": item[6],
            }
            for item in payload
        ]
        frame = pd.DataFrame(rows)
        if not frame.empty:
            frame["timestamp"] = pd.to_datetime(frame["timestamp"], unit="ms", utc=True)
            frame["_close_time"] = pd.to_datetime(
                frame["_close_time"], unit="ms", utc=True
            )
        return frame

    def fetch(
        self,
        symbol: str,
        timeframe: str,
        *,
        start: pd.Timestamp | None = None,
        end: pd.Timestamp | None = None,
        limit: int = 1000,
    ) -> pd.DataFrame:
        if timeframe not in self._INTERVALS:
            raise ValueError(f"Unsupported Binance timeframe: {timeframe}")
        params: dict[str, str | int] = {
            "symbol": symbol.upper(),
            "interval": self._INTERVALS[timeframe],
            "limit": min(max(limit, 1), 1000),
        }
        if start is not None:
            params["startTime"] = int(pd.Timestamp(start).timestamp() * 1000)
        if end is not None:
            params["endTime"] = int(pd.Timestamp(end).timestamp() * 1000)
        url = f"{self.base_url}/api/v3/klines?{urllib.parse.urlencode(params)}"
        payload, _, _ = self._request_json(url)
        raw = self._rows(payload).drop(columns=["_close_time"], errors="ignore")
        frame, _ = normalize_ohlcv(raw, timeframe, drop_incomplete=True)
        return frame

    def download_history(
        self,
        symbol: str,
        timeframe: str,
        start: pd.Timestamp | str,
        end: pd.Timestamp | str | None,
        destination: str | Path,
        *,
        metadata_path: str | Path | None = None,
        resume: bool = True,
        progress_every_pages: int = 25,
    ) -> dict[str, Any]:
        """Download closed klines to an auditable, resumable local CSV."""
        symbol = symbol.upper()
        if timeframe not in self._INTERVALS:
            raise ValueError(f"Unsupported Binance timeframe: {timeframe}")
        requested_start = self._utc_timestamp(start)
        requested_end = self._utc_timestamp(end)
        now = pd.Timestamp.now(tz="UTC")
        effective_end = min(requested_end, now)
        interval_ms = self._INTERVAL_MILLISECONDS[timeframe]
        interval = pd.Timedelta(milliseconds=interval_ms)
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        metadata_destination = (
            Path(metadata_path)
            if metadata_path is not None
            else destination.with_suffix(".metadata.json")
        )
        partial = destination.with_suffix(destination.suffix + ".partial")

        if not resume:
            partial.unlink(missing_ok=True)
        elif not partial.exists() and destination.exists():
            shutil.copyfile(destination, partial)

        existing_rows = 0
        cursor = requested_start
        if partial.exists() and partial.stat().st_size > 0:
            existing = pd.read_csv(partial, usecols=["timestamp"])
            parsed = pd.to_datetime(existing["timestamp"], utc=True, errors="raise")
            existing_rows = len(parsed)
            if not parsed.empty:
                earliest = parsed.min()
                if earliest > requested_start + interval:
                    partial.unlink()
                    existing_rows = 0
                else:
                    cursor = max(requested_start, parsed.max() + interval)

        request_count = 0
        retry_count = 0
        downloaded_rows = 0
        max_weight_seen = 0
        started_at = datetime.now(timezone.utc).isoformat()
        progress: dict[str, Any] = {
            "status": "downloading",
            "provider": "binance_public_market_data",
            "base_url": self.base_url,
            "endpoint": "/api/v3/klines",
            "symbol": symbol,
            "timeframe": timeframe,
            "requested_start_utc": requested_start.isoformat(),
            "requested_end_utc": requested_end.isoformat(),
            "effective_end_utc": effective_end.isoformat(),
            "started_at_utc": started_at,
            "resume_enabled": resume,
            "existing_rows": existing_rows,
            "uses_api_key": False,
            "trading_permissions": False,
        }
        metadata_destination.parent.mkdir(parents=True, exist_ok=True)
        metadata_destination.write_text(
            json.dumps(progress, indent=2), encoding="utf-8"
        )

        while cursor < effective_end:
            params = {
                "symbol": symbol,
                "interval": self._INTERVALS[timeframe],
                "startTime": int(cursor.timestamp() * 1000),
                "endTime": int(effective_end.timestamp() * 1000) - 1,
                "limit": 1000,
            }
            url = f"{self.base_url}/api/v3/klines?{urllib.parse.urlencode(params)}"
            payload, headers, retries = self._request_json(url)
            request_count += 1
            retry_count += retries
            weight = int(headers.get("x-mbx-used-weight-1m", "0") or 0)
            max_weight_seen = max(max_weight_seen, weight)
            if not payload:
                break
            page = self._rows(payload)
            page = page[page["_close_time"] < now].drop(columns=["_close_time"])
            if page.empty:
                break
            page.to_csv(
                partial,
                mode="a",
                header=not partial.exists() or partial.stat().st_size == 0,
                index=False,
            )
            downloaded_rows += len(page)
            next_cursor = page["timestamp"].iloc[-1] + interval
            if next_cursor <= cursor:
                raise RuntimeError("Binance pagination did not advance")
            cursor = next_cursor
            if request_count % progress_every_pages == 0:
                progress.update(
                    {
                        "requests": request_count,
                        "retries": retry_count,
                        "downloaded_rows": downloaded_rows,
                        "last_open_time_utc": page["timestamp"].iloc[-1].isoformat(),
                    }
                )
                metadata_destination.write_text(
                    json.dumps(progress, indent=2), encoding="utf-8"
                )
            if self.request_pause_seconds > 0:
                time.sleep(self.request_pause_seconds)
            if len(payload) < 1000:
                break

        if not partial.exists():
            raise RuntimeError("Binance returned no closed candles for the requested range")
        raw = pd.read_csv(partial)
        source_rows = len(raw)
        parsed_timestamp = pd.to_datetime(raw["timestamp"], utc=True, errors="raise")
        source_ordered = bool(parsed_timestamp.is_monotonic_increasing)
        source_duplicates = int(parsed_timestamp.duplicated().sum())
        normalized, incomplete_dropped = normalize_ohlcv(
            raw,
            timeframe,
            drop_incomplete=True,
            reference_time=now,
        )
        normalized = normalized[
            (normalized["timestamp"] >= requested_start)
            & (normalized["timestamp"] < effective_end)
        ].reset_index(drop=True)
        quality = validate_ohlcv(
            normalized,
            timeframe,
            asset_class="crypto",
            timezone="UTC",
            incomplete_candle_dropped=incomplete_dropped,
        )
        normalized.to_csv(destination, index=False)
        partial.unlink(missing_ok=True)
        digest = _sha256_file(destination)
        completed = {
            **progress,
            "status": "complete",
            "completed_at_utc": datetime.now(timezone.utc).isoformat(),
            "requests": request_count,
            "retries": retry_count,
            "max_reported_weight_1m": max_weight_seen,
            "source_rows": source_rows,
            "final_rows": len(normalized),
            "downloaded_rows": downloaded_rows,
            "duplicates_removed": source_duplicates,
            "source_temporal_order_valid": source_ordered,
            "first_open_time_utc": (
                normalized["timestamp"].iloc[0].isoformat()
                if not normalized.empty
                else None
            ),
            "last_open_time_utc": (
                normalized["timestamp"].iloc[-1].isoformat()
                if not normalized.empty
                else None
            ),
            "missing_bars": len(quality.missing_bars),
            "quality_valid": quality.is_valid,
            "incomplete_candle_dropped": incomplete_dropped,
            "sha256": digest,
            "file_bytes": destination.stat().st_size,
        }
        metadata_destination.write_text(
            json.dumps(completed, indent=2), encoding="utf-8"
        )
        return completed

    def _download_archive_file(self, url: str, destination: Path) -> Path | None:
        if destination.exists() and destination.stat().st_size > 0:
            return destination
        destination.parent.mkdir(parents=True, exist_ok=True)
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "DayTrade-Lab/0.2 research-only"},
            method="GET",
        )
        for retry in range(self.max_retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=60) as response:
                    payload = response.read()
                with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                    if archive.testzip() is not None:
                        raise RuntimeError(f"Corrupt Binance archive: {url}")
                temporary = destination.with_suffix(".zip.tmp")
                temporary.write_bytes(payload)
                temporary.replace(destination)
                return destination
            except HTTPError as exc:
                if exc.code == 404:
                    return None
                if exc.code not in {418, 429, 500, 502, 503, 504}:
                    raise
                if retry >= self.max_retries:
                    raise
                retry_after = exc.headers.get("Retry-After")
                delay = (
                    float(retry_after)
                    if retry_after
                    else min(60.0, 2**retry + random.random())
                )
            except (URLError, TimeoutError, zipfile.BadZipFile):
                if retry >= self.max_retries:
                    raise
                delay = min(60.0, 2**retry + random.random())
            time.sleep(delay)
        return None

    @staticmethod
    def _read_archive(path: Path) -> pd.DataFrame:
        columns = [
            "timestamp",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "_close_time",
        ]
        with zipfile.ZipFile(path) as archive:
            members = [name for name in archive.namelist() if name.endswith(".csv")]
            if len(members) != 1:
                raise RuntimeError(f"Unexpected archive contents: {path}")
            with archive.open(members[0]) as handle:
                frame = pd.read_csv(
                    handle,
                    header=None,
                    usecols=range(7),
                    names=columns,
                )
        numeric_open = pd.to_numeric(frame["timestamp"], errors="raise")
        numeric_close = pd.to_numeric(frame["_close_time"], errors="raise")
        # Binance Spot archive timestamps changed from milliseconds to
        # microseconds starting in 2025. Detect the unit per archive.
        unit = "us" if float(numeric_open.median()) > 100_000_000_000_000 else "ms"
        frame["timestamp"] = pd.to_datetime(numeric_open, unit=unit, utc=True)
        frame["_close_time"] = pd.to_datetime(numeric_close, unit=unit, utc=True)
        return frame

    def download_history_archives(
        self,
        symbol: str,
        timeframe: str,
        start: pd.Timestamp | str,
        end: pd.Timestamp | str | None,
        destination: str | Path,
        *,
        metadata_path: str | Path | None = None,
        workers: int = 8,
    ) -> dict[str, Any]:
        """Bootstrap monthly Binance public archives, then fill the tail via REST."""
        symbol = symbol.upper()
        if timeframe not in self._INTERVALS:
            raise ValueError(f"Unsupported Binance timeframe: {timeframe}")
        requested_start = self._utc_timestamp(start)
        requested_end = min(self._utc_timestamp(end), pd.Timestamp.now(tz="UTC"))
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        metadata_destination = (
            Path(metadata_path)
            if metadata_path is not None
            else destination.with_suffix(".metadata.json")
        )
        cache = destination.parent / ".archive_cache"
        interval_code = self._INTERVALS[timeframe]
        interval = pd.Timedelta(milliseconds=self._INTERVAL_MILLISECONDS[timeframe])
        first_month = requested_start.tz_localize(None).to_period("M")
        end_month = requested_end.tz_localize(None).to_period("M")
        archive_months = list(pd.period_range(first_month, end_month - 1, freq="M"))
        archive_specs = []
        for month in archive_months:
            filename = f"{symbol}-{interval_code}-{month.year}-{month.month:02d}.zip"
            url = (
                "https://data.binance.vision/data/spot/monthly/klines/"
                f"{symbol}/{interval_code}/{filename}"
            )
            archive_specs.append((month, url, cache / filename))

        started_at = datetime.now(timezone.utc).isoformat()
        downloaded: dict[pd.Period, Path] = {}
        missing_archives: list[str] = []
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            futures = {
                pool.submit(self._download_archive_file, url, path): (month, url)
                for month, url, path in archive_specs
            }
            for future in as_completed(futures):
                month, url = futures[future]
                result = future.result()
                if result is None:
                    missing_archives.append(str(month))
                else:
                    downloaded[month] = result

        frames = [
            self._read_archive(downloaded[month])
            for month in sorted(downloaded)
        ]
        archive_rows = sum(len(frame) for frame in frames)
        tail_start = requested_start
        if frames:
            tail_start = max(
                requested_start,
                frames[-1]["timestamp"].iloc[-1] + interval,
            )
        api_requests = 0
        api_retries = 0
        cursor = tail_start
        now = pd.Timestamp.now(tz="UTC")
        while cursor < requested_end:
            params = {
                "symbol": symbol,
                "interval": interval_code,
                "startTime": int(cursor.timestamp() * 1000),
                "endTime": int(requested_end.timestamp() * 1000) - 1,
                "limit": 1000,
            }
            url = f"{self.base_url}/api/v3/klines?{urllib.parse.urlencode(params)}"
            payload, _, retries = self._request_json(url)
            api_requests += 1
            api_retries += retries
            if not payload:
                break
            page = self._rows(payload)
            page = page[page["_close_time"] < now]
            if page.empty:
                break
            frames.append(page)
            next_cursor = page["timestamp"].iloc[-1] + interval
            if next_cursor <= cursor:
                raise RuntimeError("Binance tail pagination did not advance")
            cursor = next_cursor
            if len(payload) < 1000:
                break
            if self.request_pause_seconds > 0:
                time.sleep(self.request_pause_seconds)

        if not frames:
            raise RuntimeError("Binance returned no public data for the requested range")
        combined = pd.concat(frames, ignore_index=True)
        combined = combined[
            (combined["timestamp"] >= requested_start)
            & (combined["timestamp"] < requested_end)
            & (combined["_close_time"] < now)
        ]
        source_rows = len(combined)
        source_duplicates = int(combined["timestamp"].duplicated().sum())
        source_ordered = bool(combined["timestamp"].is_monotonic_increasing)
        normalized, incomplete_dropped = normalize_ohlcv(
            combined.drop(columns=["_close_time"]),
            timeframe,
            drop_incomplete=True,
            reference_time=now,
        )
        quality = validate_ohlcv(
            normalized,
            timeframe,
            asset_class="crypto",
            timezone="UTC",
            incomplete_candle_dropped=incomplete_dropped,
        )
        normalized.to_csv(destination, index=False)
        destination.with_suffix(destination.suffix + ".partial").unlink(
            missing_ok=True
        )
        digest = _sha256_file(destination)
        metadata = {
            "status": "complete",
            "provider": "binance_public_market_data",
            "download_method": "monthly_public_archives_plus_paginated_rest_tail",
            "archive_base_url": "https://data.binance.vision/data/spot/monthly/klines",
            "rest_base_url": self.base_url,
            "rest_endpoint": "/api/v3/klines",
            "symbol": symbol,
            "timeframe": timeframe,
            "requested_start_utc": requested_start.isoformat(),
            "requested_end_utc": requested_end.isoformat(),
            "started_at_utc": started_at,
            "completed_at_utc": datetime.now(timezone.utc).isoformat(),
            "archive_months_requested": len(archive_months),
            "archive_months_loaded": len(downloaded),
            "missing_archive_months": sorted(missing_archives),
            "archive_rows": archive_rows,
            "rest_tail_start_utc": tail_start.isoformat(),
            "rest_requests": api_requests,
            "rest_retries": api_retries,
            "source_rows": source_rows,
            "final_rows": len(normalized),
            "duplicates_removed": source_duplicates,
            "source_temporal_order_valid": source_ordered,
            "first_open_time_utc": normalized["timestamp"].iloc[0].isoformat(),
            "last_open_time_utc": normalized["timestamp"].iloc[-1].isoformat(),
            "missing_bars": len(quality.missing_bars),
            "quality_valid": quality.is_valid,
            "incomplete_candle_dropped": incomplete_dropped,
            "sha256": digest,
            "file_bytes": destination.stat().st_size,
            "uses_api_key": False,
            "trading_permissions": False,
        }
        metadata_destination.write_text(
            json.dumps(metadata, indent=2), encoding="utf-8"
        )
        return metadata


def save_local(frame: pd.DataFrame, path: str | Path) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(destination, index=False)
    return destination
