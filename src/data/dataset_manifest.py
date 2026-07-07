from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .alpaca_equity_downloader import DownloadResult
from .equity_audit import EquityIntradayAuditReport


APPROVED_FOR_OR_FVG_BACKTEST = "approved_for_or_fvg_backtest"
FAILED_AUDIT = "failed_audit"
NOT_AUDITED = "not_audited"


def sha256_file(path: str | Path, chunk_size: int = 1024 * 1024) -> str:
    source = Path(path)
    digest = hashlib.sha256()
    with source.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class DatasetManifest:
    symbol: str
    asset_class: str
    timeframe: str
    provider: str
    feed: str
    adjustment: str
    source_timezone: str
    rth_only: bool
    start: str
    end: str
    rows: int
    first_timestamp: str
    last_timestamp: str
    input_file: str
    sha256: str
    calendar_source: str
    calendar_loaded: bool
    calendar_holidays_loaded: int
    calendar_early_closes_loaded: int
    audit_apt_for_or_fvg_backtest: bool | None
    audit_critical_warnings: list[str] = field(default_factory=list)
    audit_warnings: list[str] = field(default_factory=list)
    dataset_status: str = NOT_AUDITED
    created_at: str = ""
    project_safety_state: dict[str, bool] = field(
        default_factory=lambda: {
            "live_trading": False,
            "broker_connected": False,
            "orders_sent": False,
        }
    )

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


def classify_dataset_status(
    audit_apt_for_or_fvg_backtest: bool | None,
    audit_critical_warnings: list[str] | None,
) -> str:
    warnings = audit_critical_warnings or []
    if audit_apt_for_or_fvg_backtest is True and not warnings:
        return APPROVED_FOR_OR_FVG_BACKTEST
    if audit_apt_for_or_fvg_backtest is False:
        return FAILED_AUDIT
    return NOT_AUDITED


def manifest_filename(
    *,
    symbol: str,
    timeframe: str,
    start: str,
    end: str,
    provider: str,
    feed: str,
    adjustment: str,
    rth_only: bool,
) -> str:
    rth = "rth" if rth_only else "all"
    return (
        f"{symbol.upper()}_{timeframe}_{start}_{end}_"
        f"{provider}_{feed}_{adjustment}_{rth}_manifest.json"
    )


def build_dataset_manifest(
    result: DownloadResult,
    *,
    audit_report: EquityIntradayAuditReport | None,
    source_timezone: str,
    asset_class: str = "equity",
    created_at: str | None = None,
) -> DatasetManifest:
    critical = (
        list(audit_report.critical_warnings)
        if audit_report is not None
        else list(result.audit_critical_warnings or [])
    )
    audit_apt = (
        audit_report.apt_for_or_fvg_backtest
        if audit_report is not None
        else result.audit_apt_for_or_fvg_backtest
    )
    return DatasetManifest(
        symbol=result.symbol,
        asset_class=asset_class,
        timeframe=result.interval,
        provider=result.provider,
        feed=result.feed,
        adjustment=result.adjustment,
        source_timezone=source_timezone,
        rth_only=result.rth_only,
        start=result.start,
        end=result.end,
        rows=result.rows,
        first_timestamp=result.first_timestamp,
        last_timestamp=result.last_timestamp,
        input_file=result.output_file,
        sha256=sha256_file(result.output_file) if result.output_file else result.sha256,
        calendar_source=audit_report.calendar_source if audit_report else "",
        calendar_loaded=audit_report.calendar_loaded if audit_report else False,
        calendar_holidays_loaded=(
            audit_report.calendar_holidays_loaded if audit_report else 0
        ),
        calendar_early_closes_loaded=(
            audit_report.calendar_early_closes_loaded if audit_report else 0
        ),
        audit_apt_for_or_fvg_backtest=audit_apt,
        audit_critical_warnings=critical,
        audit_warnings=[],
        dataset_status=classify_dataset_status(audit_apt, critical),
        created_at=created_at or datetime.now(timezone.utc).isoformat(),
    )


def write_dataset_manifest(
    manifest: DatasetManifest,
    output_dir: str | Path = Path("data") / "manifests",
) -> Path:
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    path = destination / manifest_filename(
        symbol=manifest.symbol,
        timeframe=manifest.timeframe,
        start=manifest.start,
        end=manifest.end,
        provider=manifest.provider,
        feed=manifest.feed,
        adjustment=manifest.adjustment,
        rth_only=manifest.rth_only,
    )
    path.write_text(
        json.dumps(manifest.to_record(), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return path

