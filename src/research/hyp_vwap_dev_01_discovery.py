"""Governed discovery runner for HYP-VWAP-DEV-01.

Only ``validate_implementation`` is safe before a separately frozen execution
commit.  Real datasets, manifests, and output paths are referenced exclusively
inside the future ``run_discovery`` path.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
import json
from pathlib import Path
import subprocess
from typing import Any, Literal, Mapping
from uuid import uuid4

import pandas as pd
import yaml

from src.data.dataset_manifest import require_approved_dataset_manifest_file
from src.data.sessions import EquitySessionCalendar
from src.research.hyp_drive_pb_01_discovery import (
    _atomic_rename as _shared_atomic_rename,
    _sha256_file as _shared_sha256_file,
    _write_json_atomic as _shared_write_json_atomic,
)
from src.research.hyp_vwap_dev_01 import (
    ACTIVE_AMENDMENT_FREEZE_COMMIT,
    ALL_CRITERION_IDS,
    CLARIFICATION_FREEZE_COMMIT,
    CONCEPTUAL_DESIGN_FREEZE_COMMIT,
    EXPECTED_CANONICAL_HASH,
    HYPOTHESIS_ID,
    PRIMARY_HORIZON,
    PRIOR_PREREGISTRATION_FREEZE_COMMIT,
    SUBSTANTIVE_CRITERION_IDS,
    SYMBOLS,
    TIMEZONE,
    annual_concentration,
    attach_causal_session_vwap,
    build_exact_time_control,
    build_unconditional_candidates,
    canonical_payload_hash,
    classify_gate,
    clustered_percentile_bootstrap,
    compute_path_metrics,
    derive_substantive_criteria,
    detect_session_event,
    leave_one_largest_session_out,
    resample_complete_rth_1m_to_5m,
    validate_frozen_config,
)


CONFIG_PATH = Path("configs/research/hypotheses/HYP-VWAP-DEV-01.yaml")
DISCOVERY_START = date(2022, 1, 1)
DISCOVERY_END = date(2024, 12, 31)
DEFAULT_OUTPUT_DIR = Path("artifacts/research/HYP-VWAP-DEV-01/discovery_2022_2024")
DEFAULT_DATASET_PATHS = {
    symbol: Path(f"data/curated/{symbol}_1min_2022-01-01_2026-07-06_curated.csv")
    for symbol in SYMBOLS
}
DEFAULT_MANIFEST_PATHS = {
    symbol: Path(f"data/manifests/{symbol}_1min_2022-01-01_2026-07-06_curated_manifest.json")
    for symbol in SYMBOLS
}
REQUIRED_CORE_SYMBOLS = (
    "validate_frozen_config",
    "resample_complete_rth_1m_to_5m",
    "attach_causal_session_vwap",
    "detect_session_event",
    "compute_path_metrics",
    "build_exact_time_control",
    "build_unconditional_candidates",
    "clustered_percentile_bootstrap",
    "annual_concentration",
    "leave_one_largest_session_out",
    "derive_substantive_criteria",
    "classify_gate",
)
REQUIRED_OUTPUT_FILES = (
    "run_manifest.json",
    "dataset_manifest_snapshot.json",
    "confirmed_events.csv",
    "event_exclusions.csv",
    "path_metrics.csv",
    "unconditional_control.csv",
    "incremental_metrics.csv",
    "bootstrap_intervals.json",
    "concentration_metrics.json",
    "leave_one_out_metrics.json",
    "discovery_gate.json",
    "execution_progress.json",
    "checksums.json",
)


class StrictSafeLoader(yaml.SafeLoader):
    """Safe YAML loader rejecting duplicate mapping keys."""


def _construct_unique_mapping(
    loader: StrictSafeLoader,
    node: yaml.MappingNode,
    deep: bool = False,
) -> Mapping[str, Any]:
    output: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=False)
        if key in output:
            raise ValueError(
                f"DUPLICATE_YAML_KEY: {key!r} at line {key_node.start_mark.line + 1}"
            )
        output[key] = loader.construct_object(value_node, deep=deep)
    return output


StrictSafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


@dataclass(frozen=True)
class DiscoveryRequest:
    """Explicit governance inputs for a runner invocation."""

    mode: Literal["validate_implementation", "run_discovery"]
    expected_amendment_freeze_commit: str | None = None
    expected_implementation_freeze_commit: str | None = None
    expected_canonical_hash: str | None = None


@dataclass(frozen=True)
class RuntimeState:
    """Relevant local Git state."""

    head_commit: str
    working_tree_clean: bool
    status_porcelain: str
    amendment_commit_exists: bool
    amendment_is_ancestor: bool


@dataclass
class ExecutionProgress:
    """Monotonic stage progress persisted atomically when attached."""

    path: Path | None = None
    stages: list[dict[str, Any]] | None = None
    results_written: bool = False

    def __post_init__(self) -> None:
        if self.stages is None:
            self.stages = []

    def record(self, stage: str, **details: Any) -> None:
        """Append one stage exactly once and persist its snapshot."""

        assert self.stages is not None
        if any(item["stage"] == stage for item in self.stages):
            raise RuntimeError(f"Progress stage already recorded: {stage}")
        self.stages.append({"stage": stage, **details})
        self.persist()

    def persist(self) -> None:
        """Persist progress without declaring success before atomic replacement."""

        if self.path is not None:
            _shared_write_json_atomic(self.path, self.summary())

    def summary(self) -> Mapping[str, Any]:
        """Return a JSON-safe progress snapshot."""

        return {
            "hypothesis_id": HYPOTHESIS_ID,
            "stages": list(self.stages or []),
            "results_written": self.results_written,
        }


def load_frozen_config(path: str | Path = CONFIG_PATH) -> Mapping[str, Any]:
    """Read strict YAML and validate the complete frozen mapping."""

    payload = yaml.load(Path(path).read_text(encoding="utf-8"), Loader=StrictSafeLoader)
    if not isinstance(payload, Mapping):
        raise ValueError("YAML_NOT_PARSEABLE: root must be a mapping")
    return validate_frozen_config(payload)


def _git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        check=check,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def collect_runtime_state() -> RuntimeState:
    """Collect HEAD, cleanliness, and amendment ancestry without data access."""

    head = _git("rev-parse", "--verify", "HEAD").stdout.strip()
    status = _git("status", "--porcelain=v1", "--untracked-files=all").stdout
    exists = _git(
        "cat-file", "-e", f"{ACTIVE_AMENDMENT_FREEZE_COMMIT}^{{commit}}", check=False
    ).returncode == 0
    ancestor = exists and _git(
        "merge-base", "--is-ancestor", ACTIVE_AMENDMENT_FREEZE_COMMIT, head, check=False
    ).returncode == 0
    return RuntimeState(head, status.strip() == "", status, exists, ancestor)


def validate_implementation(
    request: DiscoveryRequest | None = None,
) -> Mapping[str, Any]:
    """Validate implementation/config contracts without opening data or manifests."""

    request = request or DiscoveryRequest(mode="validate_implementation")
    if request.mode != "validate_implementation":
        raise PermissionError("MODE_NOT_AUTHORIZED")
    config = load_frozen_config()
    recomputed = canonical_payload_hash(config)
    if recomputed != EXPECTED_CANONICAL_HASH:
        raise PermissionError("CANONICAL_HASH_MISMATCH")
    if not CONFIG_PATH.is_file():
        raise FileNotFoundError(CONFIG_PATH)
    import src.research.hyp_vwap_dev_01 as core

    missing = [name for name in REQUIRED_CORE_SYMBOLS if not callable(getattr(core, name, None))]
    if missing:
        raise RuntimeError(f"REQUIRED_SYMBOL_MISSING: {missing}")
    criteria = config["discovery_gate"]["criteria"]
    ids = tuple(item["criterion_id"] for item in criteria)
    if ids != ALL_CRITERION_IDS or tuple(criteria[-1]["input_criterion_ids"]) != SUBSTANTIVE_CRITERION_IDS:
        raise ValueError("CRITERION_GRAPH_MISMATCH")
    runtime = collect_runtime_state()
    if not runtime.amendment_commit_exists or not runtime.amendment_is_ancestor:
        raise PermissionError("AMENDMENT_FREEZE_NOT_IN_HISTORY")
    return {
        "hypothesis_id": HYPOTHESIS_ID,
        "mode": "validate_implementation",
        "implementation_valid": True,
        "active_preregistration_amendment_freeze_commit": ACTIVE_AMENDMENT_FREEZE_COMMIT,
        "conceptual_design_freeze_commit": CONCEPTUAL_DESIGN_FREEZE_COMMIT,
        "clarification_freeze_commit": CLARIFICATION_FREEZE_COMMIT,
        "prior_preregistration_freeze_commit": PRIOR_PREREGISTRATION_FREEZE_COMMIT,
        "canonical_payload_sha256": recomputed,
        "criterion_count": len(ids),
        "substantive_criterion_count": len(SUBSTANTIVE_CRITERION_IDS),
        "pro_01_nonrecursive": "PRO-01" not in criteria[-1]["input_criterion_ids"],
        "safety_flags_all_false": not any(config["safety_flags"].values()),
        "datasets_opened": False,
        "manifests_opened": False,
        "discovery_executed": False,
        "artifacts_created": False,
        "validation_2025_executed": False,
        "historical_2026_executed": False,
        "strategy_created": False,
        "position_sizing_used": False,
        "orders_created": False,
        "broker_connected": False,
    }


def validate_discovery_preflight(request: DiscoveryRequest) -> Mapping[str, Any]:
    """Validate future discovery authorization before any manifest/data read."""

    if request.mode != "run_discovery":
        raise PermissionError("MODE_NOT_AUTHORIZED")
    if request.expected_amendment_freeze_commit != ACTIVE_AMENDMENT_FREEZE_COMMIT:
        raise PermissionError("PREREGISTRATION_FREEZE_MISMATCH")
    if request.expected_canonical_hash != EXPECTED_CANONICAL_HASH:
        raise PermissionError("CANONICAL_HASH_MISMATCH")
    if not request.expected_implementation_freeze_commit:
        raise PermissionError("IMPLEMENTATION_FREEZE_REQUIRED")
    runtime = collect_runtime_state()
    if not runtime.working_tree_clean:
        raise PermissionError("WORKING_TREE_NOT_CLEAN")
    if runtime.head_commit != request.expected_implementation_freeze_commit:
        raise PermissionError("IMPLEMENTATION_FREEZE_MISMATCH")
    if not runtime.amendment_commit_exists or not runtime.amendment_is_ancestor:
        raise PermissionError("AMENDMENT_FREEZE_NOT_IN_HISTORY")
    config = load_frozen_config()
    if config["discovery_execution_allowed"] is not False:
        raise PermissionError("DISCOVERY_STATE_MISMATCH")
    if DEFAULT_OUTPUT_DIR.exists():
        raise FileExistsError(DEFAULT_OUTPUT_DIR)
    return {
        "runtime": runtime,
        "config": config,
        "preflight_passed": True,
    }


def crop_discovery_period(frame: pd.DataFrame) -> pd.DataFrame:
    """Return only 2022-2024 rows without materializing future partitions."""

    if "timestamp" not in frame.columns:
        raise ValueError("Discovery frame requires timestamp.")
    timestamps = pd.to_datetime(frame["timestamp"], utc=True).dt.tz_convert(TIMEZONE)
    session_dates = timestamps.dt.date
    return frame.loc[
        (session_dates >= DISCOVERY_START) & (session_dates <= DISCOVERY_END)
    ].copy()


def _load_discovery_inputs() -> tuple[pd.DataFrame, Mapping[str, Any]]:
    """Future-only approved manifest and bounded dataset access."""

    frames: list[pd.DataFrame] = []
    snapshots: dict[str, Any] = {}
    calendar = EquitySessionCalendar.us_equity()
    for symbol in SYMBOLS:
        manifest = require_approved_dataset_manifest_file(
            DEFAULT_DATASET_PATHS[symbol], symbol, "1min", DEFAULT_MANIFEST_PATHS[symbol]
        )
        frame = pd.read_csv(DEFAULT_DATASET_PATHS[symbol])
        frame["symbol"] = symbol
        timestamps = pd.to_datetime(frame["timestamp"], utc=True).dt.tz_convert(TIMEZONE)
        frame["timestamp"] = timestamps
        frame["session_date"] = timestamps.dt.date
        if not calendar.mask(frame["timestamp"]).all():
            raise PermissionError(f"{symbol} contains rows outside approved RTH.")
        frame = crop_discovery_period(frame)
        frames.append(frame)
        snapshots[symbol] = {
            "dataset_path": str(DEFAULT_DATASET_PATHS[symbol]),
            "manifest_path": str(DEFAULT_MANIFEST_PATHS[symbol]),
            "dataset_sha256": manifest.sha256,
            "dataset_status": manifest.dataset_status,
        }
    return pd.concat(frames, ignore_index=True), snapshots


def _detect_events(five_minute: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    calendar = EquitySessionCalendar.us_equity()
    events: list[dict[str, Any]] = []
    exclusions: list[dict[str, Any]] = []
    for (symbol, session), group in five_minute.groupby(["symbol", "session_date"], sort=True):
        close_clock = calendar.session_close(session)
        if close_clock is None:
            continue
        close = pd.Timestamp.combine(session, close_clock).tz_localize(TIMEZONE)
        result = detect_session_event(
            group, symbol=str(symbol), session_date=session, session_close=close
        )
        if result.event is None:
            exclusions.append({"symbol": symbol, "session_date": session, "status": result.status})
        else:
            events.append(asdict(result.event))
    return pd.DataFrame(events), pd.DataFrame(exclusions)


def _aggregate_metrics(primary: pd.DataFrame) -> Mapping[str, Any]:
    grouped_symbol = primary.groupby("symbol")
    grouped_direction = primary.groupby("direction")
    grouped_year = primary.groupby("year")
    return {
        "event_count": len(primary),
        "gross_mean_30min": float(primary["gross_return"].mean()),
        "stress_net_mean_30min": float(primary["stress_net_return"].mean()),
        "incremental_mean_30min": float(primary["incremental_return"].mean()),
        "symbol_event_counts": grouped_symbol.size().to_dict(),
        "year_event_counts": grouped_year.size().to_dict(),
        "orientation_event_counts": grouped_direction.size().to_dict(),
        "symbol_gross_means": grouped_symbol["gross_return"].mean().to_dict(),
        "orientation_gross_means": grouped_direction["gross_return"].mean().to_dict(),
        "orientation_gross_medians": grouped_direction["gross_return"].median().to_dict(),
        "baseline_net_means": {
            "pooled": float(primary["baseline_net_return"].mean()),
            **grouped_symbol["baseline_net_return"].mean().to_dict(),
        },
    }


def _gate_metric_mapping(
    primary: pd.DataFrame,
    intervals: Mapping[str, tuple[float, float]],
    concentration_value: float,
    loo: Any,
) -> Mapping[str, Any]:
    aggregate = _aggregate_metrics(primary)
    yearly = primary.groupby("year")
    return {
        "INT-01": True,
        "INT-02": True,
        "INT-03": True,
        "INT-04": 0,
        "INT-05": 0,
        "INT-06": False,
        "INT-07": bool(primary["path_complete"].all()),
        "INT-08": 1,
        "SMP-01": aggregate["event_count"],
        "SMP-02": aggregate["symbol_event_counts"],
        "SMP-03": aggregate["year_event_counts"],
        "REP-01": aggregate["orientation_event_counts"],
        "ECO-01": aggregate["gross_mean_30min"],
        "ECO-02": aggregate["symbol_gross_means"],
        "ECO-03": [*aggregate["orientation_gross_means"].values(), *aggregate["orientation_gross_medians"].values()],
        "ECO-04": aggregate["baseline_net_means"],
        "ECO-05": aggregate["stress_net_mean_30min"],
        "INC-01": aggregate["incremental_mean_30min"],
        "UNC-01": [intervals[name][0] for name in ("gross_return", "incremental_return", "baseline_net_return")],
        "STB-01": int((yearly["gross_return"].mean() > 0).sum()),
        "STB-02": int((yearly["incremental_return"].mean() > 0).sum()),
        "CON-01": concentration_value,
        "CON-02": loo.concentration.value,
        "CON-03": loo.pooled_incremental_mean,
        "CON-04": loo.positive_incremental_years,
    }


def _write_closed_outputs(
    temp_dir: Path,
    *,
    manifest_snapshot: Mapping[str, Any],
    events: pd.DataFrame,
    exclusions: pd.DataFrame,
    paths: pd.DataFrame,
    controlled: pd.DataFrame,
    intervals: Mapping[str, Any],
    concentration: Any,
    loo: Any,
    gate: Any,
    progress: ExecutionProgress,
) -> None:
    _shared_write_json_atomic(temp_dir / "dataset_manifest_snapshot.json", manifest_snapshot)
    events.to_csv(temp_dir / "confirmed_events.csv", index=False)
    controlled.loc[:, [
        "symbol", "session_date", "executable_timestamp", "horizon",
        "unconditional_return", "unconditional_sample_count",
    ]].to_csv(temp_dir / "unconditional_control.csv", index=False)
    paths.to_csv(temp_dir / "path_metrics.csv", index=False)
    controlled.to_csv(temp_dir / "incremental_metrics.csv", index=False)
    exclusions.to_csv(temp_dir / "event_exclusions.csv", index=False)
    _shared_write_json_atomic(temp_dir / "bootstrap_intervals.json", intervals)
    _shared_write_json_atomic(temp_dir / "concentration_metrics.json", asdict(concentration))
    _shared_write_json_atomic(temp_dir / "leave_one_out_metrics.json", asdict(loo))
    _shared_write_json_atomic(temp_dir / "discovery_gate.json", asdict(gate))
    run_manifest = {
        "hypothesis_id": HYPOTHESIS_ID,
        "active_preregistration_amendment_freeze_commit": ACTIVE_AMENDMENT_FREEZE_COMMIT,
        "canonical_payload_sha256": EXPECTED_CANONICAL_HASH,
        "confirmed_event_count": len(events),
        "primary_path_count": int((paths["horizon"] == PRIMARY_HORIZON).sum()),
        "criterion_count": len(gate.criteria),
        "classification": gate.classification,
        "results_written": False,
        "paper_eligible": False,
        "live_eligible": False,
        "strategy_created": False,
        "orders_created": False,
        "position_sizing_used": False,
    }
    _shared_write_json_atomic(temp_dir / "run_manifest.json", run_manifest)
    checksums = {
        path.name: _shared_sha256_file(path)
        for path in sorted(temp_dir.iterdir())
        if path.is_file() and path.name not in {"checksums.json", "execution_progress.json"}
    }
    _shared_write_json_atomic(temp_dir / "checksums.json", checksums)
    progress.record("outputs_verified", file_count=len(checksums))


def _finalize_temp_inventory(temp_dir: Path, progress: ExecutionProgress) -> None:
    run_manifest_path = temp_dir / "run_manifest.json"
    run_manifest = json.loads(run_manifest_path.read_text(encoding="utf-8"))
    run_manifest["results_written"] = True
    run_manifest["completed_at"] = datetime.now(timezone.utc).isoformat()
    _shared_write_json_atomic(run_manifest_path, run_manifest)
    checksums = json.loads((temp_dir / "checksums.json").read_text(encoding="utf-8"))
    checksums["run_manifest.json"] = _shared_sha256_file(run_manifest_path)
    _shared_write_json_atomic(temp_dir / "checksums.json", checksums)
    progress.results_written = True
    progress.record("ready_for_atomic_promotion")
    actual = {path.name for path in temp_dir.iterdir() if path.is_file()}
    expected = set(REQUIRED_OUTPUT_FILES)
    if actual != expected:
        raise RuntimeError(
            f"OUTPUT_INVENTORY_MISMATCH: missing={sorted(expected-actual)} "
            f"extra={sorted(actual-expected)}"
        )
    for name, expected_hash in checksums.items():
        if _shared_sha256_file(temp_dir / name) != expected_hash:
            raise RuntimeError(f"CHECKSUM_MISMATCH: {name}")


def run_discovery(request: DiscoveryRequest) -> Mapping[str, Any]:
    """Execute the once-only future discovery after explicit external freeze."""

    preflight = validate_discovery_preflight(request)
    temp_dir = DEFAULT_OUTPUT_DIR.parent / f".{DEFAULT_OUTPUT_DIR.name}.tmp-{uuid4().hex}"
    temp_dir.mkdir(parents=True, exist_ok=False)
    progress = ExecutionProgress(path=temp_dir / "execution_progress.json")
    try:
        progress.record("preflight")
        minute, manifest_snapshot = _load_discovery_inputs()
        progress.record("inputs_loaded", rows=len(minute))
        five = attach_causal_session_vwap(resample_complete_rth_1m_to_5m(minute))
        progress.record("resampled_and_vwap", rows=len(five))
        events, exclusions = _detect_events(five)
        if events.empty:
            raise ValueError("No confirmed events; required gate cannot be estimated.")
        paths = compute_path_metrics(events, five)
        controls = build_unconditional_candidates(events, five)
        controlled = build_exact_time_control(paths, controls)
        primary = controlled[controlled["horizon"] == PRIMARY_HORIZON].copy()
        progress.record("events_paths_controls", events=len(events), primary_rows=len(primary))
        intervals = clustered_percentile_bootstrap(primary)
        concentration = annual_concentration(primary)
        loo = leave_one_largest_session_out(primary)
        metrics = _gate_metric_mapping(primary, intervals, concentration.value, loo)
        statuses = derive_substantive_criteria(metrics, preflight["config"]["discovery_gate"]["criteria"])
        gate = classify_gate(statuses)
        progress.record("aggregations_and_bootstrap")
        _write_closed_outputs(
            temp_dir,
            manifest_snapshot=manifest_snapshot,
            events=events,
            exclusions=exclusions,
            paths=paths,
            controlled=controlled,
            intervals=intervals,
            concentration=concentration,
            loo=loo,
            gate=gate,
            progress=progress,
        )
        _finalize_temp_inventory(temp_dir, progress)
        _shared_atomic_rename(temp_dir, DEFAULT_OUTPUT_DIR)
        return {
            "hypothesis_id": HYPOTHESIS_ID,
            "mode": "run_discovery",
            "discovery_executed": True,
            "classification": gate.classification,
            "results_written": True,
            "output_directory": str(DEFAULT_OUTPUT_DIR),
        }
    except BaseException:
        progress.results_written = False
        if temp_dir.exists():
            progress.persist()
            run_manifest_path = temp_dir / "run_manifest.json"
            if run_manifest_path.exists():
                run_manifest = json.loads(run_manifest_path.read_text(encoding="utf-8"))
                run_manifest["results_written"] = False
                run_manifest.pop("completed_at", None)
                _shared_write_json_atomic(run_manifest_path, run_manifest)
                checksums_path = temp_dir / "checksums.json"
                if checksums_path.exists():
                    checksums = json.loads(checksums_path.read_text(encoding="utf-8"))
                    checksums["run_manifest.json"] = _shared_sha256_file(run_manifest_path)
                    _shared_write_json_atomic(checksums_path, checksums)
        raise


def build_parser() -> argparse.ArgumentParser:
    """Build the two-mode governed CLI."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", required=True, choices=("validate_implementation", "run_discovery"))
    parser.add_argument("--expected-amendment-freeze-commit")
    parser.add_argument("--expected-implementation-freeze-commit")
    parser.add_argument("--expected-canonical-hash")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run validation or future discovery and print one JSON result."""

    args = build_parser().parse_args(argv)
    request = DiscoveryRequest(
        mode=args.mode,
        expected_amendment_freeze_commit=args.expected_amendment_freeze_commit,
        expected_implementation_freeze_commit=args.expected_implementation_freeze_commit,
        expected_canonical_hash=args.expected_canonical_hash,
    )
    result = validate_implementation(request) if args.mode == "validate_implementation" else run_discovery(request)
    print(json.dumps(result, ensure_ascii=True, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
