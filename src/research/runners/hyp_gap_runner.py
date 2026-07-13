from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from src.data import (
    DatasetManifest,
    EquitySessionCalendar,
    load_csv,
    require_approved_dataset_manifest_file,
)
from src.research import aggregate_event_results, compute_event_study
from src.research.hypotheses.hyp_gap import (
    SAFETY_FLAGS,
    detect_hyp_gap_events,
    load_hyp_gap_preregistration,
)


RESEARCH_PHASE = "discovery"
SCHEMA_VERSION = 1
APPROVAL_FLAGS = {
    "results_approved_for_validation": False,
    "results_approved_for_replay": False,
    "results_approved_for_paper": False,
    "results_approved_for_live": False,
}
EVENT_RESULT_COLUMNS = [
    "event_id",
    "hypothesis_id",
    "variant_id",
    "symbol",
    "timestamp",
    "session_date",
    "year",
    "expected_direction",
    "event_price",
    "future_timestamp",
    "expected_session_close_timestamp",
    "future_price",
    "horizon",
    "raw_return",
    "directional_return",
    "analysis_return",
    "availability_status",
    "missing_reason",
    "metadata",
]
EVENT_COLUMNS = [
    "event_id",
    "hypothesis_id",
    "variant_id",
    "symbol",
    "timestamp",
    "session_date",
    "expected_direction",
    "metadata",
]
AGGREGATION_GROUPS = (
    ("variant_id", "horizon"),
    ("symbol", "variant_id", "horizon"),
    ("year", "variant_id", "horizon"),
    ("expected_direction", "variant_id", "horizon"),
)


@dataclass(frozen=True)
class HypGapRunRequest:
    dataset_path: str
    manifest_path: str
    symbol: str
    timeframe: str
    requested_start: str
    requested_end: str
    preregistration_path: str
    output_directory: str
    run_id: str | None = None
    research_phase: str = RESEARCH_PHASE


@dataclass(frozen=True)
class HypGapRunResult:
    run_id: str
    output_directory: str
    run_manifest_path: str
    events_path: str
    event_results_path: str
    aggregate_results_path: str
    detection_summary_path: str
    event_count: int


def _date(value: str) -> date:
    return date.fromisoformat(str(value))


def _session_date(timestamp: pd.Timestamp, calendar: EquitySessionCalendar) -> str:
    return timestamp.tz_convert(calendar.timezone).date().isoformat()


def _safe_path(path: str | Path) -> str:
    return str(Path(path))


def _ensure_discovery_request(
    request: HypGapRunRequest,
    *,
    discovery_start: date,
    discovery_end: date,
) -> tuple[date, date]:
    if request.research_phase != RESEARCH_PHASE:
        raise ValueError("HYP-GAP runner currently supports only research_phase='discovery'")
    start = _date(request.requested_start)
    end = _date(request.requested_end)
    if start > end:
        raise ValueError("requested_start must be on or before requested_end")
    if start < discovery_start:
        raise ValueError("HYP-GAP discovery request starts before discovery")
    if end > discovery_end:
        raise ValueError("HYP-GAP discovery request must not touch validation or holdout")
    return start, end


def _excluded_session_dates(manifest: DatasetManifest, symbol: str) -> set[str]:
    wanted = symbol.upper()
    dates: set[str] = set()
    for record in manifest.excluded_sessions:
        if str(record.get("symbol", wanted)).upper() == wanted:
            dates.add(str(record.get("date")))
    return dates


def _frame_until_end(frame: pd.DataFrame, end: date, calendar: EquitySessionCalendar) -> pd.DataFrame:
    mask = [
        pd.Timestamp(timestamp).tz_convert(calendar.timezone).date() <= end
        for timestamp in frame["timestamp"]
    ]
    return frame.loc[mask].reset_index(drop=True)


def _first_session_date(frame: pd.DataFrame, calendar: EquitySessionCalendar) -> str:
    if frame.empty:
        raise ValueError("HYP-GAP runner dataset has no rows through requested_end")
    return _session_date(frame.iloc[0]["timestamp"], calendar)


