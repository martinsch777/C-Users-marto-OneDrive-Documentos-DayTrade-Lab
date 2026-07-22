from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd


MINIMUM_COLUMNS = [
    "source_symbol",
    "normalized_symbol",
    "trade_num",
    "direction",
    "entry_time_unix_ms",
    "entry_time_utc",
    "entry_time_ny",
    "entry_price",
    "exit_time_unix_ms",
    "exit_time_utc",
    "exit_time_ny",
    "exit_price",
    "qty",
    "profit",
    "commission",
    "entry_id",
    "exit_id",
    "entry_comment",
    "exit_comment",
]


@dataclass(frozen=True)
class PineLogValidation:
    trade_count: int
    min_trade_num: int
    max_trade_num: int
    duplicate_trade_nums: list[int]
    missing_trade_nums: list[int]
    first_entry_date: str
    last_entry_date: str
    normalized_symbols: list[str]
    all_qty_one: bool
    profit_sum: float
    session_close_exit_count: int

    def to_record(self) -> dict[str, Any]:
        return {
            "trade_count": self.trade_count,
            "min_trade_num": self.min_trade_num,
            "max_trade_num": self.max_trade_num,
            "duplicate_trade_nums": self.duplicate_trade_nums,
            "missing_trade_nums": self.missing_trade_nums,
            "first_entry_date": self.first_entry_date,
            "last_entry_date": self.last_entry_date,
            "normalized_symbols": self.normalized_symbols,
            "all_qty_one": self.all_qty_one,
            "profit_sum": self.profit_sum,
            "session_close_exit_count": self.session_close_exit_count,
        }


def _normalize_symbol(value: str) -> str:
    return value.split(":", 1)[-1].upper()


def _clean_unix_ms(value: str) -> int:
    return int(str(value).replace(",", ""))


def _timestamp_from_ms(value: int) -> pd.Timestamp:
    return pd.to_datetime(value, unit="ms", utc=True)


