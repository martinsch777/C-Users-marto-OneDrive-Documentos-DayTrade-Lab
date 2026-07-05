from __future__ import annotations

import gc
import json
import math
from dataclasses import replace
from pathlib import Path

import pandas as pd

from src.backtesting import (
    BacktestEngine,
    add_market_context,
    attach_market_context,
    calculate_metrics,
    invalidate_signals_after_gaps,
    metrics_by_dimension,
    out_of_sample_from_signals,
    permissive_psychology_config,
    random_entry_signals,
    walk_forward_yearly_from_signals,
)
from src.config import LabConfig, load_config
from src.data import audit_crypto_csv, load_csv
from src.reports.strategy_hunter_writer import (
    StrategyHunterReportBundle,
    StrategyHunterReportWriter,
)
from src.strategies import Signal

from .catalog import StrategyCatalog
from .costs import CostBreakEvenAnalyzer, PlatformCostCatalog
from .scoring import PretestScorer
from .strategies import add_hunter_indicators, build_hunter_strategies


HUNTER_SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT")
HUNTER_TIMEFRAMES = ("1min", "5min", "15min", "30min")
HUNTER_SCENARIOS = {
    "low": {"commission_bps": 10.0, "spread_bps": 0.5, "slippage_bps": 0.5},
    "normal": {"commission_bps": 10.0, "spread_bps": 1.0, "slippage_bps": 1.0},
    "high": {"commission_bps": 10.0, "spread_bps": 3.0, "slippage_bps": 3.0},
    "extreme": {"commission_bps": 20.0, "spread_bps": 8.0, "slippage_bps": 8.0},
}

TREND_FAMILIES = {
    "ema_9_21_vwap_scalping",
    "supertrend_ema200",
    "macd_rsi_scalping",
    "heikin_ashi_ema_trend",
    "donchian_intraday_breakout",
}
REVERSION_FAMILIES = {
    "bollinger_rsi_reversion",
    "vwap_deviation_reversion",
}


def hunter_dataset_path(symbol: str, timeframe: str) -> Path:
    return Path("data") / "crypto" / "binance" / f"{symbol}_{timeframe}.csv"


def _execution(config: LabConfig, scenario: dict) -> dict:
    values = dict(config.section("execution"))
    values.update(scenario)
    return values


def _psychology(
    config: LabConfig,
    setup: str,
    *,
    permissive: bool = False,
) -> dict:
    values = dict(config.section("psychology_guard"))
    values["trading_window_start"] = "00:00"
    values["trading_window_end"] = "23:59"
    values["allowed_setups"] = list(
        set(values.get("allowed_setups", [])) | {setup, "benchmark_random_entry"}
    )
    if permissive:
        values = permissive_psychology_config(values, setup)
        values["block_unfavorable_regime"] = False
    return values


def _engine(
    config: LabConfig,
    scenario: dict,
    setup: str,
    *,
    permissive: bool = False,
) -> BacktestEngine:
    return BacktestEngine(
        config.section("risk"),
        _execution(config, scenario),
        _psychology(config, setup, permissive=permissive),
    )


def _statistics(result) -> dict:
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
        "winning_trades": int((filled["net_pnl"] > 0).sum())
        if not filled.empty
        else 0,
        "filled_trades": len(filled),
        "blocked_signals": result.blocked_count,
        "block_reason_counts": json.dumps(
            result.block_reason_counts or {},
            sort_keys=True,
        ),
    }


def _mark_regimes(
    signals: list[Signal],
    context: pd.DataFrame,
    family_id: str,
) -> list[Signal]:
    if not signals:
        return signals
    regime = context.set_index("timestamp")["regime"]
    adjusted = []
    for signal in signals:
        label = str(regime.get(signal.timestamp, "range"))
        unfavorable = (
            family_id in TREND_FAMILIES and label == "range"
        ) or (
            family_id in REVERSION_FAMILIES and label != "range"
        )
        metadata = {
            **signal.metadata,
            "market_regime": label,
            "unfavorable_regime": unfavorable,
            "regime_block_details": (
                f"{family_id} is pre-registered as unfavorable in {label}"
            ),
        }
        adjusted.append(replace(signal, metadata=metadata))
    return adjusted


