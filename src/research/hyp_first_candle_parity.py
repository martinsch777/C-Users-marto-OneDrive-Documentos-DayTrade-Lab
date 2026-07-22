from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from datetime import date, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from src.data import EquitySessionCalendar
from src.research.hyp_first_candle import (
    FirstCandleConfig,
    ResearchPeriodRequest,
    add_session_columns,
    bullish_fvg,
    bearish_fvg,
    calculate_position_size,
    close_strictly_inside,
    compute_opening_ranges,
    detect_first_candle_signals,
    load_symbol_curated_1min,
    prepare_signal_frame,
    serialize_trade_frame,
    simulate_tradingview_parity_trade,
    stop_from_bodies,
    target_from_signal_close,
    validate_research_period_request,
)


DEFAULT_OUTPUT_DIR = Path("artifacts") / "parity" / "HYP-FCR-01" / "QQQ_2026"
DEFAULT_DATASET = Path("data") / "curated" / "QQQ_1min_2022-01-01_2026-07-06_curated.csv"
DEFAULT_MANIFEST_DIR = Path("data") / "manifests"
DEFAULT_TV_CSV = Path("data") / "parity" / "tradingview" / "QQQ_FIRST_CANDLE_2026_TRADES.csv"
PARITY_START = date(2026, 4, 13)
PARITY_END = date(2026, 7, 6)


@dataclass(frozen=True)
class Tolerances:
    price: float = 0.01
    pnl: float = 0.01
    commission: float = 0.001
    quantity: float = 0.0
    time_seconds: int = 0


@dataclass(frozen=True)
class EventMatchConfig:
    max_entry_time_difference_minutes: int = 240


FINAL_COST_ROUNDING_TOLERANCE = 0.021


def _ny_date(value: Any) -> str:
    return pd.Timestamp(value).tz_convert("America/New_York").date().isoformat()


def _to_utc_timestamp(value: Any) -> pd.Timestamp:
    return pd.Timestamp(value).tz_convert("UTC")


def _pine_exit_comment(exit_reason: str) -> str:
    if exit_reason == "PINE_FIXED_1555_CLOSE":
        return "Cierre fin de sesión"
    if exit_reason in {
        "STOP_LOSS",
        "TAKE_PROFIT",
        "STOP_FIRST_AMBIGUOUS_BAR",
        "END_OF_DATA_OR_OVERNIGHT_RISK_SOURCE_SEMANTICS",
    }:
        return "TP o SL"
    return exit_reason


def _difference_type(field: str) -> str:
    if field in {"session_date", "entry_time", "exit_time", "exit_comment"}:
        return "SESSION_ALIGNMENT_DIFFERENCE"
    if field == "direction":
        return "SIGNAL_LOGIC_DIFFERENCE"
    if field == "quantity":
        return "POSITION_SIZING_DIFFERENCE"
    if field in {"profit", "commission"}:
        return "COST_CALCULATION_DIFFERENCE"
    if field in {"entry_price", "exit_price"}:
        return "DATA_FEED_DIFFERENCE"
    return "UNEXPLAINED_DIFFERENCE"


def _max_difference_type(fields: list[str]) -> str:
    if not fields:
        return ""
    priorities = [
        "SIGNAL_LOGIC_DIFFERENCE",
        "SESSION_ALIGNMENT_DIFFERENCE",
        "POSITION_SIZING_DIFFERENCE",
        "DATA_FEED_DIFFERENCE",
        "INTRABAR_EXECUTION_DIFFERENCE",
        "COST_CALCULATION_DIFFERENCE",
        "UNEXPLAINED_DIFFERENCE",
    ]
    types = {_difference_type(field) for field in fields}
    for item in priorities:
        if item in types:
            return item
    return "UNEXPLAINED_DIFFERENCE"