def _fingerprint(payload: dict[str, Any]) -> str:
    import hashlib

    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _run_id(
    request: HypGapRunRequest,
    *,
    hypothesis_id: str,
    schema_version: int,
    config_hash: str,
    dataset_sha256: str,
) -> tuple[str, str]:
    payload = {
        "hypothesis_id": hypothesis_id,
        "research_phase": request.research_phase,
        "symbol": request.symbol.upper(),
        "timeframe": request.timeframe,
        "requested_start": request.requested_start,
        "requested_end": request.requested_end,
        "config_hash": config_hash,
        "dataset_sha256": dataset_sha256,
        "schema_version": schema_version,
    }
    digest = _fingerprint(payload)
    if request.run_id:
        return request.run_id, digest
    return (
        f"{hypothesis_id}__{request.research_phase}__{request.symbol.upper()}__"
        f"{request.timeframe}__{request.requested_start}__{request.requested_end}__"
        f"{digest[:16]}",
        digest,
    )


def _event_records(events) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for event in events:
        records.append(
            {
                "event_id": event.event_id,
                "hypothesis_id": event.hypothesis_id,
                "variant_id": event.variant_id,
                "symbol": event.symbol,
                "timestamp": event.timestamp.isoformat(),
                "session_date": event.session_date,
                "expected_direction": event.expected_direction,
                "metadata": json.dumps(event.metadata, sort_keys=True, default=str),
            }
        )
    return records


def _serializable_event_results(frame: pd.DataFrame) -> pd.DataFrame:
    data = frame.copy()
    for column in ("timestamp", "future_timestamp", "expected_session_close_timestamp"):
        if column in data.columns:
            data[column] = data[column].map(
                lambda value: value.isoformat() if pd.notna(value) else ""
            )
    if "metadata" in data.columns:
        data["metadata"] = data["metadata"].astype(str)
    return data


def _aggregate_all(event_results: pd.DataFrame) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    for group in AGGREGATION_GROUPS:
        aggregate = aggregate_event_results(event_results, group_by=group)
        aggregate.insert(0, "aggregation_group", "+".join(group))
        rows.append(aggregate)
    if not rows:
        return pd.DataFrame()
    combined = pd.concat(rows, ignore_index=True)
    sort_columns = [
        column
        for column in (
            "aggregation_group",
            "symbol",
            "year",
            "expected_direction",
            "variant_id",
            "horizon",
        )
        if column in combined.columns
    ]
    return combined.sort_values(sort_columns).reset_index(drop=True)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )


