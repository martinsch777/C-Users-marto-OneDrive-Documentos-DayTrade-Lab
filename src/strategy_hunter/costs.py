from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pandas as pd


def _load(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        try:
            import yaml  # type: ignore
        except ImportError as exc:
            raise ValueError("Platform costs must be JSON-compatible YAML") from exc
        payload = yaml.safe_load(text)
        if not isinstance(payload, dict):
            raise ValueError("Platform cost root must be an object")
        return payload


@dataclass(frozen=True)
class PlatformCostProfile:
    id: str
    platform: str
    product: str
    maker_fee_bps: float
    taker_fee_bps: float
    spread_bps: float
    slippage_bps_per_side: float
    funding_bps_per_8h: float = 0.0
    borrow_bps_per_day: float = 0.0
    regulatory_bps_round_trip: float = 0.0
    data_cost_monthly_usd: float = 0.0
    withdrawal_or_funding_cost: str = ""
    liquidity: str = ""
    api_available: bool = False
    data_quality: str = ""
    operational_risk: str = ""
    source_url: str = ""
    notes: str = ""

    def round_trip_bps(
        self,
        *,
        order_style: str = "taker",
        holding_hours: float = 0.0,
        include_funding: bool = True,
    ) -> float:
        if order_style not in {"maker", "taker"}:
            raise ValueError("order_style must be maker or taker")
        fee = self.maker_fee_bps if order_style == "maker" else self.taker_fee_bps
        funding = (
            abs(self.funding_bps_per_8h) * holding_hours / 8
            if include_funding
            else 0.0
        )
        borrow = abs(self.borrow_bps_per_day) * holding_hours / 24
        return (
            2 * fee
            + self.spread_bps
            + 2 * self.slippage_bps_per_side
            + self.regulatory_bps_round_trip
            + funding
            + borrow
        )

    def to_record(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class PlatformCostCatalog:
    profiles: tuple[PlatformCostProfile, ...]
    as_of: str

    @classmethod
    def load(
        cls,
        path: str | Path = "data/strategy_intake/platform_costs.yaml",
    ) -> "PlatformCostCatalog":
        payload = _load(Path(path))
        profiles = tuple(
            PlatformCostProfile(**entry) for entry in payload.get("profiles", [])
        )
        if not profiles:
            raise ValueError("No platform cost profiles found")
        return cls(profiles, str(payload.get("as_of", "")))

    def to_frame(self) -> pd.DataFrame:
        rows = []
        for profile in self.profiles:
            row = profile.to_record()
            row["taker_round_trip_bps"] = profile.round_trip_bps(order_style="taker")
            row["maker_round_trip_bps"] = profile.round_trip_bps(order_style="maker")
            rows.append(row)
        return pd.DataFrame(rows)


class CostBreakEvenAnalyzer:
    def __init__(self, profiles: PlatformCostCatalog) -> None:
        self.profiles = profiles

    def analyze(
        self,
        *,
        notional_usd: float = 10_000.0,
        target_bps_values: tuple[float, ...] = (10, 20, 25, 50, 100),
        holding_hours: float = 1.0,
    ) -> pd.DataFrame:
        rows = []
        for profile in self.profiles.profiles:
            for style in ("maker", "taker"):
                cost_bps = profile.round_trip_bps(
                    order_style=style,
                    holding_hours=holding_hours,
                )
                for target_bps in target_bps_values:
                    rows.append(
                        {
                            "profile_id": profile.id,
                            "platform": profile.platform,
                            "product": profile.product,
                            "order_style": style,
                            "holding_hours": holding_hours,
                            "notional_usd": notional_usd,
                            "target_bps": target_bps,
                            "round_trip_cost_bps": cost_bps,
                            "minimum_price_move_pct": cost_bps / 100,
                            "minimum_gross_profit_usd": notional_usd
                            * cost_bps
                            / 10_000,
                            "target_gross_profit_usd": notional_usd
                            * target_bps
                            / 10_000,
                            "net_after_cost_bps": target_bps - cost_bps,
                            "minimum_required_edge_bps": cost_bps,
                            "viable_before_signal_error": target_bps > cost_bps,
                        }
                    )
        return pd.DataFrame(rows)
