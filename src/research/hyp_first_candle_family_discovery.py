from __future__ import annotations

import json
import math
import shutil
import subprocess
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from src.data import EquitySessionCalendar
from src.research.hyp_first_candle import (
    FirstCandleConfig,
    add_session_columns,
    load_symbol_curated_1min,
    resample_rth_1min_to_5min,
    serialize_trade_frame,
    simulate_research_primary_trade,
)
from src.research.hyp_first_candle_discovery import (
    _add_atr,
    _filter_discovery,
    _local_dates,
    _metrics_by_group,
    metrics_for_trades,
    sha256_file,
)
from src.research.hyp_first_candle_family_runner import (
    FAMILY_CONFIG_PATH,
    FAMILY_ID,
    VARIANT_IDS,
    canonical_yaml_hash,
    select_family_variant,
)
from src.research.hyp_first_candle_variants import (
    VARIANT_SPECS,
    config_for_variant,
    detect_first_candle_variant_signals,
)


DISCOVERY_START = "2022-01-01"
DISCOVERY_END = "2024-12-31"
DEFAULT_OUTPUT_DIR = Path("artifacts/research/FCR-REFINEMENT-FAMILY-01/discovery_2022_2024")
SYMBOL_DATASETS = {
    "QQQ": Path("data/curated/QQQ_1min_2022-01-01_2026-07-06_curated.csv"),
    "SPY": Path("data/curated/SPY_1min_2022-01-01_2026-07-06_curated.csv"),
}
EXPECTED_HASHES = {
    "HYP-FCR-02": "2276cd958aaf5e982e393fcaa29611fe46bb9a483bd606a0a681a5613922c8e6",
    "HYP-FCR-03": "c7e69addf98b2e35a34bafaadc7b55e6139c79a6cc7f06538e83673584eb70ec",
    "HYP-FCR-04": "1ddd959bc559503be511b6ac1e9b62bd60e8f413b6cfdc3d98ab89cd6682799b",
    FAMILY_ID: "1ecacc828b91533458ae112ed7c749936612f94a26b2d0b48ea2da0b5948d7ad",
}


def _git_head() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str, allow_nan=False), encoding="utf-8")


def _checksum_payload(paths: list[Path]) -> list[dict[str, str]]:
    return [{"path": str(path), "sha256": sha256_file(path)} for path in paths if path.exists()]


def _assert_expected_hashes() -> dict[str, str]:
    actual = {
        hypothesis_id: canonical_yaml_hash(Path("configs/research/hypotheses") / f"{hypothesis_id}.yaml")
        for hypothesis_id in VARIANT_IDS
    }
    actual[FAMILY_ID] = canonical_yaml_hash(FAMILY_CONFIG_PATH)
    mismatches = {
        key: {"expected": EXPECTED_HASHES[key], "actual": value}
        for key, value in actual.items()
        if value != EXPECTED_HASHES[key]
    }
    if mismatches:
        raise ValueError(f"Canonical hash mismatch; family discovery blocked: {mismatches}")
    return actual


def _period_payload(period_minute: pd.DataFrame, five: pd.DataFrame, manifest: Any) -> dict[str, Any]:
    sessions = sorted(_local_dates(period_minute).astype(str).unique().tolist())
    return {
        "requested_start": DISCOVERY_START,
        "requested_end": DISCOVERY_END,
        "effective_start": sessions[0] if sessions else "",
        "effective_end": sessions[-1] if sessions else "",
        "session_count": len(sessions),
        "rows_1m": int(len(period_minute)),
        "bars_5m": int(len(five)),
        "excluded_sessions": manifest.excluded_sessions,
    }