def _compact_oos(trades: pd.DataFrame, dataset: str, scenario: str) -> pd.DataFrame:
    columns = [
        "timestamp",
        "symbol",
        "timeframe",
        "strategy",
        "status",
        "entry_timestamp",
        "exit_timestamp",
        "net_pnl",
        "total_cost",
        "duration_minutes",
    ]
    if trades.empty:
        return pd.DataFrame(columns=columns + ["dataset", "cost_scenario"])
    return trades[
        [column for column in columns if column in trades.columns]
    ].assign(dataset=dataset, cost_scenario=scenario)


def run_hunter_stage(
    symbol: str,
    timeframe: str,
    *,
    output_dir: str | Path,
    config_path: str | Path = "config.yaml",
    strategies=None,
) -> Path:
    config = load_config(config_path)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    source = hunter_dataset_path(symbol, timeframe)
    frame, report = load_csv(
        source,
        timeframe,
        asset_class="crypto",
        drop_incomplete=True,
    )
    audit = audit_crypto_csv(source, symbol, timeframe)
    if not audit.research_usable:
        raise ValueError(f"Dataset is not research usable: {symbol} {timeframe}")
    enriched = add_hunter_indicators(frame, timezone="UTC")
    context = add_market_context(frame)
    del frame
    gc.collect()

    backtest_rows: list[dict] = []
    oos_rows: list[dict] = []
    walk_rows: list[pd.DataFrame] = []
    random_rows: list[dict] = []
    dimension_rows: list[pd.DataFrame] = []
    psychology_rows: list[dict] = []
    oos_trade_rows: list[pd.DataFrame] = []
    split_position = int(len(enriched) * 0.70)
    split_timestamp = enriched.iloc[split_position]["timestamp"]
    oos_frame = enriched.iloc[split_position:].reset_index(drop=True)

    selected_strategies = (
        list(strategies) if strategies is not None else build_hunter_strategies()
    )
    for strategy_index, strategy in enumerate(selected_strategies):
        family_id = strategy.family_id
        raw_signals = strategy.generate_signals(enriched, symbol, timeframe)
        signals = invalidate_signals_after_gaps(
            enriched,
            _mark_regimes(raw_signals, context, family_id),
            timeframe,
            warmup_bars=200,
        )
        print(
            f"{symbol} {timeframe} {strategy.name}: {len(signals):,} signals",
            flush=True,
        )
        scenario_results = {}
        for scenario_name, scenario in HUNTER_SCENARIOS.items():
            result = _engine(config, scenario, strategy.name).run_signals(
                enriched,
                signals,
                allow_fractional=True,
                collect_blocked_records=False,
            )
            scenario_results[scenario_name] = result
            backtest_rows.append(
                {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "strategy": strategy.name,
                    "family_id": family_id,
                    "cost_scenario": scenario_name,
                    "generated_signals": len(signals),
                    **_statistics(result),
                }
            )

        normal = scenario_results["normal"]
        permissive = _engine(
            config,
            HUNTER_SCENARIOS["normal"],
            strategy.name,
            permissive=True,
        ).run_signals(
            enriched,
            signals,
            allow_fractional=True,
            collect_blocked_records=False,
        )
        psychology_rows.append(
            {
                "symbol": symbol,
                "timeframe": timeframe,
                "strategy": strategy.name,
                "family_id": family_id,
                "generated_signals": len(signals),
                "allowed_attempts": len(normal.trades),
                "blocked_signals": normal.blocked_count,
                "allowed_rate": len(normal.trades) / len(signals) if signals else 0.0,
                "guarded_net_pnl": _statistics(normal)["net_pnl"],
                "permissive_net_pnl": _statistics(permissive)["net_pnl"],
                "guard_pnl_delta": _statistics(normal)["net_pnl"]
                - _statistics(permissive)["net_pnl"],
                "block_reason_counts": json.dumps(
                    normal.block_reason_counts or {},
                    sort_keys=True,
                ),
            }
        )

        normal_context = attach_market_context(normal.trades, context)
        for dimension in ("utc_hour", "year", "regime", "volatility_bucket"):
            values = metrics_by_dimension(
                normal_context,
                dimension,
                initial_equity=float(config.section("risk")["initial_equity"]),
            )
            if not values.empty:
                dimension_rows.append(
                    values.assign(
                        symbol=symbol,
                        timeframe=timeframe,
                        strategy=strategy.name,
                        family_id=family_id,
                        dimension_type=dimension,
                        dimension_value=values[dimension].astype(str),
                    ).drop(columns=[dimension])
                )

        oos_results = {}
        for scenario_name in ("normal", "high"):
            oos = out_of_sample_from_signals(
                enriched,
                signals,
                _engine(config, HUNTER_SCENARIOS[scenario_name], strategy.name),
                allow_fractional=True,
            )
            oos_results[scenario_name] = oos
            oos_rows.append(
                {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "strategy": strategy.name,
                    "family_id": family_id,
                    "cost_scenario": scenario_name,
                    "test_start_utc": split_timestamp,
                    **_statistics(oos),
                }
            )
            oos_trade_rows.append(
                _compact_oos(
                    oos.trades,
                    f"{symbol}_{timeframe}",
                    scenario_name,
                )
            )

        walk, _ = walk_forward_yearly_from_signals(
            enriched,
            signals,
            _engine(config, HUNTER_SCENARIOS["normal"], strategy.name),
            allow_fractional=True,
        )
        if not walk.empty:
            walk_rows.append(
                walk.assign(
                    symbol=symbol,
                    timeframe=timeframe,
                    strategy=strategy.name,
                    family_id=family_id,
                )
            )

        template_oos = [
            signal for signal in signals if signal.timestamp >= split_timestamp
        ]
        target_count = oos_results["normal"].metrics["trade_count"]
        random_signals = random_entry_signals(
            oos_frame,
            template_oos,
            symbol,
            timeframe,
            seed=1000 + strategy_index * 100 + len(symbol) + len(timeframe),
            count=target_count,
        )
        random_result = _engine(
            config,
            HUNTER_SCENARIOS["normal"],
            "benchmark_random_entry",
            permissive=True,
        ).run_signals(
            enriched,
            random_signals,
            allow_fractional=True,
            collect_blocked_records=False,
        )
        random_rows.append(
            {
                "symbol": symbol,
                "timeframe": timeframe,
                "strategy": strategy.name,
                "family_id": family_id,
                "target_trade_count": target_count,
                "random_generated_signals": len(random_signals),
                "strategy_oos_net_pnl": _statistics(oos_results["normal"])["net_pnl"],
                "strategy_oos_profit_factor": oos_results["normal"].metrics[
                    "profit_factor"
                ],
                "random_net_pnl": _statistics(random_result)["net_pnl"],
                "random_profit_factor": random_result.metrics["profit_factor"],
                "random_trade_count": random_result.metrics["trade_count"],
                "strategy_beats_random": _statistics(oos_results["normal"])["net_pnl"]
                > _statistics(random_result)["net_pnl"],
            }
        )
        del raw_signals, signals, scenario_results, permissive, random_result
        gc.collect()

    frames = {
        "backtest_results.csv": pd.DataFrame(backtest_rows),
        "oos_results.csv": pd.DataFrame(oos_rows),
        "walk_forward_results.csv": (
            pd.concat(walk_rows, ignore_index=True) if walk_rows else pd.DataFrame()
        ),
        "random_baseline_comparison.csv": pd.DataFrame(random_rows),
        "dimensions.csv": (
            pd.concat(dimension_rows, ignore_index=True)
            if dimension_rows
            else pd.DataFrame()
        ),
        "psychology.csv": pd.DataFrame(psychology_rows),
        "oos_trades.csv": (
            pd.concat(oos_trade_rows, ignore_index=True)
            if oos_trade_rows
            else pd.DataFrame()
        ),
        "data_quality.csv": pd.DataFrame([audit.to_record()]),
    }
    for name, result_frame in frames.items():
        result_frame.to_csv(output / name, index=False)
    marker = {
        "status": "complete",
        "symbol": symbol,
        "timeframe": timeframe,
        "strategies_tested": len(selected_strategies),
        "live_trading_enabled": False,
        "broker_connected": False,
        "orders_sent": False,
    }
    (output / "stage_complete.json").write_text(
        json.dumps(marker, indent=2),
        encoding="utf-8",
    )
    return output


