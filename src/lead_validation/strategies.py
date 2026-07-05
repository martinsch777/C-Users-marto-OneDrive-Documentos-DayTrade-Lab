from __future__ import annotations

import numpy as np
import pandas as pd

from src.edge_discovery.strategies import EdgeEventStrategy
from src.edge_discovery.labels import add_event_labels
from src.indicators import detect_fvg_and_mss


class LeadStrategy(EdgeEventStrategy):
    def prepare(self, frame: pd.DataFrame) -> pd.DataFrame:
        required = {
            "atr",
            "relative_volume_event",
            "VOLATILITY_EXPANSION",
            "VOLATILITY_COMPRESSION",
        }
        if required.issubset(frame.columns):
            return frame
        data = add_event_labels(frame)
        data["atr"] = data["atr_event"]
        return data


class CompressionExpansionLead(LeadStrategy):
    hypothesis_id = "compression_expansion"
    economic_rationale = (
        "Volatility clustering can produce persistent range expansion after a "
        "causally observed compressed regime."
    )

    def __init__(
        self,
        name: str,
        *,
        compression_ratio: float,
        expansion_ratio: float,
        relative_volume_min: float,
        promotion_eligible: bool,
    ) -> None:
        super().__init__({"session_timezone": "UTC"})
        self.name = name
        self.compression_ratio = compression_ratio
        self.expansion_ratio = expansion_ratio
        self.relative_volume_min = relative_volume_min
        self.promotion_eligible = promotion_eligible

    def generate_signals(self, frame, symbol, timeframe):
        data = self.prepare(frame)
        baseline = (
            data["atr"].shift(1).rolling(288, min_periods=96).median()
        )
        ratio = data["atr"] / baseline.replace(0, np.nan)
        compression = ratio <= self.compression_ratio
        expansion = ratio >= self.expansion_ratio
        recent_compression = (
            compression.shift(1)
            .rolling(6, min_periods=6)
            .max()
            .fillna(0)
            .astype(bool)
        )
        prior_high = data["high"].shift(1).rolling(20, min_periods=20).max()
        prior_low = data["low"].shift(1).rolling(20, min_periods=20).min()
        participation = (
            data["relative_volume_event"] >= self.relative_volume_min
        )
        long_mask = (
            recent_compression
            & expansion
            & participation
            & (data["close"] > prior_high)
        )
        short_mask = (
            recent_compression
            & expansion
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
                (
                    "Closed compression, ATR expansion, RVOL confirmation and "
                    "20-bar range break"
                ),
            )
            if signal:
                signal.metadata["promotion_eligible"] = self.promotion_eligible
                signals.append(signal)
        return signals


class FVGMSSLead(LeadStrategy):
    hypothesis_id = "fvg_mss"
    economic_rationale = (
        "A closed three-bar imbalance plus a causal break of prior structure "
        "may identify displacement; the midpoint retest tests continuation."
    )

    def __init__(self, *, rvol_min: float | None) -> None:
        super().__init__({"session_timezone": "UTC"})
        self.rvol_min = rvol_min
        self.name = (
            "fvg_mss_rvol_gt_3"
            if rvol_min == 3.0
            else "fvg_mss_unfiltered"
        )
        self.promotion_eligible = rvol_min == 3.0

    def generate_signals(self, frame, symbol, timeframe):
        data = self.prepare(frame)
        setup = detect_fvg_and_mss(data)
        formations = [
            (int(position), "long")
            for position in np.flatnonzero(setup["bullish_setup"].to_numpy())
        ] + [
            (int(position), "short")
            for position in np.flatnonzero(setup["bearish_setup"].to_numpy())
        ]
        signals = []
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
                if not row["low"] <= midpoint <= row["high"]:
                    continue
                confirmed = (
                    row["close"] > row["open"]
                    if side == "long"
                    else row["close"] < row["open"]
                )
                rvol_valid = (
                    self.rvol_min is None
                    or row["relative_volume_event"] > self.rvol_min
                )
                if confirmed and rvol_valid:
                    stop = (
                        float(setup.iloc[position]["prior_low"])
                        if side == "long"
                        else float(setup.iloc[position]["prior_high"])
                    )
                    signal = self._signal(
                        row,
                        symbol,
                        timeframe,
                        side,
                        stop,
                        2.0,
                        (
                            "Closed 3-bar FVG, causal 20-bar MSS and midpoint "
                            "retest"
                            + (
                                " with entry RVOL > 3"
                                if self.rvol_min is not None
                                else ""
                            )
                        ),
                    )
                    if signal:
                        signal.metadata.update(
                            {
                                "fvg_bottom": bottom,
                                "fvg_top": top,
                                "rvol_min": self.rvol_min,
                                "promotion_eligible": self.promotion_eligible,
                            }
                        )
                        signals.append(signal)
                break
        unique = {(x.timestamp, x.side): x for x in signals}
        return sorted(unique.values(), key=lambda item: item.timestamp)


class RVOLOnlyComparator(LeadStrategy):
    name = hypothesis_id = "rvol_gt_3_breakout_comparator"
    economic_rationale = (
        "Comparator isolating exceptional participation without an FVG."
    )
    promotion_eligible = False

    def generate_signals(self, frame, symbol, timeframe):
        data = self.prepare(frame)
        prior_high = data["high"].shift(1).rolling(20, min_periods=20).max()
        prior_low = data["low"].shift(1).rolling(20, min_periods=20).min()
        participation = data["relative_volume_event"] > 3.0
        long_mask = participation & (data["close"] > prior_high)
        short_mask = participation & (data["close"] < prior_low)
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
                2.0,
                "RVOL > 3 and causal 20-bar breakout without FVG requirement",
            )
            if signal:
                signal.metadata["promotion_eligible"] = False
                signals.append(signal)
        return signals


def build_lead_strategies() -> list[EdgeEventStrategy]:
    return [
        CompressionExpansionLead(
            "compression_expansion_canonical",
            compression_ratio=0.70,
            expansion_ratio=1.50,
            relative_volume_min=2.0,
            promotion_eligible=True,
        ),
        CompressionExpansionLead(
            "compression_expansion_strict",
            compression_ratio=0.60,
            expansion_ratio=1.75,
            relative_volume_min=2.5,
            promotion_eligible=False,
        ),
        CompressionExpansionLead(
            "compression_expansion_frequency_probe",
            compression_ratio=0.80,
            expansion_ratio=1.25,
            relative_volume_min=1.5,
            promotion_eligible=False,
        ),
        FVGMSSLead(rvol_min=3.0),
        FVGMSSLead(rvol_min=None),
        RVOLOnlyComparator(),
    ]
