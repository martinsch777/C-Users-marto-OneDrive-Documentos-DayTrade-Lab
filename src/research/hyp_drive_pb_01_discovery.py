from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import subprocess
import time
import tracemalloc
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal, Mapping, Sequence
from uuid import uuid4

import numpy as np
import pandas as pd

from src.data.dataset_manifest import (
    APPROVED_FOR_OR_FVG_BACKTEST,
    DatasetManifest,
    require_approved_dataset_manifest_file,
)
from src.data.sessions import EquitySessionCalendar
from src.research.hyp_drive_pb_01 import (
    Bar,
    DailyRTHSession,
    Direction,
    DrivePullbackConfig,
    Event,
    GateMetrics,
    annual_concentration,
    atr20_prior,
    canonical_payload,
    canonical_payload_hash,
    deduplicate_events,
    detect_event_outcome,
    evaluate_gate,
    leave_one_largest_session_out_concentration,
    load_config_yaml,
    matched_unconditional_control,
    oriented_return,
    round_trip_cost,
    rvol_descriptive,
)


HYPOTHESIS_ID = "HYP-DRIVE-PB-01"
CONCEPTUAL_DESIGN_FREEZE_COMMIT = "925cede00f3d9c1b4de46e225f98d4636c19a831"
IMPLEMENTATION_CLARIFICATION_FREEZE_COMMIT = (
    "764478b86a01619620166848204e527f2fb55c55"
)
PREREGISTRATION_FREEZE_COMMIT = "adb7f7b59b08389883777103e23f98ea298a5965"
EXPECTED_CANONICAL_HASH = (
    "b763e7d2d01f1d12f9be85fa0238a4ccb21b251baee966f8e421410aaecc651b"
)
CONFIG_PATH = Path("configs/research/hypotheses/HYP-DRIVE-PB-01.yaml")
DEFAULT_OUTPUT_DIR = Path(
    "artifacts/research/HYP-DRIVE-PB-01/discovery_2022_2024"
)
DISCOVERY_START = "2022-01-01"
DISCOVERY_END = "2024-12-31"
SYMBOLS = ("QQQ", "SPY")
HORIZONS = ("15min", "30min", "60min", "session_close")
PRIMARY_HORIZON = "30min"
MINUTE_COLUMNS = ("timestamp", "open", "high", "low", "close", "volume")
DEFAULT_DATASET_PATHS = {
    symbol: Path(f"data/curated/{symbol}_1min_2022-01-01_2026-07-06_curated.csv")
    for symbol in SYMBOLS
}
DEFAULT_MANIFEST_PATHS = {
    symbol: Path(
        f"data/manifests/{symbol}_1min_2022-01-01_2026-07-06_curated_manifest.json"
    )
    for symbol in SYMBOLS
}
REQUIRED_OUTPUT_FILES = (
    "run_manifest.json",
    "dataset_manifest_snapshot.json",
    "config_snapshot.yaml",
    "confirmed_events.csv",
    "event_exclusions.csv",
    "path_metrics.csv",
    "unconditional_control.csv",
    "incremental_metrics.csv",
    "metrics_pooled.csv",
    "metrics_by_symbol.csv",
    "metrics_by_year.csv",
    "metrics_by_direction.csv",
    "metrics_by_horizon.csv",
    "concentration_metrics.csv",
    "leave_one_out_metrics.csv",
    "bootstrap_intervals.csv",
    "cost_threshold_comparison.csv",
    "discovery_gate.json",
    "execution_progress.json",
    "checksums.json",
)


@dataclass(frozen=True)
class RuntimeState:
    head_commit: str
    working_tree_clean: bool
    preregistration_commit_exists: bool
    preregistration_is_ancestor: bool
    status_porcelain: str = ""


@dataclass(frozen=True)
class DiscoveryRequest:
    mode: Literal["validate_implementation", "run_discovery"]
    expected_preregistration_commit: str | None = None
    expected_execution_freeze_commit: str | None = None
    expected_canonical_hash: str | None = None


@dataclass(frozen=True)
class ManifestContract:
    symbol: str
    dataset_path: Path
    manifest_path: Path
    dataset_sha256: str
    manifest_sha256: str
    start: str
    end: str
    excluded_sessions: tuple[date, ...]
    manifest: DatasetManifest
    raw: Mapping[str, Any]


@dataclass(frozen=True)
class TemporalAccessReport:
    requested_start: str
    requested_end: str
    materialized_min_timestamp: str | None
    materialized_max_timestamp: str | None
    materialized_rows_after_discovery_end: int
    event_rows_outside_discovery: int = 0
    control_rows_outside_discovery: int = 0
    historical_2025_rows_materialized: int = 0
    historical_2026_rows_materialized: int = 0
    horizons_crossing_session_or_period: int = 0

    @property
    def contamination_absent(self) -> bool:
        return all(
            value == 0
            for value in (
                self.materialized_rows_after_discovery_end,
                self.event_rows_outside_discovery,
                self.control_rows_outside_discovery,
                self.historical_2025_rows_materialized,
                self.historical_2026_rows_materialized,
                self.horizons_crossing_session_or_period,
            )
        )

    def to_record(self) -> dict[str, Any]:
        return {
            **self.__dict__,
            "contamination_absent": self.contamination_absent,
        }


@dataclass(frozen=True)
class SessionValidation:
    daily_sessions: tuple[DailyRTHSession, ...]
    approved_session_dates: frozenset[date]
    manifest_excluded_dates: frozenset[date]
    incomplete_session_dates: frozenset[date]
    expected_minutes_by_session: Mapping[date, tuple[pd.Timestamp, ...]]


@dataclass(frozen=True)
class CausalIntegrityReport:
    manifest_validation_passed: bool
    dataset_contract_passed: bool
    calendar_session_validation_passed: bool
    resample_causality_passed: bool
    event_timestamp_integrity_passed: bool
    horizon_continuity_passed: bool
    control_integrity_passed: bool
    unresolved_data_quality_failures: int
    lookahead_violations: int
    accepted_incomplete_sessions: int

    @property
    def causal_integrity_passed(self) -> bool:
        return (
            self.manifest_validation_passed
            and self.dataset_contract_passed
            and self.calendar_session_validation_passed
            and self.resample_causality_passed
            and self.event_timestamp_integrity_passed
            and self.horizon_continuity_passed
            and self.control_integrity_passed
            and self.unresolved_data_quality_failures == 0
            and self.lookahead_violations == 0
            and self.accepted_incomplete_sessions == 0
        )

    def to_record(self) -> dict[str, Any]:
        return {
            **self.__dict__,
            "causal_integrity_passed": self.causal_integrity_passed,
        }


class ExecutionProgress:
    def __init__(
        self, *, progress_path: Path | None = None, emit_console: bool = True
    ) -> None:
        self.progress_path = progress_path
        self.emit_console = emit_console
        self.stages: list[dict[str, Any]] = []
        self._interrupted = False

    def set_progress_path(self, path: Path) -> None:
        self.progress_path = path
        self.persist()

    def start(self, stage: str, **extra: Any) -> dict[str, Any]:
        record = {
            "stage": stage,
            "status": "running",
            "start_time": _utc_now(),
            "end_time": None,
            "elapsed_seconds": 0.0,
            "input_rows": None,
            "output_rows": None,
            "symbol": None,
            "horizons": None,
            "groups_total": None,
            "groups_processed": None,
            "bootstrap_replicates_total": None,
            "bootstrap_replicates_processed": None,
            "eta_seconds": None,
            "memory_mb": _memory_mb(),
            "interrupted": False,
            "results_written": False,
            "_perf_start": time.perf_counter(),
        }
        record.update(extra)
        self.stages.append(record)
        self.persist()
        self._emit(record)
        return record

    def update(self, record: dict[str, Any], **extra: Any) -> None:
        _validate_progress_values({**record, **extra})
        record.update(extra)
        record["elapsed_seconds"] = round(
            time.perf_counter() - record["_perf_start"], 6
        )
        record["memory_mb"] = _memory_mb()
        self.persist()

    def end(self, record: dict[str, Any], **extra: Any) -> None:
        _validate_progress_values({**record, **extra})
        record.update(extra)
        record["status"] = "completed"
        record["end_time"] = _utc_now()
        record["elapsed_seconds"] = round(
            time.perf_counter() - record.pop("_perf_start"), 6
        )
        record["memory_mb"] = _memory_mb()
        self.persist()
        self._emit(record)

    def mark_failed(self, error: BaseException, *, temp_dir: Path | None) -> None:
        for record in reversed(self.stages):
            if record.get("status") == "running":
                record["status"] = "failed"
                record["end_time"] = _utc_now()
                record["elapsed_seconds"] = round(
                    time.perf_counter() - record.pop("_perf_start", time.perf_counter()),
                    6,
                )
                record["results_written"] = False
                record["error"] = f"{type(error).__name__}: {error}"
                break
        self.stages.append(
            {
                "stage": "failure",
                "status": "failed",
                "start_time": _utc_now(),
                "end_time": _utc_now(),
                "elapsed_seconds": 0.0,
                "interrupted": False,
                "results_written": False,
                "error": f"{type(error).__name__}: {error}",
                "temp_dir": str(temp_dir) if temp_dir else None,
                "temp_dir_policy": "retained_as_failed_for_diagnostics",
            }
        )
        self.persist()

    def mark_interrupted(self, *, temp_dir: Path | None) -> None:
        if self._interrupted:
            return
        self._interrupted = True
        for record in reversed(self.stages):
            if record.get("status") == "running":
                record["status"] = "interrupted"
                record["interrupted"] = True
                record["results_written"] = False
                record["end_time"] = _utc_now()
                record.pop("_perf_start", None)
                break
        self.stages.append(
            {
                "stage": "interrupt",
                "status": "interrupted",
                "start_time": _utc_now(),
                "end_time": _utc_now(),
                "elapsed_seconds": 0.0,
                "interrupted": True,
                "results_written": False,
                "temp_dir": str(temp_dir) if temp_dir else None,
                "temp_dir_policy": "retained_as_incomplete_for_diagnostics",
            }
        )
        self.persist()

    def summary(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "stages": [
                {key: value for key, value in stage.items() if key != "_perf_start"}
                for stage in self.stages
            ],
        }

    def persist(self) -> None:
        if self.progress_path is not None:
            _write_json_atomic(self.progress_path, self.summary())

    def _emit(self, record: Mapping[str, Any]) -> None:
        if self.emit_console:
            print(
                json.dumps(
                    {
                        "execution_progress": {
                            key: value
                            for key, value in record.items()
                            if key != "_perf_start"
                        }
                    },
                    sort_keys=True,
                    default=str,
                ),
                flush=True,
            )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _memory_mb() -> float | None:
    try:
        import resource

        value = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        divisor = 1024.0 if value > 10_000 else 1.0
        return round(value / divisor, 3)
    except (ImportError, AttributeError):
        started_here = not tracemalloc.is_tracing()
        if started_here:
            tracemalloc.start()
        current, _ = tracemalloc.get_traced_memory()
        if started_here:
            tracemalloc.stop()
        return round(current / (1024.0 * 1024.0), 3)


