from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

import numpy as np
import pandas as pd
import yaml

from src.data.dataset_manifest import APPROVED_FOR_OR_FVG_BACKTEST
from src.research.hyp_first_candle_event_study import (
    EVENT_TYPES,
    HYPOTHESIS_ID,
    SAFETY_FLAGS,
    FcrEventStudyConfig,
    attach_bootstrap_intervals,
    aggregate_fcr_event_paths,
    canonical_event_config_hash,
    compute_fcr_event_paths,
    detect_fcr_event_study_events,
    load_approved_event_dataset,
    prepare_five_minute_frame,
    assert_no_strategy_columns,
)


CONFIG_PATH = Path("configs/research/hypotheses/HYP-FCR-EVENT-01.yaml")
DISCOVERY_START = "2022-01-01"
DISCOVERY_END = "2024-12-31"
DISCOVERY_PERIOD = "discovery_2022_2024"
EXPECTED_SYMBOLS = ("QQQ", "SPY")
EXPECTED_CANONICAL_HASH = "1b6ad06b974d996cdf6bd0a3a21eae097e94322e80fdec94c2cfc4ec3c18fe81"
CURATED_MANIFEST_PATHS = {
    "QQQ": Path("data/manifests/QQQ_1min_2022-01-01_2026-07-06_curated_manifest.json"),
    "SPY": Path("data/manifests/SPY_1min_2022-01-01_2026-07-06_curated_manifest.json"),
}
CURATED_DATASET_PATHS = {
    "QQQ": Path("data/curated/QQQ_1min_2022-01-01_2026-07-06_curated.csv"),
    "SPY": Path("data/curated/SPY_1min_2022-01-01_2026-07-06_curated.csv"),
}
DEFAULT_OUTPUT_DIR = Path("artifacts/research/HYP-FCR-EVENT-01/discovery_2022_2024")
BOOTSTRAP_SEED = 17
REQUIRED_OUTPUT_FILES = (
    "run_manifest.json",
    "dataset_manifest_snapshot.json",
    "config_snapshot.yaml",
    "events.csv",
    "path_metrics.csv",
    "aggregate_metrics.csv",
    "metrics_by_symbol.csv",
    "metrics_by_year.csv",
    "metrics_by_event.csv",
    "metrics_by_horizon.csv",
    "bootstrap_intervals.csv",
    "economic_threshold_comparison.csv",
    "classification.json",
    "execution_progress.json",
    "checksums.json",
)
ALLOWED_CLASSIFICATIONS = {
    "no_effect_detected",
    "weak_unstable_effect",
    "stable_but_not_economic",
    "hypothesis_generating_signal",
}
SPY_FAILED_ANNUAL_MANIFEST_PATH = Path(
    "data/manifests/SPY_1min_2023-01-01_2023-12-31_alpaca_sip_raw_rth_manifest.json"
)
FULL_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
MAX_BENCHMARK_SESSIONS_PER_SYMBOL = 10


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _process_memory_mb() -> float | None:
    try:
        import psutil  # type: ignore

        return float(psutil.Process().memory_info().rss / (1024 * 1024))
    except Exception:
        pass
    try:
        import ctypes
        from ctypes import wintypes

        class ProcessMemoryCounters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(ProcessMemoryCounters)
        ctypes.windll.kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        handle = ctypes.windll.kernel32.GetCurrentProcess()
        psapi = ctypes.WinDLL("psapi.dll")
        psapi.GetProcessMemoryInfo.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(ProcessMemoryCounters),
            wintypes.DWORD,
        ]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        if psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
            return float(counters.WorkingSetSize / (1024 * 1024))
    except Exception:
        pass
    try:
        import resource

        usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return float(usage / 1024)
    except Exception:
        return None


class ExecutionProgress:
    def __init__(self, *, progress_path: Path | None = None, emit_console: bool = True) -> None:
        self.progress_path = progress_path
        self.emit_console = emit_console
        self.stages: list[dict[str, Any]] = []

    def set_progress_path(self, progress_path: Path) -> None:
        self.progress_path = progress_path
        self.persist()

    def start(
        self,
        stage: str,
        *,
        input_rows: int | None = None,
        output_rows: int | None = None,
        progress_current: int | None = None,
        progress_total: int | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        record = {
            "stage": stage,
            "status": "running",
            "start_time": _utc_now_iso(),
            "end_time": None,
            "elapsed_seconds": None,
            "input_rows": input_rows,
            "output_rows": output_rows,
            "memory_mb": _process_memory_mb(),
            "progress_current": progress_current,
            "progress_total": progress_total,
            "_perf_start": time.perf_counter(),
        }
        if extra:
            record.update(extra)
        self.stages.append(record)
        self._emit(record)
        self.persist()
        return record

    def end(
        self,
        record: dict[str, Any],
        *,
        output_rows: int | None = None,
        input_rows: int | None = None,
        status: str = "completed",
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if input_rows is not None:
            record["input_rows"] = input_rows
        if output_rows is not None:
            record["output_rows"] = output_rows
        record["status"] = status
        record["end_time"] = _utc_now_iso()
        record["elapsed_seconds"] = round(float(time.perf_counter() - record.pop("_perf_start", time.perf_counter())), 6)
        record["memory_mb"] = _process_memory_mb()
        if extra:
            record.update(extra)
        self._emit(record)
        self.persist()
        return record

    def mark_interrupted(self, *, temp_dir: Path | None = None, policy: str = "delete_temp_dir") -> None:
        record = {
            "stage": "interrupt",
            "status": "interrupted",
            "start_time": _utc_now_iso(),
            "end_time": _utc_now_iso(),
            "elapsed_seconds": 0.0,
            "input_rows": None,
            "output_rows": None,
            "memory_mb": _process_memory_mb(),
            "progress_current": None,
            "progress_total": None,
            "interrupted": True,
            "results_written": False,
            "temp_dir": str(temp_dir) if temp_dir is not None else None,
            "temp_dir_policy": policy,
        }
        self.stages.append(record)
        self._emit(record)
        self.persist()

    def summary(self) -> dict[str, Any]:
        stages = [{key: value for key, value in record.items() if key != "_perf_start"} for record in self.stages]
        return {
            "schema_version": 1,
            "generated_at": _utc_now_iso(),
            "stages": stages,
        }

    def persist(self) -> None:
        if self.progress_path is None:
            return
        payload = self.summary()
        self.progress_path.parent.mkdir(parents=True, exist_ok=True)
        self.progress_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True, default=str, allow_nan=False),
            encoding="utf-8",
        )

    def _emit(self, record: dict[str, Any]) -> None:
        if not self.emit_console:
            return
        printable = {key: value for key, value in record.items() if key != "_perf_start"}
        print(json.dumps({"execution_progress": printable}, sort_keys=True, default=str), flush=True)


