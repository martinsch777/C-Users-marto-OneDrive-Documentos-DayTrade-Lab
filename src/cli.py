from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path

import pandas as pd

from src.backtesting import (
    BacktestEngine,
    approval_decision,
    calculate_metrics,
    compare_strategies,
    cost_sensitivity,
    out_of_sample_backtest,
    walk_forward_backtest,
)
from src.config import load_config
from src.data import (
    AlpacaDownloadError,
    AlpacaEquityIntradayDownloader,
    BinancePublicDataProvider,
    DownloadRequest,
    EquitySessionCalendar,
    audit_equity_intraday_csv,
    build_dataset_manifest,
    load_csv,
    normalize_ohlcv,
    validate_ohlcv,
    write_dataset_manifest,
    write_equity_intraday_audit_report,
)
from src.data.providers import save_local
from src.replay import MarketReplay
from src.reports import ReportBundle, ReportWriter
from src.scanner import IntradayScanner
from src.strategies import available_strategy_names, build_strategies
from src.utils import generate_synthetic_intraday


def _concat(frames: list[pd.DataFrame]) -> pd.DataFrame:
    available = [frame for frame in frames if not frame.empty]
    return pd.concat(available, ignore_index=True) if available else pd.DataFrame()


def _journal_rows(
    trades: pd.DataFrame,
    blocked: pd.DataFrame,
) -> pd.DataFrame:
    rows: list[dict] = []
    for _, item in trades.iterrows():
        rows.append(
            {
                "date": str(item.get("timestamp", ""))[:10],
                "asset": item.get("symbol", ""),
                "setup": item.get("strategy", ""),
                "entry": item.get("entry_price", ""),
                "stop": item.get("stop_price", ""),
                "take_profit": item.get("take_profit", ""),
                "size": item.get("filled_quantity", 0),
                "risk": item.get("risk_amount", 0),
                "result": item.get("net_pnl", 0),
                "entry_reason": item.get("reason", ""),
                "exit_reason": item.get("exit_reason", ""),
                "rules_followed": True,
                "blocked": False,
                "block_reason": "",
                "screenshot_path": "",
                "manual_notes": "",
                "emotion_before": "",
                "emotion_after": "",
                "mistakes": "",
            }
        )
    for _, item in blocked.iterrows():
        rows.append(
            {
                "date": str(item.get("timestamp", ""))[:10],
                "asset": item.get("symbol", ""),
                "setup": item.get("strategy", ""),
                "entry": item.get("entry_price", ""),
                "stop": item.get("stop_price", ""),
                "take_profit": item.get("take_profit", ""),
                "size": 0,
                "risk": 0,
                "result": 0,
                "entry_reason": item.get("reason", ""),
                "exit_reason": "",
                "rules_followed": False,
                "blocked": True,
                "block_reason": item.get("block_reason", ""),
                "screenshot_path": "",
                "manual_notes": "",
                "emotion_before": "",
                "emotion_after": "",
                "mistakes": "",
            }
        )
    return pd.DataFrame(rows)


