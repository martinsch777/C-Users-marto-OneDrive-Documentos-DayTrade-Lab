# Equity/ETF 1-minute Alpaca Market Data download

Esta herramienta descarga barras historicas 1 minuto de QQQ/SPY desde Alpaca
Market Data API y las guarda como CSV compatibles con `audit-data`.

No usa Alpaca Trading API, no consulta account, positions u orders, no crea ni
cancela ordenes, no habilita paper/live trading y no corre backtests.

## Credenciales en PowerShell

No guardes credenciales en `config.yaml`, GitHub ni archivos del repo.

```powershell
Set-Location "C:\Users\marto\OneDrive\Documentos\DayTrade Lab"

$env:APCA_API_KEY_ID="TU_KEY_ID"
$env:APCA_API_SECRET_KEY="TU_SECRET_KEY"
```

## Dry-run sin red y sin credenciales

```powershell
python -m src.cli download-equity-intraday `
  --provider alpaca `
  --symbols QQQ SPY `
  --start 2024-01-01 `
  --end 2024-01-31 `
  --interval 1min `
  --feed sip `
  --output-dir data\raw `
  --dry-run
```

El dry-run muestra el endpoint de Market Data y los archivos que escribiria. No
llama a la red y no requiere API keys.

## Descargar QQQ/SPY

Para dataset consolidado real se recomienda `feed=sip`:

```powershell
python -m src.cli download-equity-intraday `
  --provider alpaca `
  --symbols QQQ SPY `
  --start 2024-01-01 `
  --end 2024-12-31 `
  --interval 1min `
  --feed sip `
  --adjustment raw `
  --output-dir data\raw `
  --source-timezone America/New_York `
  --rth-only `
  --audit-after-download `
  --write-manifest `
  --range-filenames
```

Salida esperada:

- `data\raw\QQQ_1min_2024-01-01_2024-12-31_alpaca_sip_raw_rth.csv`
- `data\raw\SPY_1min_2024-01-01_2024-12-31_alpaca_sip_raw_rth.csv`

Sin `--range-filenames`, se mantiene compatibilidad hacia atras:

- `data\raw\QQQ_1min.csv`
- `data\raw\SPY_1min.csv`

Para evitar sobrescribir descargas anuales por accidente, el downloader aborta
si el archivo destino existe:

```text
OUTPUT_FILE_ALREADY_EXISTS
```

Para regenerar de forma intencional:

```powershell
--overwrite
```

Columnas exactas:

```text
timestamp,open,high,low,close,volume
```

Los timestamps se guardan como apertura de vela en America/New_York, con offset,
por ejemplo:

```text
2024-07-01 09:30:00-04:00
```

## SIP vs IEX

- `feed=sip`: consolidado ideal para QQQ/SPY y auditoria final.
- `feed=iex`: sirve para pruebas de pipeline, pero no es dataset final ideal
  porque representa una sola exchange.

Si Alpaca devuelve un error de subscripcion SIP, el comando muestra:

```text
ALPACA_SIP_SUBSCRIPTION_REQUIRED
```

En ese caso podes usar `--feed iex` solo para probar el pipeline, no para validar
rentabilidad final.

## RTH-only

Para OR/FVG se recomienda `--rth-only`.

Ese filtro usa el calendario local `builtin_us_equity_calendar_v1`:

- sesion normal 09:30 inclusive a 16:00 exclusive;
- early close 09:30 inclusive a 13:00 exclusive;
- feriados y DST incluidos.

## Auditoria despues de descargar

Con `--audit-after-download`, el comando corre internamente el auditor existente
sobre cada CSV descargado:

```text
symbol=<QQQ|SPY>
timeframe=1min
asset-class=equity
source-timezone=America/New_York
```

No corre backtests bajo ninguna circunstancia.

No correr backtests hasta que:

```text
apt_for_or_fvg_backtest=true
```

Para congelar el dataset y dejarlo reproducible, usar tambien
`--write-manifest`. Ver [DATASET_MANIFESTS.md](DATASET_MANIFESTS.md).

## Seguridad

La implementacion usa exclusivamente:

```text
GET https://data.alpaca.markets/v2/stocks/{symbol}/bars
```

No hay endpoints de account, positions, orders, broker, paper ni live trading.