@dataclass(frozen=True)
class RuntimeState:
    head_commit: str
    working_tree_clean: bool


@dataclass(frozen=True)
class FcrEventDiscoveryRequest:
    mode: Literal["prepare_only", "run_discovery", "profile_synthetic", "benchmark_subset"] = "prepare_only"
    expected_freeze_commit: str = ""
    expected_canonical_hash: str = ""
    max_sessions_per_symbol: int | None = None
    debug: bool = False
    period: str = DISCOVERY_PERIOD
    symbols: tuple[str, ...] = EXPECTED_SYMBOLS
    requested_start: str = DISCOVERY_START
    requested_end: str = DISCOVERY_END
    config_path: Path = CONFIG_PATH
    dataset_paths: dict[str, Path] | None = None
    preregistered_canonical_hash: str = EXPECTED_CANONICAL_HASH
    manifest_paths: dict[str, Path] | None = None
    spy_failed_annual_manifest_path: Path = SPY_FAILED_ANNUAL_MANIFEST_PATH
    safety_flags: dict[str, bool] | None = None


def collect_runtime_state(cwd: str | Path = Path(".")) -> RuntimeState:
    root = Path(cwd)
    status = subprocess.check_output(
        ["git", "status", "--porcelain"],
        cwd=root,
        text=True,
    )
    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        text=True,
    ).strip()
    return RuntimeState(head_commit=head, working_tree_clean=status.strip() == "")


def _read_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _read_yaml(path: str | Path) -> dict[str, Any]:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Config payload must be a mapping: {path}")
    return payload


def _reject_placeholder_or_empty_commit(value: str) -> None:
    if not value:
        raise PermissionError("--expected-freeze-commit is required for run_discovery.")
    if value == "<EVENT_FREEZE_COMMIT>" or value.startswith("<") or value.endswith(">"):
        raise PermissionError("Freeze commit placeholders are not accepted.")
    if not FULL_GIT_SHA_RE.fullmatch(value):
        raise PermissionError("--expected-freeze-commit must be a full 40-character git SHA.")


def _reject_bad_canonical_hash(value: str) -> None:
    if not value:
        raise PermissionError("--expected-canonical-hash is required for run_discovery.")
    if not SHA256_RE.fullmatch(value):
        raise PermissionError("--expected-canonical-hash must be a full SHA-256 hex digest.")


def _path_looks_curated(path: str | Path) -> bool:
    normalized = str(path).replace("\\", "/").lower()
    return "/data/curated/" in f"/{normalized}" or normalized.startswith("data/curated/")


def validate_curated_manifest_metadata(
    symbol: str,
    manifest_path: str | Path,
    *,
    failed_annual_manifest_path: str | Path | None = None,
) -> dict[str, Any]:
    symbol = symbol.upper()
    candidate = Path(manifest_path)
    if not candidate.name.endswith("_curated_manifest.json"):
        raise PermissionError(f"{symbol} final dataset manifest must be a curated manifest: {candidate}")
    payload = _read_json(candidate)
    if payload.get("symbol") != symbol:
        raise ValueError(f"{symbol} manifest symbol mismatch.")
    if payload.get("timeframe") != "1min":
        raise ValueError(f"{symbol} manifest timeframe must be 1min.")
    if payload.get("dataset_status") != APPROVED_FOR_OR_FVG_BACKTEST:
        raise PermissionError(f"{symbol} curated manifest is not approved.")
    if payload.get("audit_apt_for_or_fvg_backtest") is not True:
        raise PermissionError(f"{symbol} curated manifest audit flag is not approved.")
    if payload.get("audit_critical_warnings") not in ([], None):
        raise PermissionError(f"{symbol} curated manifest has critical warnings.")
    if payload.get("rth_only") is not True:
        raise PermissionError(f"{symbol} curated manifest must be RTH-only.")
    if payload.get("source_timezone") != "America/New_York":
        raise PermissionError(f"{symbol} curated manifest timezone mismatch.")
    if payload.get("start") > DISCOVERY_START or payload.get("end") < DISCOVERY_END:
        raise PermissionError(f"{symbol} curated manifest does not cover the discovery window.")
    for field in ("input_file", "output_file", "curated_file"):
        if not _path_looks_curated(payload.get(field, "")):
            raise PermissionError(f"{symbol} manifest {field} must point at data/curated.")
    for field in ("broker_connected", "orders_sent", "live_trading_enabled", "paper_broker_enabled"):
        if payload.get(field) is not False:
            raise PermissionError(f"{symbol} manifest safety field is not false: {field}")
    project_safety = payload.get("project_safety_state") or {}
    for field in ("broker_connected", "orders_sent", "live_trading"):
        if project_safety.get(field) is not False:
            raise PermissionError(f"{symbol} project safety field is not false: {field}")

    excluded_sessions = payload.get("excluded_sessions") or []
    if symbol == "QQQ" and excluded_sessions:
        raise PermissionError("QQQ curated manifest has unexpected discovery exclusions.")
    if symbol == "SPY":
        matching = [
            item
            for item in excluded_sessions
            if item.get("symbol") == "SPY"
            and item.get("date") == "2023-06-05"
            and item.get("policy") == "exclude_entire_session"
        ]
        if len(matching) != 1:
            raise PermissionError("SPY curated manifest must exclude 2023-06-05 exactly once.")
        if payload.get("total_excluded_sessions") != 1:
            raise PermissionError("SPY curated manifest must record one excluded session.")
        if failed_annual_manifest_path is not None:
            annual = _read_json(failed_annual_manifest_path)
            if annual.get("symbol") != "SPY" or annual.get("dataset_status") != "failed_audit":
                raise PermissionError("SPY annual raw 2023 manifest must remain failed_audit.")

    return {
        "symbol": symbol,
        "manifest_path": str(candidate),
        "dataset_status": payload.get("dataset_status"),
        "sha256": payload.get("sha256"),
        "curated_file": payload.get("curated_file"),
        "total_excluded_sessions": payload.get("total_excluded_sessions", 0),
        "excluded_sessions": excluded_sessions,
    }