def run_research(
    frame: pd.DataFrame,
    *,
    symbol: str,
    timeframe: str,
    asset_class: str,
    config_path: str | Path,
    strategy_name: str | None = None,
) -> dict[str, Path]:
    config = load_config(config_path)
    data_config = config.section("data")
    calendar = (
        EquitySessionCalendar.from_config(
            data_config.get("calendar", {}),
            timezone=str(
                config.section("project").get(
                    "timezone",
                    "America/New_York",
                )
            ),
            regular_open=str(
                data_config.get("equity_session_start", "09:30")
            ),
            regular_close=str(
                data_config.get("equity_session_end", "16:00")
            ),
        )
        if asset_class == "equity"
        else None
    )
    quality = validate_ohlcv(
        frame,
        timeframe,
        asset_class=asset_class,
        calendar=calendar,
    )
    allow_missing = bool(config.section("data").get("allow_missing_bars", False))
    if not quality.is_valid and not allow_missing:
        raise ValueError(
            "Data failed quality controls. Fix it or explicitly set "
            "data.allow_missing_bars=true for a diagnostic-only run. "
            f"Report: {quality}"
        )

    raw_config = deepcopy(config.raw)
    if asset_class == "crypto":
        raw_config["psychology_guard"]["trading_window_start"] = "00:00"
        raw_config["psychology_guard"]["trading_window_end"] = "23:59"
        raw_config.setdefault("execution", {})[
            "force_flat_before_session_end"
        ] = False
    else:
        execution = raw_config.setdefault("execution", {})
        execution.setdefault("session_timezone", "America/New_York")
        execution.setdefault("session_start", "09:30")
        execution.setdefault("session_end", "16:00")
        execution.setdefault(
            "calendar",
            raw_config.get("data", {}).get("calendar", {}),
        )
    engine = BacktestEngine(
        raw_config.get("risk", {}),
        raw_config.get("execution", {}),
        raw_config.get("psychology_guard", {}),
    )
    strategies = build_strategies(
        raw_config,
        asset_class=asset_class,
        strategy_names=[strategy_name] if strategy_name else None,
    )
    runs = [
        engine.run(
            frame,
            strategy,
            symbol,
            timeframe,
            allow_fractional=asset_class == "crypto",
        )
        for strategy in strategies
    ]
    trades = _concat([run.trades for run in runs])
    blocked = _concat([run.blocked_trades for run in runs])
    initial_equity = float(raw_config["risk"]["initial_equity"])
    metrics = calculate_metrics(trades, initial_equity)
    metrics.update(
        {
            "evaluation_scope": "independent_strategy_runs",
            "data_rows": quality.rows,
            "missing_bars": len(quality.missing_bars),
            "security_live_trading_enabled": False,
            "security_broker_connected": False,
            "security_orders_sent": False,
        }
    )
    comparison = compare_strategies(trades, initial_equity)

    oos_results = [
        out_of_sample_backtest(
            frame,
            strategy,
            symbol,
            timeframe,
            engine,
        )
        for strategy in strategies
    ]
    oos_trades = _concat([result.trades for result in oos_results])
    oos_summary = pd.DataFrame(
        [
            {"strategy": strategy.name, **result.metrics}
            for strategy, result in zip(strategies, oos_results)
        ]
    )
    approval = approval_decision(oos_trades, calculate_metrics(oos_trades))

    walk_forward = _concat(
        [
            walk_forward_backtest(
                frame,
                strategy,
                symbol,
                timeframe,
                engine,
                minimum_training_bars=min(300, max(50, len(frame) // 2)),
                test_bars=max(25, len(frame) // 8),
            ).assign(strategy=strategy.name)
            for strategy in strategies
        ]
    )
    sensitivity = _concat(
        [
            cost_sensitivity(
                frame,
                strategy,
                symbol,
                timeframe,
                raw_config,
            ).assign(strategy=strategy.name)
            for strategy in strategies
        ]
    )

    scanner = IntradayScanner(
        max_spread_bps=float(raw_config["risk"]["max_spread_bps"]),
        min_relative_volume=float(raw_config["risk"]["min_relative_volume"]),
    )
    candidates = scanner.scan(
        {symbol: frame},
        spread_by_symbol={
            symbol: float(raw_config["execution"].get("spread_bps", 0.0))
        },
    )
    replay_strategy = strategies[0]
    replay_start = max(0, len(frame) - 3 * max(1, int(pd.Timedelta("6h30min") / pd.Timedelta(timeframe))))
    replay_frame = frame.iloc[replay_start:].reset_index(drop=True)
    replay = MarketReplay(
        raw_config.get("risk", {}),
        raw_config.get("psychology_guard", {}),
    ).run(
        replay_frame,
        replay_strategy,
        symbol,
        timeframe,
        session_id=f"{symbol}-{timeframe}-latest",
        warmup_bars=min(40, max(1, len(replay_frame) - 1)),
    )
    journal = _journal_rows(trades, blocked)

    output_dir = Path(config.section("project").get("output_dir", "outputs/daytrade"))
    writer = ReportWriter(output_dir)
    paths = writer.write(
        ReportBundle(
            metrics=metrics,
            trades=trades,
            blocked_trades=blocked,
            scanner_candidates=candidates,
            replay_sessions=replay,
            journal=journal,
            strategy_comparison=comparison,
            diagnostics={
                "Out-of-sample": oos_summary,
                "Walk-forward anclado": walk_forward,
                "Sensibilidad a costos": sensitivity,
            },
            approval={
                "approved_for_internal_paper": approval.approved_for_internal_paper,
                "reasons": list(approval.reasons),
                "broker_paper_allowed": False,
                "live_trading_allowed": False,
            },
        )
    )
    for name, diagnostic in (
        ("out_of_sample_summary.csv", oos_summary),
        ("walk_forward.csv", walk_forward),
        ("cost_sensitivity.csv", sensitivity),
    ):
        diagnostic.to_csv(output_dir / name, index=False)
    return paths


def command_demo(args: argparse.Namespace) -> int:
    raw = generate_synthetic_intraday(
        sessions=args.sessions,
        timeframe=args.timeframe,
        seed=args.seed,
    )
    frame, _ = normalize_ohlcv(
        raw,
        args.timeframe,
        drop_incomplete=False,
    )
    data_path = save_local(
        frame,
        Path("data") / "synthetic" / f"SPY_{args.timeframe}.csv",
    )
    paths = run_research(
        frame,
        symbol="SPY",
        timeframe=args.timeframe,
        asset_class="equity",
        config_path=args.config,
    )
    print(f"Synthetic fixture: {data_path.resolve()}")
    print(f"Research report: {paths['html'].resolve()}")
    print("Safety state: live trading=False, broker connected=False, orders sent=False")
    return 0


def command_backtest(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    data_config = config.section("data")
    calendar = (
        EquitySessionCalendar.from_config(
            data_config.get("calendar", {}),
            timezone=str(
                config.section("project").get(
                    "timezone",
                    "America/New_York",
                )
            ),
            regular_open=str(
                data_config.get("equity_session_start", "09:30")
            ),
            regular_close=str(
                data_config.get("equity_session_end", "16:00")
            ),
        )
        if args.asset_class == "equity"
        else None
    )
    frame, quality = load_csv(
        args.csv,
        args.timeframe,
        asset_class=args.asset_class,
        drop_incomplete=True,
        source_timezone=data_config.get("source_timezone"),
        calendar=calendar,
    )
    print(
        f"Loaded {quality.rows} complete bars; "
        f"missing expected bars={len(quality.missing_bars)}"
    )
    paths = run_research(
        frame,
        symbol=args.symbol.upper(),
        timeframe=args.timeframe,
        asset_class=args.asset_class,
        config_path=args.config,
        strategy_name=args.strategy,
    )
    print(f"Research report: {paths['html'].resolve()}")
    return 0


def command_audit_data(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    data_config = config.section("data")
    calendar = EquitySessionCalendar.from_config(
        data_config.get("calendar", {}),
        timezone=str(
            config.section("project").get(
                "timezone",
                "America/New_York",
            )
        ),
        regular_open=str(data_config.get("equity_session_start", "09:30")),
        regular_close=str(data_config.get("equity_session_end", "16:00")),
    )
    source_timezone = args.source_timezone
    if source_timezone is None:
        source_timezone = data_config.get("source_timezone")
    report = audit_equity_intraday_csv(
        args.csv,
        args.symbol,
        args.timeframe,
        asset_class=args.asset_class,
        source_timezone=source_timezone,
        calendar=calendar,
    )
    output_dir = args.output_dir or (
        Path("outputs") / "data_audit" / report.symbol
    )
    paths = write_equity_intraday_audit_report(report, output_dir)
    verdict = "APTO" if report.apt_for_or_fvg_backtest else "NO APTO"
    print(f"Dataset {report.symbol} {report.timeframe}: {verdict} para OR/FVG")
    print(f"Filas={report.rows_total}; sesiones={report.sessions}; faltantes={report.missing_bars}; fuera_RTH={report.outside_rth_bars}")
    if "CSV_NOT_FOUND" in report.critical_warnings:
        print(f"CSV_NOT_FOUND: {Path(args.csv)}")
    if report.critical_warnings:
        print("Advertencias críticas: " + ", ".join(report.critical_warnings))
    print(f"JSON: {paths['json'].resolve()}")
    print(f"CSV: {paths['csv'].resolve()}")
    print(f"Markdown: {paths['markdown'].resolve()}")
    print("Safety state: live trading=False, broker connected=False, orders sent=False, api_keys_used=False")
    if args.fail_on_not_fit and not report.apt_for_or_fvg_backtest:
        return 2
    return 0


def command_calendar_diagnostics(args: argparse.Namespace) -> int:
    if args.calendar != "us_equity":
        raise ValueError("Only calendar='us_equity' is supported")
    calendar = EquitySessionCalendar.from_config({"source": args.calendar})
    rows = calendar.diagnostics(
        pd.Timestamp(args.start).date(),
        pd.Timestamp(args.end).date(),
        "1min",
    )
    if args.format == "json":
        print(json.dumps(rows, indent=2))
    else:
        print(pd.DataFrame(rows).to_csv(index=False).strip())
    print("Safety state: live trading=False, broker connected=False, orders sent=False")
    return 0


def _print_download_result(result) -> None:
    print(
        json.dumps(
            result.to_record(),
            indent=2,
        )
    )


def command_download_equity_intraday(args: argparse.Namespace) -> int:
    if args.provider != "alpaca":
        print("UNSUPPORTED_PROVIDER: only alpaca is supported")
        print("Safety state: live trading=False, broker connected=False, orders sent=False")
        return 2
    downloader = AlpacaEquityIntradayDownloader()
    results = []
    try:
        for symbol in args.symbols:
            request = DownloadRequest(
                symbol=symbol,
                start=args.start,
                end=args.end,
                interval=args.interval,
                feed=args.feed,
                adjustment=args.adjustment,
                output_dir=args.output_dir,
                source_timezone=args.source_timezone,
                rth_only=args.rth_only,
            )
            if args.dry_run:
                result = downloader.dry_run(request)
                print(f"DRY_RUN endpoint={downloader.build_url(request)}")
                print(f"DRY_RUN output_file={result.output_file}")
            else:
                result = downloader.download(request)
                audit_report = None
                if args.audit_after_download or args.write_manifest:
                    report = audit_equity_intraday_csv(
                        result.output_file,
                        result.symbol,
                        "1min",
                        asset_class="equity",
                        source_timezone=args.source_timezone,
                        calendar=EquitySessionCalendar.from_config({"source": "us_equity"}),
                    )
                    audit_report = report
                    result = type(result)(
                        **{
                            **result.to_record(),
                            "audit_apt_for_or_fvg_backtest": report.apt_for_or_fvg_backtest,
                            "audit_critical_warnings": report.critical_warnings,
                        }
                    )
                    if not report.apt_for_or_fvg_backtest:
                        print(
                            f"AUDIT_NOT_FIT {result.symbol}: "
                            + ",".join(report.critical_warnings)
                        )
                if args.write_manifest:
                    manifest = build_dataset_manifest(
                        result,
                        audit_report=audit_report,
                        source_timezone=args.source_timezone,
                    )
                    manifest_path = write_dataset_manifest(
                        manifest,
                        args.manifest_dir,
                    )
                    print(f"MANIFEST: {manifest_path.resolve()}")
            _print_download_result(result)
            results.append(result)
    except AlpacaDownloadError as exc:
        print(f"{exc.code}: {exc}")
        print("Safety state: live trading=False, broker connected=False, orders sent=False")
        return 2
    print("Safety state: live trading=False, broker connected=False, orders sent=False")
    return 0


def command_download_binance(args: argparse.Namespace) -> int:
    provider = BinancePublicDataProvider()
    frame = provider.fetch(
        args.symbol,
        args.timeframe,
        limit=args.limit,
    )
    destination = save_local(
        frame,
        Path(args.output)
        if args.output
        else Path("data") / "raw" / f"{args.symbol.upper()}_{args.timeframe}.csv",
    )
    print(f"Saved {len(frame)} closed public candles to {destination.resolve()}")
    print("No API key, account endpoint, broker connection, or order endpoint was used.")
    return 0


def command_safety(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    print(json.dumps(config.security, indent=2))
    print("No broker/order implementation exists in the MVP.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="DayTrade Lab — research and simulation only"
    )
    parser.add_argument("--config", default="config.yaml")
    subparsers = parser.add_subparsers(dest="command", required=True)

    demo = subparsers.add_parser("demo", help="Run the offline synthetic-data demo")
    demo.add_argument("--sessions", type=int, default=90)
    demo.add_argument("--timeframe", choices=["5min", "15min", "30min"], default="15min")
    demo.add_argument("--seed", type=int, default=7)
    demo.set_defaults(func=command_demo)

    backtest = subparsers.add_parser("backtest", help="Backtest a local OHLCV CSV")
    backtest.add_argument("--csv", required=True)
    backtest.add_argument("--symbol", required=True)
    backtest.add_argument(
        "--timeframe",
        choices=["1min", "5min", "15min", "30min", "1h"],
        default="15min",
    )
    backtest.add_argument(
        "--asset-class",
        choices=["equity", "crypto"],
        default="equity",
    )
    backtest.add_argument(
        "--strategy",
        choices=available_strategy_names(),
        help="Run only the selected strategy instead of the full registry",
    )
    backtest.set_defaults(func=command_backtest)

    audit = subparsers.add_parser(
        "audit-data",
        help="Audit a local 1-minute equity/ETF OHLCV CSV without running backtests",
    )
    audit.add_argument("--csv", required=True)
    audit.add_argument("--symbol", required=True)
    audit.add_argument(
        "--timeframe",
        choices=["1min", "5min", "15min", "30min", "1h"],
        default="1min",
    )
    audit.add_argument(
        "--asset-class",
        choices=["equity"],
        default="equity",
    )
    audit.add_argument(
        "--source-timezone",
        help="Required when timestamps in the CSV are naive, e.g. America/New_York",
    )
    audit.add_argument(
        "--output-dir",
        help="Directory for JSON/CSV/Markdown audit reports",
    )
    audit.add_argument(
        "--fail-on-not-fit",
        action="store_true",
        help="Return exit code 2 when the dataset is not fit for OR/FVG backtests",
    )
    audit.set_defaults(func=command_audit_data)

    calendar = subparsers.add_parser(
        "calendar-diagnostics",
        help="Print expected US equity RTH sessions for a date range",
    )
    calendar.add_argument("--calendar", choices=["us_equity"], default="us_equity")
    calendar.add_argument("--start", required=True)
    calendar.add_argument("--end", required=True)
    calendar.add_argument("--format", choices=["csv", "json"], default="csv")
    calendar.set_defaults(func=command_calendar_diagnostics)

    equity_download = subparsers.add_parser(
        "download-equity-intraday",
        help="Download Alpaca Market Data stock bars into audit-data compatible CSVs",
    )
    equity_download.add_argument("--provider", choices=["alpaca"], default="alpaca")
    equity_download.add_argument("--symbols", nargs="+", required=True)
    equity_download.add_argument("--start", required=True)
    equity_download.add_argument("--end", required=True)
    equity_download.add_argument("--interval", default="1min")
    equity_download.add_argument("--feed", choices=["sip", "iex"], required=True)
    equity_download.add_argument(
        "--adjustment",
        choices=["raw", "split", "dividend", "all"],
        default="raw",
    )
    equity_download.add_argument("--output-dir", default=str(Path("data") / "raw"))
    equity_download.add_argument("--source-timezone", default="America/New_York")
    equity_download.add_argument("--dry-run", action="store_true")
    equity_download.add_argument("--audit-after-download", action="store_true")
    equity_download.add_argument("--write-manifest", action="store_true")
    equity_download.add_argument(
        "--manifest-dir",
        default=str(Path("data") / "manifests"),
    )
    equity_download.add_argument("--rth-only", action="store_true")
    equity_download.set_defaults(func=command_download_equity_intraday)

    download = subparsers.add_parser(
        "download-binance",
        help="Download public closed crypto candles (data only)",
    )
    download.add_argument("--symbol", default="BTCUSDT")
    download.add_argument(
        "--timeframe",
        choices=["1min", "5min", "15min", "30min", "1h"],
        default="15min",
    )
    download.add_argument("--limit", type=int, default=1000)
    download.add_argument("--output")
    download.set_defaults(func=command_download_binance)

    safety = subparsers.add_parser("safety", help="Display immutable safety state")
    safety.set_defaults(func=command_safety)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
