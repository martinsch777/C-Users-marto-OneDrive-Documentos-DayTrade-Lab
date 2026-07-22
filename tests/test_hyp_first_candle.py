import json
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date
from io import StringIO
from pathlib import Path

import pandas as pd

from src.data.dataset_manifest import (
    APPROVED_FOR_OR_FVG_BACKTEST,
    FAILED_AUDIT,
    sha256_file,
)
from src.data.sessions import EquitySessionCalendar
from src.research.hyp_first_candle import (
    CostModel,
    FirstCandleConfig,
    ResearchPeriodRequest,
    bearish_fvg,
    bullish_fvg,
    calculate_position_size,
    close_strictly_inside,
    compare_tradingview_export,
    compute_opening_ranges,
    detect_first_candle_signals,
    prepare_signal_frame,
    resample_rth_1min_to_5min,
    load_symbol_curated_1min,
    main,
    simulate_research_primary_trade,
    simulate_tradingview_parity_trade,
    stop_from_bodies,
    target_from_signal_close,
    validate_research_period_request,
)


def ts(value: str) -> pd.Timestamp:
    return pd.Timestamp(value, tz="America/New_York").tz_convert("UTC")


def frame5(rows: list[tuple[str, float, float, float, float]]) -> pd.DataFrame:
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


def canonical_5m_day(day: str = "2024-07-01") -> pd.DataFrame:
    return frame5(
        [
            (f"{day} 09:30", 100.0, 100.4, 99.7, 100.1),
            (f"{day} 09:35", 100.1, 100.8, 99.9, 100.5),
            (f"{day} 09:40", 100.5, 101.0, 100.1, 100.7),
            (f"{day} 09:45", 100.7, 100.9, 99.8, 100.0),
            (f"{day} 09:50", 100.0, 100.6, 99.6, 100.2),
            (f"{day} 09:55", 100.2, 100.7, 99.5, 100.3),
            (f"{day} 10:00", 99.8, 99.9, 99.5, 99.7),
            (f"{day} 10:05", 99.7, 100.0, 99.4, 99.8),
            (f"{day} 10:10", 99.8, 100.8, 100.1, 100.5),
            (f"{day} 10:15", 100.5, 100.7, 100.2, 100.4),
            (f"{day} 15:55", 100.4, 100.6, 100.0, 100.2),
        ]
    )


def minute_frame(
    day: str = "2024-07-01",
    *,
    start: str = "10:15",
    rows: list[tuple[str, float, float, float, float]] | None = None,
) -> pd.DataFrame:
    rows = rows or [
        (f"{day} {start}", 100.5, 100.8, 100.4, 100.6),
        (f"{day} 10:16", 100.6, 102.4, 100.5, 102.0),
        (f"{day} 15:59", 100.6, 100.7, 100.2, 100.3),
    ]
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


def first_signal(frame: pd.DataFrame | None = None) -> pd.Series:
    source = canonical_5m_day() if frame is None else frame
    signals, diagnostics = detect_first_candle_signals(source, "QQQ")
    assert diagnostics.empty
    assert len(signals) == 1
    return signals.iloc[0]


def write_manifest(
    manifest_dir: Path,
    csv_path: Path,
    symbol: str = "QQQ",
    *,
    dataset_status: str = APPROVED_FOR_OR_FVG_BACKTEST,
    audit_apt_for_or_fvg_backtest: bool = True,
) -> Path:
    payload = {
        "adjustment": "raw",
        "asset_class": "equity",
        "audit_apt_for_or_fvg_backtest": audit_apt_for_or_fvg_backtest,
        "audit_critical_warnings": [],
        "audit_warnings": [],
        "broker_connected": False,
        "calendar_early_closes_loaded": 1,
        "calendar_holidays_loaded": 1,
        "calendar_loaded": True,
        "calendar_source": "builtin_us_equity_calendar_v1",
        "created_at": "2026-07-21T00:00:00+00:00",
        "curated_file": str(csv_path),
        "dataset_status": dataset_status,
        "end": "2024-07-01",
        "excluded_sessions": [{"symbol": symbol, "date": "2024-06-28"}],
        "feed": "sip",
        "first_timestamp": "2024-07-01 09:30:00-04:00",
        "input_file": str(csv_path),
        "last_timestamp": "2024-07-01 09:30:00-04:00",
        "live_trading_enabled": False,
        "orders_sent": False,
        "output_file": str(csv_path),
        "paper_broker_enabled": False,
        "provider": "alpaca",
        "rth_only": True,
        "rows": 1,
        "sha256": sha256_file(csv_path),
        "source_timezone": "America/New_York",
        "start": "2024-07-01",
        "symbol": symbol,
        "timeframe": "1min",
        "total_excluded_sessions": 1,
    }
    manifest_dir.mkdir(parents=True, exist_ok=True)
    path = manifest_dir / f"{symbol}_1min_2024-07-01_2024-07-01_curated_manifest.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


