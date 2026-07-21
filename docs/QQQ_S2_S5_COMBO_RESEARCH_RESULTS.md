# QQQ S2/S5 Combo Research Results

## Auditoria de reutilizacion

| Componente necesario | Codigo existente reutilizable | Archivo | Cambio requerido |
|---|---|---|---|
| Dataset auditado y gate | require_or_fvg_backtest_dataset_manifest | src/data/dataset_manifest.py | Reutilizado sin cambios |
| Carga OHLCV canonica | load_csv / validate_ohlcv | src/data/loader.py | Reutilizado sin cambios |
| Calendario US RTH | EquitySessionCalendar | src/data/sessions.py | Reutilizado sin cambios |
| ATR, EMA, VWAP, RVOL | atr, ema, session_vwap, relative_volume | src/indicators/core.py | Agregar DMI/ADX/ROC en modulo de investigacion |
| 60m HTF confirmado | Calendario y parser de timestamps | src/research/qqq_s2_s5.py | Implementado merge_asof con confirmed_at <= cierre 5m |
| Ejecucion process_orders_on_close | calculate_metrics | src/research/qqq_s2_s5.py | Simulador especifico; motor general entra en barra siguiente |
| Reportes estructurados | calculate_metrics y patrones de runners research | src/research/runners/hyp_gap_runner.py | Nuevo runner que escribe CSV/JSON/Markdown |

## Incompatibilidades TradingView vs Python

- TradingView `process_orders_on_close=true` puede llenar al cierre de la vela de senal; el motor general del proyecto llena en la apertura de la siguiente barra, por eso esta corrida usa un simulador especifico de investigacion.
- Los stops intrabar no conocen el orden high/low real dentro de una vela de 5 minutos; se usa politica conservadora de stop primero.
- Los indicadores HTF se mapean solo cuando la vela de 60m esta confirmada (`confirmed_at <= close_time_5m`), evitando la vela HTF abierta.
- El sizing usa fracciones para respetar exactamente 10% del equity por operacion; un broker real podria requerir redondeo a acciones enteras.

## Archivos creados/modificados

- configs/research/hypotheses/QQQ-S2-S5-COMBO.yaml
- src/research/qqq_s2_s5.py
- src/research/runners/qqq_s2_s5_runner.py
- tests/test_qqq_s2_s5.py
- docs/QQQ_S2_S5_COMBO_RESEARCH_RESULTS.md

## Comandos reproducibles

- `.\.venv\Scripts\python.exe -m unittest discover -s tests`
- `.\.venv\Scripts\python.exe -m unittest tests.test_qqq_s2_s5`
- `.\.venv\Scripts\python.exe -m src.research.runners.qqq_s2_s5_runner --dataset data\curated\QQQ_1min_2022-01-01_2026-07-06_curated.csv --manifest-dir data\manifests --preregistration configs\research\hypotheses\QQQ-S2-S5-COMBO.yaml --output-dir outputs\QQQ_S2_S5_COMBO`

## Resultados

| period | variant | trade_count | net_pnl | total_return | profit_factor | win_rate | expectancy | max_drawdown | average_minutes_in_trade | total_cost | estimated_slippage | largest_positive_trade_share |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| discovery | S2 | 147 | -103.031 | -0.0103031 | 0.602423 | 0.312925 | -0.700888 | 0.0128653 | 39.8299 | 74.6509 | 16.1216 | 0.122306 |
| discovery | S2_S5 | 305 | -136.645 | -0.0136645 | 0.712256 | 0.327869 | -0.448018 | 0.0147973 | 47.6557 | 155.287 | 33.9341 | 0.0564446 |
| discovery | S5 | 169 | -66.7214 | -0.00667214 | 0.73042 | 0.313609 | -0.394801 | 0.00713048 | 53.3136 | 86.4726 | 19.0292 | 0.0787374 |

## Clasificacion