def _prepare_symbol_data(calendar: EquitySessionCalendar) -> tuple[dict[str, Any], dict[str, Any]]:
    dataset_snapshot: dict[str, Any] = {}
    symbol_data: dict[str, Any] = {}
    for symbol, path in SYMBOL_DATASETS.items():
        minute, manifest = load_symbol_curated_1min(path, symbol, calendar=calendar)
        period_minute = _filter_discovery(minute)
        five = resample_rth_1min_to_5min(period_minute, calendar)
        minute_sessions = period_minute.copy()
        minute_sessions["session_date"] = _local_dates(minute_sessions).astype(str)
        minute_by_session = {
            str(session_date): group.drop(columns=["session_date"]).reset_index(drop=True)
            for session_date, group in minute_sessions.groupby("session_date", sort=True)
        }
        atr_lookup = _add_atr(five).set_index("timestamp")["atr_14"].to_dict()
        period = _period_payload(period_minute, five, manifest)
        dataset_snapshot[symbol] = {
            "dataset_path": str(path),
            "dataset_sha256": manifest.sha256,
            "manifest": asdict(manifest),
            "period": period,
        }
        symbol_data[symbol] = {
            "five": five,
            "minute_by_session": minute_by_session,
            "atr_lookup": atr_lookup,
            "period": period,
        }
    return dataset_snapshot, symbol_data


def _simulate_variant_symbol_scenario(
    *,
    hypothesis_id: str,
    symbol: str,
    scenario: str,
    five: pd.DataFrame,
    minute_by_session: dict[str, pd.DataFrame],
    atr_lookup: dict[pd.Timestamp, float],
    calendar: EquitySessionCalendar,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    spec = VARIANT_SPECS[hypothesis_id]
    config = config_for_variant(spec)
    costs = config.cost(scenario)
    five_with_sessions = add_session_columns(five, config)
    equity = float(config.initial_equity)
    trades: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    for session_date, session_five in five_with_sessions.groupby("session_date", sort=True):
        session_five = session_five.drop(columns=["local_time", "minute_of_day", "session_bar_index"], errors="ignore")
        signals, session_diagnostics = detect_first_candle_variant_signals(
            session_five.reset_index(drop=True),
            symbol,
            spec,
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
                    "hypothesis_id": hypothesis_id,
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
                "hypothesis_id": hypothesis_id,
                "scenario": scenario,
                "equity_before": equity_before,
                "equity_after": equity,
                "fvg_size_ticks": float(signal["fvg_size_ticks"]),
                "atr_14": atr,
                "fvg_size_normalized_by_atr": (
                    float(signal["fvg_size"]) / atr if atr and math.isfinite(atr) and atr > 0 else math.nan
                ),
                "bars_since_last_sweep": int(signal["bars_since_last_sweep"]),
                "confirmation_offset_bars": int(signal.get("confirmation_offset_bars", signal["bars_since_last_sweep"])),
                "sweep_depth_ticks": float(signal.get("sweep_depth_ticks", 0.0)),
                "stop_distance": float(signal["risk_per_unit"]),
                "minutes_between_last_touch_and_confirmation": (
                    (
                        pd.Timestamp(signal["signal_time"]) - pd.Timestamp(signal["last_sweep_time"])
                    ).total_seconds()
                    / 60.0
                ),
            }
        )
        for optional in (
            "original_body_stop",
            "structural_stop_distance_from_original",
            "structural_segment_bars",
        ):
            if optional in signal:
                trade[optional] = signal[optional]
        trades.append(trade)
    return pd.DataFrame(trades), pd.DataFrame(diagnostics)


