# DayTrade Lab — Sprint 2: validación con datos reales

## Veredicto

**Ninguna de las cinco estrategias merece pasar a replay.**

Las cinco familias fueron descartadas bajo las reglas actuales. Todas presentan
resultado, expectancy y profit factor out-of-sample negativos o insuficientes.
Ninguna pasa costos altos. Paper interno, paper broker y live trading permanecen
bloqueados.

La única combinación OOS positiva fue `SOLUSDT / 30min / Extreme Mean
Reversion`: 14 trades, retorno 0,68% y PF 1,40. Es una observación exploratoria,
no una candidata: la familia agregada tiene PF OOS 0,36 y expectancy negativa.

## Alcance

- Fuente: Binance Spot, market data pública.
- Activos: BTCUSDT, ETHUSDT y SOLUSDT.
- Timeframes: 5m, 15m y 30m.
- Período: 2022-01-01 a 2026-07-02, última vela cerrada disponible al descargar.
- Filas totales: 2.130.363.
- Combinaciones dataset/estrategia: 45.
- Escenarios principales: bajo, normal, alto y extremo.
- Split temporal: 70% train / 30% OOS.
- Walk-forward: año siguiente como test con parámetros fijos.
- No se optimizaron parámetros.

## Seguridad

```text
LIVE_TRADING_ENABLED=False
BROKER_CONNECTED=False
ORDERS_SENT=False
PAPER_INTERNAL_ENABLED=False
PAPER_BROKER_ENABLED=False
```

No existe cliente de broker ni método para enviar órdenes. La única superficie
de red es lectura de archivos públicos y `GET /api/v3/klines`. No se usaron API
keys.

## Descarga y trazabilidad

El historial se construyó con:

1. archivos mensuales públicos de Binance;
2. API REST paginada para completar el tramo posterior al último mes cerrado.

Cada CSV tiene un archivo `.metadata.json` con rango solicitado, requests,
reintentos, archivos mensuales, filas, duplicados, gaps, SHA-256, tamaño y estado
de seguridad. El descargador REST soporta reanudación, 429/418, `Retry-After`,
backoff, deduplicación y exclusión de velas abiertas.

Los timestamps de archivos Spot desde 2025 pueden estar en microsegundos; el
loader detecta la unidad por archivo y normaliza todo a UTC.

## Calidad de datos

| Activo | TF | Filas | Gaps | Cobertura |
|---|---:|---:|---:|---:|
| BTCUSDT | 5m | 473.413 | 16 | 99,9966% |
| BTCUSDT | 15m | 157.804 | 5 | 99,9968% |
| BTCUSDT | 30m | 78.902 | 2 | 99,9975% |
| ETHUSDT | 5m | 473.414 | 16 | 99,9966% |
| ETHUSDT | 15m | 157.805 | 5 | 99,9968% |
| ETHUSDT | 30m | 78.903 | 2 | 99,9975% |
| SOLUSDT | 5m | 473.414 | 16 | 99,9966% |
| SOLUSDT | 15m | 157.805 | 5 | 99,9968% |
| SOLUSDT | 30m | 78.903 | 2 | 99,9975% |

Los nueve datasets:

- no tienen timestamps duplicados;
- están estrictamente ordenados;
- usan UTC explícito;
- no contienen velas incompletas;
- no presentan OHLC inválido, precios no positivos ni volumen negativo;
- tienen metadata completa.

La continuidad estricta falla por interrupciones reales de Binance. No se
rellenaron velas. Las señales desde cada gap y durante las 200 velas siguientes
se marcaron como inválidas. Esto produjo 481 bloqueos
`BLOCKED_MISSING_DATA`.

## Costos simulados

Los bps se aplican por fill; las comisiones son por lado.

