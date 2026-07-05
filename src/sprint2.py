from __future__ import annotations

import argparse
import json
import math
from copy import deepcopy
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd

from src.backtesting import (
    BacktestEngine,
    add_market_context,
    attach_market_context,
    calculate_metrics,
    evaluate_replay_candidate,
    intraday_buy_hold_trades,
    invalidate_signals_after_gaps,
    metrics_by_dimension,
    momentum_benchmark_signals,
    out_of_sample_from_signals,
    permissive_psychology_config,
    psychology_impact,
    random_entry_signals,
    walk_forward_yearly_from_signals,
)
from src.config import LabConfig, load_config
from src.data import (
    BinancePublicDataProvider,
    audit_crypto_csv,
    load_csv,
)
from src.reports import RealDataReportBundle, RealDataReportWriter
from src.strategies import Signal, build_strategies


SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
TIMEFRAMES = ("5min", "15min", "30min")
MAIN_SCENARIOS = ("low", "normal", "high", "extreme")
STRATEGY_NAMES = (
    "opening_range_breakout",
    "vwap_pullback",
    "relative_volume_momentum",
    "extreme_mean_reversion",
    "trend_day_continuation",
)


def dataset_path(symbol: str, timeframe: str) -> Path:
    return Path("data") / "crypto" / "binance" / f"{symbol}_{timeframe}.csv"


def _utc(value: str | pd.Timestamp) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    return (
        timestamp.tz_localize("UTC")
        if timestamp.tzinfo is None
        else timestamp.tz_convert("UTC")
    )


def download_datasets(
    *,
    start: str = "2022-01-01",
    end: str | None = None,
    resume: bool = True,
) -> pd.DataFrame:
    provider = BinancePublicDataProvider()
    records: list[dict] = []
    effective_end = end or pd.Timestamp.now(tz="UTC").isoformat()
    for symbol in SYMBOLS:
        for timeframe in TIMEFRAMES:
            path = dataset_path(symbol, timeframe)
            print(f"Downloading {symbol} {timeframe} -> {path}", flush=True)
            metadata = provider.download_history_archives(
                symbol,
                timeframe,
                start,
                effective_end,
                path,
            )
            records.append(metadata)
            print(
                f"  {metadata['final_rows']:,} rows, "
                f"missing={metadata['missing_bars']}, "
                f"REST requests={metadata['rest_requests']}",
                flush=True,
            )
    return pd.DataFrame(records)


def audit_datasets(
    *,
    output_dir: str | Path = "outputs/daytrade",
    symbols: tuple[str, ...] = SYMBOLS,
    timeframes: tuple[str, ...] = TIMEFRAMES,
) -> pd.DataFrame:
    records = []
    for symbol in symbols:
        for timeframe in timeframes:
            path = dataset_path(symbol, timeframe)
            if not path.exists():
                raise FileNotFoundError(f"Missing required dataset: {path}")
            records.append(
                audit_crypto_csv(path, symbol, timeframe).to_record()
            )
    quality = pd.DataFrame(records)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    quality.to_csv(output / "real_data_data_quality.csv", index=False)
    RealDataReportWriter(output).write_quality_report(quality)
    return quality


def _crypto_psychology(config: dict, extra_setup: str | None = None) -> dict:
    values = deepcopy(config)
    values["trading_window_start"] = "00:00"
    values["trading_window_end"] = "23:59"
    if extra_setup:
        values = permissive_psychology_config(values, extra_setup)
    return values


def _execution_config(config: LabConfig, costs: dict) -> dict:
    execution = deepcopy(config.section("execution"))
    execution.update(costs)
    return execution


def _engine(
    config: LabConfig,
    execution: dict,
    *,
    extra_setup: str | None = None,
    permissive: bool = False,
) -> BacktestEngine:
    psychology = _crypto_psychology(config.section("psychology_guard"))
    if permissive and extra_setup:
        psychology = permissive_psychology_config(psychology, extra_setup)
    elif extra_setup:
        psychology["allowed_setups"] = list(
            set(psychology.get("allowed_setups", [])) | {extra_setup}
        )
    return BacktestEngine(config.section("risk"), execution, psychology)


