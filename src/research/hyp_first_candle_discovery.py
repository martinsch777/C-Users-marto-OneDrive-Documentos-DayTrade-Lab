from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
from dataclasses import asdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from src.data import EquitySessionCalendar
from src.research.hyp_first_candle import (
    EXPECTED_CANONICAL_PAYLOAD_SHA256,
    FirstCandleConfig,
    ResearchPeriodRequest,
    add_session_columns,
    detect_first_candle_signals,
    load_symbol_curated_1min,
    resample_rth_1min_to_5min,
    serialize_trade_frame,
    simulate_research_primary_trade,
    validate_research_period_request,
)


DISCOVERY_START = date(2022, 1, 1)
DISCOVERY_END = date(2024, 12, 31)
SYMBOL_DATASETS = {
    "QQQ": Path("data/curated/QQQ_1min_2022-01-01_2026-07-06_curated.csv"),
    "SPY": Path("data/curated/SPY_1min_2022-01-01_2026-07-06_curated.csv"),
}
DEFAULT_OUTPUT_DIR = Path("artifacts/research/HYP-FCR-01/discovery_2022_2024")
DEFAULT_MANIFEST_DIR = Path("data/manifests")
CONFIG_PATH = Path("configs/research/hypotheses/HYP-FCR-01.yaml")
PINE_PATH = Path("docs/research/source_pine/FIRST_CANDLE_RULE_TV_V1.pine")
EXPECTED_PINE_SHA256 = "91604D14B6DAA95758AF3D97617F3F2278E771A5A30ADC61F24E10D83B166D22"


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _local_dates(frame: pd.DataFrame) -> pd.Series:
    return frame["timestamp"].dt.tz_convert("America/New_York").dt.date


def _filter_discovery(frame: pd.DataFrame) -> pd.DataFrame:
    local_dates = _local_dates(frame)
    mask = (local_dates >= DISCOVERY_START) & (local_dates <= DISCOVERY_END)
    return frame.loc[mask].reset_index(drop=True)


def _add_atr(five: pd.DataFrame) -> pd.DataFrame:
    data = add_session_columns(five).copy()
    frames: list[pd.DataFrame] = []
    for _, session in data.groupby("session_date", sort=True):
        session = session.copy()
        prev_close = session["close"].shift(1)
        ranges = pd.concat(
            [
                session["high"] - session["low"],
                (session["high"] - prev_close).abs(),
                (session["low"] - prev_close).abs(),
            ],
            axis=1,
        )
        session["atr_14"] = ranges.max(axis=1).rolling(14, min_periods=1).mean()
        frames.append(session)
    return pd.concat(frames, ignore_index=True) if frames else data


def _session_minutes(minutes: pd.DataFrame, session_date: str) -> pd.DataFrame:
    local_dates = minutes["timestamp"].dt.tz_convert("America/New_York").dt.date.astype(str)
    return minutes.loc[local_dates == session_date].reset_index(drop=True)