def validate_event_config_payload(config_path: str | Path) -> dict[str, Any]:
    payload = _read_yaml(config_path)
    if payload.get("hypothesis_id") != HYPOTHESIS_ID:
        raise PermissionError("Operational runner is locked to HYP-FCR-EVENT-01.")
    if payload.get("type") != "event_study":
        raise PermissionError("HYP-FCR-EVENT-01 must remain type=event_study.")
    if payload.get("strategy_status") != "non_strategy":
        raise PermissionError("HYP-FCR-EVENT-01 must remain non_strategy.")
    if tuple(payload.get("symbols", [])) != EXPECTED_SYMBOLS:
        raise PermissionError("HYP-FCR-EVENT-01 symbols must remain exactly QQQ and SPY.")
    discovery = (payload.get("periods") or {}).get(DISCOVERY_PERIOD) or {}
    if discovery.get("start") != DISCOVERY_START or discovery.get("end") != DISCOVERY_END:
        raise PermissionError("Discovery period must remain exactly 2022-01-01 through 2024-12-31.")
    if "2025" in json.dumps(payload.get("periods", {})) and (
        (payload.get("periods") or {}).get("validation_2025", {}).get("status") != "blocked_not_opened"
    ):
        raise PermissionError("2025 must remain blocked_not_opened.")
    if (payload.get("periods") or {}).get("parity_debug_2026", {}).get("status") != "blocked_not_opened":
        raise PermissionError("2026 must remain blocked_not_opened.")
    constraints = payload.get("event_constraints") or {}
    for field in ("no_entries", "no_exits", "no_stops", "no_targets", "no_position_sizing", "no_pnl"):
        if constraints.get(field) is not True:
            raise PermissionError(f"Event-study non-strategy constraint missing: {field}")
    for field, value in (payload.get("safety_flags") or {}).items():
        if value is not False:
            raise PermissionError(f"Safety flag must remain false: {field}")
    return payload


def validate_discovery_preflight(
    request: FcrEventDiscoveryRequest,
    *,
    runtime_state: RuntimeState | None = None,
) -> dict[str, Any]:
    if request.mode == "prepare_only":
        return prepare_only_manifest(request)
    if request.mode not in ("run_discovery", "benchmark_subset"):
        raise PermissionError(f"Unsupported HYP-FCR-EVENT-01 mode: {request.mode}")
    if request.mode == "benchmark_subset":
        if request.max_sessions_per_symbol is None:
            raise PermissionError("--max-sessions-per-symbol is required for benchmark_subset.")
        if request.max_sessions_per_symbol < 1 or request.max_sessions_per_symbol > MAX_BENCHMARK_SESSIONS_PER_SYMBOL:
            raise PermissionError(
                f"benchmark_subset is capped at {MAX_BENCHMARK_SESSIONS_PER_SYMBOL} sessions per symbol."
            )
    _reject_placeholder_or_empty_commit(request.expected_freeze_commit)
    _reject_bad_canonical_hash(request.expected_canonical_hash)
    runtime_state = runtime_state or collect_runtime_state()
    if not runtime_state.working_tree_clean:
        raise PermissionError("Working tree must be clean before run_discovery.")
    if runtime_state.head_commit != request.expected_freeze_commit:
        raise PermissionError("HEAD does not match --expected-freeze-commit.")
    actual_hash = canonical_event_config_hash(request.config_path)
    if actual_hash != request.expected_canonical_hash:
        raise PermissionError("Canonical payload hash mismatch.")
    if actual_hash != request.preregistered_canonical_hash:
        raise PermissionError("Canonical payload hash does not match the preregistered value.")
    if request.period != DISCOVERY_PERIOD or "2025" in request.period or "2026" in request.period or "holdout" in request.period:
        raise PermissionError("Only discovery_2022_2024 is allowed for HYP-FCR-EVENT-01.")
    if tuple(request.symbols) != EXPECTED_SYMBOLS:
        raise PermissionError("Requested symbols must be exactly QQQ and SPY.")
    if request.requested_start != DISCOVERY_START or request.requested_end != DISCOVERY_END:
        raise PermissionError("Requested discovery range must be exactly 2022-01-01 through 2024-12-31.")
    if any(bool(value) for value in (request.safety_flags or SAFETY_FLAGS).values()):
        raise PermissionError("Operational safety flags must remain false.")
    validate_event_config_payload(request.config_path)
    manifest_paths = request.manifest_paths or CURATED_MANIFEST_PATHS
    if tuple(manifest_paths.keys()) != EXPECTED_SYMBOLS:
        raise PermissionError("Manifest resolution must be exactly QQQ then SPY.")
    manifest_summary = {
        symbol: validate_curated_manifest_metadata(
            symbol,
            manifest_paths[symbol],
            failed_annual_manifest_path=request.spy_failed_annual_manifest_path if symbol == "SPY" else None,
        )
        for symbol in EXPECTED_SYMBOLS
    }
    return {
        "hypothesis_id": HYPOTHESIS_ID,
        "mode": request.mode,
        "preflight_passed": True,
        "event_study_executed": False,
        "results_written": False,
        "head_commit": runtime_state.head_commit,
        "canonical_payload_hash": actual_hash,
        "requested_start": request.requested_start,
        "requested_end": request.requested_end,
        "symbols": list(request.symbols),
        "manifest_summary": manifest_summary,
        "safety_flags": dict(request.safety_flags or SAFETY_FLAGS),
        "orders_sent": False,
        "position_sizing_used": False,
        "paper_broker_enabled": False,
        "live_trading": False,
        "broker_connected": False,
    }


