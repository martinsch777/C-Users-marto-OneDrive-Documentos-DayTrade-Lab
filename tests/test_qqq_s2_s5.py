import unittest

import pandas as pd

from src.data import EquitySessionCalendar
from src.research.qqq_s2_s5 import (
    ResearchConfig,
    ResearchCosts,
    add_research_indicators,
    attach_confirmed_htf,
    backtest_variant,
    dmi_adx,
    generate_s2_signals,
    generate_s5_signals,
    opening_ranges,
    resample_rth_1min_to_5min,
    resample_rth_1min_to_60min_confirmed,
)


def minute_frame(start="2025-07-02 09:30", minutes=60, price=100.0):
    timestamps = (
        pd.date_range(start, periods=minutes, freq="1min")
        .tz_localize("America/New_York")
        .tz_convert("UTC")
    )
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": [price + i * 0.01 for i in range(minutes)],
            "high": [price + i * 0.01 + 0.05 for i in range(minutes)],
            "low": [price + i * 0.01 - 0.05 for i in range(minutes)],
            "close": [price + i * 0.01 + 0.02 for i in range(minutes)],
            "volume": [1000.0 + i for i in range(minutes)],
        }
    )


def base_5m(periods=260):
    timestamps = (
        pd.date_range("2025-07-02 09:30", periods=periods, freq="5min")
        .tz_localize("America/New_York")
        .tz_convert("UTC")
    )
    close = pd.Series([100 + i * 0.05 for i in range(periods)], dtype=float)
    frame = pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": close - 0.03,
            "high": close + 0.10,
            "low": close - 0.10,
            "close": close,
            "volume": [10000.0] * periods,
        }
    )
    frame["session_date"] = "2025-07-02"
    frame["local_time"] = pd.to_datetime(frame["timestamp"], utc=True).dt.tz_convert(
        "America/New_York"
    ).dt.strftime("%H:%M")
    frame["minute_of_day"] = pd.to_datetime(frame["timestamp"], utc=True).dt.tz_convert(
        "America/New_York"
    ).dt.hour * 60 + pd.to_datetime(frame["timestamp"], utc=True).dt.tz_convert(
        "America/New_York"
    ).dt.minute
    frame["atr"] = 1.0
    frame["atr_mean_50"] = 1.0
    frame["atr_relative"] = 1.0
    frame["vwap"] = frame["close"] - 0.5
    frame["relative_volume"] = 1.5
    frame["volume_mean_20"] = 9000.0
    frame["roc_12"] = 0.003
    frame["roc_ema_5"] = 0.001
    frame["plus_di"] = 30.0
    frame["minus_di"] = 10.0
    frame["adx"] = 25.0
    frame["htf_close"] = frame["close"] + 1.0
    frame["htf_ema_fast"] = frame["close"]
    frame["htf_ema_slow"] = frame["close"] - 1.0
    frame["htf_ema_fast_prev"] = frame["close"] - 0.1
    frame["htf_ema_s5"] = frame["close"] - 1.0
    frame["confirmed_at"] = frame["timestamp"] - pd.Timedelta(minutes=30)
    return frame