def _result_statistics(
    result,
    *,
    initial_equity: float,
) -> dict:
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
    }


TRADE_COLUMNS = [
    "timestamp",
    "symbol",
    "timeframe",
    "strategy",
    "side",
    "entry_price",
    "stop_price",
    "take_profit",
    "risk_reward",
    "status",
    "filled_quantity",
    "entry_timestamp",
    "exit_timestamp",
    "exit_price",
    "gross_pnl",
    "commission",
    "spread_cost",
    "slippage_cost",
    "total_cost",
    "net_pnl",
    "exit_reason",
    "duration_minutes",
    "position_size",
    "risk_amount",
]

BLOCK_COLUMNS = [
    "timestamp",
    "symbol",
    "timeframe",
    "strategy",
    "side",
    "entry_price",
    "stop_price",
    "take_profit",
    "risk_reward",
    "block_reason",
    "block_details",
]


def _compact(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=columns)
    return frame.loc[:, [column for column in columns if column in frame.columns]].copy()


def _append_csv(path: Path, frame: pd.DataFrame) -> None:
    if frame.empty:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(
        path,
        mode="a",
        header=not path.exists() or path.stat().st_size == 0,
        index=False,
    )


def _aggregate_strategy_rows(summary: pd.DataFrame, initial_equity: float) -> pd.DataFrame:
    if summary.empty:
        return pd.DataFrame()
    records = []
    grouped = summary.groupby(["strategy", "cost_scenario"], dropna=False)
    for (strategy, scenario), subset in grouped:
        trades = int(subset["filled_trades"].sum())
        positive = float(subset["gross_positive_pnl"].sum())
        negative = float(subset["gross_negative_pnl"].sum())
        net = float(subset["net_pnl"].sum())
        records.append(
            {
                "experiment_type": "strategy",
                "strategy": strategy,
                "cost_scenario": scenario,
                "datasets": len(subset),
                "trade_count": trades,
                "net_pnl": net,
                "total_return_on_combined_capital": net
                / (initial_equity * max(1, len(subset))),
                "profit_factor": positive / negative
                if negative > 0
                else (math.inf if positive > 0 else 0.0),
                "win_rate": float(subset["winning_trades"].sum()) / trades
                if trades
                else 0.0,
                "expectancy": net / trades if trades else 0.0,
                "maximum_dataset_drawdown": float(subset["max_drawdown"].max()),
                "total_cost": float(subset["total_cost"].sum()),
                "blocked_signals": int(subset["blocked_signals"].sum()),
            }
        )
    return pd.DataFrame(records)


def _dataset_seed(symbol: str, timeframe: str) -> int:
    return 10_000 + SYMBOLS.index(symbol) * 100 + TIMEFRAMES.index(timeframe)