def prepare_only_manifest(request: FcrEventDiscoveryRequest | None = None) -> dict[str, Any]:
    request = request or FcrEventDiscoveryRequest()
    if request.mode != "prepare_only":
        raise PermissionError("prepare_only_manifest only accepts prepare_only mode.")
    return {
        "hypothesis_id": HYPOTHESIS_ID,
        "mode": "prepare_only",
        "event_study_executed": False,
        "results_written": False,
        "orders_sent": False,
        "position_sizing_used": False,
        "paper_eligible": False,
        "live_eligible": False,
        "validation_2025_executed": False,
        "parity_2026_executed": False,
        "holdout_executed": False,
        "safety_flags": dict(request.safety_flags or SAFETY_FLAGS),
    }


def _parse_iso_date(value: str) -> date:
    return date.fromisoformat(value)


def _local_dates(frame: pd.DataFrame) -> pd.Series:
    return pd.to_datetime(frame["timestamp"], utc=True).dt.tz_convert("America/New_York").dt.date


def filter_discovery_analytic_frame(frame: pd.DataFrame, symbol: str) -> pd.DataFrame:
    start = _parse_iso_date(DISCOVERY_START)
    end = _parse_iso_date(DISCOVERY_END)
    local_dates = _local_dates(frame)
    filtered = frame.loc[(local_dates >= start) & (local_dates <= end)].copy()
    filtered_dates = _local_dates(filtered) if not filtered.empty else pd.Series(dtype=object)
    if any(item.year >= 2025 for item in filtered_dates):
        raise AssertionError("Analytic frame contains blocked 2025/2026 rows.")
    if symbol.upper() == "SPY" and any(str(item) == "2023-06-05" for item in filtered_dates):
        raise AssertionError("SPY 2023-06-05 must remain excluded from the analytic frame.")
    return filtered.reset_index(drop=True)


def limit_analytic_sessions(frame: pd.DataFrame, max_sessions: int) -> pd.DataFrame:
    if max_sessions < 1 or max_sessions > MAX_BENCHMARK_SESSIONS_PER_SYMBOL:
        raise PermissionError(f"Benchmark subset is capped at {MAX_BENCHMARK_SESSIONS_PER_SYMBOL} sessions.")
    local_dates = _local_dates(frame)
    selected = set(sorted(local_dates.astype(str).unique().tolist())[:max_sessions])
    limited = frame.loc[local_dates.astype(str).isin(selected)].copy()
    return limited.reset_index(drop=True)


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str, allow_nan=False), encoding="utf-8")


def _sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest_record(manifest: Any) -> dict[str, Any]:
    if hasattr(manifest, "to_record"):
        return dict(manifest.to_record())
    if hasattr(manifest, "__dict__"):
        return dict(manifest.__dict__)
    if isinstance(manifest, dict):
        return dict(manifest)
    raise TypeError(f"Unsupported manifest object: {type(manifest)!r}")


def _serializable_frame(frame: pd.DataFrame) -> pd.DataFrame:
    serializable = frame.copy()
    for column in serializable.columns:
        if pd.api.types.is_datetime64_any_dtype(serializable[column]):
            serializable[column] = serializable[column].map(lambda value: value.isoformat() if pd.notna(value) else "")
    return serializable


def _empty_frame_with_header(columns: list[str]) -> pd.DataFrame:
    return pd.DataFrame(columns=columns)


def _classify_effect(aggregate_metrics: pd.DataFrame) -> dict[str, Any]:
    if aggregate_metrics.empty or aggregate_metrics["available_count"].sum() == 0:
        classification = "no_effect_detected"
    else:
        available = aggregate_metrics.loc[aggregate_metrics["available_count"] > 0].copy()
        stable = available.loc[
            (available["bootstrap_reversal_mean_ci_low"] > 0)
            | (available["bootstrap_reversal_mean_ci_high"] < 0)
        ]
        strong = stable.loc[stable["session_count"] >= 20]
        if not strong.empty and strong["symbol"].nunique() >= 2 and strong["year"].nunique() >= 2:
            classification = "hypothesis_generating_signal"
        elif not stable.empty:
            classification = "stable_but_not_economic"
        elif available["mean_reversal_return"].abs().max() > 0:
            classification = "weak_unstable_effect"
        else:
            classification = "no_effect_detected"
    if classification not in ALLOWED_CLASSIFICATIONS:
        raise AssertionError(f"Unsupported diagnostic classification: {classification}")
    return {
        "hypothesis_id": HYPOTHESIS_ID,
        "classification": classification,
        "allowed_classifications": sorted(ALLOWED_CLASSIFICATIONS),
        "strategy_created": False,
        "validation_2025_unlocked": False,
        "paper_enabled": False,
        "live_enabled": False,
    }


def _economic_threshold_comparison(aggregate_metrics: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "event_type",
        "horizon",
        "symbol",
        "orientation",
        "year",
        "mean_reversal_return",
        "economic_threshold_applicable",
        "economic_threshold_passed",
        "reason",
    ]
    if aggregate_metrics.empty:
        return _empty_frame_with_header(columns)
    rows = aggregate_metrics.loc[:, ["event_type", "horizon", "symbol", "orientation", "year", "mean_reversal_return"]].copy()
    rows["economic_threshold_applicable"] = False
    rows["economic_threshold_passed"] = False
    rows["reason"] = "non_strategy_event_study_no_pnl_no_cost_model"
    return rows.loc[:, columns]


def _bootstrap_intervals(aggregate_metrics: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "event_type",
        "horizon",
        "symbol",
        "orientation",
        "year",
        "bootstrap_reversal_mean_ci_low",
        "bootstrap_reversal_mean_ci_high",
        "bootstrap_grouped_by",
        "bootstrap_seed",
    ]
    if aggregate_metrics.empty:
        return _empty_frame_with_header(columns)
    return aggregate_metrics.loc[:, columns].copy()


