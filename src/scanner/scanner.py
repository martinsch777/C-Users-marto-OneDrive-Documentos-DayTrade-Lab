from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd

from src.indicators import add_indicators


@dataclass(frozen=True)
class ScannerCandidate:
    timestamp: pd.Timestamp
    symbol: str
    percent_move: float
    relative_volume: float
    distance_to_vwap_pct: float
    atr_pct: float
    spread_bps: float
    breakout: str
    volatility_compression: bool
    intraday_trend: str
    score: float
    reasons: str

    def to_record(self) -> dict:
        record = asdict(self)
        record["timestamp"] = self.timestamp.isoformat()
        return record


class IntradayScanner:
    """Ranks research candidates. It never creates or sends orders."""

    def __init__(
        self,
        *,
        max_spread_bps: float = 8.0,
        min_relative_volume: float = 1.0,
    ) -> None:
        self.max_spread_bps = max_spread_bps
        self.min_relative_volume = min_relative_volume

    def scan(
        self,
        frames: dict[str, pd.DataFrame],
        *,
        spread_by_symbol: dict[str, float] | None = None,
    ) -> pd.DataFrame:
        spread_by_symbol = spread_by_symbol or {}
        candidates: list[ScannerCandidate] = []
        for symbol, raw in frames.items():
            if raw.empty:
                continue
            data = add_indicators(raw)
            row = data.iloc[-1]
            spread = float(spread_by_symbol.get(symbol, 0.0))
            if spread > self.max_spread_bps:
                continue
            local_day = row["timestamp"].tz_convert("America/New_York").date()
            timestamps = data["timestamp"].dt.tz_convert("America/New_York")
            session = data[timestamps.dt.date == local_day]
            if session.empty or pd.isna(row["atr"]) or pd.isna(row["vwap"]):
                continue
            session_open = float(session.iloc[0]["open"])
            percent_move = (float(row["close"]) / session_open - 1) * 100
            prior_high = data["high"].shift(1).rolling(20, min_periods=10).max().iloc[-1]
            prior_low = data["low"].shift(1).rolling(20, min_periods=10).min().iloc[-1]
            breakout = "none"
            if pd.notna(prior_high) and row["close"] > prior_high:
                breakout = "high"
            elif pd.notna(prior_low) and row["close"] < prior_low:
                breakout = "low"
            atr_baseline = data["atr"].shift(1).rolling(20, min_periods=10).mean().iloc[-1]
            compression = pd.notna(atr_baseline) and row["atr"] < atr_baseline * 0.75
            trend = "sideways"
            if row["close"] > row["vwap"] and row["ema_9"] > row["ema_20"]:
                trend = "up"
            elif row["close"] < row["vwap"] and row["ema_9"] < row["ema_20"]:
                trend = "down"
            distance = (float(row["close"]) / float(row["vwap"]) - 1) * 100
            atr_pct = float(row["atr"] / row["close"] * 100)
            rvol = float(row["relative_volume"])
            reasons: list[str] = []
            score = 0.0
            if rvol >= self.min_relative_volume:
                score += min(rvol, 3.0)
                reasons.append("high_relative_volume")
            if abs(percent_move) >= 1:
                score += min(abs(percent_move), 5.0) / 2
                reasons.append("large_intraday_move")
            if breakout != "none":
                score += 2
                reasons.append(f"{breakout}_breakout")
            if abs(distance) <= 0.25:
                score += 1
                reasons.append("near_vwap")
            if compression:
                score += 1
                reasons.append("volatility_compression")
            if trend != "sideways":
                score += 1
                reasons.append(f"{trend}_trend")
            if not reasons:
                continue
            candidates.append(
                ScannerCandidate(
                    timestamp=row["timestamp"],
                    symbol=symbol,
                    percent_move=percent_move,
                    relative_volume=rvol,
                    distance_to_vwap_pct=distance,
                    atr_pct=atr_pct,
                    spread_bps=spread,
                    breakout=breakout,
                    volatility_compression=bool(compression),
                    intraday_trend=trend,
                    score=score,
                    reasons=";".join(reasons),
                )
            )
        if not candidates:
            return pd.DataFrame(columns=list(ScannerCandidate.__dataclass_fields__))
        return pd.DataFrame(
            [candidate.to_record() for candidate in candidates]
        ).sort_values("score", ascending=False)
