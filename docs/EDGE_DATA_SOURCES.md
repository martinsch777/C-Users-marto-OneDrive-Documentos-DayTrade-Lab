# Edge Discovery: fuentes de datos

Auditoría al 4 de julio de 2026. Los precios y límites cambian; deben
revalidarse antes de contratar o iniciar una colección extensa.

La matriz operativa completa está en
`outputs/edge_discovery/data_availability_matrix.csv`.

## Cripto

| Fuente | Datos | Costo inicial | Uso honesto |
|---|---|---:|---|
| Binance público | OHLCV spot/futuros | USD 0 | Backtest; ya disponible localmente |
| Binance público | AggTrades/agresor | USD 0 | Backtest, con alto costo de almacenamiento |
| Binance USD-M | Funding histórico | USD 0 | Backtest causal; conector implementado |
| Binance/archivos | Open interest | USD 0 | Backtest condicionado a validar unidades/cobertura |
| Binance REST/WS | Book, spread y trades | USD 0 | Recolección forward; no hay archivo oficial profundo de snapshots |
| Binance Futures WS | Liquidaciones | USD 0 | Recolección forward continua |
| Bybit V5 | Funding histórico | USD 0 | Backtest, requiere normalización cross-exchange |
| Bybit V5 | Open interest 5m–1d | USD 0 | Backtest; documentación indica historial hasta el lanzamiento |
| Bybit WS | Liquidaciones completas | USD 0 | Forward, push cada 500 ms |
| CoinGlass | Liquidaciones/OI/funding/order flow | desde ~USD 29/mes | Pago; granularidad intradiaria fina requiere planes mayores |

Fuentes oficiales:

- [Binance Developer Documentation](https://developers.binance.com/en/docs/introduction)
- [Binance Funding Rate History](https://developers.binance.com/legacy-docs/derivatives/usds-margined-futures/market-data/rest-api/Get-Funding-Rate-History)
- [Binance Spot WebSocket streams](https://developers.binance.com/legacy-docs/binance-spot-api-docs/web-socket-streams)
- [Bybit Funding History](https://bybit-exchange.github.io/docs/v5/market/history-fund-rate)
- [Bybit Open Interest](https://bybit-exchange.github.io/docs/v5/market/open-interest)
- [Bybit All Liquidation](https://bybit-exchange.github.io/docs/v5/websocket/public/all-liquidation)
- [CoinGlass API](https://docs.coinglass.com/reference/getting-started-with-your-api)
- [CoinGlass Liquidation History](https://docs.coinglass.com/reference/liquidation-history)
- [CoinGlass pricing](https://www.coinglass.com/pricing)

En esta ejecución, la red del proceso local estuvo bloqueada. Por eso funding y
OI no se descargaron ni se sustituyeron con proxies. Quedaron conectores públicos
GET-only y comandos reproducibles:

```powershell
python -m src.edge_discovery_cli download-funding `
  --symbol BTCUSDT --start 2022-01-01 --end 2026-07-04

python -m src.edge_discovery_cli download-open-interest `
  --symbol BTCUSDT --interval 5min
```

No aceptan API key, secreto, cuenta, leverage ni permisos de trading.

## Acciones

| Fuente | Cobertura | Costo indicado | Decisión |
|---|---|---:|---|
| Alpaca IEX | Una bolsa, ~2,5% del volumen | USD 0 | Insuficiente para RVOL/VWAP serio |
| Alpaca SIP | Todas las bolsas, desde 2016 | USD 99/mes | Apto, no configurado |
| Massive Basic | 100% mercado, 1m, 2 años | USD 0 con registro | Exploratorio; key no configurada |
| Massive Starter | 100% mercado, 5 años, extended hours | USD 29/mes | Apto para gaps; no configurado |
| Massive Developer | 10 años y trades | USD 79/mes | Apto para investigación histórica |
| Twelve Data Basic | Cuota limitada | USD 0 con key | Exploratorio |
| Twelve Data Grow/Pro | Earnings/extended hours según plan | desde USD 79/mes | Condicional |

Fuentes oficiales:

- [Alpaca Market Data API](https://docs.alpaca.markets/us/docs/about-market-data-api)
- [Alpaca IEX vs SIP](https://docs.alpaca.markets/us/v1.1/docs/historical-stock-data-1)
- [Massive pricing](https://massive.com/pricing?product=stocks)
- [Massive stock sessions](https://massive.com/docs/rest/stocks)
- [Twelve Data pricing](https://twelvedata.com/pricing)
- [Twelve Data pre/post market](https://support.twelvedata.com/en/articles/5195429-pre-post-market-data)
- [Twelve Data earnings calendar](https://twelvedata.com/docs/introduction)

No se testeó News/Catalyst ni Premarket Gap porque no existe localmente un
histórico SIP/extended-hours más calendario de catalizadores, y el sprint prohíbe
introducir claves privadas. IEX no se usó como sustituto: sesgaría el volumen
relativo.

## Collector forward

`ForwardMarketCollector` guarda:

- top-20 de book, spread e imbalance;
- trades agregados y lado agresor;
- open interest y funding corriente;
- eventos de liquidación que reciba su adaptador WebSocket;
- estado y errores de cada captura.

La colección está desactivada por defecto. El comando manual es:

```powershell
python -m src.edge_discovery_cli collect-once --symbols BTCUSDT ETHUSDT
```

El polling puntual no reemplaza la reconstrucción de un book. Para investigación
de microestructura se necesita captura continua, secuencias verificadas,
heartbeats, detección de gaps y varios meses de datos.

