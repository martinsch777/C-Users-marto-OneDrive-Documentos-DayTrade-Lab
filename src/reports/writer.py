from __future__ import annotations

import html
import json
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd


@dataclass
class ReportBundle:
    metrics: dict
    trades: pd.DataFrame = field(default_factory=pd.DataFrame)
    blocked_trades: pd.DataFrame = field(default_factory=pd.DataFrame)
    scanner_candidates: pd.DataFrame = field(default_factory=pd.DataFrame)
    replay_sessions: pd.DataFrame = field(default_factory=pd.DataFrame)
    journal: pd.DataFrame = field(default_factory=pd.DataFrame)
    strategy_comparison: pd.DataFrame = field(default_factory=pd.DataFrame)
    diagnostics: dict[str, pd.DataFrame] = field(default_factory=dict)
    approval: dict = field(default_factory=dict)


class ReportWriter:
    def __init__(self, output_dir: str | Path = "outputs/daytrade") -> None:
        self.output_dir = Path(output_dir)

    @staticmethod
    def _write_csv(frame: pd.DataFrame, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(destination, index=False)

    @staticmethod
    def _table(frame: pd.DataFrame, limit: int = 100) -> str:
        if frame.empty:
            return "<p>No hay registros.</p>"
        return frame.head(limit).to_html(index=False, border=0, classes="data")

    def write(self, bundle: ReportBundle) -> dict[str, Path]:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        paths = {
            "backtest_summary": self.output_dir / "backtest_summary.csv",
            "trades": self.output_dir / "trades.csv",
            "blocked_trades": self.output_dir / "blocked_trades.csv",
            "scanner_candidates": self.output_dir / "scanner_candidates.csv",
            "replay_sessions": self.output_dir / "replay_sessions.csv",
            "journal": self.output_dir / "journal.csv",
            "strategy_comparison": self.output_dir / "strategy_comparison.csv",
            "html": self.output_dir / "daytrade_report.html",
        }
        summary = pd.DataFrame(
            [
                {
                    key: value
                    if not isinstance(value, (dict, list, tuple))
                    else json.dumps(value)
                    for key, value in bundle.metrics.items()
                }
            ]
        )
        self._write_csv(summary, paths["backtest_summary"])
        self._write_csv(bundle.trades, paths["trades"])
        self._write_csv(bundle.blocked_trades, paths["blocked_trades"])
        self._write_csv(bundle.scanner_candidates, paths["scanner_candidates"])
        self._write_csv(bundle.replay_sessions, paths["replay_sessions"])
        self._write_csv(bundle.journal, paths["journal"])
        self._write_csv(bundle.strategy_comparison, paths["strategy_comparison"])

        diagnostics_html = "".join(
            f"<h3>{html.escape(name)}</h3>{self._table(frame)}"
            for name, frame in bundle.diagnostics.items()
        )
        approval = html.escape(json.dumps(bundle.approval, indent=2, default=str))
        report = f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>DayTrade Lab — Reporte de investigación</title>
  <style>
    body {{ font: 15px/1.5 system-ui, sans-serif; margin: 2rem auto; max-width: 1200px; color: #18212b; }}
    h1, h2, h3 {{ color: #0b4f6c; }}
    .warning {{ background: #fff3cd; border-left: 5px solid #e0a800; padding: 1rem; }}
    .data {{ border-collapse: collapse; width: 100%; font-size: 13px; display: block; overflow-x: auto; }}
    .data th, .data td {{ border: 1px solid #d9e1e8; padding: .35rem .5rem; }}
    .data th {{ background: #edf5f8; }}
    pre {{ background: #f5f7f9; padding: 1rem; overflow-x: auto; }}
  </style>
</head>
<body>
  <h1>DayTrade Lab</h1>
  <p class="warning"><strong>Solo investigación.</strong> Live trading, brokers y envío de órdenes están bloqueados.</p>
  <h2>Resumen</h2>
  {self._table(summary)}
  <h2>Aprobación para paper interno</h2>
  <pre>{approval}</pre>
  <h2>Comparación de estrategias</h2>
  {self._table(bundle.strategy_comparison)}
  <h2>Diagnósticos de robustez</h2>
  {diagnostics_html or '<p>No hay diagnósticos.</p>'}
  <h2>Operaciones simuladas</h2>
  {self._table(bundle.trades)}
  <h2>Señales bloqueadas</h2>
  {self._table(bundle.blocked_trades)}
  <h2>Scanner</h2>
  {self._table(bundle.scanner_candidates)}
</body>
</html>
"""
        paths["html"].write_text(report, encoding="utf-8")
        return paths
