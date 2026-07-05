# Lead Validation

Estado al 4 de julio de 2026: validación completada sin replay ni paper.

## Veredicto

Las dos pistas fueron debilitadas por la ampliación del universo. Ninguna merece
replay.

| Regla | Trades OOS | Retorno OOS | PF OOS | Costos altos | Años positivos | Supera random |
|---|---:|---:|---:|---:|---:|---:|
| Compression→Expansion canónica | 96 | -0,020% | 0,92 | -0,145% | 1 | 40% |
| FVG+MSS con RVOL>3 | 394 | +0,066% | 1,03 | -0,339% | 1 | 30% |
| FVG+MSS sin RVOL | 2.298 | -0,493% | 0,96 | -2,798% | 0 | 40% |
| RVOL>3 sin FVG | 17.431 | -21,01% | 0,63 | -39,20% | 0 | 10% |

La variante estricta de Compression→Expansion obtuvo PF 1,99, pero sólo 16
trades OOS, 9,2% de folds positivos y supera random en 15% de datasets. Fue
preregistrada como diagnóstico, no elegible para promoción. Seleccionarla sería
cherry-picking.

## Universo ampliado

Se usaron los 20 datasets Binance ya auditados:

- BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT y XRPUSDT;
- 1m, 5m, 15m y 30m;
- 1m desde 2025; los demás desde 2022;
- cuatro escenarios de costo;
- OOS 70/30, walk-forward anual, cash y random count-matched.

No se agregaron activos con menor liquidez ni datos no auditados.

## Compression → Expansion

Regla canónica congelada:

1. ATR actual relativo a la mediana causal de 288 barras.
2. Alguna de las seis barras previas tuvo ratio ATR ≤ 0,70.
3. La barra actual tiene ratio ATR ≥ 1,50.
4. RVOL actual ≥ 2x, calculado contra las 96 barras previas.
5. Cierre rompe el máximo/mínimo de 20 barras, excluyendo la actual.
6. Señal al cierre; ejecución desde la barra siguiente.
7. Stop de 1 ATR limitado por el extremo opuesto del rango; target 2R.

Variantes limitadas y predefinidas:

- strict: compresión 0,60, expansión 1,75, RVOL 2,5;
- frequency-probe: compresión 0,80, expansión 1,25, RVOL 1,5.

La canónica generó 403 señales y 96 trades OOS. La frequency-probe elevó la
muestra a 826 trades OOS, pero empeoró a PF 0,69. Por tanto, la escasez canónica
proviene de filtros estrictos, pero relajarlos no revela edge: agrega señales
malas.

Conclusión: pista descartada bajo la definición actual.

## FVG + MSS + RVOL

Definiciones congeladas:

- FVG bullish: low de la tercera vela por encima del high de dos velas atrás,
  con gap ≥ 0,2 ATR. Bearish inverso.
- MSS bullish: cierre actual por encima del máximo de las 20 velas previas,
  excluyendo la actual. Bearish inverso.
- El setup existe sólo después del cierre de la tercera vela.
- Entrada: retest del midpoint del FVG dentro de las diez velas siguientes y
  vela de confirmación cerrada.
- RVOL: volumen de la vela de entrada dividido por la media de las 96 velas
  anteriores; debe ser estrictamente >3.
- Stop detrás del swing causal de 20 barras; target 2R.

No se usa ZigZag, pivote confirmado con datos futuros ni rellenado retrospectivo.
Los tests comparan señales sobre prefijos visibles contra el histórico completo.

RVOL>3 mejora al FVG sin filtro:

- reduce 18.431 señales a 1.375;
- pasa de PF 0,96 a 1,03;
- pasa de retorno OOS -0,493% a +0,066%.

Pero el resultado no es edge aprobado:

- PF muy inferior a 1,25;
- costos altos y extremos lo vuelven negativo;
- sólo 2025 es positivo;
- únicamente 35,4% de folds son positivos;
- supera random en 30% de datasets.

Conclusión: RVOL elimina parte de las señales malas, pero no alcanza para crear
un setup robusto. Se puede conservar como lead forward de baja prioridad; no
merece replay.

## Funding y open interest

La integración quedó preparada:

- adaptadores separados Binance, Bybit y CSV offline;
- normalización de timestamps numéricos/texto a UTC;
- importación de nombres de columnas comunes;
- deduplicación y quality report;
- alineación `merge_asof(direction="backward")`, nunca hacia el futuro;
- edad del dato alineado en segundos.

Comando offline:

```powershell
python -m src.specialized_data_cli import `
  --kind funding `
  --symbol BTCUSDT `
  --provider bybit_manual `
  --source C:\ruta\funding.csv
```

La red continúa bloqueada por el entorno y no hay archivos manuales locales. Las
diez hipótesis funding/OI están marcadas
`not_tested_missing_historical_data`. No se puede afirmar que agreguen valor.

## Archivos

- `compression_expansion_validation.csv`
- `fvg_mss_rvol_validation.csv`
- `random_baseline_comparison.csv`
- `cost_sensitivity.csv`
- `year_asset_breakdown.csv`
- `lead_decisions.csv`
- `funding_oi_data_quality.csv`
- `funding_oi_hypothesis_status.csv`
- `lead_validation_report.html`

Todos están en `outputs/lead_validation/`.

## Reproducción

```powershell
python -m src.lead_validation_cli matrix --workers 1
python -m src.lead_validation_cli consolidate
python -m unittest discover -s tests -v
```

El problema sigue siendo falta de edge robusto, no sólo costos.

