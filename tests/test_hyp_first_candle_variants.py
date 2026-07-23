import unittest

import pandas as pd

from src.research.hyp_first_candle import FirstCandleConfig, calculate_position_size
from src.research.hyp_first_candle_variants import (
    FCR_02,
    FCR_03,
    FCR_04,
    detect_first_candle_variant_signals,
    structural_stop_from_sweep,
)


def ts(value: str) -> pd.Timestamp:
    return pd.Timestamp(value, tz="America/New_York").tz_convert("UTC")


def frame5(rows):
    return pd.DataFrame(
        {
            "timestamp": [ts(item[0]) for item in rows],
            "open": [item[1] for item in rows],
            "high": [item[2] for item in rows],
            "low": [item[3] for item in rows],
            "close": [item[4] for item in rows],
            "volume": [1000.0] * len(rows),
        }
    )


def opening(day="2024-07-01"):
    return [
        (f"{day} 09:30", 100.0, 100.4, 99.7, 100.1),
        (f"{day} 09:35", 100.1, 100.8, 99.9, 100.5),
        (f"{day} 09:40", 100.5, 101.0, 100.1, 100.7),
        (f"{day} 09:45", 100.7, 100.9, 99.8, 100.0),
        (f"{day} 09:50", 100.0, 100.6, 99.6, 100.2),
        (f"{day} 09:55", 100.2, 100.7, 99.5, 100.3),
    ]


def near_sweep_frame(offset: int, *, new_sweep: bool = False):
    rows = opening()
    rows.append(("2024-07-01 10:00", 99.8, 100.0, 99.5, 99.8))
    for minute in range(1, offset):
        low = 99.5 if new_sweep and minute == offset - 1 else 99.7
        rows.append((f"2024-07-01 10:{minute * 5:02d}", 99.8, 100.0, low, 99.8))
    signal_minute = offset * 5
    rows.append((f"2024-07-01 10:{signal_minute:02d}", 100.8, 100.95, 100.8, 100.9))
    rows.append(("2024-07-01 15:55", 100.4, 100.6, 100.0, 100.2))
    return frame5(rows)


def strict_frame(*, low_value=99.5, high_value=100.0):
    rows = opening()
    rows.extend(
        [
            ("2024-07-01 10:00", 99.8, high_value, low_value, 99.8),
            ("2024-07-01 10:05", 100.8, 100.95, 100.8, 100.9),
            ("2024-07-01 15:55", 100.4, 100.6, 100.0, 100.2),
        ]
    )
    return frame5(rows)


def strict_short_frame(*, high_value=101.01):
    rows = opening()
    rows.extend(
        [
            ("2024-07-01 10:00", 100.5, high_value, 100.5, 100.5),
            ("2024-07-01 10:05", 100.5, 100.7, 100.2, 100.4),
            ("2024-07-01 10:10", 100.0, 100.0, 99.2, 100.0),
            ("2024-07-01 15:55", 100.4, 100.6, 100.0, 100.2),
        ]
    )
    return frame5(rows)


def structural_long_frame():
    rows = opening()
    rows.extend(
        [
            ("2024-07-01 10:00", 99.8, 100.0, 99.0, 99.8),
            ("2024-07-01 10:05", 99.8, 100.0, 99.6, 99.9),
            ("2024-07-01 10:10", 100.4, 100.9, 100.1, 100.5),
            ("2024-07-01 15:55", 100.4, 100.6, 100.0, 100.2),
        ]
    )
    return frame5(rows)


def structural_short_frame():
    rows = opening()
    rows.extend(
        [
            ("2024-07-01 10:00", 100.5, 101.5, 100.1, 100.5),
            ("2024-07-01 10:05", 100.4, 100.8, 100.0, 100.2),
            ("2024-07-01 10:10", 100.0, 100.0, 99.2, 100.0),
            ("2024-07-01 15:55", 100.4, 100.6, 100.0, 100.2),
        ]
    )
    return frame5(rows)