def _write_checksums(output_dir: Path, input_paths: list[Path], output_names: tuple[str, ...]) -> None:
    diagnostic_outputs = {"checksums.json", "execution_progress.json"}
    outputs = [output_dir / name for name in output_names if name not in diagnostic_outputs]
    payload = {
        "inputs": [{"path": str(path), "sha256": _sha256_file(path)} for path in input_paths if path.exists()],
        "outputs": [{"path": path.name, "sha256": _sha256_file(path)} for path in outputs if path.exists()],
    }
    _write_json(output_dir / "checksums.json", payload)


def _verify_required_outputs(output_dir: Path) -> None:
    missing = [name for name in REQUIRED_OUTPUT_FILES if not (output_dir / name).exists()]
    if missing:
        raise FileNotFoundError(f"Missing HYP-FCR-EVENT-01 output(s): {missing}")
    unexpected = sorted(path.name for path in output_dir.iterdir() if path.is_file() and path.name not in REQUIRED_OUTPUT_FILES)
    if unexpected:
        raise AssertionError(f"Unexpected HYP-FCR-EVENT-01 output(s): {unexpected}")


def _execute_event_study_outputs(
    preflight_payload: dict[str, Any],
    request: FcrEventDiscoveryRequest,
    *,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    dataset_loader=load_approved_event_dataset,
    bootstrap_seed: int = BOOTSTRAP_SEED,
    n_bootstrap: int = 500,
    progress: ExecutionProgress | None = None,
    benchmark_only: bool = False,
) -> dict[str, Any]:
    final_dir = Path(output_dir)
    if not benchmark_only and final_dir.exists() and any(final_dir.iterdir()):
        raise FileExistsError(f"Discovery output directory already exists and is not empty: {final_dir}")
    final_dir.parent.mkdir(parents=True, exist_ok=True)
    temp_label = "benchmark" if benchmark_only else "tmp"
    temp_dir = final_dir.parent / f".{final_dir.name}.{temp_label}-{uuid4().hex}"
    progress = progress or ExecutionProgress()
    config = FcrEventStudyConfig()
    dataset_paths = request.dataset_paths or CURATED_DATASET_PATHS
    manifest_paths = request.manifest_paths or CURATED_MANIFEST_PATHS
    all_events: list[pd.DataFrame] = []
    all_paths: list[pd.DataFrame] = []
    dataset_snapshot: dict[str, Any] = {}
    analytic_frame_rows: dict[str, Any] = {}

    try:
        temp_dir.mkdir(parents=True, exist_ok=False)
        progress.set_progress_path(temp_dir / "execution_progress.json")
        shutil.copyfile(request.config_path, temp_dir / "config_snapshot.yaml")
        for symbol_index, symbol in enumerate(EXPECTED_SYMBOLS, start=1):
            load_stage = progress.start(
                f"load_{symbol}",
                progress_current=symbol_index,
                progress_total=len(EXPECTED_SYMBOLS),
                extra={"symbol": symbol},
            )
            minute_frame, manifest = dataset_loader(symbol, dataset_paths[symbol], manifest_paths[symbol])
            progress.end(load_stage, output_rows=len(minute_frame))

            crop_stage = progress.start(
                "temporal_crop",
                input_rows=len(minute_frame),
                progress_current=symbol_index,
                progress_total=len(EXPECTED_SYMBOLS),
                extra={"symbol": symbol},
            )
            analytic = filter_discovery_analytic_frame(minute_frame, symbol)
            if benchmark_only:
                if request.max_sessions_per_symbol is None:
                    raise PermissionError("--max-sessions-per-symbol is required for benchmark_subset.")
                analytic = limit_analytic_sessions(analytic, request.max_sessions_per_symbol)
            progress.end(crop_stage, output_rows=len(analytic))

            resample_stage = progress.start(
                "resample_1m_to_5m",
                input_rows=len(analytic),
                progress_current=symbol_index,
                progress_total=len(EXPECTED_SYMBOLS),
                extra={"symbol": symbol},
            )
            five_minute = prepare_five_minute_frame(analytic)
            progress.end(resample_stage, output_rows=len(five_minute))

            detection_stage = progress.start(
                "detect_events",
                input_rows=len(five_minute),
                progress_current=symbol_index,
                progress_total=len(EXPECTED_SYMBOLS),
                extra={"symbol": symbol, "event_types": list(EVENT_TYPES)},
            )
            events = detect_fcr_event_study_events(five_minute, symbol, config)
            progress.end(detection_stage, output_rows=len(events))

            path_stage = progress.start(
                "path_metrics",
                input_rows=len(events),
                progress_current=symbol_index,
                progress_total=len(EXPECTED_SYMBOLS),
                extra={"symbol": symbol, "horizons": list(config.horizons)},
            )
            paths = compute_fcr_event_paths(five_minute, events, config, horizons=config.horizons)
            progress.end(path_stage, output_rows=len(paths))

            assert_no_strategy_columns(events)
            assert_no_strategy_columns(paths)
            if not events.empty and not set(events["event_type"]).issubset(set(EVENT_TYPES)):
                raise AssertionError("Detected event type outside preregistered EVENT-01 through EVENT-10.")
            all_events.append(events)
            all_paths.append(paths)
            sessions = sorted(_local_dates(analytic).astype(str).unique().tolist()) if not analytic.empty else []
            manifest_record = _manifest_record(manifest)
            analytic_frame_rows[symbol] = {
                "requested_start": DISCOVERY_START,
                "requested_end": DISCOVERY_END,
                "effective_start": sessions[0] if sessions else "",
                "effective_end": sessions[-1] if sessions else "",
                "rows_1m": int(len(analytic)),
                "bars_5m": int(len(five_minute)),
                "session_count": len(sessions),
                "contains_2025_or_2026": False,
            }
            dataset_snapshot[symbol] = {
                "dataset_path": str(dataset_paths[symbol]),
                "manifest_path": str(manifest_paths[symbol]),
                "manifest": manifest_record,
                "analytic_frame": analytic_frame_rows[symbol],
            }

        events_frame = pd.concat(all_events, ignore_index=True) if all_events else pd.DataFrame()
        paths_frame = pd.concat(all_paths, ignore_index=True) if all_paths else pd.DataFrame()
        if not events_frame.empty:
            events_frame = events_frame.sort_values(["symbol", "session_date", "event_type", "event_time"]).reset_index(drop=True)
        if not paths_frame.empty:
            paths_frame = paths_frame.sort_values(["symbol", "session_date", "event_type", "event_time", "horizon"]).reset_index(drop=True)
        assert_no_strategy_columns(events_frame)
        assert_no_strategy_columns(paths_frame)

        aggregate_groups = {
            "aggregate_metrics": ("event_type", "horizon", "symbol", "orientation", "year"),
            "metrics_by_symbol": ("symbol",),
            "metrics_by_year": ("year",),
            "metrics_by_event": ("event_type",),
            "metrics_by_horizon": ("horizon",),
        }
        aggregate_stage = progress.start("aggregations_base", input_rows=len(paths_frame), progress_current=0, progress_total=len(aggregate_groups))
        aggregate_metrics = aggregate_fcr_event_paths(
            paths_frame,
            group_by=aggregate_groups["aggregate_metrics"],
            n_bootstrap=n_bootstrap,
            seed=bootstrap_seed,
            include_bootstrap=False,
        )
        metrics_by_symbol = aggregate_fcr_event_paths(paths_frame, group_by=aggregate_groups["metrics_by_symbol"], n_bootstrap=n_bootstrap, seed=bootstrap_seed, include_bootstrap=False)
        metrics_by_year = aggregate_fcr_event_paths(paths_frame, group_by=aggregate_groups["metrics_by_year"], n_bootstrap=n_bootstrap, seed=bootstrap_seed, include_bootstrap=False)
        metrics_by_event = aggregate_fcr_event_paths(paths_frame, group_by=aggregate_groups["metrics_by_event"], n_bootstrap=n_bootstrap, seed=bootstrap_seed, include_bootstrap=False)
        metrics_by_horizon = aggregate_fcr_event_paths(paths_frame, group_by=aggregate_groups["metrics_by_horizon"], n_bootstrap=n_bootstrap, seed=bootstrap_seed, include_bootstrap=False)
        aggregate_output_rows = int(sum(len(frame) for frame in [aggregate_metrics, metrics_by_symbol, metrics_by_year, metrics_by_event, metrics_by_horizon]))
        progress.end(aggregate_stage, output_rows=aggregate_output_rows, extra={"group_count": len(aggregate_groups)})

        bootstrap_stage = progress.start(
            "bootstrap",
            input_rows=len(paths_frame),
            progress_current=0,
            progress_total=len(aggregate_groups),
            extra={"bootstrap_seed": int(bootstrap_seed), "n_bootstrap": int(n_bootstrap), "grouped_by": "session_date"},
        )
        aggregate_metrics = attach_bootstrap_intervals(aggregate_metrics, paths_frame, group_by=aggregate_groups["aggregate_metrics"], n_bootstrap=n_bootstrap, seed=bootstrap_seed)
        metrics_by_symbol = attach_bootstrap_intervals(metrics_by_symbol, paths_frame, group_by=aggregate_groups["metrics_by_symbol"], n_bootstrap=n_bootstrap, seed=bootstrap_seed)
        metrics_by_year = attach_bootstrap_intervals(metrics_by_year, paths_frame, group_by=aggregate_groups["metrics_by_year"], n_bootstrap=n_bootstrap, seed=bootstrap_seed)
        metrics_by_event = attach_bootstrap_intervals(metrics_by_event, paths_frame, group_by=aggregate_groups["metrics_by_event"], n_bootstrap=n_bootstrap, seed=bootstrap_seed)
        metrics_by_horizon = attach_bootstrap_intervals(metrics_by_horizon, paths_frame, group_by=aggregate_groups["metrics_by_horizon"], n_bootstrap=n_bootstrap, seed=bootstrap_seed)
        progress.end(bootstrap_stage, output_rows=aggregate_output_rows)

        bootstrap_intervals = _bootstrap_intervals(aggregate_metrics)
        economic_thresholds = _economic_threshold_comparison(aggregate_metrics)
        classification: dict[str, Any] | None = None
        if not benchmark_only:
            classification_stage = progress.start("classification", input_rows=len(aggregate_metrics))
            classification = _classify_effect(aggregate_metrics)
            for value in classification.values():
                if isinstance(value, str) and value.startswith("candidate_strategy"):
                    raise AssertionError("Event study must not create a strategy classification.")
            progress.end(classification_stage, output_rows=1, extra={"classification": classification["classification"]})

        run_manifest = {
            "hypothesis_id": HYPOTHESIS_ID,
            "mode": "benchmark_subset" if benchmark_only else "run_discovery",
            "period": DISCOVERY_PERIOD,
            "preflight_passed": True,
            "event_study_executed": not benchmark_only,
            "results_written": False,
            "benchmark_only": bool(benchmark_only),
            "requested_start": DISCOVERY_START,
            "requested_end": DISCOVERY_END,
            "symbols": list(EXPECTED_SYMBOLS),
            "event_types_executed": list(EVENT_TYPES),
            "horizons": list(config.horizons),
            "bootstrap_seed": int(bootstrap_seed),
            "bootstrap_grouped_by": "session_date",
            "canonical_payload_hash": preflight_payload["canonical_payload_hash"],
            "head_commit": preflight_payload["head_commit"],
            "analytic_frame_rows": analytic_frame_rows,
            "classification": None if classification is None else classification["classification"],
            "validation_2025_executed": False,
            "parity_2026_executed": False,
            "holdout_executed": False,
            "validation_2025_unlocked": False,
            "paper_eligible": False,
            "live_eligible": False,
            "orders_sent": False,
            "position_sizing_used": False,
            "paper_broker_enabled": False,
            "live_trading": False,
            "broker_connected": False,
            "safety_flags": dict(request.safety_flags or SAFETY_FLAGS),
            "documentation_updated": False,
            "registry_updated": False,
        }

        write_stage = progress.start("writing_and_checksums", input_rows=int(len(events_frame) + len(paths_frame) + aggregate_output_rows))
        if benchmark_only:
            _write_json(temp_dir / "benchmark_manifest.json", run_manifest)
            progress.end(write_stage, output_rows=2, extra={"diagnostic_files": ["benchmark_manifest.json", "execution_progress.json"]})
            return {
                "run_manifest": run_manifest,
                "diagnostic_dir": str(temp_dir),
                "benchmark_only": True,
                "event_count": int(len(events_frame)),
                "path_metric_rows": int(len(paths_frame)),
                "results_written": False,
            }

        _serializable_frame(events_frame).to_csv(temp_dir / "events.csv", index=False)
        _serializable_frame(paths_frame).to_csv(temp_dir / "path_metrics.csv", index=False)
        aggregate_metrics.to_csv(temp_dir / "aggregate_metrics.csv", index=False)
        metrics_by_symbol.to_csv(temp_dir / "metrics_by_symbol.csv", index=False)
        metrics_by_year.to_csv(temp_dir / "metrics_by_year.csv", index=False)
        metrics_by_event.to_csv(temp_dir / "metrics_by_event.csv", index=False)
        metrics_by_horizon.to_csv(temp_dir / "metrics_by_horizon.csv", index=False)
        bootstrap_intervals.to_csv(temp_dir / "bootstrap_intervals.csv", index=False)
        economic_thresholds.to_csv(temp_dir / "economic_threshold_comparison.csv", index=False)
        _write_json(temp_dir / "dataset_manifest_snapshot.json", dataset_snapshot)
        _write_json(temp_dir / "classification.json", classification)
        _write_json(temp_dir / "run_manifest.json", run_manifest)

        run_manifest["results_written"] = True
        _write_json(temp_dir / "run_manifest.json", run_manifest)
        progress.end(write_stage, output_rows=len(REQUIRED_OUTPUT_FILES), extra={"required_outputs": list(REQUIRED_OUTPUT_FILES)})
        _write_checksums(temp_dir, [request.config_path, *manifest_paths.values()], REQUIRED_OUTPUT_FILES)
        _verify_required_outputs(temp_dir)
        if final_dir.exists():
            final_dir.rmdir()
        temp_dir.rename(final_dir)
        return {
            "run_manifest": run_manifest,
            "output_dir": str(final_dir),
            "required_outputs": list(REQUIRED_OUTPUT_FILES),
            "event_count": int(len(events_frame)),
            "path_metric_rows": int(len(paths_frame)),
            "results_written": True,
        }
    except KeyboardInterrupt:
        progress.mark_interrupted(temp_dir=temp_dir, policy="delete_temp_dir")
        if temp_dir.exists():
            shutil.rmtree(temp_dir)
        raise
    except Exception:
        if temp_dir.exists():
            shutil.rmtree(temp_dir)
        raise


