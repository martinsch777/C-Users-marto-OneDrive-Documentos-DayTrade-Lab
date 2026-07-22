# First Candle TradingView Parity Spec

This document defines the operation-level parity contract for `HYP-FCR-01`.

Parity is a debugging tool only. It cannot approve economic performance, open validation, or use 2026 as a clean holdout.

## Source

- Pine source: `docs/research/source_pine/FIRST_CANDLE_RULE_TV_V1.pine`
- Pine SHA-256: `91604D14B6DAA95758AF3D97617F3F2278E771A5A30ADC61F24E10D83B166D22`
- Python parity module: `src/research/hyp_first_candle.py`
- Compare tool: `compare_tradingview_export(...)`
- Runner wrapper: `python -m src.research.hyp_first_candle_runner`

## Required Python Audit Columns

Each Python parity row must include:

- `symbol`
- `session_date`
- `direction`
- `opening_high`
- `opening_low`
- `last_sweep_time`
- `signal_time`
- `signal_close`
- `fvg_size`
- `stop`
- `target`
- `intended_quantity`
- `actual_quantity`
- `entry_time`
- `entry_price`
- `exit_time`
- `exit_price`
- `exit_reason`
- `gross_pnl`
- `commission`
- `slippage_cost`
- `net_pnl`
- `intended_R`
- `realized_R`

## Frozen Parity Semantics

`tradingview_parity` intentionally follows source-like behavior:

- Decision happens at the close of the 5-minute signal bar.
- Entry reference is `signal_close`.
- Slippage is adverse.
- Stop and target are calculated from `signal_close`.
- Position size uses integer shares and pre-trade equity.
- Pine fixed close logic is the 15:55-16:00 `exitSession`.
- Early close behavior is preserved, not corrected.

The Pine source uses `process_orders_on_close=true`, `commission_value=0.01`, `slippage=1`, and `pyramiding=0`.

## Research Primary Contrast

`research_primary` differs by design:

- Signal is known only after the 5-minute bar closes.
- Entry is the next available audited 1-minute open.
- Stop and target remain frozen from `signal_close`.
- TP/SL resolution uses audited 1-minute bars.
- If TP and SL are touched in the same minute, stop is assumed first.
- If the next open crosses the stop, fill at the worse of stop/open plus adverse slippage.
- If the next open crosses the target favorably, fill at target without price improvement.
- Exit is the actual `US_EQUITY_RTH` close, including early closes.
- Overnight positions are prohibited.

Only `research_primary` can later support economic conclusions.

## Early-Close Bug Audit

The source Pine has fixed `exitSession = "1555-1600"`. On an early close, such as a 13:00 close, no 15:55-16:00 bar exists. Therefore:

- `tradingview_parity` may leave the position unresolved under source semantics if neither stop nor target triggers before the early close.
- `research_primary` must close at the last executable bar before the effective session close.
- `research_primary` must never carry a position into the next session.

This difference is a preregistered methodological correction, not an optimization.

## Comparison Tool Contract

The Python comparison utility accepts:

```text
compare_tradingview_export(tradingview_csv, parity_csv, output_csv=None)
```

CLI command to use later, once both CSVs exist:

```powershell
.\.venv\Scripts\python.exe -m src.research.hyp_first_candle_runner --compare-tradingview-csv <TRADINGVIEW_EXPORT_CSV> --compare-parity-csv <PYTHON_PARITY_CSV> --parity-output-csv <OUTPUT_COMPARISON_CSV>
```

No TradingView CSV was provided during preregistration or this pre-discovery audit, so parity was not run.

Required key columns:

- `symbol`
- `session_date`
- `direction`

Numeric comparison fields:

- `entry_price`
- `exit_price`
- `stop`
- `target`
- `net_pnl`
- `realized_R`

Default tolerances:

- Price fields: 0.01
- PnL/R fields: 0.01

The output contains merge status, absolute differences, maximum difference, failed fields, `parity_bucket`, and `difference_type`.

Required buckets:

- `matched_trades`
- `missing_in_python`
- `missing_in_tradingview`
- `field_mismatches`
- `unexplained_mismatches`

Difference classifications:

- `DATA_FEED_DIFFERENCE`
- `SESSION_ALIGNMENT_DIFFERENCE`
- `SIGNAL_LOGIC_DIFFERENCE`
- `POSITION_SIZING_DIFFERENCE`
- `INTRABAR_EXECUTION_DIFFERENCE`
- `UNEXPLAINED_DIFFERENCE`

## Prohibitions

- Do not use parity mismatches to tune parameters.
- Do not use 2026 parity debugging to approve profitability.
- Do not silently correct Pine behavior in `tradingview_parity`.
- Do not modify the Pine source.
- Do not send orders or connect brokers.

Safety state remains:

- live_trading=false
- broker_connected=false
- orders_sent=false
- paper_broker_enabled=false
