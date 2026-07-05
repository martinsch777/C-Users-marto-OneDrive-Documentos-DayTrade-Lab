from __future__ import annotations

import gc
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from src.backtesting import (
    BacktestEngine,
    out_of_sample_from_signals,
    random_entry_signals,
    walk_forward_yearly_from_signals,
)
from src.config import load_config
from src.data import audit_crypto_csv, load_csv
from src.indicators import add_indicators
from src.strategy_hunter.pipeline import hunter_dataset_path

from .labels import EVENT_LABELS, add_event_labels
from .sources import data_availability_matrix
from .strategies import build_edge_strategies


EDGE_SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT")
EDGE_TIMEFRAMES = ("5min", "15min")
EDGE_SCENARIOS = {
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
        if not filled.empty
        else 0.0
    )
    negative = (
        abs(float(filled.loc[filled["net_pnl"] < 0, "net_pnl"].sum()))
        if not filled.empty
        else 0.0
    )
    return {
        **result.metrics,
        "net_pnl": float(filled["net_pnl"].sum()) if not filled.empty else 0.0,
        "gross_positive_pnl": positive,
        "gross_negative_pnl": negative,
        "filled_trades": len(filled),
        "blocked_signals": result.blocked_count,
        "block_reason_counts": json.dumps(
            result.block_reason_counts or {}, sort_keys=True
        ),
    }


def _event_study(
    data: pd.DataFrame,
    symbol: str,
    timeframe: str,
) -> pd.DataFrame:
    rows = []
    for label in EVENT_LABELS[:6]:
        mask = data[label].astype(bool)
        for horizon in (1, 3, 6):
            future = data["close"].shift(-horizon) / data["close"] - 1
            values = future[mask].dropna()
            if label == "EXTREME_UP_MOVE":
                aligned = -values
                interpretation = "reversal"
            elif label == "EXTREME_DOWN_MOVE":
                aligned = values
                interpretation = "reversal"
            else:
                aligned = values.abs()
                interpretation = "absolute_move"
            rows.append(
                {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "event_label": label,
                    "horizon_bars": horizon,
                    "event_count": len(values),
                    "mean_forward_return": float(values.mean())
                    if len(values)
                    else np.nan,
                    "median_forward_return": float(values.median())
                    if len(values)
                    else np.nan,
                    "positive_forward_rate": float((values > 0).mean())
                    if len(values)
                    else np.nan,
                    "aligned_interpretation": interpretation,
                    "mean_aligned_return": float(aligned.mean())
                    if len(aligned)
                    else np.nan,
                }
            )
    return pd.DataFrame(rows)


def _rare_candidates(
    data: pd.DataFrame,
    symbol: str,
    timeframe: str,
) -> pd.DataFrame:
    recent_start = data["timestamp"].max() - pd.Timedelta(days=90)
    recent = data[data["timestamp"] >= recent_start].copy()
    prior_high = recent["high"].shift(1).rolling(20, min_periods=20).max()
    prior_low = recent["low"].shift(1).rolling(20, min_periods=20).min()
    breakout = (recent["close"] > prior_high) | (recent["close"] < prior_low)
    direction = np.where(recent["close"] > prior_high, "up", "down")
    rare = (
        recent["HIGH_RELATIVE_VOLUME"]
        & (
            recent["EXTREME_UP_MOVE"]
            | recent["EXTREME_DOWN_MOVE"]
        )
        & recent["VOLATILITY_EXPANSION"]
        & breakout
    )
    candidates = recent.loc[
        rare,
        [
            "timestamp",
            "close",
            "volume",
            "relative_volume_event",
            "move_3bar_atr",
            "atr_event",
        ],
    ].copy()
    if candidates.empty:
        return pd.DataFrame(
            columns=[
                "timestamp",
                "symbol",
                "timeframe",
                "direction",
                "close",
                "volume",
                "relative_volume_event",
                "move_3bar_atr",
                "atr_event",
                "spread_status",
                "historical_occurrences_that_utc_day",
                "scanner_decision",
            ]
        )
    candidates["symbol"] = symbol
    candidates["timeframe"] = timeframe
    candidates["direction"] = direction[rare.to_numpy()]
    candidates["utc_day"] = candidates["timestamp"].dt.strftime("%Y-%m-%d")
    daily_count = candidates.groupby("utc_day")["timestamp"].transform("size")
    candidates["historical_occurrences_that_utc_day"] = daily_count
    candidates["spread_status"] = "unknown_in_ohlcv"
    candidates["scanner_decision"] = np.where(
        daily_count > 2,
        "blocked_too_frequent",
        "requires_forward_spread_and_liquidity_confirmation",
    )
    return candidates.drop(columns=["utc_day"]).tail(500)


