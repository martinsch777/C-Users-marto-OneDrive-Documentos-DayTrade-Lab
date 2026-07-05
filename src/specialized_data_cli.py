from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from src.lead_validation.specialized import (
    import_funding_csv,
    import_open_interest_csv,
)


def command_import(args) -> int:
    if args.kind == "funding":
        frame, report = import_funding_csv(args.source)
    else:
        frame, report = import_open_interest_csv(args.source)
    destination = (
        Path("data/specialized/offline")
        / f"{args.symbol}_{args.kind}.csv"
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(destination, index=False)
    quality_path = Path("outputs/lead_validation/funding_oi_import_quality.csv")
    quality_path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "symbol": args.symbol,
        "provider": args.provider,
        **report,
    }
    pd.DataFrame([row]).to_csv(
        quality_path,
        mode="a",
        header=not quality_path.exists(),
        index=False,
    )
    print(f"Imported {len(frame):,} rows to {destination.resolve()}")
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        description="Offline funding/open-interest import — no API keys"
    )
    command = root.add_subparsers(dest="command", required=True)
    import_parser = command.add_parser("import")
    import_parser.add_argument("--kind", choices=("funding", "open_interest"), required=True)
    import_parser.add_argument("--symbol", required=True)
    import_parser.add_argument("--source", required=True)
    import_parser.add_argument("--provider", default="manual")
    import_parser.set_defaults(func=command_import)
    return root


def main() -> int:
    args = parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
