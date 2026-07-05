from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd


REQUIRED_FIELDS = {
    "id",
    "name",
    "source_type",
    "source_url",
    "author",
    "recommended_market",
    "recommended_timeframes",
    "recommended_assets",
    "indicators",
    "long_entry",
    "long_exit",
    "short_entry",
    "short_exit",
    "stop_loss",
    "take_profit",
    "trailing_stop",
    "suggested_risk",
    "trading_hours",
    "no_trade_conditions",
    "parameters",
    "assumptions",
    "ambiguity_level",
    "repainting_risk",
    "lookahead_risk",
    "cherry_picking_risk",
    "human_discretion_dependency",
    "programmable",
    "required_data",
    "economic_rationale",
}


def _load_yaml_compatible(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        try:
            import yaml  # type: ignore
        except ImportError as exc:
            raise ValueError(
                f"{path} must use JSON-compatible YAML when PyYAML is unavailable"
            ) from exc
        payload = yaml.safe_load(text)
    if not isinstance(payload, dict):
        raise ValueError("Catalog root must be an object")
    return payload


@dataclass(frozen=True)
class StrategyCatalog:
    entries: tuple[dict[str, Any], ...]
    source: Path

    @classmethod
    def load(
        cls,
        path: str | Path = "data/strategy_intake/strategy_catalog.yaml",
    ) -> "StrategyCatalog":
        source = Path(path)
        payload = _load_yaml_compatible(source)
        entries = payload.get("strategies")
        if not isinstance(entries, list):
            raise ValueError("Catalog requires a strategies list")
        identifiers: set[str] = set()
        validated = []
        for position, entry in enumerate(entries):
            if not isinstance(entry, dict):
                raise ValueError(f"Strategy {position} must be an object")
            missing = REQUIRED_FIELDS.difference(entry)
            if missing:
                raise ValueError(
                    f"Strategy {entry.get('id', position)} missing fields: {sorted(missing)}"
                )
            identifier = str(entry["id"])
            if identifier in identifiers:
                raise ValueError(f"Duplicate strategy id: {identifier}")
            identifiers.add(identifier)
            validated.append(entry)
        return cls(tuple(validated), source.resolve())

    def by_id(self, strategy_id: str) -> dict[str, Any]:
        for entry in self.entries:
            if entry["id"] == strategy_id:
                return entry
        raise KeyError(strategy_id)

    def to_frame(self) -> pd.DataFrame:
        rows = []
        for entry in self.entries:
            row = {}
            for key, value in entry.items():
                row[key] = (
                    json.dumps(value, ensure_ascii=False, sort_keys=True)
                    if isinstance(value, (dict, list))
                    else value
                )
            rows.append(row)
        return pd.DataFrame(rows)