def _gate_criteria(
    summary: dict[str, Any],
    by_symbol: pd.DataFrame,
    by_year: pd.DataFrame,
) -> dict[str, Any]:
    baseline = summary["baseline"]
    stress = summary["stress"]
    baseline_symbols = by_symbol.loc[by_symbol["scenario"] == "baseline"].set_index("symbol")
    baseline_years = by_year.loc[(by_year["scenario"] == "baseline") & by_year["year"].notna()].copy()
    year_pnl = {str(int(row["year"])): float(row["total_net_pnl"]) for _, row in baseline_years.iterrows()}
    total_pnl = float(baseline["total_net_pnl"])
    positive_years = sum(1 for value in year_pnl.values() if value > 0)
    if total_pnl > 0:
        year_contrib = {year: pnl / total_pnl for year, pnl in year_pnl.items()}
        max_year_share = max(year_contrib.values()) if year_contrib else None
        concentration_actual: Any = {"total_net_pnl": total_pnl, "max_year_share": max_year_share, "year_contributions": year_contrib}
        concentration_pass = max_year_share is not None and max_year_share <= 0.70
    else:
        concentration_actual = {
            "total_net_pnl": total_pnl,
            "max_year_share": None,
            "year_contributions": {year: None for year in year_pnl},
            "reason": "pooled_baseline_total_net_pnl_lte_0",
        }
        concentration_pass = False
    qqq_trades = int(baseline_symbols.loc["QQQ", "completed_trades"]) if "QQQ" in baseline_symbols.index else 0
    spy_trades = int(baseline_symbols.loc["SPY", "completed_trades"]) if "SPY" in baseline_symbols.index else 0
    qqq_pnl = float(baseline_symbols.loc["QQQ", "total_net_pnl"]) if "QQQ" in baseline_symbols.index else 0.0
    spy_pnl = float(baseline_symbols.loc["SPY", "total_net_pnl"]) if "SPY" in baseline_symbols.index else 0.0
    criteria = [
        ("completed_trades_pooled", ">= 150", int(baseline["completed_trades"]), baseline["completed_trades"] >= 150, "Pooled completed discovery trades."),
        ("qqq_completed_trades", ">= 50", qqq_trades, qqq_trades >= 50, "QQQ completed discovery trades."),
        ("spy_completed_trades", ">= 50", spy_trades, spy_trades >= 50, "SPY completed discovery trades."),
        ("baseline_net_expectancy_R", "> 0", baseline["net_expectancy_R"], baseline["net_expectancy_R"] > 0, "Baseline expectancy must be positive."),
        ("baseline_profit_factor_net", ">= 1.15", baseline["profit_factor_net"], baseline["profit_factor_net"] >= 1.15, "Baseline profit factor must clear preregistered threshold."),
        ("qqq_baseline_net_pnl", "> 0", qqq_pnl, qqq_pnl > 0, "QQQ must be net positive under baseline."),
        ("spy_baseline_net_pnl", "> 0", spy_pnl, spy_pnl > 0, "SPY must be net positive under baseline."),
        ("stress_net_expectancy_R", ">= 0", stress["net_expectancy_R"], stress["net_expectancy_R"] >= 0, "Stress expectancy must be non-negative."),
        ("stress_profit_factor_net", ">= 1.00", stress["profit_factor_net"], stress["profit_factor_net"] >= 1.0, "Stress profit factor must be at least breakeven."),
        ("positive_discovery_years", ">= 2", {"positive_years": positive_years, "year_net_pnl": year_pnl}, positive_years >= 2, "At least two discovery years must be positive."),
        ("max_single_year_profit_share", "<= 70% and total > 0", concentration_actual, concentration_pass, "If total baseline PnL is not positive, concentration fails automatically."),
        ("baseline_maximum_drawdown", "<= 10%", baseline["maximum_drawdown"], baseline["maximum_drawdown"] <= 0.10, "Baseline drawdown cap."),
    ]
    rows = [
        {
            "criterion": name,
            "expected": expected,
            "actual": actual,
            "pass": bool(passed),
            "explanation": explanation,
        }
        for name, expected, actual, passed, explanation in criteria
    ]
    passed_all = all(row["pass"] for row in rows)
    return {
        "status": "discovery_passed" if passed_all else "discovery_failed",
        "validation_2025_eligible": bool(passed_all),
        "validation_2025_unlocked": bool(passed_all),
        "criteria": rows,
    }


