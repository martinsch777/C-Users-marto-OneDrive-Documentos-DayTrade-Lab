from __future__ import annotations

import argparse

from src.config import load_config
from src.microstructure_collector import (
    BybitMicrostructureCollector,
    initialize_collector_outputs,
)
from src.microstructure_collector.collector import TOPIC_TEMPLATES
from src.microstructure_collector.stability import (
    build_stability_report,
    merge_rest_diagnostic,
    metrics_from_status,
    write_stability_report,
)


SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT")
TOPIC_GROUPS = tuple(TOPIC_TEMPLATES)


def command_init(_args) -> int:
    root = initialize_collector_outputs()
    print(f"Collector outputs initialized: {root.resolve()}")
    return 0


def command_run(args) -> int:
    if not args.confirm_public_data_only:
        raise SystemExit(
            "Refusing to start without --confirm-public-data-only"
        )
    settings = load_config().section("microstructure_collector")
    topics = args.topics or settings.get(
        "enabled_topics", list(TOPIC_GROUPS)
    )
    collector = BybitMicrostructureCollector(
        tuple(args.symbols),
        enabled_topics=tuple(topics),
        recv_timeout_seconds=(
            args.recv_timeout_seconds
            if args.recv_timeout_seconds is not None
            else float(settings.get("recv_timeout_seconds", 5))
        ),
        subscription_timeout_seconds=(
            args.subscription_timeout_seconds
            if args.subscription_timeout_seconds is not None
            else float(settings.get("subscription_timeout_seconds", 15))
        ),
        no_data_timeout_seconds=(
            args.no_data_timeout_seconds
            if args.no_data_timeout_seconds is not None
            else float(settings.get("no_data_timeout_seconds", 30))
        ),
        max_reconnect_backoff_seconds=(
            args.max_reconnect_backoff_seconds
            if args.max_reconnect_backoff_seconds is not None
            else float(
                settings.get("max_reconnect_backoff_seconds", 60)
            )
        ),
    )
    collector.run(args.duration_seconds)
    return 0


def command_stability(args) -> int:
    metrics = metrics_from_status(args.status_path)
    merge_rest_diagnostic(metrics, args.diagnostic_path)
    topics = [
        TOPIC_TEMPLATES[group].format(symbol=symbol)
        for symbol in args.symbols
        for group in args.topics
    ]
    report = build_stability_report(
        metrics,
        duration_seconds=args.duration_seconds,
        topics=topics,
        maximum_reconnects=args.maximum_reconnects,
        maximum_errors=args.maximum_errors,
    )
    path = write_stability_report(report, args.output)
    print(f"Stability outcome: {report['outcome']}")
    print(f"Recommendation: {report['recommendation']}")
    print(f"Report: {path.resolve()}")
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        description="Forward public microstructure collector - no trading"
    )
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("init").set_defaults(func=command_init)

    run = commands.add_parser("run")
    run.add_argument(
        "--symbols", nargs="+", choices=SYMBOLS, default=["BTCUSDT"]
    )
    run.add_argument("--duration-seconds", type=int, default=3600)
    run.add_argument(
        "--topics",
        nargs="+",
        choices=TOPIC_GROUPS,
        default=None,
    )
    run.add_argument("--recv-timeout-seconds", type=float)
    run.add_argument(
        "--subscription-timeout-seconds", type=float
    )
    run.add_argument("--no-data-timeout-seconds", type=float)
    run.add_argument(
        "--max-reconnect-backoff-seconds", type=float
    )
    run.add_argument("--confirm-public-data-only", action="store_true")
    run.set_defaults(func=command_run)

    stability = commands.add_parser("stability")
    stability.add_argument("--duration-seconds", type=float, required=True)
    stability.add_argument(
        "--symbols", nargs="+", choices=SYMBOLS, default=["BTCUSDT"]
    )
    stability.add_argument(
        "--topics",
        nargs="+",
        choices=TOPIC_GROUPS,
        default=list(TOPIC_GROUPS),
    )
    stability.add_argument(
        "--status-path",
        default="outputs/microstructure_collector/collector_status.csv",
    )
    stability.add_argument(
        "--diagnostic-path",
        default=(
            "outputs/microstructure_collector/"
            "bybit_connection_diagnostic.json"
        ),
    )
    stability.add_argument(
        "--output",
        default=(
            "outputs/microstructure_collector/"
            "websocket_stability_report.json"
        ),
    )
    stability.add_argument("--maximum-reconnects", type=int, default=2)
    stability.add_argument("--maximum-errors", type=int, default=2)
    stability.set_defaults(func=command_stability)
    return root


def main() -> int:
    args = parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