| Escenario | Spread | Slippage | Comisión |
|---|---:|---:|---:|
| Bajo | 0,5 bps | 0,5 bps | 2 bps |
| Normal | 1 bps | 1 bps | 10 bps |
| Alto | 3 bps | 3 bps | 10 bps |
| Extremo | 8 bps | 8 bps | 20 bps |

También se ejecutaron shocks aislados `spread 3x` y `slippage 3x`.

## Resultado OOS por estrategia

El retorno usa nueve bloques de capital independientes de USD 100.000 para no
tratar los 9 datasets como una única cuenta operable.

| Estrategia | Trades OOS | Retorno | PF | Expectancy | Alto costo | Estado |
|---|---:|---:|---:|---:|---:|---|
| Opening Range Breakout | 4.009 | -4,68% | 0,63 | -52,57 | -5,92% | Descartada |
| VWAP Pullback | 12.404 | -11,59% | 0,53 | -42,03 | -13,24% | Descartada |
| Relative Volume Momentum | 9.687 | -10,48% | 0,14 | -48,71 | -11,63% | Descartada |
| Extreme Mean Reversion | 604 | -1,17% | 0,36 | -87,16 | -1,37% | Descartada |
| Trend Day Continuation | 11.761 | -10,24% | 0,65 | -39,18 | -11,95% | Descartada |

Ni siquiera el escenario de costos bajos produjo resultado agregado positivo:
los PF estuvieron entre 0,52 y 0,92.

## Resultado OOS por activo

| Activo | Trades | Retorno combinado | PF | Max DD de dataset |
|---|---:|---:|---:|---:|
| BTCUSDT | 12.457 | -38,03% | 0,40 | 73,49% |
| ETHUSDT | 12.784 | -39,26% | 0,54 | 71,08% |
| SOLUSDT | 13.224 | -37,20% | 0,60 | 70,64% |

SOL fue relativamente menos malo, pero claramente negativo.

## Resultado OOS por timeframe

| TF | Trades | Retorno combinado | PF | Max DD de dataset |
|---|---:|---:|---:|---:|
| 5m | 17.673 | -47,89% | 0,36 | 73,49% |
| 15m | 12.843 | -40,54% | 0,55 | 65,26% |
| 30m | 7.949 | -26,06% | 0,66 | 49,71% |

30m fue menos perjudicial, pero no rentable. 5m fue el peor marco y el más
sensible a fricción.

## Walk-forward

Se evaluaron 36 folds por familia:

| Estrategia | Folds positivos | Folds totales | PF mediano |
|---|---:|---:|---:|
| Opening Range Breakout | 0 | 36 | 0,61 |
| VWAP Pullback | 0 | 36 | 0,53 |
| Relative Volume Momentum | 0 | 36 | 0,13 |
| Extreme Mean Reversion | 2 | 36 | 0,39 |
| Trend Day Continuation | 0 | 36 | 0,64 |

No hay estabilidad temporal.

## Sensibilidad

Todos los resultados agregados empeoran con costos altos, extremos, spread 3x y
slippage 3x. La pérdida ya existe con costos normales, por lo que no puede
atribuirse únicamente a una comisión conservadora.

En costos bajos:

| Estrategia | Retorno agregado | PF |
|---|---:|---:|
| Opening Range Breakout | -14,10% | 0,92 |
| Trend Day Continuation | -33,66% | 0,92 |
| VWAP Pullback | -38,19% | 0,89 |
| Relative Volume Momentum | -54,37% | 0,52 |
| Extreme Mean Reversion | -9,98% | 0,62 |

## Horario, día y régimen

No hubo una hora UTC, día de la semana, año, régimen tendencial ni bucket de
volatilidad con PnL agregado positivo. Las 00:00 UTC fueron especialmente malas,
en parte por la definición experimental de ORB.

Esto elimina la posibilidad de rescatar el resultado con un filtro horario
simple sin incurrir en data mining.

## Benchmarks

