from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.bybit_diagnostics import (
    BybitRestFallback,
    diagnose_dns,
    diagnose_https,
    diagnose_tcp,
    diagnose_tls,
    diagnose_websocket,
    diagnose_write,
    environment_report,
    write_diagnostic_report,
)


DEFAULT_REPORT = Path(
    "outputs/microstructure_collector/bybit_connection_diagnostic.json"
)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        description="Bybit public connectivity diagnostics — no API keys/trading"
    )
    root.add_argument("--symbol", default="BTCUSDT")
    root.add_argument("--timeout", type=float, default=8.0)
    root.add_argument("--rest-only", action="store_true")
    root.add_argument("--output", default=str(DEFAULT_REPORT))
    root.add_argument("--json", action="store_true")
    return root


def main() -> int:
    args = parser().parse_args()
    results = [
        diagnose_dns("api.bybit.com"),
        diagnose_dns("stream.bybit.com"),
        diagnose_https(args.timeout),
        diagnose_tcp("api.bybit.com", args.timeout),
        diagnose_tcp("stream.bybit.com", args.timeout),
        diagnose_tls("stream.bybit.com", args.timeout),
        diagnose_write("data/forward_microstructure/bybit"),
    ]
    results.extend(BybitRestFallback(timeout=args.timeout).probe(args.symbol))
    if not args.rest_only:
        results.append(
            diagnose_websocket(
                args.symbol,
                args.timeout,
                persistence_path=(
                    "outputs/microstructure_collector/"
                    "websocket_diagnostic_sample.json"
                ),
            )
        )
    environment = environment_report()
    report = write_diagnostic_report(
        results,
        environment,
        args.output,
    )
    if args.json:
        print(
            json.dumps(
                {
                    "report": str(report.resolve()),
                    "results": [result.to_record() for result in results],
                    "environment": environment,
                },
                indent=2,
            )
        )
    else:
        for result in results:
            code = f" [{result.error_code}]" if result.error_code else ""
            print(
                f"{result.status:4} {result.test:28} {result.target}{code}"
            )
        print(f"Report: {report.resolve()}")
    failed = any(result.status == "FAIL" for result in results)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
