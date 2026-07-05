from __future__ import annotations

import importlib.metadata
import json
import os
import platform
import re
import socket
import ssl
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen


ERROR_CODES = {
    "DNS_FAILED",
    "HTTPS_BLOCKED",
    "TCP_443_BLOCKED",
    "TLS_HANDSHAKE_FAILED",
    "WEBSOCKET_HANDSHAKE_FAILED",
    "SUBSCRIPTION_REJECTED",
    "SUBSCRIPTION_OK_NO_DATA",
    "DATA_RECEIVED_BUT_NOT_PERSISTED",
    "FILE_WRITE_FAILED",
    "UNKNOWN_NETWORK_ERROR",
    "WEBSOCKET_CONNECT_FAILED",
    "WEBSOCKET_SUBSCRIPTION_REJECTED",
    "WEBSOCKET_SUBSCRIPTION_TIMEOUT",
    "WEBSOCKET_CONNECTED_NO_ACK",
    "WEBSOCKET_CONNECTED_NO_DATA",
    "WEBSOCKET_RECV_TIMEOUT",
    "WEBSOCKET_CLOSED_BY_REMOTE",
    "WEBSOCKET_PARSE_ERROR",
    "WEBSOCKET_PERSISTENCE_ERROR",
    "REST_FALLBACK_OK",
    "REST_FALLBACK_FAILED",
}

SECRET_PATTERN = re.compile(
    r"(?i)(api[_-]?key|api[_-]?secret|secret|token|authorization)"
    r"\s*[:=]\s*([^\s,;]+)"
)
BEARER_PATTERN = re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+")


def sanitize_message(value: Any) -> str:
    text = str(value)
    text = SECRET_PATTERN.sub(lambda match: f"{match.group(1)}=<redacted>", text)
    return BEARER_PATTERN.sub("Bearer <redacted>", text)


def classify_exception(exc: BaseException, stage: str) -> str:
    stage = stage.lower()
    if stage == "dns" or isinstance(exc, socket.gaierror):
        return "DNS_FAILED"
    if isinstance(exc, PermissionError) and stage in {"tcp", "websocket"}:
        return "TCP_443_BLOCKED"
    if stage == "file":
        return "FILE_WRITE_FAILED"
    if stage == "tls" or isinstance(exc, ssl.SSLError):
        return "TLS_HANDSHAKE_FAILED"
    if stage == "https" or isinstance(exc, (HTTPError, URLError)):
        return "HTTPS_BLOCKED"
    if stage == "tcp":
        return "TCP_443_BLOCKED"
    if stage in {"websocket", "subscription"}:
        return "WEBSOCKET_HANDSHAKE_FAILED"
    return "UNKNOWN_NETWORK_ERROR"


def classify_websocket_exception(
    exc: BaseException,
    stage: str,
) -> str:
    """Classify collector failures by the lifecycle stage that actually failed."""
    stage = stage.lower()
    name = type(exc).__name__.lower()
    message = str(exc).lower()
    if stage == "subscription_rejected":
        return "WEBSOCKET_SUBSCRIPTION_REJECTED"
    if stage == "subscription_timeout":
        return "WEBSOCKET_SUBSCRIPTION_TIMEOUT"
    if stage == "parse":
        return "WEBSOCKET_PARSE_ERROR"
    if stage in {"persist", "persistence"}:
        return "WEBSOCKET_PERSISTENCE_ERROR"
    if stage == "recv":
        if isinstance(exc, TimeoutError):
            return "WEBSOCKET_RECV_TIMEOUT"
        if (
            "connectionclosed" in name
            or "closed" in message
            or "close frame" in message
        ):
            return "WEBSOCKET_CLOSED_BY_REMOTE"
        return "WEBSOCKET_CLOSED_BY_REMOTE"
    if stage == "connect":
        if (
            "invalidstatus" in name
            or "invalidhandshake" in name
            or "handshake" in message
            or "upgrade" in message
            or "http 4" in message
            or "http 5" in message
        ):
            return "WEBSOCKET_HANDSHAKE_FAILED"
        return "WEBSOCKET_CONNECT_FAILED"
    return "UNKNOWN_NETWORK_ERROR"


@dataclass(frozen=True)
class DiagnosticResult:
    test: str
    target: str
    status: str
    error_code: str
    latency_ms: float | None
    details: str

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


def _success(test: str, target: str, started: float, details: Any) -> DiagnosticResult:
    return DiagnosticResult(
        test,
        target,
        "PASS",
        "",
        round((time.perf_counter() - started) * 1000, 3),
        sanitize_message(details),
    )


def _failure(
    test: str,
    target: str,
    started: float,
    exc: BaseException,
    stage: str,
) -> DiagnosticResult:
    return DiagnosticResult(
        test,
        target,
        "FAIL",
        classify_exception(exc, stage),
        round((time.perf_counter() - started) * 1000, 3),
        sanitize_message(f"{type(exc).__name__}: {exc}"),
    )