def run_validation(
    *,
    config_path: str | Path = "config.yaml",
    output_dir: str | Path = "outputs/daytrade",
    symbols: tuple[str, ...] = SYMBOLS,
    timeframes: tuple[str, ...] = TIMEFRAMES,
    selected_strategies: tuple[str, ...] | None = None,
) -> Path:
    config = load_config(config_path)
    quality = audit_datasets(
        output_dir=output_dir,
        symbols=symbols,
        timeframes=timeframes,
    )
    if not bool(quality["research_usable"].all()):
        invalid = quality.loc[
            ~quality["research_usable"], ["symbol", "timeframe"]
        ]
        raise ValueError(f"Invalid datasets; backtest aborted:\n{invalid}")

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    trade_path = output / "real_data_trades.csv"
    blocked_path = output / "real_data_blocked_trades.csv"
    oos_trade_path = output / "real_data_oos_trades.csv"
    for path in (trade_path, blocked_path, oos_trade_path):
        path.unlink(missing_ok=True)

    initial_equity = float(config.section("risk").get("initial_equity", 100_000))
    cost_scenarios = config.section("crypto_cost_scenarios")
    summary_rows: list[dict] = []
    oos_rows: list[dict] = []
    walk_rows: list[pd.DataFrame] = []
    sensitivity_rows: list[dict] = []
    dimension_rows: list[pd.DataFrame] = []
    psychology_rows: list[dict] = []
    block_reason_rows: list[pd.DataFrame] = []
    benchmark_rows: list[dict] = []
    normal_oos_by_strategy: dict[str, list[pd.DataFrame]] = {}
    high_oos_by_strategy: dict[str, list[pd.DataFrame]] = {}
    max_oos_drawdown_by_strategy: dict[str, list[float]] = {}
    guard_counts: dict[str, dict[str, int]] = {}

    strategy_names: set[str] = set()
    for symbol in symbols:
        for timeframe in timeframes:
            print(f"Researching {symbol} {timeframe}", flush=True)
            frame, data_report = load_csv(
                dataset_path(symbol, timeframe),
                timeframe,
                asset_class="crypto",
                drop_incomplete=True,
            )
            context = add_market_context(frame)
            strategies = build_strategies(config.raw, asset_class="crypto")
            if selected_strategies is not None:
                strategies = [
                    strategy
                    for strategy in strategies
                    if strategy.name in selected_strategies
                ]
            signal_map: dict[str, list[Signal]] = {}
            normal_results = {}
            all_templates: list[Signal] = []

            for strategy in strategies:
                strategy_names.add(strategy.name)
                signals = invalidate_signals_after_gaps(
                    frame,
                    strategy.generate_signals(frame, symbol, timeframe),
                    timeframe,
                    warmup_bars=200,
                )
                signal_map[strategy.name] = signals
                all_templates.extend(signals)
                guard_counts.setdefault(strategy.name, {"generated": 0, "allowed": 0})
                guard_counts[strategy.name]["generated"] += len(signals)
                print(
                    f"  {strategy.name}: {len(signals):,} raw signals",
                    flush=True,
                )

                for scenario in MAIN_SCENARIOS:
                    execution = _execution_config(config, cost_scenarios[scenario])
                    engine = _engine(config, execution)
                    result = engine.run_signals(
                        frame,
                        signals,
                        allow_fractional=True,
                        collect_blocked_records=scenario == "normal",
                    )
                    statistics = _result_statistics(
                        result,
                        initial_equity=initial_equity,
                    )
                    row = {
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "strategy": strategy.name,
                        "cost_scenario": scenario,
                        "generated_signals": len(signals),
                        **statistics,
                    }
                    summary_rows.append(row)
                    sensitivity_rows.append(
                        {
                            **row,
                            "sensitivity_type": "combined_cost_scenario",
                            "spread_bps": execution["spread_bps"],
                            "slippage_bps": execution["slippage_bps"],
                            "commission_bps": execution["commission_bps"],
                        }
                    )
                    compact_trades = _compact(result.trades, TRADE_COLUMNS).assign(
                        cost_scenario=scenario,
                        experiment_type="strategy",
                    )
                    compact_blocked = _compact(
                        result.blocked_trades, BLOCK_COLUMNS
                    ).assign(cost_scenario=scenario)
                    _append_csv(trade_path, compact_trades)
                    _append_csv(blocked_path, compact_blocked)

                    if scenario == "normal":
                        normal_results[strategy.name] = result
                        guard_counts[strategy.name]["allowed"] += len(result.trades)
                        enriched = attach_market_context(result.trades, context)
                        for dimension in (
                            "utc_hour",
                            "day_of_week",
                            "year",
                            "regime",
                            "volatility_bucket",
                        ):
                            dimension_result = metrics_by_dimension(
                                enriched,
                                dimension,
                                initial_equity=initial_equity,
                            )
                            if not dimension_result.empty:
                                dimension_rows.append(
                                    dimension_result.assign(
                                        dimension_type=dimension,
                                        dimension_value=dimension_result[
                                            dimension
                                        ].astype(str),
                                        symbol=symbol,
                                        timeframe=timeframe,
                                        strategy=strategy.name,
                                    ).drop(columns=[dimension])
                                )
                        permissive_engine = _engine(
                            config,
                            execution,
                            extra_setup=strategy.name,
                            permissive=True,
                        )
                        permissive = permissive_engine.run_signals(
                            frame,
                            signals,
                            allow_fractional=True,
                            collect_blocked_records=False,
                        )
                        impact, reasons = psychology_impact(
                            len(signals),
                            result,
                            permissive,
                        )
                        psychology_rows.append(
                            {
                                "symbol": symbol,
                                "timeframe": timeframe,
                                "strategy": strategy.name,
                                **impact,
                            }
                        )
                        if not reasons.empty:
                            block_reason_rows.append(
                                reasons.assign(
                                    symbol=symbol,
                                    timeframe=timeframe,
                                    strategy=strategy.name,
                                )
                            )

                        walk, _ = walk_forward_yearly_from_signals(
                            frame,
                            signals,
                            engine,
                            allow_fractional=True,
                        )
                        if not walk.empty:
                            walk_rows.append(
                                walk.assign(
                                    symbol=symbol,
                                    timeframe=timeframe,
                                    strategy=strategy.name,
                                    cost_scenario="normal",
                                )
                            )

                    if scenario in {"normal", "high"}:
                        oos = out_of_sample_from_signals(
                            frame,
                            signals,
                            engine,
                            allow_fractional=True,
                        )
                        oos_statistics = _result_statistics(
                            oos,
                            initial_equity=initial_equity,
                        )
                        split_position = int(len(frame) * 0.70)
                        oos_rows.append(
                            {
                                "symbol": symbol,
                                "timeframe": timeframe,
                                "strategy": strategy.name,
                                "cost_scenario": scenario,
                                "train_fraction": 0.70,
                                "test_start_utc": frame.iloc[split_position][
                                    "timestamp"
                                ],
                                **oos_statistics,
                            }
                        )
                        target = (
                            normal_oos_by_strategy
                            if scenario == "normal"
                            else high_oos_by_strategy
                        )
                        if not oos.trades.empty:
                            _append_csv(
                                oos_trade_path,
                                _compact(oos.trades, TRADE_COLUMNS).assign(
                                    dataset=f"{symbol}_{timeframe}",
                                    cost_scenario=scenario,
                                ),
                            )
                            target.setdefault(strategy.name, []).append(
                                oos.trades.assign(
                                    dataset=f"{symbol}_{timeframe}",
                                    cost_scenario=scenario,
                                )
                            )
                        if scenario == "normal":
                            max_oos_drawdown_by_strategy.setdefault(
                                strategy.name, []
                            ).append(float(oos.metrics["max_drawdown"]))

                normal_costs = cost_scenarios["normal"]
                for name, overrides in (
                    (
                        "spread_stress_3x",
                        {"spread_bps": float(normal_costs["spread_bps"]) * 3},
                    ),
                    (
                        "slippage_stress_3x",
                        {
                            "slippage_bps": float(
                                normal_costs["slippage_bps"]
                            )
                            * 3
                        },
                    ),
                ):
                    costs = dict(normal_costs)
                    costs.update(overrides)
                    execution = _execution_config(config, costs)
                    result = _engine(config, execution).run_signals(
                        frame,
                        signals,
                        allow_fractional=True,
                        collect_blocked_records=False,
                    )
                    sensitivity_rows.append(
                        {
                            "symbol": symbol,
                            "timeframe": timeframe,
                            "strategy": strategy.name,
                            "cost_scenario": name,
                            "sensitivity_type": name,
                            "spread_bps": execution["spread_bps"],
                            "slippage_bps": execution["slippage_bps"],
                            "commission_bps": execution["commission_bps"],
                            "generated_signals": len(signals),
                            **_result_statistics(
                                result,
                                initial_equity=initial_equity,
                            ),
                        }
                    )

            normal_execution = _execution_config(
                config, cost_scenarios["normal"]
            )
            include_shared_benchmarks = (
                selected_strategies is None
                or "opening_range_breakout" in selected_strategies
            )
            if include_shared_benchmarks:
                buy_hold = intraday_buy_hold_trades(
                    frame,
                    symbol,
                    timeframe,
                    normal_execution,
                )
                buy_hold_metrics = calculate_metrics(buy_hold, initial_equity)
                benchmark_rows.append(
                    {
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "benchmark": "intraday_buy_hold",
                        **buy_hold_metrics,
                        "net_pnl": float(buy_hold["net_pnl"].sum()),
                    }
                )
                _append_csv(
                    trade_path,
                    _compact(buy_hold, TRADE_COLUMNS).assign(
                        cost_scenario="normal",
                        experiment_type="benchmark",
                    ),
                )
                benchmark_rows.append(
                    {
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "benchmark": "cash",
                        **calculate_metrics(pd.DataFrame(), initial_equity),
                        "net_pnl": 0.0,
                    }
                )

            median_trades = int(
                np.median(
                    [
                        result.metrics["trade_count"]
                        for result in normal_results.values()
                    ]
                )
            )
            random_signals = random_entry_signals(
                frame,
                all_templates,
                symbol,
                timeframe,
                seed=_dataset_seed(symbol, timeframe),
                count=median_trades,
            )
            random_result = _engine(
                config,
                normal_execution,
                extra_setup="benchmark_random_entry",
                permissive=True,
            ).run_signals(frame, random_signals, allow_fractional=True)
            benchmark_rows.append(
                {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "benchmark": (
                        "random_entry_matched_count"
                        if selected_strategies is None
                        else f"random_entry_matched_{selected_strategies[0]}"
                    ),
                    "target_trade_count": median_trades,
                    **_result_statistics(
                        random_result,
                        initial_equity=initial_equity,
                    ),
                }
            )
            _append_csv(
                trade_path,
                _compact(random_result.trades, TRADE_COLUMNS).assign(
                    cost_scenario="normal",
                    experiment_type="benchmark",
                ),
            )

            if include_shared_benchmarks:
                momentum_signals = momentum_benchmark_signals(
                    frame, symbol, timeframe
                )
                momentum_result = _engine(
                    config,
                    normal_execution,
                    extra_setup="benchmark_simple_momentum",
                    permissive=True,
                ).run_signals(
                    frame,
                    momentum_signals,
                    allow_fractional=True,
                    collect_blocked_records=False,
                )
                benchmark_rows.append(
                    {
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "benchmark": "simple_momentum",
                        "generated_signals": len(momentum_signals),
                        **_result_statistics(
                            momentum_result,
                            initial_equity=initial_equity,
                        ),
                    }
                )
                _append_csv(
                    trade_path,
                    _compact(momentum_result.trades, TRADE_COLUMNS).assign(
                        cost_scenario="normal",
                        experiment_type="benchmark",
                    ),
                )

    summary = pd.DataFrame(summary_rows)
    oos_results = pd.DataFrame(oos_rows)
    walk_forward = (
        pd.concat(walk_rows, ignore_index=True) if walk_rows else pd.DataFrame()
    )
    cost_sensitivity = pd.DataFrame(sensitivity_rows)
    dimensions = (
        pd.concat(dimension_rows, ignore_index=True)
        if dimension_rows
        else pd.DataFrame()
    )
    psychology = pd.DataFrame(psychology_rows)
    block_reasons = (
        pd.concat(block_reason_rows, ignore_index=True)
        if block_reason_rows
        else pd.DataFrame()
    )
    benchmarks = pd.DataFrame(benchmark_rows)
    strategy_comparison = _aggregate_strategy_rows(summary, initial_equity)

    candidates = []
    for strategy in sorted(strategy_names):
        normal_oos = (
            pd.concat(normal_oos_by_strategy.get(strategy, []), ignore_index=True)
            if normal_oos_by_strategy.get(strategy)
            else pd.DataFrame()
        )
        high_oos = (
            pd.concat(high_oos_by_strategy.get(strategy, []), ignore_index=True)
            if high_oos_by_strategy.get(strategy)
            else pd.DataFrame()
        )
        counts = guard_counts[strategy]
        decision = evaluate_replay_candidate(
            strategy,
            normal_oos,
            high_oos,
            dataset_count=len(symbols) * len(timeframes),
            initial_equity=initial_equity,
            guard_allowed_rate=(
                counts["allowed"] / counts["generated"]
                if counts["generated"]
                else 0.0
            ),
            maximum_dataset_drawdown=max(
                max_oos_drawdown_by_strategy.get(strategy, [0.0])
            ),
        )
        candidates.append(decision.to_record())
    candidate_frame = pd.DataFrame(candidates)

    outputs = {
        "real_data_backtest_summary.csv": summary,
        "real_data_strategy_comparison.csv": pd.concat(
            [strategy_comparison, benchmarks.assign(experiment_type="benchmark")],
            ignore_index=True,
            sort=False,
        ),
        "real_data_oos_results.csv": oos_results,
        "real_data_walk_forward.csv": walk_forward,
        "real_data_cost_sensitivity.csv": cost_sensitivity,
        "real_data_time_of_day.csv": dimensions,
        "real_data_data_quality.csv": quality,
        "real_data_psychology_guard.csv": psychology,
        "real_data_block_reasons.csv": block_reasons,
        "real_data_replay_candidates.csv": candidate_frame,
        "real_data_benchmarks.csv": benchmarks,
    }
    for name, frame_to_write in outputs.items():
        frame_to_write.to_csv(output / name, index=False)

    if not trade_path.exists():
        pd.DataFrame(columns=TRADE_COLUMNS).to_csv(trade_path, index=False)
    if not blocked_path.exists():
        pd.DataFrame(columns=BLOCK_COLUMNS).to_csv(blocked_path, index=False)
    if not oos_trade_path.exists():
        pd.DataFrame(columns=TRADE_COLUMNS).to_csv(oos_trade_path, index=False)

    report = RealDataReportWriter(output).write(
        RealDataReportBundle(
            data_quality=quality,
            summary=summary,
            strategy_comparison=strategy_comparison,
            oos_results=oos_results,
            walk_forward=walk_forward,
            cost_sensitivity=cost_sensitivity,
            dimensions=dimensions,
            psychology_summary=psychology,
            block_reasons=block_reasons,
            candidates=candidate_frame,
            benchmarks=benchmarks,
            safety={
                "live_trading_enabled": False,
                "broker_connected": False,
                "orders_sent": False,
                "paper_internal_enabled": False,
                "paper_broker_enabled": False,
                "data_endpoint_only": "https://data-api.binance.vision/api/v3/klines",
                "api_keys_used": False,
            },
        )
    )
    print(f"Real-data report: {report.resolve()}", flush=True)
    return report


