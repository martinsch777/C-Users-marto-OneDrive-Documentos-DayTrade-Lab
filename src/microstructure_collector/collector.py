from __future__ import annotations

import io
import json
import time
from collections import Counter, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from src.bybit_diagnostics import (
    classify_websocket_exception,
    sanitize_message,
)

from .book import OrderBookState
from .parsers import parse_bybit_message
from .stability import (
    StabilityMetrics,
    build_stability_report,
    reconnect_backoff,
    write_stability_report,
)


BYBIT_PUBLIC_LINEAR = "wss://stream.bybit.com/v5/public/linear"
TOPIC_TEMPLATES = {
    "ticker": "tickers.{symbol}",
    "trades": "publicTrade.{symbol}",
    "orderbook": "orderbook.50.{symbol}",
    "liquidation": "allLiquidation.{symbol}",
    "kline": "kline.1.{symbol}",
}
RAW_COLUMNS = {
    "orderbook": [
        "received_at_utc",
        "exchange_timestamp_utc",
        "latency_ms",
        "symbol",
        "message_type",
        "update_id",
        "sequence",
        "sequence_gap",
        "best_bid",
        "best_ask",
        "mid_price",
        "spread_bps",
        "bid_depth_quote_l5",
        "ask_depth_quote_l5",
        "imbalance_l5",
        "bid_depth_quote_l10",
        "ask_depth_quote_l10",
        "imbalance_l10",
        "bid_depth_quote_l25",
        "ask_depth_quote_l25",
        "imbalance_l25",
        "bid_depth_quote_l50",
        "ask_depth_quote_l50",
        "imbalance_l50",
    ],
    "trade": [
        "received_at_utc",
        "exchange_timestamp_utc",
        "latency_ms",
        "symbol",
        "trade_id",
        "side",
        "price",
        "size",
        "tick_direction",
    ],
    "ticker": [
        "received_at_utc",
        "exchange_timestamp_utc",
        "latency_ms",
        "symbol",
        "best_bid",
        "best_ask",
        "spread_bps",
        "mark_price",
        "index_price",
        "funding_rate",
        "open_interest",
    ],
    "liquidation": [
        "received_at_utc",
        "exchange_timestamp_utc",
        "latency_ms",
        "symbol",
        "liquidated_position_side",
        "size",
        "bankruptcy_price",
        "liquidation_notional",
    ],
    "kline": [
        "received_at_utc",
        "exchange_timestamp_utc",
        "latency_ms",
        "symbol",
        "start_utc",
        "end_utc",
        "interval",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "confirmed",
    ],
}


def _write_empty(path: Path, columns: list[str]) -> None:
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(columns=columns).to_csv(path, index=False)


def initialize_collector_outputs(
    output_root: str | Path = "outputs/microstructure_collector",
) -> Path:
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    schemas = {
        "collector_status.csv": [
            "timestamp_utc",
            "status",
            "symbols",
            "messages",
            "reconnects",
            "errors",
            "last_error_code",
            "error_code_counts",
            "subscription_acknowledged",
            "topics",
            "rest_requests_ok",
            "rest_requests_failed",
            "websocket_connected",
            "websocket_subscription_acknowledged",
            "websocket_messages_received",
            "websocket_messages_persisted",
            "websocket_errors",
            "websocket_reconnects",
            "fallback_rest_messages_received",
            "total_messages_received",
            "files_written",
            "messages_by_topic",
            "persisted_by_topic",
            "first_message_at",
            "last_message_at",
            "orders_sent",
            "broker_connected",
            "api_keys_used",
        ],
        "data_quality.csv": [
            "kind",
            "messages",
            "duplicates",
            "sequence_gaps",
            "mean_latency_ms",
            "max_latency_ms",
        ],
        "spread_summary.csv": [
            "symbol",
            "observations",
            "mean_spread_bps",
            "p50_spread_bps",
            "p95_spread_bps",
            "max_spread_bps",
        ],
        "orderbook_imbalance_summary.csv": [
            "symbol",
            "observations",
            "mean_imbalance_l5",
            "p05_imbalance_l5",
            "p95_imbalance_l5",
            "mean_imbalance_l25",
        ],
        "liquidation_events.csv": RAW_COLUMNS["liquidation"],
        "funding_oi_snapshots.csv": RAW_COLUMNS["ticker"],
    }
    for name, columns in schemas.items():
        _write_empty(root / name, columns)
    if (root / "collector_status.csv").stat().st_size <= 1:
        pass
    status = pd.read_csv(root / "collector_status.csv")
    if status.empty:
        pd.DataFrame(
            [
                {
                    "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                    "status": "not_started_default_safe_state",
                    "symbols": "",
                    "messages": 0,
                    "reconnects": 0,
                    "errors": 0,
                    "last_error_code": "",
                    "error_code_counts": "{}",
                    "subscription_acknowledged": False,
                    "topics": "",
                    "rest_requests_ok": 0,
                    "rest_requests_failed": 0,
                    "websocket_connected": 0,
                    "websocket_subscription_acknowledged": False,
                    "websocket_messages_received": 0,
                    "websocket_messages_persisted": 0,
                    "websocket_errors": 0,
                    "websocket_reconnects": 0,
                    "fallback_rest_messages_received": 0,
                    "total_messages_received": 0,
                    "files_written": 0,
                    "messages_by_topic": "{}",
                    "persisted_by_topic": "{}",
                    "first_message_at": "",
                    "last_message_at": "",
                    "orders_sent": False,
                    "broker_connected": False,
                    "api_keys_used": False,
                }
            ]
        ).to_csv(root / "collector_status.csv", index=False)
    return root