def _simulate_symbol_scenario(
    *,
    symbol: str,
    five: pd.DataFrame,
    minute_by_session: dict[str, pd.DataFrame],
    atr_lookup: dict[pd.Timestamp, float],
    scenario: str,
    config: FirstCandleConfig,
    calendar: EquitySessionCalendar,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    costs = config.cost(scenario)
    five_with_sessions = add_session_columns(five, config)
    equity = float(config.initial_equity)
    trades: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    for session_date, session_five in five_with_sessions.groupby("session_date", sort=True):
        session_five = session_five.drop(columns=["local_time", "minute_of_day", "session_bar_index"], errors="ignore")
        signals, session_diagnostics = detect_first_candle_signals(
            session_five.reset_index(drop=True),
            symbol,
            config,
            equity=equity,
        )
        for _, diagnostic in session_diagnostics.iterrows():
            payload = diagnostic.to_dict()
            payload.update({"scenario": scenario, "equity_before_session": equity})
            diagnostics.append(payload)
        if signals.empty:
            continue
        signal = signals.iloc[0].copy()
        atr = float(atr_lookup.get(pd.Timestamp(signal["signal_time"]), math.nan))
        minutes_for_session = minute_by_session.get(str(session_date), pd.DataFrame())
        equity_before = equity
        trade = simulate_research_primary_trade(
            signal,
            minutes_for_session,
            equity=equity,
            costs=costs,
            config=config,
            calendar=calendar,
        )
        entry_valid = pd.notna(pd.to_datetime(trade.get("entry_time", ""), utc=True, errors="coerce"))
        exit_valid = pd.notna(pd.to_datetime(trade.get("exit_time", ""), utc=True, errors="coerce"))
        if not entry_valid or not exit_valid:
            diagnostics.append(
                {
                    "symbol": symbol,
                    "scenario": scenario,
                    "session_date": str(session_date),
                    "timestamp": pd.Timestamp(signal["signal_time"]).isoformat(),
                    "direction": str(signal["direction"]),
                    "diagnostic": str(trade.get("exit_reason", "non_completed_execution_candidate")),
                    "equity_before_session": equity,
                    "actual_quantity": trade.get("actual_quantity", 0),
                }
            )
            continue
        if float(trade.get("actual_quantity", 0)) > 0:
            equity += float(trade["net_pnl"])
        trade.update(
            {
                "scenario": scenario,
                "equity_before": equity_before,
                "equity_after": equity,
                "fvg_size_ticks": float(signal["fvg_size_ticks"]),
                "atr_14": atr,
                "fvg_size_normalized_by_atr": (
                    float(signal["fvg_size"]) / atr if atr and math.isfinite(atr) and atr > 0 else math.nan
                ),
                "bars_since_last_sweep": int(signal["bars_since_last_sweep"]),
                "minutes_between_last_touch_and_confirmation": (
                    (
                        pd.Timestamp(signal["signal_time"]) - pd.Timestamp(signal["last_sweep_time"])
                    ).total_seconds()
                    / 60.0
                ),
            }
        )
        trades.append(trade)
    return pd.DataFrame(trades), pd.DataFrame(diagnostics)


def _profit_factor(values: pd.Series) -> float:
    gains = float(values.loc[values > 0].sum())
    losses = float(values.loc[values < 0].sum())
    if losses < 0:
        return gains / abs(losses)
    return math.inf if gains > 0 else 0.0


def _max_drawdown(values: pd.Series, *, initial_equity: float) -> float:
    if values.empty:
        return 0.0
    equity = initial_equity + values.cumsum()
    peak = equity.cummax()
    drawdown = ((equity - peak) / peak).min()
    return float(abs(drawdown)) if math.isfinite(float(drawdown)) else 0.0


def _longest_losing_streak(values: pd.Series) -> int:
    longest = 0
    current = 0
    for value in values:
        if float(value) < 0:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def metrics_for_trades(
    trades: pd.DataFrame,
    *,
    initial_equity: float,
    sizing_rejections: int = 0,
) -> dict[str, Any]:
    if trades.empty:
        return {
            "completed_trades": 0,
            "net_expectancy_R": 0.0,
            "profit_factor_net": 0.0,
            "total_net_pnl": 0.0,
            "maximum_drawdown": 0.0,
            "sizing_rejections": int(sizing_rejections),
        }
    entry_times = pd.to_datetime(trades["entry_time"], utc=True, errors="coerce")
    exit_times = pd.to_datetime(trades["exit_time"], utc=True, errors="coerce")
    completed = trades.loc[
        (trades["actual_quantity"].astype(float) > 0) & entry_times.notna() & exit_times.notna()
    ].copy()
    completed = completed.sort_values(["exit_time", "entry_time"], kind="mergesort")
    net = completed["net_pnl"].astype(float)
    realized = completed["realized_R"].astype(float)
    gross = completed["intended_R"].astype(float)
    exposure = (
        pd.to_datetime(completed["exit_time"], utc=True) - pd.to_datetime(completed["entry_time"], utc=True)
    ).dt.total_seconds() / 60.0
    return {
        "completed_trades": int(len(completed)),
        "net_expectancy_R": float(realized.mean()) if not realized.empty else 0.0,
        "gross_expectancy_R": float(gross.mean()) if not gross.empty else 0.0,
        "profit_factor_net": float(_profit_factor(net)),
        "total_net_pnl": float(net.sum()),
        "maximum_drawdown": _max_drawdown(net, initial_equity=initial_equity),
        "win_rate": float((net > 0).mean()) if not net.empty else 0.0,
        "average_win_R": float(realized.loc[realized > 0].mean()) if (realized > 0).any() else 0.0,
        "average_loss_R": float(realized.loc[realized < 0].mean()) if (realized < 0).any() else 0.0,
        "median_trade_R": float(realized.median()) if not realized.empty else 0.0,
        "longest_losing_streak": int(_longest_losing_streak(net)),
        "exposure_time_minutes": float(exposure.sum()) if not exposure.empty else 0.0,
        "intended_risk_percent_mean": float(completed["risk_percent_intended"].astype(float).mean()),
        "realized_risk_percent_mean": float(completed["risk_percent_realized"].astype(float).mean()),
        "sizing_rejections": int(sizing_rejections),
        "minutes_between_last_touch_and_confirmation_mean": float(
            completed["minutes_between_last_touch_and_confirmation"].astype(float).mean()
        ),
        "fvg_size_ticks_mean": float(completed["fvg_size_ticks"].astype(float).mean()),
        "fvg_size_normalized_by_atr_mean": float(
            completed["fvg_size_normalized_by_atr"].astype(float).mean()
        ),
        "tp_exits": int((completed["exit_reason"] == "TAKE_PROFIT").sum()),
        "sl_exits": int(
            completed["exit_reason"].isin(["STOP_LOSS", "STOP_FIRST_AMBIGUOUS_BAR", "GAP_THROUGH_STOP"]).sum()
        ),
        "session_close_exits": int((completed["exit_reason"] == "FORCED_SESSION_CLOSE").sum()),
    }


def _metrics_by_group(
    trades: pd.DataFrame,
    group_columns: list[str],
    *,
    initial_equity: float,
    sizing_rejections: pd.DataFrame | None = None,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    if trades.empty:
        return pd.DataFrame()
    for key, group in trades.groupby(group_columns, dropna=False, sort=True):
        if not isinstance(key, tuple):
            key = (key,)
        if any(pd.isna(value) for value in key):
            continue
        filters = dict(zip(group_columns, key))
        rejection_count = 0
        if sizing_rejections is not None and not sizing_rejections.empty:
            mask = pd.Series(True, index=sizing_rejections.index)
            for column, value in filters.items():
                if column in sizing_rejections.columns:
                    mask &= sizing_rejections[column].astype(str) == str(value)
            rejection_count = int(mask.sum())
        rows.append(
            {
                **filters,
                **metrics_for_trades(group, initial_equity=initial_equity, sizing_rejections=rejection_count),
            }
        )
    return pd.DataFrame(rows)


def _gate_evaluation(summary: dict[str, Any], by_symbol: pd.DataFrame, by_year: pd.DataFrame) -> dict[str, Any]:
    baseline = summary["baseline"]
    stress = summary["stress"]
    baseline_symbols = by_symbol.loc[by_symbol["scenario"] == "baseline"].set_index("symbol")
    baseline_years = by_year.loc[
        (by_year["scenario"] == "baseline") & by_year["year"].notna()
    ].copy()
    year_pnl = {
        str(int(row["year"])): float(row["total_net_pnl"])
        for _, row in baseline_years.iterrows()
    }
    total_pnl = float(baseline["total_net_pnl"])
    if total_pnl > 0:
        year_contrib = {year: pnl / total_pnl for year, pnl in year_pnl.items()}
        max_year_share = max(year_contrib.values()) if year_contrib else None
        year_share_observed = {
            "total_net_pnl": total_pnl,
            "year_contributions": year_contrib,
            "max_year_share": max_year_share,
        }
    else:
        max_year_share = None
        year_share_observed = {
            "total_net_pnl": total_pnl,
            "year_contributions": {year: None for year in year_pnl},
            "max_year_share": None,
            "reason": "pooled_baseline_total_net_pnl_lte_0",
        }
    criteria = [
        ("minimum_completed_trades_pooled", baseline["completed_trades"] >= 150, baseline["completed_trades"], ">= 150"),
        (
            "minimum_completed_trades_per_symbol",
            all(float(baseline_symbols.loc[symbol, "completed_trades"]) >= 50 for symbol in ("QQQ", "SPY")),
            {symbol: int(baseline_symbols.loc[symbol, "completed_trades"]) for symbol in ("QQQ", "SPY")},
            "each >= 50",
        ),
        ("baseline_net_expectancy_R_gt_0", baseline["net_expectancy_R"] > 0, baseline["net_expectancy_R"], "> 0"),
        ("baseline_profit_factor_net_gte_1_15", baseline["profit_factor_net"] >= 1.15, baseline["profit_factor_net"], ">= 1.15"),
        ("qqq_net_positive_baseline", baseline_symbols.loc["QQQ", "total_net_pnl"] > 0, baseline_symbols.loc["QQQ", "total_net_pnl"], "> 0"),
        ("spy_net_positive_baseline", baseline_symbols.loc["SPY", "total_net_pnl"] > 0, baseline_symbols.loc["SPY", "total_net_pnl"], "> 0"),
        ("stress_net_expectancy_R_gte_0", stress["net_expectancy_R"] >= 0, stress["net_expectancy_R"], ">= 0"),
        ("stress_profit_factor_net_gte_1_00", stress["profit_factor_net"] >= 1.00, stress["profit_factor_net"], ">= 1.00"),
        (
            "minimum_two_positive_years",
            sum(1 for value in year_pnl.values() if value > 0) >= 2,
            year_pnl,
            ">= 2 positive years",
        ),
        (
            "max_single_year_profit_share_lte_70pct",
            total_pnl > 0 and max_year_share is not None and max_year_share <= 0.70,
            year_share_observed,
            "total > 0 and max(year_net / total_net) <= 0.70",
        ),
        ("maximum_drawdown_lte_10pct", baseline["maximum_drawdown"] <= 0.10, baseline["maximum_drawdown"], "<= 0.10"),
    ]
    rows = [
        {"criterion": name, "passed": bool(passed), "observed": observed, "threshold": threshold}
        for name, passed, observed, threshold in criteria
    ]
    passed_all = all(row["passed"] for row in rows)
    return {
        "status": "discovery_passed" if passed_all else "discovery_failed",
        "validation_2025_eligible": bool(passed_all),
        "validation_2025_unlocked": bool(passed_all),
        "criteria": rows,
        "year_contribution_formula": "year_net_pnl / pooled_baseline_total_net_pnl; if total <= 0 the criterion fails",
    }


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str, allow_nan=False), encoding="utf-8")


