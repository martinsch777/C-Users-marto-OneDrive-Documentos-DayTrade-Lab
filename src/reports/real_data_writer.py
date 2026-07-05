from __future__ import annotations

import html
import json
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd


@dataclass
class RealDataReportBundle:
    data_quality: pd.DataFrame
    summary: pd.DataFrame
    strategy_comparison: pd.DataFrame
    oos_results: pd.DataFrame
    walk_forward: pd.DataFrame
    cost_sensitivity: pd.DataFrame
    dimensions: pd.DataFrame
    psychology_summary: pd.DataFrame
    block_reasons: pd.DataFrame
    candidates: pd.DataFrame
    benchmarks: pd.DataFrame
    safety: dict = field(default_factory=dict)


class RealDataReportWriter:
    def __init__(self, output_dir: str | Path = "outputs/daytrade") -> None:
        self.output_dir = Path(output_dir)

    @staticmethod
    def _table(frame: pd.DataFrame, limit: int = 250) -> str:
        if frame.empty:
            return "<p>Sin registros.</p>"
        return frame.head(limit).to_html(
            index=False,
            border=0,
            classes="data",
            float_format=lambda value: f"{value:.6g}",
        )

    def write_quality_report(self, quality: pd.DataFrame) -> Path:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        csv_path = self.output_dir / "data_quality_report.csv"
        html_path = self.output_dir / "data_quality_report.html"
        quality.to_csv(csv_path, index=False)
        valid_count = int(quality.get("quality_valid", pd.Series(dtype=bool)).sum())
        page = f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8"><title>Calidad de datos</title>
<style>
body {{font: 14px/1.5 system-ui; margin:2rem auto; max-width:1400px}}
.data {{border-collapse:collapse; width:100%; font-size:12px}}
.data th,.data td {{border:1px solid #ccd6df;padding:.35rem}} .data th {{background:#eaf2f7}}
</style></head><body>
<h1>DayTrade Lab — calidad de datos reales</h1>
<p>Datasets válidos: {valid_count}/{len(quality)}. Timestamps UTC; solo velas cerradas.</p>
{self._table(quality)}
</body></html>"""
        html_path.write_text(page, encoding="utf-8")
        return html_path

    def write(self, bundle: RealDataReportBundle) -> Path:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        safety = html.escape(json.dumps(bundle.safety, indent=2, ensure_ascii=False))
        candidate_counts = (
            bundle.candidates.groupby("status").size().to_dict()
            if not bundle.candidates.empty
            else {}
        )
        candidate_text = html.escape(
            json.dumps(candidate_counts, indent=2, ensure_ascii=False)
        )
        page = f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>DayTrade Lab — validación con datos reales</title>
  <style>
    body {{font: 14px/1.5 system-ui; margin:2rem auto; max-width:1500px; color:#17212b}}
    h1,h2,h3 {{color:#0b4f6c}}
    .warning {{background:#fff3cd;border-left:5px solid #d99b00;padding:1rem}}
    .data {{border-collapse:collapse;width:100%;font-size:11px;display:block;overflow:auto;max-height:650px}}
    .data th,.data td {{border:1px solid #ccd6df;padding:.3rem .4rem;white-space:nowrap}}
    .data th {{background:#eaf2f7;position:sticky;top:0}}
    pre {{background:#f5f7f9;padding:1rem}}
  </style>
</head>
<body>
  <h1>DayTrade Lab — Sprint 2</h1>
  <p class="warning"><strong>Investigación únicamente.</strong> Datos reales no implican edge.
  Paper interno, paper broker, brokers reales y live trading continúan bloqueados.</p>
  <h2>Seguridad</h2><pre>{safety}</pre>
  <h2>Veredicto</h2><pre>{candidate_text}</pre>{self._table(bundle.candidates)}
  <h2>Calidad de datos</h2>{self._table(bundle.data_quality)}
  <h2>Comparación de estrategias</h2>{self._table(bundle.strategy_comparison)}
  <h2>Benchmarks</h2>{self._table(bundle.benchmarks)}
  <h2>Out-of-sample</h2>{self._table(bundle.oos_results)}
  <h2>Walk-forward por año</h2>{self._table(bundle.walk_forward)}
  <h2>Sensibilidad a costos, spread y slippage</h2>{self._table(bundle.cost_sensitivity)}
  <h2>Psychology Guard</h2>{self._table(bundle.psychology_summary)}
  <h3>Motivos de bloqueo y contrafactual</h3>{self._table(bundle.block_reasons)}
  <h2>Horario, día, año, régimen y volatilidad</h2>{self._table(bundle.dimensions)}
  <h2>Matriz completa</h2>{self._table(bundle.summary)}
</body></html>"""
        destination = self.output_dir / "real_data_report.html"
        destination.write_text(page, encoding="utf-8")
        return destination