def _read_stage_frames(
    stage_directories: list[Path],
    filename: str,
) -> pd.DataFrame:
    frames = [
        pd.read_csv(directory / filename)
        for directory in stage_directories
        if (directory / filename).exists()
        and (directory / filename).stat().st_size > 0
    ]
    return pd.concat(frames, ignore_index=True, sort=False) if frames else pd.DataFrame()


def consolidate_stage_results(
    *,
    stage_root: str | Path = "outputs/daytrade/staging",
    output_dir: str | Path = "outputs/daytrade",
    config_path: str | Path = "config.yaml",
) -> Path:
    config = load_config(config_path)
    root = Path(stage_root)
    expected = [
        root / f"{symbol}_{timeframe}_{strategy}"
        for symbol in SYMBOLS
        for timeframe in TIMEFRAMES
        for strategy in STRATEGY_NAMES
    ]
    missing = [
        str(directory)
        for directory in expected
        if not (directory / "real_data_backtest_summary.csv").exists()
    ]
    if missing:
        raise FileNotFoundError(f"Incomplete Sprint 2 stages: {missing}")
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)

    large_files = (
        "real_data_trades.csv",
        "real_data_blocked_trades.csv",
        "real_data_oos_trades.csv",
    )
    for filename in large_files:
        destination = output / filename
        destination.unlink(missing_ok=True)
        wrote = False
        for directory in expected:
            source = directory / filename
            if not source.exists() or source.stat().st_size == 0:
                continue
            for chunk in pd.read_csv(source, chunksize=100_000):
                chunk.to_csv(
                    destination,
                    mode="a",
                    header=not wrote,
                    index=False,
                )
                wrote = True
        if not wrote:
            pd.DataFrame().to_csv(destination, index=False)

    small_names = {
        "summary": "real_data_backtest_summary.csv",
        "oos": "real_data_oos_results.csv",
        "walk": "real_data_walk_forward.csv",
        "cost": "real_data_cost_sensitivity.csv",
        "dimensions": "real_data_time_of_day.csv",
        "quality": "real_data_data_quality.csv",
        "psychology": "real_data_psychology_guard.csv",
        "block_reasons": "real_data_block_reasons.csv",
        "benchmarks": "real_data_benchmarks.csv",
    }
    combined = {
        key: _read_stage_frames(expected, filename)
        for key, filename in small_names.items()
    }
    combined["quality"] = combined["quality"].drop_duplicates(
        subset=["symbol", "timeframe"],
        keep="first",
    )
    combined["benchmarks"] = combined["benchmarks"].drop_duplicates(
        subset=["symbol", "timeframe", "benchmark"],
        keep="first",
    )
    initial_equity = float(config.section("risk").get("initial_equity", 100_000))
    strategy_comparison = _aggregate_strategy_rows(
        combined["summary"], initial_equity
    )

    oos_trades = pd.read_csv(output / "real_data_oos_trades.csv")
    candidates = []
    strategy_names = sorted(combined["summary"]["strategy"].dropna().unique())
    for strategy in strategy_names:
        normal = oos_trades[
            (oos_trades["strategy"] == strategy)
            & (oos_trades["cost_scenario"] == "normal")
        ].copy()
        high = oos_trades[
            (oos_trades["strategy"] == strategy)
            & (oos_trades["cost_scenario"] == "high")
        ].copy()
        psychology = combined["psychology"][
            combined["psychology"]["strategy"] == strategy
        ]
        generated = float(psychology["generated_signals"].sum())
        allowed = float(psychology["allowed_attempts"].sum())
        normal_oos = combined["oos"][
            (combined["oos"]["strategy"] == strategy)
            & (combined["oos"]["cost_scenario"] == "normal")
        ]
        decision = evaluate_replay_candidate(
            strategy,
            normal,
            high,
            dataset_count=len(expected),
            initial_equity=initial_equity,
            guard_allowed_rate=allowed / generated if generated else 0.0,
            maximum_dataset_drawdown=(
                float(normal_oos["max_drawdown"].max())
                if not normal_oos.empty
                else 0.0
            ),
        )
        candidates.append(decision.to_record())
    candidate_frame = pd.DataFrame(candidates)
    comparison_with_benchmarks = pd.concat(
        [
            strategy_comparison,
            combined["benchmarks"].assign(experiment_type="benchmark"),
        ],
        ignore_index=True,
        sort=False,
    )

    final_frames = {
        "real_data_backtest_summary.csv": combined["summary"],
        "real_data_strategy_comparison.csv": comparison_with_benchmarks,
        "real_data_oos_results.csv": combined["oos"],
        "real_data_walk_forward.csv": combined["walk"],
        "real_data_cost_sensitivity.csv": combined["cost"],
        "real_data_time_of_day.csv": combined["dimensions"],
        "real_data_data_quality.csv": combined["quality"],
        "real_data_psychology_guard.csv": combined["psychology"],
        "real_data_block_reasons.csv": combined["block_reasons"],
        "real_data_replay_candidates.csv": candidate_frame,
        "real_data_benchmarks.csv": combined["benchmarks"],
    }
    for filename, frame in final_frames.items():
        frame.to_csv(output / filename, index=False)
    RealDataReportWriter(output).write_quality_report(combined["quality"])
    report = RealDataReportWriter(output).write(
        RealDataReportBundle(
            data_quality=combined["quality"],
            summary=combined["summary"],
            strategy_comparison=strategy_comparison,
            oos_results=combined["oos"],
            walk_forward=combined["walk"],
            cost_sensitivity=combined["cost"],
            dimensions=combined["dimensions"],
            psychology_summary=combined["psychology"],
            block_reasons=combined["block_reasons"],
            candidates=candidate_frame,
            benchmarks=combined["benchmarks"],
            safety={
                "live_trading_enabled": False,
                "broker_connected": False,
                "orders_sent": False,
                "paper_internal_enabled": False,
                "paper_broker_enabled": False,
                "data_endpoint_only": "Binance public archives + GET /api/v3/klines",
                "api_keys_used": False,
            },
        )
    )
    return report


