# HYP-DRIVE-PB-01 Canonical Preregistration

## 1. Executive Summary

`HYP-DRIVE-PB-01`, Opening Drive + Controlled Pullback Continuation, is a
preregistered causal event study on QQQ and SPY. Its status is
`preregistered_not_executed`. There is no evidence of profitability, discovery
has not run, validation is locked, and no strategy, paper, live, sizing, or
order capability exists.

## 2. Causal Question

After a directionally large 09:30-09:45 RTH displacement and a bounded
first-bar pullback, does the first causal prior-bar-break confirmation have a
positive direction-oriented 30-minute return, incrementally versus an
unconditional time-matched control and after frozen costs?

## 3. Independence And Source

This event uses no gap, opening-range sweep, FVG, EVENT-07, EVENT-08, or prior
favorable direction. The sole methodological source is the human-approved
`docs/HYP_DRIVE_PB_01_DESIGN_DECISIONS.md`.

The conceptual design freeze commit is:

`925cede00f3d9c1b4de46e225f98d4636c19a831`

The approved implementation clarification freeze commit is:

`764478b86a01619620166848204e527f2fb55c55`

The clarification is `HYP-DRIVE-PB-01-IMPL-CLAR-01`, selects Alternative A,
and does not modify the conceptual methodology.

## 4. Approval And Variant Budget

B1-B15 are approved as one indivisible specification. The approval status is
`approved`, the scope is `full_design_specification`, the owner approved it on
2026-07-28, all 17 parameters are frozen, and there is exactly one decisional
variant. Symbol, direction, year, and secondary-horizon cuts are governance
diagnostics, not selectable variants.

## 5. Frozen Research Parameters

| # | Stable name | Frozen value |
| ---: | --- | --- |
| 1 | `drive_start` | 09:30 |
| 2 | `drive_end` | 09:45 |
| 3 | `historical_atr_lookback` | 20 approved sessions |
| 4 | `minimum_normalized_drive` | 0.25 ATR |
| 5 | `minimum_initial_adverse_pullback_ticks` | 1 tick |
| 6 | `maximum_normalized_pullback_depth` | 0.50 |
| 7 | `maximum_post_drive_observation_bars` | 5 |
| 8 | `latest_confirmation_executable_boundary` | 10:10 / 10:15 |
| 9 | `maximum_events_per_symbol_session` | 1 |
| 10 | `primary_horizon_minutes` | 30 |
| 11 | `minimum_pooled_events` | 150 |
| 12 | `minimum_events_per_symbol` | 50 |
| 13 | `minimum_positive_discovery_years` | 2 of 3 |
| 14 | `maximum_annual_effect_concentration` | 0.70 |
| 15 | `bootstrap_confidence_level` | 0.95 |
| 16 | `bootstrap_resamples` | 10,000 |
| 17 | `bootstrap_seed` | 20260728 |

These 17 values live canonically only in
`research_parameters.values` in the hypothesis YAML.
`DrivePullbackConfig` has no decisional defaults and is constructed explicitly
from that validated mapping. Code may retain the stable list of 17 names for
schema validation, but it contains no second copy of their values.

There is separately one `frozen_market_convention`:

```yaml
tick_size_by_symbol:
  QQQ: 0.01
  SPY: 0.01
```

Tick size is non-adjustable, non-optimizable, unavailable for silent override,
and not an eighteenth research parameter. It participates in event selection,
costs, the canonical payload, and its hash. Any change requires a different
validated configuration, payload, and hash. Symbols outside this mapping are
rejected.

## 6. Universe, Data, Session, And Timeframe

The universe is QQQ and SPY, both US equity ETFs, under identical rules.
Future execution requires approved curated 1-minute Alpaca SIP data and
approved manifests, resampled to causal 5-minute bars. This materialization
does not read either source.

The session is US equity RTH, `America/New_York`, 09:30-16:00. Premarket,
after-hours, and overnight are prohibited. Bars are complete five-minute
intervals and become decision-available only at their close.

## 7. Opening Drive And ATR20

The drive consists exactly of `[09:30,09:35)`, `[09:35,09:40)`, and
`[09:40,09:45)`. Its displacement is `close_09_45 - open_09_30`. Long uses
that displacement; short uses its exact algebraic inverse.

Daily RTH true range is:

```text
TR_t = max(high_t-low_t,
           abs(high_t-previous_approved_session_close),
           abs(low_t-previous_approved_session_close))
```

ATR20 is the arithmetic mean of the 20 immediately preceding approved,
complete RTH-session true ranges, shifted one session. The current session
never participates. Manifest-excluded or incomplete sessions are omitted
without imputation; the lookback continues backward through the approved
sequence. Fewer than 20 valid prior true ranges excludes the current event.
For every approved daily session, `previous_approved_close` is derived
internally by a one-session shift of that ordered approved sequence. Callers
cannot override it. Duplicate or contradictory rows for one `session_date`
are rejected rather than resolved by row order.

The drive score is `(close_09_45-open_09_30)/ATR20`. Long qualifies at
`>= +0.25`; short qualifies at `<= -0.25`. Equality qualifies and no rounding
precedes comparison.

