from __future__ import annotations

from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from .base import Signal, Strategy


class OpeningRangeBreakoutStrategy(Strategy):
    name = "opening_range_breakout"

    def generate_signals(
        self,
        frame: pd.DataFrame,
        symbol: str,
        timeframe: str,
    ) -> list[Signal]:
        data = self.prepare(frame)
        timezone = str(self.config.get("session_timezone", "America/New_York"))
        local_time = data["timestamp"].dt.tz_convert(ZoneInfo(timezone))
        data["_session"] = local_time.dt.date
        data["_minute"] = local_time.dt.hour * 60 + local_time.dt.minute
        opening_minutes = int(self.config.get("opening_range_minutes", 30))
        session_start = str(self.config.get("session_start", "09:30"))
        start_hour, start_minute = (int(value) for value in session_start.split(":"))
        session_start_minutes = start_hour * 60 + start_minute
        opening_end = session_start_minutes + opening_minutes
        candidate_end_text = str(self.config.get("candidate_end", "15:30"))
        end_hour, end_minute = (
            int(value) for value in candidate_end_text.split(":")
        )
        candidate_end = end_hour * 60 + end_minute
        min_atr = float(self.config.get("minimum_range_atr", 0.5))
        max_atr = float(self.config.get("maximum_range_atr", 3.0))
        minimum_rvol = float(self.config.get("minimum_relative_volume", 1.2))
        risk_reward = float(self.config.get("risk_reward", 2.0))
        signals: list[Signal] = []

        for _, session in data.groupby("_session", sort=True):
            opening = session[
                (session["_minute"] >= session_start_minutes)
                & (session["_minute"] < opening_end)
            ]
            candidates = session[
                (session["_minute"] >= opening_end)
                & (session["_minute"] <= candidate_end)
            ]
            if opening.empty or candidates.empty:
                continue
            range_high = float(opening["high"].max())
            range_low = float(opening["low"].min())
            range_size = range_high - range_low
            atr_value = float(opening["atr"].iloc[-1])
            if pd.isna(atr_value) or not (min_atr * atr_value <= range_size <= max_atr * atr_value):
                continue
            previous_close = session["close"].shift(1)
            long_index = candidates.index[
                (previous_close.loc[candidates.index] <= range_high)
                & (candidates["close"] > range_high)
                & (candidates["relative_volume"] >= minimum_rvol)
            ]
            short_index = candidates.index[
                (previous_close.loc[candidates.index] >= range_low)
                & (candidates["close"] < range_low)
                & (candidates["relative_volume"] >= minimum_rvol)
            ]
            events = sorted(
                [(int(index), "long") for index in long_index[:1]]
                + [(int(index), "short") for index in short_index[:1]]
            )
            for index, side in events:
                row = data.loc[index]
                entry = float(row["close"])
                stop = (
                    max(range_low, range_high - atr_value)
                    if side == "long"
                    else min(range_high, range_low + atr_value)
                )
                stop, target = self._levels(entry, stop, side, risk_reward)
                signals.append(
                    Signal(
                        timestamp=row["timestamp"],
                        symbol=symbol,
                        timeframe=timeframe,
                        strategy=self.name,
                        side=side,
                        entry_price=entry,
                        stop_price=stop,
                        take_profit=target,
                        reason=f"{side} break of {opening_minutes}-minute opening range",
                        relative_volume=float(row["relative_volume"]),
                        atr=atr_value,
                        metadata={
                            "opening_range_high": range_high,
                            "opening_range_low": range_low,
                        },
                    )
                )
        return signals
