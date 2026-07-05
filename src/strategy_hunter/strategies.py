from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from src.indicators import add_indicators, atr, ema
from src.strategies import Signal, Strategy


HUNTER_INDICATORS = {
    "atr",
    "rsi",
    "vwap",
    "relative_volume",
    "ema_9",
    "ema_21",
    "ema_50",
    "ema_200",
    "macd",
    "macd_signal",
    "bb_basis",
    "bb_upper",
    "bb_lower",
    "adx",
    "supertrend",
    "supertrend_direction",
    "ha_open",
    "ha_close",
}


def _adx(frame: pd.DataFrame, period: int = 14) -> pd.Series:
    up = frame["high"].diff()
    down = -frame["low"].diff()
    plus_dm = up.where((up > down) & (up > 0), 0.0)
    minus_dm = down.where((down > up) & (down > 0), 0.0)
    local_atr = atr(frame, period)
    plus_di = (
        100
        * plus_dm.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
        / local_atr.replace(0, np.nan)
    )
    minus_di = (
        100
        * minus_dm.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
        / local_atr.replace(0, np.nan)
    )
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def _supertrend(
    frame: pd.DataFrame,
    period: int = 10,
    multiplier: float = 3.0,
) -> tuple[pd.Series, pd.Series]:
    local_atr = atr(frame, period)
    midpoint = (frame["high"] + frame["low"]) / 2
    upper = (midpoint + multiplier * local_atr).to_numpy(dtype=float)
    lower = (midpoint - multiplier * local_atr).to_numpy(dtype=float)
    close = frame["close"].to_numpy(dtype=float)
    final_upper = upper.copy()
    final_lower = lower.copy()
    direction = np.ones(len(frame), dtype=int)
    line = np.full(len(frame), np.nan)
    for index in range(1, len(frame)):
        if np.isnan(upper[index]):
            direction[index] = direction[index - 1]
            continue
        if np.isnan(final_upper[index - 1]):
            final_upper[index] = upper[index]
            final_lower[index] = lower[index]
            direction[index] = 1 if close[index] >= midpoint.iloc[index] else -1
            line[index] = (
                final_lower[index] if direction[index] > 0 else final_upper[index]
            )
            continue
        if upper[index] < final_upper[index - 1] or close[index - 1] > final_upper[index - 1]:
            final_upper[index] = upper[index]
        else:
            final_upper[index] = final_upper[index - 1]
        if lower[index] > final_lower[index - 1] or close[index - 1] < final_lower[index - 1]:
            final_lower[index] = lower[index]
        else:
            final_lower[index] = final_lower[index - 1]
        if direction[index - 1] < 0 and close[index] > final_upper[index]:
            direction[index] = 1
        elif direction[index - 1] > 0 and close[index] < final_lower[index]:
            direction[index] = -1
        else:
            direction[index] = direction[index - 1]
        line[index] = (
            final_lower[index] if direction[index] > 0 else final_upper[index]
        )
    return (
        pd.Series(line, index=frame.index),
        pd.Series(direction, index=frame.index),
    )


