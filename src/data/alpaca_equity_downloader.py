from __future__ import annotations

import hashlib
import json
import os
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

import pandas as pd

from .sessions import EquitySessionCalendar


ALPACA_MARKET_DATA_BASE_URL = "https://data.alpaca.markets/v2/stocks"
SUPPORTED_SYMBOLS = {"QQQ", "SPY"}
SUPPORTED_FEEDS = {"sip", "iex"}
SUPPORTED_ADJUSTMENTS = {"raw", "split", "dividend", "all"}
MAX_LIMIT = 10_000


class AlpacaDownloadError(RuntimeError):
    def __init__(self, code: str, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


@dataclass(frozen=True)
class DownloadRequest:
    symbol: str
    start: str
    end: str
    interval: str = "1min"
    feed: str = "sip"
    adjustment: str = "raw"
    output_dir: str | Path = Path("data/raw")
    source_timezone: str = "America/New_York"
    rth_only: bool = False
    limit: int = MAX_LIMIT
    range_filenames: bool = False
    overwrite: bool = False


@dataclass(frozen=True)
class DownloadResult:
    symbol: str
    provider: str
    feed: str
    interval: str
    adjustment: str
    start: str
    end: str
    rows: int
    first_timestamp: str
    last_timestamp: str
    output_file: str
    sha256: str
    rth_only: bool
    pages_downloaded: int
    dry_run: bool = False
    audit_apt_for_or_fvg_backtest: bool | None = None
    audit_critical_warnings: list[str] | None = None

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


class EquityIntradayDownloader(ABC):
    @abstractmethod
    def download(self, request: DownloadRequest) -> DownloadResult:
        raise NotImplementedError


def _sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def download_output_filename(
    request: DownloadRequest,
    *,
    provider: str = "alpaca",
) -> str:
    if not request.range_filenames:
        return f"{request.symbol.upper()}_{request.interval}.csv"
    session_scope = "rth" if request.rth_only else "all"
    return (
        f"{request.symbol.upper()}_{request.interval}_{request.start}_{request.end}_"
        f"{provider}_{request.feed}_{request.adjustment}_{session_scope}.csv"
    )


def download_output_path(
    request: DownloadRequest,
    *,
    provider: str = "alpaca",
) -> Path:
    return Path(request.output_dir) / download_output_filename(
        request,
        provider=provider,
    )


def _as_alpaca_datetime(value: str, *, end: bool = False) -> str:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        if len(str(value)) == 10:
            suffix = "23:59:59Z" if end else "00:00:00Z"
            return f"{value}T{suffix}"
        timestamp = timestamp.tz_localize("UTC")
    return timestamp.tz_convert("UTC").isoformat().replace("+00:00", "Z")


def validate_download_request(request: DownloadRequest) -> None:
    if request.symbol.upper() not in SUPPORTED_SYMBOLS:
        raise AlpacaDownloadError(
            "UNSUPPORTED_SYMBOL",
            f"Only {sorted(SUPPORTED_SYMBOLS)} are supported for this workflow.",
        )
    if request.interval != "1min":
        raise AlpacaDownloadError("UNSUPPORTED_INTERVAL", "Only interval=1min is supported.")
    if request.feed not in SUPPORTED_FEEDS:
        raise AlpacaDownloadError("UNSUPPORTED_FEED", "Feed must be sip or iex.")
    if request.adjustment not in SUPPORTED_ADJUSTMENTS:
        raise AlpacaDownloadError(
            "UNSUPPORTED_ADJUSTMENT",
            "Adjustment must be raw, split, dividend, or all.",
        )
    if pd.Timestamp(request.start) > pd.Timestamp(request.end):
        raise AlpacaDownloadError("INVALID_DATE_RANGE", "start must be <= end.")


class AlpacaEquityIntradayDownloader(EquityIntradayDownloader):
    """Alpaca Market Data downloader only; no Trading API/account/order surface."""

    def __init__(
        self,
        *,
        api_key_id: str | None = None,
        api_secret_key: str | None = None,
        request_json: Callable[[str, dict[str, str]], dict[str, Any]] | None = None,
    ) -> None:
        self.api_key_id = api_key_id if api_key_id is not None else os.getenv("APCA_API_KEY_ID")
        self.api_secret_key = (
            api_secret_key
            if api_secret_key is not None
            else os.getenv("APCA_API_SECRET_KEY")
        )
        self._request_json = request_json or self._urllib_request_json
        self.last_urls: list[str] = []
        self.last_headers: list[dict[str, str]] = []

    def validate_credentials(self) -> None:
        if not self.api_key_id:
            raise AlpacaDownloadError(
                "APCA_API_KEY_ID_MISSING",
                "Missing environment variable APCA_API_KEY_ID.",
            )
        if not self.api_secret_key:
            raise AlpacaDownloadError(
                "APCA_API_SECRET_KEY_MISSING",
                "Missing environment variable APCA_API_SECRET_KEY.",
            )

    def endpoint_for(self, symbol: str) -> str:
        return f"{ALPACA_MARKET_DATA_BASE_URL}/{symbol.upper()}/bars"

    def build_url(
        self,
        request: DownloadRequest,
        *,
        page_token: str | None = None,
    ) -> str:
        params: dict[str, str | int] = {
            "timeframe": "1Min",
            "start": _as_alpaca_datetime(request.start),
            "end": _as_alpaca_datetime(request.end, end=True),
            "limit": min(int(request.limit), MAX_LIMIT),
            "adjustment": request.adjustment,
            "feed": request.feed,
        }
        if page_token:
            params["page_token"] = page_token
        return f"{self.endpoint_for(request.symbol)}?{urlencode(params)}"

    def headers(self) -> dict[str, str]:
        self.validate_credentials()
        return {
            "APCA-API-KEY-ID": str(self.api_key_id),
            "APCA-API-SECRET-KEY": str(self.api_secret_key),
            "Accept": "application/json",
        }

    def dry_run(self, request: DownloadRequest) -> DownloadResult:
        validate_download_request(request)
        destination = download_output_path(request)
        return DownloadResult(
            symbol=request.symbol.upper(),
            provider="alpaca",
            feed=request.feed,
            interval=request.interval,
            adjustment=request.adjustment,
            start=request.start,
            end=request.end,
            rows=0,
            first_timestamp="",
            last_timestamp="",
            output_file=str(destination),
            sha256="",
            rth_only=request.rth_only,
            pages_downloaded=0,
            dry_run=True,
        )

    def download(self, request: DownloadRequest) -> DownloadResult:
        validate_download_request(request)
        output_dir = Path(request.output_dir)
        destination = download_output_path(request)
        if destination.exists() and not request.overwrite:
            raise AlpacaDownloadError(
                "OUTPUT_FILE_ALREADY_EXISTS",
                f"Output file already exists: {destination}",
            )
        headers = self.headers()
        page_token: str | None = None
        seen_tokens: set[str] = set()
        bars: list[dict[str, Any]] = []
        pages = 0

        while True:
            if page_token:
                if page_token in seen_tokens:
                    raise AlpacaDownloadError(
                        "ALPACA_PAGE_TOKEN_LOOP_DETECTED",
                        f"Repeated page_token detected for {request.symbol}.",
                    )
                seen_tokens.add(page_token)
            url = self.build_url(request, page_token=page_token)
            self.last_urls.append(url)
            self.last_headers.append({key: ("***" if "SECRET" in key else value) for key, value in headers.items()})
            payload = self._request_json(url, headers)
            pages += 1
            page_bars = payload.get("bars", [])
            if not isinstance(page_bars, list):
                raise AlpacaDownloadError(
                    "ALPACA_INVALID_RESPONSE",
                    "Alpaca response did not contain a bars list.",
                )
            bars.extend(page_bars)
            next_token = payload.get("next_page_token")
            if not next_token:
                break
            page_token = str(next_token)

        frame = normalize_alpaca_bars(
            bars,
            source_timezone=request.source_timezone,
            rth_only=request.rth_only,
        )
        output_dir.mkdir(parents=True, exist_ok=True)
        frame.to_csv(destination, index=False)
        digest = _sha256_file(destination)
        first = str(frame.iloc[0]["timestamp"]) if not frame.empty else ""
        last = str(frame.iloc[-1]["timestamp"]) if not frame.empty else ""
        return DownloadResult(
            symbol=request.symbol.upper(),
            provider="alpaca",
            feed=request.feed,
            interval=request.interval,
            adjustment=request.adjustment,
            start=request.start,
            end=request.end,
            rows=len(frame),
            first_timestamp=first,
            last_timestamp=last,
            output_file=str(destination),
            sha256=digest,
            rth_only=request.rth_only,
            pages_downloaded=pages,
        )

    def _urllib_request_json(self, url: str, headers: dict[str, str]) -> dict[str, Any]:
        try:
            request = Request(url, headers=headers, method="GET")
            with urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise classify_alpaca_http_error(exc.code, body) from exc
        except URLError as exc:
            raise AlpacaDownloadError("ALPACA_NETWORK_ERROR", str(exc)) from exc


def classify_alpaca_http_error(status: int, body: str) -> AlpacaDownloadError:
    lowered = body.lower()
    if status in {401, 403}:
        if "sip" in lowered and ("subscription" in lowered or "not authorized" in lowered):
            return AlpacaDownloadError(
                "ALPACA_SIP_SUBSCRIPTION_REQUIRED",
                "SIP data requires the right Alpaca market data subscription. "
                "Use --feed iex only for pipeline tests, not final consolidated datasets.",
                status=status,
            )
        return AlpacaDownloadError(
            "ALPACA_AUTH_FAILED",
            "Alpaca authentication/authorization failed. Check API keys and data subscription.",
            status=status,
        )
    if status == 429:
        return AlpacaDownloadError(
            "ALPACA_RATE_LIMIT",
            "Alpaca rate limit reached; retry later or reduce request size.",
            status=status,
        )
    return AlpacaDownloadError(
        "ALPACA_HTTP_ERROR",
        f"Alpaca Market Data HTTP error {status}.",
        status=status,
    )


def normalize_alpaca_bars(
    bars: list[dict[str, Any]],
    *,
    source_timezone: str = "America/New_York",
    rth_only: bool = False,
) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    local_zone = ZoneInfo(source_timezone)
    for bar in bars:
        timestamp = pd.Timestamp(bar["t"])
        if timestamp.tzinfo is None:
            timestamp = timestamp.tz_localize("UTC")
        local_timestamp = timestamp.tz_convert(local_zone)
        records.append(
            {
                "timestamp": local_timestamp.isoformat(sep=" "),
                "open": bar["o"],
                "high": bar["h"],
                "low": bar["l"],
                "close": bar["c"],
                "volume": bar["v"],
            }
        )
    frame = pd.DataFrame(
        records,
        columns=["timestamp", "open", "high", "low", "close", "volume"],
    )
    if frame.empty:
        return frame
    parsed = pd.to_datetime(frame["timestamp"], utc=True)
    frame["_timestamp_utc"] = parsed
    frame = (
        frame.sort_values("_timestamp_utc")
        .drop_duplicates(subset=["_timestamp_utc"], keep="last")
        .reset_index(drop=True)
    )
    if rth_only:
        calendar = EquitySessionCalendar.from_config({"source": "us_equity"})
        keep = frame["_timestamp_utc"].map(calendar.contains)
        frame = frame.loc[keep].reset_index(drop=True)
    return frame.loc[:, ["timestamp", "open", "high", "low", "close", "volume"]]
