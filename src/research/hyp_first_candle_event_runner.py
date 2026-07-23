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


CONFIG_PATH = Path("configs/research/hypotheses/HYP-FCR-EVENT-01.yaml")


@dataclass(frozen=True)
class FcrEventStudyRunRequest:
    mode: Literal["prepare_only"] = "prepare_only"
    period: str = "discovery_2022_2024"
    config_path: Path = CONFIG_PATH
    safety_flags: dict[str, bool] = field(default_factory=lambda: dict(SAFETY_FLAGS))


def validate_event_study_request(request: FcrEventStudyRunRequest) -> None:
    if request.mode != "prepare_only":
        raise PermissionError("HYP-FCR-EVENT-01 runner is locked to prepare_only.")
    validate_event_study_period(request.period)
    if any(bool(value) for value in request.safety_flags.values()):
        raise PermissionError("Safety flags must remain false for event-study preparation.")


def prepare_event_study_manifest(request: FcrEventStudyRunRequest | None = None) -> dict[str, Any]:
    request = request or FcrEventStudyRunRequest()
    validate_event_study_request(request)
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
    parser = argparse.ArgumentParser(description="Prepare HYP-FCR-EVENT-01 manifest only.")
    parser.add_argument("--mode", default="prepare_only")
    parser.add_argument("--period", default="discovery_2022_2024")
    args = parser.parse_args()
    manifest = prepare_event_study_manifest(
        FcrEventStudyRunRequest(mode=args.mode, period=args.period)  # type: ignore[arg-type]
    )
    print(json.dumps(manifest, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()

