# Dataset manifests

Los manifests congelan/versionan datasets descargados para que cualquier
backtest posterior sea reproducible y comparable.

Un CSV intradiario puede cambiar por redescarga, ajustes, proveedor, feed,
filtro RTH, calendario o correcciones manuales. Si el CSV cambia, su `sha256`
cambia y los resultados de backtest dejan de ser comparables con ejecuciones
anteriores.

## Generar manifest al descargar

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
  --write-manifest
```

Por defecto se escriben en:

```text
data\manifests\
```

Ejemplos:

```text
data\manifests\QQQ_1min_2024-01-01_2024-12-31_alpaca_sip_raw_rth_manifest.json
data\manifests\SPY_1min_2024-01-01_2024-12-31_alpaca_sip_raw_rth_manifest.json
```

## Estados

- `approved_for_or_fvg_backtest`: auditoria apta y sin critical warnings.
- `failed_audit`: el CSV existe pero no paso la auditoria.
- `not_audited`: no hay auditoria asociada.

No correr backtests sobre CSV sin manifest con:

```text
dataset_status=approved_for_or_fvg_backtest
```

## Verificar hash

El manifest guarda `sha256` del CSV. Para verificar en PowerShell:

```powershell
Get-FileHash data\raw\QQQ_1min.csv -Algorithm SHA256
```

El hash debe coincidir con el campo `sha256` del manifest. Si no coincide, el
dataset cambio y cualquier backtest previo deja de ser comparable.

## Campos principales

El manifest incluye:

- simbolo, asset class y timeframe;
- provider, feed y adjustment;
- source timezone y `rth_only`;
- rango de fechas;
- filas y primer/ultimo timestamp;
- archivo de entrada y `sha256`;
- metadata del calendario local;
- resultado de `audit-data`;
- `created_at`;
- safety state:
  - `live_trading=false`
  - `broker_connected=false`
  - `orders_sent=false`

## Seguridad

El manifest es un artefacto local de auditoria. No ejecuta backtests, no conecta
brokers, no usa Trading API, no habilita paper/live trading y no envia ordenes.

