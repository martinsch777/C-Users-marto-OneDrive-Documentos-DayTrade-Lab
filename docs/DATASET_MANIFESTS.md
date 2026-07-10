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
  --write-manifest `
  --range-filenames
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
- `total_excluded_sessions`;
- detalle de `excluded_sessions`, si existen;
- `created_at`;
- safety state:
  - `live_trading=false`
  - `broker_connected=false`
  - `orders_sent=false`

## Seguridad

El manifest es un artefacto local de auditoria. No ejecuta backtests, no conecta
brokers, no usa Trading API, no habilita paper/live trading y no envia ordenes.

## Manifests de datasets curados

Cuando existe una exclusion de calidad de proveedor, generar un dataset curado
separado del raw:

```powershell
python -m src.cli build-equity-dataset `
  --csv "data\raw\SPY_1min.csv" `
  --symbol SPY `
  --timeframe 1min `
  --asset-class equity `
  --source-timezone America/New_York `
  --start 2023-01-01 `
  --end 2023-12-31 `
  --provider alpaca `
  --feed sip `
  --adjustment raw `
  --rth-only `
  --excluded-sessions "data\quality_overrides\excluded_sessions.json" `
  --output-dir "data\curated" `
  --manifest-dir "data\manifests" `
  --range-filenames
```

El manifest consolidado conserva el hash del CSV curado y registra la exclusion:

```json
{
  "symbol": "SPY",
  "timeframe": "1min",
  "raw_input_file": "data\\raw\\SPY_1min_2022-01-01_2026-07-06_alpaca_sip_raw_rth.csv",
  "curated_file": "data\\curated\\SPY_1min_2022-01-01_2026-07-06_curated.csv",
  "input_file": "data\\curated\\SPY_1min_2022-01-01_2026-07-06_curated.csv",
  "output_file": "data\\curated\\SPY_1min_2022-01-01_2026-07-06_curated.csv",
  "rows_input": 439000,
  "rows_output": 438614,
  "rows_removed": 386,
  "provider": "alpaca",
  "feed": "sip",
  "adjustment": "raw",
  "dataset_status": "approved_for_or_fvg_backtest",
  "total_excluded_sessions": 1,
  "excluded_sessions": [
    {
      "symbol": "SPY",
      "date": "2023-06-05",
      "reason": "MISSING_RTH_BARS_FROM_PROVIDER",
      "source": "alpaca_sip_raw_rth",
      "policy": "exclude_entire_session",
      "expected_bars": 390,
      "bars_removed": 386
    }
  ],
  "project_safety_state": {
    "live_trading": false,
    "broker_connected": false,
    "orders_sent": false
  }
}
```

Los manifests curados usan nombres claros:

```text
data\manifests\QQQ_1min_2022-01-01_2026-07-06_curated_manifest.json
data\manifests\SPY_1min_2022-01-01_2026-07-06_curated_manifest.json
```

Los manifests raw descargados conservan la convencion anterior, por ejemplo:

```text
data\manifests\SPY_1min_2022-01-01_2026-07-06_alpaca_sip_raw_rth_manifest.json
```

`require_approved_dataset_manifest(csv_path, symbol, timeframe)` acepta ambos
formatos, pero para permitir backtests exige:

- `input_file` apuntando al CSV que se va a usar;
- `sha256` igual al hash actual del CSV;
- `symbol` y `timeframe` coincidentes;
- `dataset_status=approved_for_or_fvg_backtest`;
- `audit_apt_for_or_fvg_backtest=true`;
- `audit_critical_warnings=[]`.

No correr backtests sobre CSV raw con sesiones incompletas ni sobre CSV curados
sin manifest `approved_for_or_fvg_backtest`.
