# Equity/ETF 1-minute data audit

Esta herramienta audita CSV intradiarios de equities/ETF antes de permitir un
backtest de Opening Range + FVG. No ejecuta backtests, no conecta brokers, no usa
credenciales y no envia ordenes.

## Comando

```powershell
python -m src.cli audit-data `
  --csv "data\raw\QQQ_1min.csv" `
  --symbol QQQ `
  --timeframe 1min `
  --asset-class equity `
  --source-timezone America/New_York
```

`--source-timezone` solo es necesario cuando los timestamps del CSV son naive
(sin offset ni timezone). Si los timestamps ya son timezone-aware, el auditor los
normaliza a UTC.

Por defecto escribe reportes en:

```text
outputs/data_audit/<SYMBOL>/
```

Archivos generados:

- `<SYMBOL>_1min_data_audit.json`: reporte completo.
- `<SYMBOL>_1min_data_audit.csv`: resumen plano.
- `<SYMBOL>_1min_data_audit_sessions.csv`: detalle por sesion.
- `<SYMBOL>_1min_data_audit.md`: resumen legible.

## Validaciones

El auditor exige columnas minimas:

```text
timestamp, open, high, low, close, volume
```

Y valida:

- timestamps timezone-aware, o `source_timezone` explicito si son naive;
- orden cronologico;
- timestamps duplicados;
- barras faltantes dentro de RTH;
- feriados y early closes del calendario US equity;
- barras fuera de 09:30-16:00 America/New_York;
- presencia de premarket/after-hours;
- gaps anormales dentro de la misma sesion RTH;
- OHLC invalido;
- precios cero o negativos;
- volumen cero o negativo;
- sesiones con pocas barras;
- sesiones con cantidad de barras distinta a la esperada.

Convencion de barras: `timestamp` representa la apertura de la vela.

- Sesion normal: 09:30 inclusive a 16:00 exclusive = 390 barras.
- Early close 13:00: 09:30 inclusive a 13:00 exclusive = 210 barras.

## Veredicto

`apt_for_or_fvg_backtest=true` solo aparece cuando el dataset:

- es QQQ o SPY;
- es `1min`;
- tiene timestamps no ambiguos;
- no tiene duplicados;
- esta ordenado cronologicamente;
- no tiene missing bars RTH;
- no contiene premarket/after-hours;
- no contiene barras de feriados/sesiones cerradas;
- no tiene OHLC/precio/volumen invalido;
- no tiene sesiones incompletas;
- usa calendario real cargado y dentro del rango soportado.

## Ejemplo de reporte esperado

```json
{
  "symbol": "QQQ",
  "timeframe": "1min",
  "rows_total": 390,
  "sessions": 1,
  "sessions_complete": 1,
  "sessions_incomplete": 0,
  "expected_bars": 390,
  "observed_rth_bars": 390,
  "missing_bars": 0,
  "duplicate_timestamps": 0,
  "outside_rth_bars": 0,
  "critical_warnings": [],
  "calendar_name": "US_EQUITY_RTH",
  "calendar_source": "builtin_us_equity_calendar_v1",
  "calendar_loaded": true,
  "calendar_supported_start": "1990-01-01",
  "calendar_supported_end": "2035-12-31",
  "apt_for_or_fvg_backtest": true,
  "broker_connected": false,
  "orders_sent": false,
  "live_trading_enabled": false,
  "api_keys_used": false
}
```

## Calendario

El auditor usa `data.calendar.source=us_equity` de `config.yaml` via
`EquitySessionCalendar`. Ese modo carga un calendario local versionado:

```text
builtin_us_equity_calendar_v1
```

Cobertura:

- sesiones normales 09:30-16:00 America/New_York;
- feriados regulares NYSE/Nasdaq;
- New Year observado;
- Independence Day observado;
- Thanksgiving;
- Christmas observado;
- Good Friday;
- Juneteenth desde 2022;
- cierres extraordinarios versionados dentro de la tabla local, incluido
  2025-01-09 por National Day of Mourning for Jimmy Carter;
- early closes estandar a las 13:00 para Black Friday, Christmas Eve y la rueda
  previa al feriado de Independence Day;
- cambios DST via `zoneinfo` y timestamps timezone-aware;
- rango soportado 1990-01-01 a 2035-12-31.

Limitacion: futuros cambios regulatorios, nuevos feriados o cierres
extraordinarios posteriores a la version actual requieren actualizar el
calendario local y sumar tests explicitos. Esta decision mantiene el proyecto
offline-first y evita depender de servicios externos durante auditorias.

## Diagnostico del calendario

Para inspeccionar las sesiones esperadas de un rango:

```powershell
python -m src.cli calendar-diagnostics `
  --calendar us_equity `
  --start 2024-07-01 `
  --end 2024-07-05
```

Columnas devueltas:

- `date`
- `is_session`
- `open`
- `close`
- `is_early_close`
- `expected_1min_bars`
- `reason`

Tambien puede emitirse JSON:

```powershell
python -m src.cli calendar-diagnostics `
  --calendar us_equity `
  --start 2024-07-01 `
  --end 2024-07-05 `
  --format json
```

Con este calendario cargado, el auditor ya no debe emitir:

```text
CALENDAR_HAS_NO_HOLIDAYS_OR_EARLY_CLOSES_LOADED
```

Si alguien fuerza `data.calendar.source=manual` sin proveer feriados/early
closes, el auditor marca:

```text
REAL_MARKET_CALENDAR_NOT_LOADED
```

Si el dataset cae fuera del rango versionado, marca:

```text
CALENDAR_DATE_OUT_OF_SUPPORTED_RANGE
```

No se conecta a ningun proveedor externo para resolver calendario.

## Seguridad

Esta herramienta es de lectura/escritura local:

- no instancia estrategias;
- no ejecuta backtests de rentabilidad;
- no conecta brokers;
- no usa API keys;
- no manda ordenes;
- no habilita paper ni live trading.
