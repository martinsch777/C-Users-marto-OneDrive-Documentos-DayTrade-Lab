# HYP-GAP Event Study Preregistration

Date: 2026-07-13

Status: `PREREGISTERED`

This document preregisters the first hypothesis family from the intraday hypothesis refinement protocol:

```text
HYP-GAP -- Gap continuation versus gap reversal
```

This is an event-study specification only. It does not define entries, exits, stops, sizing, slippage, profit targets, or execution rules. No event studies, backtests, validation runs, holdout runs, replay, paper broker, or live trading are authorized by this document.

The base OR/FVG research remains discarded and must not be retroactively optimized.

Safety state is fixed:

| Field | Required Value |
| --- | --- |
| `live_trading` | `false` |
| `broker_connected` | `false` |
| `orders_sent` | `false` |
| `paper_broker_enabled` | `false` |

## Frozen Splits

Only the discovery period is documented for this task.

| Split | Dates | Status |
| --- | --- | --- |
| Discovery | 2022-01-01 to 2024-12-31 | Open only after detector implementation is separately approved |
| Validation | 2025-01-01 to 2025-12-31 | Closed |
| Final holdout | 2026-01-01 to 2026-07-06 | Closed |

Validation and final holdout must not be inspected or used to choose thresholds, variants, filters, symbols, or parameters.

## Source Of Truth

DayTrade Lab, the curated CSVs, their approved manifests, and reproducible local event-study outputs are the source of truth.

TradingView may be used only for visual inspection, checking whether detected events appear in the intended chart locations, and catching timestamp interpretation mistakes. TradingView must not be used to change thresholds after seeing results or to approve the hypothesis.

## Event Timing

All timestamps are interpreted in `America/New_York` regular trading hours.

The common confirmation timestamp is:

```text
09:45 America/New_York
```

The event-study base price is the close of the 09:45 confirmation bar. Variables measured from 09:30 through 09:45 may use only information available at or before the close of the confirmation bar. No variable may use data after the confirmation timestamp.

## Required Price Definitions

`previous_session_close` is the last valid close of the previous approved RTH session.

`current_session_open` is the open of the 09:30 America/New_York bar for the current approved RTH session.

```text
gap_return = current_session_open / previous_session_close - 1
```

```text
gap_direction = 1  when gap_return > 0
gap_direction = -1 when gap_return < 0
```

Sessions with `gap_return == 0` are ineligible for this family because continuation and reversal direction would be undefined.

## Approved Session Handling

A session excluded by an approved manifest must not be used as the previous session and must not be used as the event session.

The first available session in the dataset is ineligible because it has no prior approved RTH session inside the dataset.

If the previous approved session is absent, incomplete, or excluded, the current session is ineligible.

If the current session lacks the 09:30 open bar, the 09:45 confirmation close, or any required 09:30-09:45 input, the current session is ineligible.

Bars outside RTH are ignored and must not be used to compute event variables.

Missing bars are not filled. A missing required bar makes the event unavailable rather than estimated.

Calendar-approved early closes may be eligible only if the session has all required 09:30-09:45 inputs and the later `session_close` event-study horizon is validated against the expected calendar close before running on real data.

## Gap Normalization

The normalized gap uses only prior approved RTH sessions.

Daily true range for a session is:

```text
true_range = max(
  session_high - session_low,
  abs(session_high - previous_approved_session_close),
  abs(session_low - previous_approved_session_close)
)
```

`previous_20_session_ATR` is the arithmetic mean of daily true range over the 20 approved RTH sessions before the event session. The current session is never included.

At least 20 prior approved RTH sessions are required. Warm-up sessions before that threshold are ineligible.

```text
normalized_gap = abs(current_session_open - previous_session_close) / previous_20_session_ATR
```

## Additional Variables

All variables below are computed causally.

`open_to_confirmation_return`:

```text
confirmation_close / current_session_open - 1
```

`confirmation_vwap` is the cumulative VWAP from 09:30 through the close of the 09:45 confirmation bar.

`relative_volume_0930_0945` is the current session's 09:30-09:45 volume divided by the median 09:30-09:45 volume over the prior 20 approved RTH sessions. A minimum of 20 prior approved sessions is required.

`opening_move_atr`:

```text
abs(confirmation_close - current_session_open) / previous_20_session_ATR
```

## Conceptual Families

Gap continuation expects the post-confirmation return to align with `gap_direction`.

Gap reversal expects the post-confirmation return to align with `-gap_direction`.

The observed behavior through 09:45 must confirm the event type before the event can be recorded. A continuation event requires price behavior that has not rejected the gap by the confirmation timestamp. A reversal event requires observable rejection or adverse movement against the gap by the confirmation timestamp.

## Frozen Variant Budget

Exactly six variants are preregistered:

| Variant | Family | Expected Direction |
| --- | --- | --- |
| HYP-GAP-01 | continuation | `gap_direction` |
| HYP-GAP-02 | continuation | `gap_direction` |
| HYP-GAP-03 | continuation | `gap_direction` |
| HYP-GAP-04 | reversal | `-gap_direction` |
| HYP-GAP-05 | reversal | `-gap_direction` |
| HYP-GAP-06 | reversal | `-gap_direction` |

No additional HYP-GAP variants are allowed during this discovery stage.

## Preregistered Variants

### HYP-GAP-01: Large Gap Holds Previous Close

Rationale: a large overnight repricing that remains accepted through the first 15 minutes may reflect unresolved inventory imbalance or news absorption.

Event conditions:

- `normalized_gap >= 0.50`;
- `gap_direction != 0`;
- the 09:45 confirmation close remains on the gap side of `previous_session_close`.

For an up gap, confirmation close must be greater than `previous_session_close`. For a down gap, confirmation close must be less than `previous_session_close`.

