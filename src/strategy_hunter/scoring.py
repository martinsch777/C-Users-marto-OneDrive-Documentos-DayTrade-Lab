from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import pandas as pd

from .catalog import StrategyCatalog


RISK_SCORE = {"low": 10, "medium": 5, "high": 0}
CLARITY_SCORE = {"low": 10, "medium": 6, "high": 2}
AMBIGUOUS_TERMS = {
    "strong",
    "clear",
    "significant",
    "recent",
    "relevant",
    "institutional",
    "high probability",
    "if possible",
}


@dataclass(frozen=True)
class PretestScore:
    strategy_id: str
    strategy_name: str
    programmability: int
    rule_clarity: int
    simplicity: int
    repaint_safety: int
    overfit_safety: int
    discretion_safety: int
    expected_cost_robustness: int
    expected_trade_sample: int
    data_compatibility: int
    execution_compatibility: int
    economic_rationale: int
    total_score: int
    ambiguity_terms_detected: str
    classification: str
    reasons: str

    def to_record(self) -> dict:
        return asdict(self)


class PretestScorer:
    def __init__(self, available_data: set[str] | None = None) -> None:
        self.available_data = available_data or {"OHLCV"}

    @staticmethod
    def _ambiguity_terms(entry: dict[str, Any]) -> list[str]:
        rule_text = " ".join(
            str(entry.get(field, "")).lower()
            for field in (
                "long_entry",
                "long_exit",
                "short_entry",
                "short_exit",
                "stop_loss",
                "take_profit",
                "no_trade_conditions",
            )
        )
        return sorted(term for term in AMBIGUOUS_TERMS if term in rule_text)

    def score(self, entry: dict[str, Any]) -> PretestScore:
        required = set(entry.get("required_data", []))
        missing_data = required.difference(self.available_data)
        ambiguity = str(entry.get("ambiguity_level", "high"))
        repaint = str(entry.get("repainting_risk", "high"))
        lookahead = str(entry.get("lookahead_risk", "high"))
        cherry = str(entry.get("cherry_picking_risk", "high"))
        discretion = str(entry.get("human_discretion_dependency", "high"))
        terms = self._ambiguity_terms(entry)
        programmable = bool(entry.get("programmable", False))
        frozen = bool(entry.get("frozen_clarification"))

        components = {
            "programmability": 10 if programmable else 0,
            "rule_clarity": max(0, CLARITY_SCORE.get(ambiguity, 2) - min(3, len(terms))),
            "simplicity": max(2, 10 - max(0, len(entry.get("indicators", [])) - 2)),
            "repaint_safety": min(
                RISK_SCORE.get(repaint, 0),
                RISK_SCORE.get(lookahead, 0),
            )
            + (4 if frozen else 0),
            "overfit_safety": RISK_SCORE.get(cherry, 0),
            "discretion_safety": RISK_SCORE.get(discretion, 0),
            "expected_cost_robustness": (
                3
                if any(
                    token in entry["name"].lower()
                    for token in ("scalp", "1min")
                )
                else 6
            ),
            "expected_trade_sample": 8
            if any(tf in {"1min", "5min", "15min"} for tf in entry["recommended_timeframes"])
            else 5,
            "data_compatibility": 10 if not missing_data else 0,
            "execution_compatibility": 8
            if "OHLCV" in required and not missing_data
            else 2,
            "economic_rationale": 8
            if len(str(entry.get("economic_rationale", ""))) >= 30
            else 3,
        }
        components["repaint_safety"] = min(10, components["repaint_safety"])
        total = int(round(sum(components.values()) / 110 * 100))
        reasons: list[str] = []
        if not programmable:
            reasons.append("not_programmable_as_submitted")
        if missing_data:
            reasons.append(f"missing_data:{','.join(sorted(missing_data))}")
        if repaint == "high" or lookahead == "high":
            if frozen:
                reasons.append("high_original_repaint_risk_frozen_causal_variant_required")
            else:
                reasons.append("unresolved_repaint_or_lookahead_risk")
        if ambiguity == "high":
            reasons.append("high_ambiguity")
        if not programmable or missing_data or (
            (repaint == "high" or lookahead == "high") and not frozen
        ):
            classification = "rejected_before_test"
        elif ambiguity == "high" or frozen or terms:
            classification = "testable_with_clarifications"
        elif discretion == "high":
            classification = "manual_analysis_only"
        else:
            classification = "testable"
        return PretestScore(
            strategy_id=str(entry["id"]),
            strategy_name=str(entry["name"]),
            total_score=total,
            ambiguity_terms_detected=";".join(terms),
            classification=classification,
            reasons=";".join(reasons),
            **components,
        )

    def score_catalog(self, catalog: StrategyCatalog) -> pd.DataFrame:
        return pd.DataFrame(
            [self.score(entry).to_record() for entry in catalog.entries]
        ).sort_values(["classification", "total_score"], ascending=[True, False])
