from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Literal

import yaml

from src.data import EquitySessionCalendar
from src.research.hyp_first_candle import load_symbol_curated_1min


FAMILY_ID = "FCR-REFINEMENT-FAMILY-01"
VARIANT_IDS = ("HYP-FCR-02", "HYP-FCR-03", "HYP-FCR-04")
DISCOVERY_START = date(2022, 1, 1)
DISCOVERY_END = date(2024, 12, 31)
VALIDATION_START = date(2025, 1, 1)
VALIDATION_END = date(2025, 12, 31)
CONFIG_DIR = Path("configs/research/hypotheses")
FAMILY_CONFIG_PATH = CONFIG_DIR / f"{FAMILY_ID}.yaml"


@dataclass(frozen=True)
class FamilyRunRequest:
    mode: Literal["prepare_only", "discovery", "validation", "holdout", "parity_debug_2026"] = "prepare_only"
    variant_ids: tuple[str, ...] = VARIANT_IDS


def canonical_yaml_hash(path: str | Path) -> str:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        payload.pop("canonical_payload_hash", None)
        payload.pop("yaml_sha256", None)
        configuration_hash = payload.get("configuration_hash")
        if isinstance(configuration_hash, dict):
            configuration_hash.pop("sha256", None)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_variant_set(variant_ids: tuple[str, ...] = VARIANT_IDS) -> None:
    if tuple(variant_ids) != VARIANT_IDS:
        raise PermissionError("FCR refinement family must contain exactly HYP-FCR-02, HYP-FCR-03, and HYP-FCR-04.")


def validate_family_run_request(request: FamilyRunRequest) -> None:
    validate_variant_set(request.variant_ids)
    if request.mode != "prepare_only":
        raise PermissionError("This runner is locked to prepare_only; discovery, validation, 2026, and holdout are blocked.")


def validate_family_manifests(dataset_paths: dict[str, Path], *, manifest_dir: Path = Path("data/manifests")) -> dict[str, str]:
    calendar = EquitySessionCalendar.from_config({"source": "us_equity"})
    hashes: dict[str, str] = {}
    for symbol, path in dataset_paths.items():
        _, manifest = load_symbol_curated_1min(path, symbol, manifest_dir=manifest_dir, calendar=calendar)
        hashes[symbol.upper()] = manifest.sha256
    return hashes


def passed_individual_gate(result: dict[str, Any]) -> bool:
    return bool(result.get("gate_passed") or result.get("status") == "discovery_passed")


def select_family_variant(results: list[dict[str, Any]]) -> dict[str, Any]:
    result_ids = tuple(item["hypothesis_id"] for item in results)
    validate_variant_set(result_ids)
    passed = [item for item in results if passed_individual_gate(item)]
    if not passed:
        return {
            "family_status": "discovery_failed",
            "selected_hypothesis_id": None,
            "validation_2025_unlocked": False,
            "variant_statuses": {item["hypothesis_id"]: "discovery_failed" for item in results},
        }
    if len(passed) == 1:
        selected = passed[0]
    else:
        best_stress = max(float(item["stress_net_expectancy_R"]) for item in passed)
        stress_leaders = [
            item
            for item in passed
            if abs(best_stress - float(item["stress_net_expectancy_R"])) < 0.01
        ]
        if len(stress_leaders) == 1:
            selected = stress_leaders[0]
        else:
            selected = sorted(
                stress_leaders,
                key=lambda item: (
                    -float(item["baseline_profit_factor_net"]),
                    float(item["baseline_maximum_drawdown"]),
                    str(item["hypothesis_id"]),
                ),
            )[0]
    statuses = {}
    for item in results:
        if item["hypothesis_id"] == selected["hypothesis_id"]:
            statuses[item["hypothesis_id"]] = "discovery_passed_selected"
        elif passed_individual_gate(item):
            statuses[item["hypothesis_id"]] = "discovery_passed_not_selected"
        else:
            statuses[item["hypothesis_id"]] = "discovery_failed"
    return {
        "family_status": "discovery_passed",
        "selected_hypothesis_id": selected["hypothesis_id"],
        "validation_2025_unlocked": True,
        "variant_statuses": statuses,
    }


def prepare_family_manifest() -> dict[str, Any]:
    request = FamilyRunRequest()
    validate_family_run_request(request)
    hashes = {
        hypothesis_id: canonical_yaml_hash(CONFIG_DIR / f"{hypothesis_id}.yaml")
        for hypothesis_id in VARIANT_IDS
    }
    hashes[FAMILY_ID] = canonical_yaml_hash(FAMILY_CONFIG_PATH)
    return {
        "family_id": FAMILY_ID,
        "mode": request.mode,
        "variant_ids": list(VARIANT_IDS),
        "discovery_period": {"start": DISCOVERY_START.isoformat(), "end": DISCOVERY_END.isoformat()},
        "validation_period": {"start": VALIDATION_START.isoformat(), "end": VALIDATION_END.isoformat()},
        "discovery_executed": False,
        "validation_executed": False,
        "contaminated_2026_executed": False,
        "holdout_executed": False,
        "optimization_executed": False,
        "parameter_sweep_executed": False,
        "paper_eligible": False,
        "live_eligible": False,
        "safety_flags": {
            "live_trading": False,
            "broker_connected": False,
            "orders_sent": False,
            "paper_broker_enabled": False,
        },
        "canonical_hashes": hashes,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare FCR refinement family preregistration manifest")
    parser.add_argument("--mode", default="prepare_only")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    validate_family_run_request(FamilyRunRequest(mode=args.mode))
    print(json.dumps(prepare_family_manifest(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