class QQQS2S5ResearchTests(unittest.TestCase):
    def setUp(self):
        self.calendar = EquitySessionCalendar.from_config({"source": "us_equity"})

    def test_resampling_1m_to_5m_uses_rth_buckets(self):
        frame = minute_frame(minutes=10)
        bars = resample_rth_1min_to_5min(frame, self.calendar)
        self.assertEqual(len(bars), 2)
        self.assertEqual(bars.iloc[0]["timestamp"], frame.iloc[0]["timestamp"])
        self.assertAlmostEqual(bars.iloc[0]["open"], frame.iloc[0]["open"])
        self.assertAlmostEqual(bars.iloc[0]["close"], frame.iloc[4]["close"])
        self.assertAlmostEqual(bars.iloc[1]["volume"], frame.iloc[5:10]["volume"].sum())

    def test_opening_range_uses_0930_to_1000(self):
        data = base_5m(20)
        data.loc[:5, "high"] = [100, 101, 102, 103, 104, 105]
        data.loc[:5, "low"] = [99, 98, 97, 96, 95, 94]
        ranges = opening_ranges(data, self.calendar)
        self.assertEqual(float(ranges.iloc[0]["opening_range_high"]), 105.0)
        self.assertEqual(float(ranges.iloc[0]["opening_range_low"]), 94.0)

    def test_vwap_daily_and_indicators_are_added(self):
        frame = minute_frame(minutes=180)
        five = resample_rth_1min_to_5min(frame, self.calendar)
        htf = resample_rth_1min_to_60min_confirmed(frame, self.calendar)
        data = add_research_indicators(five, htf, self.calendar)
        self.assertIn("vwap", data.columns)
        self.assertIn("roc_12", data.columns)
        self.assertTrue((data["vwap"].dropna() > 0).all())

    def test_htf_mapping_uses_only_confirmed_bars(self):
        five = resample_rth_1min_to_5min(minute_frame(minutes=75), self.calendar)
        htf = resample_rth_1min_to_60min_confirmed(minute_frame(minutes=120), self.calendar)
        mapped = attach_confirmed_htf(five, htf)
        before_confirmation = mapped[mapped["timestamp"] < pd.Timestamp("2025-07-02 10:25", tz="America/New_York").tz_convert("UTC")]
        self.assertTrue(before_confirmation["htf_close"].isna().all())
        after_confirmation = mapped[mapped["timestamp"] >= pd.Timestamp("2025-07-02 10:25", tz="America/New_York").tz_convert("UTC")]
        self.assertTrue(after_confirmation["htf_close"].notna().any())

    def test_dmi_adx_columns_are_causal_prefix_stable(self):
        data = base_5m(80)
        full = dmi_adx(data)
        prefix = dmi_adx(data.iloc[:50].copy())
        pd.testing.assert_series_equal(full.iloc[:50]["adx"], prefix["adx"], check_names=False)

    def test_s5_breakout_and_retest_signal(self):
        data = base_5m(20)
        data.loc[:5, ["high", "low", "close", "open"]] = [100, 99, 99.5, 99.5]
        data.loc[6, ["open", "high", "low", "close"]] = [99.7, 101.0, 99.6, 100.8]
        data.loc[7, ["open", "high", "low", "close"]] = [100.2, 100.7, 100.1, 100.6]
        data.loc[7, "relative_volume"] = 1.2
        signals = generate_s5_signals(data, self.calendar)
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals.iloc[0]["module"], "S5")
        self.assertEqual(signals.iloc[0]["side"], "long")

    def test_s2_entry_signal(self):
        data = base_5m(80)
        data["roc_12"] = 0.0
        data.loc[60, "roc_12"] = 0.003
        data.loc[60, "roc_ema_5"] = 0.001
        signals = generate_s2_signals(data, self.calendar)
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals.iloc[0]["side"], "long")

    def test_trailing_stop_and_session_close(self):
        data = base_5m(20)
        signal = pd.DataFrame(
            [
                {
                    "timestamp": data.iloc[6]["timestamp"],
                    "session_date": "2025-07-02",
                    "module": "S2",
                    "side": "long",
                    "signal_close": 100.0,
                    "atr": 1.0,
                    "vwap": 99.0,
                    "relative_volume": 1.5,
                    "roc_12": 0.003,
                    "adx": 25.0,
                    "bar_index": 6,
                }
            ]
        )
        data.loc[7, ["high", "low", "close"]] = [105.0, 103.0, 104.0]
        data.loc[8, ["high", "low", "close"]] = [104.0, 102.5, 103.0]
        trades, _ = backtest_variant(data, signal, pd.DataFrame(), variant="S2", calendar=self.calendar)
        self.assertEqual(trades.iloc[0]["exit_reason"], "TRAILING_STOP")

    def test_daily_limits_module_limit_and_s5_priority(self):
        data = base_5m(20)
        s2 = pd.DataFrame(
            [
                {
                    "timestamp": data.iloc[6]["timestamp"],
                    "session_date": "2025-07-02",
                    "module": "S2",
                    "side": "long",
                    "signal_close": 100.0,
                    "atr": 1.0,
                    "vwap": 99.0,
                    "relative_volume": 1.5,
                    "roc_12": 0.003,
                    "adx": 25.0,
                    "bar_index": 6,
                }
            ]
        )
        s5 = s2.copy()
        s5["module"] = "S5"
        s5["opening_range_high"] = 99.0
        s5["opening_range_low"] = 98.0
        trades, blocked = backtest_variant(data, s2, s5, variant="S2_S5", calendar=self.calendar)
        self.assertEqual(trades.iloc[0]["module"], "S5")
        self.assertTrue(blocked["block_reason"].isin(["BLOCKED_POSITION_OPEN", "BLOCKED_COOLDOWN"]).any())

    def test_commissions_and_slippage_are_applied(self):
        data = base_5m(12)
        signal = pd.DataFrame(
            [
                {
                    "timestamp": data.iloc[6]["timestamp"],
                    "session_date": "2025-07-02",
                    "module": "S2",
                    "side": "long",
                    "signal_close": 100.0,
                    "atr": 1.0,
                    "vwap": 99.0,
                    "relative_volume": 1.5,
                    "roc_12": 0.003,
                    "adx": 25.0,
                    "bar_index": 6,
                }
            ]
        )
        trades, _ = backtest_variant(
            data,
            signal,
            pd.DataFrame(),
            variant="S2",
            config=ResearchConfig(costs=ResearchCosts(slippage_ticks_per_execution=2, tick_size=0.01)),
            calendar=self.calendar,
        )
        self.assertAlmostEqual(trades.iloc[0]["entry_price"], 100.02)
        self.assertGreater(trades.iloc[0]["commission"], 0)
        self.assertGreater(trades.iloc[0]["slippage_cost"], 0)


if __name__ == "__main__":
    unittest.main()
