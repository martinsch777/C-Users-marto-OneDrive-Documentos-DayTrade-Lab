# HYP-FCR-01 - QQQ TradingView Parity 2026

## Scope

This report documents the non-decisional parity comparison between real TradingView Pine logs and the local Python implementation for HYP-FCR-01.

- Hypothesis: HYP-FCR-01
- Symbol: QQQ
- Period label: parity_debug_2026
- Execution mode: tradingview_parity
- Range: 2026-04-13 through 2026-07-06 inclusive
- Dataset: data/curated/QQQ_1min_2022-01-01_2026-07-06_curated.csv
- Dataset sha256: 2e9fd658e31c698f79bb5bcfcc7077a25e2c7b245d5b5d5f1fc3a158e7931fe4
- Decisional periods executed: none
- Discovery executed: false
- Validation executed: false
- Holdout executed: false

No profitability conclusion is made in this report.

## Pine Log Validation

Input:

- data/parity/tradingview/QQQ_FIRST_CANDLE_2026_PINE_LOGS.txt

Generated structured CSV:

- data/parity/tradingview/QQQ_FIRST_CANDLE_2026_TRADES.csv

Validation results:

| Check | Result |
| --- | ---: |
| Trade count | 40 |
| Minimum trade_num | 0 |
| Maximum trade_num | 39 |
| Duplicate trade_num values | 0 |
| Missing trade_num values | 0 |
| First entry date | 2026-04-13 |
| Last entry date | 2026-07-06 |
| Normalized symbol | QQQ |
| Trades with qty = 1 | 40 |
| TradingView profit sum | 13.17 |
| Session-close exits | 3 |

The parser uses the Unix millisecond timestamps supplied inside the TVTRADE payload. It does not use the visual timestamp between square brackets as the operation date.

## Parser Controls

The Pine log parser:

- Ignores text before `TVTRADE|`.
- Parses `key=value` fields.
- Removes thousands separators from `entry_time` and `exit_time`.
- Converts Unix millisecond timestamps to UTC and America/New_York.
- Preserves `source_symbol` and normalizes `BATS:QQQ` to `QQQ`.
- Converts price, quantity, profit, and commission fields to numeric values.
- Detects duplicate trade numbers.
- Verifies consecutive trades from 0 through 39.
- Sorts by `entry_time` and `trade_num`.

## Artifacts

Structured parity artifacts were written under:

- artifacts/parity/HYP-FCR-01/QQQ_2026/

Files:

- pine_log_validation.json
- python_tradingview_parity_trades.csv
- python_tradingview_parity_signals.csv
- python_tradingview_parity_diagnostics.csv
- run_manifest.json
- tradingview_vs_python_comparison.csv
- matched_trades.csv
- missing_in_python.csv
- missing_in_tradingview.csv
- field_mismatches.csv
- unexplained_mismatches.csv
- comparison_summary.json

## Tolerances

| Field family | Tolerance |
| --- | ---: |
| Price | 0.01 |
| Profit | 0.01 |
| Commission | 0.001 |
| Quantity | 0.0 |
| Time | 0 seconds |

Small numeric differences are normalized only through these explicit tolerances. Signal, session, and missing-trade differences are not hidden by tolerance.

## Parity Summary

| Metric | Count |
| --- | ---: |
| matched_trades | 6 |
| missing_in_python | 0 |
| missing_in_tradingview | 0 |
| field_mismatches | 34 |
| unexplained_mismatches | 0 |
| date and direction matches | 28 |
| entry price exact matches | 5 |
| entry price matches within tolerance | 13 |
| exit price exact matches | 4 |
| exit price matches within tolerance | 12 |

Matched trade numbers:

- 0, 1, 2, 5, 15, 22

## Difference Classification

| Difference type | Count |
| --- | ---: |
| DATA_FEED_DIFFERENCE | 14 |
| SESSION_ALIGNMENT_DIFFERENCE | 12 |
| SIGNAL_LOGIC_DIFFERENCE | 6 |
| POSITION_SIZING_DIFFERENCE | 0 |
| INTRABAR_EXECUTION_DIFFERENCE | 0 |
| COST_CALCULATION_DIFFERENCE | 2 |
| UNEXPLAINED_DIFFERENCE | 0 |

No missing Python trades, missing TradingView trades, or unexplained differences were found.

## Concrete Examples