def _read_stages(stage_dirs: list[Path], name: str) -> pd.DataFrame:
    frames = [
        pd.read_csv(directory / name)
        for directory in stage_dirs
        if (directory / name).exists() and (directory / name).stat().st_size > 0
    ]
    return pd.concat(frames, ignore_index=True, sort=False) if frames else pd.DataFrame()


def _aggregate(rows: pd.DataFrame, group: str, initial_equity: float) -> pd.DataFrame:
    records = []
    for value, subset in rows.groupby(group):
        trades = int(subset["filled_trades"].sum())
        positive = float(subset["gross_positive_pnl"].sum())
        negative = float(subset["gross_negative_pnl"].sum())
        net = float(subset["net_pnl"].sum())
        records.append(
            {
                group: value,
                "datasets": len(subset),
                "trade_count": trades,
                "net_pnl": net,
                "total_return": net / (initial_equity * max(1, len(subset))),
                "profit_factor": (
                    positive / negative
                    if negative > 0
                    else (math.inf if positive > 0 else 0.0)
                ),
                "expectancy": net / trades if trades else 0.0,
                "win_rate": float(subset["winning_trades"].sum()) / trades
                if trades
                else 0.0,
                "maximum_dataset_drawdown": float(subset["max_drawdown"].max()),
                "total_cost": float(subset["total_cost"].sum()),
            }
        )
    return pd.DataFrame(records)


