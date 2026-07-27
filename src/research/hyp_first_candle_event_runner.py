from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from src.research.hyp_first_candle_event_study import (
    HYPOTHESIS_ID,
    SAFETY_FLAGS,
    canonical_event_config_hash,
    validate_event_study_period,
)
from src.research.hyp_first_candle_event_discovery import (
    DEFAULT_OUTPUT_DIR,
    FcrEventDiscoveryRequest,
    run_operational_discovery,
)


CONFIG_PATH = Path("configs/research/hypotheses/HYP-FCR-EVENT-01.yaml")


@dataclass(frozen=True)
class FcrEventStudyRunRequest:
    mode: Literal["prepare_only", "run_discovery", "profile_synthetic", "benchmark_subset"] = "prepare_only"
    period: str = "discovery_2022_2024"
    config_path: Path = CONFIG_PATH
    expected_freeze_commit: str = ""
    expected_canonical_hash: str = ""
    max_sessions_per_symbol: int | None = None
    output_dir: Path = DEFAULT_OUTPUT_DIR
    safety_flags: dict[str, bool] = field(default_factory=lambda: dict(SAFETY_FLAGS))


def validate_event_study_request(request: FcrEventStudyRunRequest) -> None:
    if request.mode not in ("prepare_only", "run_discovery", "profile_synthetic", "benchmark_subset"):
        raise PermissionError(f"Unsupported HYP-FCR-EVENT-01 mode: {request.mode}")
    validate_event_study_period(request.period)
    if any(bool(value) for value in request.safety_flags.values()):
        raise PermissionError("Safety flags must remain false for event-study preparation.")
    if request.mode in ("run_discovery", "benchmark_subset") and not request.expected_freeze_commit:
        raise PermissionError(f"--expected-freeze-commit is required for {request.mode}.")
    if request.mode in ("run_discovery", "benchmark_subset") and not request.expected_canonical_hash:
        raise PermissionError(f"--expected-canonical-hash is required for {request.mode}.")
    if request.mode == "benchmark_subset" and request.max_sessions_per_symbol is None:
        raise PermissionError("--max-sessions-per-symbol is required for benchmark_subset.")


def prepare_event_study_manifest(request: FcrEventStudyRunRequest | None = None) -> dict[str, Any]:
    request = request or FcrEventStudyRunRequest()
    validate_event_study_request(request)
    if request.mode in ("run_discovery", "profile_synthetic", "benchmark_subset"):
        return run_operational_discovery(
            FcrEventDiscoveryRequest(
                mode=request.mode,
                expected_freeze_commit=request.expected_freeze_commit,
                expected_canonical_hash=request.expected_canonical_hash,
                max_sessions_per_symbol=request.max_sessions_per_symbol,
                config_path=request.config_path,
                safety_flags=request.safety_flags,
            ),
            output_dir=request.output_dir,
        )
    config_hash = canonical_event_config_hash(request.config_path) if request.config_path.exists() else None
    return {
        "hypothesis_id": HYPOTHESIS_ID,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "mode": request.mode,
        "period": request.period,
        "event_study_executed": False,
        "results_written": False,
        "validation_2025_executed": False,
        "parity_2026_executed": False,
        "holdout_executed": False,
        "orders_sent": False,
        "position_sizing_used": False,
        "paper_eligible": False,
        "live_eligible": False,
        "config_path": str(request.config_path),
        "canonical_payload_hash": config_hash,
        "safety_flags": dict(request.safety_flags),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare or run authorized HYP-FCR-EVENT-01 discovery.")
    parser.add_argument(
        "--mode",
        choices=("prepare_only", "run_discovery", "profile_synthetic", "benchmark_subset"),
        default="prepare_only",
    )
    parser.add_argument("--period", default="discovery_2022_2024")
    parser.add_argument("--expected-freeze-commit", default="")
    parser.add_argument("--expected-canonical-hash", default="")
    parser.add_argument("--max-sessions-per-symbol", type=int, default=None)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    args = parser.parse_args()
    manifest = prepare_event_study_manifest(
        FcrEventStudyRunRequest(
            mode=args.mode,
            period=args.period,
            expected_freeze_commit=args.expected_freeze_commit,
            expected_canonical_hash=args.expected_canonical_hash,
            max_sessions_per_symbol=args.max_sessions_per_symbol,
            output_dir=Path(args.output_dir),
        )
    )
    print(json.dumps(manifest, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