def _validate_progress_values(values: Mapping[str, Any]) -> None:
    for processed_name, total_name in (
        ("groups_processed", "groups_total"),
        ("bootstrap_replicates_processed", "bootstrap_replicates_total"),
    ):
        processed = values.get(processed_name)
        total = values.get(total_name)
        if processed is not None and total is not None:
            if int(processed) < 0 or int(total) < 0 or int(processed) > int(total):
                raise ValueError(f"Invalid progress: {processed_name}={processed}, {total_name}={total}")
    eta = values.get("eta_seconds")
    if eta is not None and float(eta) < 0:
        raise ValueError("eta_seconds cannot be negative.")


def _write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{uuid4().hex}")
    temporary.write_text(
        json.dumps(
            _json_safe(payload),
            indent=2,
            sort_keys=True,
            ensure_ascii=True,
            allow_nan=False,
            default=str,
        )
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def collect_runtime_state(cwd: str | Path = ".") -> RuntimeState:
    root = Path(cwd)

    def git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args],
            cwd=root,
            text=True,
            capture_output=True,
            check=check,
        )

    head = git("rev-parse", "--verify", "HEAD").stdout.strip()
    if len(head) != 40 or any(character not in "0123456789abcdef" for character in head):
        raise RuntimeError(f"Git returned an invalid full HEAD SHA: {head!r}")
    status = git("status", "--porcelain=v1", "--untracked-files=all").stdout
    clean = status.strip() == ""
    exists = git(
        "cat-file",
        "-e",
        f"{PREREGISTRATION_FREEZE_COMMIT}^{{commit}}",
        check=False,
    ).returncode == 0
    ancestor = (
        exists
        and git(
            "merge-base",
            "--is-ancestor",
            PREREGISTRATION_FREEZE_COMMIT,
            head,
            check=False,
        ).returncode
        == 0
    )
    return RuntimeState(head, clean, exists, ancestor, status)