def _candidate_decisions(
    oos: pd.DataFrame,
    oos_trades: pd.DataFrame,
    walk: pd.DataFrame,
    random: pd.DataFrame,
    scoring: pd.DataFrame,
    *,
    initial_equity: float,
) -> pd.DataFrame:
    records = []
    for strategy in sorted(oos["strategy"].unique()):
        normal_rows = oos[
            (oos["strategy"] == strategy) & (oos["cost_scenario"] == "normal")
        ]
        high_rows = oos[
            (oos["strategy"] == strategy) & (oos["cost_scenario"] == "high")
        ]
        normal_trades = oos_trades[
            (oos_trades["strategy"] == strategy)
            & (oos_trades["cost_scenario"] == "normal")
            & (oos_trades["status"] == "FILLED")
        ].copy()
        normal_stats = _aggregate(
            normal_rows.assign(group_key=strategy),
            "group_key",
            initial_equity,
        ).iloc[0]
        high_stats = _aggregate(
            high_rows.assign(group_key=strategy),
            "group_key",
            initial_equity,
        ).iloc[0]
        strategy_walk = walk[walk["strategy"] == strategy]
        positive_fold_rate = (
            float((strategy_walk["total_return"] > 0).mean())
            if not strategy_walk.empty
            else 0.0
        )
        random_rows = random[random["strategy"] == strategy]
        beats_random_rate = (
            float(random_rows["strategy_beats_random"].astype(bool).mean())
            if not random_rows.empty
            else 0.0
        )
        reasons = []
        if normal_stats["total_return"] <= 0:
            reasons.append("OOS result is not positive")
        if normal_stats["profit_factor"] <= 1.25:
            reasons.append("OOS profit factor is not above 1.25")
        if normal_stats["trade_count"] < 100:
            reasons.append("Fewer than 100 OOS trades")
        if high_stats["total_return"] <= 0:
            reasons.append("High costs destroy profitability")
        if positive_fold_rate < 0.50:
            reasons.append("Fewer than 50% walk-forward folds are positive")
        if beats_random_rate < 0.50:
            reasons.append("Does not beat matched random entry in a majority of datasets")
        if normal_stats["expectancy"] <= 0:
            reasons.append("OOS expectancy is not positive")
        if not normal_trades.empty:
            exit_time = pd.to_datetime(normal_trades["exit_timestamp"], utc=True)
            normal_trades["year"] = exit_time.dt.year
            normal_trades["utc_hour"] = exit_time.dt.hour
            positive_total = float(normal_trades["net_pnl"].clip(lower=0).sum())
            for column, label, threshold in (
                ("symbol", "asset", 0.70),
                ("year", "year", 0.50),
                ("utc_hour", "UTC hour", 0.50),
            ):
                grouped = normal_trades.groupby(column)["net_pnl"].sum().clip(lower=0)
                if positive_total > 0 and not grouped.empty and grouped.max() / positive_total > threshold:
                    reasons.append(f"Depends too much on one {label}")
            largest_share = (
                float(normal_trades["net_pnl"].clip(lower=0).max()) / positive_total
                if positive_total > 0
                else 0.0
            )
            if largest_share > 0.25:
                reasons.append("One trade contributes more than 25% of positive PnL")
        else:
            largest_share = 0.0
        family_id = str(normal_rows.iloc[0]["family_id"])
        pretest = scoring[scoring["strategy_id"] == family_id]
        if pretest.empty or pretest.iloc[0]["classification"] == "rejected_before_test":
            reasons.append("Pretest programmability/repainting gate failed")
        candidate = not reasons
        status = (
            "candidate_for_replay"
            if candidate
            else (
                "discarded"
                if normal_stats["total_return"] <= 0
                or normal_stats["profit_factor"] < 1.0
                else "needs_more_testing"
            )
        )
        records.append(
            {
                "rank": 0,
                "strategy": strategy,
                "family_id": family_id,
                "status": status,
                "candidate_for_replay": candidate,
                "candidate_for_internal_paper": False,
                "oos_trade_count": int(normal_stats["trade_count"]),
                "oos_total_return": normal_stats["total_return"],
                "oos_profit_factor": normal_stats["profit_factor"],
                "oos_expectancy": normal_stats["expectancy"],
                "high_cost_total_return": high_stats["total_return"],
                "positive_walk_forward_fold_rate": positive_fold_rate,
                "beats_random_dataset_rate": beats_random_rate,
                "largest_positive_trade_share": largest_share,
                "reasons": json.dumps(reasons, ensure_ascii=False),
            }
        )
    result = pd.DataFrame(records).sort_values(
        ["candidate_for_replay", "oos_profit_factor", "oos_total_return"],
        ascending=[False, False, False],
    ).reset_index(drop=True)
    result["rank"] = result.index + 1
    return result


