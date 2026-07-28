from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

import pandas as pd
import yaml

from src.data.dataset_manifest import APPROVED_FOR_OR_FVG_BACKTEST
from src.research.hyp_first_candle_event_study import load_approved_event_dataset, prepare_five_minute_frame
from src.research.hyp_or_cont_event_01 import (
    CONFIG_PATH,
    DISCOVERY_END,
    DISCOVERY_PERIOD,
    DISCOVERY_START,
    EXPECTED_CANONICAL_HASH,
    EXPECTED_FREEZE_COMMIT,
    EXPECTED_SYMBOLS,
    HORIZONS,
    HYPOTHESIS_ID,
    PRIMARY_HORIZON,
    SAFETY_FLAGS,
    OrContEventConfig,
    aggregate_incremental_metrics,
    assert_no_strategy_columns,
    attach_cost_thresholds,
    attach_incremental_returns,
    canonical_or_cont_config_hash,
    compute_or_continuation_paths,
    compute_unconditional_control,
    cost_threshold_comparison,
    detect_or_continuation_events,
    evaluate_discovery_gate,
    filter_discovery_period,
    validate_or_cont_period,
)


CURATED_MANIFEST_PATHS = {
    "QQQ": Path("data/manifests/QQQ_1min_2022-01-01_2026-07-06_curated_manifest.json"),
    "SPY": Path("data/manifests/SPY_1min_2022-01-01_2026-07-06_curated_manifest.json"),
}
CURATED_DATASET_PATHS = {
    "QQQ": Path("data/curated/QQQ_1min_2022-01-01_2026-07-06_curated.csv"),
    "SPY": Path("data/curated/SPY_1min_2022-01-01_2026-07-06_curated.csv"),
}
PREREG_DOC_PATH = Path("docs/HYP_OR_CONT_EVENT_01_PREREGISTRATION.md")
DEFAULT_OUTPUT_DIR = Path("artifacts/research/HYP-OR-CONT-EVENT-01/discovery_2022_2024")
BOOTSTRAP_SEED = 17
REQUIRED_OUTPUT_FILES = (
    "run_manifest.json",
    "dataset_manifest_snapshot.json",
    "config_snapshot.yaml",
    "confirmed_events.csv",
    "path_metrics.csv",
    "unconditional_control.csv",
    "incremental_metrics.csv",
    "metrics_by_symbol.csv",
    "metrics_by_year.csv",
    "bootstrap_intervals.csv",
    "cost_threshold_comparison.csv",
    "discovery_gate.json",
    "execution_progress.json",
    "checksums.json",
)
PREREGISTRATION_COMMIT = EXPECTED_FREEZE_COMMIT


@dataclass(frozen=True)
class RuntimeState:
    head_commit: str
    config_freeze_commit: str
    doc_freeze_commit: str
    working_tree_clean: bool = True


@dataclass(frozen=True)
class OrContDiscoveryRequest:
    mode: Literal["prepare_only", "run_discovery"] = "prepare_only"
    expected_freeze_commit: str | None = None
    expected_canonical_hash: str | None = None
    period: str = DISCOVERY_PERIOD
    requested_start: str = DISCOVERY_START
    requested_end: str = DISCOVERY_END
    symbols: tuple[str, ...] = EXPECTED_SYMBOLS
    config_path: Path = CONFIG_PATH
    prereg_doc_path: Path = PREREG_DOC_PATH
    dataset_paths: dict[str, Path] = field(default_factory=lambda: dict(CURATED_DATASET_PATHS))
    manifest_paths: dict[str, Path] = field(default_factory=lambda: dict(CURATED_MANIFEST_PATHS))
    safety_flags: dict[str, bool] = field(default_factory=lambda: dict(SAFETY_FLAGS))