def _diagnostic_metrics(hypothesis_id: str, trades: pd.DataFrame, diagnostics: pd.DataFrame) -> dict[str, Any]:
    baseline = trades.loc[trades["scenario"] == "baseline"].copy() if not trades.empty else pd.DataFrame()
    result: dict[str, Any] = {
        "sizing_rejections": int((diagnostics.get("diagnostic", pd.Series(dtype=str)) == "quantity_below_minimum").sum())
        if not diagnostics.empty
        else 0,
        "stop_distance_mean": float(baseline["stop_distance"].astype(float).mean()) if "stop_distance" in baseline else 0.0,
    }
    if hypothesis_id == "HYP-FCR-02":
        result["trades_by_confirmation_offset"] = (
            baseline["confirmation_offset_bars"].astype(int).value_counts().sort_index().to_dict()
            if "confirmation_offset_bars" in baseline
            else {}
        )
        result["expired_sweeps"] = int(
            diagnostics.get("diagnostic", pd.Series(dtype=str)).isin(["low_sweep_window_expired", "high_sweep_window_expired"]).sum()
        ) if not diagnostics.empty else 0
        result["offset_4_plus_rejections"] = result["expired_sweeps"]
    if hypothesis_id == "HYP-FCR-03":
        diag = diagnostics.get("diagnostic", pd.Series(dtype=str)) if not diagnostics.empty else pd.Series(dtype=str)
        result["exact_or_subtick_touches_rejected"] = int(diag.str.contains("exact_or_subtick_touch_rejected", na=False).sum())
        result["valid_sweeps_with_trades"] = int(len(baseline))
        result["sweep_depth_ticks_mean"] = float(baseline["sweep_depth_ticks"].astype(float).mean()) if "sweep_depth_ticks" in baseline else 0.0
    if hypothesis_id == "HYP-FCR-04":
        result["structural_stop_distance_mean"] = float(baseline["stop_distance"].astype(float).mean()) if "stop_distance" in baseline else 0.0
        result["original_vs_structural_stop_distance_mean"] = (
            float(baseline["structural_stop_distance_from_original"].astype(float).mean())
            if "structural_stop_distance_from_original" in baseline
            else 0.0
        )
        result["structural_segment_bars_mean"] = (
            float(baseline["structural_segment_bars"].astype(float).mean())
            if "structural_segment_bars" in baseline
            else 0.0
        )
        result["additional_sizing_rejections"] = result["sizing_rejections"]
    return result


