# HYP-OR-CONT-EVENT-01 Preregistration

## Status

Hypothesis: `HYP-OR-CONT-EVENT-01`

Name: Opening Range Sweep Without Opposing FVG: Post-Confirmation Continuation

Initial state: `preregistered_not_executed`

Type: `event_study`

Strategy status: `non_strategy`

Canonical payload hash:
`d76572e7534e8cf66104ceb2d30dd08a7c0b080fc4460e496b58a08d3736060b`

This preregistration creates only the configuration, documentation, and
synthetic structural tests for a future causal event study. It does not execute
real data, produce results, create a strategy, generate orders, or backtest PnL.

## Background

`HYP-FCR-EVENT-01` is treated as closed and versioned at commit `dc15fd8` with
classification `event_study_completed_stable_not_economic`. It found stable but
non-economic descriptive effects in:

- `EVENT-07 / long_reversal`: 5min, 15min, and 30min.
- `EVENT-08 / short_reversal`: 15min, 30min, and 60min.

Because EVENT-07 and EVENT-08 require three future bars to know whether the
opposing FVG did not appear, the sweep timestamp itself is not causal for an
executable study. This new preregistration moves the measurement origin to the
first executable instant after confirmation.

## Frozen Definitions

The study reuses the frozen definitions from `HYP-FCR-EVENT-01` for:

- Opening Range construction: 09:30-10:00 America/New_York on 5-minute bars.
- Low sweep used by EVENT-07.
- High sweep used by EVENT-08.
- Bullish FVG.
- Bearish FVG.
- Tick size and equality policy.
- Timestamp/session handling.

No reinterpretation or rule modification is allowed.

## Causal Timestamp

For a low sweep:

1. A bar after 10:00 touches or breaks the Opening Range low.
2. The next three complete 5-minute bars are observed.
3. None of those three bars may generate the opposing bullish FVG.
4. The event is confirmed at the close of the third confirmation bar.
5. `executable_timestamp` is the opening timestamp of the next 5-minute bar.
6. Orientation is `continuation_short`.

For a high sweep:

1. A bar after 10:00 touches or breaks the Opening Range high.
2. The next three complete 5-minute bars are observed.
3. None of those three bars may generate the opposing bearish FVG.
4. The event is confirmed at the close of the third confirmation bar.
5. `executable_timestamp` is the opening timestamp of the next 5-minute bar.
6. Orientation is `continuation_long`.

The event does not exist before the third confirmation bar has closed. Prices
after `executable_timestamp` are prohibited for event selection and may only be
used later for path measurement in an approved run.

Required event fields:

- `sweep_timestamp`
- `confirmation_timestamp`
- `executable_timestamp`
- `swept_side`
- `confirmation_bar_count`
- `reason_for_exclusion`

## Deduplication

Only the first confirmed signal per symbol-session is allowed, independent of
side. A session may contain at most one primary event. Later qualifying sweeps
are ignored for the primary event set.

## Horizons

Primary horizon:

- `30min` from `executable_timestamp`

Secondary descriptive horizons:

- `15min`
- `60min`
- `session_close`

The 5-minute horizon is not a primary approval criterion. Overnight crossing is
not allowed; unavailable same-session horizons must be reported as unavailable,
not carried into the next session.

## Control

An unconditional matched control is preregistered but not executed. It must be
matched by:

- symbol
- year
- executable timestamp hour bucket
- horizon

Metrics:

- `event_return`
- `unconditional_return`
- `incremental_return`

## Costs

The canonical source is `configs/research/hypotheses/HYP-FCR-01.yaml`.

| Profile | Commission Per Side | Slippage Per Execution | Round Trip Commission | Round Trip Slippage | Round Trip Formula |
| --- | ---: | ---: | ---: | ---: | --- |
| baseline | 0.0001 | 1 tick | 0.0002 | 2 ticks = USD 0.02/share | `0.0002 + 0.02 / executable_price` |
| stress | 0.0002 | 2 ticks | 0.0004 | 4 ticks = USD 0.04/share | `0.0004 + 0.04 / executable_price` |

## Discovery Gate

The primary 30-minute horizon advances only if all criteria pass:

1. `continuation_short` and `continuation_long` have the expected positive sign.
2. QQQ and SPY show the same sign.
3. The effect appears in at least two of three discovery years.
4. Incremental return versus the matched unconditional control is positive.
5. Mean return exceeds the baseline round-trip cost.
6. The effect is not dominated by a single year.
7. Session-clustered bootstrap CI does not strongly contradict the effect.
8. No lookahead exists.
9. No 2025 or 2026 contamination exists.

Secondary horizons cannot override a failed primary horizon.

## Locked Periods And Safety

Discovery is preregistered for 2022-01-01 through 2024-12-31 but not executed
now. Validation 2025 is blocked. Historical 2026 remains contaminated and
non-decisional. Any shadow-forward period may begin only after the commit that
freezes this hypothesis.

Safety flags remain false:

- `live_trading=false`
- `broker_connected=false`
- `orders_sent=false`
- `paper_broker_enabled=false`
