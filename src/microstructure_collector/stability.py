from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PASS_WEBSOCKET_STABLE = "PASS_WEBSOCKET_STABLE"
PASS_REST_ONLY_FALLBACK = "PASS_REST_ONLY_FALLBACK"
FAIL_WEBSOCKET_UNSTABLE = "FAIL_WEBSOCKET_UNSTABLE"
FAIL_NO_MARKET_DATA = "FAIL_NO_MARKET_DATA"


def reconnect_backoff(attempt: int, maximum_seconds: float = 60.0) -> float:
    schedule = (1.0, 2.0, 5.0, 10.0)
    if attempt < len(schedule):
        value = schedule[max(0, attempt)]
    else:
        value = schedule[-1] * (2 ** (attempt - len(schedule) + 1))
    return min(float(maximum_seconds), value)


@dataclass
class StabilityMetrics:
    rest_requests_ok: int = 0
    rest_requests_failed: int = 0
    websocket_connected: int = 0
    websocket_subscription_acknowledged: bool = False
    websocket_messages_received: int = 0
    websocket_messages_persisted: int = 0
    websocket_errors: int = 0
    websocket_reconnects: int = 0
    fallback_rest_messages_received: int = 0
    total_messages_received: int = 0
    files_written: int = 0
    messages_by_topic: dict[str, int] = field(default_factory=dict)
    persisted_by_topic: dict[str, int] = field(default_factory=dict)
    first_message_at: str | None = None
    last_message_at: str | None = None
    last_error_code: str = ""


def classify_stability(
    metrics: StabilityMetrics,
    *,
    maximum_reconnects: int = 2,
    maximum_errors: int = 2,
) -> str:
    websocket_has_data = (
        metrics.websocket_messages_received > 0
        or metrics.websocket_messages_persisted > 0
    )
    websocket_stable = (
        metrics.websocket_messages_received > 0
        and metrics.websocket_messages_persisted > 0
        and metrics.websocket_subscription_acknowledged
        and metrics.websocket_reconnects <= maximum_reconnects
        and metrics.websocket_errors <= maximum_errors
    )
    if websocket_stable:
        return PASS_WEBSOCKET_STABLE
    if websocket_has_data:
        return FAIL_WEBSOCKET_UNSTABLE
    if (
        metrics.fallback_rest_messages_received > 0
        or metrics.rest_requests_ok > 0
    ):
        return PASS_REST_ONLY_FALLBACK
    return FAIL_NO_MARKET_DATA


def _json_object(value: Any) -> dict[str, int]:
    if isinstance(value, dict):
        return {str(key): int(item) for key, item in value.items()}
    if value in (None, "", "nan"):
        return {}
    try:
        parsed = json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {str(key): int(item) for key, item in parsed.items()}


def _as_int(row: dict[str, Any], name: str, fallback: str | None = None) -> int:
    raw = row.get(name)
    if raw in (None, "") and fallback:
        raw = row.get(fallback)
    try:
        return int(float(raw or 0))
    except (TypeError, ValueError):
        return 0