class ExecutionProgress:
    def __init__(self, *, progress_path: Path | None = None, emit_console: bool = True) -> None:
        self.progress_path = progress_path
        self.emit_console = emit_console
        self.stages: list[dict[str, Any]] = []

    def set_progress_path(self, progress_path: Path) -> None:
        self.progress_path = progress_path
        self.persist()

    def start(self, stage: str, **extra: Any) -> dict[str, Any]:
        record = {
            "stage": stage,
            "status": "running",
            "start_time": _utc_now_iso(),
            "end_time": None,
            "elapsed_seconds": None,
            "_perf_start": time.perf_counter(),
        }
        record.update(extra)
        self.stages.append(record)
        self._emit(record)
        self.persist()
        return record

    def end(self, record: dict[str, Any], *, status: str = "completed", **extra: Any) -> None:
        record["status"] = status
        record["end_time"] = _utc_now_iso()
        record["elapsed_seconds"] = round(float(time.perf_counter() - record.pop("_perf_start", time.perf_counter())), 6)
        record.update(extra)
        self._emit(record)
        self.persist()

    def mark_interrupted(self, *, temp_dir: Path | None = None) -> None:
        self.stages.append(
            {
                "stage": "interrupt",
                "status": "interrupted",
                "start_time": _utc_now_iso(),
                "end_time": _utc_now_iso(),
                "elapsed_seconds": 0.0,
                "interrupted": True,
                "results_written": False,
                "temp_dir": str(temp_dir) if temp_dir else None,
                "temp_dir_policy": "delete_temp_dir",
            }
        )
        self.persist()

    def summary(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "generated_at_utc": _utc_now_iso(),
            "stages": [{key: value for key, value in item.items() if key != "_perf_start"} for item in self.stages],
        }

    def persist(self) -> None:
        if self.progress_path is None:
            return
        self.progress_path.parent.mkdir(parents=True, exist_ok=True)
        _write_json(self.progress_path, self.summary())

    def _emit(self, record: dict[str, Any]) -> None:
        if self.emit_console:
            printable = {key: value for key, value in record.items() if key != "_perf_start"}
            print(json.dumps({"execution_progress": printable}, sort_keys=True, default=str), flush=True)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def collect_runtime_state(cwd: str | Path = Path(".")) -> RuntimeState:
    root = Path(cwd)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    status = subprocess.check_output(["git", "status", "--porcelain"], cwd=root, text=True).strip()
    config_commit = subprocess.check_output(
        ["git", "log", "-n", "1", "--format=%H", "--", str(CONFIG_PATH)],
        cwd=root,
        text=True,
    ).strip()
    doc_commit = subprocess.check_output(
        ["git", "log", "-n", "1", "--format=%H", "--", str(PREREG_DOC_PATH)],
        cwd=root,
        text=True,
    ).strip()
    return RuntimeState(
        head_commit=head,
        config_freeze_commit=config_commit,
        doc_freeze_commit=doc_commit,
        working_tree_clean=status == "",
    )


def _read_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _read_yaml(path: str | Path) -> dict[str, Any]:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Config payload must be a mapping: {path}")
    return payload


def _validate_config_payload(config_path: Path) -> dict[str, Any]:
    payload = _read_yaml(config_path)
    if payload.get("hypothesis_id") != HYPOTHESIS_ID:
        raise PermissionError("Runner is locked to HYP-OR-CONT-EVENT-01.")
    if payload.get("type") != "event_study" or payload.get("strategy_status") != "non_strategy":
        raise PermissionError("HYP-OR-CONT-EVENT-01 must remain a non-strategy event study.")
    if payload.get("status") != "preregistered_not_executed":
        raise PermissionError("HYP-OR-CONT-EVENT-01 status must remain preregistered_not_executed before discovery.")
    if (payload.get("horizons") or {}).get("primary") != PRIMARY_HORIZON:
        raise PermissionError("Primary horizon must remain 30min.")
    if tuple((payload.get("horizons") or {}).get("secondary", [])) != ("15min", "60min", "session_close"):
        raise PermissionError("Secondary horizons must remain 15min, 60min, session_close.")
    blocked = payload.get("blocked_actions") or {}
    for field in ("create_strategy", "create_orders", "backtest_pnl", "optimize", "execute_validation_2025", "execute_2026"):
        if blocked.get(field) is not True:
            raise PermissionError(f"Blocked action missing in preregistration: {field}")
    for field, value in (payload.get("safety_flags") or {}).items():
        if value is not False:
            raise PermissionError(f"Safety flag must remain false: {field}")
    discovery = (payload.get("periods") or {}).get(DISCOVERY_PERIOD, {})
    if discovery.get("start") != DISCOVERY_START or discovery.get("end") != DISCOVERY_END:
        raise PermissionError("Discovery period must remain 2022-01-01 through 2024-12-31.")
    return payload


