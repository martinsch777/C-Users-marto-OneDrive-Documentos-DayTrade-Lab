# HYP-FCR-EVENT-01 Preregistration

## Status

Hypothesis: `HYP-FCR-EVENT-01`

Name: Opening Range Sweep and Post-Event Path Study

Type: `event_study`

Research status: `non_strategy`, `hypothesis_generating`, `preregistered_not_run`

Eligibility: `not_eligible_for_paper_or_live`

Canonical payload hash: `1b6ad06b974d996cdf6bd0a3a21eae097e94322e80fdec94c2cfc4ec3c18fe81`

This document preregisters the event-study tool only. The event study was not
executed, no results were produced, and no period was opened.

## Motivation

FCR-REFINEMENT-FAMILY-01 closed as `discovery_failed`. HYP-FCR-04 losing less
than other variants is not evidence of a tradable edge and does not create a
candidate. The next allowed research action is a non-strategy descriptive event
study that asks what happens after Opening Range touches, sweeps, and FVG
events without creating entries, exits, stops, targets, quantities, or PnL.

## Data And Periods

Allowed preparation period:

- `discovery_2022_2024`: local curated QQQ/SPY only, approved manifests required.

Blocked periods:

- `validation_2025`: blocked, not opened.
- `parity_debug_2026`: blocked, not opened.
- `holdout`: blocked, not opened.

No downloads, Alpaca calls, broker/API calls, paper trading, live trading,
validation, holdout, optimization, or parameter sweeps are allowed.

## Event Definitions

Events are measured after the 09:30-10:00 Opening Range on 5-minute bars.

| Event | Definition |
| --- | --- |
| EVENT-01 | First touch of Opening Range low after 10:00. |
| EVENT-02 | First strict break of Opening Range low by at least one tick. |
| EVENT-03 | First touch of Opening Range high after 10:00. |
| EVENT-04 | First strict break of Opening Range high by at least one tick. |
| EVENT-05 | Latest low sweep followed by bullish FVG and close back inside range within three bars. |
| EVENT-06 | Latest high sweep followed by bearish FVG and close back inside range within three bars. |
| EVENT-07 | Low sweep without bullish FVG confirmation in the next three bars. |
| EVENT-08 | High sweep without bearish FVG confirmation in the next three bars. |
| EVENT-09 | Bullish FVG inside the Opening Range without prior low sweep. |
| EVENT-10 | Bearish FVG inside the Opening Range without prior high sweep. |

Only one event per event type per symbol-session may be recorded. EVENT-05 and
EVENT-06 use the latest valid sweep preceding the confirming FVG.

## Path Measurements

Horizons:

- `5min`
- `15min`
- `30min`
- `60min`
- `session_close`

Metrics:

- Raw close-to-close return from the event bar close.
- Reversal-oriented return.
- Continuation-oriented return.
- MFE and MAE through the horizon.
- Time to MFE and MAE.
- Returned to Opening Range center.
- Reached opposite Opening Range extreme.
- Broke same-side Opening Range extreme.

Normalization fields:

- Opening Range width.
- ATR 14 on 5-minute bars.
- Sweep depth in ticks and ATR units.
- FVG size in ticks and ATR units.
- Gap direction when prior session close is available.
- Symbol, year, day of week, and event hour.

## Aggregation

The approved aggregation is by event type, horizon, symbol, year, and direction
orientation, with bootstrap confidence intervals sampled by session. Bootstrap
sampling must be deterministic for a fixed seed.

## Methodological Locks

- This is not a strategy.
- No orders, entries, exits, stops, targets, sizing, PnL, portfolio simulation,
  or execution model may be added inside this preregistration.
- Results, if a future approved run is opened, are hypothesis-generating only.
- Any conversion to strategy requires a separate preregistration before seeing
  independent new data.
- 2025 and 2026 remain blocked for this tool.

## Implementation Scope

Implemented files:

- `configs/research/hypotheses/HYP-FCR-EVENT-01.yaml`
- `src/research/hyp_first_candle_event_study.py`
- `src/research/hyp_first_candle_event_runner.py`
- `tests/test_hyp_first_candle_event_study.py`

The runner is locked to `prepare_only`. It can emit a preparation manifest but
cannot run the event study.