def _heikin_ashi(frame: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    ha_close = frame[["open", "high", "low", "close"]].mean(axis=1).to_numpy()
    ha_open = np.empty(len(frame), dtype=float)
    if len(frame):
        ha_open[0] = (float(frame.iloc[0]["open"]) + float(frame.iloc[0]["close"])) / 2
    for index in range(1, len(frame)):
        ha_open[index] = (ha_open[index - 1] + ha_close[index - 1]) / 2
    return (
        pd.Series(ha_open, index=frame.index),
        pd.Series(ha_close, index=frame.index),
    )


def add_hunter_indicators(
    frame: pd.DataFrame,
    *,
    timezone: str = "UTC",
) -> pd.DataFrame:
    data = add_indicators(frame, timezone=timezone)
    data["ema_21"] = ema(data["close"], 21)
    data["ema_50"] = ema(data["close"], 50)
    data["ema_200"] = ema(data["close"], 200)
    ema_12 = ema(data["close"], 12)
    ema_26 = ema(data["close"], 26)
    data["macd"] = ema_12 - ema_26
    data["macd_signal"] = ema(data["macd"], 9)
    data["bb_basis"] = data["close"].rolling(20, min_periods=20).mean()
    bb_std = data["close"].rolling(20, min_periods=20).std(ddof=0)
    data["bb_upper"] = data["bb_basis"] + 2 * bb_std
    data["bb_lower"] = data["bb_basis"] - 2 * bb_std
    data["adx"] = _adx(data)
    data["supertrend"], data["supertrend_direction"] = _supertrend(data)
    data["ha_open"], data["ha_close"] = _heikin_ashi(data)
    return data


class HunterStrategy(Strategy):
    family_id: str

    def prepare(self, frame: pd.DataFrame) -> pd.DataFrame:
        if HUNTER_INDICATORS.issubset(frame.columns):
            return frame.copy()
        return add_hunter_indicators(
            frame,
            timezone=str(self.config.get("session_timezone", "UTC")),
        )

    def _make_signal(
        self,
        row: pd.Series,
        symbol: str,
        timeframe: str,
        side: str,
        stop: float,
        risk_reward: float,
        reason: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> Signal | None:
        entry = float(row["close"])
        if side == "long" and not 0 < stop < entry:
            return None
        if side == "short" and not stop > entry:
            return None
        stop, target = self._levels(entry, float(stop), side, risk_reward)
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
            relative_volume=float(row.get("relative_volume", 1.0)),
            atr=float(row.get("atr", 0.0)),
            metadata={"family_id": self.family_id, **(metadata or {})},
        )


class EMA921VWAPScalping(HunterStrategy):
    family_id = "ema_9_21_vwap_scalping"

    def __init__(self, risk_reward: float = 1.5) -> None:
        super().__init__({"session_timezone": "UTC"})
        self.risk_reward = risk_reward
        self.name = f"{self.family_id}_r{str(risk_reward).replace('.', '_')}"

    def generate_signals(self, frame, symbol, timeframe):
        data = self.prepare(frame)
        long_mask = (
            (data["ema_9"].shift(1) <= data["ema_21"].shift(1))
            & (data["ema_9"] > data["ema_21"])
            & (data["close"] > data["vwap"])
            & (data["close"] > data["ema_200"])
            & (data["relative_volume"] >= 1.2)
            & data["rsi"].between(50, 70)
        )
        short_mask = (
            (data["ema_9"].shift(1) >= data["ema_21"].shift(1))
            & (data["ema_9"] < data["ema_21"])
            & (data["close"] < data["vwap"])
            & (data["close"] < data["ema_200"])
            & (data["relative_volume"] >= 1.2)
            & data["rsi"].between(30, 50)
        )
        swing_low = data["low"].rolling(5, min_periods=5).min()
        swing_high = data["high"].rolling(5, min_periods=5).max()
        signals = []
        for position in np.flatnonzero((long_mask | short_mask).to_numpy()):
            row = data.iloc[position]
            side = "long" if long_mask.iloc[position] else "short"
            stop = swing_low.iloc[position] if side == "long" else swing_high.iloc[position]
            signal = self._make_signal(
                row,
                symbol,
                timeframe,
                side,
                stop,
                self.risk_reward,
                f"EMA9/21 cross aligned with VWAP, EMA200, RVOL and RSI ({self.risk_reward}R)",
            )
            if signal:
                signals.append(signal)
        return signals


class SupertrendEMA200(HunterStrategy):
    family_id = name = "supertrend_ema200"

    def generate_signals(self, frame, symbol, timeframe):
        data = self.prepare(frame)
        flip_up = (data["supertrend_direction"].shift(1) < 0) & (
            data["supertrend_direction"] > 0
        )
        flip_down = (data["supertrend_direction"].shift(1) > 0) & (
            data["supertrend_direction"] < 0
        )
        long_mask = flip_up & (data["close"] > data["ema_200"]) & (
            data["relative_volume"] >= 1.0
        )
        short_mask = flip_down & (data["close"] < data["ema_200"]) & (
            data["relative_volume"] >= 1.0
        )
        signals = []
        for position in np.flatnonzero((long_mask | short_mask).to_numpy()):
            row = data.iloc[position]
            side = "long" if long_mask.iloc[position] else "short"
            stop = (
                max(float(row["supertrend"]), float(row["close"] - row["atr"]))
                if side == "long"
                else min(float(row["supertrend"]), float(row["close"] + row["atr"]))
            )
            signal = self._make_signal(
                row, symbol, timeframe, side, stop, 2.0, "Supertrend flip aligned with EMA200"
            )
            if signal:
                signals.append(signal)
        return signals


class MACDRSIScalping(HunterStrategy):
    family_id = name = "macd_rsi_scalping"

    def generate_signals(self, frame, symbol, timeframe):
        data = self.prepare(frame)
        cross_up = (data["macd"].shift(1) <= data["macd_signal"].shift(1)) & (
            data["macd"] > data["macd_signal"]
        )
        cross_down = (data["macd"].shift(1) >= data["macd_signal"].shift(1)) & (
            data["macd"] < data["macd_signal"]
        )
        long_mask = cross_up & (data["rsi"] > 50) & (data["close"] > data["vwap"]) & (
            data["adx"] >= 20
        )
        short_mask = cross_down & (data["rsi"] < 50) & (data["close"] < data["vwap"]) & (
            data["adx"] >= 20
        )
        return self._atr_signals(data, long_mask, short_mask, symbol, timeframe, 1.5)

    def _atr_signals(self, data, long_mask, short_mask, symbol, timeframe, rr):
        signals = []
        for position in np.flatnonzero((long_mask | short_mask).to_numpy()):
            row = data.iloc[position]
            side = "long" if long_mask.iloc[position] else "short"
            stop = row["close"] - row["atr"] if side == "long" else row["close"] + row["atr"]
            signal = self._make_signal(
                row, symbol, timeframe, side, stop, rr, "MACD cross with RSI, VWAP and ADX confirmation"
            )
            if signal:
                signals.append(signal)
        return signals


class BollingerRSIReversion(HunterStrategy):
    family_id = name = "bollinger_rsi_reversion"

    def generate_signals(self, frame, symbol, timeframe):
        data = self.prepare(frame)
        long_mask = (
            (data["close"].shift(1) < data["bb_lower"].shift(1))
            & (data["rsi"].shift(1) < 30)
            & (data["close"] > data["open"])
            & (data["close"] > data["close"].shift(1))
            & (data["adx"] < 25)
        )
        short_mask = (
            (data["close"].shift(1) > data["bb_upper"].shift(1))
            & (data["rsi"].shift(1) > 70)
            & (data["close"] < data["open"])
            & (data["close"] < data["close"].shift(1))
            & (data["adx"] < 25)
        )
        signals = []
        for position in np.flatnonzero((long_mask | short_mask).to_numpy()):
            row = data.iloc[position]
            previous = data.iloc[position - 1]
            side = "long" if long_mask.iloc[position] else "short"
            stop = (
                min(row["low"], previous["low"]) - 0.25 * row["atr"]
                if side == "long"
                else max(row["high"], previous["high"]) + 0.25 * row["atr"]
            )
            signal = self._make_signal(
                row, symbol, timeframe, side, stop, 1.5, "Bollinger excursion and RSI extreme with next-bar reversal"
            )
            if signal:
                signals.append(signal)
        return signals


class HeikinAshiEMATrend(HunterStrategy):
    family_id = name = "heikin_ashi_ema_trend"

    def generate_signals(self, frame, symbol, timeframe):
        data = self.prepare(frame)
        bullish = data["ha_close"] > data["ha_open"]
        bearish = data["ha_close"] < data["ha_open"]
        long_mask = (
            ~bullish.shift(1, fill_value=False)
            & bullish
            & (data["ema_50"] > data["ema_200"])
            & (data["close"] > data["vwap"])
        )
        short_mask = (
            ~bearish.shift(1, fill_value=False)
            & bearish
            & (data["ema_50"] < data["ema_200"])
            & (data["close"] < data["vwap"])
        )
        swing_low = data["low"].rolling(5, min_periods=5).min()
        swing_high = data["high"].rolling(5, min_periods=5).max()
        signals = []
        for position in np.flatnonzero((long_mask | short_mask).to_numpy()):
            row = data.iloc[position]
            side = "long" if long_mask.iloc[position] else "short"
            stop = swing_low.iloc[position] if side == "long" else swing_high.iloc[position]
            signal = self._make_signal(
                row, symbol, timeframe, side, stop, 2.0, "Heikin Ashi color change with EMA trend and VWAP"
            )
            if signal:
                signals.append(signal)
        return signals


class DonchianIntradayBreakout(HunterStrategy):
    family_id = "donchian_intraday_breakout"

    def __init__(self, risk_reward: float = 2.0) -> None:
        super().__init__({"session_timezone": "UTC"})
        self.risk_reward = risk_reward
        self.name = f"{self.family_id}_r{str(risk_reward).replace('.', '_')}"

    def generate_signals(self, frame, symbol, timeframe):
        data = self.prepare(frame)
        upper = data["high"].shift(1).rolling(20, min_periods=20).max()
        lower = data["low"].shift(1).rolling(20, min_periods=20).min()
        width_ok = (upper - lower) <= 4 * data["atr"]
        long_mask = (
            (data["close"] > upper)
            & (data["close"] > data["ema_200"])
            & (data["relative_volume"] >= 1.2)
            & width_ok
        )
        short_mask = (
            (data["close"] < lower)
            & (data["close"] < data["ema_200"])
            & (data["relative_volume"] >= 1.2)
            & width_ok
        )
        signals = []
        midpoint = (upper + lower) / 2
        for position in np.flatnonzero((long_mask | short_mask).to_numpy()):
            row = data.iloc[position]
            side = "long" if long_mask.iloc[position] else "short"
            stop = (
                max(midpoint.iloc[position], row["close"] - row["atr"])
                if side == "long"
                else min(midpoint.iloc[position], row["close"] + row["atr"])
            )
            signal = self._make_signal(
                row, symbol, timeframe, side, stop, self.risk_reward, "Causal Donchian breakout with EMA200 and RVOL"
            )
            if signal:
                signals.append(signal)
        return signals


class LiquiditySweepReversal(HunterStrategy):
    family_id = name = "liquidity_sweep_reversal"

    def generate_signals(self, frame, symbol, timeframe):
        data = self.prepare(frame)
        prior_low = data["low"].shift(2).rolling(20, min_periods=20).min()
        prior_high = data["high"].shift(2).rolling(20, min_periods=20).max()
        prev_sweep_long = (
            (data["low"].shift(1) < prior_low)
            & (data["close"].shift(1) > prior_low)
            & ((prior_low - data["low"].shift(1)) <= 3 * data["atr"].shift(1))
        )
        prev_sweep_short = (
            (data["high"].shift(1) > prior_high)
            & (data["close"].shift(1) < prior_high)
            & ((data["high"].shift(1) - prior_high) <= 3 * data["atr"].shift(1))
        )
        long_mask = prev_sweep_long & (data["close"] > data["open"]) & (
            data["close"] > data["close"].shift(1)
        )
        short_mask = prev_sweep_short & (data["close"] < data["open"]) & (
            data["close"] < data["close"].shift(1)
        )
        signals = []
        for position in np.flatnonzero((long_mask | short_mask).to_numpy()):
            row = data.iloc[position]
            previous = data.iloc[position - 1]
            side = "long" if long_mask.iloc[position] else "short"
            stop = (
                previous["low"] - 0.1 * row["atr"]
                if side == "long"
                else previous["high"] + 0.1 * row["atr"]
            )
            signal = self._make_signal(
                row, symbol, timeframe, side, stop, 1.5, "Rolling-extreme liquidity sweep with closed-bar reversal"
            )
            if signal:
                signals.append(signal)
        return signals


class FVGMarketStructureShift(HunterStrategy):
    family_id = name = "fvg_market_structure_shift"

    def generate_signals(self, frame, symbol, timeframe):
        data = self.prepare(frame)
        prior_high = data["high"].shift(1).rolling(20, min_periods=20).max()
        prior_low = data["low"].shift(1).rolling(20, min_periods=20).min()
        bullish_gap = (data["low"] > data["high"].shift(2)) & (
            data["low"] - data["high"].shift(2) >= 0.2 * data["atr"]
        )
        bearish_gap = (data["high"] < data["low"].shift(2)) & (
            data["low"].shift(2) - data["high"] >= 0.2 * data["atr"]
        )
        bullish_formation = bullish_gap & (data["close"] > prior_high)
        bearish_formation = bearish_gap & (data["close"] < prior_low)
        signals = []
        formations = [
            (int(position), "long")
            for position in np.flatnonzero(bullish_formation.to_numpy())
        ] + [
            (int(position), "short")
            for position in np.flatnonzero(bearish_formation.to_numpy())
        ]
        for formation, side in sorted(formations):
            if side == "long":
                bottom = float(data.iloc[formation - 2]["high"])
                top = float(data.iloc[formation]["low"])
            else:
                bottom = float(data.iloc[formation]["high"])
                top = float(data.iloc[formation - 2]["low"])
            midpoint = (bottom + top) / 2
            end = min(len(data), formation + 11)
            for position in range(formation + 1, end):
                row = data.iloc[position]
                touched = row["low"] <= midpoint <= row["high"]
                confirmed = (
                    row["close"] > row["open"]
                    if side == "long"
                    else row["close"] < row["open"]
                )
                if not touched:
                    continue
                if confirmed:
                    stop = (
                        float(prior_low.iloc[position])
                        if side == "long"
                        else float(prior_high.iloc[position])
                    )
                    signal = self._make_signal(
                        row,
                        symbol,
                        timeframe,
                        side,
                        stop,
                        2.0,
                        "Closed 3-bar FVG, causal structure break, and midpoint retest",
                        metadata={"fvg_bottom": bottom, "fvg_top": top},
                    )
                    if signal:
                        signals.append(signal)
                break
        # Multiple zones can trigger the same bar; keep one signal per side/time.
        unique = {}
        for signal in signals:
            unique[(signal.timestamp, signal.side)] = signal
        return sorted(unique.values(), key=lambda item: item.timestamp)


class VWAPDeviationReversion(HunterStrategy):
    family_id = name = "vwap_deviation_reversion"

    def generate_signals(self, frame, symbol, timeframe):
        data = self.prepare(frame)
        extension = (data["close"] - data["vwap"]) / data["atr"]
        long_mask = (
            (extension.shift(1) <= -2)
            & (data["rsi"].shift(1) < 25)
            & (data["close"] > data["open"])
            & (data["close"] > data["close"].shift(1))
        )
        short_mask = (
            (extension.shift(1) >= 2)
            & (data["rsi"].shift(1) > 75)
            & (data["close"] < data["open"])
            & (data["close"] < data["close"].shift(1))
        )
        signals = []
        for position in np.flatnonzero((long_mask | short_mask).to_numpy()):
            row = data.iloc[position]
            previous = data.iloc[position - 1]
            side = "long" if long_mask.iloc[position] else "short"
            stop = (
                min(row["low"], previous["low"]) - 0.25 * row["atr"]
                if side == "long"
                else max(row["high"], previous["high"]) + 0.25 * row["atr"]
            )
            signal = self._make_signal(
                row, symbol, timeframe, side, stop, 1.5, "Two-ATR VWAP deviation with RSI and closed-bar reversal"
            )
            if signal:
                signals.append(signal)
        return signals


def build_hunter_strategies(
    *,
    include_predefined_variants: bool = False,
) -> list[HunterStrategy]:
    strategies: list[HunterStrategy] = [
        EMA921VWAPScalping(1.5),
        SupertrendEMA200(),
        MACDRSIScalping(),
        BollingerRSIReversion(),
        HeikinAshiEMATrend(),
        DonchianIntradayBreakout(2.0),
        LiquiditySweepReversal(),
        FVGMarketStructureShift(),
        VWAPDeviationReversion(),
    ]
    if include_predefined_variants:
        strategies.extend(
            [
                EMA921VWAPScalping(1.0),
                EMA921VWAPScalping(2.0),
                DonchianIntradayBreakout(1.5),
            ]
        )
    return strategies