def _stage_task(task: tuple[str, str, str, str]) -> str:
    symbol, timeframe, strategy, config_path = task
    destination = (
        Path("outputs")
        / "daytrade"
        / "staging"
        / f"{symbol}_{timeframe}_{strategy}"
    )
    report = run_validation(
        config_path=config_path,
        output_dir=destination,
        symbols=(symbol,),
        timeframes=(timeframe,),
        selected_strategies=(strategy,),
    )
    return str(report)


def run_stage_matrix(
    *,
    config_path: str = "config.yaml",
    symbols: tuple[str, ...] = SYMBOLS,
    timeframes: tuple[str, ...] = TIMEFRAMES,
    workers: int = 2,
) -> None:
    tasks = []
    for symbol in symbols:
        for timeframe in timeframes:
            for strategy in STRATEGY_NAMES:
                destination = (
                    Path("outputs")
                    / "daytrade"
                    / "staging"
                    / f"{symbol}_{timeframe}_{strategy}"
                )
                if (destination / "real_data_backtest_summary.csv").exists():
                    print(f"SKIP complete {symbol} {timeframe} {strategy}", flush=True)
                    continue
                tasks.append((symbol, timeframe, strategy, config_path))
    if not tasks:
        print("All Sprint 2 stages are already complete.", flush=True)
        return
    with ProcessPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {pool.submit(_stage_task, task): task for task in tasks}
        for future in as_completed(futures):
            symbol, timeframe, strategy, _ = futures[future]
            report = future.result()
            print(
                f"DONE {symbol} {timeframe} {strategy}: {report}",
                flush=True,
            )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="DayTrade Lab Sprint 2 — public real data, research only"
    )
    parser.add_argument("--config", default="config.yaml")
    subparsers = parser.add_subparsers(dest="command", required=True)

    download = subparsers.add_parser("download")
    download.add_argument("--start", default="2022-01-01")
    download.add_argument("--end")
    download.add_argument("--no-resume", action="store_true")

    subparsers.add_parser("audit")
    run = subparsers.add_parser("run")
    run.add_argument("--symbol", choices=SYMBOLS)
    run.add_argument("--timeframe", choices=TIMEFRAMES)
    run.add_argument("--strategy", choices=STRATEGY_NAMES)
    run.add_argument("--output-dir", default="outputs/daytrade")
    consolidate = subparsers.add_parser("consolidate")
    consolidate.add_argument(
        "--stage-root",
        default="outputs/daytrade/staging",
    )
    stage = subparsers.add_parser("stage")
    stage.add_argument("--symbol", choices=SYMBOLS)
    stage.add_argument("--timeframe", choices=TIMEFRAMES)
    stage.add_argument("--workers", type=int, default=2)

    all_command = subparsers.add_parser("all")
    all_command.add_argument("--start", default="2022-01-01")
    all_command.add_argument("--end")
    all_command.add_argument("--no-resume", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command in {"download", "all"}:
        download_datasets(
            start=args.start,
            end=args.end,
            resume=not args.no_resume,
        )
    if args.command in {"audit", "all"}:
        quality = audit_datasets()
        print(
            quality[
                [
                    "symbol",
                    "timeframe",
                    "rows",
                    "coverage_ratio",
                    "missing_bars",
                    "quality_valid",
                ]
            ].to_string(index=False)
        )
    if args.command in {"run", "all"}:
        run_validation(
            config_path=args.config,
            output_dir=getattr(args, "output_dir", "outputs/daytrade"),
            symbols=(args.symbol,) if getattr(args, "symbol", None) else SYMBOLS,
            timeframes=(args.timeframe,)
            if getattr(args, "timeframe", None)
            else TIMEFRAMES,
            selected_strategies=(args.strategy,)
            if getattr(args, "strategy", None)
            else None,
        )
    if args.command == "consolidate":
        report = consolidate_stage_results(
            stage_root=args.stage_root,
            config_path=args.config,
        )
        print(f"Consolidated report: {report.resolve()}")
    if args.command == "stage":
        run_stage_matrix(
            config_path=args.config,
            symbols=(args.symbol,) if args.symbol else SYMBOLS,
            timeframes=(args.timeframe,) if args.timeframe else TIMEFRAMES,
            workers=args.workers,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
