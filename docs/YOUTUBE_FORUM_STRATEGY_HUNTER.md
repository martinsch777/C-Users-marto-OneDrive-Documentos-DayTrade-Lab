# YouTube / Forum Strategy Hunter

Estado al 3 de julio de 2026: sprint completado en modo investigación. No se
habilitó live trading, broker, envío de órdenes, paper broker ni paper interno.

## Veredicto

No hay candidatas a replay. Las 12 reglas y variantes efectivamente testeadas
fallaron el filtro OOS; por lo tanto, ninguna puede pasar a paper interno.

| Rank | Regla | Trades OOS | Retorno OOS agregado | PF OOS | Folds positivos | Supera random |
|---:|---|---:|---:|---:|---:|---:|
| 1 | FVG + Market Structure Shift | 2.579 | -3,37% | 0,75 | 29,2% | 25% |
| 2 | EMA 9/21 + VWAP, 2R | 8.378 | -12,19% | 0,71 | 12,3% | 45% |
| 3 | EMA 9/21 + VWAP, 1,5R | 7.135 | -10,79% | 0,66 | 9,2% | 15% |
| 4 | Heikin Ashi + EMA | 18.969 | -29,52% | 0,62 | 1,5% | 25% |
| 5 | VWAP Deviation Reversion | 1.567 | -2,94% | 0,54 | 7,7% | 15% |
| 6 | Liquidity Sweep + Reversal | 17.415 | -33,59% | 0,51 | 0% | 0% |
| 7 | Bollinger + RSI | 748 | -1,39% | 0,45 | 18,5% | 10% |
| 8 | Donchian, 2R | 17.134 | -33,01% | 0,43 | 0% | 10% |
| 9 | MACD + RSI | 10.393 | -18,71% | 0,42 | 0% | 10% |
| 10 | Supertrend + EMA200 | 10.793 | -20,03% | 0,38 | 0% | 10% |
| 11 | Donchian, 1,5R | 14.493 | -28,87% | 0,36 | 0% | 0% |
| 12 | EMA 9/21 + VWAP, 1R | 0 | 0% | 0 | 0% | 0% |

La variante EMA 1R fue bloqueada por el mínimo de riesgo/beneficio predefinido
de 1,5. No se relajó el control para fabricar trades.

El mejor resultado aislado fue FVG en BNBUSDT 1m, pero no alcanza para aprobar
la familia: el agregado es negativo, PF 0,75, sólo 29,2% de folds positivos y
supera al baseline aleatorio en apenas 25% de los datasets. Aceptarlo sería
cherry-picking.

## Intake y filtro previo

Se registraron diez familias en
`data/strategy_intake/strategy_catalog.yaml`, con fuente, reglas long/short,
salidas, riesgo, horarios, supuestos, datos requeridos y riesgos de ambigüedad,
repainting, look-ahead y cherry-picking.

- Siete familias quedaron `testable`.
- Liquidity Sweep y FVG quedaron `testable_with_clarifications`. Sólo se
  ejecutaron sus traducciones causales congeladas, sin ZigZag ni pivotes
  confirmados con datos futuros.
- Funding/Basis Mean Reversion fue `rejected_before_test`: faltan históricos
  sincronizados de funding, basis, open interest, spot y perpetuos. No se
  sustituyeron esos datos por OHLCV.
- Ninguna familia adicional fue rechazada sólo por ambigüedad: las dos familias
  SMC ambiguas pudieron convertirse en reglas objetivas, pero conservan esa
  advertencia en el scoring.

## Datos

Se usaron velas públicas reales de Binance, sin API key:

- BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT y XRPUSDT.
- 5m, 15m y 30m: 2022-01-01 a 2026-07-02.
- 1m: 2025-01-01 a 2026-07-03.
- 20 datasets, entre 78.902 y 790.172 barras cada uno.
- Cobertura auditada entre 99,9966% y 100%; todos resultaron aptos para
  investigación.

