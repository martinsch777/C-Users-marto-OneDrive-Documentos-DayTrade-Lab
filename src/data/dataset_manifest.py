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
OFFLINE_SAFETY_FIELDS = (
    "broker_connected",
    "orders_sent",
    "live_trading_enabled",
    "paper_broker_enabled",
)


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
    output_file: str | None = None
    raw_input_file: str | None = None
    curated_file: str | None = None
    rows_input: int | None = None
    rows_output: int | None = None
    rows_removed: int | None = None
    total_excluded_sessions: int = 0
    excluded_sessions: list[dict[str, Any]] = field(default_factory=list)
    dataset_status: str = NOT_AUDITED
    created_at: str = ""
    broker_connected: bool = False
    orders_sent: bool = False
    live_trading_enabled: bool = False
    paper_broker_enabled: bool = False
    project_safety_state: dict[str, bool] = field(
        default_factory=lambda: {
            "live_trading": False,
            "live_trading_enabled": False,
            "broker_connected": False,
            "orders_sent": False,
            "paper_broker_enabled": False,
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


def curated_manifest_filename(
    *,
    symbol: str,
    timeframe: str,
    start: str,
    end: str,
) -> str:
    return f"{symbol.upper()}_{timeframe}_{start}_{end}_curated_manifest.json"


def build_dataset_manifest(
    result: DownloadResult,
    *,
    audit_report: EquityIntradayAuditReport | None,
    source_timezone: str,
    asset_class: str = "equity",
    created_at: str | None = None,
    excluded_sessions: list[dict[str, Any]] | None = None,
    raw_input_file: str | None = None,
    curated_file: str | None = None,
    rows_input: int | None = None,
    rows_output: int | None = None,
    rows_removed: int | None = None,
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
    manifest_excluded_sessions = (
        excluded_sessions
        if excluded_sessions is not None
        else (
            [session.to_record() for session in audit_report.excluded_sessions]
            if audit_report
            else []
        )
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
        output_file=result.output_file,
        raw_input_file=raw_input_file,
        curated_file=curated_file,
        rows_input=rows_input,
        rows_output=rows_output,
        rows_removed=rows_removed,
        sha256=(
            result.sha256
            if result.sha256
            else sha256_file(result.output_file)
            if result.output_file
            else ""
        ),
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
        total_excluded_sessions=len(manifest_excluded_sessions),
        excluded_sessions=manifest_excluded_sessions,
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


def write_curated_dataset_manifest(
    manifest: DatasetManifest,
    output_dir: str | Path = Path("data") / "manifests",
) -> Path:
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    path = destination / curated_manifest_filename(
        symbol=manifest.symbol,
        timeframe=manifest.timeframe,
        start=manifest.start,
        end=manifest.end,
    )
    path.write_text(
        json.dumps(manifest.to_record(), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return path


def _has_explicit_offline_safety_fields(payload: dict[str, Any]) -> bool:
    return any(field in payload for field in OFFLINE_SAFETY_FIELDS)


def _requires_explicit_offline_safety_validation(
    payload: dict[str, Any],
    manifest_path: Path,
) -> bool:
    return (
        manifest_path.name.endswith("_curated_manifest.json")
        or _has_explicit_offline_safety_fields(payload)
    )


def _validate_explicit_offline_safety_fields(
    payload: dict[str, Any],
    manifest_path: Path,
) -> None:
    for field in OFFLINE_SAFETY_FIELDS:
        if payload.get(field) is not False:
            raise ValueError(
                f"Dataset manifest {field} is not false: {manifest_path}"
            )


def _path_is_data_raw(path: str | Path) -> bool:
    normalized = str(path).replace("\\", "/")
    parts = [part.lower() for part in Path(normalized).parts]
    return any(
        left == "data" and right == "raw"
        for left, right in zip(parts, parts[1:])
    )


def _canonical_path(path: str | Path) -> str:
    normalized = str(path).replace("\\", "/")
    candidate = Path(normalized)
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    resolved = str(candidate.resolve(strict=False)).replace("\\", "/")
    return resolved.casefold()


def _same_manifest_path(expected: str | None, actual: str | Path) -> bool:
    if not expected:
        return False
    return _canonical_path(expected) == _canonical_path(actual)


def _manifest_candidates(
    symbol: str,
    timeframe: str,
    manifest_dir: str | Path,
) -> list[tuple[Path, dict[str, Any]]]:
    wanted_symbol = symbol.upper()
    candidates: list[tuple[Path, dict[str, Any]]] = []
    for candidate in sorted(Path(manifest_dir).glob(f"{wanted_symbol}_{timeframe}_*_manifest.json")):
        payload = json.loads(candidate.read_text(encoding="utf-8"))
        if payload.get("symbol") != wanted_symbol:
            continue
        if payload.get("timeframe") != timeframe:
            continue
        candidates.append((candidate, payload))
    return candidates


def _matches_curated_or_output(payload: dict[str, Any], csv_path: str | Path) -> bool:
    return (
        _same_manifest_path(payload.get("curated_file"), csv_path)
        or _same_manifest_path(payload.get("output_file"), csv_path)
    )


def _matches_input_file(payload: dict[str, Any], csv_path: str | Path) -> bool:
    input_file = payload.get("input_file")
    if _same_manifest_path(input_file, csv_path):
        return True
    if not input_file:
        return False
    return Path(str(input_file).replace("\\", "/")).name == Path(
        str(csv_path).replace("\\", "/")
    ).name


def _candidate_summary(candidates: list[tuple[Path, dict[str, Any]]]) -> str:
    if not candidates:
        return "none"
    rows = []
    for candidate, payload in candidates:
        rows.append(
            f"{candidate.name}: curated_file={payload.get('curated_file')!r}, "
            f"output_file={payload.get('output_file')!r}"
        )
    return "; ".join(rows)


def _validate_approved_manifest_payload(
    payload: dict[str, Any],
    candidate: Path,
    expected_hash: str,
) -> None:
    if payload.get("dataset_status") != APPROVED_FOR_OR_FVG_BACKTEST:
        raise ValueError(
            f"Dataset manifest is not approved_for_or_fvg_backtest: {candidate}"
        )
    if payload.get("audit_apt_for_or_fvg_backtest") is not True:
        raise ValueError(
            f"Dataset manifest audit_apt_for_or_fvg_backtest is not true: {candidate}"
        )
    if payload.get("audit_critical_warnings") not in ([], None):
        raise ValueError(
            f"Dataset manifest has audit_critical_warnings: {candidate}"
        )
    if payload.get("sha256") != expected_hash:
        raise ValueError(
            f"Dataset manifest sha256 does not match CSV: {candidate}"
        )
    if _requires_explicit_offline_safety_validation(payload, candidate):
        _validate_explicit_offline_safety_fields(payload, candidate)


def require_or_fvg_backtest_dataset_manifest(
    csv_path: str | Path,
    symbol: str,
    timeframe: str,
    manifest_dir: str | Path = Path("data") / "manifests",
) -> DatasetManifest:
    if _path_is_data_raw(csv_path):
        raise ValueError(
            f"OR/FVG backtests must use curated datasets, not data/raw: {csv_path}"
        )
    candidates = _manifest_candidates(symbol, timeframe, manifest_dir)
    if not [
        payload
        for _, payload in candidates
        if _matches_curated_or_output(payload, csv_path)
    ]:
        raise FileNotFoundError(
            "No OR/FVG approved manifest matched the requested CSV via "
            f"curated_file or output_file: {csv_path}. "
            f"Candidates: {_candidate_summary(candidates)}"
        )
    manifest = require_approved_dataset_manifest(
        csv_path,
        symbol,
        timeframe,
        manifest_dir=manifest_dir,
    )
    if not (
        _same_manifest_path(manifest.curated_file, csv_path)
        or _same_manifest_path(manifest.output_file, csv_path)
    ):
        raise ValueError(
            "OR/FVG backtest CSV must match manifest curated_file or output_file: "
            f"{csv_path}"
        )
    for field in OFFLINE_SAFETY_FIELDS:
        if getattr(manifest, field) is not False:
            raise ValueError(
                f"OR/FVG backtest manifest {field} is not false: {csv_path}"
            )
    return manifest


def require_approved_dataset_manifest(
    csv_path: str | Path,
    symbol: str,
    timeframe: str,
    manifest_dir: str | Path = Path("data") / "manifests",
) -> DatasetManifest:
    source = Path(csv_path)
    expected_hash = sha256_file(source)
    candidates = _manifest_candidates(symbol, timeframe, manifest_dir)
    curated_or_output_matches = [
        (candidate, payload)
        for candidate, payload in candidates
        if _matches_curated_or_output(payload, source)
    ]
    input_matches = [
        (candidate, payload)
        for candidate, payload in candidates
        if _matches_input_file(payload, source)
        and not _matches_curated_or_output(payload, source)
    ]
    for candidate, payload in curated_or_output_matches + input_matches:
        _validate_approved_manifest_payload(payload, candidate, expected_hash)
        return DatasetManifest(**payload)
    raise FileNotFoundError(
        f"No approved dataset manifest found for {source} "
        f"({wanted_symbol} {timeframe})"
    )