class HypFirstCandleVariantTests(unittest.TestCase):
    def test_hyp_fcr_02_confirmation_offsets_1_2_3_are_accepted(self):
        for offset in (1, 2, 3):
            signals, diagnostics = detect_first_candle_variant_signals(near_sweep_frame(offset), "QQQ", FCR_02)
            if not diagnostics.empty:
                self.assertEqual(diagnostics.loc[diagnostics["diagnostic"].eq("quantity_below_minimum")].shape[0], 0)
            self.assertEqual(len(signals), 1)
            self.assertEqual(int(signals.iloc[0]["confirmation_offset_bars"]), offset)

    def test_hyp_fcr_02_offset_4_and_same_bar_are_rejected(self):
        signals, diagnostics = detect_first_candle_variant_signals(near_sweep_frame(4), "QQQ", FCR_02)
        self.assertTrue(signals.empty)
        self.assertIn("low_sweep_window_expired", diagnostics["diagnostic"].tolist())
        same_bar_only = frame5(opening() + [("2024-07-01 10:00", 99.8, 100.0, 99.5, 99.8)])
        signals, _ = detect_first_candle_variant_signals(same_bar_only, "QQQ", FCR_02)
        self.assertTrue(signals.empty)

    def test_hyp_fcr_02_new_sweep_resets_window_and_expired_window_does_not_persist(self):
        signals, diagnostics = detect_first_candle_variant_signals(near_sweep_frame(4, new_sweep=True), "QQQ", FCR_02)
        self.assertEqual(len(signals), 1)
        self.assertEqual(int(signals.iloc[0]["confirmation_offset_bars"]), 1)
        self.assertTrue(diagnostics.empty)

    def test_hyp_fcr_02_sizing_rejection_does_not_consume_trade(self):
        frame = frame5(
            opening()
            + [
                ("2024-07-01 10:00", 90.0, 100.5, 99.5, 100.4),
                ("2024-07-01 10:05", 100.8, 100.9, 100.8, 100.9),
                ("2024-07-01 10:10", 100.49, 100.5, 99.5, 100.49),
                ("2024-07-01 10:15", 100.95, 100.97, 100.95, 100.96),
            ]
        )
        signals, diagnostics = detect_first_candle_variant_signals(frame, "QQQ", FCR_02, equity=1000.0)
        self.assertEqual(len(signals), 1)
        self.assertIn("quantity_below_minimum", diagnostics["diagnostic"].tolist())

    def test_hyp_fcr_03_exact_touch_and_subtick_break_do_not_count(self):
        exact, exact_diag = detect_first_candle_variant_signals(strict_frame(low_value=99.5), "QQQ", FCR_03)
        subtick, subtick_diag = detect_first_candle_variant_signals(strict_frame(low_value=99.495), "QQQ", FCR_03)
        self.assertTrue(exact.empty)
        self.assertTrue(subtick.empty)
        self.assertIn("low_exact_or_subtick_touch_rejected_by_strict_sweep", exact_diag["diagnostic"].tolist())
        self.assertIn("low_exact_or_subtick_touch_rejected_by_strict_sweep", subtick_diag["diagnostic"].tolist())

    def test_hyp_fcr_03_one_tick_break_counts_and_depth_is_recorded(self):
        signals, diagnostics = detect_first_candle_variant_signals(strict_frame(low_value=99.49), "QQQ", FCR_03)
        self.assertTrue(diagnostics.empty)
        self.assertEqual(len(signals), 1)
        self.assertAlmostEqual(float(signals.iloc[0]["sweep_depth_ticks"]), 1.0)

    def test_hyp_fcr_03_long_and_short_use_tick_size_and_latest_sweep_updates(self):
        short, _ = detect_first_candle_variant_signals(strict_short_frame(high_value=101.01), "QQQ", FCR_03)
        self.assertEqual(short.iloc[0]["direction"], "short")
        rows = opening() + [
            ("2024-07-01 10:00", 99.8, 100.0, 99.49, 99.8),
            ("2024-07-01 10:05", 99.8, 100.0, 99.48, 99.8),
            ("2024-07-01 10:10", 100.4, 100.9, 100.1, 100.5),
        ]
        signals, _ = detect_first_candle_variant_signals(frame5(rows), "QQQ", FCR_03)
        self.assertEqual(pd.Timestamp(signals.iloc[0]["last_sweep_time"]), ts("2024-07-01 10:05"))

    def test_hyp_fcr_03_rest_of_signal_matches_fcr_01(self):
        strict, _ = detect_first_candle_variant_signals(strict_frame(low_value=99.49), "QQQ", FCR_03)
        self.assertAlmostEqual(strict.iloc[0]["fvg_size_ticks"], 10.0)
        self.assertAlmostEqual(strict.iloc[0]["target"], 103.12)

    def test_hyp_fcr_04_long_stop_uses_full_lows_inclusive_and_buffer(self):
        frame = structural_long_frame()
        stop = structural_stop_from_sweep(frame, 6, 8, "long")
        self.assertAlmostEqual(stop, 98.99)
        signals, _ = detect_first_candle_variant_signals(frame, "QQQ", FCR_04)
        self.assertAlmostEqual(float(signals.iloc[0]["stop"]), 98.99)
        self.assertEqual(int(signals.iloc[0]["structural_segment_bars"]), 3)

    def test_hyp_fcr_04_short_stop_uses_full_highs_inclusive_and_buffer(self):
        frame = structural_short_frame()
        stop = structural_stop_from_sweep(frame, 6, 8, "short")
        self.assertAlmostEqual(stop, 101.51)
        signals, _ = detect_first_candle_variant_signals(frame, "QQQ", FCR_04)
        self.assertAlmostEqual(float(signals.iloc[0]["stop"]), 101.51)

    def test_hyp_fcr_04_target_sizing_rejection_and_no_body_stop(self):
        signals, _ = detect_first_candle_variant_signals(structural_long_frame(), "QQQ", FCR_04)
        signal = signals.iloc[0]
        self.assertAlmostEqual(float(signal["target"]), 103.52)
        self.assertGreater(float(signal["structural_stop_distance_from_original"]), 0)
        rejected = calculate_position_size(
            equity=100,
            signal_close=float(signal["signal_close"]),
            risk_per_unit=float(signal["risk_per_unit"]),
            config=FirstCandleConfig(hypothesis_id="HYP-FCR-04"),
        )
        self.assertEqual(rejected.rejection_reason, "quantity_below_minimum")

    def test_hyp_fcr_04_no_prior_sweep_data_and_no_lookahead(self):
        frame = frame5(
            opening()
            + [
                ("2024-07-01 10:00", 99.8, 100.0, 90.0, 99.8),
                ("2024-07-01 10:05", 99.8, 100.0, 99.0, 99.9),
                ("2024-07-01 10:10", 99.9, 100.0, 99.6, 99.9),
                ("2024-07-01 10:15", 100.4, 100.9, 100.1, 100.5),
            ]
        )
        full, _ = detect_first_candle_variant_signals(frame, "QQQ", FCR_04)
        prefix, _ = detect_first_candle_variant_signals(frame.iloc[:10].copy(), "QQQ", FCR_04)
        self.assertAlmostEqual(float(full.iloc[0]["stop"]), 98.99)
        pd.testing.assert_frame_equal(full.reset_index(drop=True), prefix.reset_index(drop=True))


if __name__ == "__main__":
    unittest.main()
