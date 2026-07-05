from __future__ import annotations

import numpy as np
import pandas as pd

from .base import Signal, Strategy


class VWAPPullbackStrategy(Strategy):
    name = "vwap_pullback"

    def generate_signals(
        self,
        frame: pd.DataFrame,
        symbol: str,
        timeframe: str,
    ) -> list[Signal]:
        data = self.prepare(frame)
        tolerance_atr = float(self.config.get("vwap_tolerance_atr", 0.25))
        risk_reward = float(self.config.get("risk_reward", 1.8))
        tolerance = data["atr"] * tolerance_atr
        previous_close = data["close"].shift(1)
        valid = data["atr"].notna() & (data["atr"] > 0) & data["vwap"].notna()
        long_mask = (
            valid
            & (data["ema_9"] > data["ema_20"])
            & (data["close"] > data["vwap"])
            & (data["low"] <= data["vwap"] + tolerance)
            & (data["close"] > data["open"])
            & (data["close"] > previous_close)
        )
        short_mask = (
            valid
            & (data["ema_9"] < data["ema_20"])
            & (data["close"] < data["vwap"])
            & (data["high"] >= data["vwap"] - tolerance)
            & (data["close"] < data["open"])
            & (data["close"] < previous_close)
        )
        signals: list[Signal] = []
        positions = np.flatnonzero((long_mask | short_mask).to_numpy())
        for index in positions:
            row = data.iloc[index]
            row_tolerance = row["atr"] * tolerance_atr
            if long_mask.iloc[index]:
                side = "long"
                stop = min(float(row["low"]), float(row["vwap"] - row_tolerance))
            else:
                side = "short"
                stop = max(float(row["high"]), float(row["vwap"] + row_tolerance))
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
                    reason=f"{side} rejection at session VWAP with aligned EMAs",
                    relative_volume=float(row["relative_volume"]),
                    atr=float(row["atr"]),
                    metadata={"vwap": float(row["vwap"])},
                )
            )
        return signals
