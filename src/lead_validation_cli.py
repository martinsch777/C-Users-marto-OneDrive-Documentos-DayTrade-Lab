from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from src.lead_validation.pipeline import (
    LEAD_SYMBOLS,
    LEAD_TIMEFRAMES,
    consolidate_leads,
    run_lead_stage,
)


OUTPUT = Path("outputs/lead_validation")


def command_stage(args) -> int:
    destination = OUTPUT / "staging" / f"{args.symbol}_{args.timeframe}"
    run_lead_stage(args.symbol, args.timeframe, output_dir=destination)
    print(f"Stage complete: {destination.resolve()}")
    return 0


def _task(task):
    symbol, timeframe = task
    destination = OUTPUT / "staging" / f"{symbol}_{timeframe}"
    return str(run_lead_stage(symbol, timeframe, output_dir=destination))


def command_matrix(args) -> int:
    tasks = []
    symbols = (args.symbol,) if args.symbol else LEAD_SYMBOLS
    timeframes = (args.timeframe,) if args.timeframe else LEAD_TIMEFRAMES
    for symbol in symbols:
        for timeframe in timeframes:
            destination = OUTPUT / "staging" / f"{symbol}_{timeframe}"
            if (destination / "stage_complete.json").exists():
                print(f"SKIP {symbol} {timeframe}", flush=True)
            else:
                tasks.append((symbol, timeframe))
    if args.workers <= 1:
        for symbol, timeframe in tasks:
            print(
                f"DONE {symbol} {timeframe}: {_task((symbol, timeframe))}",
                flush=True,
            )
        if not tasks:
            print("All lead-validation stages are complete.")
        return 0
    with ProcessPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = {pool.submit(_task, task): task for task in tasks}
        for future in as_completed(futures):
            symbol, timeframe = futures[future]
            print(f"DONE {symbol} {timeframe}: {future.result()}", flush=True)
    if not tasks:
        print("All lead-validation stages are complete.")
    return 0


def command_consolidate(_args) -> int:
    report = consolidate_leads()
    print(f"Consolidated report: {report.resolve()}")
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Lead Validation — research only")
    commands = root.add_subparsers(dest="command", required=True)
    stage = commands.add_parser("stage")
    stage.add_argument("--symbol", required=True, choices=LEAD_SYMBOLS)
    stage.add_argument("--timeframe", required=True, choices=LEAD_TIMEFRAMES)
    stage.set_defaults(func=command_stage)
    matrix = commands.add_parser("matrix")
    matrix.add_argument("--workers", type=int, default=1)
    matrix.add_argument("--symbol", choices=LEAD_SYMBOLS)
    matrix.add_argument("--timeframe", choices=LEAD_TIMEFRAMES)
    matrix.set_defaults(func=command_matrix)
    commands.add_parser("consolidate").set_defaults(func=command_consolidate)
    return root


def main() -> int:
    args = parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
