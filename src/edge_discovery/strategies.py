from __future__ import annotations

import numpy as np
import pandas as pd

from src.indicators import add_indicators
from src.strategies import Signal, Strategy

from .labels import add_event_labels


class EdgeEventStrategy(Strategy):
    hypothesis_id: str
    economic_rationale: str

    def prepare(self, frame: pd.DataFrame) -> pd.DataFrame:
        required = {
            "atr",
            "vwap",
            "relative_volume",
            "EXTREME_UP_MOVE",
            "EXTREME_DOWN_MOVE",
        }
        if required.issubset(frame.columns):
            # Strategies treat prepared data as read-only. Returning the same
            # frame avoids a >100 MB deep copy for each 1m lead validation.
            return frame
        data = add_indicators(frame, timezone="UTC")
        return add_event_labels(data)

    def _signal(
        self,
        row: pd.Series,
        symbol: str,
        timeframe: str,
        side: str,
        stop: float,
        risk_reward: float,
        reason: str,
    ) -> Signal | None:
        entry = float(row["close"])
        if side == "long" and not 0 < stop < entry:
            return None
        if side == "short" and not stop > entry:
            return None
        stop, target = self._levels(entry, stop, side, risk_reward)
        return Signal(
            timestamp=row["timestamp"],
            symbol=symbol,
            timeframe=timeframe,
            strategy=self.name,
            side=side,
            entry_price=entry,
            stop_price=stop,
            take_profit=target,
            reason=reason,
            relative_volume=float(row.get("relative_volume_event", 0.0)),
            atr=float(row.get("atr", 0.0)),
            metadata={
                "hypothesis_id": self.hypothesis_id,
                "economic_rationale": self.economic_rationale,
                "rare_event": True,
            },
        )


class PostExtremeReversal(EdgeEventStrategy):
    hypothesis_id = "crypto_post_extreme_reversal"
    economic_rationale = (
        "Forced deleveraging can temporarily exhaust one-sided liquidity; "
        "a closed-bar recovery tests whether price mean-reverts after the shock."
    )

    def __init__(self, risk_reward: float) -> None:
        super().__init__({"session_timezone": "UTC"})
        self.risk_reward = risk_reward
        self.name = f"post_extreme_reversal_r{str(risk_reward).replace('.', '_')}"

    def generate_signals(self, frame, symbol, timeframe):
        data = self.prepare(frame)
        prior_down = (
            data["EXTREME_DOWN_MOVE"].shift(1).fillna(False)
            & data["HIGH_RELATIVE_VOLUME"].shift(1).fillna(False)
            & (data["lower_wick_ratio"].shift(1) >= 0.25)
        )
        prior_up = (
            data["EXTREME_UP_MOVE"].shift(1).fillna(False)
            & data["HIGH_RELATIVE_VOLUME"].shift(1).fillna(False)
            & (data["upper_wick_ratio"].shift(1) >= 0.25)
        )
        long_mask = (
            prior_down
            & (data["close"] > data["open"])
            & (data["close"] > data["close"].shift(1))
            & ~data["VOLATILITY_EXPANSION"].astype(bool)
        )
        short_mask = (
            prior_up
            & (data["close"] < data["open"])
            & (data["close"] < data["close"].shift(1))
            & ~data["VOLATILITY_EXPANSION"].astype(bool)
        )
        signals = []
        for position in np.flatnonzero((long_mask | short_mask).to_numpy()):
            row = data.iloc[position]
            previous = data.iloc[position - 1]
            side = "long" if long_mask.iloc[position] else "short"
            stop = (
                min(float(row["low"]), float(previous["low"]))
                - 0.1 * float(row["atr"])
                if side == "long"
                else max(float(row["high"]), float(previous["high"]))
                + 0.1 * float(row["atr"])
            )
            signal = self._signal(
                row,
                symbol,
                timeframe,
                side,
                stop,
                self.risk_reward,
                "Extreme 3-bar move, >3x volume, large wick and next-bar recovery",
            )
            if signal:
                signals.append(signal)
        return signals