class BybitMicrostructureCollector:
    """Public Bybit market stream collector; no account/trading methods."""

    def __init__(
        self,
        symbols: tuple[str, ...],
        *,
        data_root: str | Path = "data/forward_microstructure/bybit",
        output_root: str | Path = "outputs/microstructure_collector",
        log_root: str | Path = "logs/microstructure_collector",
        enabled_topics: tuple[str, ...] = tuple(TOPIC_TEMPLATES),
        recv_timeout_seconds: float = 5.0,
        subscription_timeout_seconds: float = 15.0,
        no_data_timeout_seconds: float = 30.0,
        max_reconnect_backoff_seconds: float = 60.0,
        stable_reset_seconds: float = 60.0,
    ) -> None:
        self.symbols = tuple(symbols)
        unknown = sorted(set(enabled_topics) - set(TOPIC_TEMPLATES))
        if unknown:
            raise ValueError(f"Unknown public topic groups: {unknown}")
        if not enabled_topics:
            raise ValueError("At least one public topic group must be enabled")
        self.enabled_topics = tuple(dict.fromkeys(enabled_topics))
        self.recv_timeout_seconds = float(recv_timeout_seconds)
        self.subscription_timeout_seconds = float(
            subscription_timeout_seconds
        )
        self.no_data_timeout_seconds = float(no_data_timeout_seconds)
        self.max_reconnect_backoff_seconds = float(
            max_reconnect_backoff_seconds
        )
        self.stable_reset_seconds = float(stable_reset_seconds)
        self.endpoint = BYBIT_PUBLIC_LINEAR
        self.data_root = Path(data_root)
        self.output_root = initialize_collector_outputs(output_root)
        self.log_root = Path(log_root)
        self.log_root.mkdir(parents=True, exist_ok=True)
        self.books = {symbol: OrderBookState(symbol) for symbol in self.symbols}
        self.counts: Counter[str] = Counter()
        self.duplicates: Counter[str] = Counter()
        self.latencies: dict[str, list[float]] = {}
        self.reconnects = 0
        self.errors = 0
        self.rest_requests_ok = 0
        self.rest_requests_failed = 0
        self.websocket_connected = 0
        self.websocket_messages_received = 0
        self.websocket_messages_persisted = 0
        self.fallback_rest_messages_received = 0
        self.messages_by_topic: Counter[str] = Counter()
        self.persisted_by_topic: Counter[str] = Counter()
        self.files_written: set[str] = set()
        self.first_message_at: str | None = None
        self.last_message_at: str | None = None
        self.error_codes: Counter[str] = Counter()
        self.last_error_code = ""
        self.subscription_acknowledged = False
        self._seen: set[tuple] = set()
        self._seen_order: deque[tuple] = deque()
        self.max_seen = 200_000
        self._load_existing_dedupe_keys()

    def topics(self) -> list[str]:
        result: list[str] = []
        for symbol in self.symbols:
            for name in self.enabled_topics:
                result.append(TOPIC_TEMPLATES[name].format(symbol=symbol))
        return result

    def subscription_message(self) -> dict[str, Any]:
        return {"op": "subscribe", "args": self.topics()}

    def _log(self, error_code: str, message: str) -> None:
        path = self.log_root / "collector.log"
        with path.open("a", encoding="utf-8") as stream:
            stream.write(
                f"{datetime.now(timezone.utc).isoformat()} "
                f"code={error_code or 'INFO'} {sanitize_message(message)}\n"
            )

    def _record_error(self, error_code: str, message: str) -> None:
        self.errors += 1
        self.error_codes[error_code] += 1
        self.last_error_code = error_code
        self._log(error_code, message)

    def _dedupe_key(self, event: dict) -> tuple:
        kind = event["kind"]
        if kind == "orderbook":
            return (kind, event["symbol"], event["sequence"])
        if kind == "trade":
            return (kind, event["symbol"], event["trade_id"])
        if kind == "liquidation":
            return (
                kind,
                event["symbol"],
                event["exchange_timestamp_ms"],
                event["liquidated_position_side"],
                event["size"],
                event["bankruptcy_price"],
            )
        if kind == "kline":
            return (kind, event["symbol"], event["start_ms"], event["confirmed"])
        return (kind, event["symbol"], event["exchange_timestamp_ms"])

    def _is_duplicate(self, key: tuple) -> bool:
        if key in self._seen:
            return True
        self._remember_key(key)
        return False

    def _remember_key(self, key: tuple) -> None:
        self._seen.add(key)
        self._seen_order.append(key)
        if len(self._seen_order) > self.max_seen:
            self._seen.discard(self._seen_order.popleft())

    @staticmethod
    def _utc_to_ms(value: Any) -> int:
        return int(pd.Timestamp(value).value // 1_000_000)

    def _dedupe_key_from_row(self, kind: str, row: dict[str, Any]) -> tuple:
        symbol = str(row["symbol"])
        if kind == "orderbook":
            return (kind, symbol, int(row["sequence"]))
        if kind == "trade":
            return (kind, symbol, str(row["trade_id"]))
        if kind == "liquidation":
            return (
                kind,
                symbol,
                self._utc_to_ms(row["exchange_timestamp_utc"]),
                str(row["liquidated_position_side"]),
                float(row["size"]),
                float(row["bankruptcy_price"]),
            )
        if kind == "kline":
            confirmed = str(row["confirmed"]).strip().lower() in {
                "1",
                "true",
                "yes",
            }
            return (
                kind,
                symbol,
                self._utc_to_ms(row["start_utc"]),
                confirmed,
            )
        return (
            kind,
            symbol,
            self._utc_to_ms(row["exchange_timestamp_utc"]),
        )

    def _load_existing_dedupe_keys(self) -> None:
        """Seed bounded deduplication state from prior collector sessions."""
        if not self.data_root.exists():
            return
        keys_per_kind = max(1, self.max_seen // len(RAW_COLUMNS))
        for kind in RAW_COLUMNS:
            path = self.data_root / f"{kind}.csv"
            if not path.exists() or path.stat().st_size == 0:
                continue
            try:
                with path.open("r", encoding="utf-8", newline="") as stream:
                    header = stream.readline()
                    tail = deque(stream, maxlen=keys_per_kind)
                if not header or not tail:
                    continue
                frame = pd.read_csv(io.StringIO(header + "".join(tail)))
                for row in frame.to_dict("records"):
                    self._remember_key(
                        self._dedupe_key_from_row(kind, row)
                    )
            except Exception as exc:
                self._log(
                    "DEDUPE_HISTORY_LOAD_FAILED",
                    f"{path.name} {type(exc).__name__}: {exc}",
                )

    @staticmethod
    def _append(path: Path, row: dict, columns: list[str]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame([{column: row.get(column) for column in columns}]).to_csv(
            path,
            mode="a",
            header=not path.exists(),
            index=False,
        )

    def process_payload(
        self,
        payload: dict[str, Any],
        *,
        received_at_ms: int | None = None,
    ) -> int:
        events = parse_bybit_message(payload)
        return self._process_events(events, received_at_ms=received_at_ms)

    def _process_events(
        self,
        events: list[dict[str, Any]],
        *,
        received_at_ms: int | None = None,
    ) -> int:
        received_ms = received_at_ms or int(time.time() * 1000)
        written = 0
        for event in events:
            kind = event["kind"]
            key = self._dedupe_key(event)
            if self._is_duplicate(key):
                self.duplicates[kind] += 1
                continue
            exchange_ms = int(event["exchange_timestamp_ms"])
            common = {
                "received_at_utc": pd.to_datetime(
                    received_ms, unit="ms", utc=True
                ).isoformat(),
                "exchange_timestamp_utc": pd.to_datetime(
                    exchange_ms, unit="ms", utc=True
                ).isoformat(),
                "latency_ms": max(0, received_ms - exchange_ms),
                "symbol": event["symbol"],
            }
            row = {**common, **event}
            if kind == "orderbook":
                gap = self.books[event["symbol"]].update(event)
                try:
                    metrics = self.books[event["symbol"]].metrics()
                except ValueError as exc:
                    self._record_error(
                        "WEBSOCKET_PERSISTENCE_ERROR",
                        f"invalid_book {event['symbol']} {exc}",
                    )
                    continue
                row.update(metrics)
                row["sequence_gap"] = gap
            elif kind == "ticker":
                bid, ask = event.get("best_bid"), event.get("best_ask")
                row["spread_bps"] = (
                    (ask - bid) / ((ask + bid) / 2) * 10_000
                    if bid and ask and ask > bid
                    else None
                )
            elif kind == "liquidation":
                row["liquidation_notional"] = (
                    event["size"] * event["bankruptcy_price"]
                )
            elif kind == "kline":
                row["start_utc"] = pd.to_datetime(
                    event["start_ms"], unit="ms", utc=True
                ).isoformat()
                row["end_utc"] = pd.to_datetime(
                    event["end_ms"], unit="ms", utc=True
                ).isoformat()
            try:
                raw_path = self.data_root / f"{kind}.csv"
                self._append(
                    raw_path,
                    row,
                    RAW_COLUMNS[kind],
                )
                self.files_written.add(str(raw_path.resolve()))
                if kind == "liquidation":
                    liquidation_path = (
                        self.output_root / "liquidation_events.csv"
                    )
                    self._append(
                        liquidation_path,
                        row,
                        RAW_COLUMNS[kind],
                    )
                    self.files_written.add(str(liquidation_path.resolve()))
                if kind == "ticker":
                    funding_path = (
                        self.output_root / "funding_oi_snapshots.csv"
                    )
                    self._append(
                        funding_path,
                        row,
                        RAW_COLUMNS[kind],
                    )
                    self.files_written.add(str(funding_path.resolve()))
            except Exception as exc:
                self._record_error(
                    "WEBSOCKET_PERSISTENCE_ERROR",
                    f"{type(exc).__name__}: {exc}",
                )
                raise
            self.counts[kind] += 1
            topic = str(event.get("topic", kind))
            self.persisted_by_topic[topic] += 1
            self.websocket_messages_persisted += 1
            self.latencies.setdefault(kind, []).append(common["latency_ms"])
            written += 1
        return written

    def stability_metrics(self) -> StabilityMetrics:
        return StabilityMetrics(
            rest_requests_ok=self.rest_requests_ok,
            rest_requests_failed=self.rest_requests_failed,
            websocket_connected=self.websocket_connected,
            websocket_subscription_acknowledged=(
                self.subscription_acknowledged
            ),
            websocket_messages_received=self.websocket_messages_received,
            websocket_messages_persisted=self.websocket_messages_persisted,
            websocket_errors=self.errors,
            websocket_reconnects=self.reconnects,
            fallback_rest_messages_received=(
                self.fallback_rest_messages_received
            ),
            total_messages_received=(
                self.websocket_messages_received
                + self.fallback_rest_messages_received
            ),
            files_written=len(self.files_written),
            messages_by_topic=dict(self.messages_by_topic),
            persisted_by_topic=dict(self.persisted_by_topic),
            first_message_at=self.first_message_at,
            last_message_at=self.last_message_at,
            last_error_code=self.last_error_code,
        )

    def write_stability_report(self, duration_seconds: float) -> Path:
        report = build_stability_report(
            self.stability_metrics(),
            duration_seconds=duration_seconds,
            topics=self.topics(),
        )
        return write_stability_report(
            report,
            self.output_root / "websocket_stability_report.json",
        )

    def write_quality_reports(self, status: str) -> None:
        quality = []
        for kind in RAW_COLUMNS:
            latency = self.latencies.get(kind, [])
            quality.append(
                {
                    "kind": kind,
                    "messages": self.counts[kind],
                    "duplicates": self.duplicates[kind],
                    "sequence_gaps": (
                        sum(book.gap_count for book in self.books.values())
                        if kind == "orderbook"
                        else 0
                    ),
                    "mean_latency_ms": (
                        sum(latency) / len(latency) if latency else None
                    ),
                    "max_latency_ms": max(latency) if latency else None,
                }
            )
        pd.DataFrame(quality).to_csv(
            self.output_root / "data_quality.csv", index=False
        )
        book_path = self.data_root / "orderbook.csv"
        if book_path.exists() and book_path.stat().st_size > 0:
            book = pd.read_csv(book_path)
            spread = (
                book.groupby("symbol")["spread_bps"]
                .agg(
                    observations="count",
                    mean_spread_bps="mean",
                    p50_spread_bps="median",
                    p95_spread_bps=lambda x: x.quantile(0.95),
                    max_spread_bps="max",
                )
                .reset_index()
            )
            spread.to_csv(
                self.output_root / "spread_summary.csv", index=False
            )
            imbalance = (
                book.groupby("symbol")
                .agg(
                    observations=("imbalance_l5", "count"),
                    mean_imbalance_l5=("imbalance_l5", "mean"),
                    p05_imbalance_l5=(
                        "imbalance_l5",
                        lambda x: x.quantile(0.05),
                    ),
                    p95_imbalance_l5=(
                        "imbalance_l5",
                        lambda x: x.quantile(0.95),
                    ),
                    mean_imbalance_l25=("imbalance_l25", "mean"),
                )
                .reset_index()
            )
            imbalance.to_csv(
                self.output_root / "orderbook_imbalance_summary.csv",
                index=False,
            )
        pd.DataFrame(
            [
                {
                    "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                    "status": status,
                    "symbols": ";".join(self.symbols),
                    "messages": sum(self.counts.values()),
                    "reconnects": self.reconnects,
                    "errors": self.errors,
                    "last_error_code": self.last_error_code,
                    "error_code_counts": json.dumps(
                        dict(self.error_codes), sort_keys=True
                    ),
                    "subscription_acknowledged": self.subscription_acknowledged,
                    "topics": ";".join(self.topics()),
                    "rest_requests_ok": self.rest_requests_ok,
                    "rest_requests_failed": self.rest_requests_failed,
                    "websocket_connected": self.websocket_connected,
                    "websocket_subscription_acknowledged": (
                        self.subscription_acknowledged
                    ),
                    "websocket_messages_received": (
                        self.websocket_messages_received
                    ),
                    "websocket_messages_persisted": (
                        self.websocket_messages_persisted
                    ),
                    "websocket_errors": self.errors,
                    "websocket_reconnects": self.reconnects,
                    "fallback_rest_messages_received": (
                        self.fallback_rest_messages_received
                    ),
                    "total_messages_received": (
                        self.websocket_messages_received
                        + self.fallback_rest_messages_received
                    ),
                    "files_written": len(self.files_written),
                    "messages_by_topic": json.dumps(
                        dict(self.messages_by_topic), sort_keys=True
                    ),
                    "persisted_by_topic": json.dumps(
                        dict(self.persisted_by_topic), sort_keys=True
                    ),
                    "first_message_at": self.first_message_at or "",
                    "last_message_at": self.last_message_at or "",
                    "orders_sent": False,
                    "broker_connected": False,
                    "api_keys_used": False,
                }
            ]
        ).to_csv(self.output_root / "collector_status.csv", index=False)

    @staticmethod
    def _close_details(exc: BaseException) -> tuple[Any, Any]:
        received = getattr(exc, "rcvd", None)
        code = getattr(received, "code", getattr(exc, "code", ""))
        reason = getattr(received, "reason", getattr(exc, "reason", ""))
        return code, reason

    @staticmethod
    def _subscription_control(payload: dict[str, Any]) -> str:
        if payload.get("op") == "subscribe":
            return (
                "rejected"
                if payload.get("success") is False
                else "acknowledged"
            )
        if payload.get("type") == "COMMAND_RESP":
            data = payload.get("data", {})
            if data.get("failTopics"):
                return "rejected"
            if data.get("successTopics"):
                return "acknowledged"
        return ""

    def run(self, duration_seconds: int) -> None:
        try:
            from websockets.sync.client import connect  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "Install requirements.txt to enable the public WebSocket collector"
            ) from exc

        started = time.monotonic()
        deadline = started + duration_seconds
        reconnect_attempt = 0
        self.write_quality_reports("starting")

        while time.monotonic() < deadline:
            connection_started = time.monotonic()
            connected = False
            data_since_connect = 0
            self.subscription_acknowledged = False
            recorded_in_connection: set[str] = set()
            try:
                with connect(
                    self.endpoint,
                    additional_headers={
                        "User-Agent": "DayTrade-Lab-Research/1.0"
                    },
                    open_timeout=10,
                    close_timeout=5,
                    ping_interval=20,
                    ping_timeout=20,
                ) as connection:
                    connected = True
                    self.websocket_connected += 1
                    connection_started = time.monotonic()
                    connection_acknowledged = False
                    data_since_connect = 0
                    first_message_logged = False
                    no_ack_logged = False
                    no_data_logged = False
                    recv_timeout_logged = False
                    last_application_ping = time.monotonic()
                    requested_topics = self.topics()
                    connection.send(
                        json.dumps(self.subscription_message())
                    )
                    self._log(
                        "",
                        f"websocket_connected endpoint={self.endpoint} "
                        f"topics={json.dumps(requested_topics)}",
                    )

                    while time.monotonic() < deadline:
                        now = time.monotonic()
                        elapsed = now - connection_started
                        if (
                            not connection_acknowledged
                            and data_since_connect > 0
                            and elapsed >= self.subscription_timeout_seconds
                            and not no_ack_logged
                        ):
                            code = "WEBSOCKET_CONNECTED_NO_ACK"
                            self._record_error(
                                code,
                                "Market data arrived before a subscription ACK",
                            )
                            recorded_in_connection.add(code)
                            no_ack_logged = True
                        if now - last_application_ping >= 20:
                            connection.send(
                                json.dumps(
                                    {
                                        "req_id": "daytrade-lab-keepalive",
                                        "op": "ping",
                                    }
                                )
                            )
                            last_application_ping = now
                            self._log("", "application_ping_sent")
                        try:
                            raw = connection.recv(
                                timeout=min(
                                    self.recv_timeout_seconds,
                                    max(0.1, deadline - now),
                                )
                            )
                        except TimeoutError:
                            elapsed = time.monotonic() - connection_started
                            if not recv_timeout_logged:
                                self._log(
                                    "WEBSOCKET_RECV_TIMEOUT",
                                    "No frame during one receive interval; "
                                    "connection kept open",
                                )
                                recv_timeout_logged = True
                            if (
                                not connection_acknowledged
                                and elapsed
                                >= self.subscription_timeout_seconds
                            ):
                                if data_since_connect > 0:
                                    if not no_ack_logged:
                                        code = "WEBSOCKET_CONNECTED_NO_ACK"
                                        self._record_error(
                                            code,
                                            "Market data arrived before a "
                                            "subscription ACK",
                                        )
                                        recorded_in_connection.add(code)
                                        no_ack_logged = True
                                else:
                                    code = "WEBSOCKET_SUBSCRIPTION_TIMEOUT"
                                    self._record_error(
                                        code,
                                        "No ACK or market data before "
                                        "subscription timeout",
                                    )
                                    recorded_in_connection.add(code)
                                    raise RuntimeError(code)
                            if (
                                connection_acknowledged
                                and data_since_connect == 0
                                and elapsed >= self.no_data_timeout_seconds
                                and not no_data_logged
                            ):
                                self._log(
                                    "WEBSOCKET_CONNECTED_NO_DATA",
                                    "Subscription ACK received but no market "
                                    "data yet; connection kept open",
                                )
                                no_data_logged = True
                            continue

                        if not raw:
                            continue
                        if not first_message_logged:
                            self._log(
                                "",
                                "first_message="
                                + sanitize_message(raw)[:2000],
                            )
                            first_message_logged = True
                        try:
                            payload = json.loads(raw)
                        except Exception as exc:
                            code = "WEBSOCKET_PARSE_ERROR"
                            self._record_error(
                                code,
                                f"{type(exc).__name__}: {exc}; "
                                f"payload={sanitize_message(raw)[:500]}",
                            )
                            recorded_in_connection.add(code)
                            continue

                        control = self._subscription_control(payload)
                        if control == "rejected":
                            code = "WEBSOCKET_SUBSCRIPTION_REJECTED"
                            self._record_error(
                                code,
                                f"response={sanitize_message(payload)}",
                            )
                            recorded_in_connection.add(code)
                            raise RuntimeError(code)
                        if control == "acknowledged":
                            connection_acknowledged = True
                            self.subscription_acknowledged = True
                            self._log(
                                "",
                                "subscription_acknowledged "
                                f"response={sanitize_message(payload)}",
                            )
                            continue
                        if payload.get("op") in {"ping", "pong"}:
                            self._log(
                                "",
                                f"pong_received op={payload.get('op')}",
                            )
                            continue

                        topic = str(payload.get("topic", ""))
                        if not topic:
                            continue
                        observed_at = datetime.now(timezone.utc).isoformat()
                        if self.first_message_at is None:
                            self.first_message_at = observed_at
                        self.last_message_at = observed_at
                        self.websocket_messages_received += 1
                        self.messages_by_topic[topic] += 1
                        data_since_connect += 1

                        try:
                            parsed = parse_bybit_message(payload)
                        except Exception as exc:
                            code = "WEBSOCKET_PARSE_ERROR"
                            self._record_error(
                                code,
                                f"topic={topic} {type(exc).__name__}: {exc}",
                            )
                            recorded_in_connection.add(code)
                            continue
                        try:
                            self._process_events(parsed)
                        except Exception as exc:
                            code = "WEBSOCKET_PERSISTENCE_ERROR"
                            if self.last_error_code != code:
                                self._record_error(
                                    code,
                                    f"topic={topic} "
                                    f"{type(exc).__name__}: {exc}",
                                )
                            recorded_in_connection.add(code)
                            continue
                    self._log(
                        "",
                        "websocket_client_close_requested close_code=1000 "
                        "close_reason=duration_complete",
                    )

            except Exception as exc:
                if time.monotonic() >= deadline:
                    break
                error_code = str(exc)
                known = {
                    "WEBSOCKET_SUBSCRIPTION_REJECTED",
                    "WEBSOCKET_SUBSCRIPTION_TIMEOUT",
                }
                if error_code not in known:
                    stage = "recv" if connected else "connect"
                    error_code = classify_websocket_exception(exc, stage)
                    self._record_error(
                        error_code,
                        f"{type(exc).__name__}: {exc}",
                    )
                code, reason = self._close_details(exc)
                self._log(
                    error_code,
                    f"connection_closed close_code={code} "
                    f"close_reason={reason} exception="
                    f"{type(exc).__name__}: {exc}",
                )
                self.reconnects += 1
                connected_for = time.monotonic() - connection_started
                if (
                    connected_for >= self.stable_reset_seconds
                    and data_since_connect > 0
                ):
                    reconnect_attempt = 0
                delay = reconnect_backoff(
                    reconnect_attempt,
                    self.max_reconnect_backoff_seconds,
                )
                reconnect_attempt += 1
                self._log(
                    "",
                    f"reconnect_scheduled delay_seconds={delay} "
                    f"attempt={reconnect_attempt}",
                )
                time.sleep(
                    min(delay, max(0, deadline - time.monotonic()))
                )

        final_status = (
            "completed"
            if self.websocket_messages_persisted > 0
            else "blocked_no_market_data_received"
        )
        self._log(
            "",
            "run_summary "
            f"messages_by_topic={json.dumps(dict(self.messages_by_topic))} "
            f"persisted_by_topic="
            f"{json.dumps(dict(self.persisted_by_topic))}",
        )
        self.write_quality_reports(final_status)
        self.write_stability_report(time.monotonic() - started)