| Trade | Session | Classification | Observed difference |
| ---: | --- | --- | --- |
| 3 | 2026-04-21 | DATA_FEED_DIFFERENCE | Same direction and timestamps. TV exit price 645.61 vs Python 645.7603; profit differs by 0.15058. |
| 8 | 2026-04-29 | SESSION_ALIGNMENT_DIFFERENCE | Same entry timestamp. TV exit 16:30 UTC vs Python exit 18:35 UTC; exit price and profit diverge after the exit-time mismatch. |
| 13 | 2026-05-12 | COST_CALCULATION_DIFFERENCE | Entry and exit prices are within tolerance, timestamps match, but profit differs by 0.010405. |
| 18 | 2026-05-21 | SESSION_ALIGNMENT_DIFFERENCE | Entry and exit timestamps differ, producing materially different entry/exit prices and profit. |
| 23 | 2026-06-02 | SESSION_ALIGNMENT_DIFFERENCE | Same entry timestamp and price. TV exit 14:50 UTC vs Python exit 14:55 UTC. |

## Gate Pre-Discovery

Status: BLOCKED.

Discovery remains blocked because there are unresolved blocking differences:

- SIGNAL_LOGIC_DIFFERENCE rows: 6
- SESSION_ALIGNMENT_DIFFERENCE rows: 12
- missing_in_python rows: 0
- missing_in_tradingview rows: 0
- UNEXPLAINED_DIFFERENCE rows: 0

Differences classified as feed, intrabar execution, or cost calculation are documented but were not corrected by changing strategy rules. No parameters, YAML hypothesis file, or canonical Pine code were modified.

## Technical Conclusion

The 2026 TradingView log file is structurally valid and was converted into a reproducible CSV. The Python tradingview_parity run produced the same number of trades as TradingView, with no missing trades on either side and no unexplained mismatches. However, strict parity is not achieved because unresolved signal-logic and session-alignment differences remain. Therefore the pre-discovery gate must stay blocked.

Safety confirmation: this run used only local data, did not call Alpaca, did not download market data, did not send orders, and did not execute discovery, validation, holdout, or any decisional period.

---

## Run 002 Corrected Audit

This section preserves the initial result above as `run_001_initial` and documents the corrected technical parity audit saved as `run_002_corrected`.

Baseline preserved:

- artifacts/parity/HYP-FCR-01/QQQ_2026/run_001_initial/
- Hash manifest: artifacts/parity/HYP-FCR-01/QQQ_2026/run_001_initial/baseline_hashes.json

Corrected run:

- artifacts/parity/HYP-FCR-01/QQQ_2026/run_002_corrected/
- Hash manifest: artifacts/parity/HYP-FCR-01/QQQ_2026/run_002_corrected/run_002_hashes.json

Canonical controls:

- `configs/research/hypotheses/HYP-FCR-01.yaml` was not modified.
- `docs/research/source_pine/FIRST_CANDLE_RULE_TV_V1.pine` was not modified.
- Canonical YAML payload SHA-256 remains `bac53f3ff97176b9be5bd5b52a9d6589747587a313b34f24644e1d99bb4cd2ab`.
- Full Pine file SHA-256 remains `91604D14B6DAA95758AF3D97617F3F2278E771A5A30ADC61F24E10D83B166D22`.

## Matching Audit

The initial comparator matched TradingView `trade_num = N` to Python `trade_num = N`. That was not safe as a sole equivalence key. Python had counted a rejected signal candidate as a trade-like row with `quantity_below_minimum` and empty entry/exit fields. Because that row sorted last, the sequence comparison after 2026-06-11 created a cascade of false mismatches.

The corrected comparator writes both views:

- `sequence_comparison.csv`: explicit old-style sequence audit.
- `event_matching.csv`: deterministic one-to-one event matching.

Event matching keys:

- normalized symbol.
- session date in America/New_York.
- direction.
- configurable entry-time proximity, default 240 minutes.
- entry-price distance as secondary score.
- no Python trade can be assigned to more than one TradingView trade.

Run 002 event matching classifications:

| Classification | Count |
| --- | ---: |
| exact_event_match | 38 |
| probable_event_match | 1 |
| shifted_event | 1 |
| unmatched_tradingview | 0 |
| unmatched_python | 0 |
| sequence_misalignment | 0 |

## Corrections Applied

Only one implementation bug was corrected:

- Python previously marked the session as already traded when a raw logical signal appeared, even if position sizing later rejected it with `quantity_below_minimum`.
- Pine only sets `tradedToday := true` after a valid order is submitted.
- Python now records the rejected signal as a diagnostic and continues scanning the session for the next valid order.

No preregistered rule, parameter, time window, OR definition, sweep definition, FVG definition, stop, target, risk, quantity rule, commission, slippage, universe, period, YAML file, or Pine source was changed.

## Run 001 vs Run 002

| Metric | run_001_initial | run_002_corrected |
| --- | ---: | ---: |
| TradingView trades | 40 | 40 |
| Python trades | 40 | 40 |
| matched_trades | 6 | 9 |
| missing_in_python | 0 | 0 |
| missing_in_tradingview | 0 | 0 |
| field_mismatches | 34 | 31 |
| unexplained_mismatches | 0 | 0 |
| date + direction matches | 28 | 40 |
| entry exact matches | 5 | 8 |
| entry within tolerance | 13 | 20 |
| exit exact matches | 4 | 6 |
| exit within tolerance | 12 | 18 |