def _validate_manifest_metadata(symbol: str, manifest_path: Path) -> dict[str, Any]:
    payload = _read_json(manifest_path)
    if payload.get("symbol") != symbol:
        raise PermissionError(f"{symbol} manifest symbol mismatch.")
    if payload.get("timeframe") != "1min":
        raise PermissionError(f"{symbol} manifest timeframe must be 1min.")
    if payload.get("dataset_status") != APPROVED_FOR_OR_FVG_BACKTEST:
        raise PermissionError(f"{symbol} manifest is not approved_for_or_fvg_backtest.")
    if payload.get("audit_apt_for_or_fvg_backtest") is not True:
        raise PermissionError(f"{symbol} manifest audit flag is not approved.")
    if payload.get("audit_critical_warnings") not in ([], None):
        raise PermissionError(f"{symbol} manifest has critical warnings.")
    if payload.get("start") > DISCOVERY_START or payload.get("end") < DISCOVERY_END:
        raise PermissionError(f"{symbol} manifest does not cover discovery 2022-2024.")
    for field in ("broker_connected", "orders_sent", "live_trading_enabled", "paper_broker_enabled"):
        if payload.get(field) is not False:
            raise PermissionError(f"{symbol} manifest safety field is not false: {field}")
    return {
        "symbol": symbol,
        "manifest_path": str(manifest_path),
        "dataset_status": payload.get("dataset_status"),
        "sha256": payload.get("sha256"),
        "curated_file": payload.get("curated_file"),
        "start": payload.get("start"),
        "end": payload.get("end"),
        "excluded_sessions": payload.get("excluded_sessions") or [],
    }


