from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

import pandas as pd


SUPPORTED_OVERRIDE_VERSION = 1
EXCLUDE_ENTIRE_SESSION = "exclude_entire_session"


@dataclass(frozen=True)
class ExcludedSession:
    symbol: str
    date: str
    reason: str
    missing_timestamps: list[str] = field(default_factory=list)
    source: str = ""
    policy: str = EXCLUDE_ENTIRE_SESSION
    created_by: str = ""

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> "ExcludedSession":
        symbol = str(record.get("symbol", "")).upper().strip()
        date = str(record.get("date", "")).strip()
        reason = str(record.get("reason", "")).strip()
        policy = str(record.get("policy", EXCLUDE_ENTIRE_SESSION)).strip()
        if not symbol:
            raise ValueError("Excluded session override is missing symbol")
        if not date:
            raise ValueError(f"Excluded session override for {symbol} is missing date")
        pd.Timestamp(date).date()
        if not reason:
            raise ValueError(f"Excluded session override for {symbol} {date} is missing reason")
        if policy != EXCLUDE_ENTIRE_SESSION:
            raise ValueError(
                f"Unsupported excluded session policy {policy!r}; "
                f"only {EXCLUDE_ENTIRE_SESSION!r} is supported"
            )
        missing = record.get("missing_timestamps", [])
        if not isinstance(missing, list):
            raise ValueError("missing_timestamps must be a list")
        return cls(
            symbol=symbol,
            date=pd.Timestamp(date).date().isoformat(),
            reason=reason,
            missing_timestamps=[str(item) for item in missing],
            source=str(record.get("source", "")).strip(),
            policy=policy,
            created_by=str(record.get("created_by", "")).strip(),
        )

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class QualityOverrides:
    version: int = SUPPORTED_OVERRIDE_VERSION
    excluded_sessions: list[ExcludedSession] = field(default_factory=list)

    @classmethod
    def empty(cls) -> "QualityOverrides":
        return cls()

    @classmethod
    def from_record(cls, payload: dict[str, Any]) -> "QualityOverrides":
        version = int(payload.get("version", 0))
        if version != SUPPORTED_OVERRIDE_VERSION:
            raise ValueError(
                f"Unsupported excluded sessions override version {version}; "
                f"expected {SUPPORTED_OVERRIDE_VERSION}"
            )
        raw_sessions = payload.get("excluded_sessions", [])
        if not isinstance(raw_sessions, list):
            raise ValueError("excluded_sessions must be a list")
        return cls(
            version=version,
            excluded_sessions=[
                ExcludedSession.from_record(record) for record in raw_sessions
            ],
        )

    def matching_sessions(
        self,
        *,
        symbol: str,
        dates: Iterable[str],
    ) -> list[ExcludedSession]:
        wanted_symbol = symbol.upper().strip()
        wanted_dates = {pd.Timestamp(date).date().isoformat() for date in dates}
        return [
            session
            for session in self.excluded_sessions
            if session.symbol == wanted_symbol and session.date in wanted_dates
        ]

    def dates_for_symbol(self, symbol: str) -> set[str]:
        wanted_symbol = symbol.upper().strip()
        return {
            session.date
            for session in self.excluded_sessions
            if session.symbol == wanted_symbol
        }

    def to_record(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "excluded_sessions": [
                session.to_record() for session in self.excluded_sessions
            ],
        }


def load_quality_overrides(path: str | Path | None) -> QualityOverrides:
    if path is None:
        return QualityOverrides.empty()
    source = Path(path)
    if not source.exists():
        raise FileNotFoundError(f"Excluded sessions file not found: {source}")
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Excluded sessions override file must contain a JSON object")
    return QualityOverrides.from_record(payload)