def _parse_trade_payload(payload: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for part in payload.split("|"):
        if not part:
            continue
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        fields[key.strip()] = value.strip()
    return fields


def parse_pine_log_text(text: str) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if "TVTRADE|" not in line:
            continue
        payload = line.split("TVTRADE|", 1)[1].strip()
        fields = _parse_trade_payload(payload)
        missing = [
            key
            for key in (
                "symbol",
                "trade_num",
                "direction",
                "entry_time",
                "entry_price",
                "exit_time",
                "exit_price",
                "qty",
                "profit",
                "commission",
                "entry_id",
                "exit_id",
                "entry_comment",
                "exit_comment",
            )
            if key not in fields
        ]
        if missing:
            raise ValueError(f"Missing Pine log fields on line {line_number}: {missing}")
        entry_ms = _clean_unix_ms(fields["entry_time"])
        exit_ms = _clean_unix_ms(fields["exit_time"])
        entry_utc = _timestamp_from_ms(entry_ms)
        exit_utc = _timestamp_from_ms(exit_ms)
        rows.append(
            {
                "source_symbol": fields["symbol"],
                "normalized_symbol": _normalize_symbol(fields["symbol"]),
                "trade_num": int(fields["trade_num"]),
                "direction": fields["direction"].lower(),
                "entry_time_unix_ms": entry_ms,
                "entry_time_utc": entry_utc.isoformat(),
                "entry_time_ny": entry_utc.tz_convert("America/New_York").isoformat(),
                "entry_price": float(fields["entry_price"]),
                "exit_time_unix_ms": exit_ms,
                "exit_time_utc": exit_utc.isoformat(),
                "exit_time_ny": exit_utc.tz_convert("America/New_York").isoformat(),
                "exit_price": float(fields["exit_price"]),
                "qty": float(fields["qty"]),
                "profit": float(fields["profit"]),
                "commission": float(fields["commission"]),
                "entry_id": fields["entry_id"],
                "exit_id": fields["exit_id"],
                "entry_comment": fields["entry_comment"],
                "exit_comment": fields["exit_comment"],
            }
        )
    frame = pd.DataFrame(rows, columns=MINIMUM_COLUMNS)
    if frame.empty:
        raise ValueError("No TVTRADE records found in Pine log text")
    duplicates = sorted(
        frame.loc[frame["trade_num"].duplicated(keep=False), "trade_num"]
        .astype(int)
        .unique()
        .tolist()
    )
    if duplicates:
        raise ValueError(f"Duplicate trade_num values: {duplicates}")
    expected = set(range(int(frame["trade_num"].min()), int(frame["trade_num"].max()) + 1))
    actual = set(frame["trade_num"].astype(int).tolist())
    missing = sorted(expected.difference(actual))
    if missing:
        raise ValueError(f"Missing trade_num values: {missing}")
    return frame.sort_values(["entry_time_unix_ms", "trade_num"]).reset_index(drop=True)


def parse_pine_log_file(path: str | Path) -> pd.DataFrame:
    return parse_pine_log_text(Path(path).read_text(encoding="utf-8"))


def validate_pine_trades(
    trades: pd.DataFrame,
    *,
    expected_count: int = 40,
    expected_min_trade_num: int = 0,
    expected_max_trade_num: int = 39,
    expected_first_entry_date: str = "2026-04-13",
    expected_last_entry_date: str = "2026-07-06",
    expected_symbol: str = "QQQ",
    expected_profit_sum: float = 13.17,
    profit_tolerance: float = 0.02,
    expected_session_close_exits: int = 3,
) -> PineLogValidation:
    duplicate_trade_nums = sorted(
        trades.loc[trades["trade_num"].duplicated(keep=False), "trade_num"]
        .astype(int)
        .unique()
        .tolist()
    )
    actual_nums = set(trades["trade_num"].astype(int).tolist())
    missing = sorted(set(range(expected_min_trade_num, expected_max_trade_num + 1)).difference(actual_nums))
    entry_dates = pd.to_datetime(trades["entry_time_ny"], utc=True).dt.tz_convert(
        ZoneInfo("America/New_York")
    ).dt.date.astype(str)
    summary = PineLogValidation(
        trade_count=int(len(trades)),
        min_trade_num=int(trades["trade_num"].min()),
        max_trade_num=int(trades["trade_num"].max()),
        duplicate_trade_nums=duplicate_trade_nums,
        missing_trade_nums=missing,
        first_entry_date=str(entry_dates.iloc[0]),
        last_entry_date=str(entry_dates.iloc[-1]),
        normalized_symbols=sorted(trades["normalized_symbol"].astype(str).unique().tolist()),
        all_qty_one=bool((trades["qty"].astype(float) == 1.0).all()),
        profit_sum=float(trades["profit"].astype(float).sum()),
        session_close_exit_count=int((trades["exit_comment"] == "Cierre fin de sesión").sum()),
    )
    failures: list[str] = []
    if summary.trade_count != expected_count:
        failures.append(f"trade_count={summary.trade_count}")
    if summary.min_trade_num != expected_min_trade_num:
        failures.append(f"min_trade_num={summary.min_trade_num}")
    if summary.max_trade_num != expected_max_trade_num:
        failures.append(f"max_trade_num={summary.max_trade_num}")
    if summary.duplicate_trade_nums:
        failures.append(f"duplicate_trade_nums={summary.duplicate_trade_nums}")
    if summary.missing_trade_nums:
        failures.append(f"missing_trade_nums={summary.missing_trade_nums}")
    if summary.first_entry_date != expected_first_entry_date:
        failures.append(f"first_entry_date={summary.first_entry_date}")
    if summary.last_entry_date != expected_last_entry_date:
        failures.append(f"last_entry_date={summary.last_entry_date}")
    if summary.normalized_symbols != [expected_symbol]:
        failures.append(f"normalized_symbols={summary.normalized_symbols}")
    if not summary.all_qty_one:
        failures.append("qty_not_all_one")
    if abs(summary.profit_sum - expected_profit_sum) > profit_tolerance:
        failures.append(f"profit_sum={summary.profit_sum:.6f}")
    if summary.session_close_exit_count != expected_session_close_exits:
        failures.append(f"session_close_exit_count={summary.session_close_exit_count}")
    if failures:
        raise ValueError("Pine log validation failed: " + "; ".join(failures))
    return summary


def write_trades_csv(trades: pd.DataFrame, output_path: str | Path) -> Path:
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    trades.loc[:, MINIMUM_COLUMNS].to_csv(destination, index=False)
    return destination


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Parse TradingView Pine TVTRADE logs")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--summary-json", default="")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    trades = parse_pine_log_file(args.input)
    summary = validate_pine_trades(trades)
    output = write_trades_csv(trades, args.output)
    payload = {
        "output": str(output),
        "validation": summary.to_record(),
    }
    if args.summary_json:
        Path(args.summary_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.summary_json).write_text(
            json.dumps(payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