def validate_discovery_preflight(
    request: OrContDiscoveryRequest,
    *,
    runtime_state: RuntimeState | None = None,
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    if request.mode == "prepare_only":
        return prepare_only_manifest(request)
    if request.mode != "run_discovery":
        raise PermissionError(f"Unsupported mode for {HYPOTHESIS_ID}: {request.mode}")
    if not request.expected_freeze_commit:
        raise PermissionError("--expected-freeze-commit is required for run_discovery.")
    if not request.expected_canonical_hash:
        raise PermissionError("--expected-canonical-hash is required for run_discovery.")
    runtime_state = runtime_state or collect_runtime_state()
    if not runtime_state.working_tree_clean:
        raise PermissionError("Working tree must be clean before run_discovery.")
    if runtime_state.head_commit != request.expected_freeze_commit:
        raise PermissionError(
            "Execution freeze commit mismatch: "
            f"expected_freeze_commit={request.expected_freeze_commit} "
            f"actual_head_commit={runtime_state.head_commit}"
        )
    actual_hash = canonical_or_cont_config_hash(request.config_path)
    if actual_hash != request.expected_canonical_hash:
        raise PermissionError(
            "Canonical payload hash mismatch: "
            f"expected_canonical_hash={request.expected_canonical_hash} "
            f"actual_canonical_hash={actual_hash}"
        )
    if actual_hash != EXPECTED_CANONICAL_HASH:
        raise PermissionError("Canonical payload hash no longer matches the preregistered constant.")
    if runtime_state.config_freeze_commit != PREREGISTRATION_COMMIT:
        raise PermissionError("Config file was not frozen at the preregistration commit.")
    if runtime_state.doc_freeze_commit != PREREGISTRATION_COMMIT:
        raise PermissionError("Preregistration document was not frozen at the preregistration commit.")
    if any(bool(value) for value in request.safety_flags.values()):
        raise PermissionError("Safety flags must remain false.")
    validate_or_cont_period(request.period)
    if request.requested_start != DISCOVERY_START or request.requested_end != DISCOVERY_END:
        raise PermissionError("Discovery request must be exactly 2022-01-01 through 2024-12-31.")
    if tuple(request.symbols) != EXPECTED_SYMBOLS:
        raise PermissionError("Discovery symbols must be exactly QQQ and SPY.")
    if output_dir is not None:
        _validate_final_output_absent(output_dir)
    _validate_config_payload(request.config_path)
    manifest_summary = {
        symbol: _validate_manifest_metadata(symbol, request.manifest_paths[symbol])
        for symbol in EXPECTED_SYMBOLS
    }
    return {
        "hypothesis_id": HYPOTHESIS_ID,
        "mode": request.mode,
        "preflight_passed": True,
        "event_study_executed": False,
        "results_written": False,
        "head_commit": runtime_state.head_commit,
        "preregistration_commit": PREREGISTRATION_COMMIT,
        "execution_freeze_commit": request.expected_freeze_commit,
        "freeze_commit": request.expected_freeze_commit,
        "canonical_payload_hash": actual_hash,
        "requested_start": request.requested_start,
        "requested_end": request.requested_end,
        "symbols": list(request.symbols),
        "manifest_summary": manifest_summary,
        "orders_created": False,
        "position_sizing_used": False,
        "safety_flags": dict(request.safety_flags),
    }


def prepare_only_manifest(request: OrContDiscoveryRequest | None = None) -> dict[str, Any]:
    request = request or OrContDiscoveryRequest()
    return {
        "hypothesis_id": HYPOTHESIS_ID,
        "mode": "prepare_only",
        "event_study_executed": False,
        "results_written": False,
        "preregistration_commit": PREREGISTRATION_COMMIT,
        "execution_freeze_commit": request.expected_freeze_commit,
        "freeze_commit": request.expected_freeze_commit or PREREGISTRATION_COMMIT,
        "canonical_payload_hash": request.expected_canonical_hash or EXPECTED_CANONICAL_HASH,
        "validation_2025_executed": False,
        "historical_2026_executed": False,
        "orders_created": False,
        "position_sizing_used": False,
        "strategy_created": False,
        "safety_flags": dict(request.safety_flags),
    }


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str, allow_nan=False), encoding="utf-8")


def _serialize_frame(frame: pd.DataFrame) -> pd.DataFrame:
    serializable = frame.copy()
    for column in serializable.columns:
        if pd.api.types.is_datetime64_any_dtype(serializable[column]):
            serializable[column] = serializable[column].map(lambda value: value.isoformat() if pd.notna(value) else "")
        elif len(serializable) and isinstance(serializable[column].iloc[0], pd.Timestamp):
            serializable[column] = serializable[column].map(lambda value: value.isoformat() if pd.notna(value) else "")
    return serializable


def _sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _write_checksums(output_dir: Path, input_paths: list[Path]) -> None:
    output_paths = [output_dir / name for name in REQUIRED_OUTPUT_FILES if name not in {"checksums.json", "execution_progress.json"}]
    payload = {
        "inputs": [{"path": str(path), "sha256": _sha256_file(path)} for path in input_paths if path.exists()],
        "outputs": [{"path": path.name, "sha256": _sha256_file(path)} for path in output_paths if path.exists()],
    }
    _write_json(output_dir / "checksums.json", payload)


