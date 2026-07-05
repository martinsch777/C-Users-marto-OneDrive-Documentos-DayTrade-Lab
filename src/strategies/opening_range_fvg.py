from __future__ import annotations

from datetime import time

import pandas as pd

from src.data import EquitySessionCalendar
from src.indicators import detect_fvg_and_mss

from .base import Signal, Strategy


class OpeningRangeFVGStrategy(Strategy):
    """Five-minute RTH opening-range breakout confirmed by displacement and FVG."""

    name = "opening_range_fvg"

    def generate_signals(
        self,
        frame: pd.DataFrame,
        symbol: str,
        timeframe: str,
    ) -> list[Signal]:
        if timeframe != "1min" or frame.empty:
            return []

        timezone = str(self.config.get("session_timezone", "America/New_York"))
        calendar = EquitySessionCalendar.from_config(
            self.config.get("calendar", {}),
            timezone=timezone,
            regular_open=str(self.config.get("session_start", "09:30")),
            regular_close=str(self.config.get("session_end", "16:00")),
        )
        rth = frame.loc[calendar.mask(frame["timestamp"]).to_numpy()].copy()
        if rth.empty:
            return []

        data = self.prepare(rth.reset_index(drop=True))
        local_time = calendar.localize(data["timestamp"])
        data["_session"] = local_time.dt.date
        data["_minute"] = local_time.dt.hour * 60 + local_time.dt.minute
        structure = detect_fvg_and_mss(
            data,
            structure_lookback=int(self.config.get("structure_lookback", 20)),
            minimum_gap_atr=float(
                self.config.get("minimum_fvg_gap_atr", 0.2)
            ),
        )

        opening_minutes = int(self.config.get("opening_range_minutes", 5))
        if opening_minutes != 5:
            raise ValueError("OpeningRangeFVGStrategy currently requires a 5-minute range")
        session_start = time.fromisoformat(
            str(self.config.get("session_start", "09:30"))
        )
        start_minute = session_start.hour * 60 + session_start.minute
        opening_end = start_minute + opening_minutes
        candidate_end = time.fromisoformat(
            str(self.config.get("candidate_end", "15:30"))
        )
        candidate_end_minute = candidate_end.hour * 60 + candidate_end.minute

        minimum_range_atr = float(
            self.config.get("minimum_range_atr", 0.5)
        )
        maximum_range_atr = float(
            self.config.get("maximum_range_atr", 5.0)
        )
        minimum_displacement_atr = float(
            self.config.get("minimum_displacement_atr", 0.5)
        )
        risk_reward = float(self.config.get("risk_reward", 2.0))
        max_entry_gap_pct = float(
            self.config.get("max_entry_gap_pct", 0.005)
        )
        max_trades = int(self.config.get("max_trades_per_day", 1))
        stop_mode = str(self.config.get("stop_mode", "breakout_candle"))
        structure_lookback = int(self.config.get("stop_structure_lookback", 5))
        stop_buffer_atr = float(self.config.get("stop_buffer_atr", 0.0))

        if max_trades <= 0:
            return []
        if stop_mode not in {"breakout_candle", "recent_structure"}:
            raise ValueError(
                "stop_mode must be 'breakout_candle' or 'recent_structure'"
            )

        signals: list[Signal] = []
        required_opening_minutes = set(range(start_minute, opening_end))
        previous_close = data["close"].shift(1)

        for session_date, session in data.groupby("_session", sort=True):
            opening = session[
                (session["_minute"] >= start_minute)
                & (session["_minute"] < opening_end)
            ]
            if (
                len(opening) != opening_minutes
                or set(opening["_minute"].astype(int)) != required_opening_minutes
            ):
                continue

            range_high = float(opening["high"].max())
            range_low = float(opening["low"].min())
            range_size = range_high - range_low
            opening_atr = float(opening["atr"].iloc[-1])
            if (
                pd.isna(opening_atr)
                or opening_atr <= 0
                or not (
                    minimum_range_atr * opening_atr
                    <= range_size
                    <= maximum_range_atr * opening_atr
                )
            ):
                continue

            candidates = session[
                (session["_minute"] >= opening_end)
                & (session["_minute"] <= candidate_end_minute)
            ]
            session_signal_count = 0
            for index, row in candidates.iterrows():
                local_atr = float(row["atr"])
                if pd.isna(local_atr) or local_atr <= 0:
                    continue
                displacement = abs(float(row["close"]) - float(row["open"]))
                if displacement < minimum_displacement_atr * local_atr:
                    continue

                bullish = bool(
                    previous_close.loc[index] <= range_high
                    and row["close"] > range_high
                    and structure.loc[index, "bullish_fvg"]
                )
                bearish = bool(
                    previous_close.loc[index] >= range_low
                    and row["close"] < range_low
                    and structure.loc[index, "bearish_fvg"]
                )
                if not bullish and not bearish:
                    continue

                side = "long" if bullish else "short"
                if stop_mode == "recent_structure":
                    start = max(int(session.index.min()), int(index) - structure_lookback + 1)
                    recent = data.loc[start:index]
                    stop_base = (
                        float(recent["low"].min())
                        if side == "long"
                        else float(recent["high"].max())
                    )
                else:
                    stop_base = (
                        float(row["low"])
                        if side == "long"
                        else float(row["high"])
                    )
                stop = (
                    stop_base - stop_buffer_atr * local_atr
                    if side == "long"
                    else stop_base + stop_buffer_atr * local_atr
                )
                entry_reference = float(row["close"])
                if (
                    (side == "long" and stop >= entry_reference)
                    or (side == "short" and stop <= entry_reference)
                ):
                    continue
                stop, target = self._levels(
                    entry_reference,
                    stop,
                    side,
                    risk_reward,
                )
                signals.append(
                    Signal(
                        timestamp=row["timestamp"],
                        symbol=symbol,
                        timeframe=timeframe,
                        strategy=self.name,
                        side=side,
                        entry_price=entry_reference,
                        stop_price=stop,
                        take_profit=target,
                        reason=(
                            f"{side} break of completed 5-minute opening range "
                            "with closed-bar displacement and FVG"
                        ),
                        atr=local_atr,
                        metadata={
                            "session": str(session_date),
                            "opening_range_high": range_high,
                            "opening_range_low": range_low,
                            "displacement_atr": displacement / local_atr,
                            "fvg_bottom": float(
                                structure.loc[
                                    index,
                                    (
                                        "bullish_fvg_bottom"
                                        if side == "long"
                                        else "bearish_fvg_bottom"
                                    ),
                                ]
                            ),
                            "fvg_top": float(
                                structure.loc[
                                    index,
                                    (
                                        "bullish_fvg_top"
                                        if side == "long"
                                        else "bearish_fvg_top"
                                    ),
                                ]
                            ),
                            "force_flat_before_session_end": True,
                            "recalculate_risk_from_fill": True,
                            "reward_r": risk_reward,
                            "max_entry_gap_pct": max_entry_gap_pct,
                        },
                    )
                )
                session_signal_count += 1
                if session_signal_count >= max_trades:
                    break
        return signals


__all__ = ["OpeningRangeFVGStrategy"]
