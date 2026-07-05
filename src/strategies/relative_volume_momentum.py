from __future__ import annotations

import numpy as np
import pandas as pd

from .base import Signal, Strategy


class RelativeVolumeMomentumStrategy(Strategy):
    name = "relative_volume_momentum"

    def generate_signals(
        self,
        frame: pd.DataFrame,
        symbol: str,
        timeframe: str,
    ) -> list[Signal]:
        data = self.prepare(frame)
        lookback = int(self.config.get("lookback", 20))
        minimum_rvol = float(self.config.get("minimum_relative_volume", 1.5))
        maximum_extension = float(self.config.get("maximum_extension_atr", 2.0))
        risk_reward = float(self.config.get("risk_reward", 1.8))
        prior_high = data["high"].shift(1).rolling(lookback, min_periods=lookback).max()
        prior_low = data["low"].shift(1).rolling(lookback, min_periods=lookback).min()
        extension = (data["close"] - data["ema_9"]).abs() / data["atr"]
        valid = (
            data["atr"].notna()
            & (data["atr"] > 0)
            & (data["relative_volume"] >= minimum_rvol)
            & (extension <= maximum_extension)
        )
        long_mask = valid & (data["close"] > prior_high) & (
            data["close"] > data["open"]
        )
        short_mask = valid & (data["close"] < prior_low) & (
            data["close"] < data["open"]
        )
        signals: list[Signal] = []
        positions = np.flatnonzero((long_mask | short_mask).to_numpy())
        for index in positions:
            row = data.iloc[index]
            row_extension = float(extension.iloc[index])
            if long_mask.iloc[index]:
                side = "long"
                stop = max(float(prior_high.iloc[index]), float(row["close"] - row["atr"]))
            else:
                side = "short"
                stop = min(float(prior_low.iloc[index]), float(row["close"] + row["atr"]))
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
                    reason=f"{side} {lookback}-bar breakout with high relative volume",
                    relative_volume=float(row["relative_volume"]),
                    atr=float(row["atr"]),
                    fomo_flag=row_extension > maximum_extension * 0.85,
                    metadata={"extension_atr": row_extension},
                )
            )
        return signals