- S2: descartada. Razones: Discovery profit factor neto <= 1.15; Discovery neto no positivo
- S2_S5: descartada. Razones: Discovery profit factor neto <= 1.15; Discovery neto no positivo
- S5: descartada. Razones: Discovery profit factor neto <= 1.15; Discovery neto no positivo

## Bloqueos y simultaneas

| period | variant | block_reason | count |
| --- | --- | --- | --- |
| discovery | S2 | BLOCKED_COOLDOWN | 2 |
| discovery | S2 | BLOCKED_MODULE_DAILY_LIMIT | 31 |
| discovery | S2 | BLOCKED_POSITION_OPEN | 6 |
| discovery | S2_S5 | BLOCKED_COOLDOWN | 3 |
| discovery | S2_S5 | BLOCKED_MAX_TRADES_PER_DAY | 9 |
| discovery | S2_S5 | BLOCKED_MODULE_DAILY_LIMIT | 50 |
| discovery | S2_S5 | BLOCKED_POSITION_OPEN | 24 |
| discovery | S5 | BLOCKED_COOLDOWN | 2 |
| discovery | S5 | BLOCKED_MODULE_DAILY_LIMIT | 34 |

## Senales simultaneas

| period | variant | module | signal_status | count |
| --- | --- | --- | --- | --- |
| discovery | S2_S5 | S2 | blocked | 6 |
| discovery | S2_S5 | S5 | executed | 6 |

## Motivos de salida

| period | variant | exit_reason | count |
| --- | --- | --- | --- |
| discovery | S2 | FORCED_SESSION_CLOSE | 3 |
| discovery | S2 | MAX_BARS | 2 |
| discovery | S2 | MOMENTUM_EXIT | 26 |
| discovery | S2 | STOP_LOSS | 38 |
| discovery | S2 | TRAILING_STOP | 78 |
| discovery | S2_S5 | FORCED_SESSION_CLOSE | 25 |
| discovery | S2_S5 | MAX_BARS | 3 |
| discovery | S2_S5 | MOMENTUM_EXIT | 25 |
| discovery | S2_S5 | STOP_LOSS | 85 |
| discovery | S2_S5 | STRUCTURAL_INVALIDATION | 35 |
| discovery | S2_S5 | TRAILING_STOP | 132 |
| discovery | S5 | FORCED_SESSION_CLOSE | 20 |
| discovery | S5 | MAX_BARS | 1 |
| discovery | S5 | STOP_LOSS | 53 |
| discovery | S5 | STRUCTURAL_INVALIDATION | 37 |
| discovery | S5 | TRAILING_STOP | 58 |

## Sensibilidad a costos

| period | variant | trade_count | net_pnl | profit_factor | win_rate | max_drawdown | total_cost | estimated_slippage |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| discovery_stress_costs | S2 | 147 | -176.342 | 0.432836 | 0.244898 | 0.0192563 | 148.76 | 32.1354 |
| discovery_stress_costs | S5 | 169 | -152.382 | 0.501924 | 0.295858 | 0.0155449 | 172.202 | 37.9067 |
| discovery_stress_costs | S2_S5 | 305 | -288.89 | 0.499043 | 0.288525 | 0.0291915 | 308.196 | 67.3879 |

## Estado validation y holdout

- Validation abierta: False.
- Holdout abierto: False.
- No se optimizaron parametros ni se uso validation/holdout para elegir parametros.

## Outputs estructurados

- Directorio: `outputs\QQQ_S2_S5_COMBO`
- trades.csv, blocked_signals.csv, metrics.csv, metrics_by_module.csv, metrics_by_year.csv, metrics_by_month.csv, metrics_by_side.csv
- cost_sensitivity.csv, run_manifest.json, config.json

## Verificacion

- baseline_unittest: 242 tests OK before implementation
- pytest: not available in project venv: No module named pytest
- git_diff_check: OK
- full_suite_after: 252 tests OK
- git_status_short: five new research files tracked as untracked; generated outputs directory is ignored by git

## Flags de seguridad

- live_trading=false
- broker_connected=false
- orders_sent=false
- paper_broker_enabled=false
