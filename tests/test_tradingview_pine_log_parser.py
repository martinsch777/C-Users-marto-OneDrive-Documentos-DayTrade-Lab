import tempfile
import unittest
from pathlib import Path

import pandas as pd

from src.research.tradingview_pine_log_parser import (
    parse_pine_log_file,
    parse_pine_log_text,
    validate_pine_trades,
    write_trades_csv,
)


LINE0 = (
    "[2026-04-13T16:40:00.000+02:00]: ignored prefix "
    "TVTRADE|symbol=BATS:QQQ|trade_num=0|direction=SHORT|"
    "entry_time=1,776,089,700,000|entry_price=610.77|"
    "exit_time=1,776,091,200,000|exit_price=611.89|qty=1|"
    "profit=-1.242|commission=0.122|entry_id=Short|exit_id=Short TP-SL|"
    "entry_comment=First Candle Short|exit_comment=TP o SL"
)
LINE1 = (
    "noise TVTRADE|symbol=BATS:QQQ|trade_num=1|direction=LONG|"
    "entry_time=1,776,095,700,000|entry_price=612.00|"
    "exit_time=1,776,097,200,000|exit_price=613.00|qty=1|"
    "profit=0.877|commission=0.123|entry_id=Long|exit_id=Close position order|"
    "entry_comment=First Candle Long|exit_comment=Cierre fin de sesión"
)


class TradingViewPineLogParserTests(unittest.TestCase):
    def test_parser_ignores_visual_timestamp_and_normalizes_fields(self):
        trades = parse_pine_log_text("header\n" + LINE0 + "\n" + LINE1)
        self.assertEqual(len(trades), 2)
        first = trades.iloc[0]
        self.assertEqual(first["source_symbol"], "BATS:QQQ")
        self.assertEqual(first["normalized_symbol"], "QQQ")
        self.assertEqual(first["direction"], "short")
        self.assertEqual(first["entry_time_unix_ms"], 1776089700000)
        self.assertEqual(pd.Timestamp(first["entry_time_utc"]).tz_convert("America/New_York").date().isoformat(), "2026-04-13")
        self.assertAlmostEqual(first["entry_price"], 610.77)
        self.assertAlmostEqual(first["qty"], 1.0)
        self.assertEqual(first["exit_comment"], "TP o SL")

    def test_duplicate_trade_num_fails(self):
        duplicate = LINE0 + "\n" + LINE0.replace("entry_time=1,776,089,700,000", "entry_time=1,776,095,700,000")
        with self.assertRaisesRegex(ValueError, "Duplicate trade_num"):
            parse_pine_log_text(duplicate)

    def test_missing_trade_num_fails(self):
        gap = LINE0 + "\n" + LINE1.replace("trade_num=1", "trade_num=2")
        with self.assertRaisesRegex(ValueError, "Missing trade_num"):
            parse_pine_log_text(gap)

    def test_file_parse_validation_and_csv_write(self):
        directory = Path(tempfile.mkdtemp())
        source = directory / "logs.txt"
        source.write_text(LINE0 + "\n" + LINE1, encoding="utf-8")
        trades = parse_pine_log_file(source)
        summary = validate_pine_trades(
            trades,
            expected_count=2,
            expected_min_trade_num=0,
            expected_max_trade_num=1,
            expected_first_entry_date="2026-04-13",
            expected_last_entry_date="2026-04-13",
            expected_profit_sum=-0.365,
            expected_session_close_exits=1,
        )
        self.assertEqual(summary.trade_count, 2)
        output = write_trades_csv(trades, directory / "out.csv")
        self.assertTrue(output.exists())
        loaded = pd.read_csv(output)
        self.assertEqual(list(loaded["trade_num"]), [0, 1])


if __name__ == "__main__":
    unittest.main()