class FirstCandleRuleTests(unittest.TestCase):
    def test_opening_range_uses_exactly_six_bars(self):
        ranges = compute_opening_ranges(canonical_5m_day())
        self.assertEqual(ranges.iloc[0]["opening_bar_count"], 6)
        self.assertAlmostEqual(ranges.iloc[0]["opening_high"], 101.0)
        self.assertAlmostEqual(ranges.iloc[0]["opening_low"], 99.5)

    def test_five_minute_alignment_from_one_minute_rth(self):
        minutes = []
        for minute in pd.date_range(ts("2024-07-01 09:30"), periods=10, freq="1min"):
            minutes.append((minute, 100.0, 101.0, 99.0, 100.5, 1.0))
        frame = pd.DataFrame(minutes, columns=["timestamp", "open", "high", "low", "close", "volume"])
        five = resample_rth_1min_to_5min(frame, EquitySessionCalendar.from_config({"source": "us_equity"}))
        local_times = five["timestamp"].dt.tz_convert("America/New_York").dt.strftime("%H:%M").tolist()
        self.assertEqual(local_times, ["09:30", "09:35"])

    def test_dst_alignment_uses_america_new_york(self):
        jan = ts("2024-01-03 09:30")
        jul = ts("2024-07-01 09:30")
        self.assertEqual(jan.strftime("%H:%M"), "14:30")
        self.assertEqual(jul.strftime("%H:%M"), "13:30")

    def test_holidays_and_early_closes_are_calendar_driven(self):
        calendar = EquitySessionCalendar.from_config({"source": "us_equity"})
        self.assertIsNone(calendar.session_close(pd.Timestamp("2024-07-04").date()))
        self.assertEqual(str(calendar.session_close(pd.Timestamp("2024-11-29").date())), "13:00:00")

    def test_exact_opening_low_and_high_touches_count(self):
        frame = canonical_5m_day()
        signals, _ = detect_first_candle_signals(frame, "QQQ")
        self.assertEqual(signals.iloc[0]["last_sweep_time"], frame.iloc[7]["timestamp"])
        high_touch = canonical_5m_day()
        high_touch.loc[6, ["open", "high", "low", "close"]] = [100.7, 101.0, 100.5, 100.7]
        high_touch.loc[7, ["open", "high", "low", "close"]] = [100.4, 100.8, 100.1, 100.3]
        high_touch.loc[8, ["open", "high", "low", "close"]] = [100.3, 100.4, 99.2, 100.0]
        signals, _ = detect_first_candle_signals(high_touch, "QQQ")
        self.assertEqual(signals.iloc[0]["direction"], "short")

    def test_most_recent_touch_updates_and_same_bar_confirmation_blocked(self):
        frame = canonical_5m_day()
        signals, _ = detect_first_candle_signals(frame, "QQQ")
        self.assertEqual(signals.iloc[0]["bars_since_last_sweep"], 1)
        same_bar = canonical_5m_day()
        same_bar = same_bar.iloc[:9].copy()
        same_bar.loc[7, ["low", "high", "close"]] = [99.5, 100.9, 100.5]
        same_bar.loc[8, ["low", "high", "close"]] = [99.5, 100.8, 100.5]
        signals, _ = detect_first_candle_signals(same_bar, "QQQ")
        self.assertTrue(signals.empty)

    def test_bullish_bearish_and_zero_tick_fvg_rules(self):
        current = pd.Series({"low": 101.01, "high": 100.0})
        two_back = pd.Series({"high": 101.0, "low": 99.0})
        self.assertTrue(bullish_fvg(current, two_back)[0])
        self.assertFalse(bullish_fvg(pd.Series({"low": 101.0, "high": 100.0}), two_back)[0])
        self.assertTrue(bearish_fvg(pd.Series({"high": 98.99, "low": 100.0}), two_back)[0])

    def test_close_on_edge_rejected_and_strict_inside_accepted(self):
        self.assertFalse(close_strictly_inside(99.5, 99.5, 101.0))
        self.assertFalse(close_strictly_inside(101.0, 99.5, 101.0))
        self.assertTrue(close_strictly_inside(100.0, 99.5, 101.0))

    def test_simultaneous_long_short_signal_records_conflict_without_trade(self):
        frame = canonical_5m_day()
        frame.loc[6, ["high", "low"]] = [101.0, 99.5]
        frame.loc[7, ["high", "low"]] = [101.0, 99.5]
        frame.loc[8, ["high", "low", "close"]] = [99.0, 102.0, 100.0]
        signals, diagnostics = detect_first_candle_signals(frame, "QQQ")
        self.assertTrue(signals.empty)
        self.assertIn("simultaneous_long_short_signal_no_trade", diagnostics["diagnostic"].tolist())

    def test_stop_long_short_buffer_and_target_from_signal_close(self):
        frame = canonical_5m_day().reset_index(drop=True)
        long_stop = stop_from_bodies(frame, 8, "long")
        short_stop = stop_from_bodies(frame, 8, "short")
        self.assertAlmostEqual(long_stop, min(99.8, 99.7, 99.8, 99.8, 99.8, 100.5) - 0.01)
        self.assertAlmostEqual(short_stop, max(99.8, 99.7, 99.8, 99.8, 99.8, 100.5) + 0.01)
        self.assertAlmostEqual(target_from_signal_close(100.5, 99.69, "long"), 102.12)
        self.assertAlmostEqual(target_from_signal_close(100.5, 101.31, "short"), 98.88)

    def test_position_sizing_rounding_exposure_and_quantity_rejection(self):
        decision = calculate_position_size(equity=1000, signal_close=333, risk_per_unit=0.50)
        self.assertEqual(decision.actual_quantity, 3)
        self.assertLessEqual(decision.actual_quantity * 333, 1000)
        rejected = calculate_position_size(equity=100, signal_close=500, risk_per_unit=1)
        self.assertEqual(rejected.rejection_reason, "quantity_below_minimum")

    def test_one_trade_per_day_limit(self):
        next_day = canonical_5m_day("2024-07-02")
        frame = pd.concat([canonical_5m_day(), next_day], ignore_index=True)
        signals, _ = detect_first_candle_signals(frame.sort_values("timestamp"), "QQQ")
        self.assertEqual(len(signals), 2)
        signals, _ = detect_first_candle_signals(canonical_5m_day(), "QQQ")
        self.assertEqual(len(signals), 1)

    def test_rejected_quantity_signal_does_not_block_later_valid_order(self):
        frame = frame5(
            [
                ("2024-07-01 09:30", 700.0, 704.0, 699.0, 701.0),
                ("2024-07-01 09:35", 701.0, 705.0, 700.0, 704.0),
                ("2024-07-01 09:40", 704.0, 704.5, 700.0, 702.0),
                ("2024-07-01 09:45", 702.0, 703.0, 697.0, 698.0),
                ("2024-07-01 09:50", 698.0, 700.0, 696.0, 699.0),
                ("2024-07-01 09:55", 699.0, 701.0, 695.0, 700.0),
                ("2024-07-01 10:00", 710.0, 711.0, 700.0, 710.0),
                ("2024-07-01 10:05", 710.0, 710.0, 706.0, 707.0),
                ("2024-07-01 10:10", 699.0, 699.0, 699.0, 699.0),
                ("2024-07-01 10:15", 699.0, 700.0, 696.0, 699.0),
                ("2024-07-01 10:20", 698.0, 698.0, 696.0, 698.0),
            ]
        )
        signals, diagnostics = detect_first_candle_signals(frame, "QQQ")

        self.assertEqual(len(signals), 1)
        self.assertEqual(pd.Timestamp(signals.iloc[0]["signal_time"]), ts("2024-07-01 10:20"))
        self.assertIn("quantity_below_minimum", diagnostics["diagnostic"].tolist())

    def test_commission_and_adverse_slippage_long_and_short(self):
        signal = first_signal()
        long_trade = simulate_research_primary_trade(signal, minute_frame(rows=[
            ("2024-07-01 10:15", 100.5, 100.8, 100.4, 100.6),
            ("2024-07-01 10:16", 100.6, 102.5, 100.5, 102.0),
        ]))
        self.assertGreater(long_trade["commission"], 0)
        self.assertAlmostEqual(long_trade["entry_price"], 100.51)
        short_signal = signal.copy()
        short_signal["direction"] = "short"
        short_signal["stop"] = 101.0
        short_signal["target"] = 99.0
        short_signal["risk_per_unit"] = 0.5
        short_trade = simulate_research_primary_trade(short_signal, minute_frame(rows=[
            ("2024-07-01 10:15", 100.5, 100.6, 99.0, 100.0),
        ]))
        self.assertAlmostEqual(short_trade["entry_price"], 100.49)

    def test_stop_first_when_target_and_stop_touch_same_minute(self):
        signal = first_signal()
        trade = simulate_research_primary_trade(signal, minute_frame(rows=[
            ("2024-07-01 10:15", 100.5, 103.0, 99.0, 100.0),
        ]))
        self.assertEqual(trade["exit_reason"], "STOP_FIRST_AMBIGUOUS_BAR")

    def test_gap_through_stop_and_target_without_improvement(self):
        signal = first_signal()
        stopped = simulate_research_primary_trade(signal, minute_frame(rows=[
            ("2024-07-01 10:15", 99.0, 99.1, 98.9, 99.0),
        ]))
        self.assertEqual(stopped["exit_reason"], "GAP_THROUGH_STOP")
        targeted = simulate_research_primary_trade(signal, minute_frame(rows=[
            ("2024-07-01 10:15", 103.0, 103.1, 102.9, 103.0),
        ]))
        self.assertEqual(targeted["exit_reason"], "GAP_THROUGH_TARGET_NO_IMPROVEMENT")
        self.assertAlmostEqual(targeted["exit_price"], signal["target"])

    def test_normal_and_early_close_forced_exit_no_overnight_research_primary(self):
        signal = first_signal()
        normal = simulate_research_primary_trade(signal, minute_frame(rows=[
            ("2024-07-01 10:15", 100.5, 100.6, 100.4, 100.5),
            ("2024-07-01 15:59", 100.5, 100.6, 100.4, 100.5),
            ("2024-07-02 09:30", 120.0, 120.0, 120.0, 120.0),
        ]))
        self.assertEqual(normal["exit_reason"], "FORCED_SESSION_CLOSE")
        self.assertEqual(pd.Timestamp(normal["exit_time"]).tz_convert("America/New_York").date().isoformat(), "2024-07-01")
        early_signal = signal.copy()
        early_signal["session_date"] = "2024-11-29"
        early_signal["signal_time"] = ts("2024-11-29 12:45")
        early_signal["signal_bar_close_time"] = ts("2024-11-29 12:50")
        early = simulate_research_primary_trade(early_signal, minute_frame("2024-11-29", rows=[
            ("2024-11-29 12:50", 100.5, 100.6, 100.4, 100.5),
            ("2024-11-29 12:59", 100.5, 100.6, 100.4, 100.5),
            ("2024-12-02 09:30", 120.0, 120.0, 120.0, 120.0),
        ]))
        self.assertEqual(pd.Timestamp(early["exit_time"]).tz_convert("America/New_York").strftime("%H:%M"), "12:59")

    def test_tradingview_parity_preserves_fixed_close_early_close_semantics(self):
        signal = first_signal()
        early_frame = canonical_5m_day("2024-11-29")
        early_frame = early_frame.loc[early_frame["timestamp"].dt.tz_convert("America/New_York").dt.strftime("%H:%M") < "13:00"]
        early_signal = signal.copy()
        early_signal["session_date"] = "2024-11-29"
        early_signal["signal_time"] = early_frame.iloc[8]["timestamp"]
        early_signal["signal_bar_close_time"] = early_signal["signal_time"] + pd.Timedelta(5, unit="min")
        trade = simulate_tradingview_parity_trade(early_signal, early_frame)
        self.assertEqual(trade["exit_reason"], "END_OF_DATA_OR_OVERNIGHT_RISK_SOURCE_SEMANTICS")

    def test_manifest_gate_and_excluded_sessions_are_respected(self):
        directory = Path(tempfile.mkdtemp())
        csv_path = directory / "QQQ_1min.csv"
        pd.DataFrame(
            {
                "timestamp": [ts("2024-07-01 09:30")],
                "open": [100.0],
                "high": [101.0],
                "low": [99.0],
                "close": [100.5],
                "volume": [1000.0],
            }
        ).to_csv(csv_path, index=False)
        write_manifest(directory / "manifests", csv_path)

        frame, manifest = load_symbol_curated_1min(csv_path, "QQQ", manifest_dir=directory / "manifests")
        self.assertEqual(len(frame), 1)
        self.assertEqual(manifest.excluded_sessions[0]["date"], "2024-06-28")

    def test_unapproved_manifest_is_rejected(self):
        directory = Path(tempfile.mkdtemp())
        csv_path = directory / "QQQ_1min.csv"
        pd.DataFrame(
            {
                "timestamp": [ts("2024-07-01 09:30")],
                "open": [100.0],
                "high": [101.0],
                "low": [99.0],
                "close": [100.5],
                "volume": [1000.0],
            }
        ).to_csv(csv_path, index=False)
        write_manifest(
            directory / "manifests",
            csv_path,
            dataset_status=FAILED_AUDIT,
            audit_apt_for_or_fvg_backtest=False,
        )
        with self.assertRaisesRegex(ValueError, "approved_for_or_fvg_backtest"):
            load_symbol_curated_1min(csv_path, "QQQ", manifest_dir=directory / "manifests")

    def test_absence_of_lookahead_and_repeatability(self):
        frame = canonical_5m_day()
        full, _ = detect_first_candle_signals(frame, "QQQ")
        prefix, _ = detect_first_candle_signals(frame.iloc[:9].copy(), "QQQ")
        self.assertEqual(full.iloc[0]["signal_time"], prefix.iloc[0]["signal_time"])
        again, _ = detect_first_candle_signals(frame, "QQQ")
        pd.testing.assert_frame_equal(full, again)

    def test_prepare_signal_frame_and_parity_comparison_tool(self):
        minutes = []
        for bar in canonical_5m_day().itertuples(index=False):
            for offset in range(5):
                minutes.append(
                    {
                        "timestamp": bar.timestamp + pd.Timedelta(offset, unit="min"),
                        "open": bar.open,
                        "high": bar.high,
                        "low": bar.low,
                        "close": bar.close,
                        "volume": 100.0,
                    }
                )
        five, signals, diagnostics = prepare_signal_frame(pd.DataFrame(minutes), "QQQ")
        self.assertFalse(five.empty)
        self.assertFalse(signals.empty)
        self.assertTrue(diagnostics.empty)
        directory = Path(tempfile.mkdtemp())
        left = directory / "tv.csv"
        right = directory / "py.csv"
        trade = simulate_tradingview_parity_trade(signals.iloc[0], five)
        pd.DataFrame([trade]).to_csv(left, index=False)
        pd.DataFrame([trade]).to_csv(right, index=False)
        comparison = compare_tradingview_export(left, right)
        self.assertEqual(comparison.iloc[0]["failed_fields"], "")
        self.assertEqual(comparison.iloc[0]["parity_bucket"], "matched_trades")

    def test_parity_comparison_buckets_and_difference_types(self):
        directory = Path(tempfile.mkdtemp())
        tv = pd.DataFrame(
            [
                {
                    "symbol": "QQQ",
                    "session_date": "2024-07-01",
                    "direction": "long",
                    "opening_high": 101.0,
                    "opening_low": 99.5,
                    "signal_close": 100.5,
                    "entry_price": 100.5,
                    "exit_price": 102.0,
                    "stop": 99.5,
                    "target": 102.5,
                    "actual_quantity": 3,
                    "net_pnl": 4.5,
                    "realized_R": 1.5,
                },
                {
                    "symbol": "SPY",
                    "session_date": "2024-07-01",
                    "direction": "short",
                    "entry_price": 100.0,
                },
            ]
        )
        py = pd.DataFrame(
            [
                {
                    "symbol": "QQQ",
                    "session_date": "2024-07-01",
                    "direction": "long",
                    "opening_high": 101.0,
                    "opening_low": 99.5,
                    "signal_close": 100.5,
                    "entry_price": 100.5,
                    "exit_price": 101.0,
                    "stop": 99.5,
                    "target": 102.5,
                    "actual_quantity": 3,
                    "net_pnl": 1.5,
                    "realized_R": 0.5,
                },
                {
                    "symbol": "QQQ",
                    "session_date": "2024-07-02",
                    "direction": "long",
                    "entry_price": 100.0,
                },
            ]
        )
        tv_path = directory / "tv.csv"
        py_path = directory / "py.csv"
        tv.to_csv(tv_path, index=False)
        py.to_csv(py_path, index=False)
        comparison = compare_tradingview_export(tv_path, py_path)
        buckets = set(comparison["parity_bucket"])
        self.assertIn("field_mismatches", buckets)
        self.assertIn("missing_in_python", buckets)
        self.assertIn("missing_in_tradingview", buckets)
        mismatch = comparison.loc[comparison["parity_bucket"] == "field_mismatches"].iloc[0]
        self.assertEqual(mismatch["difference_type"], "INTRABAR_EXECUTION_DIFFERENCE")

    def test_parity_comparison_cli_requires_both_csvs(self):
        with self.assertRaisesRegex(SystemExit, "requires both"):
            main(["--compare-tradingview-csv", "tv.csv"])

    def test_runner_default_is_prepare_only(self):
        output = StringIO()
        with redirect_stdout(output):
            self.assertEqual(main([]), 0)
        payload = output.getvalue()
        self.assertIn('"discovery_executed": false', payload)
        self.assertIn("live_trading=False", payload)

    def test_period_guards_reject_2025_before_gate_and_2026_discovery(self):
        with self.assertRaisesRegex(PermissionError, "validation is blocked"):
            validate_research_period_request(
                ResearchPeriodRequest(
                    period="validation",
                    start=date(2025, 1, 1),
                    end=date(2025, 12, 31),
                )
            )
        with self.assertRaisesRegex(PermissionError, "discovery is frozen"):
            validate_research_period_request(
                ResearchPeriodRequest(
                    period="discovery",
                    start=date(2026, 1, 1),
                    end=date(2026, 12, 31),
                )
            )

    def test_cli_date_override_validation_hash_mismatch_and_holdout_fail(self):
        with self.assertRaisesRegex(PermissionError, "discovery is frozen"):
            main(["--run-period", "discovery", "--start", "2022-01-01", "--end", "2024-12-30"])
        approval = Path(tempfile.mkdtemp()) / "approval.json"
        approval.write_text(
            json.dumps(
                {
                    "hypothesis_id": "HYP-FCR-01",
                    "discovery_gate_passed": True,
                    "canonical_payload_sha256": "wrong",
                }
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            validate_research_period_request(
                ResearchPeriodRequest(
                    period="validation",
                    start=date(2025, 1, 1),
                    end=date(2025, 12, 31),
                    discovery_approval_path=approval,
                )
            )
        with self.assertRaisesRegex(PermissionError, "holdout has no executable"):
            validate_research_period_request(
                ResearchPeriodRequest(
                    period="holdout",
                    start=date(2027, 1, 1),
                    end=date(2027, 12, 31),
                )
            )

    def test_2026_requires_explicit_non_decisional_parity_debug(self):
        with self.assertRaisesRegex(PermissionError, "non-decisional"):
            validate_research_period_request(
                ResearchPeriodRequest(
                    period="parity_debug_2026",
                    start=date(2026, 1, 1),
                    end=date(2026, 1, 31),
                )
            )
        validate_research_period_request(
            ResearchPeriodRequest(
                period="parity_debug_2026",
                start=date(2026, 1, 1),
                end=date(2026, 1, 31),
                non_decisional=True,
            )
        )


if __name__ == "__main__":
    unittest.main()
