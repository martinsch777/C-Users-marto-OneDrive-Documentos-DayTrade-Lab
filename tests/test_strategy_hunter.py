import copy
import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from src.backtesting import random_entry_signals
from src.psychology_guard import PsychologyGuard
from src.risk import TradingState
from src.strategies import Signal
from src.strategy_hunter import (
    CostBreakEvenAnalyzer,
    PlatformCostCatalog,
    PretestScorer,
    StrategyCatalog,
    build_hunter_strategies,
)
from src.strategy_hunter.catalog import REQUIRED_FIELDS
from src.utils.synthetic import generate_synthetic_intraday


ROOT = Path(__file__).resolve().parents[1]


class StrategyHunterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = StrategyCatalog.load(
            ROOT / "data" / "strategy_intake" / "strategy_catalog.yaml"
        )

    def test_catalog_registers_ten_complete_unique_families(self):
        self.assertEqual(len(self.catalog.entries), 10)
        identifiers = {entry["id"] for entry in self.catalog.entries}
        self.assertEqual(len(identifiers), 10)
        for entry in self.catalog.entries:
            self.assertFalse(REQUIRED_FIELDS.difference(entry))

    def test_catalog_rejects_missing_required_field(self):
        entry = copy.deepcopy(self.catalog.entries[0])
        del entry["economic_rationale"]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad_catalog.yaml"
            path.write_text(
                json.dumps({"strategies": [entry]}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "missing fields"):
                StrategyCatalog.load(path)

    def test_pretest_detects_ambiguity_and_rejects_unresolved_lookahead(self):
        entry = copy.deepcopy(self.catalog.entries[0])
        entry["long_entry"] = "Enter after a strong and clear confirmation"
        entry["ambiguity_level"] = "high"
        entry["lookahead_risk"] = "high"
        entry["frozen_clarification"] = ""
        score = PretestScorer({"OHLCV"}).score(entry)
        self.assertIn("clear", score.ambiguity_terms_detected)
        self.assertIn("strong", score.ambiguity_terms_detected)
        self.assertEqual(score.classification, "rejected_before_test")
        self.assertIn("unresolved_repaint_or_lookahead_risk", score.reasons)

    def test_missing_specialized_data_rejects_funding_strategy(self):
        score = PretestScorer({"OHLCV"}).score(
            self.catalog.by_id("funding_basis_mean_reversion")
        )
        self.assertEqual(score.classification, "rejected_before_test")
        self.assertIn("missing_data", score.reasons)

    def test_cost_break_even_includes_both_order_styles_and_exact_math(self):
        costs = PlatformCostCatalog.load(
            ROOT / "data" / "strategy_intake" / "platform_costs.yaml"
        )
        analysis = CostBreakEvenAnalyzer(costs).analyze(
            notional_usd=10_000,
            target_bps_values=(25,),
            holding_hours=0,
        )
        self.assertEqual(len(analysis), len(costs.profiles) * 2)
        row = analysis[
            (analysis["profile_id"] == "bybit_spot_vip0_taker")
            & (analysis["order_style"] == "taker")
        ].iloc[0]
        self.assertAlmostEqual(
            row["minimum_gross_profit_usd"],
            row["round_trip_cost_bps"],
            places=8,
        )
        self.assertEqual(
            bool(row["viable_before_signal_error"]),
            25 > row["round_trip_cost_bps"],
        )

    def test_all_programmed_families_are_causal_on_visible_prefix(self):
        frame = generate_synthetic_intraday(sessions=35, timeframe="15min", seed=91)
        cutoff = len(frame) * 2 // 3
        visible_end = frame.iloc[cutoff - 1]["timestamp"]
        for strategy in build_hunter_strategies():
            with self.subTest(strategy=strategy.name):
                prefix = strategy.generate_signals(
                    frame.iloc[:cutoff].copy(), "TEST", "15min"
                )
                full_visible = [
                    signal
                    for signal in strategy.generate_signals(
                        frame.copy(), "TEST", "15min"
                    )
                    if signal.timestamp <= visible_end
                ]
                left = [
                    (signal.timestamp, signal.side, signal.entry_price)
                    for signal in prefix
                ]
                right = [
                    (signal.timestamp, signal.side, signal.entry_price)
                    for signal in full_visible
                ]
                self.assertEqual(left, right)
                for signal in prefix:
                    self.assertGreater(signal.risk_per_unit, 0)
                    self.assertGreater(signal.reward_per_unit, 0)

    def test_predefined_reward_variants_are_registered_without_search(self):
        names = {
            strategy.name
            for strategy in build_hunter_strategies(
                include_predefined_variants=True
            )
        }
        self.assertTrue(
            {
                "ema_9_21_vwap_scalping_r1_0",
                "ema_9_21_vwap_scalping_r1_5",
                "ema_9_21_vwap_scalping_r2_0",
                "donchian_intraday_breakout_r1_5",
                "donchian_intraday_breakout_r2_0",
            }.issubset(names)
        )

    def test_matched_random_baseline_is_reproducible_and_count_matched(self):
        frame = generate_synthetic_intraday(sessions=3, timeframe="15min", seed=8)
        template = Signal(
            timestamp=frame.iloc[20]["timestamp"],
            symbol="TEST",
            timeframe="15min",
            strategy="template",
            side="long",
            entry_price=100,
            stop_price=99,
            take_profit=102,
            reason="test",
        )
        first = random_entry_signals(
            frame, [template], "TEST", "15min", seed=123, count=8
        )
        second = random_entry_signals(
            frame, [template], "TEST", "15min", seed=123, count=8
        )
        self.assertEqual(len(first), 8)
        self.assertEqual(
            [(signal.timestamp, signal.side) for signal in first],
            [(signal.timestamp, signal.side) for signal in second],
        )

    def test_guard_blocks_pre_registered_unfavorable_regime(self):
        signal = Signal(
            timestamp=pd.Timestamp("2024-01-02 15:00:00+00:00"),
            symbol="BTCUSDT",
            timeframe="15min",
            strategy="hunter_setup",
            side="long",
            entry_price=100,
            stop_price=99,
            take_profit=102,
            reason="test",
            metadata={"unfavorable_regime": True},
        )
        guard = PsychologyGuard(
            {
                "allowed_setups": ["hunter_setup"],
                "trading_window_start": "09:30",
                "trading_window_end": "16:00",
                "block_unfavorable_regime": True,
            }
        )
        decision = guard.evaluate(signal, TradingState(100_000, 100_000))
        self.assertFalse(decision.approved)
        self.assertEqual(decision.reason, "BLOCKED_UNFAVORABLE_REGIME")


if __name__ == "__main__":
    unittest.main()
