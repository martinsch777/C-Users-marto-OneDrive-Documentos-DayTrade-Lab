from __future__ import annotations

import gc
import json
import math
from pathlib import Path

import pandas as pd

from src.backtesting import (
    BacktestEngine,
    invalidate_signals_after_gaps,
    out_of_sample_from_signals,
    random_entry_signals,
    walk_forward_yearly_from_signals,
)
from src.config import load_config
from src.edge_discovery.labels import add_event_labels
from src.strategy_hunter.pipeline import hunter_dataset_path

from .strategies import build_lead_strategies
from .specialized import import_funding_csv, import_open_interest_csv


LEAD_SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT")
LEAD_TIMEFRAMES = ("1min", "5min", "15min", "30min")
LEAD_SCENARIOS = {
    "low": {"commission_bps": 2.0, "spread_bps": 0.5, "slippage_bps": 0.5},
    "normal": {"commission_bps": 5.0, "spread_bps": 1.0, "slippage_bps": 1.0},
    "high": {"commission_bps": 10.0, "spread_bps": 3.0, "slippage_bps": 3.0},
    "extreme": {"commission_bps": 20.0, "spread_bps": 8.0, "slippage_bps": 8.0},
}


def _engine(config, scenario: dict, setup: str, *, permissive=False):
    risk = dict(config.section("risk"))
    risk["minimum_risk_reward"] = 1.0
    execution = dict(config.section("execution"))
    execution.update(scenario)
    guard = dict(config.section("psychology_guard"))
    guard["allowed_setups"] = list(
        set(guard.get("allowed_setups", []))
        | {setup, "benchmark_random_entry"}
    )
    guard["trading_window_start"] = "00:00"
    guard["trading_window_end"] = "23:59"
    if permissive:
        guard["loss_cooldown_minutes"] = 0
        guard["max_trades_per_hour"] = 100_000
        guard["block_fomo"] = False
        guard["block_unfavorable_regime"] = False
    return BacktestEngine(risk, execution, guard)


def _stats(result) -> dict:
    filled = (
        result.trades[result.trades["status"] == "FILLED"]
        if not result.trades.empty
        else pd.DataFrame()
    )
    positive = (
        float(filled.loc[filled["net_pnl"] > 0, "net_pnl"].sum())
        if len(filled)
        else 0.0
    )
    negative = (
        abs(float(filled.loc[filled["net_pnl"] < 0, "net_pnl"].sum()))
        if len(filled)
        else 0.0
    )
    return {
        **result.metrics,
        "net_pnl": float(filled["net_pnl"].sum()) if len(filled) else 0.0,
        "gross_positive_pnl": positive,
        "gross_negative_pnl": negative,
        "filled_trades": len(filled),
        "blocked_signals": result.blocked_count,
    }