def consolidate_hunter(
    *,
    stage_root: str | Path = "outputs/daytrade_strategy_hunter/staging",
    variant_stage_root: str | Path = "outputs/daytrade_strategy_hunter/staging_variants",
    output_dir: str | Path = "outputs/daytrade_strategy_hunter",
    config_path: str | Path = "config.yaml",
) -> Path:
    config = load_config(config_path)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    primary_stage_dirs = [
        Path(stage_root) / f"{symbol}_{timeframe}"
        for symbol in HUNTER_SYMBOLS
        for timeframe in HUNTER_TIMEFRAMES
    ]
    variant_stage_dirs = [
        Path(variant_stage_root) / f"{symbol}_{timeframe}"
        for symbol in HUNTER_SYMBOLS
        for timeframe in HUNTER_TIMEFRAMES
    ]
    stage_dirs = primary_stage_dirs + variant_stage_dirs
    missing = [
        str(path)
        for path in stage_dirs
        if not (path / "stage_complete.json").exists()
    ]
    if missing:
        raise FileNotFoundError(f"Incomplete Strategy Hunter stages: {missing}")
    backtest = _read_stages(stage_dirs, "backtest_results.csv")
    oos = _read_stages(stage_dirs, "oos_results.csv")
    walk = _read_stages(stage_dirs, "walk_forward_results.csv")
    random = _read_stages(stage_dirs, "random_baseline_comparison.csv")
    dimensions = _read_stages(stage_dirs, "dimensions.csv")
    psychology = _read_stages(stage_dirs, "psychology.csv")
    oos_trades = _read_stages(stage_dirs, "oos_trades.csv")
    quality = _read_stages(stage_dirs, "data_quality.csv")
    if not quality.empty:
        quality = quality.drop_duplicates(
            subset=["symbol", "timeframe"],
            keep="first",
        ).reset_index(drop=True)

    catalog = StrategyCatalog.load()
    scoring = PretestScorer({"OHLCV"}).score_catalog(catalog)
    platforms = PlatformCostCatalog.load()
    platform_frame = platforms.to_frame()
    break_even = CostBreakEvenAnalyzer(platforms).analyze()
    initial_equity = float(config.section("risk")["initial_equity"])
    candidates = _candidate_decisions(
        oos,
        oos_trades,
        walk,
        random,
        scoring,
        initial_equity=initial_equity,
    )

    required_outputs = {
        "strategy_catalog.csv": catalog.to_frame(),
        "pretest_scoring.csv": scoring,
        "cost_break_even.csv": break_even,
        "platform_cost_comparison.csv": platform_frame,
        "backtest_results.csv": backtest,
        "oos_results.csv": oos,
        "walk_forward_results.csv": walk,
        "random_baseline_comparison.csv": random,
        "strategy_ranking.csv": candidates,
        "psychology_guard_results.csv": psychology,
        "dimension_results.csv": dimensions,
        "data_quality.csv": quality,
    }
    for name, frame in required_outputs.items():
        frame.to_csv(output / name, index=False)
    report = StrategyHunterReportWriter(output).write(
        StrategyHunterReportBundle(
            catalog=catalog.to_frame(),
            scoring=scoring,
            platforms=platform_frame,
            break_even=break_even,
            backtest=backtest,
            oos=oos,
            walk_forward=walk,
            random=random,
            ranking=candidates,
            psychology=psychology,
            quality=quality,
        )
    )
    return report