def _as_bool(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes"}


def metrics_from_status(path: str | Path) -> StabilityMetrics:
    with Path(path).open("r", encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    if not rows:
        return StabilityMetrics()
    row = rows[-1]
    websocket_received = _as_int(
        row, "websocket_messages_received", "messages"
    )
    websocket_connected = _as_int(row, "websocket_connected")
    if (
        "websocket_connected" not in row
        and websocket_received > 0
    ):
        websocket_connected = 1
    return StabilityMetrics(
        rest_requests_ok=_as_int(row, "rest_requests_ok"),
        rest_requests_failed=_as_int(row, "rest_requests_failed"),
        websocket_connected=websocket_connected,
        websocket_subscription_acknowledged=_as_bool(
            row.get(
                "websocket_subscription_acknowledged",
                row.get("subscription_acknowledged", False),
            )
        ),
        websocket_messages_received=websocket_received,
        websocket_messages_persisted=_as_int(
            row, "websocket_messages_persisted", "messages"
        ),
        websocket_errors=_as_int(row, "websocket_errors", "errors"),
        websocket_reconnects=_as_int(
            row, "websocket_reconnects", "reconnects"
        ),
        fallback_rest_messages_received=_as_int(
            row, "fallback_rest_messages_received"
        ),
        total_messages_received=_as_int(row, "total_messages_received"),
        files_written=_as_int(row, "files_written"),
        messages_by_topic=_json_object(row.get("messages_by_topic")),
        persisted_by_topic=_json_object(row.get("persisted_by_topic")),
        first_message_at=row.get("first_message_at") or None,
        last_message_at=row.get("last_message_at") or None,
        last_error_code=str(row.get("last_error_code") or ""),
    )


def merge_rest_diagnostic(
    metrics: StabilityMetrics,
    diagnostic_path: str | Path | None,
) -> StabilityMetrics:
    if not diagnostic_path or not Path(diagnostic_path).exists():
        return metrics
    payload = json.loads(Path(diagnostic_path).read_text(encoding="utf-8"))
    rest = [
        result
        for result in payload.get("results", [])
        if str(result.get("test", "")).startswith("rest_")
    ]
    metrics.rest_requests_ok = sum(
        result.get("status") == "PASS" for result in rest
    )
    metrics.rest_requests_failed = sum(
        result.get("status") == "FAIL" for result in rest
    )
    metrics.fallback_rest_messages_received = sum(
        result.get("status") == "PASS"
        and "records=0" not in str(result.get("details", ""))
        for result in rest
    )
    metrics.total_messages_received = (
        metrics.websocket_messages_received
        + metrics.fallback_rest_messages_received
    )
    return metrics


def build_stability_report(
    metrics: StabilityMetrics,
    *,
    duration_seconds: float,
    topics: list[str],
    maximum_reconnects: int = 2,
    maximum_errors: int = 2,
    topic_failures: list[str] | None = None,
) -> dict[str, Any]:
    outcome = classify_stability(
        metrics,
        maximum_reconnects=maximum_reconnects,
        maximum_errors=maximum_errors,
    )
    failures = topic_failures or []
    if outcome == PASS_WEBSOCKET_STABLE:
        recommendation = "ready_for_2h_test"
    elif outcome == PASS_REST_ONLY_FALLBACK:
        recommendation = "rest_only_mode"
    elif failures or metrics.last_error_code in {
        "WEBSOCKET_SUBSCRIPTION_REJECTED",
        "WEBSOCKET_PARSE_ERROR",
        "WEBSOCKET_PERSISTENCE_ERROR",
    }:
        recommendation = "not_ready_fix_topics"
    else:
        recommendation = "network_unstable"
    hours = max(float(duration_seconds) / 3600.0, 1 / 3600.0)
    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "duration_seconds": float(duration_seconds),
        "topics": topics,
        "messages_by_topic": metrics.messages_by_topic,
        "persisted_by_topic": metrics.persisted_by_topic,
        "reconnects_per_hour_estimated": round(
            metrics.websocket_reconnects / hours, 3
        ),
        "errors_per_hour_estimated": round(
            metrics.websocket_errors / hours, 3
        ),
        "ack_status": metrics.websocket_subscription_acknowledged,
        "first_message_at": metrics.first_message_at,
        "last_message_at": metrics.last_message_at,
        "last_error_code": metrics.last_error_code,
        "metrics": {
            "rest_requests_ok": metrics.rest_requests_ok,
            "rest_requests_failed": metrics.rest_requests_failed,
            "websocket_connected": metrics.websocket_connected,
            "websocket_subscription_acknowledged": (
                metrics.websocket_subscription_acknowledged
            ),
            "websocket_messages_received": (
                metrics.websocket_messages_received
            ),
            "websocket_messages_persisted": (
                metrics.websocket_messages_persisted
            ),
            "websocket_errors": metrics.websocket_errors,
            "websocket_reconnects": metrics.websocket_reconnects,
            "fallback_rest_messages_received": (
                metrics.fallback_rest_messages_received
            ),
            "total_messages_received": metrics.total_messages_received,
            "files_written": metrics.files_written,
        },
        "thresholds": {
            "maximum_reconnects": maximum_reconnects,
            "maximum_errors": maximum_errors,
            "websocket_data_required": True,
            "websocket_persistence_required": True,
            "subscription_acknowledgement_required": True,
        },
        "topic_failures": failures,
        "outcome": outcome,
        "recommendation": recommendation,
        "ready_for_long_collection": outcome == PASS_WEBSOCKET_STABLE,
        "safety": {
            "orders_sent": False,
            "broker_connected": False,
            "api_keys_used": False,
            "live_trading_enabled": False,
            "paper_internal_enabled": False,
            "paper_broker_enabled": False,
            "real_leverage_used": False,
        },
    }


def write_stability_report(
    report: dict[str, Any],
    destination: str | Path,
) -> Path:
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return path