def run_lead_stage(
    symbol: str,
    timeframe: str,
    *,
    output_dir: str | Path,
    config_path: str | Path = "config.yaml",
) -> Path:
    config = load_config(config_path)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    source = hunter_dataset_path(symbol, timeframe)
    prior_quality_path = Path(
        "outputs/daytrade_strategy_hunter/data_quality.csv"
    )
    prior_quality = pd.read_csv(prior_quality_path)
    quality_match = prior_quality[
        (prior_quality["symbol"] == symbol)
        & (prior_quality["timeframe"] == timeframe)
    ]
    if quality_match.empty or not bool(quality_match.iloc[0]["research_usable"]):
        raise ValueError(f"No prior usable audit: {symbol} {timeframe}")
    quality_record = quality_match.iloc[0].to_dict()
    frame = pd.read_csv(
        source,
        dtype={
            "open": "float32",
            "high": "float32",
            "low": "float32",
            "close": "float32",
            "volume": "float32",
        },
    )
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    data = add_event_labels(frame)
    data["atr"] = data["atr_event"]
    del frame
    gc.collect()
    split_position = int(len(data) * 0.70)
    split_timestamp = data.iloc[split_position]["timestamp"]
    oos_frame = data.iloc[split_position:]

    cost_rows = []
    oos_rows = []
    walk_rows = []
    random_rows = []
    trade_rows = []
    for strategy_index, strategy in enumerate(build_lead_strategies()):
        raw_signals = strategy.generate_signals(data, symbol, timeframe)
        signals = invalidate_signals_after_gaps(
            data,
            raw_signals,
            timeframe,
            warmup_bars=200,
        )
        promotion_eligible = bool(
            getattr(strategy, "promotion_eligible", False)
        )
        print(
            f"{symbol} {timeframe} {strategy.name}: {len(signals):,} signals",
            flush=True,
        )
        for scenario_name, scenario in LEAD_SCENARIOS.items():
            full = _engine(config, scenario, strategy.name).run_signals(
                data,
                signals,
                allow_fractional=True,
                collect_blocked_records=False,
            )
            cost_rows.append(
                {
                    "scope": "full",
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "strategy": strategy.name,
                    "hypothesis_id": strategy.hypothesis_id,
                    "promotion_eligible": promotion_eligible,
                    "cost_scenario": scenario_name,
                    "generated_signals": len(signals),
                    **_stats(full),
                }
            )
        oos_results = {}
        for scenario_name in ("normal", "high", "extreme"):
            result = out_of_sample_from_signals(
                data,
                signals,
                _engine(config, LEAD_SCENARIOS[scenario_name], strategy.name),
                allow_fractional=True,
            )
            oos_results[scenario_name] = result
            record = {
                "scope": "oos",
                "symbol": symbol,
                "timeframe": timeframe,
                "strategy": strategy.name,
                "hypothesis_id": strategy.hypothesis_id,
                "promotion_eligible": promotion_eligible,
                "cost_scenario": scenario_name,
                "test_start_utc": split_timestamp,
                "generated_signals": len(signals),
                **_stats(result),
            }
            oos_rows.append(record)
            cost_rows.append(record)
            if not result.trades.empty:
                trade_rows.append(
                    result.trades.assign(
                        dataset=f"{symbol}_{timeframe}",
                        cost_scenario=scenario_name,
                    )
                )
        walk, _ = walk_forward_yearly_from_signals(
            data,
            signals,
            _engine(config, LEAD_SCENARIOS["normal"], strategy.name),
            allow_fractional=True,
        )
        if not walk.empty:
            walk_rows.append(
                walk.assign(
                    symbol=symbol,
                    timeframe=timeframe,
                    strategy=strategy.name,
                    hypothesis_id=strategy.hypothesis_id,
                    promotion_eligible=promotion_eligible,
                )
            )
        templates = [
            signal for signal in signals if signal.timestamp >= split_timestamp
        ]
        target_count = int(oos_results["normal"].metrics["trade_count"])
        seed = 71_000 + strategy_index * 100 + len(symbol) + len(timeframe)
        random_signals = random_entry_signals(
            oos_frame,
            templates,
            symbol,
            timeframe,
            seed=seed,
            count=target_count,
        )
        random_result = _engine(
            config,
            LEAD_SCENARIOS["normal"],
            "benchmark_random_entry",
            permissive=True,
        ).run_signals(
            data,
            random_signals,
            allow_fractional=True,
            collect_blocked_records=False,
        )
        random_rows.append(
            {
                "symbol": symbol,
                "timeframe": timeframe,
                "strategy": strategy.name,
                "hypothesis_id": strategy.hypothesis_id,
                "matched_trade_count": target_count,
                "strategy_oos_net_pnl": _stats(oos_results["normal"])["net_pnl"],
                "random_net_pnl": _stats(random_result)["net_pnl"],
                "strategy_beats_random": (
                    _stats(oos_results["normal"])["net_pnl"]
                    > _stats(random_result)["net_pnl"]
                ),
                "seed": seed,
            }
        )
        gc.collect()
    frames = {
        "cost.csv": pd.DataFrame(cost_rows),
        "oos.csv": pd.DataFrame(oos_rows),
        "walk.csv": (
            pd.concat(walk_rows, ignore_index=True)
            if walk_rows
            else pd.DataFrame()
        ),
        "random.csv": pd.DataFrame(random_rows),
        "trades.csv": (
            pd.concat(trade_rows, ignore_index=True)
            if trade_rows
            else pd.DataFrame()
        ),
        "quality.csv": pd.DataFrame([quality_record]),
    }
    for name, value in frames.items():
        value.to_csv(output / name, index=False)
    (output / "stage_complete.json").write_text(
        json.dumps(
            {
                "status": "complete",
                "symbol": symbol,
                "timeframe": timeframe,
                "rules_frozen": True,
                "live_trading": False,
                "replay": False,
                "paper_internal": False,
                "broker_connected": False,
                "orders_sent": False,
                "real_leverage": False,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return output


def _read(stages: list[Path], name: str) -> pd.DataFrame:
    frames = [
        pd.read_csv(stage / name)
        for stage in stages
        if (stage / name).exists() and (stage / name).stat().st_size > 0
    ]
    return pd.concat(frames, ignore_index=True, sort=False) if frames else pd.DataFrame()


def _aggregate(rows: pd.DataFrame, initial_equity: float) -> dict:
    trades = int(rows["filled_trades"].sum())
    positive = float(rows["gross_positive_pnl"].sum())
    negative = float(rows["gross_negative_pnl"].sum())
    net = float(rows["net_pnl"].sum())
    return {
        "datasets": len(rows),
        "trade_count": trades,
        "net_pnl": net,
        "total_return": net / (initial_equity * max(1, len(rows))),
        "profit_factor": (
            positive / negative
            if negative > 0
            else (math.inf if positive > 0 else 0.0)
        ),
        "expectancy": net / trades if trades else 0.0,
    }


def _summaries(
    oos: pd.DataFrame,
    walk: pd.DataFrame,
    random: pd.DataFrame,
    *,
    initial_equity: float,
) -> pd.DataFrame:
    records = []
    for strategy in sorted(oos["strategy"].unique()):
        scenario_stats = {}
        for scenario in ("normal", "high", "extreme"):
            rows = oos[
                (oos["strategy"] == strategy)
                & (oos["cost_scenario"] == scenario)
            ]
            scenario_stats[scenario] = _aggregate(rows, initial_equity)
        normal_rows = oos[
            (oos["strategy"] == strategy)
            & (oos["cost_scenario"] == "normal")
        ]
        folds = walk[walk["strategy"] == strategy]
        random_rows = random[random["strategy"] == strategy]
        positive_assets = int(
            (normal_rows.groupby("symbol")["net_pnl"].sum() > 0).sum()
        )
        positive_timeframes = int(
            (normal_rows.groupby("timeframe")["net_pnl"].sum() > 0).sum()
        )
        positive_years = int(
            (
                folds.groupby("test_year")["total_return"].sum() > 0
            ).sum()
        ) if len(folds) else 0
        positive_fold_rate = (
            float((folds["total_return"] > 0).mean()) if len(folds) else 0.0
        )
        beats_random_rate = (
            float(random_rows["strategy_beats_random"].astype(bool).mean())
            if len(random_rows)
            else 0.0
        )
        eligible = bool(normal_rows.iloc[0]["promotion_eligible"])
        minimum_trades = 50
        reasons = []
        if not eligible:
            reasons.append("Diagnostic comparator/variant; not promotion eligible")
        if scenario_stats["normal"]["trade_count"] < minimum_trades:
            reasons.append("Fewer than 50 OOS trades")
        if scenario_stats["normal"]["total_return"] <= 0:
            reasons.append("OOS is not positive")
        if scenario_stats["normal"]["profit_factor"] <= 1.25:
            reasons.append("OOS profit factor is not above 1.25")
        if scenario_stats["high"]["total_return"] <= 0:
            reasons.append("High costs remove the edge")
        if positive_years < 2:
            reasons.append("Fewer than two positive OOS years")
        if positive_assets < 2:
            reasons.append("Fewer than two positive assets")
        if beats_random_rate <= 0.50:
            reasons.append("Does not beat random in a majority of datasets")
        if positive_fold_rate < 0.50:
            reasons.append("Fewer than 50% positive walk-forward folds")
        candidate = not reasons
        records.append(
            {
                "strategy": strategy,
                "hypothesis_id": str(normal_rows.iloc[0]["hypothesis_id"]),
                "promotion_eligible": eligible,
                "status": (
                    "candidate_for_replay"
                    if candidate
                    else (
                        "needs_more_testing"
                        if scenario_stats["normal"]["total_return"] > 0
                        and scenario_stats["normal"]["profit_factor"] >= 1.0
                        else "discarded"
                    )
                ),
                "candidate_for_replay": candidate,
                "candidate_for_internal_paper": False,
                "oos_trade_count": scenario_stats["normal"]["trade_count"],
                "oos_total_return": scenario_stats["normal"]["total_return"],
                "oos_profit_factor": scenario_stats["normal"]["profit_factor"],
                "oos_expectancy": scenario_stats["normal"]["expectancy"],
                "high_cost_total_return": scenario_stats["high"]["total_return"],
                "high_cost_profit_factor": scenario_stats["high"]["profit_factor"],
                "extreme_cost_total_return": scenario_stats["extreme"]["total_return"],
                "positive_assets": positive_assets,
                "positive_timeframes": positive_timeframes,
                "positive_oos_years": positive_years,
                "positive_walk_forward_fold_rate": positive_fold_rate,
                "beats_random_dataset_rate": beats_random_rate,
                "reasons": json.dumps(reasons),
            }
        )
    result = pd.DataFrame(records).sort_values(
        ["candidate_for_replay", "oos_profit_factor", "oos_total_return"],
        ascending=[False, False, False],
    ).reset_index(drop=True)
    result.insert(0, "rank", result.index + 1)
    return result


def _html(frame: pd.DataFrame, limit=400) -> str:
    if frame.empty:
        return "<p>Sin datos.</p>"
    return frame.head(limit).to_html(
        index=False,
        border=0,
        classes="data",
        float_format=lambda value: f"{value:.6g}",
    )


def _specialized_quality_and_status() -> tuple[pd.DataFrame, pd.DataFrame]:
    roots = [Path("data/specialized")]
    quality_rows = []
    available = {"funding": set(), "open_interest": set()}
    for symbol in LEAD_SYMBOLS:
        for kind, importer in (
            ("funding", import_funding_csv),
            ("open_interest", import_open_interest_csv),
        ):
            matches = []
            for root in roots:
                matches.extend(root.glob(f"**/{symbol}_{kind}.csv"))
            if not matches:
                quality_rows.append(
                    {
                        "symbol": symbol,
                        "dataset": kind,
                        "status": "missing_local_file",
                        "source_rows": 0,
                        "valid_rows": 0,
                        "invalid_rows": 0,
                        "duplicate_timestamps": 0,
                        "utc": False,
                        "chronological": False,
                        "first_timestamp_utc": "",
                        "last_timestamp_utc": "",
                    }
                )
                continue
            try:
                _frame, report = importer(matches[0])
                quality_rows.append(
                    {
                        "symbol": symbol,
                        "dataset": kind,
                        "status": "valid_local_file",
                        **report,
                    }
                )
                available[kind].add(symbol)
            except Exception as exc:
                quality_rows.append(
                    {
                        "symbol": symbol,
                        "dataset": kind,
                        "status": f"invalid:{type(exc).__name__}:{exc}",
                        "source_rows": 0,
                        "valid_rows": 0,
                        "invalid_rows": 0,
                        "duplicate_timestamps": 0,
                        "utc": False,
                        "chronological": False,
                        "first_timestamp_utc": "",
                        "last_timestamp_utc": "",
                    }
                )
    hypotheses = [
        "funding_extreme_positive_anti_long",
        "funding_extreme_negative_anti_short",
        "funding_positive_price_drop_reversal",
        "funding_negative_price_rise_squeeze",
        "oi_up_price_up",
        "oi_up_price_down",
        "oi_down_price_up",
        "oi_down_price_down",
        "oi_shock_regime_alert",
        "funding_oi_volume_filter_fvg_mss",
    ]
    status_rows = []
    for hypothesis in hypotheses:
        needs_funding = "funding" in hypothesis
        needs_oi = hypothesis.startswith("oi_") or "funding_oi" in hypothesis
        funding_ok = bool(available["funding"]) if needs_funding else True
        oi_ok = bool(available["open_interest"]) if needs_oi else True
        status_rows.append(
            {
                "hypothesis": hypothesis,
                "status": (
                    "ready_for_causal_alignment_test"
                    if funding_ok and oi_ok
                    else "not_tested_missing_historical_data"
                ),
                "funding_symbols_available": len(available["funding"]),
                "oi_symbols_available": len(available["open_interest"]),
                "result": (
                    "No edge conclusion; data unavailable."
                    if not (funding_ok and oi_ok)
                    else "Data present; rerun specialized validation."
                ),
            }
        )
    return pd.DataFrame(quality_rows), pd.DataFrame(status_rows)


def consolidate_leads(
    *,
    stage_root: str | Path = "outputs/lead_validation/staging",
    output_dir: str | Path = "outputs/lead_validation",
    config_path: str | Path = "config.yaml",
) -> Path:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    stages = [
        Path(stage_root) / f"{symbol}_{timeframe}"
        for symbol in LEAD_SYMBOLS
        for timeframe in LEAD_TIMEFRAMES
    ]
    missing = [
        str(stage)
        for stage in stages
        if not (stage / "stage_complete.json").exists()
    ]
    if missing:
        raise FileNotFoundError(f"Incomplete lead stages: {missing}")
    costs = _read(stages, "cost.csv")
    oos = _read(stages, "oos.csv")
    walk = _read(stages, "walk.csv")
    random = _read(stages, "random.csv")
    trades = _read(stages, "trades.csv")
    quality = _read(stages, "quality.csv")
    config = load_config(config_path)
    summary = _summaries(
        oos,
        walk,
        random,
        initial_equity=float(config.section("risk")["initial_equity"]),
    )
    specialized_quality, specialized_status = _specialized_quality_and_status()
    compression = summary[
        summary["hypothesis_id"] == "compression_expansion"
    ].copy()
    fvg = summary[
        summary["hypothesis_id"].isin(
            ["fvg_mss", "rvol_gt_3_breakout_comparator"]
        )
    ].copy()
    year_asset = pd.concat(
        [
            walk.assign(breakdown_type="year_walk_forward"),
            oos[oos["cost_scenario"] == "normal"].assign(
                breakdown_type="asset_timeframe_oos"
            ),
        ],
        ignore_index=True,
        sort=False,
    )
    outputs = {
        "compression_expansion_validation.csv": compression,
        "fvg_mss_rvol_validation.csv": fvg,
        "random_baseline_comparison.csv": random,
        "cost_sensitivity.csv": costs,
        "year_asset_breakdown.csv": year_asset,
        "lead_decisions.csv": summary,
        "oos_results.csv": oos,
        "walk_forward_results.csv": walk,
        "oos_trades.csv": trades,
        "data_quality.csv": quality,
        "funding_oi_data_quality.csv": specialized_quality,
        "funding_oi_hypothesis_status.csv": specialized_status,
    }
    for name, frame in outputs.items():
        frame.to_csv(output / name, index=False)
    candidates = int(summary["candidate_for_replay"].astype(bool).sum())
    report = f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Lead Validation</title><style>
body{{font:14px/1.5 system-ui;margin:2rem auto;max-width:1500px;color:#17212b}}
h1,h2{{color:#0b4f6c}} .warning{{background:#fff3cd;padding:1rem;border-left:5px solid #d99b00}}
.data{{border-collapse:collapse;width:100%;font-size:11px;display:block;overflow:auto;max-height:650px}}
.data th,.data td{{border:1px solid #ccd6df;padding:.3rem;white-space:nowrap}}
.data th{{background:#eaf2f7;position:sticky;top:0}}</style></head><body>
<h1>Lead Validation</h1>
<p class="warning"><strong>Investigación solamente.</strong> Replay, paper,
live, brokers, órdenes y leverage real permanecen bloqueados.</p>
<p>Reglas y comparadores: {len(summary)}. Candidatas a replay: {candidates}.</p>
<h2>Decisiones</h2>{_html(summary)}
<h2>Compression → Expansion</h2>{_html(compression)}
<h2>FVG + MSS + RVOL</h2>{_html(fvg)}
<h2>Random baseline</h2>{_html(random)}
<h2>Costos</h2>{_html(costs)}
<h2>Año / activo / timeframe</h2>{_html(year_asset)}
<h2>Calidad</h2>{_html(quality)}
<h2>Funding / OI: calidad e hipótesis</h2>{_html(specialized_quality)}
{_html(specialized_status)}
</body></html>"""
    destination = output / "lead_validation_report.html"
    destination.write_text(report, encoding="utf-8")
    return destination