def diagnose_dns(host: str) -> DiagnosticResult:
    started = time.perf_counter()
    try:
        addresses = sorted(
            {
                record[4][0]
                for record in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
            }
        )
        return _success("dns", host, started, f"addresses={addresses}")
    except Exception as exc:
        return _failure("dns", host, started, exc, "dns")


def diagnose_tcp(host: str, timeout: float) -> DiagnosticResult:
    started = time.perf_counter()
    try:
        with socket.create_connection((host, 443), timeout=timeout):
            return _success("tcp_443", f"{host}:443", started, "connected")
    except Exception as exc:
        return _failure("tcp_443", f"{host}:443", started, exc, "tcp")


def diagnose_tls(host: str, timeout: float) -> DiagnosticResult:
    started = time.perf_counter()
    try:
        context = ssl.create_default_context()
        with socket.create_connection((host, 443), timeout=timeout) as raw:
            with context.wrap_socket(raw, server_hostname=host) as secured:
                details = {
                    "version": secured.version(),
                    "cipher": secured.cipher()[0] if secured.cipher() else "",
                    "peer_subject": dict(
                        item[0] for item in secured.getpeercert().get("subject", [])
                    ),
                }
        return _success("tls_handshake", host, started, json.dumps(details))
    except Exception as exc:
        return _failure("tls_handshake", host, started, exc, "tls")


def _public_json_get(url: str, timeout: float) -> Any:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "api.bybit.com":
        raise ValueError("Only public api.bybit.com HTTPS endpoints are allowed")
    request = Request(
        url,
        method="GET",
        headers={"User-Agent": "DayTrade-Lab-Diagnostics/1.0"},
    )
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def diagnose_https(timeout: float) -> DiagnosticResult:
    target = "https://api.bybit.com/v5/market/time"
    started = time.perf_counter()
    try:
        payload = _public_json_get(target, timeout)
        if payload.get("retCode") != 0:
            raise RuntimeError(f"Bybit retCode={payload.get('retCode')}")
        return _success(
            "https_server_time",
            target,
            started,
            f"server_time_ms={payload.get('time')}",
        )
    except Exception as exc:
        return _failure("https_server_time", target, started, exc, "https")


class BybitRestFallback:
    """Public GET-only diagnostics. It exposes no account or order endpoints."""

    BASE = "https://api.bybit.com"

    def __init__(self, transport=None, *, timeout: float = 10.0) -> None:
        self.transport = transport or (
            lambda url: _public_json_get(url, timeout)
        )

    @staticmethod
    def endpoints(symbol: str) -> dict[str, str]:
        common = {"category": "linear", "symbol": symbol}
        return {
            "server_time": "/v5/market/time",
            "tickers": f"/v5/market/tickers?{urlencode(common)}",
            "open_interest": (
                "/v5/market/open-interest?"
                + urlencode({**common, "intervalTime": "5min", "limit": 1})
            ),
            "funding_history": (
                "/v5/market/funding/history?"
                + urlencode({**common, "limit": 1})
            ),
            "recent_trades": (
                "/v5/market/recent-trade?"
                + urlencode({**common, "limit": 1})
            ),
        }

    def probe(self, symbol: str) -> list[DiagnosticResult]:
        results = []
        for name, path in self.endpoints(symbol).items():
            url = f"{self.BASE}{path}"
            started = time.perf_counter()
            try:
                payload = self.transport(url)
                if payload.get("retCode") != 0:
                    raise RuntimeError(
                        f"retCode={payload.get('retCode')} retMsg={payload.get('retMsg')}"
                    )
                data = payload.get("result", {})
                size = len(data.get("list", [])) if isinstance(data, dict) else 0
                results.append(
                    DiagnosticResult(
                        f"rest_{name}",
                        url,
                        "PASS",
                        "REST_FALLBACK_OK",
                        round(
                            (time.perf_counter() - started) * 1000, 3
                        ),
                        f"retCode=0 records={size}",
                    )
                )
            except Exception as exc:
                results.append(
                    DiagnosticResult(
                        f"rest_{name}",
                        url,
                        "FAIL",
                        "REST_FALLBACK_FAILED",
                        round(
                            (time.perf_counter() - started) * 1000, 3
                        ),
                        sanitize_message(
                            f"{type(exc).__name__}: {exc}"
                        ),
                    )
                )
        return results


