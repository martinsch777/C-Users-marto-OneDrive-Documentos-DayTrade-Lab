# Forward Microstructure Collector

Collector de investigación para streams públicos Bybit USDT perpetual. No usa
cuenta, claves, broker, órdenes, posiciones ni leverage.

Documentación oficial:

- [Bybit public WebSocket](https://bybit-exchange.github.io/docs/v5/ws/connect)
- [Order book](https://bybit-exchange.github.io/docs/v5/websocket/public/orderbook)
- [Public trades](https://bybit-exchange.github.io/docs/v5/websocket/public/trade)
- [Ticker, funding y OI](https://bybit-exchange.github.io/docs/v5/websocket/public/ticker)
- [All Liquidation](https://bybit-exchange.github.io/docs/v5/websocket/public/all-liquidation)

## Datos recolectados

Por símbolo se suscribe a:

- `orderbook.50`: snapshot y deltas;
- `publicTrade`: precio, size, lado agresor y trade ID;
- `tickers`: bid/ask, mark, index, funding y open interest;
- `allLiquidation`: lado liquidado, size y bankruptcy price;
- `kline.1`: OHLCV y flag de vela confirmada.

Calcula:

- best bid/ask y spread real;
- profundidad quote en 5, 10, 25 y 50 niveles;
- imbalance por profundidad;
- latencia exchange→recepción;
- duplicados;
- gaps de secuencia;
- reconexiones y errores.

## Seguridad

- La URL está fijada al WebSocket público linear de Bybit.
- El constructor no acepta API key ni secreto.
- No existe método de orden, broker, cuenta, posición o leverage.
- El CLI exige `--confirm-public-data-only`.
- Replay, paper, live y órdenes siguen bloqueados globalmente.

## Ejecución

```powershell
pip install -r requirements.txt
python -m src.microstructure_collector_cli init
python -m src.microstructure_collector_cli run `
  --symbols BTCUSDT ETHUSDT `
  --duration-seconds 3600 `
  --confirm-public-data-only
```

Reconecta con backoff exponencial de 1 a 60 segundos. Los datos quedan en:

- `data/forward_microstructure/bybit/`
- `outputs/microstructure_collector/`
- `logs/microstructure_collector/collector.log`

## Ejecución en Windows

Abrir PowerShell en la raíz de DayTrade Lab. El preparador busca `.venv`,
`venv`, `env` y `.env`; valida `Scripts\python.exe` y
`Scripts\Activate.ps1`; y crea `.venv` cuando no encuentra uno válido. Después
instala `requirements.txt` y, si existe, `pyproject.toml`:

```powershell
.\scripts\setup_or_find_venv.ps1
```

No es necesario activar el entorno: los demás scripts usan directamente el
Python detectado. Para revisar Python, pip, arquitectura, imports, archivos y
variables de OpenBLAS:

```powershell
.\scripts\diagnose_local_environment.ps1
```

Diagnóstico público completo de Bybit:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File scripts\diagnose_bybit_connection.ps1
```

Smoke test de cinco minutos (primero exige que el diagnóstico Bybit dé PASS):

```powershell
.\scripts\smoke_test_bybit_collector.ps1
```

Collector público por diez minutos o dos horas:

```powershell
.\scripts\run_bybit_microstructure_collector.ps1 -DurationMinutes 10
.\scripts\run_bybit_microstructure_collector.ps1 -DurationMinutes 120
```

Si PowerShell bloquea scripts, habilitar sólo el proceso actual:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

Los cuatro scripts fijan automáticamente estos límites antes de iniciar Python:

```text
OPENBLAS_NUM_THREADS=1
OMP_NUM_THREADS=1
MKL_NUM_THREADS=1
NUMEXPR_NUM_THREADS=1
```

Esto evita que NumPy/pandas intenten crear demasiados threads OpenBLAS en
Windows. Si la instalación falla con `WinError 10013`, no es un problema del
entorno virtual: Windows, firewall, antivirus/EDR o la red están bloqueando
HTTPS saliente. Revisar la sección de firewall y probar una red autorizada.

## Auditoría de estabilidad WebSocket

La causa de las 105 reconexiones observadas en diez minutos no era un fallo de
handshake. La conexión se abría, llegaban datos y el parser de kline lanzaba:

```text
KeyError: 'symbol'
```

Bybit publica `kline.{interval}.{symbol}`, pero el objeto dentro de `data` no
incluye `symbol`. El parser ahora deriva el símbolo del nombre del topic. Los
errores de parseo o persistencia se registran por mensaje y ya no derriban una
conexión sana.

Los topics habilitados son públicos y válidos para linear:

- `tickers.{symbol}`: ticker, funding y open interest;
- `publicTrade.{symbol}`: trades públicos;
- `orderbook.50.{symbol}`: snapshot y deltas de 50 niveles;
- `allLiquidation.{symbol}`: liquidaciones;
- `kline.1.{symbol}`: vela de un minuto.

Se pueden desactivar grupos sin modificar código en
`config.yaml`, sección `microstructure_collector.enabled_topics`, o por CLI:

```powershell
.\scripts\run_bybit_microstructure_collector.ps1 `
  -DurationMinutes 10 `
  -Topics ticker,trades,orderbook
```

Funding y open interest llegan por ticker. El diagnóstico REST también consulta
los endpoints públicos correspondientes, pero sus conteos nunca se mezclan con
mensajes WebSocket.

### Smoke incremental por topic

Ejecuta siete fases de un minuto: ticker, trades, order book, liquidaciones,
ticker+trades, ticker+trades+order book y todos los topics:

```powershell
.\scripts\smoke_test_bybit_topics.ps1 -DurationMinutesPerPhase 1
```

Para dos minutos por fase:

```powershell
.\scripts\smoke_test_bybit_topics.ps1 -DurationMinutesPerPhase 2
```

El resultado se guarda en
`outputs/microstructure_collector/topic_stability_report.json`.

### Métricas separadas

`collector_status.csv` distingue:

- `rest_requests_ok` y `rest_requests_failed`;
- `websocket_connected`;
- `websocket_subscription_acknowledged`;
- `websocket_messages_received` y `websocket_messages_persisted`;
- `websocket_errors` y `websocket_reconnects`;
- `fallback_rest_messages_received`;
- `total_messages_received`;
- `files_written`;
- `messages_by_topic` y `persisted_by_topic`.

El collector envía heartbeat de aplicación cada 20 segundos, mantiene la
conexión ante un timeout corto de recepción y usa backoff `1, 2, 5, 10...`
segundos hasta el máximo configurable. Un timeout de recepción aislado no
provoca reconexión.

### Códigos WebSocket

| Código | Significado |
|---|---|
| `WEBSOCKET_CONNECT_FAILED` | No pudo abrirse la conexión WebSocket. |
| `WEBSOCKET_HANDSHAKE_FAILED` | Falló el upgrade HTTP/WebSocket. |
| `WEBSOCKET_SUBSCRIPTION_REJECTED` | Bybit rechazó uno o más topics. |
| `WEBSOCKET_SUBSCRIPTION_TIMEOUT` | No llegó ACK ni datos dentro del plazo. |
| `WEBSOCKET_CONNECTED_NO_ACK` | Llegaron datos pero no el ACK esperado. |
| `WEBSOCKET_CONNECTED_NO_DATA` | Llegó ACK, pero aún no hubo datos. No fuerza reconexión. |
| `WEBSOCKET_RECV_TIMEOUT` | Un intervalo de recepción quedó vacío. No fuerza reconexión. |
| `WEBSOCKET_CLOSED_BY_REMOTE` | El peer cerró una conexión ya establecida. |
| `WEBSOCKET_PARSE_ERROR` | Un payload no pudo interpretarse. Se aísla ese mensaje. |
| `WEBSOCKET_PERSISTENCE_ERROR` | Un evento no pudo guardarse. |
| `REST_FALLBACK_OK` | Un GET público REST respondió correctamente. |
| `REST_FALLBACK_FAILED` | Falló un GET público REST. |

### Estados del smoke y gate de dos horas

- `PASS_WEBSOCKET_STABLE`: WebSocket y persistencia estables.
- `PASS_REST_ONLY_FALLBACK`: REST funciona, pero no habilita recolección larga.
- `FAIL_WEBSOCKET_UNSTABLE`: hubo datos WebSocket, con ACK/errores/reconexiones
  fuera del límite.
- `FAIL_NO_MARKET_DATA`: no llegó información por WebSocket ni REST.

Para quedar `ready_for_2h_test`, una corrida de diez minutos debe cumplir:

```text
websocket_messages_received > 0
websocket_messages_persisted > 0
websocket_subscription_acknowledged = true
websocket_reconnects <= 2
websocket_errors <= 2
orders_sent = false
broker_connected = false
live_trading_enabled = false
```

El reporte queda en
`outputs/microstructure_collector/websocket_stability_report.json` e incluye
tasas horarias estimadas, timestamps del primer/último mensaje y una
recomendación. No iniciar una captura de 90 días hasta obtener
`PASS_WEBSOCKET_STABLE` en diez minutos y luego completar una prueba de dos
horas con los mismos límites de seguridad.

## Estado actual

La prueba de conectividad fue bloqueada por Windows con `WinError 10013`.
El collector registró reconexión/error, recibió cero mensajes y terminó como
`blocked_no_market_data_received`. Esto valida el manejo del fallo, no la captura.

Para recolectar de verdad debe habilitarse salida WebSocket HTTPS/WSS hacia
`stream.bybit.com:443` en el entorno.

## Calidad mínima antes de investigar

- Spread filter: mínimo 30 días completos.
- Imbalance/absorción: mínimo 60 días.
- Liquidation cascade: mínimo 90 días y al menos 100 eventos extremos.
- Recomendado: 180 días para incluir más de un régimen de volatilidad.

Los cinco setups forward están congelados en
`data/forward_microstructure/hypothesis_registry.yaml`. No deben backtestearse ni
pasar a replay hasta alcanzar cobertura, continuidad y muestra suficientes.

## Reportes

- `collector_status.csv`
- `data_quality.csv`
- `spread_summary.csv`
- `orderbook_imbalance_summary.csv`
- `liquidation_events.csv`
- `funding_oi_snapshots.csv`

Los CSV se inicializan incluso sin conexión para que el estado “sin datos” sea
explícito y no se confunda con cero eventos.

## Diagnóstico de conexión

Ejecutar primero el script integral de Windows:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File scripts\diagnose_bybit_connection.ps1
```

Prueba DNS, HTTPS, TCP 443, TLS, WebSocket, suscripción pública, escritura,
variables relevantes y versiones de Python/librerías. Los valores de variables
que podrían contener credenciales nunca se imprimen: sólo figura
`<set:length=N>` o `<unset>`.

El equivalente Python es:

```powershell
python -m src.diagnose_bybit_connection
```

Para aislar REST de WebSocket:

```powershell
python -m src.diagnose_bybit_connection --rest-only
```

Los reportes quedan en:

- `outputs/microstructure_collector/bybit_connection_diagnostic.json`
- `outputs/microstructure_collector/bybit_connection_diagnostic_powershell.json`

### Resultado observado

En este entorno:

- DNS de `api.bybit.com`: PASS.
- DNS de `stream.bybit.com`: PASS.
- Escritura local: PASS.
- TCP 443 a ambos hosts: `TCP_443_BLOCKED`, `WinError 10013`.
- HTTPS: `HTTPS_BLOCKED`.
- TLS: `TLS_HANDSHAKE_FAILED` porque TCP no llega a abrirse.
- REST y WebSocket: bloqueados antes del handshake.

La causa está en permisos/política de socket saliente del entorno, no en una
respuesta de rechazo de Bybit.

## Códigos de diagnóstico

| Código | Significado |
|---|---|
| `DNS_FAILED` | El hostname no pudo resolverse. |
| `TCP_443_BLOCKED` | No se pudo abrir un socket a puerto 443. Revisar firewall, política o red. |
| `TLS_HANDSHAKE_FAILED` | TCP abrió, pero falló negociación TLS/certificado. |
| `HTTPS_BLOCKED` | Falló un GET público HTTPS o Bybit devolvió error. |
| `WEBSOCKET_HANDSHAKE_FAILED` | HTTPS/TLS pudo avanzar, pero no se completó upgrade WebSocket. |
| `SUBSCRIPTION_REJECTED` | Bybit abrió WebSocket pero rechazó el topic. |
| `SUBSCRIPTION_OK_NO_DATA` | Suscripción aceptada, sin mensajes antes del timeout. |
| `DATA_RECEIVED_BUT_NOT_PERSISTED` | Llegó un evento válido pero no quedó almacenado. |
| `FILE_WRITE_FAILED` | No se pudo crear o anexar un archivo local. |
| `UNKNOWN_NETWORK_ERROR` | Error no clasificable; revisar tipo y mensaje sanitizado. |

`collector_status.csv` incluye `last_error_code`, conteos por código y si la
suscripción fue reconocida.

## REST fallback

El fallback usa exclusivamente GET públicos:

- `/v5/market/time`;
- `/v5/market/tickers`;
- `/v5/market/open-interest`;
- `/v5/market/funding/history`;
- `/v5/market/recent-trade`.

Sirve para distinguir “Bybit responde por HTTPS” de “WebSocket bloqueado”. No
reemplaza order book/deltas y no usa endpoints `/order`, `/position`, cuenta o
wallet.

Documentación oficial:

- [Server time](https://bybit-exchange.github.io/docs/v5/market/time)
- [Recent public trades](https://bybit-exchange.github.io/docs/v5/market/recent-trade)
- [Public WebSocket](https://bybit-exchange.github.io/docs/v5/ws/connect)

## Probar otra red

Sin modificar código:

1. Ejecutar el diagnóstico en la red actual y conservar ambos JSON.
2. Desconectar VPN/proxy corporativo sólo si la política local lo permite.
3. Probar una red doméstica o hotspot móvil autorizado.
4. Repetir exactamente el mismo comando.
5. Comparar primero DNS y TCP 443. Si TCP pasa pero WebSocket no, revisar
   inspección TLS/proxy que bloquee `Upgrade: websocket`.

No usar herramientas para eludir políticas organizacionales.

## Revisar Firewall de Windows

No desactivar el firewall globalmente. Revisar:

```powershell
Get-NetFirewallProfile |
  Select-Object Name, Enabled, DefaultOutboundAction

Test-NetConnection api.bybit.com -Port 443
Test-NetConnection stream.bybit.com -Port 443

Get-NetFirewallApplicationFilter |
  Where-Object Program -Match "python|powershell"
```

También revisar Windows Security → Firewall & network protection → Advanced
settings → Outbound Rules y el antivirus/EDR instalado. Si la política lo
permite, autorizar salida TCP 443 para el ejecutable de Python mostrado en el
JSON, limitada a los hosts públicos de Bybit. En equipos administrados debe
hacerlo el responsable de sistemas.

## Confirmar ausencia de claves y trading

Los JSON incluyen:

```text
api_keys_used=false
broker_connected=false
orders_sent=false
live_trading_enabled=false
paper_internal_enabled=false
paper_broker_enabled=false
real_leverage_used=false
```

El diagnóstico sólo permite `https://api.bybit.com/v5/market/*` y
`wss://stream.bybit.com/v5/public/linear`. No construye headers
`X-BAPI-API-KEY`, no firma requests y no contiene endpoints de órdenes.