Difference type comparison:

| Difference type | run_001_initial | run_002_corrected |
| --- | ---: | ---: |
| DATA_FEED_DIFFERENCE | 14 | 18 |
| SESSION_ALIGNMENT_DIFFERENCE | 12 | 8 |
| SIGNAL_LOGIC_DIFFERENCE | 6 | 0 |
| COST_CALCULATION_DIFFERENCE | 2 | 5 |
| POSITION_SIZING_DIFFERENCE | 0 | 0 |
| INTRABAR_EXECUTION_DIFFERENCE | 0 | 0 |
| UNEXPLAINED_DIFFERENCE | 0 | 0 |

## Root Cause Summary

Initial 12 `SESSION_ALIGNMENT_DIFFERENCE` rows:

- 5 were artifacts of the unsafe sequence matching cascade after the rejected 2026-06-11 signal candidate.
- 5 were same-event exit timing differences consistent with intrabar/feed boundary behavior.
- 2 were same-session signal timing boundaries where the local SIP-derived 5-minute sequence and TradingView/BATS event timing selected nearby but non-identical bars.

Initial 6 `SIGNAL_LOGIC_DIFFERENCE` rows:

- All 6 were prior-classification errors caused by sequence misalignment, not confirmed FVG rule bugs.
- Signal traces were written to `signal_logic_diagnostics.csv`.

Cost differences:

- TradingView reported profit is inferred to be net of commission.
- Commission is percent-per-side on entry plus exit notional.
- Five run_002 rows exceed the explicit profit tolerance while price differences are exact or within the explicit price tolerance.
- The cost reconciliation is written to `cost_reconciliation.csv`; most are minor decimal/rounding boundaries, while trade 37 also reflects accumulated penny-level price difference plus commission precision.

Remaining differences in run_002:

- 18 `DATA_FEED_DIFFERENCE` rows remain documented.
- 8 unresolved `SESSION_ALIGNMENT_DIFFERENCE` rows remain.
- 5 `COST_CALCULATION_DIFFERENCE` rows remain documented.
- No missing trades and no unexplained differences remain.

## Final Gate

Status: BLOCKED.

The final pre-discovery gate cannot pass because unresolved `SESSION_ALIGNMENT_DIFFERENCE` rows remain. The required gate condition of 40/40 date + direction matches is satisfied, and there are no missing or unexplained rows, but unresolved session alignment is still a blocker.

No 2026 result in this document is economic evidence. It remains parity_debug_2026 and non_decisional only.

Additional artifacts:

- artifacts/parity/HYP-FCR-01/QQQ_2026/run_002_corrected/event_matching.csv
- artifacts/parity/HYP-FCR-01/QQQ_2026/run_002_corrected/sequence_comparison.csv
- artifacts/parity/HYP-FCR-01/QQQ_2026/run_002_corrected/session_alignment_diagnostics.csv
- artifacts/parity/HYP-FCR-01/QQQ_2026/run_002_corrected/signal_logic_diagnostics.csv
- artifacts/parity/HYP-FCR-01/QQQ_2026/run_002_corrected/cost_reconciliation.csv

---

## Run 003 Final Audit

Run 003 performs a final technical classification of the remaining run_002 differences. It does not rerun discovery, validation, holdout, or any decisional period.

Artifacts:

- artifacts/parity/HYP-FCR-01/QQQ_2026/run_003_final_audit/timing_reclassification.csv
- artifacts/parity/HYP-FCR-01/QQQ_2026/run_003_final_audit/signal_boundary_fixtures.csv
- artifacts/parity/HYP-FCR-01/QQQ_2026/run_003_final_audit/signal_boundary_fixture_results.csv
- artifacts/parity/HYP-FCR-01/QQQ_2026/run_003_final_audit/signal_boundary_ohlc_diagnostics.csv
- artifacts/parity/HYP-FCR-01/QQQ_2026/run_003_final_audit/cost_reconciliation_final.csv
- artifacts/parity/HYP-FCR-01/QQQ_2026/run_003_final_audit/final_gate_summary.json
- artifacts/parity/HYP-FCR-01/QQQ_2026/run_003_final_audit/input_hashes.json
- artifacts/parity/HYP-FCR-01/QQQ_2026/run_003_final_audit/run_003_hashes.json

Inputs were hashed in `input_hashes.json`. Runs `run_001_initial` and `run_002_corrected` were not overwritten.

## Timing Reclassification

The eight run_002 rows previously labeled `SESSION_ALIGNMENT_DIFFERENCE` were reclassified as follows:

| Trade | Session | Direction | Entry delta min | Exit delta min | Final classification | Blocks discovery |
| ---: | --- | --- | ---: | ---: | --- | --- |
| 8 | 2026-04-29 | short | 0 | -125 | EXIT_INTRABAR_TIMING | false |
| 16 | 2026-05-19 | long | 0 | 5 | EXIT_INTRABAR_TIMING | false |
| 17 | 2026-05-20 | long | 0 | 15 | EXIT_INTRABAR_TIMING | false |
| 18 | 2026-05-21 | long | -30 | -35 | DATA_FEED_SIGNAL_BOUNDARY | false |
| 23 | 2026-06-02 | short | 0 | -5 | EXIT_INTRABAR_TIMING | false |
| 27 | 2026-06-10 | short | 0 | 30 | EXIT_INTRABAR_TIMING | false |
| 28 | 2026-06-11 | short | 10 | -25 | DATA_FEED_SIGNAL_BOUNDARY | false |
| 38 | 2026-07-01 | short | 0 | -5 | EXIT_INTRABAR_TIMING | false |

No row remains classified as a true `SIGNAL_SESSION_ALIGNMENT` bug. The 6 exit-only timing rows have the same entry event and differ because stop/target is reached on another bar under the local SIP OHLC path. That is intrabar/feed timing, not session alignment.

## Shifted Signals

The two real signal-time shifts are trades 18 and 28.

| Trade | TV signal NY | Python signal NY | Result |
| ---: | --- | --- | --- |
| 18 | 2026-05-21 11:15 | 2026-05-21 11:45 | DATA_FEED_SIGNAL_BOUNDARY |
| 28 | 2026-06-11 11:00 | 2026-06-11 10:50 | DATA_FEED_SIGNAL_BOUNDARY |

For both cases, synthetic fixtures built from the exact local OHLC prefix reproduce the Python signal timestamp. The OHLC diagnostics include bars `t`, `t-1`, and `t-2`, opening high/low, sweep state, FVG booleans, back-inside booleans, delay booleans, and stop candidates. The fixture results show no five-minute timestamp labeling displacement and no timezone/DST displacement. The remaining explanation is a strict OHLC boundary difference between TradingView/BATS and local Alpaca SIP, not a frozen-rule bug.

## Final Cost Reconciliation

TradingView `strategy.closedtrades.profit` is inferred to be net of reported commission:

`expected_tv_net_profit = gross_price_pnl - tradingview_reported_commission`

All five cost rows match this relationship within floating-point noise.

| Trade | Direction | TV net residual | Python vs TV net residual | Within 0.021 |
| ---: | --- | ---: | ---: | --- |
| 13 | long | ~0.000000 | -0.010405 | true |
| 26 | long | ~0.000000 | -0.010002 | true |
| 29 | short | ~0.000000 | -0.010358 | true |
| 34 | long | ~0.000000 | -0.014867 | true |
| 37 | short | ~0.000000 | -0.020352 | true |

The final parity cost tolerance is `0.021`, documented as a parity-reporting tolerance only. It is derived from observed price reporting precision of one cent on each side plus commission precision, not from a change to strategy logic. It does not modify the preregistration.

Trade 37 is the largest cost residual. TV gross is `-2.58`, TV commission is `0.146`, expected TV net is `-2.726`, and reported TV profit is `-2.726`. Python net is `-2.746352`, leaving `-0.020352`, within the documented precision boundary.

## Final Gate Result

Final technical gate status: PASS.

Gate inputs:

| Check | Result |
| --- | ---: |
| TradingView trades | 40 |
| Python trades | 40 |
| Session date + direction | 40/40 |
| missing_in_python | 0 |
| missing_in_tradingview | 0 |
| unresolved SIGNAL_LOGIC_DIFFERENCE | 0 |
| unresolved true SIGNAL_SESSION_ALIGNMENT bugs | 0 |
| UNEXPLAINED_DIFFERENCE | 0 |
| POSITION_SIZING_DIFFERENCE | 0 |
| unresolved costs | 0 |

Remaining non-blocking categories:

| Category | Count |
| --- | ---: |
| DATA_FEED_DIFFERENCE | 18 |
| DATA_FEED_SIGNAL_BOUNDARY | 2 |
| EXIT_INTRABAR_TIMING | 6 |
| COST_ROUNDING_DIFFERENCE | 5 |

This is a technical parity gate result only. Year 2026 remains `parity_debug_2026` and `non_decisional`; it is not economic evidence and was not used for profitability conclusions, parameter selection, strategy approval, discovery, validation, or holdout.

Canonical controls remain unchanged:

- Canonical YAML payload SHA-256: `bac53f3ff97176b9be5bd5b52a9d6589747587a313b34f24644e1d99bb4cd2ab`
- Pine source file unchanged.
- HYP-FCR-01.yaml unchanged.
