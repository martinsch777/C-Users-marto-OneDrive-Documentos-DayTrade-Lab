from __future__ import annotations

import numpy as np
import pandas as pd

from .base import Signal, Strategy


class ExtremeMeanReversionStrategy(Strategy):
    name = "extreme_mean_reversion"

    def generate_signals(
        self,
        frame: pd.DataFrame,
        symbol: str,
        timeframe: str,
    ) -> list[Signal]:
        data = self.prepare(frame)
        rsi_low = float(self.config.get("rsi_low", 25))
        rsi_high = float(self.config.get("rsi_high", 75))
        minimum_extension = float(self.config.get("minimum_extension_atr", 2.0))
        risk_reward = float(self.config.get("risk_reward", 1.5))
        extension = (data["close"] - data["vwap"]) / data["atr"]
        previous_close = data["close"].shift(1)
        previous_low = data["low"].shift(1)
        previous_high = data["high"].shift(1)
        valid = data["atr"].notna() & (data["atr"] > 0) & data["vwap"].notna()
        long_mask = (
            valid
            & (extension <= -minimum_extension)
            & (data["rsi"] <= rsi_low)
            & (data["close"] > data["open"])
            & (data["close"] > previous_close)
            & (data["low"] >= previous_low)
        )
        short_mask = (
            valid
            & (extension >= minimum_extension)
            & (data["rsi"] >= rsi_high)
            & (data["close"] < data["open"])
            & (data["close"] < previous_close)
            & (data["high"] <= previous_high)
        )
        strong_against = (
            long_mask
            & (data["ema_9"] < data["ema_20"])
            & (extension > -3.0)
        ) | (
            short_mask
            & (data["ema_9"] > data["ema_20"])
            & (extension < 3.0)
        )
        candidate_mask = (long_mask | short_mask) & ~strong_against
        signals: list[Signal] = []
        for index in np.flatnonzero(candidate_mask.to_numpy()):
            row = data.iloc[index]
            previous = data.iloc[index - 1]
            row_extension = float(extension.iloc[index])
            if long_mask.iloc[index]:
                side = "long"
                stop = float(min(row["low"], previous["low"]) - row["atr"] * 0.15)
            else:
                side = "short"
                stop = float(max(row["high"], previous["high"]) + row["atr"] * 0.15)
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
                    reason=f"{side} reversal after {row_extension:.2f} ATR VWAP extension",
                    relative_volume=float(row["relative_volume"]),
                    atr=float(row["atr"]),
                    metadata={"extension_atr": row_extension, "rsi": float(row["rsi"])},
                )
            )
        return signals