def build_synthetic_five_minute_frame(session_count: int, *, symbol: str = "QQQ") -> pd.DataFrame:
    if session_count < 1:
        raise ValueError("session_count must be positive.")
    rows: list[dict[str, Any]] = []
    sessions = pd.bdate_range("2024-01-02", periods=session_count)
    for session_index, session_day in enumerate(sessions):
        base = 100.0 + session_index * 0.01 + (0.5 if symbol.upper() == "SPY" else 0.0)
        for bar_index in range(78):
            local_timestamp = (
                pd.Timestamp(f"{session_day.date()} 09:30", tz="America/New_York")
                + timedelta(minutes=int(5 * bar_index))
            )
            open_price = base
            high = base + 0.45
            low = base - 0.45
            close = base
            if bar_index < 6:
                high = base + 1.0
                low = base - 1.0
            elif bar_index == 6:
                low = base - 1.02
                close = base - 0.35
            elif bar_index == 7:
                low = base - 1.20
                close = base - 0.20
            elif bar_index == 8:
                high = base + 0.75
                low = base + 0.10
                close = base + 0.35
            elif bar_index == 12:
                high = base + 1.02
                close = base + 0.35
            elif bar_index == 13:
                high = base + 1.20
                close = base + 0.20
            elif bar_index == 14:
                high = base - 0.10
                low = base - 0.75
                close = base - 0.35
            elif bar_index > 14:
                drift = ((bar_index - 14) % 9 - 4) * 0.02
                high = base + 0.40 + drift
                low = base - 0.40 + drift
                close = base + drift
            rows.append(
                {
                    "timestamp": local_timestamp.tz_convert("UTC"),
                    "open": open_price,
                    "high": high,
                    "low": low,
                    "close": close,
                    "volume": 1000 + session_index,
                }
            )
    return pd.DataFrame(rows)


