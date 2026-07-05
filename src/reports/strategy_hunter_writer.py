from __future__ import annotations

import html
import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd


@dataclass
class StrategyHunterReportBundle:
    catalog: pd.DataFrame
    scoring: pd.DataFrame
    platforms: pd.DataFrame
    break_even: pd.DataFrame
    backtest: pd.DataFrame
    oos: pd.DataFrame
    walk_forward: pd.DataFrame
    random: pd.DataFrame
    ranking: pd.DataFrame
    psychology: pd.DataFrame
    quality: pd.DataFrame


class StrategyHunterReportWriter:
    def __init__(self, output_dir: str | Path) -> None:
        self.output_dir = Path(output_dir)

    @staticmethod
    def _table(frame: pd.DataFrame, limit: int = 300) -> str:
        if frame.empty:
            return "<p>Sin registros.</p>"
        return frame.head(limit).to_html(
            index=False,
            border=0,
            classes="data",
            float_format=lambda value: f"{value:.6g}",
        )

    def write(self, bundle: StrategyHunterReportBundle) -> Path:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        tested = int(len(bundle.ranking))
        candidates = int(bundle.ranking["candidate_for_replay"].astype(bool).sum())
        rejected_pretest = int(
            (bundle.scoring["classification"] == "rejected_before_test").sum()
        )
        page = f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>YouTube / Forum Strategy Hunter</title>
<style>
body {{font:14px/1.5 system-ui;margin:2rem auto;max-width:1500px;color:#17212b}}
h1,h2 {{color:#0b4f6c}} .warning {{background:#fff3cd;border-left:5px solid #d99b00;padding:1rem}}
.data {{border-collapse:collapse;width:100%;font-size:11px;display:block;overflow:auto;max-height:650px}}
.data th,.data td {{border:1px solid #ccd6df;padding:.3rem;white-space:nowrap}}
.data th {{background:#eaf2f7;position:sticky;top:0}}
</style></head><body>
<h1>YouTube / Forum Strategy Hunter</h1>
<p class="warning"><strong>Investigación únicamente.</strong> No hay broker, órdenes,
paper interno ni live trading. Una estrategia popular no se presume rentable.</p>
<p>Reglas y variantes testeadas: {tested}. Rechazadas antes de test: {rejected_pretest}.
Candidatas a replay: {candidates}.</p>
<h2>Ranking y veredicto</h2>{self._table(bundle.ranking)}
<h2>Filtro previo</h2>{self._table(bundle.scoring)}
<h2>Comparación de plataformas</h2>{self._table(bundle.platforms)}
<h2>Break-even de costos</h2>{self._table(bundle.break_even)}
<h2>Out-of-sample</h2>{self._table(bundle.oos)}
<h2>Walk-forward</h2>{self._table(bundle.walk_forward)}
<h2>Comparación aleatoria</h2>{self._table(bundle.random)}
<h2>Psychology Guard</h2>{self._table(bundle.psychology)}
<h2>Calidad de datos</h2>{self._table(bundle.quality)}
<h2>Matriz de backtest</h2>{self._table(bundle.backtest)}
</body></html>"""
        destination = self.output_dir / "strategy_hunter_report.html"
        destination.write_text(page, encoding="utf-8")
        return destination