def _read_manifest(path: Path) -> Mapping[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError(f"Manifest root must be a mapping: {path}")
    return payload


def _manifest_exclusion_date(item: Mapping[str, Any]) -> date:
    value = item.get("session_date", item.get("date"))
    if value is None:
        raise PermissionError("Manifest exclusion is missing session_date/date.")
    return date.fromisoformat(str(value))


def validate_manifest_contract(
    symbol: str,
    dataset_path: Path,
    manifest_path: Path,
) -> ManifestContract:
    manifest = require_approved_dataset_manifest_file(
        dataset_path,
        symbol,
        "1min",
        manifest_path,
    )
    raw = _read_manifest(manifest_path)
    if manifest.asset_class.lower() not in {"equity", "etf"}:
        raise PermissionError(f"{symbol} manifest asset_class must be equity/ETF.")
    provider = manifest.provider.strip().lower()
    feed = manifest.feed.strip().lower()
    if provider != "alpaca" or feed != "sip":
        raise PermissionError(f"{symbol} manifest source must be Alpaca SIP.")
    if manifest.dataset_status != APPROVED_FOR_OR_FVG_BACKTEST:
        raise PermissionError(f"{symbol} manifest status is not exactly approved.")
    if manifest.audit_apt_for_or_fvg_backtest is not True:
        raise PermissionError(f"{symbol} manifest audit flag must be true.")
    if manifest.audit_critical_warnings != []:
        raise PermissionError(f"{symbol} manifest has critical warnings.")
    if not manifest.rth_only or manifest.source_timezone != "America/New_York":
        raise PermissionError(f"{symbol} manifest RTH/timezone contract mismatch.")
    if (
        not manifest.calendar_loaded
        or manifest.calendar_source
        not in {"US_EQUITY_RTH", "builtin_us_equity_calendar_v1"}
    ):
        raise PermissionError(f"{symbol} manifest calendar is not approved US_EQUITY_RTH.")
    if "excluded_sessions" not in raw or "total_excluded_sessions" not in raw:
        raise PermissionError(f"{symbol} manifest must declare exclusions and their count.")
    if manifest.total_excluded_sessions != len(manifest.excluded_sessions):
        raise PermissionError(f"{symbol} manifest exclusion count is inconsistent.")
    exclusions = tuple(
        sorted(_manifest_exclusion_date(item) for item in manifest.excluded_sessions)
    )
    if len(exclusions) != len(set(exclusions)):
        raise PermissionError(f"{symbol} manifest contains duplicate exclusions.")
    if not manifest.curated_file:
        raise PermissionError(f"{symbol} manifest curated_file is missing.")
    if Path(manifest.curated_file).resolve() != dataset_path.resolve():
        raise PermissionError(f"{symbol} manifest curated_file does not match dataset.")
    if not dataset_path.is_file():
        raise FileNotFoundError(dataset_path)
    if _sha256_file(dataset_path) != manifest.sha256:
        raise PermissionError(f"{symbol} curated dataset hash mismatch.")
    if manifest.start > DISCOVERY_START or manifest.end < DISCOVERY_END:
        raise PermissionError(f"{symbol} manifest does not cover discovery.")
    for field in (
        "broker_connected",
        "orders_sent",
        "paper_broker_enabled",
        "live_trading_enabled",
    ):
        if getattr(manifest, field) is not False:
            raise PermissionError(f"{symbol} manifest safety flag {field} must be false.")
    return ManifestContract(
        symbol=symbol,
        dataset_path=dataset_path,
        manifest_path=manifest_path,
        dataset_sha256=manifest.sha256,
        manifest_sha256=_sha256_file(manifest_path),
        start=manifest.start,
        end=manifest.end,
        excluded_sessions=exclusions,
        manifest=manifest,
        raw=dict(raw),
    )


def validate_implementation(
    request: DiscoveryRequest | None = None,
) -> dict[str, Any]:
    request = request or DiscoveryRequest(mode="validate_implementation")
    config = load_config_yaml(CONFIG_PATH)
    recomputed = canonical_payload_hash(canonical_payload(config))
    if recomputed != EXPECTED_CANONICAL_HASH:
        raise PermissionError("Canonical hash differs from preregistration freeze.")
    if (
        config.conceptual_design_freeze_commit
        != CONCEPTUAL_DESIGN_FREEZE_COMMIT
        or config.implementation_clarification_freeze_commit
        != IMPLEMENTATION_CLARIFICATION_FREEZE_COMMIT
    ):
        raise PermissionError("Conceptual or clarification freeze mismatch.")
    if config.hypothesis_id != HYPOTHESIS_ID:
        raise PermissionError("Runner hypothesis mismatch.")
    if config.status != "preregistered_not_executed":
        raise PermissionError("Discovery requires preregistered_not_executed status.")
    if len(config.research_parameters()) != 17:
        raise PermissionError("Exactly 17 research parameters are required.")
    if config.canonical_spec["frozen_market_conventions"]["count"] != 1:
        raise PermissionError("Exactly one frozen market convention is required.")
    if config.decision_variants != 1:
        raise PermissionError("Decision variant budget must remain one.")
    if any(config.safety_flags.values()):
        raise PermissionError("Every safety flag must remain false.")
    if (
        config.canonical_spec["session"]["calendar"] != "US_EQUITY_RTH"
        or config.timezone != "America/New_York"
    ):
        raise PermissionError("Session contract mismatch.")
    if (
        config.canonical_spec["temporal_splits"]["validation_2025"]["unlocked"]
        is not False
    ):
        raise PermissionError("Validation 2025 must remain locked.")
    return {
        "hypothesis_id": config.hypothesis_id,
        "mode": "validate_implementation",
        "implementation_valid": True,
        "canonical_payload_hash": recomputed,
        "conceptual_design_freeze_commit": config.conceptual_design_freeze_commit,
        "implementation_clarification_freeze_commit": (
            config.implementation_clarification_freeze_commit
        ),
        "preregistration_freeze_commit": PREREGISTRATION_FREEZE_COMMIT,
        "execution_freeze_commit": None,
        "datasets_opened": False,
        "manifests_opened": False,
        "artifacts_created": False,
        "discovery_executed": False,
        "validation_2025_executed": False,
        "historical_2026_executed": False,
        "strategy_created": False,
        "orders_created": False,
        "position_sizing_used": False,
    }


def validate_discovery_preflight(
    request: DiscoveryRequest,
) -> dict[str, Any]:
    if request.mode != "run_discovery":
        raise PermissionError("Discovery preflight only accepts run_discovery mode.")
    if request.expected_preregistration_commit != PREREGISTRATION_FREEZE_COMMIT:
        raise PermissionError("Preregistration freeze commit mismatch.")
    if not request.expected_execution_freeze_commit:
        raise PermissionError("--expected-execution-freeze-commit is required.")
    if request.expected_canonical_hash != EXPECTED_CANONICAL_HASH:
        raise PermissionError("Expected canonical hash mismatch.")
    runtime = collect_runtime_state()
    if not runtime.preregistration_commit_exists:
        raise PermissionError("Preregistration freeze commit does not exist.")
    if not runtime.preregistration_is_ancestor:
        raise PermissionError("Preregistration freeze is not an ancestor of execution HEAD.")
    if runtime.head_commit != request.expected_execution_freeze_commit:
        raise PermissionError("Execution freeze must equal execution HEAD.")
    if not runtime.working_tree_clean:
        raise PermissionError("Working tree must be clean.")
    if DEFAULT_OUTPUT_DIR.exists():
        raise FileExistsError(
            f"Final discovery output already exists: {DEFAULT_OUTPUT_DIR}"
        )

    implementation = validate_implementation(request)
    config = load_config_yaml(CONFIG_PATH)
    manifest_contracts: dict[str, ManifestContract] = {}
    for symbol in SYMBOLS:
        manifest_contracts[symbol] = validate_manifest_contract(
            symbol,
            DEFAULT_DATASET_PATHS[symbol],
            DEFAULT_MANIFEST_PATHS[symbol],
        )
    return {
        **implementation,
        "mode": "run_discovery",
        "preflight_passed": True,
        "head_commit": runtime.head_commit,
        "execution_freeze_commit": request.expected_execution_freeze_commit,
        "requested_start": DISCOVERY_START,
        "requested_end": DISCOVERY_END,
        "symbols": list(SYMBOLS),
        "manifest_contracts": manifest_contracts,
        "config": config,
    }


def load_bounded_dataset(
    path: Path,
) -> tuple[pd.DataFrame, TemporalAccessReport]:
    if path.suffix.lower() != ".csv":
        raise ValueError(
            "The governed runner supports bounded CSV reads only; Parquet requires "
            "audited predicate-pushdown support."
        )
    cutoff = pd.Timestamp("2025-01-01 00:00", tz="America/New_York")
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames is None or "timestamp" not in reader.fieldnames:
            raise ValueError(f"Curated CSV is missing timestamp: {path}")
        for row in reader:
            timestamp = pd.Timestamp(row["timestamp"])
            if timestamp.tzinfo is None:
                raise ValueError("Bounded reader requires timezone-aware timestamps.")
            if timestamp.tz_convert("America/New_York") >= cutoff:
                break
            rows.append(row)
    frame = pd.DataFrame(rows, columns=reader.fieldnames)
    timestamps = (
        pd.to_datetime(frame["timestamp"], utc=True)
        if not frame.empty
        else pd.Series([], dtype="datetime64[ns, UTC]")
    )
    local_dates = (
        timestamps.dt.tz_convert("America/New_York").dt.date
        if not timestamps.empty
        else pd.Series([], dtype=object)
    )
    local_years = (
        timestamps.dt.tz_convert("America/New_York").dt.year
        if not timestamps.empty
        else pd.Series([], dtype="int64")
    )
    discovery_end = date.fromisoformat(DISCOVERY_END)
    report = TemporalAccessReport(
        requested_start=DISCOVERY_START,
        requested_end=DISCOVERY_END,
        materialized_min_timestamp=(
            pd.Timestamp(timestamps.min()).isoformat() if not timestamps.empty else None
        ),
        materialized_max_timestamp=(
            pd.Timestamp(timestamps.max()).isoformat() if not timestamps.empty else None
        ),
        materialized_rows_after_discovery_end=int((local_dates > discovery_end).sum()),
        historical_2025_rows_materialized=int((local_years == 2025).sum()),
        historical_2026_rows_materialized=int((local_years == 2026).sum()),
    )
    return frame, report


def validate_minute_frame(
    frame: pd.DataFrame,
    symbol: str,
    calendar: EquitySessionCalendar | None = None,
) -> pd.DataFrame:
    calendar = calendar or EquitySessionCalendar.us_equity()
    missing = set(MINUTE_COLUMNS) - set(frame.columns)
    if missing:
        raise ValueError(f"{symbol} minute data missing columns: {sorted(missing)}")
    columns = [*MINUTE_COLUMNS, *(["symbol"] if "symbol" in frame.columns else [])]
    data = frame.loc[:, columns].copy()
    try:
        raw_timestamps = [pd.Timestamp(value) for value in data["timestamp"]]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{symbol} contains invalid timestamps.") from exc
    if any(timestamp.tzinfo is None for timestamp in raw_timestamps):
        raise ValueError(f"{symbol} timestamps must be timezone-aware.")
    data["timestamp"] = pd.to_datetime(data["timestamp"], utc=True)
    if not data["timestamp"].is_monotonic_increasing:
        raise ValueError(f"{symbol} timestamps must be strictly ordered.")
    if data["timestamp"].duplicated().any():
        raise ValueError(f"{symbol} contains duplicate timestamps.")
    local = data["timestamp"].dt.tz_convert(calendar.timezone)
    if any(
        timestamp.second != 0 or timestamp.microsecond != 0 or timestamp.nanosecond != 0
        for timestamp in local
    ):
        raise ValueError(f"{symbol} timestamps must align to exact minute labels.")
    numeric = list(MINUTE_COLUMNS[1:])
    data[numeric] = data[numeric].apply(pd.to_numeric, errors="coerce")
    if not np.isfinite(data[numeric].to_numpy(dtype=float)).all():
        raise ValueError(f"{symbol} contains non-finite OHLCV.")
    if (data[["open", "high", "low", "close"]] <= 0).any().any():
        raise ValueError(f"{symbol} prices must be strictly positive.")
    if (data["volume"] < 0).any():
        raise ValueError(f"{symbol} volume must be non-negative.")
    if (
        (data["high"] < data[["open", "close", "low"]].max(axis=1)).any()
        or (data["low"] > data[["open", "close", "high"]].min(axis=1)).any()
    ):
        raise ValueError(f"{symbol} contains inconsistent OHLC.")
    if not calendar.mask(data["timestamp"]).all():
        raise ValueError(f"{symbol} contains bars outside approved US_EQUITY_RTH.")
    if "symbol" in data.columns:
        symbols = set(data["symbol"].astype(str).str.upper())
        if symbols != {symbol.upper()}:
            raise ValueError(f"{symbol} dataset contains a different or mixed symbol.")
    else:
        data["symbol"] = symbol.upper()
    return data.reset_index(drop=True)


def crop_discovery_period(frame: pd.DataFrame) -> pd.DataFrame:
    local = frame["timestamp"].dt.tz_convert("America/New_York")
    dates = local.dt.date
    start, end = date.fromisoformat(DISCOVERY_START), date.fromisoformat(DISCOVERY_END)
    return frame.loc[(dates >= start) & (dates <= end)].reset_index(drop=True)


def resample_rth_1min_to_5min(frame: pd.DataFrame) -> pd.DataFrame:
    data = frame.copy()
    local = data["timestamp"].dt.tz_convert("America/New_York")
    minute = local.dt.hour * 60 + local.dt.minute
    data = data.loc[(minute >= 570) & (minute < 960)].copy()
    local = data["timestamp"].dt.tz_convert("America/New_York")
    data["_session_date"] = local.dt.date
    data["_minute"] = local.dt.hour * 60 + local.dt.minute
    data["_bucket"] = ((data["_minute"] - 570) // 5).astype(int)
    rows: list[dict[str, Any]] = []
    for (session_date, bucket), group in data.groupby(
        ["_session_date", "_bucket"], sort=True
    ):
        expected = list(range(570 + bucket * 5, 575 + bucket * 5))
        observed = sorted(group["_minute"].astype(int).tolist())
        if observed != expected:
            continue
        ordered = group.sort_values("timestamp", kind="mergesort")
        rows.append(
            {
                "timestamp": ordered.iloc[0]["timestamp"],
                "open": float(ordered.iloc[0]["open"]),
                "high": float(ordered["high"].max()),
                "low": float(ordered["low"].min()),
                "close": float(ordered.iloc[-1]["close"]),
                "volume": float(ordered["volume"].sum()),
                "session_date": session_date,
                "complete": True,
            }
        )
    if not rows:
        return pd.DataFrame(
            columns=(
                "timestamp",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "session_date",
                "complete",
            )
        )
    return pd.DataFrame(rows).sort_values(
        ["session_date", "timestamp"], kind="mergesort"
    ).reset_index(drop=True)


def build_daily_approved_sessions(
    minute_frame: pd.DataFrame,
    excluded_sessions: tuple[date, ...],
    calendar: EquitySessionCalendar | None = None,
) -> SessionValidation:
    calendar = calendar or EquitySessionCalendar.us_equity()
    data = minute_frame.copy()
    local = data["timestamp"].dt.tz_convert(calendar.timezone)
    data["session_date"] = local.dt.date
    excluded = set(excluded_sessions)
    sessions: list[DailyRTHSession] = []
    approved_dates: set[date] = set()
    incomplete_dates: set[date] = set()
    expected_by_session: dict[date, tuple[pd.Timestamp, ...]] = {}
    for session_date, group in data.groupby("session_date", sort=True):
        expected = tuple(
            calendar.expected_timestamps(session_date, session_date, "1min")
        )
        expected_by_session[session_date] = expected
        observed = tuple(group["timestamp"])
        complete = observed == expected
        if not complete:
            incomplete_dates.add(session_date)
        approved = session_date not in excluded and complete
        if approved:
            approved_dates.add(session_date)
        sessions.append(
            DailyRTHSession(
                session_date=session_date,
                high=float(group["high"].max()),
                low=float(group["low"].min()),
                close=float(
                    group.sort_values("timestamp", kind="mergesort").iloc[-1]["close"]
                ),
                approved=approved,
                complete=complete,
            )
        )
    return SessionValidation(
        daily_sessions=tuple(sessions),
        approved_session_dates=frozenset(approved_dates),
        manifest_excluded_dates=frozenset(excluded),
        incomplete_session_dates=frozenset(incomplete_dates),
        expected_minutes_by_session=expected_by_session,
    )


def _bars(frame: pd.DataFrame) -> list[Bar]:
    return [
        Bar(
            row.timestamp,
            row.open,
            row.high,
            row.low,
            row.close,
            row.volume,
            bool(row.complete),
        )
        for row in frame.itertuples(index=False)
    ]


def detect_confirmed_events(
    symbol: str,
    minute_frame: pd.DataFrame,
    five_minute: pd.DataFrame,
    session_validation: SessionValidation,
    config: DrivePullbackConfig,
) -> tuple[pd.DataFrame, pd.DataFrame, tuple[Event, ...]]:
    accepted_rows: list[dict[str, Any]] = []
    exclusions: list[dict[str, Any]] = []
    events: list[Event] = []
    sessions = session_validation.daily_sessions
    minute_local = minute_frame["timestamp"].dt.tz_convert(config.timezone)
    minute_work = minute_frame.copy()
    minute_work["session_date"] = minute_local.dt.date
    grouped_dates = frozenset(five_minute["session_date"])
    for session_date in sorted(
        (
            session_validation.manifest_excluded_dates
            | session_validation.incomplete_session_dates
        )
        - grouped_dates
    ):
        exclusions.append(
            {
                "symbol": symbol,
                "session_date": session_date,
                "exclusion_reason": (
                    "EXCLUDED_SESSION_NOT_APPROVED"
                    if session_date in session_validation.manifest_excluded_dates
                    else "EXCLUDED_INCOMPLETE_INTRADAY_DATA"
                ),
            }
        )
    for session_date, group in five_minute.groupby("session_date", sort=True):
        if session_date in session_validation.manifest_excluded_dates:
            exclusions.append(
                {
                    "symbol": symbol,
                    "session_date": session_date,
                    "exclusion_reason": "EXCLUDED_SESSION_NOT_APPROVED",
                }
            )
            continue
        if session_date in session_validation.incomplete_session_dates:
            exclusions.append(
                {
                    "symbol": symbol,
                    "session_date": session_date,
                    "exclusion_reason": "EXCLUDED_INCOMPLETE_INTRADAY_DATA",
                }
            )
            continue
        if session_date not in session_validation.approved_session_dates:
            exclusions.append(
                {
                    "symbol": symbol,
                    "session_date": session_date,
                    "exclusion_reason": "EXCLUDED_SESSION_NOT_APPROVED",
                }
            )
            continue
        atr = atr20_prior(sessions, session_date, config)
        if atr is None:
            exclusions.append(
                {
                    "symbol": symbol,
                    "session_date": session_date,
                    "exclusion_reason": "EXCLUDED_INSUFFICIENT_ATR_HISTORY",
                }
            )
            continue
        local = group["timestamp"].dt.tz_convert(config.timezone)
        by_clock = {
            timestamp.strftime("%H:%M"): row
            for timestamp, (_, row) in zip(local, group.iterrows())
        }
        drive_rows = [
            by_clock[clock]
            for clock in ("09:30", "09:35", "09:40")
            if clock in by_clock
        ]
        post_rows = [
            by_clock[clock]
            for clock in ("09:45", "09:50", "09:55", "10:00", "10:05")
            if clock in by_clock
        ]
        if len(drive_rows) != 3 or not post_rows:
            exclusions.append(
                {
                    "symbol": symbol,
                    "session_date": session_date,
                    "exclusion_reason": "EXCLUDED_INCOMPLETE_INTRADAY_DATA",
                }
            )
            continue
        outcome = detect_event_outcome(
            symbol,
            _bars(pd.DataFrame(drive_rows)),
            _bars(pd.DataFrame(post_rows)),
            _bars(group),
            atr,
            config,
        )
        if outcome.event is None:
            exclusions.append(
                {
                    "symbol": symbol,
                    "session_date": session_date,
                    "exclusion_reason": outcome.exclusion_reason,
                }
            )
            continue
        event = outcome.event
        events.append(event)
        session_minutes = minute_work[
            minute_work["session_date"] == session_date
        ].copy()
        local_minutes = session_minutes["timestamp"].dt.tz_convert(config.timezone)
        drive_minutes = session_minutes[
            (local_minutes.dt.strftime("%H:%M") >= "09:30")
            & (local_minutes.dt.strftime("%H:%M") < "09:45")
        ]
        causal_minutes = session_minutes[
            session_minutes["timestamp"] < event.confirmation_timestamp
        ]
        typical_price = (
            causal_minutes["high"]
            + causal_minutes["low"]
            + causal_minutes["close"]
        ) / 3.0
        causal_volume = float(causal_minutes["volume"].sum())
        vwap = (
            float((typical_price * causal_minutes["volume"]).sum() / causal_volume)
            if causal_volume > 0
            else np.nan
        )
        prior_volumes = [
            float(
                minute_work[
                    (minute_work["session_date"] == prior.session_date)
                    & (
                        minute_work["timestamp"]
                        .dt.tz_convert(config.timezone)
                        .dt.strftime("%H:%M")
                        >= "09:30"
                    )
                    & (
                        minute_work["timestamp"]
                        .dt.tz_convert(config.timezone)
                        .dt.strftime("%H:%M")
                        < "09:45"
                    )
                ]["volume"].sum()
            )
            for prior in sessions
            if prior.approved and prior.complete and prior.session_date < session_date
        ][-config.historical_atr_lookback :]
        rvol = rvol_descriptive(
            float(drive_minutes["volume"].sum()), prior_volumes, config
        )
        accepted_rows.append(
            {
                "event_id": f"{symbol}-{session_date.isoformat()}",
                "hypothesis_id": event.hypothesis_id,
                "symbol": symbol,
                "session_date": session_date,
                "direction_orientation": event.direction.value,
                "drive_start_timestamp": drive_rows[0]["timestamp"],
                "drive_end_timestamp": event.drive.frozen_at,
                "drive_open": event.drive.initial_price,
                "drive_close": event.drive.final_price,
                "drive_displacement": event.drive.displacement,
                "atr20": atr,
                "normalized_drive": event.drive.score,
                "frozen_drive_extreme": event.drive.extreme,
                "drive_excursion": event.drive.excursion,
                "pullback_start_timestamp": post_rows[0]["timestamp"],
                "pullback_end_timestamp": event.confirmation_timestamp,
                "pullback_depth": event.pullback_depth,
                "pullback_depth_ratio": event.pullback_depth_ratio,
                "confirmation_timestamp": event.confirmation_timestamp,
                "executable_timestamp": event.executable_timestamp,
                "executable_price": event.executable_price,
                "vwap_descriptive": vwap,
                "rvol_descriptive": rvol,
                "event_status": "accepted",
                "exclusion_reason": None,
            }
        )
    deduplicated = deduplicate_events(events, config)
    kept = {
        (event.symbol, event.session_date, event.executable_timestamp)
        for event in deduplicated.events
    }
    accepted = pd.DataFrame(
        [
            row
            for row in accepted_rows
            if (
                row["symbol"],
                row["session_date"],
                row["executable_timestamp"],
            )
            in kept
        ]
    )
    for (dedup_symbol, session_date), reason in deduplicated.exclusions.items():
        exclusions.append(
            {
                "symbol": dedup_symbol,
                "session_date": session_date,
                "exclusion_reason": reason,
            }
        )
    return (
        accepted.sort_values(
            ["symbol", "session_date", "executable_timestamp"], kind="mergesort"
        ).reset_index(drop=True)
        if not accepted.empty
        else accepted,
        pd.DataFrame(exclusions),
        deduplicated.events,
    )


def compute_path_metrics(
    events_frame: pd.DataFrame,
    events: tuple[Event, ...],
    five_minute: pd.DataFrame,
    config: DrivePullbackConfig,
    calendar: EquitySessionCalendar | None = None,
) -> pd.DataFrame:
    calendar = calendar or EquitySessionCalendar.us_equity()
    by_id = {
        f"{event.symbol}-{event.session_date.isoformat()}": event for event in events
    }
    rows: list[dict[str, Any]] = []
    for record in events_frame.to_dict("records"):
        event = by_id[record["event_id"]]
        session = five_minute[five_minute["session_date"] == event.session_date].copy()
        session = session.sort_values("timestamp", kind="mergesort")
        session_by_timestamp = session.set_index("timestamp", drop=False)
        close_clock = calendar.session_close(event.session_date)
        if close_clock is None:
            raise ValueError(f"Event occurs on non-session date: {event.session_date}")
        official_close = pd.Timestamp(
            datetime.combine(event.session_date, close_clock),
            tz=calendar.timezone,
        ).tz_convert("UTC")
        executable_timestamp = event.executable_timestamp.tz_convert("UTC")
        for horizon in HORIZONS:
            if horizon == "session_close":
                future_timestamp = official_close
                expected_path = pd.date_range(
                    executable_timestamp,
                    official_close - pd.Timedelta(5, unit="min"),
                    freq="5min",
                )
                complete_path = (
                    len(expected_path) > 0
                    and all(timestamp in session_by_timestamp.index for timestamp in expected_path)
                )
                path = (
                    session_by_timestamp.loc[list(expected_path)].reset_index(drop=True)
                    if complete_path
                    else session.iloc[0:0]
                )
                future_price = (
                    float(path.iloc[-1]["close"]) if complete_path else np.nan
                )
            else:
                minutes = int(horizon.removesuffix("min"))
                future_timestamp = executable_timestamp + pd.Timedelta(
                    minutes, unit="min"
                )
                expected = pd.date_range(
                    executable_timestamp,
                    future_timestamp,
                    freq="5min",
                )
                complete_path = (
                    future_timestamp < official_close
                    and len(expected) == minutes // 5 + 1
                    and all(timestamp in session_by_timestamp.index for timestamp in expected)
                )
                path = (
                    session_by_timestamp.loc[list(expected[:-1])].reset_index(drop=True)
                    if complete_path
                    else session.iloc[0:0]
                )
                future_price = (
                    float(session_by_timestamp.loc[future_timestamp]["open"])
                    if complete_path
                    else np.nan
                )
            horizon_available = bool(
                complete_path
                and np.isfinite(future_price)
                and future_timestamp.date() == event.session_date
            )
            event_return = (
                oriented_return(event.direction, event.executable_price, future_price)
                if horizon_available
                else np.nan
            )
            if path.empty:
                mfe = mae = np.nan
            elif event.direction is Direction.LONG:
                mfe = float(path["high"].max() / event.executable_price - 1)
                mae = float(path["low"].min() / event.executable_price - 1)
            else:
                mfe = float(event.executable_price / path["low"].min() - 1)
                mae = float(event.executable_price / path["high"].max() - 1)
            baseline = round_trip_cost(
                event.symbol, event.executable_price, "baseline", config
            )
            stress = round_trip_cost(
                event.symbol, event.executable_price, "stress", config
            )
            rows.append(
                {
                    "event_id": record["event_id"],
                    "symbol": event.symbol,
                    "session_date": event.session_date,
                    "direction": event.direction.value,
                    "executable_timestamp": event.executable_timestamp,
                    "executable_price": event.executable_price,
                    "horizon": horizon,
                    "future_timestamp": future_timestamp,
                    "future_price": future_price,
                    "horizon_available": horizon_available,
                    "path_complete": bool(complete_path),
                    "event_return": event_return,
                    "MFE": mfe,
                    "MAE": mae,
                    "baseline_round_trip_cost": baseline,
                    "stress_round_trip_cost": stress,
                    "net_return_baseline": event_return - baseline,
                    "net_return_stress": event_return - stress,
                }
            )
    return pd.DataFrame(rows).sort_values(
        ["symbol", "session_date", "event_id", "horizon"], kind="mergesort"
    ).reset_index(drop=True)


def build_unconditional_candidates(
    path_metrics: pd.DataFrame,
    five_by_symbol: Mapping[str, pd.DataFrame],
    approved_sessions_by_symbol: Mapping[str, frozenset[date]],
    calendar: EquitySessionCalendar | None = None,
) -> pd.DataFrame:
    calendar = calendar or EquitySessionCalendar.us_equity()
    rows: list[dict[str, Any]] = []
    event_buckets = path_metrics[
        ["symbol", "direction", "executable_timestamp", "horizon"]
    ].drop_duplicates()
    for event in event_buckets.to_dict("records"):
        symbol = str(event["symbol"])
        five = five_by_symbol[symbol]
        local_time = pd.Timestamp(event["executable_timestamp"]).tz_convert(
            "America/New_York"
        ).strftime("%H:%M")
        for session_date, session in five.groupby("session_date", sort=True):
            if session_date not in approved_sessions_by_symbol[symbol]:
                continue
            local = session["timestamp"].dt.tz_convert("America/New_York")
            executable = session[local.dt.strftime("%H:%M") == local_time]
            if executable.empty:
                continue
            start = executable.iloc[0]
            horizon = str(event["horizon"])
            close_clock = calendar.session_close(session_date)
            if close_clock is None:
                continue
            official_close = pd.Timestamp(
                datetime.combine(session_date, close_clock),
                tz=calendar.timezone,
            ).tz_convert("UTC")
            by_timestamp = session.set_index("timestamp", drop=False)
            if horizon == "session_close":
                expected = pd.date_range(
                    start["timestamp"],
                    official_close - pd.Timedelta(5, unit="min"),
                    freq="5min",
                )
                if not len(expected) or not all(
                    timestamp in by_timestamp.index for timestamp in expected
                ):
                    continue
                future_price = float(by_timestamp.loc[expected[-1]]["close"])
            else:
                future_timestamp = start["timestamp"] + pd.Timedelta(
                    int(horizon.removesuffix("min")), unit="min"
                )
                expected = pd.date_range(
                    start["timestamp"], future_timestamp, freq="5min"
                )
                if future_timestamp >= official_close or not all(
                    timestamp in by_timestamp.index for timestamp in expected
                ):
                    continue
                future_price = float(by_timestamp.loc[future_timestamp]["open"])
            direction = Direction(str(event["direction"]))
            rows.append(
                {
                    "symbol": symbol,
                    "session_date": session_date,
                    "executable_timestamp": start["timestamp"],
                    "horizon": horizon,
                    "direction": direction.value,
                    "event_return": oriented_return(
                        direction, float(start["open"]), future_price
                    ),
                }
            )
    if not rows:
        return pd.DataFrame(
            columns=(
                "symbol",
                "session_date",
                "executable_timestamp",
                "horizon",
                "direction",
                "event_return",
            )
        )
    return pd.DataFrame(rows).drop_duplicates().sort_values(
        ["symbol", "direction", "session_date", "executable_timestamp", "horizon"],
        kind="mergesort",
    )


def attach_unconditional_control(
    path_metrics: pd.DataFrame,
    candidates: pd.DataFrame,
    config: DrivePullbackConfig,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    event_columns = [
        "symbol",
        "session_date",
        "executable_timestamp",
        "horizon",
        "event_return",
    ]
    matched_parts: list[pd.DataFrame] = []
    for direction, direction_events in path_metrics.groupby("direction", sort=True):
        direction_candidates = candidates[candidates["direction"] == direction]
        matched = matched_unconditional_control(
            direction_events[event_columns], direction_candidates[event_columns], config
        )
        matched.index = direction_events.index
        matched_parts.append(matched)
    matched_all = pd.concat(matched_parts).sort_index() if matched_parts else pd.DataFrame()
    result = path_metrics.copy()
    result["unconditional_return"] = matched_all["unconditional_return"]
    result["incremental_return"] = matched_all["incremental_return"]
    return result, matched_all.reset_index(drop=True)


def derive_temporal_access_report(
    reports: Sequence[TemporalAccessReport],
    events: pd.DataFrame,
    controls: pd.DataFrame,
    path_metrics: pd.DataFrame,
) -> TemporalAccessReport:
    minimums = [
        report.materialized_min_timestamp
        for report in reports
        if report.materialized_min_timestamp is not None
    ]
    maximums = [
        report.materialized_max_timestamp
        for report in reports
        if report.materialized_max_timestamp is not None
    ]
    start = date.fromisoformat(DISCOVERY_START)
    end = date.fromisoformat(DISCOVERY_END)

    def outside(frame: pd.DataFrame) -> int:
        if frame.empty or "session_date" not in frame:
            return 0
        dates = pd.to_datetime(frame["session_date"]).dt.date
        return int(((dates < start) | (dates > end)).sum())

    crossing = 0
    if not path_metrics.empty:
        available = path_metrics[path_metrics["horizon_available"]]
        future_dates = pd.to_datetime(
            available["future_timestamp"], utc=True
        ).dt.tz_convert("America/New_York").dt.date
        session_dates = pd.to_datetime(available["session_date"]).dt.date
        crossing = int(
            ((future_dates != session_dates) | (future_dates > end)).sum()
        )
    return TemporalAccessReport(
        requested_start=DISCOVERY_START,
        requested_end=DISCOVERY_END,
        materialized_min_timestamp=min(minimums) if minimums else None,
        materialized_max_timestamp=max(maximums) if maximums else None,
        materialized_rows_after_discovery_end=sum(
            report.materialized_rows_after_discovery_end for report in reports
        ),
        event_rows_outside_discovery=outside(events),
        control_rows_outside_discovery=outside(controls),
        historical_2025_rows_materialized=sum(
            report.historical_2025_rows_materialized for report in reports
        ),
        historical_2026_rows_materialized=sum(
            report.historical_2026_rows_materialized for report in reports
        ),
        horizons_crossing_session_or_period=crossing,
    )


def derive_causal_integrity_report(
    contracts: Mapping[str, ManifestContract],
    validated_frames: Mapping[str, pd.DataFrame],
    sessions: Mapping[str, SessionValidation],
    five_by_symbol: Mapping[str, pd.DataFrame],
    events: pd.DataFrame,
    path_metrics: pd.DataFrame,
    candidates: pd.DataFrame,
) -> CausalIntegrityReport:
    accepted_incomplete = 0
    if not events.empty:
        for row in events.itertuples(index=False):
            if row.session_date not in sessions[row.symbol].approved_session_dates:
                accepted_incomplete += 1

    lookahead_violations = 0
    if not events.empty:
        drive_end = pd.to_datetime(events["drive_end_timestamp"], utc=True)
        confirmation = pd.to_datetime(events["confirmation_timestamp"], utc=True)
        executable = pd.to_datetime(events["executable_timestamp"], utc=True)
        confirmation_local = confirmation.dt.tz_convert("America/New_York")
        executable_local = executable.dt.tz_convert("America/New_York")
        session_dates = pd.to_datetime(events["session_date"]).dt.date
        valid_timing = (
            (drive_end <= confirmation)
            & (confirmation < executable)
            & ((executable - confirmation) == pd.Timedelta(5, unit="min"))
            & (confirmation_local.dt.date == session_dates)
            & (executable_local.dt.date == session_dates)
            & (confirmation_local.dt.strftime("%H:%M") <= "10:10")
            & (executable_local.dt.strftime("%H:%M") <= "10:15")
        )
        lookahead_violations = int((~valid_timing).sum())
    event_timestamp_ok = lookahead_violations == 0

    horizon_failures = 0
    if not path_metrics.empty:
        availability_mismatch = (
            path_metrics["horizon_available"] != path_metrics["path_complete"]
        )
        unavailable = ~path_metrics["horizon_available"]
        unavailable_has_excursion = path_metrics.loc[
            unavailable, ["MFE", "MAE"]
        ].notna().any(axis=1)
        available = path_metrics["horizon_available"]
        available_nonfinite = ~np.isfinite(
            path_metrics.loc[
                available, ["future_price", "event_return", "MFE", "MAE"]
            ].to_numpy(dtype=float)
        )
        horizon_failures = (
            int(availability_mismatch.sum())
            + int(unavailable_has_excursion.sum())
            + int(available_nonfinite.any(axis=1).sum())
        )
    horizon_ok = horizon_failures == 0

    control_failures = 0
    if not candidates.empty:
        invalid_session = [
            row.session_date not in sessions[row.symbol].approved_session_dates
            for row in candidates.itertuples(index=False)
        ]
        duplicate_candidates = candidates.duplicated(
            [
                "symbol",
                "session_date",
                "executable_timestamp",
                "horizon",
                "direction",
            ]
        )
        nonfinite_candidates = ~np.isfinite(
            candidates["event_return"].to_numpy(dtype=float)
        )
        control_failures = (
            sum(invalid_session)
            + int(duplicate_candidates.sum())
            + int(nonfinite_candidates.sum())
        )
    control_ok = control_failures == 0

    resample_ok = all(
        frame.empty
        or (
            frame["complete"].eq(True).all()
            and frame["timestamp"]
            .dt.tz_convert("America/New_York")
            .dt.minute.mod(5)
            .eq(0)
            .all()
        )
        for frame in five_by_symbol.values()
    )
    manifest_ok = set(contracts) == set(SYMBOLS) and all(
        contract.symbol == symbol
        and contract.dataset_path == DEFAULT_DATASET_PATHS[symbol]
        and contract.manifest_path == DEFAULT_MANIFEST_PATHS[symbol]
        and len(contract.dataset_sha256) == 64
        and len(contract.manifest_sha256) == 64
        for symbol, contract in contracts.items()
    )
    dataset_ok = set(validated_frames) == set(SYMBOLS) and all(
        set(MINUTE_COLUMNS).issubset(frame.columns)
        and frame["timestamp"].is_monotonic_increasing
        and not frame["timestamp"].duplicated().any()
        and (
            frame.empty
            or (
                frame["timestamp"]
                .dt.tz_convert("America/New_York")
                .dt.date.le(date.fromisoformat(DISCOVERY_END))
                .all()
            )
        )
        for frame in validated_frames.values()
    )
    calendar_ok = set(sessions) == set(SYMBOLS) and all(
        not (
            validation.approved_session_dates
            & (
                validation.manifest_excluded_dates
                | validation.incomplete_session_dates
            )
        )
        for validation in sessions.values()
    )
    unresolved_failures = (
        accepted_incomplete + horizon_failures + control_failures
    )
    return CausalIntegrityReport(
        manifest_validation_passed=manifest_ok,
        dataset_contract_passed=dataset_ok,
        calendar_session_validation_passed=calendar_ok,
        resample_causality_passed=resample_ok,
        event_timestamp_integrity_passed=event_timestamp_ok,
        horizon_continuity_passed=horizon_ok,
        control_integrity_passed=control_ok,
        unresolved_data_quality_failures=unresolved_failures,
        lookahead_violations=lookahead_violations,
        accepted_incomplete_sessions=accepted_incomplete,
    )


def clustered_percentile_bootstrap_arrays(
    rows: pd.DataFrame,
    config: DrivePullbackConfig,
    *,
    progress_callback: Callable[..., None] | None = None,
    block_size: int = 256,
) -> dict[str, tuple[float, float]]:
    columns = ("event_return", "incremental_return", "net_return_baseline")
    if rows.empty or "session_date" not in rows or not set(columns).issubset(rows):
        raise ValueError("Bootstrap rows are missing required data.")
    if not np.isfinite(rows[list(columns)].to_numpy(dtype=float)).all():
        raise ValueError("Bootstrap inputs must be finite.")
    grouped = list(rows.groupby("session_date", sort=True))
    cluster_sums = np.asarray(
        [group[list(columns)].to_numpy(dtype=float).sum(axis=0) for _, group in grouped]
    )
    cluster_counts = np.asarray([len(group) for _, group in grouped], dtype=np.int64)
    groups_total = len(grouped)
    rng = np.random.default_rng(config.bootstrap_seed)
    statistics = np.empty((config.bootstrap_resamples, len(columns)), dtype=float)
    start = time.perf_counter()
    if progress_callback:
        progress_callback(
            groups_total=groups_total,
            groups_processed=groups_total,
            bootstrap_replicates_total=config.bootstrap_resamples,
            bootstrap_replicates_processed=0,
            percentage=0.0,
            eta_seconds=None,
        )
    for offset in range(0, config.bootstrap_resamples, block_size):
        size = min(block_size, config.bootstrap_resamples - offset)
        sampled = rng.integers(0, groups_total, size=(size, groups_total))
        totals = cluster_sums[sampled].sum(axis=1)
        counts = cluster_counts[sampled].sum(axis=1)
        statistics[offset : offset + size] = totals / counts[:, None]
        processed = offset + size
        elapsed = time.perf_counter() - start
        eta = elapsed * (config.bootstrap_resamples - processed) / processed
        if progress_callback:
            progress_callback(
                groups_total=groups_total,
                groups_processed=groups_total,
                bootstrap_replicates_total=config.bootstrap_resamples,
                bootstrap_replicates_processed=processed,
                percentage=round(100.0 * processed / config.bootstrap_resamples, 3),
                eta_seconds=max(0.0, eta),
            )
    alpha = (1.0 - config.bootstrap_confidence_level) / 2.0
    return {
        column: (
            float(np.quantile(statistics[:, index], alpha)),
            float(np.quantile(statistics[:, index], 1.0 - alpha)),
        )
        for index, column in enumerate(columns)
    }


def _summary_record(frame: pd.DataFrame) -> dict[str, Any]:
    available = frame[frame["horizon_available"]].copy()

    def stats(column: str) -> tuple[float, float, float]:
        values = pd.to_numeric(available[column], errors="coerce")
        values = values[np.isfinite(values)]
        if values.empty:
            return np.nan, np.nan, np.nan
        return float(values.mean()), float(values.median()), float((values > 0).mean())

    gross_mean, gross_median, gross_win = stats("event_return")
    incremental_mean, incremental_median, incremental_win = stats(
        "incremental_return"
    )
    baseline_mean, baseline_median, _ = stats("net_return_baseline")
    stress_mean, _, _ = stats("net_return_stress")
    mfe_mean, mfe_median, _ = stats("MFE")
    mae_mean, mae_median, _ = stats("MAE")
    total = int(frame["event_id"].nunique())
    available_count = int(available["event_id"].nunique())
    return {
        "events_total": total,
        "events_available": available_count,
        "availability_rate": float(available_count / total) if total else np.nan,
        "gross_mean": gross_mean,
        "gross_median": gross_median,
        "gross_win_rate": gross_win,
        "incremental_mean": incremental_mean,
        "incremental_median": incremental_median,
        "incremental_win_rate": incremental_win,
        "net_baseline_mean": baseline_mean,
        "net_baseline_median": baseline_median,
        "net_stress_mean": stress_mean,
        "MFE_mean": mfe_mean,
        "MFE_median": mfe_median,
        "MAE_mean": mae_mean,
        "MAE_median": mae_median,
    }


def _grouped_metric_table(
    metrics: pd.DataFrame,
    group_columns: Sequence[str],
    config: DrivePullbackConfig,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for keys, group in metrics.groupby(list(group_columns), sort=True, dropna=False):
        key_values = keys if isinstance(keys, tuple) else (keys,)
        record = dict(zip(group_columns, key_values, strict=True))
        record.update(_summary_record(group))
        horizon = record.get("horizon")
        record["primary_horizon"] = horizon == config.primary_horizon_label
        rows.append(record)
    return pd.DataFrame(rows)


def aggregate_and_gate(
    metrics: pd.DataFrame,
    config: DrivePullbackConfig,
    causal_report: CausalIntegrityReport,
    temporal_report: TemporalAccessReport,
    *,
    progress_callback: Callable[..., None] | None = None,
) -> dict[str, Any]:
    primary = metrics[
        (metrics["horizon"] == config.primary_horizon_label)
        & metrics["horizon_available"]
    ].copy()
    finite_columns = (
        "event_return",
        "incremental_return",
        "net_return_baseline",
        "net_return_stress",
    )
    if primary.empty or not np.isfinite(
        primary[list(finite_columns)].to_numpy(dtype=float)
    ).all():
        raise ValueError("Primary metrics must be non-empty and finite.")
    intervals = clustered_percentile_bootstrap_arrays(
        primary,
        config,
        progress_callback=progress_callback,
    )
    concentration = annual_concentration(primary, config)
    loo = leave_one_largest_session_out_concentration(primary, config)
    metrics_work = metrics.assign(
        year=pd.to_datetime(metrics["session_date"]).dt.year
    )
    pooled = pd.DataFrame(
        [
            {
                "scope": "pooled_primary",
                "horizon": config.primary_horizon_label,
                "primary_horizon": True,
                **_summary_record(primary),
            }
        ]
    )
    by_horizon = _grouped_metric_table(metrics_work, ("horizon",), config)
    by_symbol = _grouped_metric_table(
        metrics_work, ("symbol", "horizon"), config
    )
    by_year_work = primary.assign(
        year=pd.to_datetime(primary["session_date"]).dt.year
    )
    by_year = _grouped_metric_table(
        metrics_work, ("year", "horizon"), config
    )
    by_direction = _grouped_metric_table(
        metrics_work, ("direction", "horizon"), config
    )
    event_count_by_symbol = {
        symbol: int(primary.loc[primary["symbol"] == symbol, "event_id"].nunique())
        for symbol in config.symbols
    }
    direction_primary = by_direction[by_direction["primary_horizon"]]
    symbol_primary = by_symbol[by_symbol["primary_horizon"]]
    year_primary = by_year[by_year["primary_horizon"]]
    direction_mean = dict(
        zip(direction_primary["direction"], direction_primary["gross_mean"], strict=False)
    )
    direction_median = dict(
        zip(
            direction_primary["direction"],
            direction_primary["gross_median"],
            strict=False,
        )
    )
    symbol_mean = dict(
        zip(symbol_primary["symbol"], symbol_primary["gross_mean"], strict=False)
    )
    annual_gross = dict(
        zip(year_primary["year"], year_primary["gross_mean"], strict=False)
    )
    annual_signs = (
        primary.assign(year=pd.to_datetime(primary["session_date"]).dt.year)
        .groupby("year", sort=True)["incremental_return"]
        .sum()
        .to_dict()
    )
    removed = loo.removed_session_date
    loo_rows = (
        primary[primary["session_date"] != removed] if removed is not None else primary
    )
    loo_year = loo_rows.assign(
        year=pd.to_datetime(loo_rows["session_date"]).dt.year
    ).groupby("year", sort=True)["incremental_return"].sum()
    gate_metrics = GateMetrics(
        primary_horizon_minutes=config.primary_horizon_minutes,
        pooled_event_count=int(primary["event_id"].nunique()),
        event_count_by_symbol=event_count_by_symbol,
        direction_mean=direction_mean,
        direction_median=direction_median,
        symbol_mean=symbol_mean,
        annual_gross_mean=annual_gross,
        pooled_incremental_mean=float(primary["incremental_return"].mean()),
        pooled_baseline_net_mean=float(primary["net_return_baseline"].mean()),
        pooled_stress_net_mean=float(primary["net_return_stress"].mean()),
        annual_concentration=concentration,
        leave_one_session_out_concentration=loo,
        annual_incremental_signs=annual_signs,
        leave_one_out_annual_incremental_signs={
            int(year): float(value) for year, value in loo_year.items()
        },
        bootstrap_intervals=intervals,
        causal_integrity_passed=causal_report.causal_integrity_passed,
        temporal_contamination_absent=temporal_report.contamination_absent,
        decision_variants=config.decision_variants,
    )
    gate = evaluate_gate(gate_metrics, config)
    incremental = pooled.copy()
    bootstrap_frame = pd.DataFrame(
        [
            {"metric": metric, "ci_low": bounds[0], "ci_high": bounds[1]}
            for metric, bounds in intervals.items()
        ]
    )
    cost_comparison = pd.DataFrame(
        [
            {
                "profile": profile,
                "percentage_exceeding_cost": float(
                    (
                        primary["event_return"]
                        > primary[f"{profile}_round_trip_cost"]
                    ).mean()
                ),
            }
            for profile in ("baseline", "stress")
        ]
    )
    concentration_frame = pd.DataFrame(
        [
            {
                "scope": "annual_concentration",
                "value": concentration.value,
                "passed": concentration.passed,
                "validation_status": concentration.validation_status,
                "threshold": config.maximum_annual_effect_concentration,
            }
        ]
    )
    loo_frame = pd.DataFrame(
        [
            {
                "scope": "leave_one_largest_session_out",
                "removed_session_date": loo.removed_session_date,
                "value": loo.value,
                "passed": loo.passed,
                "validation_status": loo.validation_status,
                "threshold": config.maximum_annual_effect_concentration,
            }
        ]
    )
    gate_inputs = {
        "primary_horizon_minutes": gate_metrics.primary_horizon_minutes,
        "pooled_event_count": gate_metrics.pooled_event_count,
        "event_count_by_symbol": dict(gate_metrics.event_count_by_symbol),
        "direction_mean": dict(gate_metrics.direction_mean),
        "direction_median": dict(gate_metrics.direction_median),
        "symbol_mean": dict(gate_metrics.symbol_mean),
        "annual_gross_mean": dict(gate_metrics.annual_gross_mean),
        "pooled_incremental_mean": gate_metrics.pooled_incremental_mean,
        "pooled_baseline_net_mean": gate_metrics.pooled_baseline_net_mean,
        "pooled_stress_net_mean": gate_metrics.pooled_stress_net_mean,
        "annual_concentration": concentration_frame.iloc[0].to_dict(),
        "leave_one_session_out_concentration": loo_frame.iloc[0].to_dict(),
        "annual_incremental_signs": dict(gate_metrics.annual_incremental_signs),
        "leave_one_out_annual_incremental_signs": dict(
            gate_metrics.leave_one_out_annual_incremental_signs
        ),
        "bootstrap_intervals": dict(gate_metrics.bootstrap_intervals),
        "causal_integrity_report": causal_report.to_record(),
        "temporal_access_report": temporal_report.to_record(),
        "decision_variants": gate_metrics.decision_variants,
    }
    return {
        "incremental_metrics": incremental,
        "metrics_pooled": pooled,
        "metrics_by_symbol": by_symbol,
        "metrics_by_year": by_year,
        "metrics_by_direction": by_direction,
        "metrics_by_horizon": by_horizon,
        "concentration_metrics": concentration_frame,
        "leave_one_out_metrics": loo_frame,
        "bootstrap_intervals": bootstrap_frame,
        "cost_threshold_comparison": cost_comparison,
        "gate": {
            "criteria": dict(gate.criteria),
            "gate_inputs": gate_inputs,
            "thresholds": {
                "minimum_pooled_events": config.minimum_pooled_events,
                "minimum_events_per_symbol": config.minimum_events_per_symbol,
                "minimum_positive_discovery_years": config.minimum_positive_discovery_years,
                "maximum_annual_effect_concentration": config.maximum_annual_effect_concentration,
                "bootstrap_lower_bound": 0.0,
            },
            "all_required": gate.all_required,
            "passed": gate.passed,
            "classification": gate.classification,
            "validation_2025_unlocked": gate.validation_2025_unlocked,
            "paper_eligible": gate.paper_eligible,
            "live_eligible": gate.live_eligible,
            "primary_horizon": config.primary_horizon_label,
            "secondary_horizons_cannot_override_primary_fail": True,
            "strategy_created": False,
            "orders_created": False,
            "position_sizing_used": False,
        },
    }


def _serialize_frame(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    for column in result.columns:
        if "timestamp" in column:
            result[column] = result[column].map(
                lambda value: pd.Timestamp(value).isoformat()
                if pd.notna(value)
                else ""
            )
        elif column == "session_date":
            result[column] = result[column].map(str)
    sort_columns = list(result.columns[: min(4, len(result.columns))])
    if sort_columns:
        result = result.sort_values(sort_columns, kind="mergesort")
    return result.reset_index(drop=True)


def _repo_relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _input_checksum_records(
    contracts: Mapping[str, ManifestContract],
    *,
    execution_freeze_commit: str,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for symbol in SYMBOLS:
        contract = contracts[symbol]
        for name, path, digest in (
            (f"{symbol}_curated_dataset", contract.dataset_path, contract.dataset_sha256),
            (f"{symbol}_manifest", contract.manifest_path, contract.manifest_sha256),
        ):
            records.append(
                {
                    "name": name,
                    "kind": "file",
                    "path": _repo_relative(path),
                    "size": path.stat().st_size,
                    "sha256": digest,
                }
            )
    records.append(
        {
            "name": "config_yaml",
            "kind": "file",
            "path": _repo_relative(CONFIG_PATH),
            "size": CONFIG_PATH.stat().st_size,
            "sha256": _sha256_file(CONFIG_PATH),
        }
    )
    for name, value in (
        ("canonical_payload_hash", EXPECTED_CANONICAL_HASH),
        ("preregistration_freeze_commit", PREREGISTRATION_FREEZE_COMMIT),
        ("execution_freeze_commit", execution_freeze_commit),
        ("head_commit", execution_freeze_commit),
    ):
        records.append(
            {
                "name": name,
                "kind": "logical",
                "value": value,
                "size": len(value.encode("utf-8")),
                "sha256": hashlib.sha256(value.encode("utf-8")).hexdigest(),
            }
        )
    return records


def _output_is_decisional(name: str) -> bool:
    return name not in {
        "execution_progress.json",
        "dataset_manifest_snapshot.json",
        "config_snapshot.yaml",
    }


def _write_checksums(
    directory: Path,
    input_records: Sequence[Mapping[str, Any]],
) -> None:
    outputs = []
    for name in REQUIRED_OUTPUT_FILES:
        if name == "checksums.json":
            continue
        path = directory / name
        if not path.is_file():
            raise RuntimeError(f"Cannot checksum missing output: {name}")
        outputs.append(
            {
                "path": name,
                "size": path.stat().st_size,
                "sha256": _sha256_file(path),
                "decisional": _output_is_decisional(name),
            }
        )
    _write_json_atomic(
        directory / "checksums.json",
        {
            "algorithm": "SHA-256",
            "inputs": [dict(record) for record in input_records],
            "outputs": outputs,
            "exclusions_from_self_hash": ["checksums.json"],
        },
    )


def _verify_checksums(directory: Path) -> None:
    checksum_path = directory / "checksums.json"
    payload = json.loads(checksum_path.read_text(encoding="utf-8"))
    if payload.get("algorithm") != "SHA-256":
        raise RuntimeError("Unsupported checksum algorithm.")
    if payload.get("exclusions_from_self_hash") != ["checksums.json"]:
        raise RuntimeError("Checksum self-exclusion contract mismatch.")
    expected_names = set(REQUIRED_OUTPUT_FILES)
    actual_names = {path.name for path in directory.iterdir() if path.is_file()}
    if actual_names != expected_names:
        raise RuntimeError(
            f"Closed output contract mismatch: missing={sorted(expected_names - actual_names)}, "
            f"extra={sorted(actual_names - expected_names)}"
        )
    output_records = payload.get("outputs")
    if not isinstance(output_records, list) or {
        record.get("path") for record in output_records
    } != expected_names - {"checksums.json"}:
        raise RuntimeError("Output checksum inventory is incomplete.")
    for record in output_records:
        path = directory / str(record["path"])
        if path.stat().st_size != int(record["size"]):
            raise RuntimeError(f"Output size mismatch: {path.name}")
        if _sha256_file(path) != record["sha256"]:
            raise RuntimeError(f"Output checksum mismatch: {path.name}")
    input_records = payload.get("inputs")
    required_inputs = {
        "QQQ_curated_dataset",
        "SPY_curated_dataset",
        "QQQ_manifest",
        "SPY_manifest",
        "config_yaml",
        "canonical_payload_hash",
        "preregistration_freeze_commit",
        "execution_freeze_commit",
        "head_commit",
    }
    if not isinstance(input_records, list) or {
        record.get("name") for record in input_records
    } != required_inputs:
        raise RuntimeError("Input checksum inventory is incomplete.")
    for record in input_records:
        if record["kind"] == "file":
            path = Path(record["path"])
            if not path.is_file() or path.stat().st_size != int(record["size"]):
                raise RuntimeError(f"Input file missing or size mismatch: {record['name']}")
            digest = _sha256_file(path)
        elif record["kind"] == "logical":
            value = str(record["value"])
            if len(value.encode("utf-8")) != int(record["size"]):
                raise RuntimeError(f"Logical input size mismatch: {record['name']}")
            digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
        else:
            raise RuntimeError(f"Unknown checksum input kind: {record['kind']}")
        if digest != record["sha256"]:
            raise RuntimeError(f"Input checksum mismatch: {record['name']}")


def _write_artifacts(
    temp_dir: Path,
    *,
    run_manifest: dict[str, Any],
    manifest_snapshot: Mapping[str, Any],
    events: pd.DataFrame,
    exclusions: pd.DataFrame,
    path_metrics: pd.DataFrame,
    control: pd.DataFrame,
    aggregations: Mapping[str, Any],
) -> None:
    _write_json_atomic(temp_dir / "run_manifest.json", run_manifest)
    _write_json_atomic(temp_dir / "dataset_manifest_snapshot.json", manifest_snapshot)
    shutil.copyfile(CONFIG_PATH, temp_dir / "config_snapshot.yaml")
    frames = {
        "confirmed_events.csv": events,
        "event_exclusions.csv": exclusions,
        "path_metrics.csv": path_metrics,
        "unconditional_control.csv": control,
        "incremental_metrics.csv": aggregations["incremental_metrics"],
        "metrics_pooled.csv": aggregations["metrics_pooled"],
        "metrics_by_symbol.csv": aggregations["metrics_by_symbol"],
        "metrics_by_year.csv": aggregations["metrics_by_year"],
        "metrics_by_direction.csv": aggregations["metrics_by_direction"],
        "metrics_by_horizon.csv": aggregations["metrics_by_horizon"],
        "concentration_metrics.csv": aggregations["concentration_metrics"],
        "leave_one_out_metrics.csv": aggregations["leave_one_out_metrics"],
        "bootstrap_intervals.csv": aggregations["bootstrap_intervals"],
        "cost_threshold_comparison.csv": aggregations["cost_threshold_comparison"],
    }
    for name, frame in frames.items():
        _serialize_frame(frame).to_csv(temp_dir / name, index=False, lineterminator="\n")
    _write_json_atomic(temp_dir / "discovery_gate.json", aggregations["gate"])


def _atomic_rename(source: Path, destination: Path) -> None:
    source.replace(destination)


def run_discovery(
    request: DiscoveryRequest,
) -> dict[str, Any]:
    progress = ExecutionProgress()
    final_dir = DEFAULT_OUTPUT_DIR
    temp_dir: Path | None = None
    run_manifest: dict[str, Any] | None = None
    try:
        stage = progress.start("preflight")
        preflight = validate_discovery_preflight(request)
        progress.end(stage, output_rows=1)
        config = preflight["config"]
        if config.bootstrap_resamples != 10_000:
            raise PermissionError("Productive discovery requires canonical 10,000 resamples.")
        calendar = EquitySessionCalendar.us_equity()
        final_dir.parent.mkdir(parents=True, exist_ok=True)
        temp_dir = final_dir.parent / f".{final_dir.name}.tmp-{uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=False)
        progress.set_progress_path(temp_dir / "execution_progress.json")
        events_parts: list[pd.DataFrame] = []
        exclusions_parts: list[pd.DataFrame] = []
        event_objects: dict[str, tuple[Event, ...]] = {}
        five_by_symbol: dict[str, pd.DataFrame] = {}
        manifest_snapshot: dict[str, Any] = {}
        validated_by_symbol: dict[str, pd.DataFrame] = {}
        sessions_by_symbol: dict[str, SessionValidation] = {}
        temporal_reports: list[TemporalAccessReport] = []
        for symbol in SYMBOLS:
            stage = progress.start(f"load_{symbol}", symbol=symbol)
            raw_minute, temporal_report = load_bounded_dataset(
                DEFAULT_DATASET_PATHS[symbol]
            )
            minute_all = validate_minute_frame(raw_minute, symbol, calendar)
            temporal_reports.append(temporal_report)
            validated_by_symbol[symbol] = minute_all
            progress.end(stage, output_rows=len(minute_all))

            stage = progress.start(
                f"crop_discovery_period_{symbol}",
                symbol=symbol,
                input_rows=len(minute_all),
            )
            minute_discovery = crop_discovery_period(minute_all)
            progress.end(stage, output_rows=len(minute_discovery))

            stage = progress.start(
                f"build_{symbol}_daily_approved_sessions",
                symbol=symbol,
                input_rows=len(minute_all),
            )
            contract = preflight["manifest_contracts"][symbol]
            session_validation = build_daily_approved_sessions(
                minute_all,
                contract.excluded_sessions,
                calendar,
            )
            sessions_by_symbol[symbol] = session_validation
            progress.end(
                stage,
                output_rows=len(session_validation.daily_sessions),
                approved_sessions=len(session_validation.approved_session_dates),
                incomplete_sessions=len(session_validation.incomplete_session_dates),
            )

            stage = progress.start(
                f"resample_{symbol}_1m_to_5m",
                symbol=symbol,
                input_rows=len(minute_discovery),
            )
            five = resample_rth_1min_to_5min(minute_discovery)
            five_by_symbol[symbol] = five
            progress.end(stage, output_rows=len(five))

            stage = progress.start(
                f"detect_{symbol}_confirmed_events",
                symbol=symbol,
                input_rows=len(five),
            )
            events, exclusions, objects = detect_confirmed_events(
                symbol,
                minute_all,
                five,
                session_validation,
                config,
            )
            events_parts.append(events)
            exclusions_parts.append(exclusions)
            event_objects[symbol] = objects
            progress.end(stage, output_rows=len(events), exclusions=len(exclusions))
            manifest_snapshot[symbol] = {
                "manifest_path": _repo_relative(contract.manifest_path),
                "curated_file": _repo_relative(contract.dataset_path),
                "manifest": dict(contract.raw),
                "approved_sessions": sorted(
                    value.isoformat()
                    for value in session_validation.approved_session_dates
                ),
                "excluded_sessions": sorted(
                    value.isoformat()
                    for value in session_validation.manifest_excluded_dates
                ),
                "incomplete_sessions": sorted(
                    value.isoformat()
                    for value in session_validation.incomplete_session_dates
                ),
                "temporal_access_report": temporal_report.to_record(),
            }

        confirmed_events = (
            pd.concat(events_parts, ignore_index=True)
            if events_parts
            else pd.DataFrame()
        )
        event_exclusions = (
            pd.concat(exclusions_parts, ignore_index=True)
            if exclusions_parts
            else pd.DataFrame()
        )
        path_parts: list[pd.DataFrame] = []
        for symbol in SYMBOLS:
            symbol_events = (
                confirmed_events[confirmed_events["symbol"] == symbol]
                if not confirmed_events.empty
                else pd.DataFrame()
            )
            if symbol_events.empty:
                continue
            stage = progress.start(
                f"compute_{symbol}_path_metrics",
                symbol=symbol,
                input_rows=len(symbol_events),
                horizons=list(HORIZONS),
            )
            part = compute_path_metrics(
                symbol_events,
                event_objects[symbol],
                five_by_symbol[symbol],
                config,
                calendar,
            )
            path_parts.append(part)
            progress.end(stage, output_rows=len(part))
        path_metrics = (
            pd.concat(path_parts, ignore_index=True)
            if path_parts
            else pd.DataFrame()
        )
        if path_metrics.empty:
            raise ValueError("Discovery produced no path metrics.")

        stage = progress.start(
            "unconditional_control",
            input_rows=len(path_metrics),
            horizons=list(HORIZONS),
        )
        approved_by_symbol = {
            symbol: sessions_by_symbol[symbol].approved_session_dates
            for symbol in SYMBOLS
        }
        candidates = build_unconditional_candidates(
            path_metrics,
            five_by_symbol,
            approved_by_symbol,
            calendar,
        )
        path_metrics, control = attach_unconditional_control(
            path_metrics, candidates, config
        )
        control_groups = (
            candidates[
                ["symbol", "direction", "executable_timestamp", "horizon"]
            ]
            .drop_duplicates()
            .shape[0]
        )
        progress.end(
            stage,
            output_rows=len(control),
            groups_total=control_groups,
            groups_processed=control_groups,
        )

        temporal_report = derive_temporal_access_report(
            temporal_reports,
            confirmed_events,
            candidates,
            path_metrics,
        )
        causal_report = derive_causal_integrity_report(
            preflight["manifest_contracts"],
            validated_by_symbol,
            sessions_by_symbol,
            five_by_symbol,
            confirmed_events,
            path_metrics,
            candidates,
        )

        stage = progress.start(
            "aggregations_and_bootstrap",
            input_rows=len(path_metrics),
            groups_total=int(path_metrics["session_date"].nunique()),
            groups_processed=0,
            bootstrap_replicates_total=config.bootstrap_resamples,
            bootstrap_replicates_processed=0,
        )
        aggregations = aggregate_and_gate(
            path_metrics,
            config,
            causal_report,
            temporal_report,
            progress_callback=lambda **payload: progress.update(stage, **payload),
        )
        progress.end(
            stage,
            output_rows=sum(
                len(aggregations[key])
                for key in (
                    "incremental_metrics",
                    "metrics_by_symbol",
                    "metrics_by_year",
                    "metrics_by_direction",
                )
            ),
        )
        gate = aggregations["gate"]
        run_manifest = {
            "hypothesis_id": HYPOTHESIS_ID,
            "mode": "run_discovery",
            "period": "discovery_2022_2024",
            "requested_start": DISCOVERY_START,
            "requested_end": DISCOVERY_END,
            "symbols": list(SYMBOLS),
            "horizons": list(HORIZONS),
            "primary_horizon": config.primary_horizon_label,
            "conceptual_design_freeze_commit": CONCEPTUAL_DESIGN_FREEZE_COMMIT,
            "implementation_clarification_freeze_commit": (
                IMPLEMENTATION_CLARIFICATION_FREEZE_COMMIT
            ),
            "preregistration_freeze_commit": PREREGISTRATION_FREEZE_COMMIT,
            "execution_freeze_commit": request.expected_execution_freeze_commit,
            "head_commit": preflight["head_commit"],
            "canonical_payload_hash": request.expected_canonical_hash,
            "runtime_config_hash": canonical_payload_hash(canonical_payload(config)),
            "manifests": {
                symbol: _repo_relative(
                    preflight["manifest_contracts"][symbol].manifest_path
                )
                for symbol in SYMBOLS
            },
            "curated_files": {
                symbol: _repo_relative(
                    preflight["manifest_contracts"][symbol].dataset_path
                )
                for symbol in SYMBOLS
            },
            "approved_sessions": {
                symbol: len(sessions_by_symbol[symbol].approved_session_dates)
                for symbol in SYMBOLS
            },
            "excluded_sessions": {
                symbol: sorted(
                    value.isoformat()
                    for value in sessions_by_symbol[symbol].manifest_excluded_dates
                )
                for symbol in SYMBOLS
            },
            "temporal_access_report": temporal_report.to_record(),
            "causal_integrity_report": causal_report.to_record(),
            "event_study_executed": True,
            "discovery_executed": True,
            "validation_2025_executed": False,
            "historical_2026_executed": False,
            "results_written": False,
            "checksums_verified": False,
            "strategy_created": False,
            "orders_created": False,
            "position_sizing_used": False,
            "safety_flags": dict(config.safety_flags),
        }

        stage = progress.start(
            "atomic_write",
            input_rows=len(confirmed_events) + len(path_metrics),
        )
        _write_artifacts(
            temp_dir,
            run_manifest=run_manifest,
            manifest_snapshot=manifest_snapshot,
            events=confirmed_events,
            exclusions=event_exclusions,
            path_metrics=path_metrics,
            control=control,
            aggregations=aggregations,
        )
        input_records = _input_checksum_records(
            preflight["manifest_contracts"],
            execution_freeze_commit=str(request.expected_execution_freeze_commit),
        )
        _write_checksums(temp_dir, input_records)
        _verify_checksums(temp_dir)

        run_manifest["checksums_verified"] = True
        run_manifest["results_written"] = True
        _write_json_atomic(temp_dir / "run_manifest.json", run_manifest)
        progress.end(stage, output_rows=len(REQUIRED_OUTPUT_FILES), results_written=True)
        _write_checksums(temp_dir, input_records)
        _verify_checksums(temp_dir)
        _atomic_rename(temp_dir, final_dir)
        return {
            **run_manifest,
            "output_dir": str(final_dir),
            "confirmed_event_count": len(confirmed_events),
            "path_metric_rows": len(path_metrics),
            "gate_passed": bool(gate["passed"]),
        }
    except KeyboardInterrupt:
        progress.mark_interrupted(temp_dir=temp_dir)
        if temp_dir is not None and temp_dir.exists() and run_manifest is not None:
            run_manifest["results_written"] = False
            run_manifest["checksums_verified"] = False
            _write_json_atomic(temp_dir / "run_manifest.json", run_manifest)
        raise
    except Exception as exc:
        progress.mark_failed(exc, temp_dir=temp_dir)
        if temp_dir is not None and temp_dir.exists():
            if run_manifest is not None:
                run_manifest["results_written"] = False
                run_manifest["checksums_verified"] = False
                _write_json_atomic(temp_dir / "run_manifest.json", run_manifest)
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Governed discovery runner for HYP-DRIVE-PB-01."
    )
    parser.add_argument(
        "--mode",
        required=True,
        choices=("validate_implementation", "run_discovery"),
    )
    parser.add_argument("--expected-preregistration-commit")
    parser.add_argument("--expected-execution-freeze-commit")
    parser.add_argument("--expected-canonical-hash")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.mode == "run_discovery":
        missing = [
            flag
            for flag, value in (
                ("--expected-preregistration-commit", args.expected_preregistration_commit),
                ("--expected-execution-freeze-commit", args.expected_execution_freeze_commit),
                ("--expected-canonical-hash", args.expected_canonical_hash),
            )
            if not value
        ]
        if missing:
            parser.error(f"run_discovery requires: {', '.join(missing)}")
    request = DiscoveryRequest(
        mode=args.mode,
        expected_preregistration_commit=args.expected_preregistration_commit,
        expected_execution_freeze_commit=args.expected_execution_freeze_commit,
        expected_canonical_hash=args.expected_canonical_hash,
    )
    try:
        payload = (
            validate_implementation(request)
            if args.mode == "validate_implementation"
            else run_discovery(request)
        )
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(f"error: {exc}")
        return 1
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
