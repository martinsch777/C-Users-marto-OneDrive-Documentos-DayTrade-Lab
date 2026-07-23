from __future__ import annotations

import argparse
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml

from src.data.dataset_manifest import APPROVED_FOR_OR_FVG_BACKTEST
from src.research.hyp_first_candle_event_study import (
    HYPOTHESIS_ID,
    SAFETY_FLAGS,
    canonical_event_config_hash,
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
SPY_FAILED_ANNUAL_MANIFEST_PATH = Path(
    "data/manifests/SPY_1min_2023-01-01_2023-12-31_alpaca_sip_raw_rth_manifest.json"
)
FULL_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class RuntimeState:
    head_commit: str
    working_tree_clean: bool


@dataclass(frozen=True)
class FcrEventDiscoveryRequest:
    mode: Literal["prepare_only", "run_discovery"] = "prepare_only"
    expected_freeze_commit: str = ""
    expected_canonical_hash: str = ""
    period: str = DISCOVERY_PERIOD
    symbols: tuple[str, ...] = EXPECTED_SYMBOLS
    requested_start: str = DISCOVERY_START
    requested_end: str = DISCOVERY_END
    config_path: Path = CONFIG_PATH
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
    if request.mode != "run_discovery":
        raise PermissionError(f"Unsupported HYP-FCR-EVENT-01 mode: {request.mode}")
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Operational preflight for HYP-FCR-EVENT-01 discovery.")
    parser.add_argument("--mode", choices=("prepare_only", "run_discovery"), default="prepare_only")
    parser.add_argument("--expected-freeze-commit", default="")
    parser.add_argument("--expected-canonical-hash", default="")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    payload = validate_discovery_preflight(
        FcrEventDiscoveryRequest(
            mode=args.mode,
            expected_freeze_commit=args.expected_freeze_commit,
            expected_canonical_hash=args.expected_canonical_hash,
        )
    )
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