def _time_call(label: str, fn, *, progress: ExecutionProgress, input_rows: int | None = None) -> tuple[Any, dict[str, Any]]:
    stage = progress.start(label, input_rows=input_rows)
    result = fn()
    output_rows = len(result) if hasattr(result, "__len__") else None
    record = progress.end(stage, output_rows=output_rows)
    return result, record


def _profile_synthetic_size(
    session_count: int,
    *,
    n_bootstrap: int,
    progress: ExecutionProgress,
) -> dict[str, Any]:
    config = FcrEventStudyConfig()
    five_minute = build_synthetic_five_minute_frame(session_count, symbol="QQQ")
    events, detection = _time_call(
        f"profile_detect_events_{session_count}",
        lambda: detect_fcr_event_study_events(five_minute, "QQQ", config),
        progress=progress,
        input_rows=len(five_minute),
    )
    paths, path_metrics = _time_call(
        f"profile_path_metrics_{session_count}",
        lambda: compute_fcr_event_paths(five_minute, events, config, horizons=config.horizons),
        progress=progress,
        input_rows=len(events),
    )
    aggregates, aggregation = _time_call(
        f"profile_aggregations_base_{session_count}",
        lambda: aggregate_fcr_event_paths(
            paths,
            group_by=("event_type", "horizon", "symbol", "orientation", "year"),
            n_bootstrap=n_bootstrap,
            seed=BOOTSTRAP_SEED,
            include_bootstrap=False,
        ),
        progress=progress,
        input_rows=len(paths),
    )
    with_bootstrap, bootstrap = _time_call(
        f"profile_bootstrap_{session_count}",
        lambda: attach_bootstrap_intervals(
            aggregates,
            paths,
            group_by=("event_type", "horizon", "symbol", "orientation", "year"),
            n_bootstrap=n_bootstrap,
            seed=BOOTSTRAP_SEED,
        ),
        progress=progress,
        input_rows=len(paths),
    )
    return {
        "sessions": session_count,
        "five_minute_rows": int(len(five_minute)),
        "events": int(len(events)),
        "path_rows": int(len(paths)),
        "aggregate_rows": int(len(with_bootstrap)),
        "timings": {
            "detection_seconds": detection["elapsed_seconds"],
            "path_metrics_seconds": path_metrics["elapsed_seconds"],
            "aggregations_base_seconds": aggregation["elapsed_seconds"],
            "bootstrap_seconds": bootstrap["elapsed_seconds"],
        },
        "dataframe_copies_inferred": {
            "path_metrics_session_cache": 1,
            "bootstrap_dataframe_concats_per_replica": 0,
            "aggregate_dataframe_copies": 0,
        },
    }


