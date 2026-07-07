# DayTrade Lab

Laboratorio **offline-first** para investigar estrategias intradiarias con datos
OHLCV, ejecución simulada conservadora, controles de riesgo y bloqueos contra
errores humanos.

No es un bot de trading. No conecta brokers, no envía órdenes y no promete
rentabilidad. Los resultados sintéticos solo demuestran que el software funciona;
no son evidencia de edge.

## Estado de seguridad

- `LIVE_TRADING_ENABLED = False`
- `BROKER_CONNECTED = False`
- `ORDERS_SENT = False`
- `PAPER_INTERNAL_ENABLED = False`
- `PAPER_BROKER_ENABLED = False`
- No existe cliente de órdenes ni método de conexión a broker.
- La configuración se rechaza al iniciar si cualquiera de esos tres valores es
  distinto de `false`.

## Inicio rápido en Windows

Abrí PowerShell dentro de esta carpeta:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python -m src.cli demo
```

Si PowerShell no permite activar el entorno, podés ejecutar directamente:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m src.cli demo
```

El reporte se genera en `outputs\daytrade\daytrade_report.html`.

Para preparar automáticamente el entorno virtual y ejecutar el collector
público de Bybit con duración limitada:

```powershell
.\scripts\setup_or_find_venv.ps1
.\scripts\diagnose_local_environment.ps1
.\scripts\run_bybit_microstructure_collector.ps1 -DurationMinutes 10
```

La guía completa, incluido el smoke test y el diagnóstico de red, está en
[Forward Microstructure Collector](docs/FORWARD_MICROSTRUCTURE_COLLECTOR.md).

Antes de una captura larga, aislar la estabilidad por topic:

```powershell
.\scripts\smoke_test_bybit_topics.ps1 -DurationMinutesPerPhase 1
```

Sólo continuar con una prueba de dos horas cuando
`websocket_stability_report.json` indique `ready_for_2h_test`.

## Comandos

Verificar los bloqueos:

```powershell
python -m src.cli safety
```

Ejecutar la demo reproducible con datos sintéticos:

```powershell
python -m src.cli demo --sessions 90 --timeframe 15min --seed 7
```

Probar un CSV propio:

```powershell
python -m src.cli backtest `
  --csv "data\raw\SPY_15min.csv" `
  --symbol SPY `
  --timeframe 15min `
  --asset-class equity
```

Descargar únicamente velas públicas de Binance, sin API key:

```powershell
python -m src.cli download-binance --symbol BTCUSDT --timeframe 15min --limit 1000
python -m src.cli backtest `
  --csv "data\raw\BTCUSDT_15min.csv" `
  --symbol BTCUSDT `
  --timeframe 15min `
  --asset-class crypto
```

Auditar un CSV equity/ETF de 1 minuto antes de correr rentabilidad:

```powershell
python -m src.cli audit-data `
  --csv "data\raw\QQQ_1min.csv" `
  --symbol QQQ `
  --timeframe 1min `
  --asset-class equity `
  --source-timezone America/New_York
```

El auditor genera JSON/CSV/Markdown en `outputs\data_audit\<SYMBOL>\` e indica
si el dataset es apto para Opening Range + FVG. No ejecuta backtests, no conecta
brokers, no usa credenciales y no envía órdenes. Usa calendario US equity local
versionado con feriados, early closes y DST. Detalle:
[docs/EQUITY_DATA_AUDIT.md](docs/EQUITY_DATA_AUDIT.md).

El CSV debe contener `timestamp,open,high,low,close,volume`. Los timestamps se
normalizan a UTC. También se aceptan `datetime`, `date`, `time` u `open_time`
como nombre de la columna temporal.

## Tests

```powershell
python -m unittest discover -s tests -v
```

## Qué incluye el MVP

- Ingesta CSV y descarga pública de velas Binance.
- Normalización, control OHLCV, gaps, sesiones e incompletas.
- ORB, VWAP Pullback, Relative Volume Momentum, Extreme Mean Reversion y Trend
  Day Continuation.
- Market/limit fills simulados, latencia, spread, slippage, comisión, no-fill,
  fills parciales, partial exits, trailing y regla `stop_first`.
- Sizing, límites diario/semanal, exposición, frecuencia y kill switch.
- Psychology Guard con motivos de bloqueo auditables.
- Scanner que genera candidatos, nunca órdenes.
- Backtest, OOS 70/30, walk-forward anclado y sensibilidad 0.5x/1x/2x a costos.
- Replay causal, journal CSV y reporte HTML.

El diagnóstico, los riesgos, la arquitectura y el protocolo de aprobación están
en [docs/DAYTRADE_LAB.md](docs/DAYTRADE_LAB.md).

## Sprint 2: datos reales

La validación 2022–2026 con BTCUSDT, ETHUSDT y SOLUSDT en 5m, 15m y
30m está documentada en
[docs/DAYTRADE_REAL_DATA_VALIDATION.md](docs/DAYTRADE_REAL_DATA_VALIDATION.md).

Resultado: ninguna de las cinco estrategias calificó como candidata para replay.
Paper interno continúa bloqueado.

Comandos reproducibles:

```powershell
python -m src.sprint2 audit
python -m src.sprint2 stage --workers 2
python -m src.sprint2 consolidate
```

Las descargas históricas usan archivos públicos mensuales de Binance y completan
el tramo reciente mediante `GET /api/v3/klines`, sin claves:

```powershell
python -m src.sprint2 download --start 2022-01-01
```

## YouTube / Forum Strategy Hunter

El sprint evalúa diez familias populares con reglas causales, costos reales,
OOS, walk-forward y baseline aleatorio. Se probaron 12 reglas/variantes sobre
BTC, ETH, SOL, BNB y XRP en 1m, 5m, 15m y 30m.

Resultado: ninguna calificó para replay ni paper interno. El protocolo, ranking
y conclusiones están en
[docs/YOUTUBE_FORUM_STRATEGY_HUNTER.md](docs/YOUTUBE_FORUM_STRATEGY_HUNTER.md).

```powershell
python -m src.strategy_hunter_cli audit
python -m src.strategy_hunter_cli matrix --workers 1
python -m src.strategy_hunter_cli variant-matrix --workers 1
python -m src.strategy_hunter_cli consolidate
```

## DayTrade Edge Discovery

El sprint event-driven investiga movimientos extremos, volumen, wicks,
compresión/expansión y la viabilidad de funding, OI, order book, liquidaciones y
catalizadores.

Resultado: ninguna hipótesis pasa a replay. Compression→Expansion y FVG+MSS
filtrado por RVOL alto requieren más evidencia independiente.

- [Resultado y protocolo](docs/EDGE_DISCOVERY.md)
- [Fuentes y costos de datos](docs/EDGE_DATA_SOURCES.md)

```powershell
python -m src.edge_discovery_cli sources
python -m src.edge_discovery_cli matrix --workers 1
python -m src.edge_discovery_cli consolidate
```

## Lead Validation + Forward Microstructure Collector

La validación ampliada a 20 datasets descartó Compression→Expansion canónica y
debilitó FVG+MSS+RVOL>3. Ninguna pista pasa a replay.

- [Validación de leads](docs/LEAD_VALIDATION.md)
- [Collector forward](docs/FORWARD_MICROSTRUCTURE_COLLECTOR.md)

```powershell
python -m src.lead_validation_cli matrix --workers 1
python -m src.lead_validation_cli consolidate
python -m src.microstructure_collector_cli init
```