class ExtremeMoveContinuation(EdgeEventStrategy):
    name = hypothesis_id = "crypto_extreme_move_continuation"
    economic_rationale = (
        "A range break with exceptional participation and a close near the "
        "extreme may indicate information-driven flow that persists briefly."
    )

    def generate_signals(self, frame, symbol, timeframe):
        data = self.prepare(frame)
        prior_up = (
            data["EXTREME_UP_MOVE"].shift(1).fillna(False)
            & data["HIGH_RELATIVE_VOLUME"].shift(1).fillna(False)
            & (data["close_location"].shift(1) >= 0.80)
        )
        prior_down = (
            data["EXTREME_DOWN_MOVE"].shift(1).fillna(False)
            & data["HIGH_RELATIVE_VOLUME"].shift(1).fillna(False)
            & (data["close_location"].shift(1) <= 0.20)
        )
        long_mask = (
            prior_up
            & (data["close"] > data["high"].shift(1))
            & (data["move_3bar_atr"] <= 3.5)
        )
        short_mask = (
            prior_down
            & (data["close"] < data["low"].shift(1))
            & (data["move_3bar_atr"] <= 3.5)
        )
        signals = []
        for position in np.flatnonzero((long_mask | short_mask).to_numpy()):
            row = data.iloc[position]
            side = "long" if long_mask.iloc[position] else "short"
            stop = (
                float(row["close"] - row["atr"])
                if side == "long"
                else float(row["close"] + row["atr"])
            )
            signal = self._signal(
                row,
                symbol,
                timeframe,
                side,
                stop,
                1.5,
                "Extreme high-volume close followed by next-bar range continuation",
            )
            if signal:
                signals.append(signal)
        return signals


class LargeWickReversal(EdgeEventStrategy):
    name = hypothesis_id = "large_wick_volume_reversal"
    economic_rationale = (
        "A large rejection wick with exceptional volume can reveal exhausted "
        "aggressive flow when the next closed bar confirms the rejection."
    )

    def generate_signals(self, frame, symbol, timeframe):
        data = self.prepare(frame)
        prior_volume = data["HIGH_RELATIVE_VOLUME"].shift(1).fillna(False)
        lower = (
            prior_volume
            & (data["lower_wick_ratio"].shift(1) >= 0.50)
            & (data["close"] > data["high"].shift(1))
        )
        upper = (
            prior_volume
            & (data["upper_wick_ratio"].shift(1) >= 0.50)
            & (data["close"] < data["low"].shift(1))
        )
        signals = []
        for position in np.flatnonzero((lower | upper).to_numpy()):
            row = data.iloc[position]
            previous = data.iloc[position - 1]
            side = "long" if lower.iloc[position] else "short"
            stop = (
                float(previous["low"] - 0.1 * row["atr"])
                if side == "long"
                else float(previous["high"] + 0.1 * row["atr"])
            )
            signal = self._signal(
                row,
                symbol,
                timeframe,
                side,
                stop,
                1.5,
                "High-volume rejection wick and next-bar break confirmation",
            )
            if signal:
                signals.append(signal)
        return signals


class CompressionExpansionBreakout(EdgeEventStrategy):
    name = hypothesis_id = "compression_expansion_breakout"
    economic_rationale = (
        "Volatility clustering suggests a compressed regime can transition "
        "into persistent expansion when price breaks a pre-existing range."
    )

    def generate_signals(self, frame, symbol, timeframe):
        data = self.prepare(frame)
        prior_high = data["high"].shift(1).rolling(20, min_periods=20).max()
        prior_low = data["low"].shift(1).rolling(20, min_periods=20).min()
        recent_compression = (
            data["VOLATILITY_COMPRESSION"]
            .shift(1)
            .rolling(6, min_periods=6)
            .max()
            .fillna(0)
            .astype(bool)
        )
        participation = data["relative_volume_event"] >= 2.0
        long_mask = (
            recent_compression
            & data["VOLATILITY_EXPANSION"]
            & participation
            & (data["close"] > prior_high)
        )
        short_mask = (
            recent_compression
            & data["VOLATILITY_EXPANSION"]
            & participation
            & (data["close"] < prior_low)
        )
        signals = []
        for position in np.flatnonzero((long_mask | short_mask).to_numpy()):
            row = data.iloc[position]
            side = "long" if long_mask.iloc[position] else "short"
            stop = (
                max(float(prior_low.iloc[position]), float(row["close"] - row["atr"]))
                if side == "long"
                else min(
                    float(prior_high.iloc[position]),
                    float(row["close"] + row["atr"]),
                )
            )
            signal = self._signal(
                row,
                symbol,
                timeframe,
                side,
                stop,
                2.0,
                "Causal compression followed by high-volume range expansion",
            )
            if signal:
                signals.append(signal)
        return signals


def build_edge_strategies() -> list[EdgeEventStrategy]:
    return [
        PostExtremeReversal(1.0),
        PostExtremeReversal(1.5),
        ExtremeMoveContinuation(),
        LargeWickReversal(),
        CompressionExpansionBreakout(),
    ]