def run_profile_synthetic(
    *,
    base_sessions: int = 12,
    n_bootstrap: int = 500,
    progress: ExecutionProgress | None = None,
) -> dict[str, Any]:
    progress = progress or ExecutionProgress()
    first = _profile_synthetic_size(base_sessions, n_bootstrap=n_bootstrap, progress=progress)
    second = _profile_synthetic_size(base_sessions * 2, n_bootstrap=n_bootstrap, progress=progress)
    growth = {
        key: (
            second["timings"][key] / first["timings"][key]
            if first["timings"][key] and first["timings"][key] > 0
            else None
        )
        for key in first["timings"]
    }
    return {
        "hypothesis_id": HYPOTHESIS_ID,
        "mode": "profile_synthetic",
        "synthetic_only": True,
        "real_ohlc_read": False,
        "base_sessions": base_sessions,
        "double_sessions": base_sessions * 2,
        "n_bootstrap": int(n_bootstrap),
        "bootstrap_seed": BOOTSTRAP_SEED,
        "first": first,
        "second": second,
        "growth_when_doubling_sessions": growth,
        "progress": progress.summary(),
    }


def run_operational_discovery(
    request: FcrEventDiscoveryRequest | None = None,
    *,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    runtime_state: RuntimeState | None = None,
    dataset_loader=load_approved_event_dataset,
    n_bootstrap: int = 500,
    raise_on_error: bool = True,
    progress: ExecutionProgress | None = None,
) -> dict[str, Any]:
    request = request or FcrEventDiscoveryRequest()
    progress = progress or ExecutionProgress()
    if request.mode == "profile_synthetic":
        return run_profile_synthetic(n_bootstrap=n_bootstrap, progress=progress)

    preflight_stage = progress.start("preflight")
    try:
        preflight_payload = validate_discovery_preflight(request, runtime_state=runtime_state)
        progress.end(preflight_stage, output_rows=1, extra={"preflight_passed": True})
    except Exception as exc:
        progress.end(preflight_stage, status="failed", extra={"preflight_passed": False, "error": str(exc)})
        raise

    if request.mode == "prepare_only":
        return preflight_payload
    summary = dict(preflight_payload)
    summary["event_study_executed"] = False
    summary["results_written"] = False
    benchmark_only = request.mode == "benchmark_subset"
    try:
        execution = _execute_event_study_outputs(
            preflight_payload,
            request,
            output_dir=output_dir,
            dataset_loader=dataset_loader,
            n_bootstrap=n_bootstrap,
            progress=progress,
            benchmark_only=benchmark_only,
        )
    except KeyboardInterrupt:
        summary["interrupted"] = True
        summary["event_study_executed"] = not benchmark_only
        summary["results_written"] = False
        if raise_on_error:
            raise
        return summary
    except Exception as exc:
        summary["event_study_executed"] = not benchmark_only
        summary["results_written"] = False
        summary["error"] = str(exc)
        if raise_on_error:
            raise
        return summary
    if benchmark_only:
        summary.update(
            {
                "benchmark_only": True,
                "event_study_executed": False,
                "results_written": False,
                "diagnostic_dir": execution["diagnostic_dir"],
                "event_count": execution["event_count"],
                "path_metric_rows": execution["path_metric_rows"],
            }
        )
        return summary
    summary.update(
        {
            "event_study_executed": True,
            "results_written": bool(execution["results_written"]),
            "output_dir": execution["output_dir"],
            "required_outputs": execution["required_outputs"],
            "event_count": execution["event_count"],
            "path_metric_rows": execution["path_metric_rows"],
        }
    )
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Operational preflight for HYP-FCR-EVENT-01 discovery.")
    parser.add_argument(
        "--mode",
        choices=("prepare_only", "run_discovery", "profile_synthetic", "benchmark_subset"),
        default="prepare_only",
    )
    parser.add_argument("--expected-freeze-commit", default="")
    parser.add_argument("--expected-canonical-hash", default="")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--max-sessions-per-symbol", type=int, default=None)
    parser.add_argument("--synthetic-sessions", type=int, default=12)
    parser.add_argument("--debug", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    progress = ExecutionProgress()
    try:
        if args.mode == "profile_synthetic":
            payload = run_profile_synthetic(base_sessions=args.synthetic_sessions, progress=progress)
        else:
            payload = run_operational_discovery(
                FcrEventDiscoveryRequest(
                    mode=args.mode,
                    expected_freeze_commit=args.expected_freeze_commit,
                    expected_canonical_hash=args.expected_canonical_hash,
                    max_sessions_per_symbol=args.max_sessions_per_symbol,
                    debug=args.debug,
                ),
                output_dir=args.output_dir,
                progress=progress,
            )
    except KeyboardInterrupt:
        progress.mark_interrupted(policy="delete_temp_dir")
        payload = {
            "hypothesis_id": HYPOTHESIS_ID,
            "mode": args.mode,
            "interrupted": True,
            "results_written": False,
            "event_study_executed": False,
            "registry_updated": False,
            "temp_dir_policy": "delete_temp_dir",
        }
        print(json.dumps(payload, indent=2, sort_keys=True, default=str), file=sys.stderr, flush=True)
        if args.debug:
            raise
        return 130
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