Expected direction: `gap_direction`.

### HYP-GAP-02: Gap Continuation With VWAP Acceptance

Rationale: price accepted on the gap side of both prior close and early VWAP may indicate that early participation agrees with the overnight move.

Event conditions:

- `normalized_gap >= 0.35`;
- the 09:45 confirmation close remains on the gap side of `previous_session_close`;
- the 09:45 confirmation close is on the gap side of `confirmation_vwap`.

Expected direction: `gap_direction`.

### HYP-GAP-03: Gap Continuation With Opening Follow-Through

Rationale: a gap followed by additional movement in the same direction before 09:45 may signal an opening drive rather than a liquidity fade.

Event conditions:

- `normalized_gap >= 0.35`;
- `open_to_confirmation_return` has the same sign as `gap_direction`;
- `opening_move_atr >= 0.10`.

Expected direction: `gap_direction`.

### HYP-GAP-04: Large Gap Rejected Through Previous Close

Rationale: a large overnight move that is rejected back through the previous close by 09:45 may indicate liquidity provision against an overextended open.

Event conditions:

- `normalized_gap >= 0.50`;
- `gap_direction != 0`;
- the 09:45 confirmation close is on the opposite side of `previous_session_close` from the gap.

For an up gap, confirmation close must be less than `previous_session_close`. For a down gap, confirmation close must be greater than `previous_session_close`.

Expected direction: `-gap_direction`.

### HYP-GAP-05: Gap Reversal With VWAP Rejection

Rationale: failure to hold early VWAP after a gap may show that the initial repricing is not accepted by regular-session participants.

Event conditions:

- `normalized_gap >= 0.35`;
- `open_to_confirmation_return` has the opposite sign from `gap_direction`;
- the 09:45 confirmation close is on the opposite side of `confirmation_vwap` from the gap.

Expected direction: `-gap_direction`.

### HYP-GAP-06: Gap Reversal With Weak Participation

Rationale: a gap that immediately moves against its direction on below-normal early participation may represent a weak open vulnerable to reversal.

Event conditions:

- `normalized_gap >= 0.35`;
- `open_to_confirmation_return` has the opposite sign from `gap_direction`;
- `relative_volume_0930_0945 <= 0.90`.

Expected direction: `-gap_direction`.

## Horizons

Every variant uses the same event-study horizons:

- 5 minutes;
- 15 minutes;
- 30 minutes;
- 60 minutes;
- session close.

The existing event-study infrastructure currently uses the last close available in the session DataFrame for `session_close`. Before HYP-GAP is executed on real data, a separate validation must confirm that this bar matches the expected calendar close for each session, including calendar-approved early closes. The event-study engine is not modified by this specification.

## Symbols

Each variant must be evaluated without modification on:

- QQQ;
- SPY.

No QQQ-specific or SPY-specific thresholds are allowed in discovery.

## Availability Criteria

An event is available only when all of the following are true:

- the symbol is QQQ or SPY;
- the event session is inside discovery;
- the event session is approved by its manifest;
- the previous RTH session is approved by its manifest;
- at least 20 prior approved RTH sessions exist for ATR and relative volume warm-up;
- the 09:30 open, 09:45 close, 09:30-09:45 VWAP inputs, and 09:30-09:45 volume inputs are present;
- timestamps are inside RTH and aligned to the curated 1-minute data;
- no session excluded by manifest is used as event session or previous session.

## Exclusion Criteria

Exclude the candidate session if:

- `gap_return == 0`;
- required prior-session data is missing;
- required warm-up data is missing;
- the event session is incomplete before the confirmation timestamp;
- the session or prior session is excluded by manifest;
- any required bar is missing;
- timestamps are outside RTH;
- any event variable would require data after 09:45.

## Minimum Metrics

The discovery report for each variant must include:

- number of events;
- mean return;
- median return;
- positive rate;
- standard deviation;
- standard error;
- confidence intervals;
- results by year;
- results by symbol;
- results by horizon;
- stability between QQQ and SPY.

Profit factor is not required at this stage because no trade simulation is defined.

## Preregistered Discard Criteria

Discard a variant in discovery if any of the following occurs:

- sample size is insufficient, defined as fewer than 100 total available events across QQQ and SPY;
- more than 50% of available events are concentrated in a single calendar year;
- QQQ and SPY show opposite directional evidence without a preregistered rationale;
- the mean is positive only because of a small number of outliers;
- median return or positive rate contradicts the hypothesis direction;
- the sign is opposite the expected direction;
- yearly results show no reasonable stability;
- evidence appears only in one isolated horizon and not in adjacent horizons;
- conclusions depend excessively on one variant;
- results are economically insignificant before costs;
- any evidence of leakage, lookahead, timestamp misalignment, or discretionary filtering appears.

## Criteria To Advance To Validation

At most one continuation variant and one reversal variant may advance to validation.

A variant can be considered for validation only if discovery shows:

- sufficient sample size;
- sign coherent with the preregistered hypothesis;
- reasonable year-by-year stability;
- behavior not dependent on a single symbol;
- mean and median returns pointing in the same practical direction;
- confidence intervals reported for the selected return horizon;
- no evidence of leakage, lookahead, timestamp misalignment, or discretionary exclusion;
- reproducible outputs from DayTrade Lab.

Passing discovery does not authorize a strategy, replay, paper broker, or live trading. It only permits a separately approved validation task.

## Machine-Readable Registry

The structured registry for this preregistration is:

```text
configs/research/hypotheses/HYP-GAP.yaml
```

The registry is intended for later detector implementation. It records the frozen variants, thresholds, variables, safety flags, split dates, horizons, availability rules, discard rules, and advancement rules.
