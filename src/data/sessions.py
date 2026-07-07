from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, time
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

import pandas as pd


US_EQUITY_CALENDAR_START = date(1990, 1, 1)
US_EQUITY_CALENDAR_END = date(2035, 12, 31)


def _as_date(value: date | str) -> date:
    return value if isinstance(value, date) else date.fromisoformat(str(value))


def _nth_weekday(year: int, month: int, weekday: int, nth: int) -> date:
    current = date(year, month, 1)
    while current.weekday() != weekday:
        current += timedelta(days=1)
    return current + timedelta(days=7 * (nth - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    if month == 12:
        current = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        current = date(year, month + 1, 1) - timedelta(days=1)
    while current.weekday() != weekday:
        current -= timedelta(days=1)
    return current


def _observed_fixed_holiday(year: int, month: int, day: int) -> date:
    actual = date(year, month, day)
    if actual.weekday() == 5:
        return actual - timedelta(days=1)
    if actual.weekday() == 6:
        return actual + timedelta(days=1)
    return actual


def _easter_sunday(year: int) -> date:
    """Gregorian computus used to derive Good Friday."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def _thanksgiving(year: int) -> date:
    return _nth_weekday(year, 11, 3, 4)


def _previous_session_day(day: date, holidays: set[date]) -> date:
    current = day - timedelta(days=1)
    while current.weekday() >= 5 or current in holidays:
        current -= timedelta(days=1)
    return current


def _us_equity_holiday_reasons_for_year(year: int) -> dict[date, str]:
    holidays = {
        _observed_fixed_holiday(year, 1, 1): "New Year observed",
        _nth_weekday(year, 1, 0, 3): "Martin Luther King Jr. Day",
        _nth_weekday(year, 2, 0, 3): "Washington's Birthday",
        _easter_sunday(year) - timedelta(days=2): "Good Friday",
        _last_weekday(year, 5, 0): "Memorial Day",
        _observed_fixed_holiday(year, 7, 4): "Independence Day observed",
        _nth_weekday(year, 9, 0, 1): "Labor Day",
        _thanksgiving(year): "Thanksgiving Day",
        _observed_fixed_holiday(year, 12, 25): "Christmas observed",
    }
    if year >= 2022:
        holidays[_observed_fixed_holiday(year, 6, 19)] = "Juneteenth observed"
    special_closures = {
        date(2001, 9, 11): "September 11 market closure",
        date(2001, 9, 12): "September 11 market closure",
        date(2001, 9, 13): "September 11 market closure",
        date(2001, 9, 14): "September 11 market closure",
        date(2004, 6, 11): "National Day of Mourning for Ronald Reagan",
        date(2007, 1, 2): "National Day of Mourning for Gerald Ford",
        date(2012, 10, 29): "Hurricane Sandy market closure",
        date(2012, 10, 30): "Hurricane Sandy market closure",
        date(2018, 12, 5): "National Day of Mourning for George H. W. Bush",
        date(2025, 1, 9): "National Day of Mourning for Jimmy Carter",
    }
    holidays.update(
        {
            day: reason
            for day, reason in special_closures.items()
            if day.year == year
        }
    )
    return holidays


def _build_us_equity_calendar(
    start_year: int = US_EQUITY_CALENDAR_START.year,
    end_year: int = US_EQUITY_CALENDAR_END.year,
) -> tuple[frozenset[date], dict[date, time], dict[date, str]]:
    holiday_reasons: dict[date, str] = {}
    for year in range(start_year - 1, end_year + 2):
        holiday_reasons.update(_us_equity_holiday_reasons_for_year(year))
    holiday_reasons = {
        day: reason
        for day, reason in holiday_reasons.items()
        if US_EQUITY_CALENDAR_START <= day <= US_EQUITY_CALENDAR_END
    }
    holidays = set(holiday_reasons)
    early_closes: dict[date, time] = {}
    early_close_time = time(13, 0)
    for year in range(start_year, end_year + 1):
        black_friday = _thanksgiving(year) + timedelta(days=1)
        if black_friday.weekday() < 5 and black_friday not in holidays:
            early_closes[black_friday] = early_close_time

        christmas_eve = date(year, 12, 24)
        if christmas_eve.weekday() < 5 and christmas_eve not in holidays:
            early_closes[christmas_eve] = early_close_time

        independence_observed = _observed_fixed_holiday(year, 7, 4)
        previous = _previous_session_day(independence_observed, holidays)
        if previous.year == year and previous not in holidays:
            early_closes[previous] = early_close_time

    return frozenset(holidays), early_closes, holiday_reasons


@dataclass(frozen=True)
class EquitySessionCalendar:
    """Configurable RTH calendar; exchange schedules can be injected explicitly."""

    timezone: str = "America/New_York"
    regular_open: time = time(9, 30)
    regular_close: time = time(16, 0)
    holidays: frozenset[date] = field(default_factory=frozenset)
    early_closes: Mapping[date, time] = field(default_factory=dict)
    name: str = "custom"
    source: str = "manual"
    loaded: bool = False
    supported_start: date | None = None
    supported_end: date | None = None
    holiday_reasons: Mapping[date, str] = field(default_factory=dict)

    @classmethod
    def us_equity(
        cls,
        *,
        timezone: str = "America/New_York",
        regular_open: str = "09:30",
        regular_close: str = "16:00",
    ) -> "EquitySessionCalendar":
        holidays, early_closes, holiday_reasons = _build_us_equity_calendar()
        return cls(
            timezone=timezone,
            regular_open=time.fromisoformat(regular_open),
            regular_close=time.fromisoformat(regular_close),
            holidays=holidays,
            early_closes=early_closes,
            name="US_EQUITY_RTH",
            source="builtin_us_equity_calendar_v1",
            loaded=True,
            supported_start=US_EQUITY_CALENDAR_START,
            supported_end=US_EQUITY_CALENDAR_END,
            holiday_reasons=holiday_reasons,
        )

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
        source = str(values.get("source", "us_equity")).lower()
        use_builtin = source in {
            "us_equity",
            "us_equities",
            "nyse",
            "nasdaq",
            "xnys",
            "xnas",
            "builtin_us_equity",
        }
        base = (
            cls.us_equity(
                timezone=str(values.get("timezone", timezone)),
                regular_open=str(values.get("regular_open", regular_open)),
                regular_close=str(values.get("regular_close", regular_close)),
            )
            if use_builtin
            else cls(
                timezone=str(values.get("timezone", timezone)),
                regular_open=time.fromisoformat(
                    str(values.get("regular_open", regular_open))
                ),
                regular_close=time.fromisoformat(
                    str(values.get("regular_close", regular_close))
                ),
                name=str(values.get("name", "custom")),
                source=source,
                loaded=False,
            )
        )
        holidays = frozenset(
            _as_date(value) for value in values.get("holidays", [])
        )
        explicit_holiday_reasons = {
            _as_date(day): str(reason)
            for day, reason in values.get("holiday_reasons", {}).items()
        }
        early_closes = {
            _as_date(day): time.fromisoformat(str(close))
            for day, close in values.get("early_closes", {}).items()
        }
        return cls(
            timezone=base.timezone,
            regular_open=base.regular_open,
            regular_close=base.regular_close,
            holidays=frozenset(set(base.holidays).union(holidays)),
            early_closes={**dict(base.early_closes), **early_closes},
            name=str(values.get("name", base.name)),
            source=base.source if use_builtin else source,
            loaded=bool(base.loaded or holidays or early_closes),
            supported_start=base.supported_start,
            supported_end=base.supported_end,
            holiday_reasons={
                **dict(base.holiday_reasons),
                **{day: "Configured holiday" for day in holidays},
                **explicit_holiday_reasons,
            },
        )

    def is_session_day(self, session_date: date) -> bool:
        return session_date.weekday() < 5 and session_date not in self.holidays

    def session_close(self, session_date: date) -> time | None:
        if not self.is_session_day(session_date):
            return None
        return self.early_closes.get(session_date, self.regular_close)

    def session_reason(self, session_date: date) -> str:
        if session_date.weekday() >= 5:
            return "Weekend"
        if session_date in self.holidays:
            return self.holiday_reasons.get(session_date, "Market holiday")
        if session_date in self.early_closes:
            return "Early close"
        return "Regular session"

    def supports(self, session_date: date) -> bool:
        if self.supported_start is None or self.supported_end is None:
            return True
        return self.supported_start <= session_date <= self.supported_end

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

    def expected_timestamps(
        self,
        start_date: date,
        end_date: date,
        timeframe: str = "1min",
    ) -> pd.DatetimeIndex:
        """Return expected UTC bar opens for all configured equity RTH sessions."""
        duration = pd.Timedelta(timeframe)
        local_zone = ZoneInfo(self.timezone)
        expected: list[pd.Timestamp] = []
        for session_date in pd.date_range(start_date, end_date, freq="D"):
            current_date = session_date.date()
            close = self.session_close(current_date)
            if close is None:
                continue
            local_open = pd.Timestamp(
                datetime.combine(current_date, self.regular_open),
                tz=local_zone,
            )
            local_last_open = pd.Timestamp(
                datetime.combine(current_date, close),
                tz=local_zone,
            ) - duration
            if local_last_open < local_open:
                continue
            expected.extend(
                pd.date_range(
                    local_open,
                    local_last_open,
                    freq=duration,
                ).tz_convert("UTC")
            )
        return pd.DatetimeIndex(expected, tz="UTC")

    def diagnostics(
        self,
        start_date: date,
        end_date: date,
        timeframe: str = "1min",
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for session_date in pd.date_range(start_date, end_date, freq="D"):
            current_date = session_date.date()
            close = self.session_close(current_date)
            expected = self.expected_timestamps(
                current_date,
                current_date,
                timeframe,
            )
            rows.append(
                {
                    "date": current_date.isoformat(),
                    "is_session": close is not None,
                    "open": (
                        self.regular_open.isoformat(timespec="minutes")
                        if close is not None
                        else ""
                    ),
                    "close": close.isoformat(timespec="minutes") if close else "",
                    "is_early_close": bool(
                        close is not None and close != self.regular_close
                    ),
                    "expected_1min_bars": len(expected),
                    "reason": self.session_reason(current_date),
                }
            )
        return rows


__all__ = ["EquitySessionCalendar"]
