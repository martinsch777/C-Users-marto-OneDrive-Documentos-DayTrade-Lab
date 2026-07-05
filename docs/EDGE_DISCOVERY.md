# DayTrade Edge Discovery

Estado al 4 de julio de 2026: sprint completado en modo investigación.

## Veredicto

No hay hipótesis aptas para replay ni paper interno.

El cambio desde estrategias genéricas hacia eventos sí tiene sentido: produjo
dos pistas más informativas que los indicadores aislados. Aun así, ninguna
supera hoy el protocolo de aprobación.

| Rank | Hipótesis | Trades OOS | Retorno OOS | PF OOS | Folds positivos | Supera random | Estado |
|---:|---|---:|---:|---:|---:|---:|---|
| 1 | Compression → Expansion Breakout | 24 | +0,046% | 1,27 | 30% | 60% | Más pruebas |
| 2 | Large Wick + Volume Reversal | 2.733 | -10,67% | 0,69 | 7,5% | 20% | Descartada |
| 3 | Post-Extreme Reversal 1,5R | 2.610 | -7,99% | 0,67 | 2,5% | 0% | Descartada |
| 4 | Post-Extreme Reversal 1R | 2.657 | -7,55% | 0,63 | 0% | 30% | Descartada |
| 5 | Extreme Move Continuation | 1.426 | -4,07% | 0,60 | 5% | 30% | Descartada |

Compression→Expansion no pasa porque:

- sólo tiene 24 trades OOS;
- con costos altos vuelve a -0,050%;
- únicamente un activo y un año quedan positivos;
- sólo 30% de los folds walk-forward son positivos.

No se bajaron umbrales para aumentar artificialmente la muestra.

## Pista secundaria: mejorar FVG con un evento

Se aplicaron cinco filtros causales a las estrategias del sprint anterior. De 45
combinaciones, una quedó positiva con costos normales:

- FVG + MSS condicionado a RVOL > 3x;
- 111 trades OOS;
- PnL neto normal +USD 3.880,83;
- expectancy +USD 34,96 por trade;
- PF normal 1,20;
- PnL con costos altos +USD 2.591,85;
- PF con costos altos 1,13;
- tres activos positivos, pero sólo un año positivo.

Es una hipótesis para confirmar con datos nuevos, no una candidata a replay:
incumple PF > 1,25, estabilidad anual y validación independiente. El archivo
`prior_strategy_filter_analysis.csv` conserva todas las comparaciones, incluidas
las negativas.

## Datos y protocolo

Se usaron diez datasets Binance ya auditados:

- BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT y XRPUSDT;
- 5m y 15m;
- 2022–2026;
- cobertura entre 99,9966% y 99,9968%.

Las reglas quedaron congeladas antes de mirar el ranking. Cada señal usa sólo
velas cerradas y se ejecuta desde la vela siguiente. Se aplicaron:

- backtest completo;
- OOS temporal 70/30;
- walk-forward anual;
- bloques por activo, año y timeframe;
- costos low, normal, high y extreme;
- baseline aleatorio determinístico con igual número de trades;
- cash como retorno cero;
- ejecución `stop_first`, spread, slippage, comisiones y controles de riesgo.

El escenario normal representa aproximadamente 13 bps round-trip: 5 bps de
comisión por lado, 1 bp de spread y 1 bp de slippage por lado.

## Etiquetas de eventos

Todas son causales y tienen umbrales fijos:

- `EXTREME_UP_MOVE` / `EXTREME_DOWN_MOVE`: movimiento de tres barras ≥ 2 ATR;
- `HIGH_RELATIVE_VOLUME`: volumen ≥ 3x la media previa de 96 barras;
- `LARGE_WICK_REVERSAL`: wick ≥ 1,5x body y cierre de rechazo;
- `VOLATILITY_EXPANSION`: ATR ≥ 1,5x mediana previa;
- `VOLATILITY_COMPRESSION`: ATR ≤ 0,7x mediana previa;
- funding extremo: ±5 bps por intervalo;
- spike de OI: cambio absoluto ≥ 5%;
- spread widening: ≥ 2x mediana previa;
- liquidation cascade: ≥ 5x mediana y USD 100.000.

Los movimientos extremos bajistas muestran una reversión media de apenas 0,66
bps a una barra y 1,36 bps a seis barras, muy por debajo del costo normal. Las
subidas extremas no muestran reversión persistente. Esto explica por qué el
efecto estadístico bruto desaparece al convertirlo en trades realistas.

## Funding, OI, book, liquidaciones y noticias

- Funding y OI: conectores y parsers implementados, pero sin historial local por
  bloqueo de red de esta ejecución. No se emitió resultado inventado.
- Order book/spread/aggressor: sólo forward hasta reunir captura continua y
  auditable.
- Liquidaciones: forward por WebSocket o histórico pago; OHLCV no se etiquetó
  falsamente como liquidación.
- News, earnings y gaps premarket: requieren SIP/extended-hours y calendario de
  catalizadores confiable. Se difieren.

El detalle está en [EDGE_DATA_SOURCES.md](EDGE_DATA_SOURCES.md).

## Rare Setup Scanner

El scanner exige simultáneamente RVOL > 3x, movimiento > 2 ATR, expansión de
volatilidad y ruptura del rango previo. Sobre los últimos 90 días históricos
generó:

- 1.117 observaciones;
- 764 bloqueadas por aparecer más de dos veces ese día;
- 353 pendientes de confirmar spread y liquidez en datos forward.

No son recomendaciones ni órdenes. Sin spread histórico real, el scanner marca
`requires_forward_spread_and_liquidity_confirmation`.

## Forward collector y seguridad

El collector está en `src/edge_discovery/collector.py` y escribe sólo en
`data/forward_collector/`. Está desactivado por defecto.

- No acepta API key ni secreto.
- No tiene métodos de cuenta, broker, órdenes o leverage.
- Sólo permite cuatro endpoints GET públicos de datos Binance Futures.
- Live, broker, órdenes, paper interno, paper broker y leverage real siguen en
  `false`.

## Reproducción

```powershell
python -m src.edge_discovery_cli sources
python -m src.edge_discovery_cli matrix --workers 1
python -m src.edge_discovery_cli consolidate
python -m unittest discover -s tests -v
```

## Conclusión

El problema sigue siendo falta de edge robusto. Costos y ejecución conservadora
agravan los resultados, pero cuatro de cinco hipótesis ya son negativas antes de
cualquier argumento de escala.

Sí conviene continuar por eventos, con dos prioridades:

1. Confirmación forward de FVG+MSS con RVOL > 3x, sin cambiar reglas.
2. Reunir muestra independiente de compression→expansion, book, spread,
   agresor, OI y liquidaciones.

Hasta entonces: cero replay, cero paper y cero capital real.

