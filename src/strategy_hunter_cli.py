from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

from src.data import audit_crypto_csv
from src.strategy_hunter import (
    CostBreakEvenAnalyzer,
    PlatformCostCatalog,
    PretestScorer,
    StrategyCatalog,
    build_hunter_strategies,
)
from src.strategy_hunter.pipeline import (
    HUNTER_SYMBOLS,
    HUNTER_TIMEFRAMES,
    consolidate_hunter,
    hunter_dataset_path,
    run_hunter_stage,
)


DEFAULT_OUTPUT = Path("outputs/daytrade_strategy_hunter")


def command_intake(_args) -> int:
    catalog = StrategyCatalog.load()
    scoring = PretestScorer({"OHLCV"}).score_catalog(catalog)
    DEFAULT_OUTPUT.mkdir(parents=True, exist_ok=True)
    catalog.to_frame().to_csv(DEFAULT_OUTPUT / "strategy_catalog.csv", index=False)
    scoring.to_csv(DEFAULT_OUTPUT / "pretest_scoring.csv", index=False)
    print(scoring[["strategy_id", "total_score", "classification"]].to_string(index=False))
    return 0


def command_costs(_args) -> int:
    profiles = PlatformCostCatalog.load()
    comparison = profiles.to_frame()
    break_even = CostBreakEvenAnalyzer(profiles).analyze()
    DEFAULT_OUTPUT.mkdir(parents=True, exist_ok=True)
    comparison.to_csv(DEFAULT_OUTPUT / "platform_cost_comparison.csv", index=False)
    break_even.to_csv(DEFAULT_OUTPUT / "cost_break_even.csv", index=False)
    print(
        comparison[
            ["id", "maker_round_trip_bps", "taker_round_trip_bps"]
        ].to_string(index=False)
    )
    return 0


def command_audit(_args) -> int:
    records = []
    for symbol in HUNTER_SYMBOLS:
        for timeframe in HUNTER_TIMEFRAMES:
            path = hunter_dataset_path(symbol, timeframe)
            if not path.exists():
                raise FileNotFoundError(path)
            records.append(
                audit_crypto_csv(path, symbol, timeframe).to_record()
            )
    quality = pd.DataFrame(records)
    DEFAULT_OUTPUT.mkdir(parents=True, exist_ok=True)
    quality.to_csv(DEFAULT_OUTPUT / "data_quality.csv", index=False)
    print(
        quality[
            [
                "symbol",
                "timeframe",
                "rows",
                "missing_bars",
                "coverage_ratio",
                "research_usable",
            ]
        ].to_string(index=False)
    )
    return 0


def _task(task):
    symbol, timeframe = task
    destination = DEFAULT_OUTPUT / "staging" / f"{symbol}_{timeframe}"
    return str(
        run_hunter_stage(
            symbol,
            timeframe,
            output_dir=destination,
        )
    )


def _variant_task(task):
    symbol, timeframe = task
    destination = DEFAULT_OUTPUT / "staging_variants" / f"{symbol}_{timeframe}"
    variants = build_hunter_strategies(include_predefined_variants=True)[9:]
    return str(
        run_hunter_stage(
            symbol,
            timeframe,
            output_dir=destination,
            strategies=variants,
        )
    )


def command_stage(args) -> int:
    destination = DEFAULT_OUTPUT / "staging" / f"{args.symbol}_{args.timeframe}"
    result = run_hunter_stage(
        args.symbol,
        args.timeframe,
        output_dir=destination,
    )
    print(f"Stage complete: {result.resolve()}")
    return 0


def command_matrix(args) -> int:
    tasks = []
    symbols = (args.symbol,) if args.symbol else HUNTER_SYMBOLS
    timeframes = (args.timeframe,) if args.timeframe else HUNTER_TIMEFRAMES
    for symbol in symbols:
        for timeframe in timeframes:
            destination = DEFAULT_OUTPUT / "staging" / f"{symbol}_{timeframe}"
            if (destination / "stage_complete.json").exists():
                print(f"SKIP {symbol} {timeframe}", flush=True)
            else:
                tasks.append((symbol, timeframe))
    if not tasks:
        print("All Strategy Hunter stages are complete.")
        return 0
    with ProcessPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = {pool.submit(_task, task): task for task in tasks}
        for future in as_completed(futures):
            symbol, timeframe = futures[future]
            print(f"DONE {symbol} {timeframe}: {future.result()}", flush=True)
    return 0


def command_variant_stage(args) -> int:
    destination = (
        DEFAULT_OUTPUT / "staging_variants" / f"{args.symbol}_{args.timeframe}"
    )
    variants = build_hunter_strategies(include_predefined_variants=True)[9:]
    result = run_hunter_stage(
        args.symbol,
        args.timeframe,
        output_dir=destination,
        strategies=variants,
    )
    print(f"Variant stage complete: {result.resolve()}")
    return 0


def command_variant_matrix(args) -> int:
    tasks = []
    symbols = (args.symbol,) if args.symbol else HUNTER_SYMBOLS
    timeframes = (args.timeframe,) if args.timeframe else HUNTER_TIMEFRAMES
    for symbol in symbols:
        for timeframe in timeframes:
            destination = (
                DEFAULT_OUTPUT / "staging_variants" / f"{symbol}_{timeframe}"
            )
            if (destination / "stage_complete.json").exists():
                print(f"SKIP VARIANTS {symbol} {timeframe}", flush=True)
            else:
                tasks.append((symbol, timeframe))
    if not tasks:
        print("All predefined variant stages are complete.")
        return 0
    with ProcessPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = {pool.submit(_variant_task, task): task for task in tasks}
        for future in as_completed(futures):
            symbol, timeframe = futures[future]
            print(
                f"DONE VARIANTS {symbol} {timeframe}: {future.result()}",
                flush=True,
            )
    return 0


def command_consolidate(_args) -> int:
    report = consolidate_hunter()
    print(f"Consolidated report: {report.resolve()}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="YouTube / Forum Strategy Hunter — research only"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("intake").set_defaults(func=command_intake)
    subparsers.add_parser("costs").set_defaults(func=command_costs)
    subparsers.add_parser("audit").set_defaults(func=command_audit)
    stage = subparsers.add_parser("stage")
    stage.add_argument("--symbol", required=True, choices=HUNTER_SYMBOLS)
    stage.add_argument("--timeframe", required=True, choices=HUNTER_TIMEFRAMES)
    stage.set_defaults(func=command_stage)
    matrix = subparsers.add_parser("matrix")
    matrix.add_argument("--symbol", choices=HUNTER_SYMBOLS)
    matrix.add_argument("--timeframe", choices=HUNTER_TIMEFRAMES)
    matrix.add_argument("--workers", type=int, default=1)
    matrix.set_defaults(func=command_matrix)
    variant_stage = subparsers.add_parser("variant-stage")
    variant_stage.add_argument("--symbol", required=True, choices=HUNTER_SYMBOLS)
    variant_stage.add_argument(
        "--timeframe", required=True, choices=HUNTER_TIMEFRAMES
    )
    variant_stage.set_defaults(func=command_variant_stage)
    variant_matrix = subparsers.add_parser("variant-matrix")
    variant_matrix.add_argument("--symbol", choices=HUNTER_SYMBOLS)
    variant_matrix.add_argument("--timeframe", choices=HUNTER_TIMEFRAMES)
    variant_matrix.add_argument("--workers", type=int, default=1)
    variant_matrix.set_defaults(func=command_variant_matrix)
    subparsers.add_parser("consolidate").set_defaults(func=command_consolidate)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
