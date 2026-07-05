from __future__ import annotations

import pandas as pd

from .core import atr


def detect_fvg_and_mss(
    frame: pd.DataFrame,
    *,
    structure_lookback: int = 20,
    minimum_gap_atr: float = 0.2,
) -> pd.DataFrame:
    """Detect closed three-bar FVGs and causal breaks of prior structure."""
    if structure_lookback <= 0:
        raise ValueError("structure_lookback must be positive")
    if minimum_gap_atr < 0:
        raise ValueError("minimum_gap_atr cannot be negative")

    local_atr = frame["atr"] if "atr" in frame.columns else atr(frame, 14)
    prior_high = (
        frame["high"]
        .shift(1)
        .rolling(structure_lookback, min_periods=structure_lookback)
        .max()
    )
    prior_low = (
        frame["low"]
        .shift(1)
        .rolling(structure_lookback, min_periods=structure_lookback)
        .min()
    )
    bullish_gap_size = frame["low"] - frame["high"].shift(2)
    bearish_gap_size = frame["low"].shift(2) - frame["high"]

    result = pd.DataFrame(index=frame.index)
    result["bullish_fvg"] = (bullish_gap_size > 0) & (
        bullish_gap_size >= minimum_gap_atr * local_atr
    )
    result["bearish_fvg"] = (bearish_gap_size > 0) & (
        bearish_gap_size >= minimum_gap_atr * local_atr
    )
    result["bullish_mss"] = frame["close"] > prior_high
    result["bearish_mss"] = frame["close"] < prior_low
    result["bullish_setup"] = result["bullish_fvg"] & result["bullish_mss"]
    result["bearish_setup"] = result["bearish_fvg"] & result["bearish_mss"]
    result["bullish_fvg_bottom"] = frame["high"].shift(2)
    result["bullish_fvg_top"] = frame["low"]
    result["bearish_fvg_bottom"] = frame["high"]
    result["bearish_fvg_top"] = frame["low"].shift(2)
    result["prior_high"] = prior_high
    result["prior_low"] = prior_low
    return result


__all__ = ["detect_fvg_and_mss"]
