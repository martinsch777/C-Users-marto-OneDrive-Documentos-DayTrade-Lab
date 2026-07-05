import tempfile
import unittest
from pathlib import Path

import pandas as pd

from src.reports import ReportBundle, ReportWriter


class ReportTests(unittest.TestCase):
    def test_required_artifacts_are_created(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = ReportWriter(directory).write(
                ReportBundle(
                    metrics={"trade_count": 0, "total_return": 0},
                    strategy_comparison=pd.DataFrame(
                        [{"strategy": "test", "trade_count": 0}]
                    ),
                )
            )
            expected = {
                "backtest_summary.csv",
                "trades.csv",
                "blocked_trades.csv",
                "scanner_candidates.csv",
                "replay_sessions.csv",
                "journal.csv",
                "strategy_comparison.csv",
                "daytrade_report.html",
            }
            self.assertEqual(
                {Path(path).name for path in paths.values()},
                expected,
            )
            self.assertTrue(all(Path(path).exists() for path in paths.values()))


if __name__ == "__main__":
    unittest.main()