## 8. Causal Extreme And Pullback

At 09:45, long freezes the maximum high observed from 09:30 through 09:45 and
short freezes the corresponding minimum low. The extreme never updates.
Excursion is measured from the 09:30 open to that frozen extreme and must be
positive.

The first post-drive bar `[09:45,09:50)` must establish an adverse pullback of
at least one tick. Long depth is `frozen_high - cumulative_pullback_low`; short
depth is `cumulative_pullback_high - frozen_low`. Depth divided by drive
excursion must remain `<= 0.50`; equality qualifies. A later violation
permanently invalidates the session. There is no restart, second drive, or
overlapping pullback.

The minimum distance is
`minimum_initial_adverse_pullback_ticks * tick_size_by_symbol[symbol]`.
Therefore the approved minimum is `1 * 0.01 = 0.01` for both QQQ and SPY, with
equality valid.

For long, any post-drive `high > frozen_drive_extreme` invalidates the event;
for short, any post-drive `low < frozen_drive_extreme` invalidates it.
Equality remains valid. This check applies through confirmation and has
priority when one OHLC bar appears both to extend and to pull back or confirm,
because intrabar ordering is unknown. The stable reason is
`EXCLUDED_POST_DRIVE_NEW_EXTREME`.

## 9. Confirmation, Execution, And Cutoff

Exactly five post-drive bars are eligible:

`[09:45,09:50)`, `[09:50,09:55)`, `[09:55,10:00)`,
`[10:00,10:05)`, and `[10:05,10:10)`.

The first bar may establish the pullback but cannot confirm. The first later
long close strictly above the previous bar high confirms; the symmetric short
rule is a close strictly below the previous bar low. Equality does not confirm.

`confirmation_timestamp` is the causal confirming close. The last valid value
is 10:10. Under the project's approved timestamp convention,
`executable_timestamp` is the first five-minute bar label strictly later than
`confirmation_timestamp`. For confirmation bar `[t,t+5min)`, confirmation is
available at `t+5min` and execution uses the labeled open at `t+10min`.
Therefore 09:55 confirms to 10:00 execution and the final 10:10 confirmation
executes at 10:15. `executable_price` is that bar's open, never the confirming
close. A 10:15 confirmation is ineligible because it would require 10:20
execution. A missing, incomplete, out-of-session, or different-session
executable bar excludes the event.

## 10. Deduplication And Descriptives

The chronologically earliest valid event is retained, with at most one event
per symbol and session regardless of direction. Later and consecutive signals
are ignored; no future drive size or signal quality is compared.

If opposite directions share the earliest executable timestamp for one symbol
and session, neither is retained. The session is excluded with
`EXCLUDED_DIRECTION_CONFLICT`, independently of input order or direction text.

VWAP is `descriptive_only`. RVOL is also `descriptive_only` and, when
available, equals current 09:30-09:45 volume divided by the median same-window
volume of the 20 immediately preceding approved sessions, shifted one session.
Neither field selects, gates, rescues, or creates variants.

## 11. Horizons And Returns

The primary horizon is 30 minutes from `executable_timestamp`. Descriptive
secondary horizons are 15 minutes, 60 minutes, and session close. Missing
same-session horizons are unavailable without imputation. Secondary horizons
cannot rescue the primary.

`primary_horizon_minutes` is the sole canonical and executable source. Labels
such as `"30min"` are derived as `f"{primary_horizon_minutes}min"` and cannot
be supplied as an independent configuration field.

Long return is `future_price/executable_price - 1`. Short return is
`executable_price/future_price - 1`. This favorable-positive orientation is
used for gross, control, incremental, net, bootstrap, and gate calculations.

## 12. Unconditional Control

The sole decisional control matches exact `symbol`, `year`, executable
five-minute time-of-day `HH:MM`, and `horizon`. QQQ and SPY remain separate,
and the event's own `session_date` is excluded. Broad hourly buckets are
forbidden. `incremental_return = event_return - unconditional_return`.

The drive-only comparator is rejected because waiting to establish the absence
of a pullback creates landmark bias after many event execution timestamps.

## 13. Costs And Metrics

Baseline cost uses commission `0.0001` per side, one tick per execution, and
the frozen symbol tick size `0.01`:

`baseline_round_trip_cost = 0.0002 + 0.02/executable_price`.

Stress uses commission `0.0002` per side and two ticks per execution:

`stress_round_trip_cost = 0.0004 + 0.04/executable_price`.

Both profiles resolve tick size through `tick_size_by_symbol[symbol]`; no
generic or caller-overridable tick default exists.

Net returns subtract the applicable cost. Preregistered metrics are event and
session counts; mean, median, win rate, MFE, MAE; bootstrap intervals; symbol,
year, and direction cuts; annual and leave-one-session-out concentration;
horizon availability; control and incremental returns; baseline/stress net
returns; and percentages exceeding each cost. Portfolio PnL, equity curves,
CAGR, Sharpe, drawdown, stops, and targets are outside scope.

## 14. Sample Size And Concentration