No se incorporaron acciones/ETF. No había un feed SIP intradiario confiable
configurado; usar sólo IEX habría sesgado volumen relativo y VWAP. La
documentación de Alpaca distingue el feed IEX gratuito del SIP consolidado:
[Historical Stock Data](https://docs.alpaca.markets/us/docs/historical-stock-data-1)
y [Market Data FAQ](https://docs.alpaca.markets/us/docs/market-data-faq).

## Protocolo

Cada regla usó señales al cierre de vela y ejecución en la vela siguiente.
Cuando stop y target podían tocarse en la misma vela, se aplicó `stop_first`.
No hubo búsqueda de parámetros: sólo las variantes predefinidas 1R, 1,5R y 2R.

La validación incluyó:

- backtest completo;
- split temporal OOS 70/30;
- walk-forward anual anclado;
- bloques por activo, timeframe, año, hora UTC, régimen y volatilidad;
- costos low, normal, high y extreme;
- baseline aleatorio determinístico con igual cantidad de trades;
- cash como umbral de retorno cero;
- concentración por activo, año, hora y trade individual;
- Psychology Guard con régimen desfavorable.

Buy-and-hold intradiario no se aplicó: en cripto 24/7 no existe una sesión diaria
homogénea equivalente y las reglas incluyen long/short. Cash y random
count-matched son los comparadores pertinentes para este protocolo.

## Costos y plataformas

El modelo guarda fecha, supuestos y fuente por perfil. Los costos estimados de
ida y vuelta para órdenes taker son:

| Perfil | Round-trip |
|---|---:|
| Binance spot VIP0 | 23,0 bps |
| Binance USD-M futures VIP0 | 13,2 bps |
| Bybit spot VIP0 | 23,9 bps |
| Bybit futures VIP0 | 15,0 bps |
| Kraken Pro, tier inicial | 87,0 bps |
| Alpaca IEX (proxy acciones) | 6,2 bps |
| Alpaca SIP (proxy acciones) | 4,2 bps + datos |
| IBKR Pro fixed (proxy acciones) | 6,2 bps |

Fuentes: [Binance fee calculation](https://academy.binance.com/en/articles/how-to-calculate-transaction-fees-on-binance),
[Bybit fee structure](https://www.bybit.com/en/help-center/article/Trading-Fee-Structure),
[Kraken fee schedule](https://www.kraken.com/features/fee-schedule),
[Alpaca regulatory fees](https://docs.alpaca.markets/us/docs/regulatory-fees) e
[IBKR commissions](https://www.interactivebrokers.com/en/pricing/commissions-stocks.php).
Son costos sujetos a cambios y deben verificarse antes de una investigación
futura.

Incluso el escenario low dejó negativas las 12 reglas. El problema principal
es la ausencia de edge robusto en las reglas testeadas; los costos agravan el
resultado, pero no explican por sí solos el fracaso. La ejecución conservadora
también reduce resultados, como debe ocurrir en una prueba prudente. Psychology
Guard mejoró el PnL respecto del contrafactual permisivo, pero no creó edge.

## Reproducción

```powershell
python -m src.strategy_hunter_cli intake
python -m src.strategy_hunter_cli costs
python -m src.strategy_hunter_cli audit
python -m src.strategy_hunter_cli matrix --workers 1
python -m src.strategy_hunter_cli variant-matrix --workers 1
python -m src.strategy_hunter_cli consolidate
python -m unittest discover -s tests -v
```

Los stages tienen checkpoints. En esta máquina, más de un worker agotó memoria
durante 15m; un worker es la opción segura.

## Artefactos

Los CSV y el reporte navegable están en
`outputs/daytrade_strategy_hunter/`. El ranking canónico es
`strategy_ranking.csv`; `strategy_hunter_report.html` reúne intake, scoring,
costos, OOS, walk-forward, random baseline, Psychology Guard y calidad de datos.