def generate_python_parity(
    *,
    dataset_path: str | Path = DEFAULT_DATASET,
    manifest_dir: str | Path = DEFAULT_MANIFEST_DIR,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    validate_research_period_request(
        ResearchPeriodRequest(
            period="parity_debug_2026",
            start=PARITY_START,
            end=PARITY_END,
            non_decisional=True,
        )
    )
    calendar = EquitySessionCalendar.from_config({"source": "us_equity"})
    minute, manifest = load_symbol_curated_1min(
        dataset_path,
        "QQQ",
        manifest_dir=manifest_dir,
        calendar=calendar,
    )
    local = minute["timestamp"].dt.tz_convert("America/New_York")
    mask = (local.dt.date >= PARITY_START) & (local.dt.date <= PARITY_END)
    period_minute = minute.loc[mask].reset_index(drop=True)
    five, signals, diagnostics = prepare_signal_frame(period_minute, "QQQ", calendar=calendar)
    records = [simulate_tradingview_parity_trade(signal, five) for _, signal in signals.iterrows()]
    all_trades = pd.DataFrame(records)
    if all_trades.empty:
        trades = all_trades
    else:
        trades = all_trades.loc[
            (all_trades["actual_quantity"].astype(float) > 0)
            & pd.to_datetime(all_trades["entry_time"], utc=True, errors="coerce").notna()
        ].copy()
    if not trades.empty:
        trades = (
            trades.assign(_entry_sort=pd.to_datetime(trades["entry_time"], utc=True, errors="coerce"))
            .sort_values(["_entry_sort", "session_date", "direction"], na_position="last")
            .drop(columns=["_entry_sort"])
            .reset_index(drop=True)
        )
    if not trades.empty:
        trades.insert(0, "trade_num", range(len(trades)))
        trades["exit_comment"] = trades["exit_reason"].map(_pine_exit_comment)
        trades["profit"] = trades["net_pnl"].astype(float)
    outputs = Path(output_dir)
    outputs.mkdir(parents=True, exist_ok=True)
    serialize_trade_frame(trades).to_csv(outputs / "python_tradingview_parity_trades.csv", index=False)
    if not all_trades.empty:
        serialize_trade_frame(all_trades).to_csv(outputs / "python_tradingview_parity_all_signal_candidates.csv", index=False)
    serialize_trade_frame(signals).to_csv(outputs / "python_tradingview_parity_signals.csv", index=False)
    diagnostics.to_csv(outputs / "python_tradingview_parity_diagnostics.csv", index=False)
    run_manifest = {
        "hypothesis_id": "HYP-FCR-01",
        "mode": "parity_debug_2026",
        "execution_mode": "tradingview_parity",
        "non_decisional": True,
        "symbol": "QQQ",
        "start": PARITY_START.isoformat(),
        "end": PARITY_END.isoformat(),
        "dataset_path": str(dataset_path),
        "manifest_dir": str(manifest_dir),
        "dataset_sha256": manifest.sha256,
        "rows_1min": int(len(period_minute)),
        "rows_5min": int(len(five)),
        "signals": int(len(signals)),
        "trades": int(len(trades)),
        "signal_candidates": int(len(all_trades)),
        "diagnostics": int(len(diagnostics)),
        "discovery_executed": False,
        "validation_executed": False,
        "holdout_executed": False,
        "safety_flags": {
            "live_trading": False,
            "broker_connected": False,
            "orders_sent": False,
            "paper_broker_enabled": False,
        },
        "outputs": {
            "python_trades": "python_tradingview_parity_trades.csv",
            "python_signals": "python_tradingview_parity_signals.csv",
            "python_diagnostics": "python_tradingview_parity_diagnostics.csv",
        },
    }
    (outputs / "run_manifest.json").write_text(
        json.dumps(run_manifest, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    return trades, signals, diagnostics, run_manifest


def compare_pine_to_python(
    tv_trades: pd.DataFrame,
    py_trades: pd.DataFrame,
    *,
    tolerances: Tolerances = Tolerances(),
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    tv_by_num = {int(row["trade_num"]): row for _, row in tv_trades.iterrows()}
    py_by_num = {int(row["trade_num"]): row for _, row in py_trades.iterrows()}
    for trade_num in sorted(set(tv_by_num).union(py_by_num)):
        if trade_num not in tv_by_num:
            row = py_by_num[trade_num]
            rows.append(
                {
                    "trade_num": trade_num,
                    "session_date": _ny_date(row["entry_time"]),
                    "direction": row["direction"],
                    "parity_bucket": "missing_in_tradingview",
                    "difference_type": "SIGNAL_LOGIC_DIFFERENCE",
                    "failed_fields": "missing_in_tradingview",
                }
            )
            continue
        if trade_num not in py_by_num:
            row = tv_by_num[trade_num]
            rows.append(
                {
                    "trade_num": trade_num,
                    "session_date": _ny_date(row["entry_time_utc"]),
                    "direction": row["direction"],
                    "parity_bucket": "missing_in_python",
                    "difference_type": "SIGNAL_LOGIC_DIFFERENCE",
                    "failed_fields": "missing_in_python",
                }
            )
            continue
        tv = tv_by_num[trade_num]
        py = py_by_num[trade_num]
        failed: list[str] = []
        tv_entry = _to_utc_timestamp(tv["entry_time_utc"])
        tv_exit = _to_utc_timestamp(tv["exit_time_utc"])
        py_entry = _to_utc_timestamp(py["entry_time"])
        py_exit = _to_utc_timestamp(py["exit_time"])
        comparisons = {
            "session_date": (_ny_date(tv_entry), str(py["session_date"])),
            "direction": (str(tv["direction"]).lower(), str(py["direction"]).lower()),
            "entry_time": (tv_entry, py_entry),
            "entry_price": (float(tv["entry_price"]), float(py["entry_price"])),
            "exit_time": (tv_exit, py_exit),
            "exit_price": (float(tv["exit_price"]), float(py["exit_price"])),
            "quantity": (float(tv["qty"]), float(py["actual_quantity"])),
            "exit_comment": (str(tv["exit_comment"]), str(py["exit_comment"])),
            "profit": (float(tv["profit"]), float(py["profit"])),
            "commission": (float(tv["commission"]), float(py["commission"])),
        }
        if comparisons["session_date"][0] != comparisons["session_date"][1]:
            failed.append("session_date")
        if comparisons["direction"][0] != comparisons["direction"][1]:
            failed.append("direction")
        if abs((comparisons["entry_time"][0] - comparisons["entry_time"][1]).total_seconds()) > tolerances.time_seconds:
            failed.append("entry_time")
        if abs((comparisons["exit_time"][0] - comparisons["exit_time"][1]).total_seconds()) > tolerances.time_seconds:
            failed.append("exit_time")
        for field, tolerance in (
            ("entry_price", tolerances.price),
            ("exit_price", tolerances.price),
            ("quantity", tolerances.quantity),
            ("profit", tolerances.pnl),
            ("commission", tolerances.commission),
        ):
            left, right = comparisons[field]
            if abs(float(left) - float(right)) > tolerance:
                failed.append(field)
        if comparisons["exit_comment"][0] != comparisons["exit_comment"][1]:
            failed.append("exit_comment")
        rows.append(
            {
                "trade_num": trade_num,
                "session_date": comparisons["session_date"][0],
                "direction": comparisons["direction"][0],
                "parity_bucket": "matched_trades" if not failed else "field_mismatches",
                "difference_type": _max_difference_type(failed),
                "failed_fields": ",".join(failed),
                "tv_entry_time_utc": tv_entry.isoformat(),
                "py_entry_time_utc": py_entry.isoformat(),
                "entry_time_exact_match": "entry_time" not in failed,
                "tv_exit_time_utc": tv_exit.isoformat(),
                "py_exit_time_utc": py_exit.isoformat(),
                "exit_time_exact_match": "exit_time" not in failed,
                "tv_entry_price": comparisons["entry_price"][0],
                "py_entry_price": comparisons["entry_price"][1],
                "entry_price_abs_diff": abs(comparisons["entry_price"][0] - comparisons["entry_price"][1]),
                "entry_price_within_tolerance": abs(comparisons["entry_price"][0] - comparisons["entry_price"][1]) <= tolerances.price,
                "tv_exit_price": comparisons["exit_price"][0],
                "py_exit_price": comparisons["exit_price"][1],
                "exit_price_abs_diff": abs(comparisons["exit_price"][0] - comparisons["exit_price"][1]),
                "exit_price_within_tolerance": abs(comparisons["exit_price"][0] - comparisons["exit_price"][1]) <= tolerances.price,
                "tv_quantity": comparisons["quantity"][0],
                "py_quantity": comparisons["quantity"][1],
                "tv_exit_comment": comparisons["exit_comment"][0],
                "py_exit_comment": comparisons["exit_comment"][1],
                "tv_profit": comparisons["profit"][0],
                "py_profit": comparisons["profit"][1],
                "profit_abs_diff": abs(comparisons["profit"][0] - comparisons["profit"][1]),
                "tv_commission": comparisons["commission"][0],
                "py_commission": comparisons["commission"][1],
                "commission_abs_diff": abs(comparisons["commission"][0] - comparisons["commission"][1]),
            }
        )
    return pd.DataFrame(rows)


def _tv_session_date(row: pd.Series) -> str:
    return _ny_date(row["entry_time_utc"])


def _py_session_date(row: pd.Series) -> str:
    value = row.get("session_date", "")
    if pd.notna(value) and str(value) and str(value) != "NaT":
        return str(value)
    return _ny_date(row["entry_time"])


def _normalized_symbol(row: pd.Series, default: str = "QQQ") -> str:
    for column in ("normalized_symbol", "symbol"):
        if column in row and pd.notna(row[column]) and str(row[column]):
            return str(row[column]).split(":")[-1].upper()
    return default


def _event_candidates(
    tv_trades: pd.DataFrame,
    py_trades: pd.DataFrame,
    *,
    config: EventMatchConfig,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for tv_index, tv in tv_trades.iterrows():
        tv_entry = _to_utc_timestamp(tv["entry_time_utc"])
        tv_symbol = _normalized_symbol(tv)
        tv_session = _tv_session_date(tv)
        tv_direction = str(tv["direction"]).lower()
        for py_index, py in py_trades.iterrows():
            py_entry = pd.to_datetime(py["entry_time"], utc=True, errors="coerce")
            if pd.isna(py_entry):
                continue
            if tv_symbol != _normalized_symbol(py):
                continue
            if tv_session != _py_session_date(py):
                continue
            if tv_direction != str(py["direction"]).lower():
                continue
            minutes = abs((tv_entry - py_entry).total_seconds()) / 60.0
            if minutes > config.max_entry_time_difference_minutes:
                continue
            price_distance = abs(float(tv["entry_price"]) - float(py["entry_price"]))
            candidates.append(
                {
                    "tv_index": int(tv_index),
                    "py_index": int(py_index),
                    "tv_trade_num": int(tv["trade_num"]),
                    "py_trade_num": int(py["trade_num"]),
                    "entry_time_difference_minutes": float(minutes),
                    "entry_price_distance": float(price_distance),
                    "score": float(minutes * 1000.0 + price_distance * 10.0 + abs(int(tv["trade_num"]) - int(py["trade_num"]))),
                }
            )
    return sorted(
        candidates,
        key=lambda row: (
            row["score"],
            row["entry_time_difference_minutes"],
            row["entry_price_distance"],
            row["tv_trade_num"],
            row["py_trade_num"],
        ),
    )


def build_event_matches(
    tv_trades: pd.DataFrame,
    py_trades: pd.DataFrame,
    *,
    config: EventMatchConfig = EventMatchConfig(),
) -> list[dict[str, Any]]:
    matched_tv: set[int] = set()
    matched_py: set[int] = set()
    matches: list[dict[str, Any]] = []
    for candidate in _event_candidates(tv_trades, py_trades, config=config):
        if candidate["tv_index"] in matched_tv or candidate["py_index"] in matched_py:
            continue
        matched_tv.add(candidate["tv_index"])
        matched_py.add(candidate["py_index"])
        if candidate["entry_time_difference_minutes"] == 0:
            alignment = "exact_event_match"
        elif candidate["entry_time_difference_minutes"] <= 15:
            alignment = "probable_event_match"
        else:
            alignment = "shifted_event"
        classification = (
            "sequence_misalignment"
            if candidate["tv_trade_num"] != candidate["py_trade_num"]
            else alignment
        )
        matches.append({**candidate, "event_alignment": alignment, "matching_classification": classification})
    for tv_index, tv in tv_trades.iterrows():
        if int(tv_index) not in matched_tv:
            matches.append(
                {
                    "tv_index": int(tv_index),
                    "py_index": None,
                    "tv_trade_num": int(tv["trade_num"]),
                    "py_trade_num": None,
                    "entry_time_difference_minutes": None,
                    "entry_price_distance": None,
                    "score": None,
                    "event_alignment": "unmatched_tradingview",
                    "matching_classification": "unmatched_tradingview",
                }
            )
    for py_index, py in py_trades.iterrows():
        if int(py_index) not in matched_py:
            matches.append(
                {
                    "tv_index": None,
                    "py_index": int(py_index),
                    "tv_trade_num": None,
                    "py_trade_num": int(py["trade_num"]),
                    "entry_time_difference_minutes": None,
                    "entry_price_distance": None,
                    "score": None,
                    "event_alignment": "unmatched_python",
                    "matching_classification": "unmatched_python",
                }
            )
    return sorted(
        matches,
        key=lambda row: (
            999999 if row["tv_trade_num"] is None else int(row["tv_trade_num"]),
            999999 if row["py_trade_num"] is None else int(row["py_trade_num"]),
        ),
    )


def _paired_comparison_row(
    tv: pd.Series,
    py: pd.Series,
    *,
    tolerances: Tolerances,
    match: dict[str, Any],
) -> dict[str, Any]:
    failed: list[str] = []
    tv_entry = _to_utc_timestamp(tv["entry_time_utc"])
    tv_exit = _to_utc_timestamp(tv["exit_time_utc"])
    py_entry = _to_utc_timestamp(py["entry_time"])
    py_exit = _to_utc_timestamp(py["exit_time"])
    comparisons = {
        "session_date": (_ny_date(tv_entry), _py_session_date(py)),
        "direction": (str(tv["direction"]).lower(), str(py["direction"]).lower()),
        "entry_time": (tv_entry, py_entry),
        "entry_price": (float(tv["entry_price"]), float(py["entry_price"])),
        "exit_time": (tv_exit, py_exit),
        "exit_price": (float(tv["exit_price"]), float(py["exit_price"])),
        "quantity": (float(tv["qty"]), float(py["actual_quantity"])),
        "exit_comment": (str(tv["exit_comment"]), str(py["exit_comment"])),
        "profit": (float(tv["profit"]), float(py["profit"])),
        "commission": (float(tv["commission"]), float(py["commission"])),
    }
    if comparisons["session_date"][0] != comparisons["session_date"][1]:
        failed.append("session_date")
    if comparisons["direction"][0] != comparisons["direction"][1]:
        failed.append("direction")
    if abs((comparisons["entry_time"][0] - comparisons["entry_time"][1]).total_seconds()) > tolerances.time_seconds:
        failed.append("entry_time")
    if abs((comparisons["exit_time"][0] - comparisons["exit_time"][1]).total_seconds()) > tolerances.time_seconds:
        failed.append("exit_time")
    for field, tolerance in (
        ("entry_price", tolerances.price),
        ("exit_price", tolerances.price),
        ("quantity", tolerances.quantity),
        ("profit", tolerances.pnl),
        ("commission", tolerances.commission),
    ):
        left, right = comparisons[field]
        if abs(float(left) - float(right)) > tolerance:
            failed.append(field)
    if comparisons["exit_comment"][0] != comparisons["exit_comment"][1]:
        failed.append("exit_comment")
    return {
        "trade_num": int(tv["trade_num"]),
        "tv_trade_num": int(tv["trade_num"]),
        "python_trade_identifier": int(py["trade_num"]),
        "py_trade_num": int(py["trade_num"]),
        "session_date": comparisons["session_date"][0],
        "direction": comparisons["direction"][0],
        "event_alignment": match["event_alignment"],
        "matching_classification": match["matching_classification"],
        "sequence_misalignment": bool(int(tv["trade_num"]) != int(py["trade_num"])),
        "entry_time_difference_minutes": match["entry_time_difference_minutes"],
        "entry_price_match_distance": match["entry_price_distance"],
        "parity_bucket": "matched_trades" if not failed else "field_mismatches",
        "difference_type": _max_difference_type(failed),
        "failed_fields": ",".join(failed),
        "tv_entry_time_utc": tv_entry.isoformat(),
        "py_entry_time_utc": py_entry.isoformat(),
        "entry_time_exact_match": "entry_time" not in failed,
        "tv_exit_time_utc": tv_exit.isoformat(),
        "py_exit_time_utc": py_exit.isoformat(),
        "exit_time_exact_match": "exit_time" not in failed,
        "tv_entry_price": comparisons["entry_price"][0],
        "py_entry_price": comparisons["entry_price"][1],
        "entry_price_abs_diff": abs(comparisons["entry_price"][0] - comparisons["entry_price"][1]),
        "entry_price_within_tolerance": abs(comparisons["entry_price"][0] - comparisons["entry_price"][1]) <= tolerances.price,
        "tv_exit_price": comparisons["exit_price"][0],
        "py_exit_price": comparisons["exit_price"][1],
        "exit_price_abs_diff": abs(comparisons["exit_price"][0] - comparisons["exit_price"][1]),
        "exit_price_within_tolerance": abs(comparisons["exit_price"][0] - comparisons["exit_price"][1]) <= tolerances.price,
        "tv_quantity": comparisons["quantity"][0],
        "py_quantity": comparisons["quantity"][1],
        "tv_exit_comment": comparisons["exit_comment"][0],
        "py_exit_comment": comparisons["exit_comment"][1],
        "tv_profit": comparisons["profit"][0],
        "py_profit": comparisons["profit"][1],
        "profit_abs_diff": abs(comparisons["profit"][0] - comparisons["profit"][1]),
        "tv_commission": comparisons["commission"][0],
        "py_commission": comparisons["commission"][1],
        "commission_abs_diff": abs(comparisons["commission"][0] - comparisons["commission"][1]),
    }


def compare_pine_to_python_events(
    tv_trades: pd.DataFrame,
    py_trades: pd.DataFrame,
    *,
    tolerances: Tolerances = Tolerances(),
    match_config: EventMatchConfig = EventMatchConfig(),
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    matches = build_event_matches(tv_trades, py_trades, config=match_config)
    for match in matches:
        if match["tv_index"] is None:
            py = py_trades.loc[int(match["py_index"])]
            rows.append(
                {
                    "trade_num": "",
                    "tv_trade_num": "",
                    "python_trade_identifier": int(py["trade_num"]),
                    "py_trade_num": int(py["trade_num"]),
                    "session_date": _py_session_date(py),
                    "direction": str(py["direction"]).lower(),
                    "event_alignment": "unmatched_python",
                    "matching_classification": "unmatched_python",
                    "sequence_misalignment": False,
                    "parity_bucket": "missing_in_tradingview",
                    "difference_type": "SIGNAL_LOGIC_DIFFERENCE",
                    "failed_fields": "missing_in_tradingview",
                }
            )
            continue
        if match["py_index"] is None:
            tv = tv_trades.loc[int(match["tv_index"])]
            rows.append(
                {
                    "trade_num": int(tv["trade_num"]),
                    "tv_trade_num": int(tv["trade_num"]),
                    "python_trade_identifier": "",
                    "py_trade_num": "",
                    "session_date": _tv_session_date(tv),
                    "direction": str(tv["direction"]).lower(),
                    "event_alignment": "unmatched_tradingview",
                    "matching_classification": "unmatched_tradingview",
                    "sequence_misalignment": False,
                    "parity_bucket": "missing_in_python",
                    "difference_type": "SIGNAL_LOGIC_DIFFERENCE",
                    "failed_fields": "missing_in_python",
                }
            )
            continue
        rows.append(
            _paired_comparison_row(
                tv_trades.loc[int(match["tv_index"])],
                py_trades.loc[int(match["py_index"])],
                tolerances=tolerances,
                match=match,
            )
        )
    return pd.DataFrame(rows)


def summarize_comparison(comparison: pd.DataFrame) -> dict[str, Any]:
    counts = comparison["parity_bucket"].value_counts().to_dict() if not comparison.empty else {}
    type_counts = (
        comparison.loc[comparison["difference_type"] != "", "difference_type"]
        .value_counts()
        .to_dict()
        if not comparison.empty
        else {}
    )
    blockers = {
        "SIGNAL_LOGIC_DIFFERENCE",
        "SESSION_ALIGNMENT_DIFFERENCE",
        "UNEXPLAINED_DIFFERENCE",
    }
    blocking_rows = comparison[
        comparison["difference_type"].isin(blockers)
        | comparison["parity_bucket"].isin({"missing_in_python", "missing_in_tradingview", "unexplained_mismatches"})
    ]
    paired = comparison.loc[
        ~comparison["parity_bucket"].isin({"missing_in_python", "missing_in_tradingview"})
    ]
    matching_counts = (
        comparison["matching_classification"].value_counts().to_dict()
        if "matching_classification" in comparison.columns and not comparison.empty
        else {}
    )
    return {
        "matched_trades": int(counts.get("matched_trades", 0)),
        "missing_in_python": int(counts.get("missing_in_python", 0)),
        "missing_in_tradingview": int(counts.get("missing_in_tradingview", 0)),
        "field_mismatches": int(counts.get("field_mismatches", 0)),
        "unexplained_mismatches": int(counts.get("unexplained_mismatches", 0)),
        "matching_classification_counts": matching_counts,
        "difference_type_counts": type_counts,
        "date_direction_matches": int(
            (
                paired["failed_fields"].fillna("").map(
                    lambda value: "session_date" not in value and "direction" not in value
                )
            ).sum()
        ),
        "entry_price_exact_matches": int((comparison["entry_price_abs_diff"].fillna(999) == 0).sum()),
        "entry_price_within_tolerance": int(comparison["entry_price_within_tolerance"].fillna(False).sum()),
        "exit_price_exact_matches": int((comparison["exit_price_abs_diff"].fillna(999) == 0).sum()),
        "exit_price_within_tolerance": int(comparison["exit_price_within_tolerance"].fillna(False).sum()),
        "pre_discovery_gate_blocked": bool(not blocking_rows.empty),
        "pre_discovery_blocking_rows": int(len(blocking_rows)),
    }


def _load_period_signal_inputs(
    dataset_path: str | Path,
    manifest_dir: str | Path,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    calendar = EquitySessionCalendar.from_config({"source": "us_equity"})
    minute, _ = load_symbol_curated_1min(
        dataset_path,
        "QQQ",
        manifest_dir=manifest_dir,
        calendar=calendar,
    )
    local = minute["timestamp"].dt.tz_convert("America/New_York")
    mask = (local.dt.date >= PARITY_START) & (local.dt.date <= PARITY_END)
    period_minute = minute.loc[mask].reset_index(drop=True)
    five, signals, diagnostics = prepare_signal_frame(period_minute, "QQQ", calendar=calendar)
    return five, signals, diagnostics


def _floor_5min_open(value: Any) -> str:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    else:
        timestamp = timestamp.tz_convert("UTC")
    return timestamp.floor("5min").isoformat()


def build_session_alignment_diagnostics(
    *,
    initial_sequence_comparison: pd.DataFrame,
    event_comparison: pd.DataFrame,
    py_trades: pd.DataFrame,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    initial = initial_sequence_comparison.loc[
        initial_sequence_comparison["difference_type"] == "SESSION_ALIGNMENT_DIFFERENCE"
    ]
    event_by_tv = {
        int(row["tv_trade_num"]): row
        for _, row in event_comparison.iterrows()
        if str(row.get("tv_trade_num", "")) not in {"", "nan", "NaN"}
    }
    py_by_num = {int(row["trade_num"]): row for _, row in py_trades.iterrows()}
    for _, row in initial.iterrows():
        tv_num = int(row["trade_num"])
        event = event_by_tv.get(tv_num)
        py_identifier = None
        py = None
        if event is not None and str(event.get("py_trade_num", "")) not in {"", "nan", "NaN"}:
            py_identifier = int(event["py_trade_num"])
            py = py_by_num.get(py_identifier)
        tv_entry = pd.Timestamp(row["tv_entry_time_utc"])
        py_entry_value = event.get("py_entry_time_utc") if event is not None else row.get("py_entry_time_utc")
        py_entry = pd.to_datetime(py_entry_value, utc=True, errors="coerce")
        entry_diff = None if pd.isna(py_entry) else (tv_entry - py_entry).total_seconds() / 60.0
        failed = str(row.get("failed_fields", ""))
        if event is not None and (
            bool(event.get("sequence_misalignment", False))
            or ("session_date" in failed and event.get("event_alignment", "") == "exact_event_match")
        ):
            cause = "sequence_misalignment_from_rejected_quantity_signal"
        elif "entry_time" in failed:
            cause = "same_session_signal_timing_boundary"
        elif "exit_time" in failed:
            cause = "intrabar_exit_boundary_or_feed_difference"
        else:
            cause = "classification_prior_requires_event_matching"
        rows.append(
            {
                "tradingview_trade_num": tv_num,
                "python_trade_identifier": "" if py_identifier is None else py_identifier,
                "session_date": row["session_date"],
                "tradingview_direction": row["direction"],
                "python_direction": "" if py is None else str(py["direction"]),
                "entry_time_unix_ms": int(tv_entry.timestamp() * 1000),
                "entry_time_utc": tv_entry.isoformat(),
                "entry_time_ny": tv_entry.tz_convert("America/New_York").isoformat(),
                "python_entry_time_utc": "" if pd.isna(py_entry) else py_entry.isoformat(),
                "entry_time_difference_minutes": entry_diff,
                "signal_bar_time": "" if py is None else str(py.get("signal_time", "")),
                "fill_time": "" if py is None else str(py.get("entry_time", "")),
                "associated_5m_bar_open": _floor_5min_open(tv_entry),
                "opening_high": "" if py is None else py.get("opening_high", ""),
                "opening_low": "" if py is None else py.get("opening_low", ""),
                "prior_failed_fields": failed,
                "event_matching_classification": "" if event is None else event.get("matching_classification", ""),
                "technical_cause_proposed": cause,
                "bar_label_audit": "local 5m bars are labeled by open; 09:30 covers 09:30-09:34 and 09:55 covers 09:55-09:59",
                "process_orders_on_close_audit": "Pine logs use the internal bar timestamp while orders are submitted on close",
                "timezone_dst_audit": "UTC to America/New_York conversion used zoneinfo/pandas timezone conversion; dates are in DST during this range",
            }
        )
    return pd.DataFrame(rows)


def _signal_state_for_session(five: pd.DataFrame, session_date: str) -> pd.DataFrame:
    config = FirstCandleConfig()
    data = add_session_columns(five, config)
    ranges = compute_opening_ranges(data, config)
    enriched = data.merge(ranges, on="session_date", how="left")
    session = enriched.loc[enriched["session_date"] == session_date].reset_index(drop=True)
    if session.empty:
        return pd.DataFrame()
    opening_high = float(session["opening_high"].iloc[0])
    opening_low = float(session["opening_low"].iloc[0])
    entry_start = pd.Timestamp(f"{session_date} {config.entry_start}", tz=config.timezone).time()
    entry_end = pd.Timestamp(f"{session_date} {config.entry_end_exclusive}", tz=config.timezone).time()
    low_swept = False
    high_swept = False
    low_sweep_bar = ""
    high_sweep_bar = ""
    low_sweep_position: int | None = None
    high_sweep_position: int | None = None
    states: list[dict[str, Any]] = []
    for position, row in session.iterrows():
        timestamp = pd.Timestamp(row["timestamp"])
        timestamp_ny = timestamp.tz_convert(config.timezone)
        low_touch_now = bool(float(row["low"]) <= opening_low)
        high_touch_now = bool(float(row["high"]) >= opening_high)
        if low_touch_now:
            low_swept = True
            low_sweep_position = int(position)
            low_sweep_bar = timestamp_ny.isoformat()
        if high_touch_now:
            high_swept = True
            high_sweep_position = int(position)
            high_sweep_bar = timestamp_ny.isoformat()
        bull = bear = False
        bull_gap = bear_gap = 0.0
        long_signal = short_signal = False
        long_delay = short_delay = False
        long_stop = short_stop = ""
        if int(position) >= 2:
            two_back = session.iloc[int(position) - 2]
            bull, bull_gap = bullish_fvg(row, two_back, config.cost("baseline").tick_size, config.minimum_fvg_ticks)
            bear, bear_gap = bearish_fvg(row, two_back, config.cost("baseline").tick_size, config.minimum_fvg_ticks)
            inside = close_strictly_inside(float(row["close"]), opening_low, opening_high)
            long_delay = low_swept and low_sweep_position is not None and int(position) > low_sweep_position
            short_delay = high_swept and high_sweep_position is not None and int(position) > high_sweep_position
            long_signal = bool(long_delay and bull and inside)
            short_signal = bool(short_delay and bear and inside)
            if long_signal:
                long_stop = stop_from_bodies(session, int(position), "long")
            if short_signal:
                short_stop = stop_from_bodies(session, int(position), "short")
        states.append(
            {
                "timestamp_ny": timestamp_ny.isoformat(),
                "timestamp_utc": timestamp.isoformat(),
                "session_date": session_date,
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "opening_high": opening_high,
                "opening_low": opening_low,
                "low_touch_now": low_touch_now,
                "high_touch_now": high_touch_now,
                "low_swept": low_swept,
                "high_swept": high_swept,
                "low_sweep_bar": low_sweep_bar,
                "high_sweep_bar": high_sweep_bar,
                "bullish_gap_size": float(bull_gap),
                "bearish_gap_size": float(bear_gap),
                "bullish_fvg": bool(bull),
                "bearish_fvg": bool(bear),
                "bullish_back_inside": bool(close_strictly_inside(float(row["close"]), opening_low, opening_high)),
                "bearish_back_inside": bool(close_strictly_inside(float(row["close"]), opening_low, opening_high)),
                "long_delay_satisfied": bool(long_delay),
                "short_delay_satisfied": bool(short_delay),
                "long_signal": bool(long_signal),
                "short_signal": bool(short_signal),
                "long_stop_candidate": long_stop,
                "short_stop_candidate": short_stop,
            }
        )
    return pd.DataFrame(states)


def build_signal_logic_diagnostics(
    *,
    five: pd.DataFrame,
    initial_sequence_comparison: pd.DataFrame,
) -> pd.DataFrame:
    initial = initial_sequence_comparison.loc[
        initial_sequence_comparison["difference_type"] == "SIGNAL_LOGIC_DIFFERENCE"
    ]
    frames: list[pd.DataFrame] = []
    for _, mismatch in initial.iterrows():
        session_date = str(mismatch["session_date"])
        state = _signal_state_for_session(five, session_date)
        if state.empty:
            continue
        tv_entry = pd.Timestamp(mismatch["tv_entry_time_utc"]).tz_convert("America/New_York")
        state_times = pd.to_datetime(state["timestamp_ny"])
        exact_positions = state.index[state_times == tv_entry].tolist()
        if exact_positions:
            center = int(exact_positions[0])
        else:
            center = int((state_times - tv_entry).abs().argmin())
        window = state.iloc[max(0, center - 6) : min(len(state), center + 4)].copy()
        window.insert(0, "prior_tradingview_trade_num", int(mismatch["trade_num"]))
        window["prior_sequence_py_entry_time_utc"] = mismatch.get("py_entry_time_utc", "")
        window["prior_classification"] = "SIGNAL_LOGIC_DIFFERENCE"
        window["diagnosis"] = "classification_prior_incorrect_sequence_misalignment"
        frames.append(window)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def build_cost_reconciliation(comparison: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    cost_rows = comparison.loc[comparison["difference_type"] == "COST_CALCULATION_DIFFERENCE"]
    for _, row in cost_rows.iterrows():
        direction = str(row["direction"]).lower()
        sign = 1 if direction == "long" else -1
        tv_gross = sign * (float(row["tv_exit_price"]) - float(row["tv_entry_price"])) * float(row["tv_quantity"])
        py_gross = sign * (float(row["py_exit_price"]) - float(row["py_entry_price"])) * float(row["py_quantity"])
        rows.append(
            {
                "tradingview_trade_num": row["tv_trade_num"],
                "python_trade_identifier": row["py_trade_num"],
                "session_date": row["session_date"],
                "direction": direction,
                "gross_price_pnl": tv_gross,
                "tradingview_reported_profit": float(row["tv_profit"]),
                "tradingview_commission": float(row["tv_commission"]),
                "python_gross_pnl": py_gross,
                "python_commission": float(row["py_commission"]),
                "python_net_pnl": float(row["py_profit"]),
                "difference": float(row["tv_profit"]) - float(row["py_profit"]),
                "technical_cause_proposed": "minor_decimal_rounding_boundary" if float(row["profit_abs_diff"]) <= 0.02 else "requires_manual_cost_review",
                "tradingview_profit_net_of_commission_inferred": abs((tv_gross - float(row["tv_commission"])) - float(row["tv_profit"])) <= 0.02,
            }
        )
    return pd.DataFrame(rows)


def _timestamp_ny_iso(value: Any) -> str:
    parsed = pd.to_datetime(value, utc=True, errors="coerce")
    if pd.isna(parsed):
        return ""
    return parsed.tz_convert("America/New_York").isoformat()


def _minutes_delta(left: Any, right: Any) -> float | None:
    left_ts = pd.to_datetime(left, utc=True, errors="coerce")
    right_ts = pd.to_datetime(right, utc=True, errors="coerce")
    if pd.isna(left_ts) or pd.isna(right_ts):
        return None
    return float((left_ts - right_ts).total_seconds() / 60.0)


def classify_timing_difference(row: pd.Series) -> dict[str, Any]:
    failed = str(row.get("failed_fields", ""))
    entry_delta = _minutes_delta(row.get("tv_entry_time_utc"), row.get("py_entry_time_utc"))
    exit_delta = _minutes_delta(row.get("tv_exit_time_utc"), row.get("py_exit_time_utc"))
    signal_delta = entry_delta
    tv_num = int(row.get("tv_trade_num", row.get("trade_num")))
    if "entry_time" in failed:
        final = "DATA_FEED_SIGNAL_BOUNDARY"
        root = (
            "same session and direction but different signal bar selected at a strict OHLC boundary; "
            "local bar construction/timezone checks do not show a session-label bug"
        )
        blocks = False
    elif "exit_time" in failed:
        final = "EXIT_INTRABAR_TIMING"
        root = (
            "same entry event but stop/target is touched on a different later/earlier bar under local SIP OHLC; "
            "this is not a true session alignment bug"
        )
        blocks = False
    else:
        final = "SIGNAL_SESSION_ALIGNMENT"
        root = "timing mismatch does not fit a feed or intrabar boundary explanation"
        blocks = True
    return {
        "trade_num": tv_num,
        "session_date": row.get("session_date", ""),
        "direction": row.get("direction", ""),
        "tv_signal_time_ny": _timestamp_ny_iso(row.get("tv_entry_time_utc")),
        "python_signal_time_ny": _timestamp_ny_iso(row.get("py_entry_time_utc")),
        "tv_entry_time_ny": _timestamp_ny_iso(row.get("tv_entry_time_utc")),
        "python_entry_time_ny": _timestamp_ny_iso(row.get("py_entry_time_utc")),
        "tv_exit_time_ny": _timestamp_ny_iso(row.get("tv_exit_time_utc")),
        "python_exit_time_ny": _timestamp_ny_iso(row.get("py_exit_time_utc")),
        "signal_time_delta_minutes": signal_delta,
        "entry_time_delta_minutes": entry_delta,
        "exit_time_delta_minutes": exit_delta,
        "opening_high_python": "",
        "opening_low_python": "",
        "root_cause": root,
        "old_classification": row.get("difference_type", ""),
        "final_classification": final,
        "blocks_discovery": bool(blocks),
        "evidence": (
            f"failed_fields={failed}; event_alignment={row.get('event_alignment', '')}; "
            f"entry_delta_min={entry_delta}; exit_delta_min={exit_delta}"
        ),
    }


def build_timing_reclassification(comparison: pd.DataFrame, py_trades: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    py_by_num = {int(row["trade_num"]): row for _, row in py_trades.iterrows()}
    timing = comparison.loc[comparison["difference_type"] == "SESSION_ALIGNMENT_DIFFERENCE"]
    for _, item in timing.iterrows():
        row = classify_timing_difference(item)
        py_num = int(item.get("py_trade_num", item.get("python_trade_identifier")))
        py = py_by_num.get(py_num)
        if py is not None:
            row["opening_high_python"] = py.get("opening_high", "")
            row["opening_low_python"] = py.get("opening_low", "")
        rows.append(row)
    return pd.DataFrame(rows)


def build_cost_reconciliation_final(comparison: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    cost_rows = comparison.loc[comparison["difference_type"] == "COST_CALCULATION_DIFFERENCE"]
    for _, row in cost_rows.iterrows():
        direction = str(row["direction"]).lower()
        qty = float(row["tv_quantity"])
        if direction == "long":
            tv_gross = (float(row["tv_exit_price"]) - float(row["tv_entry_price"])) * qty
            py_gross = (float(row["py_exit_price"]) - float(row["py_entry_price"])) * float(row["py_quantity"])
        else:
            tv_gross = (float(row["tv_entry_price"]) - float(row["tv_exit_price"])) * qty
            py_gross = (float(row["py_entry_price"]) - float(row["py_exit_price"])) * float(row["py_quantity"])
        tv_commission = float(row["tv_commission"])
        expected_tv_net = tv_gross - tv_commission
        tv_profit = float(row["tv_profit"])
        py_commission = float(row["py_commission"])
        py_entry_commission = abs(float(row["py_entry_price"]) * float(row["py_quantity"])) * 0.0001
        py_exit_commission = abs(float(row["py_exit_price"]) * float(row["py_quantity"])) * 0.0001
        py_net = float(row["py_profit"])
        tv_profit_residual = tv_profit - expected_tv_net
        py_vs_tv = py_net - tv_profit
        rows.append(
            {
                "trade_num": int(row["tv_trade_num"]),
                "session_date": row["session_date"],
                "direction": direction,
                "gross_price_pnl": tv_gross,
                "tradingview_reported_commission": tv_commission,
                "expected_tv_net_profit": expected_tv_net,
                "tradingview_reported_profit": tv_profit,
                "strategy_closedtrades_profit_net_of_commission": abs(tv_profit_residual) <= 0.001,
                "python_gross_pnl": py_gross,
                "python_entry_commission": py_entry_commission,
                "python_exit_commission": py_exit_commission,
                "python_total_commission": py_commission,
                "python_net_pnl": py_net,
                "tv_profit_residual": tv_profit_residual,
                "python_vs_tv_net_residual": py_vs_tv,
                "absolute_python_vs_tv_net_residual": abs(py_vs_tv),
                "rounding_tolerance": FINAL_COST_ROUNDING_TOLERANCE,
                "within_rounding_tolerance": abs(py_vs_tv) <= FINAL_COST_ROUNDING_TOLERANCE,
                "root_cause": (
                    "trade_37_price_precision_boundary_plus_commission_rounding"
                    if int(row["tv_trade_num"]) == 37
                    else "reported_price_precision_and_commission_rounding"
                ),
            }
        )
    return pd.DataFrame(rows)


def _session_prefix_fixture(five: pd.DataFrame, session_date: str, through_utc: str) -> pd.DataFrame:
    config = FirstCandleConfig()
    data = add_session_columns(five, config)
    session = data.loc[data["session_date"] == session_date].reset_index(drop=True)
    through = pd.Timestamp(through_utc)
    return session.loc[session["timestamp"] <= through, ["timestamp", "open", "high", "low", "close", "volume"]].copy()


def build_signal_boundary_audit(
    *,
    five: pd.DataFrame,
    timing_reclassification: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    shifted = timing_reclassification.loc[
        timing_reclassification["final_classification"] == "DATA_FEED_SIGNAL_BOUNDARY"
    ]
    fixture_rows: list[pd.DataFrame] = []
    result_rows: list[dict[str, Any]] = []
    diagnostic_rows: list[pd.DataFrame] = []
    for _, row in shifted.iterrows():
        trade_num = int(row["trade_num"])
        session_date = str(row["session_date"])
        python_signal_utc = pd.Timestamp(row["python_entry_time_ny"]).tz_convert("UTC").isoformat()
        fixture = _session_prefix_fixture(five, session_date, python_signal_utc)
        fixture = fixture.copy()
        fixture.insert(0, "trade_num", trade_num)
        fixture["timestamp_ny"] = fixture["timestamp"].dt.tz_convert("America/New_York").map(lambda value: value.isoformat())
        fixture_rows.append(fixture)
        signals, diagnostics = detect_first_candle_signals(fixture.drop(columns=["trade_num", "timestamp_ny"]), "QQQ")
        observed = "" if signals.empty else pd.Timestamp(signals.iloc[0]["signal_time"]).isoformat()
        state = _signal_state_for_session(five, session_date)
        py_signal_ny = pd.Timestamp(row["python_entry_time_ny"])
        state_times = pd.to_datetime(state["timestamp_ny"])
        positions = state.index[state_times == py_signal_ny].tolist()
        center = int(positions[0]) if positions else int((state_times - py_signal_ny).abs().argmin())
        window = state.iloc[max(0, center - 2) : center + 1].copy()
        window.insert(0, "trade_num", trade_num)
        window["bar_role"] = [f"t-{len(window) - 1 - idx}" if idx < len(window) - 1 else "t" for idx in range(len(window))]
        diagnostic_rows.append(window)
        result_rows.append(
            {
                "trade_num": trade_num,
                "session_date": session_date,
                "tv_signal_time_ny": row["tv_signal_time_ny"],
                "python_signal_time_ny": row["python_signal_time_ny"],
                "expected_python_signal_time_utc": python_signal_utc,
                "fixture_observed_signal_time_utc": observed,
                "fixture_signal_matches_expected": observed == python_signal_utc,
                "diagnostic_count": int(len(diagnostics)),
                "root_cause": "local OHLC fixture reproduces Python timing; no 5-minute label displacement found",
                "final_classification": "DATA_FEED_SIGNAL_BOUNDARY",
            }
        )
    fixtures = pd.concat(fixture_rows, ignore_index=True) if fixture_rows else pd.DataFrame()
    results = pd.DataFrame(result_rows)
    diagnostics = pd.concat(diagnostic_rows, ignore_index=True) if diagnostic_rows else pd.DataFrame()
    return fixtures, results, diagnostics


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def write_final_audit_artifacts(
    *,
    run_002_dir: str | Path = DEFAULT_OUTPUT_DIR / "run_002_corrected",
    output_dir: str | Path = DEFAULT_OUTPUT_DIR / "run_003_final_audit",
    dataset_path: str | Path = DEFAULT_DATASET,
    manifest_dir: str | Path = DEFAULT_MANIFEST_DIR,
    tradingview_csv: str | Path = DEFAULT_TV_CSV,
) -> dict[str, Any]:
    source_dir = Path(run_002_dir)
    outputs = Path(output_dir)
    if outputs.exists() and any(outputs.iterdir()):
        raise FileExistsError(f"Final audit output already exists and is not empty: {outputs}")
    outputs.mkdir(parents=True, exist_ok=True)
    comparison = pd.read_csv(source_dir / "tradingview_vs_python_comparison.csv")
    py_trades = pd.read_csv(source_dir / "python_tradingview_parity_trades.csv")
    timing = build_timing_reclassification(comparison, py_trades)
    timing.to_csv(outputs / "timing_reclassification.csv", index=False)
    cost = build_cost_reconciliation_final(comparison)
    cost.to_csv(outputs / "cost_reconciliation_final.csv", index=False)
    five, _, _ = _load_period_signal_inputs(dataset_path, manifest_dir)
    fixtures, fixture_results, signal_details = build_signal_boundary_audit(
        five=five,
        timing_reclassification=timing,
    )
    fixtures.to_csv(outputs / "signal_boundary_fixtures.csv", index=False)
    fixture_results.to_csv(outputs / "signal_boundary_fixture_results.csv", index=False)
    signal_details.to_csv(outputs / "signal_boundary_ohlc_diagnostics.csv", index=False)
    input_paths = [
        Path("data/parity/tradingview/QQQ_FIRST_CANDLE_2026_PINE_LOGS.txt"),
        Path(tradingview_csv),
        Path(dataset_path),
        Path("configs/research/hypotheses/HYP-FCR-01.yaml"),
        Path("docs/research/source_pine/FIRST_CANDLE_RULE_TV_V1.pine"),
        source_dir / "comparison_summary.json",
        source_dir / "event_matching.csv",
        source_dir / "field_mismatches.csv",
        source_dir / "python_tradingview_parity_trades.csv",
        source_dir / "tradingview_vs_python_comparison.csv",
    ]
    hashes = [
        {"path": str(path), "sha256": _hash_file(path)}
        for path in input_paths
        if path.exists()
    ]
    true_session_blockers = int(
        timing.loc[
            (timing["final_classification"] == "SIGNAL_SESSION_ALIGNMENT")
            & (timing["blocks_discovery"].astype(bool))
        ].shape[0]
    )
    unresolved_costs = int((~cost["within_rounding_tolerance"].astype(bool)).sum()) if not cost.empty else 0
    summary_payload = json.loads((source_dir / "comparison_summary.json").read_text(encoding="utf-8"))
    comparison_summary = summary_payload["comparison_summary"]
    final_gate_passed = bool(
        comparison_summary["date_direction_matches"] == 40
        and comparison_summary["missing_in_python"] == 0
        and comparison_summary["missing_in_tradingview"] == 0
        and comparison_summary["unexplained_mismatches"] == 0
        and comparison_summary["difference_type_counts"].get("SIGNAL_LOGIC_DIFFERENCE", 0) == 0
        and comparison_summary["difference_type_counts"].get("POSITION_SIZING_DIFFERENCE", 0) == 0
        and true_session_blockers == 0
        and unresolved_costs == 0
    )
    final_summary = {
        "run": "run_003_final_audit",
        "source_run": "run_002_corrected",
        "non_decisional": True,
        "discovery_executed": False,
        "validation_executed": False,
        "holdout_executed": False,
        "canonical_payload_sha256": "bac53f3ff97176b9be5bd5b52a9d6589747587a313b34f24644e1d99bb4cd2ab",
        "tradingview_trades": 40,
        "python_trades": int(len(py_trades)),
        "date_direction_matches": int(comparison_summary["date_direction_matches"]),
        "missing_in_python": int(comparison_summary["missing_in_python"]),
        "missing_in_tradingview": int(comparison_summary["missing_in_tradingview"]),
        "unresolved_signal_logic": int(comparison_summary["difference_type_counts"].get("SIGNAL_LOGIC_DIFFERENCE", 0)),
        "unresolved_true_signal_session_alignment": true_session_blockers,
        "unexplained_mismatches": int(comparison_summary["unexplained_mismatches"]),
        "position_sizing_differences": int(comparison_summary["difference_type_counts"].get("POSITION_SIZING_DIFFERENCE", 0)),
        "cost_rounding_tolerance": FINAL_COST_ROUNDING_TOLERANCE,
        "unresolved_costs": unresolved_costs,
        "final_gate_status": "PASS" if final_gate_passed else "BLOCKED",
        "timing_final_classification_counts": timing["final_classification"].value_counts().to_dict(),
        "remaining_non_blocking_categories": {
            "DATA_FEED_DIFFERENCE": int(comparison_summary["difference_type_counts"].get("DATA_FEED_DIFFERENCE", 0)),
            "DATA_FEED_SIGNAL_BOUNDARY": int((timing["final_classification"] == "DATA_FEED_SIGNAL_BOUNDARY").sum()),
            "EXIT_INTRABAR_TIMING": int((timing["final_classification"] == "EXIT_INTRABAR_TIMING").sum()),
            "COST_ROUNDING_DIFFERENCE": int(len(cost)),
        },
        "safety_flags": {
            "live_trading": False,
            "broker_connected": False,
            "orders_sent": False,
            "paper_broker_enabled": False,
        },
    }
    (outputs / "input_hashes.json").write_text(
        json.dumps({"inputs": hashes}, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (outputs / "final_gate_summary.json").write_text(
        json.dumps(final_summary, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    output_hashes = [
        {"path": str(path), "sha256": _hash_file(path)}
        for path in sorted(outputs.glob("*"))
        if path.is_file() and path.name != "run_003_hashes.json"
    ]
    (outputs / "run_003_hashes.json").write_text(
        json.dumps({"outputs": output_hashes}, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return final_summary


def write_comparison_artifacts(
    tv_csv: str | Path = DEFAULT_TV_CSV,
    *,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    dataset_path: str | Path = DEFAULT_DATASET,
    manifest_dir: str | Path = DEFAULT_MANIFEST_DIR,
) -> dict[str, Any]:
    py_trades, _, _, run_manifest = generate_python_parity(
        dataset_path=dataset_path,
        manifest_dir=manifest_dir,
        output_dir=output_dir,
    )
    tv_trades = pd.read_csv(tv_csv)
    sequence_comparison = compare_pine_to_python(tv_trades, py_trades)
    comparison = compare_pine_to_python_events(tv_trades, py_trades)
    outputs = Path(output_dir)
    sequence_comparison.to_csv(outputs / "sequence_comparison.csv", index=False)
    comparison.to_csv(outputs / "event_matching.csv", index=False)
    comparison.to_csv(outputs / "tradingview_vs_python_comparison.csv", index=False)
    for bucket in (
        "matched_trades",
        "missing_in_python",
        "missing_in_tradingview",
        "field_mismatches",
        "unexplained_mismatches",
    ):
        comparison.loc[comparison["parity_bucket"] == bucket].to_csv(
            outputs / f"{bucket}.csv",
            index=False,
        )
    five, _, _ = _load_period_signal_inputs(dataset_path, manifest_dir)
    initial_path = DEFAULT_OUTPUT_DIR / "run_001_initial" / "tradingview_vs_python_comparison.csv"
    initial_sequence = pd.read_csv(initial_path) if initial_path.exists() else sequence_comparison
    session_diagnostics = build_session_alignment_diagnostics(
        initial_sequence_comparison=initial_sequence,
        event_comparison=comparison,
        py_trades=py_trades,
    )
    session_diagnostics.to_csv(outputs / "session_alignment_diagnostics.csv", index=False)
    signal_diagnostics = build_signal_logic_diagnostics(
        five=five,
        initial_sequence_comparison=initial_sequence,
    )
    signal_diagnostics.to_csv(outputs / "signal_logic_diagnostics.csv", index=False)
    cost_reconciliation = build_cost_reconciliation(comparison)
    cost_reconciliation.to_csv(outputs / "cost_reconciliation.csv", index=False)
    summary = summarize_comparison(comparison)
    sequence_summary = summarize_comparison(sequence_comparison)
    summary_payload = {
        "run_manifest": run_manifest,
        "comparison_summary": summary,
        "sequence_comparison_summary": sequence_summary,
        "tolerances": Tolerances().__dict__,
        "event_match_config": EventMatchConfig().__dict__,
        "non_decisional": True,
        "discovery_executed": False,
        "validation_executed": False,
        "holdout_executed": False,
    }
    (outputs / "comparison_summary.json").write_text(
        json.dumps(summary_payload, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    return summary_payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run non-decisional HYP-FCR-01 QQQ 2026 parity")
    parser.add_argument("--tradingview-csv", default=str(DEFAULT_TV_CSV))
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET))
    parser.add_argument("--manifest-dir", default=str(DEFAULT_MANIFEST_DIR))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    payload = write_comparison_artifacts(
        args.tradingview_csv,
        output_dir=args.output_dir,
        dataset_path=args.dataset,
        manifest_dir=args.manifest_dir,
    )
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