def run_hyp_gap_event_study(request: HypGapRunRequest) -> HypGapRunResult:
    preregistration = load_hyp_gap_preregistration(request.preregistration_path)
    requested_start, requested_end = _ensure_discovery_request(
        request,
        discovery_start=preregistration.discovery_start,
        discovery_end=preregistration.discovery_end,
    )
    manifest = require_approved_dataset_manifest_file(
        request.dataset_path,
        request.symbol,
        request.timeframe,
        request.manifest_path,
    )
    if request.timeframe != preregistration.timeframe:
        raise ValueError("HYP-GAP runner timeframe must match preregistration")
    if request.symbol.upper() not in preregistration.symbols:
        raise ValueError("HYP-GAP runner symbol must be preregistered")
    calendar = EquitySessionCalendar.from_config({"source": "us_equity"})
    excluded_dates = _excluded_session_dates(manifest, request.symbol)
    frame, report = load_csv(
        request.dataset_path,
        request.timeframe,
        asset_class="equity",
        drop_incomplete=False,
        calendar=calendar,
        excluded_session_dates=excluded_dates,
    )
    if not report.is_valid:
        raise ValueError("HYP-GAP runner dataset failed OHLCV quality validation")
    loaded = _frame_until_end(frame, requested_end, calendar)
    loaded_warmup_start = _first_session_date(loaded, calendar)
    detection = detect_hyp_gap_events(
        loaded,
        symbol=request.symbol,
        timeframe=request.timeframe,
        start_date=loaded_warmup_start,
        end_date=requested_end.isoformat(),
        event_start_date=requested_start.isoformat(),
        calendar=calendar,
        excluded_session_dates=excluded_dates,
        config_path=request.preregistration_path,
    )
    if detection.events:
        event_results = compute_event_study(
            loaded,
            detection.events,
            calendar=calendar,
            timeframe=request.timeframe,
            horizons=preregistration.horizons,
        )
        event_results = event_results.sort_values(
            ["session_date", "symbol", "variant_id", "horizon"]
        ).reset_index(drop=True)
    else:
        event_results = pd.DataFrame(columns=EVENT_RESULT_COLUMNS)
    aggregate_results = _aggregate_all(event_results)
    run_id, fingerprint = _run_id(
        request,
        hypothesis_id=preregistration.hypothesis_id,
        schema_version=SCHEMA_VERSION,
        config_hash=preregistration.config_hash,
        dataset_sha256=manifest.sha256,
    )
    output_dir = Path(request.output_directory)
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"HYP-GAP output directory is not empty: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    run_manifest_path = output_dir / "run_manifest.json"
    events_path = output_dir / "events.csv"
    event_results_path = output_dir / "event_results.csv"
    aggregate_results_path = output_dir / "aggregate_results.csv"
    detection_summary_path = output_dir / "detection_summary.json"

    pd.DataFrame(_event_records(detection.events), columns=EVENT_COLUMNS).to_csv(
        events_path,
        index=False,
    )
    _serializable_event_results(event_results).to_csv(event_results_path, index=False)
    aggregate_results.to_csv(aggregate_results_path, index=False)
    detection_summary_payload = asdict(detection.summary)
    _write_json(detection_summary_path, detection_summary_payload)
    run_manifest = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "fingerprint": fingerprint,
        "hypothesis_id": preregistration.hypothesis_id,
        "research_phase": request.research_phase,
        "symbol": request.symbol.upper(),
        "timeframe": request.timeframe,
        "dataset_path": _safe_path(request.dataset_path),
        "manifest_path": _safe_path(request.manifest_path),
        "dataset_sha256": manifest.sha256,
        "preregistration_path": _safe_path(request.preregistration_path),
        "preregistration_hash": preregistration.config_hash,
        "config_hash": preregistration.config_hash,
        "requested_start": requested_start.isoformat(),
        "requested_end": requested_end.isoformat(),
        "loaded_warmup_start": loaded_warmup_start,
        "effective_event_start": requested_start.isoformat(),
        "effective_event_end": requested_end.isoformat(),
        "horizons": list(preregistration.horizons),
        "variant_ids": [variant.variant_id for variant in preregistration.variants],
        "total_variants_expected": 6,
        "total_variants_executed": len(preregistration.variants),
        "excluded_sessions": sorted(excluded_dates),
        "event_count": len(detection.events),
        "events_by_variant": detection.summary.events_by_variant,
        "ineligible_reasons": detection.summary.ineligible_reasons,
        "outputs": {
            "run_manifest": run_manifest_path.name,
            "events": events_path.name,
            "event_results": event_results_path.name,
            "aggregate_results": aggregate_results_path.name,
            "detection_summary": detection_summary_path.name,
        },
        "execution_timestamp": datetime.now(timezone.utc).isoformat(),
        "technical_conventions": {
            "vwap": "sum(((high + low + close) / 3) * volume) / sum(volume)",
            "event_eligibility_window": "09:30 through 09:45 inclusive bar opens",
        },
        "safety_flags": dict(SAFETY_FLAGS),
        **APPROVAL_FLAGS,
    }
    _write_json(run_manifest_path, run_manifest)
    return HypGapRunResult(
        run_id=run_id,
        output_directory=str(output_dir),
        run_manifest_path=str(run_manifest_path),
        events_path=str(events_path),
        event_results_path=str(event_results_path),
        aggregate_results_path=str(aggregate_results_path),
        detection_summary_path=str(detection_summary_path),
        event_count=len(detection.events),
    )
