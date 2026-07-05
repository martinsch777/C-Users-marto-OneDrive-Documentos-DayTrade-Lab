from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from src.edge_discovery import ForwardMarketCollector, data_availability_matrix
from src.edge_discovery.pipeline import (
    EDGE_SYMBOLS,
    EDGE_TIMEFRAMES,
    consolidate_edge_discovery,
    run_edge_stage,
)
from src.edge_discovery.specialized_data import (
    download_binance_funding_history,
    download_bybit_open_interest_history,
    save_specialized_frame,
)


OUTPUT = Path("outputs/edge_discovery")


def command_sources(_args) -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    matrix = data_availability_matrix()
    matrix.to_csv(OUTPUT / "data_availability_matrix.csv", index=False)
    print(
        matrix[
            [
                "source",
                "dataset",
                "estimated_cost_usd_month",
                "status",
            ]
        ].to_string(index=False)
    )
    return 0


def command_stage(args) -> int:
    destination = OUTPUT / "staging" / f"{args.symbol}_{args.timeframe}"
    run_edge_stage(args.symbol, args.timeframe, output_dir=destination)
    print(f"Stage complete: {destination.resolve()}")
    return 0


def _task(task):
    symbol, timeframe = task
    destination = OUTPUT / "staging" / f"{symbol}_{timeframe}"
    return str(run_edge_stage(symbol, timeframe, output_dir=destination))


def command_matrix(args) -> int:
    tasks = []
    for symbol in EDGE_SYMBOLS:
        for timeframe in EDGE_TIMEFRAMES:
            destination = OUTPUT / "staging" / f"{symbol}_{timeframe}"
            if (destination / "stage_complete.json").exists():
                print(f"SKIP {symbol} {timeframe}", flush=True)
            else:
                tasks.append((symbol, timeframe))
    with ProcessPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = {pool.submit(_task, task): task for task in tasks}
        for future in as_completed(futures):
            symbol, timeframe = futures[future]
            print(f"DONE {symbol} {timeframe}: {future.result()}", flush=True)
    if not tasks:
        print("All edge-discovery stages are complete.")
    return 0


def command_collect_once(args) -> int:
    collector = ForwardMarketCollector()
    result = collector.collect_once(tuple(args.symbols))
    OUTPUT.mkdir(parents=True, exist_ok=True)
    result.to_csv(OUTPUT / "collector_status.csv", index=False)
    print(result.to_string(index=False))
    return 0


def command_download_funding(args) -> int:
    frame = download_binance_funding_history(
        args.symbol,
        args.start,
        args.end,
    )
    destination = save_specialized_frame(
        frame,
        Path("data/specialized/binance") / f"{args.symbol}_funding.csv",
    )
    print(f"Saved {len(frame):,} funding rows to {destination.resolve()}")
    return 0


def command_download_oi(args) -> int:
    frame = download_bybit_open_interest_history(
        args.symbol,
        interval=args.interval,
    )
    destination = save_specialized_frame(
        frame,
        Path("data/specialized/bybit") / f"{args.symbol}_open_interest.csv",
    )
    print(f"Saved {len(frame):,} OI rows to {destination.resolve()}")
    return 0


def command_consolidate(_args) -> int:
    report = consolidate_edge_discovery()
    print(f"Consolidated report: {report.resolve()}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="DayTrade Edge Discovery — research only"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("sources").set_defaults(func=command_sources)
    stage = commands.add_parser("stage")
    stage.add_argument("--symbol", required=True, choices=EDGE_SYMBOLS)
    stage.add_argument("--timeframe", required=True, choices=EDGE_TIMEFRAMES)
    stage.set_defaults(func=command_stage)
    matrix = commands.add_parser("matrix")
    matrix.add_argument("--workers", type=int, default=1)
    matrix.set_defaults(func=command_matrix)
    collect = commands.add_parser("collect-once")
    collect.add_argument(
        "--symbols",
        nargs="+",
        choices=EDGE_SYMBOLS,
        default=list(EDGE_SYMBOLS),
    )
    collect.set_defaults(func=command_collect_once)
    funding = commands.add_parser("download-funding")
    funding.add_argument("--symbol", required=True, choices=EDGE_SYMBOLS)
    funding.add_argument("--start", default="2022-01-01")
    funding.add_argument("--end", default="2026-07-04")
    funding.set_defaults(func=command_download_funding)
    oi = commands.add_parser("download-open-interest")
    oi.add_argument("--symbol", required=True, choices=EDGE_SYMBOLS)
    oi.add_argument(
        "--interval",
        choices=("5min", "15min", "30min", "1h", "4h", "1d"),
        default="5min",
    )
    oi.set_defaults(func=command_download_oi)
    commands.add_parser("consolidate").set_defaults(func=command_consolidate)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