def run_edge_stage(
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
    frame, _ = load_csv(
        source,
        timeframe,
        asset_class="crypto",
        drop_incomplete=True,
    )
    audit = audit_crypto_csv(source, symbol, timeframe)
    if not audit.research_usable:
        raise ValueError(f"Dataset is not research usable: {symbol} {timeframe}")
    data = add_event_labels(add_indicators(frame, timezone="UTC"))
    del frame
    gc.collect()

    split_position = int(len(data) * 0.70)
    split_timestamp = data.iloc[split_position]["timestamp"]
    oos_frame = data.iloc[split_position:]
    backtest_rows = []
    oos_rows = []
    walk_rows = []
    random_rows = []
    oos_trades = []

    for index, strategy in enumerate(build_edge_strategies()):
        signals = strategy.generate_signals(data, symbol, timeframe)
        print(
            f"{symbol} {timeframe} {strategy.name}: {len(signals):,} signals",
            flush=True,
        )
        for scenario_name, scenario in EDGE_SCENARIOS.items():
            result = _engine(config, scenario, strategy.name).run_signals(
                data,
                signals,
                allow_fractional=True,
                collect_blocked_records=False,
            )
            backtest_rows.append(
                {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "strategy": strategy.name,
                    "hypothesis_id": strategy.hypothesis_id,
                    "economic_rationale": strategy.economic_rationale,
                    "cost_scenario": scenario_name,
                    "generated_signals": len(signals),
                    **_stats(result),
                }
            )
        oos_results = {}
        for scenario_name in ("normal", "high"):
            result = out_of_sample_from_signals(
                data,
                signals,
                _engine(config, EDGE_SCENARIOS[scenario_name], strategy.name),
                allow_fractional=True,
            )
            oos_results[scenario_name] = result
            oos_rows.append(
                {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "strategy": strategy.name,
                    "hypothesis_id": strategy.hypothesis_id,
                    "cost_scenario": scenario_name,
                    "test_start_utc": split_timestamp,
                    **_stats(result),
                }
            )
            if not result.trades.empty:
                oos_trades.append(
                    result.trades.assign(
                        cost_scenario=scenario_name,
                        dataset=f"{symbol}_{timeframe}",
                    )
                )
        walk, _ = walk_forward_yearly_from_signals(
            data,
            signals,
            _engine(config, EDGE_SCENARIOS["normal"], strategy.name),
            allow_fractional=True,
        )
        if not walk.empty:
            walk_rows.append(
                walk.assign(
                    symbol=symbol,
                    timeframe=timeframe,
                    strategy=strategy.name,
                    hypothesis_id=strategy.hypothesis_id,
                )
            )
        templates = [
            signal for signal in signals if signal.timestamp >= split_timestamp
        ]
        target = int(oos_results["normal"].metrics["trade_count"])
        random_signals = random_entry_signals(
            oos_frame,
            templates,
            symbol,
            timeframe,
            seed=44_000 + index * 100 + len(symbol) + len(timeframe),
            count=target,
        )
        random_result = _engine(
            config,
            EDGE_SCENARIOS["normal"],
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
                "matched_trade_count": target,
                "strategy_oos_net_pnl": _stats(oos_results["normal"])["net_pnl"],
                "random_net_pnl": _stats(random_result)["net_pnl"],
                "strategy_beats_random": (
                    _stats(oos_results["normal"])["net_pnl"]
                    > _stats(random_result)["net_pnl"]
                ),
                "seed": 44_000 + index * 100 + len(symbol) + len(timeframe),
            }
        )
        gc.collect()

    frames = {
        "backtest.csv": pd.DataFrame(backtest_rows),
        "oos.csv": pd.DataFrame(oos_rows),
        "walk.csv": (
            pd.concat(walk_rows, ignore_index=True)
            if walk_rows
            else pd.DataFrame()
        ),
        "random.csv": pd.DataFrame(random_rows),
        "oos_trades.csv": (
            pd.concat(oos_trades, ignore_index=True)
            if oos_trades
            else pd.DataFrame()
        ),
        "events.csv": _event_study(data, symbol, timeframe),
        "rare.csv": _rare_candidates(data, symbol, timeframe),
        "quality.csv": pd.DataFrame([audit.to_record()]),
    }
    for name, value in frames.items():
        value.to_csv(output / name, index=False)
    (output / "stage_complete.json").write_text(
        json.dumps(
            {
                "status": "complete",
                "symbol": symbol,
                "timeframe": timeframe,
                "strategies": len(build_edge_strategies()),
                "live_trading": False,
                "broker_connected": False,
                "orders_sent": False,
                "leverage_real": False,
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


def _aggregate_oos(rows: pd.DataFrame, initial_equity: float) -> dict:
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


def _rank_hypotheses(
    oos: pd.DataFrame,
    walk: pd.DataFrame,
    random: pd.DataFrame,
    *,
    initial_equity: float,
) -> pd.DataFrame:
    records = []
    rationale = {
        strategy.name: strategy.economic_rationale
        for strategy in build_edge_strategies()
    }
    for strategy in sorted(oos["strategy"].unique()):
        normal_rows = oos[
            (oos["strategy"] == strategy)
            & (oos["cost_scenario"] == "normal")
        ]
        high_rows = oos[
            (oos["strategy"] == strategy)
            & (oos["cost_scenario"] == "high")
        ]
        normal = _aggregate_oos(normal_rows, initial_equity)
        high = _aggregate_oos(high_rows, initial_equity)
        folds = walk[walk["strategy"] == strategy]
        positive_fold_rate = (
            float((folds["total_return"] > 0).mean()) if len(folds) else 0.0
        )
        random_rows = random[random["strategy"] == strategy]
        beats_random = (
            float(random_rows["strategy_beats_random"].astype(bool).mean())
            if len(random_rows)
            else 0.0
        )
        asset_pnl = normal_rows.groupby("symbol")["net_pnl"].sum()
        positive_assets = int((asset_pnl > 0).sum())
        positive_years = int(
            (
                folds.groupby("test_year")["total_return"].sum() > 0
            ).sum()
        ) if len(folds) else 0
        reasons = []
        if normal["total_return"] <= 0:
            reasons.append("OOS is not positive")
        if normal["profit_factor"] <= 1.25:
            reasons.append("OOS profit factor is not above 1.25")
        if normal["trade_count"] < 100:
            reasons.append("Fewer than 100 OOS trades")
        if high["total_return"] <= 0:
            reasons.append("Does not survive high costs")
        if beats_random <= 0.50:
            reasons.append("Does not beat matched random in a majority of datasets")
        if positive_fold_rate < 0.50:
            reasons.append("Fewer than 50% walk-forward folds are positive")
        if positive_assets < 2:
            reasons.append("Not positive on at least two assets")
        if positive_years < 2:
            reasons.append("Not positive in at least two OOS years")
        candidate = not reasons
        records.append(
            {
                "rank": 0,
                "strategy": strategy,
                "hypothesis_id": str(normal_rows.iloc[0]["hypothesis_id"]),
                "status": (
                    "candidate_for_replay"
                    if candidate
                    else (
                        "discarded"
                        if normal["profit_factor"] < 1
                        or normal["total_return"] <= 0
                        else "needs_more_testing"
                    )
                ),
                "candidate_for_replay": candidate,
                "candidate_for_internal_paper": False,
                "economic_rationale": rationale[strategy],
                "oos_trade_count": normal["trade_count"],
                "oos_total_return": normal["total_return"],
                "oos_profit_factor": normal["profit_factor"],
                "oos_expectancy": normal["expectancy"],
                "high_cost_total_return": high["total_return"],
                "positive_walk_forward_fold_rate": positive_fold_rate,
                "beats_random_dataset_rate": beats_random,
                "positive_assets": positive_assets,
                "positive_oos_years": positive_years,
                "reasons": json.dumps(reasons),
            }
        )
    result = pd.DataFrame(records).sort_values(
        ["candidate_for_replay", "oos_profit_factor", "oos_total_return"],
        ascending=[False, False, False],
    ).reset_index(drop=True)
    result["rank"] = result.index + 1
    return result


def _funding_oi_status() -> pd.DataFrame:
    root = Path("data/specialized")
    rows = []
    for symbol in EDGE_SYMBOLS:
        for dataset in ("funding", "open_interest"):
            matches = list(root.glob(f"**/{symbol}_{dataset}.csv"))
            if not matches:
                rows.append(
                    {
                        "symbol": symbol,
                        "dataset": dataset,
                        "status": "not_tested_missing_local_history",
                        "rows": 0,
                        "extreme_events": 0,
                        "conclusion": (
                            "Public connector exists, but network access was "
                            "unavailable in this execution environment."
                        ),
                    }
                )
                continue
            frame = pd.read_csv(matches[0])
            if dataset == "funding":
                values = pd.to_numeric(frame["funding_rate"], errors="coerce")
                extremes = int((values.abs() >= 0.0005).sum())
            else:
                values = pd.to_numeric(frame["open_interest"], errors="coerce")
                extremes = int(
                    (values.pct_change(fill_method=None).abs() >= 0.05).sum()
                )
            rows.append(
                {
                    "symbol": symbol,
                    "dataset": dataset,
                    "status": "available_local_requires_alignment_test",
                    "rows": len(frame),
                    "extreme_events": extremes,
                    "conclusion": "Parsed; causal candle alignment required before backtest.",
                }
            )
    return pd.DataFrame(rows)


def _prior_strategy_filter_analysis() -> pd.DataFrame:
    hunter_root = Path("outputs/daytrade_strategy_hunter/staging")
    filters = {
        "extreme_move": lambda data: (
            data["EXTREME_UP_MOVE"] | data["EXTREME_DOWN_MOVE"]
        ),
        "high_relative_volume": lambda data: data["HIGH_RELATIVE_VOLUME"],
        "large_wick_reversal": lambda data: data["LARGE_WICK_REVERSAL"],
        "volatility_expansion": lambda data: data["VOLATILITY_EXPANSION"],
        "rare_extreme_volume_expansion": lambda data: (
            (data["EXTREME_UP_MOVE"] | data["EXTREME_DOWN_MOVE"])
            & data["HIGH_RELATIVE_VOLUME"]
            & data["VOLATILITY_EXPANSION"]
        ),
    }
    joined_rows = []
    for symbol in EDGE_SYMBOLS:
        for timeframe in EDGE_TIMEFRAMES:
            trade_path = (
                hunter_root
                / f"{symbol}_{timeframe}"
                / "oos_trades.csv"
            )
            if not trade_path.exists() or trade_path.stat().st_size == 0:
                continue
            trades = pd.read_csv(trade_path)
            trades = trades[
                trades["cost_scenario"].isin(["normal", "high"])
                & (trades["status"] == "FILLED")
            ].copy()
            if trades.empty:
                continue
            frame, _ = load_csv(
                hunter_dataset_path(symbol, timeframe),
                timeframe,
                asset_class="crypto",
                drop_incomplete=True,
            )
            labels = add_event_labels(frame)
            flags = labels[["timestamp"]].copy()
            for name, function in filters.items():
                flags[name] = function(labels).astype(bool)
            trades["timestamp"] = pd.to_datetime(trades["timestamp"], utc=True)
            joined = trades.merge(flags, on="timestamp", how="left")
            joined_rows.append(joined)
            del frame, labels, flags, trades, joined
            gc.collect()
    if not joined_rows:
        return pd.DataFrame(
            columns=[
                "strategy",
                "filter",
                "unfiltered_trades",
                "filtered_trades",
                "retention_rate",
                "unfiltered_expectancy",
                "filtered_expectancy",
                "expectancy_delta",
                "filtered_profit_factor",
                "filtered_net_pnl",
                "improves_expectancy",
                "positive_after_normal_costs",
            ]
        )
    all_trades = pd.concat(joined_rows, ignore_index=True)
    records = []
    for strategy, all_strategy_rows in all_trades.groupby("strategy"):
        strategy_rows = all_strategy_rows[
            all_strategy_rows["cost_scenario"] == "normal"
        ]
        unfiltered_count = len(strategy_rows)
        unfiltered_expectancy = float(strategy_rows["net_pnl"].mean())
        for name in filters:
            selected = strategy_rows[strategy_rows[name].fillna(False).astype(bool)]
            selected_high = all_strategy_rows[
                (all_strategy_rows["cost_scenario"] == "high")
                & all_strategy_rows[name].fillna(False).astype(bool)
            ]
            positive = float(selected["net_pnl"].clip(lower=0).sum())
            negative = abs(float(selected["net_pnl"].clip(upper=0).sum()))
            high_positive = float(selected_high["net_pnl"].clip(lower=0).sum())
            high_negative = abs(
                float(selected_high["net_pnl"].clip(upper=0).sum())
            )
            filtered_expectancy = (
                float(selected["net_pnl"].mean()) if len(selected) else np.nan
            )
            if len(selected):
                exit_time = pd.to_datetime(selected["exit_timestamp"], utc=True)
                selected = selected.assign(exit_year=exit_time.dt.year)
                positive_assets = int(
                    (selected.groupby("symbol")["net_pnl"].sum() > 0).sum()
                )
                positive_years = int(
                    (selected.groupby("exit_year")["net_pnl"].sum() > 0).sum()
                )
            else:
                positive_assets = 0
                positive_years = 0
            records.append(
                {
                    "strategy": strategy,
                    "filter": name,
                    "unfiltered_trades": unfiltered_count,
                    "filtered_trades": len(selected),
                    "retention_rate": len(selected) / unfiltered_count
                    if unfiltered_count
                    else 0.0,
                    "unfiltered_expectancy": unfiltered_expectancy,
                    "filtered_expectancy": filtered_expectancy,
                    "expectancy_delta": (
                        filtered_expectancy - unfiltered_expectancy
                        if len(selected)
                        else np.nan
                    ),
                    "filtered_profit_factor": (
                        positive / negative
                        if negative > 0
                        else (math.inf if positive > 0 else 0.0)
                    ),
                    "filtered_net_pnl": float(selected["net_pnl"].sum()),
                    "high_cost_filtered_net_pnl": float(
                        selected_high["net_pnl"].sum()
                    ),
                    "high_cost_filtered_profit_factor": (
                        high_positive / high_negative
                        if high_negative > 0
                        else (math.inf if high_positive > 0 else 0.0)
                    ),
                    "positive_assets": positive_assets,
                    "positive_years": positive_years,
                    "improves_expectancy": (
                        bool(filtered_expectancy > unfiltered_expectancy)
                        if len(selected)
                        else False
                    ),
                    "positive_after_normal_costs": (
                        bool(selected["net_pnl"].sum() > 0)
                        if len(selected)
                        else False
                    ),
                }
            )
    return pd.DataFrame(records)


def _html_table(frame: pd.DataFrame, limit=300) -> str:
    if frame.empty:
        return "<p>Sin datos.</p>"
    return frame.head(limit).to_html(
        index=False,
        border=0,
        classes="data",
        float_format=lambda value: f"{value:.6g}",
    )


def consolidate_edge_discovery(
    *,
    stage_root: str | Path = "outputs/edge_discovery/staging",
    output_dir: str | Path = "outputs/edge_discovery",
    config_path: str | Path = "config.yaml",
) -> Path:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    stages = [
        Path(stage_root) / f"{symbol}_{timeframe}"
        for symbol in EDGE_SYMBOLS
        for timeframe in EDGE_TIMEFRAMES
    ]
    missing = [
        str(stage)
        for stage in stages
        if not (stage / "stage_complete.json").exists()
    ]
    if missing:
        raise FileNotFoundError(f"Incomplete edge stages: {missing}")
    backtest = _read(stages, "backtest.csv")
    oos = _read(stages, "oos.csv")
    walk = _read(stages, "walk.csv")
    random = _read(stages, "random.csv")
    events = _read(stages, "events.csv")
    rare = _read(stages, "rare.csv")
    quality = _read(stages, "quality.csv")
    config = load_config(config_path)
    ranking = _rank_hypotheses(
        oos,
        walk,
        random,
        initial_equity=float(config.section("risk")["initial_equity"]),
    )
    availability = data_availability_matrix()
    funding_oi = _funding_oi_status()
    prior_filters = _prior_strategy_filter_analysis()
    orderbook = availability[
        availability["dataset"].str.contains(
            "Order book|Liquidation|Aggregate trades", regex=True
        )
    ].copy()
    history_status = Path("data/forward_collector/collector_status_history.csv")
    if history_status.exists():
        collector_status = pd.read_csv(history_status).tail(200)
    else:
        collector_status = pd.DataFrame(
            [
                {
                    "collected_at_utc": "",
                    "symbol": symbol,
                    "status": "not_started_default_safe_state",
                    "orderbook": False,
                    "recent_trades": 0,
                    "open_interest": False,
                    "funding": False,
                    "liquidations": False,
                    "orders_sent": False,
                    "broker_connected": False,
                    "error": "Network collection was not run in this session.",
                }
                for symbol in EDGE_SYMBOLS
            ]
        )
    outputs = {
        "data_availability_matrix.csv": availability,
        "edge_hypothesis_results.csv": ranking,
        "funding_oi_analysis.csv": funding_oi,
        "extreme_move_analysis.csv": events,
        "orderbook_feasibility.csv": orderbook,
        "rare_setup_scanner.csv": rare,
        "collector_status.csv": collector_status,
        "prior_strategy_filter_analysis.csv": prior_filters,
        "backtest_results.csv": backtest,
        "oos_results.csv": oos,
        "walk_forward_results.csv": walk,
        "random_baseline_comparison.csv": random,
        "data_quality.csv": quality,
    }
    for name, frame in outputs.items():
        frame.to_csv(output / name, index=False)
    candidates = int(ranking["candidate_for_replay"].astype(bool).sum())
    report = f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>DayTrade Edge Discovery</title><style>
body{{font:14px/1.5 system-ui;margin:2rem auto;max-width:1500px;color:#17212b}}
h1,h2{{color:#0b4f6c}} .warning{{background:#fff3cd;padding:1rem;border-left:5px solid #d99b00}}
.data{{border-collapse:collapse;width:100%;font-size:11px;display:block;overflow:auto;max-height:650px}}
.data th,.data td{{border:1px solid #ccd6df;padding:.3rem;white-space:nowrap}}
.data th{{background:#eaf2f7;position:sticky;top:0}}</style></head><body>
<h1>DayTrade Edge Discovery</h1>
<p class="warning"><strong>Investigación solamente.</strong> Sin live trading,
broker, órdenes, leverage real ni claves privadas.</p>
<p>Hipótesis testeadas: {len(ranking)}. Candidatas a replay: {candidates}.</p>
<h2>Ranking</h2>{_html_table(ranking)}
<h2>Disponibilidad y costo de datos</h2>{_html_table(availability)}
<h2>Funding / open interest</h2>{_html_table(funding_oi)}
<h2>Eventos extremos</h2>{_html_table(events)}
<h2>Order book y liquidaciones</h2>{_html_table(orderbook)}
<h2>Rare Setup Scanner</h2>{_html_table(rare)}
<h2>Collector</h2>{_html_table(collector_status)}
<h2>OOS</h2>{_html_table(oos)}
<h2>Walk-forward</h2>{_html_table(walk)}
<h2>Random baseline</h2>{_html_table(random)}
<h2>Filtros de eventos sobre estrategias previas</h2>{_html_table(prior_filters)}
</body></html>"""
    destination = output / "edge_discovery_report.html"
    destination.write_text(report, encoding="utf-8")
    return destination
