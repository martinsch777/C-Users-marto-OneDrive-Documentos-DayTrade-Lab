# Forward collector

This directory is reserved for public market-data collection only.

Expected files:

- `orderbook_snapshots.csv`
- `recent_trades.csv`
- `funding_open_interest.csv`
- `liquidation_events.csv`
- `collector_status_history.csv`

The collector has no broker, account, position, leverage or order methods. API
keys and secrets are not accepted. Collection is disabled by default in
`config.yaml`.