def _write_variant_outputs(
    *,
    output_dir: Path,
    hypothesis_id: str,
    scenario_frames: dict[str, pd.DataFrame],
    diagnostics: pd.DataFrame,
    dataset_snapshot: dict[str, Any],
    canonical_hashes: dict[str, str],
    pre_run_commit: str,
) -> dict[str, Any]:
    variant_dir = output_dir / hypothesis_id
    variant_dir.mkdir(parents=True, exist_ok=False)
    config_path = Path("configs/research/hypotheses") / f"{hypothesis_id}.yaml"
    shutil.copyfile(config_path, variant_dir / "config_snapshot.yaml")
    sizing_rejections = diagnostics.loc[diagnostics["diagnostic"] == "quantity_below_minimum"].copy() if not diagnostics.empty and "diagnostic" in diagnostics else pd.DataFrame()
    metrics_summary: dict[str, Any] = {}
    serialized_frames: dict[str, pd.DataFrame] = {}
    for scenario, trades in scenario_frames.items():
        frame = trades.copy()
        if not frame.empty:
            frame["year"] = pd.to_datetime(frame["entry_time"], utc=True).dt.year
            frame["entry_hour"] = pd.to_datetime(frame["entry_time"], utc=True).dt.tz_convert("America/New_York").dt.hour
            frame = frame.sort_values(["entry_time", "symbol"], kind="mergesort").reset_index(drop=True)
        rejection_count = int((sizing_rejections["scenario"] == scenario).sum()) if not sizing_rejections.empty else 0
        metrics_summary[scenario] = metrics_for_trades(
            frame,
            initial_equity=FirstCandleConfig().initial_equity * len(SYMBOL_DATASETS),
            sizing_rejections=rejection_count,
        )
        serialized = serialize_trade_frame(frame)
        serialized.to_csv(variant_dir / f"trades_{scenario}.csv", index=False)
        serialized_frames[scenario] = frame
    all_trades = pd.concat(serialized_frames.values(), ignore_index=True)
    metrics_by_symbol = _metrics_by_group(all_trades, ["scenario", "symbol"], initial_equity=FirstCandleConfig().initial_equity, sizing_rejections=sizing_rejections)
    metrics_by_year = _metrics_by_group(all_trades, ["scenario", "year"], initial_equity=FirstCandleConfig().initial_equity * len(SYMBOL_DATASETS), sizing_rejections=sizing_rejections)
    metrics_by_direction = _metrics_by_group(all_trades, ["scenario", "direction"], initial_equity=FirstCandleConfig().initial_equity * len(SYMBOL_DATASETS))
    metrics_by_hour = _metrics_by_group(all_trades, ["scenario", "entry_hour"], initial_equity=FirstCandleConfig().initial_equity * len(SYMBOL_DATASETS))
    metrics_by_symbol.to_csv(variant_dir / "metrics_by_symbol.csv", index=False)
    metrics_by_year.to_csv(variant_dir / "metrics_by_year.csv", index=False)
    metrics_by_direction.to_csv(variant_dir / "metrics_by_direction.csv", index=False)
    metrics_by_hour.to_csv(variant_dir / "metrics_by_hour.csv", index=False)
    sizing_rejections.to_csv(variant_dir / "sizing_rejections.csv", index=False)
    diagnostics.to_csv(variant_dir / "execution_diagnostics.csv", index=False)
    diagnostic_metrics = _diagnostic_metrics(hypothesis_id, all_trades, diagnostics)
    gate = _gate_criteria(metrics_summary, metrics_by_symbol, metrics_by_year)
    run_manifest = {
        "hypothesis_id": hypothesis_id,
        "family_id": FAMILY_ID,
        "execution_mode": "research_primary",
        "period": "discovery",
        "requested_start": DISCOVERY_START,
        "requested_end": DISCOVERY_END,
        "symbols": list(SYMBOL_DATASETS),
        "scenarios": ["baseline", "stress", "severe"],
        "canonical_payload_hash": canonical_hashes[hypothesis_id],
        "pre_run_commit": pre_run_commit,
        "status": gate["status"],
        "validation_2025_eligible": gate["validation_2025_eligible"],
        "validation_executed": False,
        "holdout_executed": False,
        "parity_2026_executed": False,
        "optimization_executed": False,
        "parameter_sweep_executed": False,
        "paper_eligible": False,
        "live_eligible": False,
        "safety_flags": {
            "live_trading": False,
            "broker_connected": False,
            "orders_sent": False,
            "paper_broker_enabled": False,
        },
        "dataset_snapshot_ref": "../dataset_manifest_snapshot.json",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    _write_json(variant_dir / "run_manifest.json", run_manifest)
    _write_json(variant_dir / "metrics_summary.json", metrics_summary)
    _write_json(variant_dir / "diagnostic_metrics.json", diagnostic_metrics)
    _write_json(variant_dir / "gate_evaluation.json", gate)
    output_paths = [
        variant_dir / "run_manifest.json",
        variant_dir / "config_snapshot.yaml",
        variant_dir / "trades_baseline.csv",
        variant_dir / "trades_stress.csv",
        variant_dir / "trades_severe.csv",
        variant_dir / "metrics_summary.json",
        variant_dir / "metrics_by_symbol.csv",
        variant_dir / "metrics_by_year.csv",
        variant_dir / "metrics_by_direction.csv",
        variant_dir / "metrics_by_hour.csv",
        variant_dir / "diagnostic_metrics.json",
        variant_dir / "sizing_rejections.csv",
        variant_dir / "execution_diagnostics.csv",
        variant_dir / "gate_evaluation.json",
    ]
    input_paths = [config_path, *SYMBOL_DATASETS.values(), Path("data/manifests/QQQ_1min_2022-01-01_2026-07-06_curated_manifest.json"), Path("data/manifests/SPY_1min_2022-01-01_2026-07-06_curated_manifest.json")]
    _write_json(variant_dir / "checksums.json", {"inputs": _checksum_payload(input_paths), "outputs": _checksum_payload(output_paths)})
    return {
        "hypothesis_id": hypothesis_id,
        "status": gate["status"],
        "gate_passed": gate["status"] == "discovery_passed",
        "baseline_completed_trades": metrics_summary["baseline"]["completed_trades"],
        "baseline_total_net_pnl": metrics_summary["baseline"]["total_net_pnl"],
        "baseline_net_expectancy_R": metrics_summary["baseline"]["net_expectancy_R"],
        "baseline_profit_factor_net": metrics_summary["baseline"]["profit_factor_net"],
        "baseline_maximum_drawdown": metrics_summary["baseline"]["maximum_drawdown"],
        "stress_net_expectancy_R": metrics_summary["stress"]["net_expectancy_R"],
        "stress_profit_factor_net": metrics_summary["stress"]["profit_factor_net"],
        "severe_net_expectancy_R": metrics_summary["severe"]["net_expectancy_R"],
        "severe_profit_factor_net": metrics_summary["severe"]["profit_factor_net"],
    }


def run_family_discovery(output_dir: str | Path = DEFAULT_OUTPUT_DIR) -> dict[str, Any]:
    output = Path(output_dir)
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite existing family discovery output: {output}")
    canonical_hashes = _assert_expected_hashes()
    pre_run_commit = _git_head()
    calendar = EquitySessionCalendar.from_config({"source": "us_equity"})
    dataset_snapshot, symbol_data = _prepare_symbol_data(calendar)
    output.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(FAMILY_CONFIG_PATH, output / "family_config_snapshot.yaml")
    _write_json(output / "dataset_manifest_snapshot.json", dataset_snapshot)

    variant_summaries: list[dict[str, Any]] = []
    batch_completed: list[str] = []
    for hypothesis_id in VARIANT_IDS:
        scenario_frames: dict[str, list[pd.DataFrame]] = {scenario: [] for scenario in ("baseline", "stress", "severe")}
        diagnostics: list[pd.DataFrame] = []
        for symbol in SYMBOL_DATASETS:
            data = symbol_data[symbol]
            for scenario in ("baseline", "stress", "severe"):
                trades, diag = _simulate_variant_symbol_scenario(
                    hypothesis_id=hypothesis_id,
                    symbol=symbol,
                    scenario=scenario,
                    five=data["five"],
                    minute_by_session=data["minute_by_session"],
                    atr_lookup=data["atr_lookup"],
                    calendar=calendar,
                )
                if not trades.empty:
                    scenario_frames[scenario].append(trades)
                if not diag.empty:
                    diag["symbol"] = symbol
                    diagnostics.append(diag.copy())
        frames = {
            scenario: pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
            for scenario, parts in scenario_frames.items()
        }
        all_diagnostics = pd.concat(diagnostics, ignore_index=True) if diagnostics else pd.DataFrame()
        variant_summary = _write_variant_outputs(
            output_dir=output,
            hypothesis_id=hypothesis_id,
            scenario_frames=frames,
            diagnostics=all_diagnostics,
            dataset_snapshot=dataset_snapshot,
            canonical_hashes=canonical_hashes,
            pre_run_commit=pre_run_commit,
        )
        variant_summaries.append(variant_summary)
        batch_completed.append(hypothesis_id)

    selection = select_family_variant(variant_summaries)
    for variant_summary in variant_summaries:
        variant_summary["family_selection_status"] = selection["variant_statuses"][variant_summary["hypothesis_id"]]
        variant_summary["validation_2025_eligible"] = (
            variant_summary["hypothesis_id"] == selection["selected_hypothesis_id"]
        )
    comparison = pd.DataFrame(variant_summaries)
    comparison.to_csv(output / "family_metrics_comparison.csv", index=False)
    family_gate = {
        "family_id": FAMILY_ID,
        "batch_status": "completed" if tuple(batch_completed) == VARIANT_IDS else "batch_incomplete",
        "completed_variants_before_selection": batch_completed,
        "individual_results": variant_summaries,
    }
    family_manifest = {
        "family_id": FAMILY_ID,
        "execution_mode": "research_primary",
        "period": "discovery",
        "requested_start": DISCOVERY_START,
        "requested_end": DISCOVERY_END,
        "variant_ids": list(VARIANT_IDS),
        "pre_run_commit": pre_run_commit,
        "canonical_hashes": canonical_hashes,
        "selection_applied_after_all_variants_completed": tuple(batch_completed) == VARIANT_IDS,
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
    _write_json(output / "family_run_manifest.json", family_manifest)
    _write_json(output / "family_gate_evaluation.json", family_gate)
    _write_json(output / "family_selection_result.json", selection)
    family_outputs = [
        output / "family_run_manifest.json",
        output / "family_config_snapshot.yaml",
        output / "family_gate_evaluation.json",
        output / "family_selection_result.json",
        output / "family_metrics_comparison.csv",
        output / "dataset_manifest_snapshot.json",
    ]
    family_inputs = [FAMILY_CONFIG_PATH, *[Path("configs/research/hypotheses") / f"{item}.yaml" for item in VARIANT_IDS]]
    _write_json(output / "checksums.json", {"inputs": _checksum_payload(family_inputs), "outputs": _checksum_payload(family_outputs)})
    return {
        "family_run_manifest": family_manifest,
        "family_gate_evaluation": family_gate,
        "family_selection_result": selection,
        "variant_summaries": variant_summaries,
    }


if __name__ == "__main__":
    print(json.dumps(run_family_discovery(), indent=2, sort_keys=True, default=str, allow_nan=False))
