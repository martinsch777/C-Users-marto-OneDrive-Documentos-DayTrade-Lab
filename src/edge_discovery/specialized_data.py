from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd


PUBLIC_HOSTS = {"fapi.binance.com", "api.bybit.com"}


def parse_funding_payload(payload: Any, provider: str) -> pd.DataFrame:
    if provider == "binance":
        records = payload
        time_key, rate_key = "fundingTime", "fundingRate"
    elif provider == "bybit":
        records = payload.get("result", {}).get("list", [])
        time_key, rate_key = "fundingRateTimestamp", "fundingRate"
    else:
        raise ValueError(f"Unsupported provider: {provider}")
    frame = pd.DataFrame(records)
    if frame.empty:
        return pd.DataFrame(columns=["timestamp", "funding_rate", "symbol"])
    required = {time_key, rate_key}
    if not required.issubset(frame.columns):
        raise ValueError(f"Funding payload missing {sorted(required - set(frame))}")
    result = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(
                pd.to_numeric(frame[time_key], errors="raise"),
                unit="ms",
                utc=True,
            ),
            "funding_rate": pd.to_numeric(frame[rate_key], errors="raise"),
            "symbol": frame.get("symbol", ""),
        }
    )
    return result.sort_values("timestamp").drop_duplicates("timestamp")


def parse_open_interest_payload(payload: Any, provider: str) -> pd.DataFrame:
    if provider == "binance":
        records = payload if isinstance(payload, list) else [payload]
        time_key = "timestamp" if records and "timestamp" in records[0] else "time"
        value_candidates = ("sumOpenInterest", "openInterest")
    elif provider == "bybit":
        records = payload.get("result", {}).get("list", [])
        time_key = "timestamp"
        value_candidates = ("openInterest",)
    else:
        raise ValueError(f"Unsupported provider: {provider}")
    frame = pd.DataFrame(records)
    if frame.empty:
        return pd.DataFrame(columns=["timestamp", "open_interest", "symbol"])
    value_key = next(
        (candidate for candidate in value_candidates if candidate in frame.columns),
        None,
    )
    if time_key not in frame or value_key is None:
        raise ValueError("Open-interest payload has no supported time/value fields")
    result = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(
                pd.to_numeric(frame[time_key], errors="raise"),
                unit="ms",
                utc=True,
            ),
            "open_interest": pd.to_numeric(frame[value_key], errors="raise"),
            "symbol": frame.get("symbol", ""),
        }
    )
    return result.sort_values("timestamp").drop_duplicates("timestamp")


class PublicSpecializedDataClient:
    """GET-only public market data client. It has no order or account methods."""

    def __init__(self, transport=None) -> None:
        self.transport = transport or self._get_json

    @staticmethod
    def _get_json(url: str) -> Any:
        request = Request(url, headers={"User-Agent": "DayTrade-Lab-Research/1.0"})
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))

    def binance_funding(
        self,
        symbol: str,
        start_ms: int,
        *,
        limit: int = 1000,
    ) -> pd.DataFrame:
        query = urlencode(
            {"symbol": symbol, "startTime": int(start_ms), "limit": int(limit)}
        )
        payload = self.transport(
            f"https://fapi.binance.com/fapi/v1/fundingRate?{query}"
        )
        return parse_funding_payload(payload, "binance")

    def bybit_open_interest(
        self,
        symbol: str,
        *,
        interval: str = "5min",
        cursor: str = "",
    ) -> tuple[pd.DataFrame, str]:
        params = {
            "category": "linear",
            "symbol": symbol,
            "intervalTime": interval,
            "limit": 200,
        }
        if cursor:
            params["cursor"] = cursor
        payload = self.transport(
            f"https://api.bybit.com/v5/market/open-interest?{urlencode(params)}"
        )
        frame = parse_open_interest_payload(payload, "bybit")
        next_cursor = str(
            payload.get("result", {}).get("nextPageCursor", "")
        )
        return frame, next_cursor


class BinanceFundingAdapter:
    provider = "binance"

    def __init__(self, client: PublicSpecializedDataClient | None = None) -> None:
        self.client = client or PublicSpecializedDataClient()

    def fetch_page(self, symbol: str, start_ms: int) -> pd.DataFrame:
        return self.client.binance_funding(symbol, start_ms, limit=1000)


class BybitOpenInterestAdapter:
    provider = "bybit"

    def __init__(self, client: PublicSpecializedDataClient | None = None) -> None:
        self.client = client or PublicSpecializedDataClient()

    def fetch_page(
        self,
        symbol: str,
        *,
        interval: str = "5min",
        cursor: str = "",
    ) -> tuple[pd.DataFrame, str]:
        return self.client.bybit_open_interest(
            symbol,
            interval=interval,
            cursor=cursor,
        )


def save_specialized_frame(frame: pd.DataFrame, path: str | Path) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(destination, index=False)
    return destination


def download_binance_funding_history(
    symbol: str,
    start: str,
    end: str,
    *,
    client: PublicSpecializedDataClient | None = None,
) -> pd.DataFrame:
    service = client or PublicSpecializedDataClient()
    cursor = int(pd.Timestamp(start, tz="UTC").timestamp() * 1000)
    end_ms = int(pd.Timestamp(end, tz="UTC").timestamp() * 1000)
    pages = []
    while cursor <= end_ms:
        page = service.binance_funding(symbol, cursor, limit=1000)
        if page.empty:
            break
        page = page[page["timestamp"] <= pd.to_datetime(end_ms, unit="ms", utc=True)]
        if page.empty:
            break
        pages.append(page)
        next_cursor = int(page["timestamp"].max().timestamp() * 1000) + 1
        if next_cursor <= cursor:
            raise RuntimeError("Funding pagination did not advance")
        cursor = next_cursor
        if len(page) < 1000:
            break
    if not pages:
        return pd.DataFrame(columns=["timestamp", "funding_rate", "symbol"])
    return (
        pd.concat(pages, ignore_index=True)
        .drop_duplicates("timestamp")
        .sort_values("timestamp")
        .reset_index(drop=True)
    )


def download_bybit_open_interest_history(
    symbol: str,
    *,
    interval: str = "5min",
    max_pages: int = 10_000,
    client: PublicSpecializedDataClient | None = None,
) -> pd.DataFrame:
    service = client or PublicSpecializedDataClient()
    cursor = ""
    pages = []
    seen: set[str] = set()
    for _ in range(max_pages):
        page, next_cursor = service.bybit_open_interest(
            symbol,
            interval=interval,
            cursor=cursor,
        )
        if not page.empty:
            pages.append(page)
        if not next_cursor or next_cursor in seen:
            break
        seen.add(next_cursor)
        cursor = next_cursor
    else:
        raise RuntimeError("Bybit OI pagination exceeded max_pages")
    if not pages:
        return pd.DataFrame(columns=["timestamp", "open_interest", "symbol"])
    return (
        pd.concat(pages, ignore_index=True)
        .drop_duplicates("timestamp")
        .sort_values("timestamp")
        .reset_index(drop=True)
    )
