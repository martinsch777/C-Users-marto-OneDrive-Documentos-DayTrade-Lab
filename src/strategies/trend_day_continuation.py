from __future__ import annotations

import numpy as np
import pandas as pd

from .base import Signal, Strategy


class TrendDayContinuationStrategy(Strategy):
    name = "trend_day_continuation"

    def generate_signals(
        self,
        frame: pd.DataFrame,
        symbol: str,
        timeframe: str,
    ) -> list[Signal]:
        data = self.prepare(frame)
        minimum_rvol = float(self.config.get("minimum_relative_volume", 1.0))
        risk_reward = float(self.config.get("risk_reward", 2.0))
        tolerance = data["atr"] * 0.2
        previous_close = data["close"].shift(1)
        previous_ema_20 = data["ema_20"].shift(1)
        valid = (
            data["atr"].notna()
            & (data["atr"] > 0)
            & (data["relative_volume"] >= minimum_rvol)
        )
        long_mask = (
            valid
            & (data["close"] > data["vwap"])
            & (data["ema_9"] > data["ema_20"])
            & (data["low"] <= data["ema_9"] + tolerance)
            & (data["close"] > data["ema_9"])
            & (data["close"] > data["open"])
            & (previous_close >= previous_ema_20)
        )
        short_mask = (
            valid
            & (data["close"] < data["vwap"])
            & (data["ema_9"] < data["ema_20"])
            & (data["high"] >= data["ema_9"] - tolerance)
            & (data["close"] < data["ema_9"])
            & (data["close"] < data["open"])
            & (previous_close <= previous_ema_20)
        )
        signals: list[Signal] = []
        for index in np.flatnonzero((long_mask | short_mask).to_numpy()):
            row = data.iloc[index]
            row_tolerance = row["atr"] * 0.2
            if long_mask.iloc[index]:
                side = "long"
                stop = float(min(row["low"], row["ema_20"]) - row_tolerance)
            else:
                side = "short"
                stop = float(max(row["high"], row["ema_20"]) + row_tolerance)
            entry = float(row["close"])
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
                    reason=f"{side} continuation after orderly EMA pullback",
                    relative_volume=float(row["relative_volume"]),
                    atr=float(row["atr"]),
                    metadata={
                        "vwap": float(row["vwap"]),
                        "ema_9": float(row["ema_9"]),
                        "ema_20": float(row["ema_20"]),
                    },
                )
            )
        return signals
