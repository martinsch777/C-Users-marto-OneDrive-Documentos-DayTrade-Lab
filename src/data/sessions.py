from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, time
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

import pandas as pd


def _as_date(value: date | str) -> date:
    return value if isinstance(value, date) else date.fromisoformat(str(value))


@dataclass(frozen=True)
class EquitySessionCalendar:
    """Configurable RTH calendar; exchange schedules can be injected explicitly."""

    timezone: str = "America/New_York"
    regular_open: time = time(9, 30)
    regular_close: time = time(16, 0)
    holidays: frozenset[date] = field(default_factory=frozenset)
    early_closes: Mapping[date, time] = field(default_factory=dict)

    @classmethod
    def from_config(
        cls,
        config: Mapping[str, Any] | None = None,
        *,
        timezone: str = "America/New_York",
        regular_open: str = "09:30",
        regular_close: str = "16:00",
    ) -> "EquitySessionCalendar":
        values = dict(config or {})
        holidays = frozenset(
            _as_date(value) for value in values.get("holidays", [])
        )
        early_closes = {
            _as_date(day): time.fromisoformat(str(close))
            for day, close in values.get("early_closes", {}).items()
        }
        return cls(
            timezone=str(values.get("timezone", timezone)),
            regular_open=time.fromisoformat(
                str(values.get("regular_open", regular_open))
            ),
            regular_close=time.fromisoformat(
                str(values.get("regular_close", regular_close))
            ),
            holidays=holidays,
            early_closes=early_closes,
        )

    def is_session_day(self, session_date: date) -> bool:
        return session_date.weekday() < 5 and session_date not in self.holidays

    def session_close(self, session_date: date) -> time | None:
        if not self.is_session_day(session_date):
            return None
        return self.early_closes.get(session_date, self.regular_close)

    def contains(self, timestamp: pd.Timestamp) -> bool:
        local = timestamp.tz_convert(ZoneInfo(self.timezone))
        close = self.session_close(local.date())
        if close is None:
            return False
        clock = local.time().replace(tzinfo=None)
        return self.regular_open <= clock < close

    def mask(self, timestamps: Iterable[pd.Timestamp] | pd.Series) -> pd.Series:
        values = pd.Series(timestamps, copy=False)
        return values.map(self.contains).astype(bool)

    def localize(self, timestamps: pd.Series) -> pd.Series:
        return pd.to_datetime(timestamps, utc=True).dt.tz_convert(
            ZoneInfo(self.timezone)
        )


__all__ = ["EquitySessionCalendar"]