def _write_checksums(output_dir: Path, input_paths: list[Path], primary_outputs: list[Path]) -> None:
    payload = {
        "inputs": [{"path": str(path), "sha256": sha256_file(path)} for path in input_paths if path.exists()],
        "outputs": [{"path": str(path), "sha256": sha256_file(path)} for path in primary_outputs if path.exists()],
    }
    _write_json(output_dir / "checksums.json", payload)


def run_discovery(
    *,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    manifest_dir: str | Path = DEFAULT_MANIFEST_DIR,
) -> dict[str, Any]:
    validate_research_period_request(
        ResearchPeriodRequest(
            period="discovery",
            start=DISCOVERY_START,
            end=DISCOVERY_END,
            canonical_payload_sha256=EXPECTED_CANONICAL_PAYLOAD_SHA256,
            non_decisional=False,
        )
    )
    if sha256_file(PINE_PATH).upper() != EXPECTED_PINE_SHA256:
        raise ValueError("Pine SHA-256 mismatch; discovery blocked.")
    output = Path(output_dir)
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"Discovery output directory already exists and is not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(CONFIG_PATH, output / "config_snapshot.yaml")
    calendar = EquitySessionCalendar.from_config({"source": "us_equity"})
    config = FirstCandleConfig()
    dataset_snapshot: dict[str, Any] = {}
    period_rows: dict[str, Any] = {}
    all_trades: dict[str, list[pd.DataFrame]] = {scenario: [] for scenario in ("baseline", "stress", "severe")}
    all_rejections: list[pd.DataFrame] = []
    all_diagnostics: list[pd.DataFrame] = []
    for symbol, path in SYMBOL_DATASETS.items():
        minute, manifest = load_symbol_curated_1min(path, symbol, manifest_dir=manifest_dir, calendar=calendar)
        period_minute = _filter_discovery(minute)
        five = resample_rth_1min_to_5min(period_minute, calendar)
        minute_sessions = period_minute.copy()
        minute_sessions["session_date"] = _local_dates(minute_sessions).astype(str)
        minute_by_session = {
            str(session_date): group.drop(columns=["session_date"]).reset_index(drop=True)
            for session_date, group in minute_sessions.groupby("session_date", sort=True)
        }
        atr_lookup = _add_atr(five).set_index("timestamp")["atr_14"].to_dict()
        sessions = sorted(_local_dates(period_minute).astype(str).unique().tolist())
        period_rows[symbol] = {
            "requested_start": DISCOVERY_START.isoformat(),
            "requested_end": DISCOVERY_END.isoformat(),
            "effective_start": sessions[0] if sessions else "",
            "effective_end": sessions[-1] if sessions else "",
            "session_count": len(sessions),
            "rows_1m": int(len(period_minute)),
            "bars_5m": int(len(five)),
            "excluded_sessions": manifest.excluded_sessions,
        }
        dataset_snapshot[symbol] = {
            "dataset_path": str(path),
            "dataset_sha256": manifest.sha256,
            "manifest": asdict(manifest),
            "period": period_rows[symbol],
        }
        for scenario in ("baseline", "stress", "severe"):
            trades, diagnostics = _simulate_symbol_scenario(
                symbol=symbol,
                five=five,
                minute_by_session=minute_by_session,
                atr_lookup=atr_lookup,
                scenario=scenario,
                config=config,
                calendar=calendar,
            )
            if not trades.empty:
                all_trades[scenario].append(trades)
            if not diagnostics.empty:
                diagnostics["symbol"] = symbol
                all_diagnostics.append(diagnostics.copy())
                all_rejections.append(diagnostics.loc[diagnostics["diagnostic"] == "quantity_below_minimum"].copy())
    sizing_rejections = pd.concat(all_rejections, ignore_index=True) if all_rejections else pd.DataFrame()
    execution_diagnostics = pd.concat(all_diagnostics, ignore_index=True) if all_diagnostics else pd.DataFrame()
    if not sizing_rejections.empty and "timestamp" in sizing_rejections.columns:
        sizing_rejections["year"] = pd.to_datetime(sizing_rejections["timestamp"], utc=True).dt.year
    scenario_frames: dict[str, pd.DataFrame] = {}
    metrics_summary: dict[str, Any] = {}
    for scenario, frames in all_trades.items():
        trades = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        if not trades.empty:
            trades["year"] = pd.to_datetime(trades["entry_time"], utc=True).dt.year
            trades["entry_hour"] = pd.to_datetime(trades["entry_time"], utc=True).dt.tz_convert("America/New_York").dt.hour
            trades = trades.sort_values(["entry_time", "symbol"], kind="mergesort").reset_index(drop=True)
        scenario_frames[scenario] = trades
        rejection_count = int((sizing_rejections["scenario"] == scenario).sum()) if not sizing_rejections.empty else 0
        metrics_summary[scenario] = metrics_for_trades(
            trades,
            initial_equity=config.initial_equity * len(SYMBOL_DATASETS),
            sizing_rejections=rejection_count,
        )
        serialize_trade_frame(trades).to_csv(output / f"trades_{scenario}.csv", index=False)
    all_scenario_trades = pd.concat(scenario_frames.values(), ignore_index=True)
    metrics_by_symbol = _metrics_by_group(
        all_scenario_trades,
        ["scenario", "symbol"],
        initial_equity=config.initial_equity,
        sizing_rejections=sizing_rejections,
    )
    metrics_by_year = _metrics_by_group(
        all_scenario_trades,
        ["scenario", "year"],
        initial_equity=config.initial_equity * len(SYMBOL_DATASETS),
        sizing_rejections=sizing_rejections,
    )
    metrics_by_direction = _metrics_by_group(
        all_scenario_trades,
        ["scenario", "direction"],
        initial_equity=config.initial_equity * len(SYMBOL_DATASETS),
    )
    metrics_by_symbol.to_csv(output / "metrics_by_symbol.csv", index=False)
    metrics_by_year.to_csv(output / "metrics_by_year.csv", index=False)
    metrics_by_direction.to_csv(output / "metrics_by_direction.csv", index=False)
    if not sizing_rejections.empty:
        sizing_rejections.to_csv(output / "sizing_rejections.csv", index=False)
    else:
        pd.DataFrame().to_csv(output / "sizing_rejections.csv", index=False)
    execution_diagnostics.to_csv(output / "execution_diagnostics.csv", index=False)
    gate = _gate_evaluation(metrics_summary, metrics_by_symbol, metrics_by_year)
    _write_json(output / "metrics_summary.json", metrics_summary)
    _write_json(output / "gate_evaluation.json", gate)
    _write_json(output / "dataset_manifest_snapshot.json", dataset_snapshot)
    run_manifest = {
        "hypothesis_id": "HYP-FCR-01",
        "execution_mode": "research_primary",
        "period": "discovery",
        "requested_start": DISCOVERY_START.isoformat(),
        "requested_end": DISCOVERY_END.isoformat(),
        "symbols": list(SYMBOL_DATASETS),
        "scenarios": ["baseline", "stress", "severe"],
        "canonical_payload_sha256": EXPECTED_CANONICAL_PAYLOAD_SHA256,
        "pine_sha256": sha256_file(PINE_PATH),
        "config_path": str(CONFIG_PATH),
        "pine_path": str(PINE_PATH),
        "period_rows": period_rows,
        "status": gate["status"],
        "validation_2025_eligible": gate["validation_2025_eligible"],
        "validation_executed": False,
        "holdout_executed": False,
        "parity_2026_executed": False,
        "optimization_executed": False,
        "parameter_sweep_executed": False,
        "safety_flags": {
            "live_trading": False,
            "broker_connected": False,
            "orders_sent": False,
            "paper_broker_enabled": False,
        },
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    _write_json(output / "run_manifest.json", run_manifest)
    input_paths = [CONFIG_PATH, PINE_PATH, *SYMBOL_DATASETS.values()]
    manifest_paths = [
        Path("data/manifests/QQQ_1min_2022-01-01_2026-07-06_curated_manifest.json"),
        Path("data/manifests/SPY_1min_2022-01-01_2026-07-06_curated_manifest.json"),
    ]
    primary_outputs = [
        output / "run_manifest.json",
        output / "dataset_manifest_snapshot.json",
        output / "config_snapshot.yaml",
        output / "trades_baseline.csv",
        output / "trades_stress.csv",
        output / "trades_severe.csv",
        output / "metrics_summary.json",
        output / "metrics_by_symbol.csv",
        output / "metrics_by_year.csv",
        output / "metrics_by_direction.csv",
        output / "sizing_rejections.csv",
        output / "execution_diagnostics.csv",
        output / "gate_evaluation.json",
    ]
    _write_checksums(output, [*input_paths, *manifest_paths], primary_outputs)
    return {"run_manifest": run_manifest, "metrics_summary": metrics_summary, "gate_evaluation": gate}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run HYP-FCR-01 preregistered discovery only")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--manifest-dir", default=str(DEFAULT_MANIFEST_DIR))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    payload = run_discovery(output_dir=args.output_dir, manifest_dir=args.manifest_dir)
    print(json.dumps(payload, indent=2, sort_keys=True, default=str, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