def diagnose_websocket(
    symbol: str,
    timeout: float,
    *,
    persistence_path: str | Path,
) -> DiagnosticResult:
    target = "wss://stream.bybit.com/v5/public/linear"
    started = time.perf_counter()
    try:
        from websockets.sync.client import connect  # type: ignore

        with connect(
            target,
            additional_headers={"User-Agent": "DayTrade-Lab-Diagnostics/1.0"},
            open_timeout=timeout,
            close_timeout=min(timeout, 5),
        ) as connection:
            connection.send(
                json.dumps({"op": "subscribe", "args": [f"tickers.{symbol}"]})
            )
            deadline = time.monotonic() + timeout
            subscription_ok = False
            while time.monotonic() < deadline:
                remaining = max(0.1, deadline - time.monotonic())
                try:
                    raw = connection.recv(timeout=remaining)
                except TimeoutError:
                    break
                payload = json.loads(raw)
                if payload.get("op") == "subscribe":
                    if payload.get("success") is False:
                        return DiagnosticResult(
                            "websocket_subscription",
                            target,
                            "FAIL",
                            "WEBSOCKET_SUBSCRIPTION_REJECTED",
                            round((time.perf_counter() - started) * 1000, 3),
                            sanitize_message(payload.get("ret_msg", payload)),
                        )
                    subscription_ok = True
                    continue
                if payload.get("topic") == f"tickers.{symbol}":
                    try:
                        path = Path(persistence_path)
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_text(
                            json.dumps(
                                {
                                    "topic": payload["topic"],
                                    "received_at_utc": time.time(),
                                    "api_keys_used": False,
                                    "orders_sent": False,
                                },
                                indent=2,
                            ),
                            encoding="utf-8",
                        )
                    except Exception as exc:
                        return DiagnosticResult(
                            "websocket_persistence",
                            str(persistence_path),
                            "FAIL",
                            "DATA_RECEIVED_BUT_NOT_PERSISTED",
                            round((time.perf_counter() - started) * 1000, 3),
                            sanitize_message(f"{type(exc).__name__}: {exc}"),
                        )
                    if subscription_ok:
                        return _success(
                            "websocket_subscription",
                            target,
                            started,
                            "subscription_ok=true data_received=true",
                        )
                    return DiagnosticResult(
                        "websocket_subscription",
                        target,
                        "WARN",
                        "WEBSOCKET_CONNECTED_NO_ACK",
                        round(
                            (time.perf_counter() - started) * 1000, 3
                        ),
                        "Market data arrived before a subscription ACK.",
                    )
            if subscription_ok:
                return DiagnosticResult(
                    "websocket_subscription",
                    target,
                    "WARN",
                    "SUBSCRIPTION_OK_NO_DATA",
                    round((time.perf_counter() - started) * 1000, 3),
                    "Subscription accepted but no ticker data arrived before timeout.",
                )
            return DiagnosticResult(
                "websocket_subscription",
                target,
                "FAIL",
                "WEBSOCKET_CONNECTED_NO_ACK",
                round((time.perf_counter() - started) * 1000, 3),
                "Connected but no subscription acknowledgement was received.",
            )
    except Exception as exc:
        return DiagnosticResult(
            "websocket_connection",
            target,
            "FAIL",
            classify_websocket_exception(exc, "connect"),
            round((time.perf_counter() - started) * 1000, 3),
            sanitize_message(f"{type(exc).__name__}: {exc}"),
        )


def diagnose_write(path: str | Path) -> DiagnosticResult:
    target = Path(path)
    started = time.perf_counter()
    probe = target / ".diagnostic_write_probe.tmp"
    try:
        target.mkdir(parents=True, exist_ok=True)
        probe.write_text("public-data-write-probe", encoding="utf-8")
        probe.unlink()
        return _success("filesystem_write", str(target.resolve()), started, "write/delete ok")
    except Exception as exc:
        return _failure("filesystem_write", str(target), started, exc, "file")


def environment_report() -> dict[str, Any]:
    relevant = (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "NO_PROXY",
        "ALL_PROXY",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "REQUESTS_CA_BUNDLE",
        "BYBIT_API_KEY",
        "BYBIT_API_SECRET",
        "API_KEY",
        "API_SECRET",
    )
    environment = {
        name: (
            f"<set:length={len(os.environ[name])}>"
            if os.environ.get(name)
            else "<unset>"
        )
        for name in relevant
    }
    packages = {}
    for name in ("websockets", "websocket-client", "aiohttp"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = "<not-installed>"
    return {
        "python_version": sys.version.split()[0],
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "packages": packages,
        "environment_redacted": environment,
        "path_entry_count": len(os.environ.get("PATH", "").split(os.pathsep)),
        "private_values_logged": False,
    }


def write_diagnostic_report(
    results: list[DiagnosticResult],
    environment: dict[str, Any],
    destination: str | Path,
) -> Path:
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "results": [result.to_record() for result in results],
        "environment": environment,
        "safety": {
            "api_keys_used": False,
            "broker_connected": False,
            "orders_sent": False,
            "live_trading_enabled": False,
            "paper_internal_enabled": False,
            "paper_broker_enabled": False,
            "real_leverage_used": False,
        },
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path