def _verify_required_outputs(output_dir: Path) -> None:
    missing = [name for name in REQUIRED_OUTPUT_FILES if not (output_dir / name).exists()]
    if missing:
        raise FileNotFoundError(f"Missing HYP-OR-CONT-EVENT-01 outputs: {missing}")


def _validate_final_output_absent(output_dir: str | Path) -> None:
    final_dir = Path(output_dir)
    if final_dir.exists() and any(final_dir.iterdir()):
        raise FileExistsError(f"Output directory already exists and is not empty: {final_dir}")


def _manifest_record(manifest: Any) -> dict[str, Any]:
    if hasattr(manifest, "to_record"):
        return dict(manifest.to_record())
    if isinstance(manifest, dict):
        return dict(manifest)
    if hasattr(manifest, "__dict__"):
        return dict(manifest.__dict__)
    raise TypeError(f"Unsupported manifest object: {type(manifest)!r}")


def _execute_discovery_outputs(
    preflight: dict[str, Any],
    request: OrContDiscoveryRequest,
    *,
    output_dir: str | Path,
    dataset_loader=load_approved_event_dataset,
    five_minute_preparer=prepare_five_minute_frame,
    n_bootstrap: int = 500,
    bootstrap_seed: int = BOOTSTRAP_SEED,
    progress: ExecutionProgress | None = None,
) -> dict[str, Any]:
    progress = progress or ExecutionProgress()
    final_dir = Path(output_dir)
    _validate_final_output_absent(final_dir)
    final_dir.parent.mkdir(parents=True, exist_ok=True)
    temp_dir = final_dir.parent / f".{final_dir.name}.tmp-{uuid4().hex}"
    config = OrContEventConfig()
    five_by_symbol: dict[str, pd.DataFrame] = {}
    events_by_symbol: list[pd.DataFrame] = []
    paths_by_symbol: list[pd.DataFrame] = []
    dataset_snapshot: dict[str, Any] = {}
    try:
        temp_dir.mkdir(parents=True, exist_ok=False)
        progress.set_progress_path(temp_dir / "execution_progress.json")
        shutil.copyfile(request.config_path, temp_dir / "config_snapshot.yaml")
        for symbol in EXPECTED_SYMBOLS:
            stage = progress.start(f"load_{symbol}", symbol=symbol)
            minute_frame, manifest = dataset_loader(symbol, request.dataset_paths[symbol], request.manifest_paths[symbol])
            progress.end(stage, input_rows=None, output_rows=int(len(minute_frame)))

            stage = progress.start("crop_discovery_period", symbol=symbol, input_rows=int(len(minute_frame)))
            cropped = filter_discovery_period(minute_frame)
            progress.end(stage, output_rows=int(len(cropped)))

            stage = progress.start("resample_1m_to_5m", symbol=symbol, input_rows=int(len(cropped)))
            five_minute = five_minute_preparer(cropped)
            progress.end(stage, output_rows=int(len(five_minute)))
            five_by_symbol[symbol] = five_minute

            stage = progress.start("detect_confirmed_events", symbol=symbol, input_rows=int(len(five_minute)))
            events, exclusions = detect_or_continuation_events(five_minute, symbol, config)
            progress.end(stage, output_rows=int(len(events)), exclusions=int(len(exclusions)))
            assert_no_strategy_columns(events)

            stage = progress.start("path_metrics", symbol=symbol, input_rows=int(len(events)), horizons=list(HORIZONS))
            paths = compute_or_continuation_paths(five_minute, events, horizons=HORIZONS, config=config)
            paths = attach_cost_thresholds(paths)
            progress.end(stage, output_rows=int(len(paths)))
            assert_no_strategy_columns(paths)
            events_by_symbol.append(events)
            paths_by_symbol.append(paths)
            dataset_snapshot[symbol] = {
                "dataset_path": str(request.dataset_paths[symbol]),
                "manifest_path": str(request.manifest_paths[symbol]),
                "manifest": _manifest_record(manifest),
                "cropped_rows": int(len(cropped)),
                "five_minute_rows": int(len(five_minute)),
                "requested_start": DISCOVERY_START,
                "requested_end": DISCOVERY_END,
                "contains_2025_or_2026": False,
            }

        confirmed_events = pd.concat(events_by_symbol, ignore_index=True) if events_by_symbol else pd.DataFrame()
        path_metrics = pd.concat(paths_by_symbol, ignore_index=True) if paths_by_symbol else pd.DataFrame()

        stage = progress.start("unconditional_control", input_rows=int(len(path_metrics)))
        control = compute_unconditional_control(five_by_symbol, path_metrics, config)
        path_metrics = attach_incremental_returns(path_metrics, control)
        progress.end(stage, output_rows=int(len(control)))

        stage = progress.start("aggregations_and_bootstrap", input_rows=int(len(path_metrics)), bootstrap_grouped_by="session_date")
        incremental_metrics = aggregate_incremental_metrics(
            path_metrics,
            group_by=("symbol", "direction_orientation", "horizon"),
            n_bootstrap=n_bootstrap,
            seed=bootstrap_seed,
        )
        metrics_by_symbol = aggregate_incremental_metrics(path_metrics, group_by=("symbol",), n_bootstrap=n_bootstrap, seed=bootstrap_seed)
        metrics_by_year = aggregate_incremental_metrics(path_metrics, group_by=("year",), n_bootstrap=n_bootstrap, seed=bootstrap_seed)
        bootstrap_intervals = aggregate_incremental_metrics(
            path_metrics,
            group_by=("symbol", "direction_orientation", "horizon"),
            n_bootstrap=n_bootstrap,
            seed=bootstrap_seed,
        ).loc[
            :,
            [
                "symbol",
                "direction_orientation",
                "horizon",
                "bootstrap_ci_low",
                "bootstrap_ci_high",
                "bootstrap_grouped_by",
                "bootstrap_seed",
            ],
        ]
        cost_comparison = cost_threshold_comparison(path_metrics)
        gate = evaluate_discovery_gate(path_metrics, bootstrap_intervals)
        progress.end(stage, output_rows=int(len(incremental_metrics) + len(metrics_by_symbol) + len(metrics_by_year)))

        run_manifest = {
            "hypothesis_id": HYPOTHESIS_ID,
            "mode": "run_discovery",
            "period": DISCOVERY_PERIOD,
            "preregistration_commit": preflight["preregistration_commit"],
            "execution_freeze_commit": preflight["execution_freeze_commit"],
            "freeze_commit": preflight["freeze_commit"],
            "head_commit": preflight["head_commit"],
            "canonical_payload_hash": preflight["canonical_payload_hash"],
            "requested_start": DISCOVERY_START,
            "requested_end": DISCOVERY_END,
            "symbols": list(EXPECTED_SYMBOLS),
            "horizons": list(HORIZONS),
            "primary_horizon": PRIMARY_HORIZON,
            "event_study_executed": True,
            "results_written": False,
            "validation_2025_executed": False,
            "historical_2026_executed": False,
            "orders_created": False,
            "strategy_created": False,
            "position_sizing_used": False,
            "safety_flags": dict(request.safety_flags),
        }

        stage = progress.start("atomic_write", input_rows=int(len(confirmed_events) + len(path_metrics)))
        _write_json(temp_dir / "run_manifest.json", run_manifest)
        _write_json(temp_dir / "dataset_manifest_snapshot.json", dataset_snapshot)
        _serialize_frame(confirmed_events).to_csv(temp_dir / "confirmed_events.csv", index=False)
        _serialize_frame(path_metrics).to_csv(temp_dir / "path_metrics.csv", index=False)
        _serialize_frame(control).to_csv(temp_dir / "unconditional_control.csv", index=False)
        incremental_metrics.to_csv(temp_dir / "incremental_metrics.csv", index=False)
        metrics_by_symbol.to_csv(temp_dir / "metrics_by_symbol.csv", index=False)
        metrics_by_year.to_csv(temp_dir / "metrics_by_year.csv", index=False)
        bootstrap_intervals.to_csv(temp_dir / "bootstrap_intervals.csv", index=False)
        cost_comparison.to_csv(temp_dir / "cost_threshold_comparison.csv", index=False)
        _write_json(temp_dir / "discovery_gate.json", gate)
        run_manifest["results_written"] = True
        _write_json(temp_dir / "run_manifest.json", run_manifest)
        progress.end(stage, output_rows=len(REQUIRED_OUTPUT_FILES))
        _write_checksums(temp_dir, [request.config_path, request.prereg_doc_path, *request.manifest_paths.values()])
        _verify_required_outputs(temp_dir)
        if final_dir.exists():
            final_dir.rmdir()
        temp_dir.rename(final_dir)
        return {
            **run_manifest,
            "output_dir": str(final_dir),
            "confirmed_event_count": int(len(confirmed_events)),
            "path_metric_rows": int(len(path_metrics)),
            "gate_passed": bool(gate["passed"]),
        }
    except KeyboardInterrupt:
        progress.mark_interrupted(temp_dir=temp_dir)
        if temp_dir.exists():
            shutil.rmtree(temp_dir)
        raise
    except Exception:
        if temp_dir.exists():
            shutil.rmtree(temp_dir)
        raise


