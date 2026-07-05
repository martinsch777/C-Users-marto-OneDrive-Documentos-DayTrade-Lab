from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ConfigError(ValueError):
    """Raised when configuration is invalid or unsafe."""


@dataclass(frozen=True)
class LabConfig:
    raw: dict[str, Any]
    source: Path

    def section(self, name: str) -> dict[str, Any]:
        value = self.raw.get(name, {})
        if not isinstance(value, dict):
            raise ConfigError(f"Configuration section '{name}' must be an object")
        return value

    @property
    def security(self) -> dict[str, bool]:
        return self.section("security")

    def strategy(self, name: str) -> dict[str, Any]:
        return self.section("strategies").get(name, {})


def _parse_config(text: str) -> dict[str, Any]:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        try:
            import yaml  # type: ignore
        except ImportError as exc:
            raise ConfigError(
                "config.yaml is not JSON-compatible YAML and PyYAML is not installed"
            ) from exc
        parsed = yaml.safe_load(text)
    if not isinstance(parsed, dict):
        raise ConfigError("The configuration root must be an object")
    return parsed


def _validate_security(raw: dict[str, Any]) -> None:
    security = raw.get("security")
    if not isinstance(security, dict):
        raise ConfigError("Missing security configuration")
    required_false = (
        "live_trading_enabled",
        "broker_connected",
        "orders_sent",
        "paper_internal_enabled",
        "paper_broker_enabled",
    )
    unsafe = [key for key in required_false if security.get(key) is not False]
    if unsafe:
        joined = ", ".join(unsafe)
        raise ConfigError(f"Unsafe configuration rejected; must be false: {joined}")


def load_config(path: str | Path = "config.yaml") -> LabConfig:
    source = Path(path).resolve()
    raw = _parse_config(source.read_text(encoding="utf-8"))
    _validate_security(raw)
    return LabConfig(raw=raw, source=source)