- **Cash/no operar:** 0; fue el mejor benchmark.
- **Buy-and-hold intradiario equivalente:** negativo en los 9 datasets. Es
  entrada y salida diaria UTC, no buy-and-hold tradicional; la rotación paga
  costos cada día.
- **Random entry con cantidad y niveles comparables:** todas las variantes
  negativas.
- **Momentum simple de 20 barras:** negativo en los 9 datasets.

Las estrategias suelen superar a su benchmark aleatorio equivalente, pero
“menos negativo que azar” no constituye edge.

## Psychology Guard

| Estrategia | Señales | Permitidas | Tasa | Delta PnL guard |
|---|---:|---:|---:|---:|
| Opening Range Breakout | 16.601 | 13.165 | 79,3% | +16.092 |
| VWAP Pullback | 201.198 | 41.133 | 20,4% | +816 |
| Relative Volume Momentum | 81.676 | 33.407 | 40,9% | +36.819 |
| Extreme Mean Reversion | 4.830 | 2.098 | 43,4% | +10.130 |
| Trend Day Continuation | 152.608 | 38.941 | 25,5% | -3.360 |

El guard mejoró cuatro familias en el contrafactual, pero ninguna se acercó a
rentabilidad. En Trend Day Continuation empeoró levemente.

Bloqueos destacados:

- FOMO: 20.002 señales; el contrafactual suma -204.397.
- Cooldown después de pérdida: 22.661; contrafactual -162.716.
- Máximas pérdidas consecutivas: 74.626; contrafactual -16.336.
- Overtrading: 21.482; contrafactual -5.089.
- Mala relación R/R: 1.048 bloqueos.

El guard reduce errores y pérdidas contrafactuales, pero no crea edge.

## Decisiones

### Descartadas bajo las reglas actuales

- Opening Range Breakout.
- VWAP Pullback.
- Relative Volume Momentum.
- Extreme Mean Reversion.
- Trend Day Continuation.

### Necesitan más pruebas

Ninguna estrategia completa justifica más replay con los parámetros actuales.
La anomalía `SOLUSDT / 30m / Extreme Mean Reversion` puede inspirar una nueva
hipótesis preregistrada, pero no debe reutilizarse como OOS ni optimizarse sobre
estos mismos datos.

### Candidatas a replay

**Ninguna.**

### Candidatas a paper interno

**Ninguna. Paper interno no fue activado.**

## Limitaciones

- Backtest por OHLCV: no reconstruye secuencia intrabar, order book ni queue.
- Spread es escenario, no bid/ask histórico observado.
- Binance Spot no permite short simétrico sin margin/derivados. Los shorts del
  laboratorio son hipótesis abstractas; no se modelan borrow, funding ni
  liquidación. Aun con esa concesión, el resultado fue negativo.
- ORB a 00:00 UTC es una frontera artificial en un mercado 24/7 y tiene menor
  sentido económico que una apertura bursátil.
- Universo de tres criptoactivos actuales; existe riesgo de selección y
  supervivencia.
- El volumen y la microestructura de Binance no representan otros venues.
- No se hicieron intervalos de confianza, bootstrap ni deflated Sharpe porque
  ninguna familia superó el filtro básico OOS.
- Los resultados no prueban que estas ideas nunca funcionen; prueban que estas
  reglas concretas no sobrevivieron este protocolo.

## Artefactos

Los archivos principales están en `outputs/daytrade/`:

- `real_data_backtest_summary.csv`
- `real_data_trades.csv`
- `real_data_blocked_trades.csv`
- `real_data_strategy_comparison.csv`
- `real_data_oos_results.csv`
- `real_data_walk_forward.csv`
- `real_data_cost_sensitivity.csv`
- `real_data_time_of_day.csv`
- `real_data_data_quality.csv`
- `real_data_psychology_guard.csv`
- `real_data_block_reasons.csv`
- `real_data_replay_candidates.csv`
- `real_data_report.html`
- `data_quality_report.csv`
- `data_quality_report.html`