def run_operational_discovery(
    request: OrContDiscoveryRequest | None = None,
    *,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    runtime_state: RuntimeState | None = None,
    dataset_loader=load_approved_event_dataset,
    five_minute_preparer=prepare_five_minute_frame,
    n_bootstrap: int = 500,
    progress: ExecutionProgress | None = None,
    raise_on_error: bool = True,
) -> dict[str, Any]:
    request = request or OrContDiscoveryRequest()
    progress = progress or ExecutionProgress()
    if request.mode == "prepare_only":
        return prepare_only_manifest(request)
    try:
        stage = progress.start("preflight")
        preflight = validate_discovery_preflight(request, runtime_state=runtime_state, output_dir=output_dir)
        progress.end(stage, output_rows=1)
        return _execute_discovery_outputs(
            preflight,
            request,
            output_dir=output_dir,
            dataset_loader=dataset_loader,
            five_minute_preparer=five_minute_preparer,
            n_bootstrap=n_bootstrap,
            progress=progress,
        )
    except KeyboardInterrupt:
        progress.mark_interrupted(temp_dir=None)
        if raise_on_error:
            raise
        return {
            "hypothesis_id": HYPOTHESIS_ID,
            "interrupted": True,
            "event_study_executed": False,
            "results_written": False,
        }
    except Exception as exc:
        if raise_on_error:
            raise
        return {
            "hypothesis_id": HYPOTHESIS_ID,
            "error": str(exc),
            "event_study_executed": False,
            "results_written": False,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="HYP-OR-CONT-EVENT-01 operational discovery runner.")
    parser.add_argument("--mode", default="prepare_only", choices=("prepare_only", "run_discovery"))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--expected-freeze-commit")
    parser.add_argument("--expected-canonical-hash")
    args = parser.parse_args()
    if args.mode == "run_discovery":
        if not args.expected_freeze_commit:
            parser.error("--expected-freeze-commit is required for run_discovery")
        if not args.expected_canonical_hash:
            parser.error("--expected-canonical-hash is required for run_discovery")
    request = OrContDiscoveryRequest(
        mode=args.mode,
        expected_freeze_commit=args.expected_freeze_commit,
        expected_canonical_hash=args.expected_canonical_hash,
    )
    try:
        payload = run_operational_discovery(request, output_dir=args.output_dir)
    except Exception as exc:
        parser.exit(1, f"error: {exc}\n")
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