Discovery requires at least 150 pooled events and at least 50 for each symbol.
Neither symbol can compensate for the other.

For each year, `C_y` is the sum of primary incremental returns.

```text
annual_concentration = max(abs(C_y)) / sum(abs(C_y))
```

All of 2022, 2023, and 2024 must have valid observations, the denominator must
be positive and finite, and concentration must be `<= 0.70`. The entire
session with largest absolute incremental contribution is then removed and the
same conditions are recomputed and required.

Before either calculation, every `incremental_return`, `session_date`, derived
year, session contribution, and annual contribution must be present and
finite. `NaN`, positive or negative infinity, invalid dates, and contradictory
years fail explicitly; aggregation cannot silently omit or convert them.

## 15. Bootstrap

The cluster is `session_date`; QQQ and SPY rows from the same date remain
together. The frozen procedure is a two-sided 95% percentile interval with
10,000 resamples and seed 20260728. At the primary horizon, lower bounds for
mean gross `event_return`, mean `incremental_return`, and mean
`net_return_baseline` must each be strictly greater than zero. Zero fails.

## 16. Complete Discovery Gate

All 16 conditions are required:

1. At least 150 pooled events.
2. At least 50 events for QQQ and for SPY.
3. Long primary mean and median are strictly positive.
4. Short primary mean and median are strictly positive.
5. QQQ and SPY primary means are strictly positive.
6. Gross primary mean is positive in at least two of 2022-2024.
7. Pooled primary incremental mean is strictly positive.
8. Pooled primary baseline-net mean is strictly positive.
9. Pooled primary stress-net mean is non-negative.
10. Original annual concentration is at most 0.70.
11. Leave-one-session-out concentration is at most 0.70.
12. Original and leave-one-out annual signs are positive in at least two years.
13. All three bootstrap lower-bound conditions pass.
14. No lookahead, timestamp error, invalid manifest use, or unresolved data-quality failure exists.
15. No 2025 or historical 2026 information informed a rule.
16. The one-variant budget was respected.

Any false item yields `discovery_failed`; validation remains locked and
paper/live remain false. A favorable symbol, direction, year, secondary
horizon, VWAP, or RVOL cannot rescue failure.

These booleans are outputs derived from a structured primary-horizon metric
record. Caller-supplied boolean criteria are not an authoritative gate input.
The derivation applies the frozen sample, sign, cost, concentration, bootstrap,
integrity, contamination, variant, and primary-horizon rules.

## 17. Multiplicity And Temporal Policy

No formal multiplicity correction exists, so the gate is not a claim of
multiple-comparison-corrected statistical significance.

Discovery is 2022-01-01 through 2024-12-31 and has not run. Validation
2025-01-01 through 2025-12-31 is locked until every discovery gate condition
passes. Historical 2026 is contaminated, non-decisional, and prohibited.
Forward shadow can begin only after identifiable preregistration and future
implementation freeze commits.

## 18. Lookahead, Safety, And Prohibitions

Event selection may use information only through `confirmation_timestamp`.
The causal extreme is fixed at 09:45, current-session ATR is excluded,
execution uses a later open, the control excludes the event date, and
deduplication never compares future candidates.

All of `strategy_created`, `orders_created`, `position_sizing_used`,
`broker_connected`, `paper_broker_enabled`, `live_trading`, `orders_sent`,
`paper_eligible`, and `live_eligible` are false. This preregistration does not
authorize reading real data or
manifests, discovery, validation, 2026 analysis, optimization, strategy
construction, portfolio PnL, sizing, orders, or broker connectivity.

## 19. Canonical Payload Hash

The canonical payload is serialized as UTF-8 JSON with sorted keys,
deterministic separators, stable numeric values, and explicit list order. Its
SHA-256 is:

`b763e7d2d01f1d12f9be85fa0238a4ccb21b251baee966f8e421410aaecc651b`

The payload is derived directly from the complete, deeply immutable,
strictly validated YAML configuration. Every YAML field is included except
`canonical_payload_hash`, which is classified as
`declared_integrity_metadata` and excluded solely to avoid checksum
self-reference. After payload calculation, the declared checksum is compared
strictly with the recomputed value; a missing or incorrect declaration blocks
configuration loading.

Executable methodology is selected by validated canonical IDs for pullback
distance, post-drive invalidation and intrabar priority, confirmation,
execution timestamp, primary-horizon label derivation, round-trip costs,
annual concentration, clustered bootstrap, and gate evaluation. The effective
16-item gate list comes from the YAML and is resolved through an
implementation registry. There are no separate authoritative policy or gate
value tables in Python.

External fields named by
`canonical_payload.explicitly_non_methodological_excluded` are removed only
if supplied outside the canonical YAML: generation timestamps, absolute path,
user, hostname, working-tree state, future execution SHA, preregistration
commit, results, historical counts, and run-derived data. No status, freeze,
policy, formula ID, gate rule, cost, split, promotion consequence, safety flag,
or forbidden action is excluded.

The preregistration commit is intentionally absent until project-owner review
and a later commit. Passing this document's checks does not imply that the
hypothesis will pass discovery.
