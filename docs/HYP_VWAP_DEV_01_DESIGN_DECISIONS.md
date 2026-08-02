# HYP-VWAP-DEV-01 Design Decisions

```text
hypothesis_id: HYP-VWAP-DEV-01
design_status: human_approved_ready_for_preregistration
human_review_performed: true
human_approved: true
methodology_frozen: false
ready_for_preregistration: true
implementation_started: false
implementation_allowed: false
historical_discovery_opened: false
validation_2025_unlocked: false
historical_2026_decisional: false
decision_variants: 1
blockers_remaining: 0
```

## Document Purpose

This document is a human-approved conceptual design. It is not a
preregistration, configuration, implementation specification, methodology
freeze, or authorization to inspect historical outcomes. All B1-B15 decisions
are approved and no conceptual blocker remains.

`human_approved=true` records approval of the conceptual design.
`methodology_frozen=false` remains because no conceptual-design freeze commit
exists. `ready_for_preregistration=true` authorizes drafting the
preregistration only. Implementation remains prohibited until the complete
preregistration and any required clarifications are reviewed and frozen.

The objective is one independent, causal equity event study. It must not relax
or rename HYP-DRIVE-PB-01, and it must not reproduce a previously rejected
VWAP strategy with cosmetic changes.

## PRIOR ART AND PROJECT PROVENANCE

### Provenance Timeline

| Date/commit | Evidence | Meaning |
| --- | --- | --- |
| 2026-07-13, `0a487351b3bbd1ae39ad6a71ef38b5cc8b931002` | `docs/INTRADAY_HYPOTHESIS_REFINEMENT_PROTOCOL.md`, section `HYP-VWAP-DEV` around line 132 | First explicit project concept: choose continuation or reversion after a VWAP deviation; no exact variant or preregistration |
| 2026-07-28, `a30dfdd66809ada8e836efaf92b564b96623eb9c` | `docs/NEXT_RESEARCH_PRIORITY.md`, inventory and priority matrix around lines 80, 244, and 351 | First exact proposed ID `HYP-VWAP-DEV-01`; ranked as a category-B alternative before HYP-DRIVE-PB-01 discovery results |
| 2026-08-02, `8bf40206aa2096bbbb12b6dcd15ca561a936c722` | HYP-DRIVE-PB-01 discovery closure | VWAP-DEV becomes the next design priority only after the previously preferred candidate closes |

The family concept and exact proposed ID both predate the DRIVE-PB discovery
closure. The exact ID was a named alternative, not a preregistered hypothesis.

### Internal Files Found

| File | Relevant internal precedent | Reuse or conflict |
| --- | --- | --- |
| `docs/INTRADAY_HYPOTHESIS_REFINEMENT_PROTOCOL.md` | Requires deviation unit, scaling, time bucket, RVOL policy, prior-return policy, and one expected direction | Source concept; leaves all exact decisions open |
| `docs/NEXT_RESEARCH_PRIORITY.md` | Proposed a one-variant QQQ/SPY event study using causal VWAP deviation and a fixed intraday design | Priority provenance; not a freeze |
| `docs/DAYTRADE_LAB.md` around lines 97-110 | Defines historical VWAP Pullback and Extreme Mean Reversion strategy families | Must not duplicate strategy logic |
| `docs/DAYTRADE_REAL_DATA_VALIDATION.md` around lines 107-164 | Historical crypto VWAP Pullback and Extreme Mean Reversion were rejected under their tested rules | Prior negative strategy evidence; not parameter input for this design |
| `docs/YOUTUBE_FORUM_STRATEGY_HUNTER.md` around line 17 | Historical `VWAP Deviation Reversion` strategy was rejected | Direct overlap risk |
| `src/strategies/vwap_pullback.py` | EMA alignment, VWAP touch/rejection, stop and target | Existing implementation, but not this hypothesis |
| `src/strategies/extreme_mean_reversion.py` | Two-ATR-like extension family with RSI and reversal conditions | Existing implementation, but not this hypothesis |
| `src/strategy_hunter/strategies.py` around line 550 | Two-ATR VWAP deviation, RSI, closed-bar reversal, stop/target | Closest duplicate risk; must not be copied |
| `src/indicators/core.py` around lines 37-44 | Session VWAP from typical price and cumulative volume | Reusable project convention after review |
| `docs/HYP_GAP_EVENT_STUDY_SPEC.md` around lines 121 and 170-216 | Causal opening VWAP used in gap continuation/reversal variants | VWAP precedent, but gap-conditioned mechanism is closed and must not be reused |
| `docs/HYP_DRIVE_PB_01_DESIGN_DECISIONS.md` around lines 396-433 and 470-500 | Causal session VWAP convention and exact-time unconditional control | Reusable research conventions, not DRIVE-PB selection rules |
| `docs/HYP_REL_01_INTRADAY_DIVERGENCE_RESULTS.md` | Relative mean reversion study | Mechanism differs: cross-symbol divergence rather than own-price VWAP deviation |

### Prior Definition And Missing Decisions

The previous protocol defined only a family: distance from VWAP could represent
temporary dislocation or institutional trend pressure. It explicitly required
choosing continuation or reversion before testing. The later priority document
suggested a volatility-scaled deviation at a fixed intraday timestamp, but did
not freeze scaling, timestamp, threshold, confirmation, gate, or orientation.

No `HYP-VWAP-DEV-01` YAML, preregistration, source module, runner, test, or
artifact exists. There is no duplicate implementation under that ID.

Those previously absent decisions are now resolved in B1-B15. They remain
unfrozen and must be translated without alteration into a reviewed
preregistration before implementation can be considered.

### Conflict Controls

The new concept must remain distinct from:

- generic crypto VWAP Pullback using EMA alignment and a VWAP rejection;
- Extreme Mean Reversion using ATR extension, RSI, candle reversal, stops, and
  targets;
- the strategy-hunter two-ATR VWAP Deviation Reversion;
- gap-conditioned VWAP acceptance/rejection;
- opening-drive/pullback continuation;
- QQQ/SPY relative-divergence mean reversion.

The proposed study uses own-price distance from causal RTH session VWAP as an
event, measures forward oriented returns, and has no EMA, RSI, gap, OR, FVG,
stop, target, sizing, or order logic.

## Conceptual Alternatives

### Alternative A: Mean Reversion

After an extreme causal deviation from session VWAP, the first closed-bar move
back toward VWAP may indicate that a temporary intraday dislocation is starting
to normalize. Orientation is toward VWAP: negative deviation implies long and
positive deviation implies short.

### Alternative B: Continuation

After an extreme causal deviation, continued acceptance away from VWAP may
indicate persistent institutional pressure. Orientation is away from VWAP.

### Human Review Decision

Alternative A, mean reversion, is approved as the sole mechanism. It has an
explicit economic anchor, is distinct from DRIVE-PB continuation, and uses one
simple causal confirmation. The decision does not rely on historical comparison
between A and B. Alternative B is rejected as an executable alternative.

The approved mechanism remains distinct from prior ATR+RSI VWAP-reversion
strategies: it uses no RSI, trend filter, stop, target, or historically selected
two-ATR threshold.

## Decision Matrix B1-B15

| decision_id | approved | requires_human_approval | resolution_status | implementation_allowed | approved_or_pending_choice |
| --- | --- | --- | --- | --- | --- |
| B1 | true | false | approved_by_human_review | false | Mean reversion toward causal session VWAP; continuation prohibited |
| B2 | true | false | approved_by_human_review | false | QQQ and SPY; causal 5-minute RTH bars in America/New_York |
| B3 | true | false | approved_by_human_review | false | Cumulative causal typical-price session VWAP including the current completed bar |
| B4 | true | false | approved_by_human_review | false | Signed percentage deviation only |
| B5 | true | false | approved_by_human_review | false | Strict symmetric percentage threshold `tau=0.005` |
| B6 | true | false | approved_by_human_review | false | Breach close 10:00 through session close minus 65 minutes; execution through close minus 60 minutes |
| B7 | true | false | approved_by_human_review_with_corrected_wording | false | First breach and immediate next-bar confirmation contract |
| B8 | true | false | approved_by_human_review_with_corrected_wording | false | Next-bar-open causal execution with pre-execution crossing cancellation |
| B9 | true | false | approved_by_human_review_with_corrected_wording | false | One candidate per symbol-session; no rescanning or replacement signal |
| B10 | true | false | approved_by_human_review | false | 30-minute primary; 15-minute, 60-minute, and session-close secondary horizons |
| B11 | true | false | approved_by_human_review | false | Exact-time matched unconditional control |
| B12 | true | false | approved_by_human_review | false | Inherited baseline and stress costs |
| B13 | true | false | approved_by_human_review | false | Complete balanced all-required discovery gate |
| B14 | true | false | approved_by_human_review | false | Discovery 2022-2024; 2025 locked; historical 2026 non-decisional |
| B15 | true | false | approved_by_human_review | false | Causal event study only; permanent safety state |

## Detailed Draft Conventions

### B1: Mechanism

The sole mechanism is mean reversion toward causal session VWAP.

For signed deviation:

```text
deviation_t = close_t / session_vwap_t - 1
```

A negative signed deviation is long-oriented. A positive signed deviation is
short-oriented. Continuation is not an executable alternative or decision
variant. Mean reversion and continuation cannot be combined.

### B2: Universe And Timeframe

QQQ and SPY are mandatory research symbols. Approved source inputs are
one-minute regular-trading-hours equity datasets. Research bars are causal
five-minute bars in `America/New_York`, and only approved RTH sessions are
eligible. Premarket, after-hours, and overnight observations are excluded.

### B3: Causal Session VWAP

For each completed five-minute bar:

```text
typical_price_t = (high_t + low_t + close_t) / 3

session_vwap_t =
    cumulative_sum(typical_price_i * volume_i) /
    cumulative_sum(volume_i)

for completed bars i from the 09:30 session open through bar t
```

- The current completed bar is included.
- Reset all cumulative state at every approved session.
- Only completed-bar information may enter the calculation.
- No future bar, future volume, or future price may be used.
- If cumulative session volume through completed bar `t` is zero,
  `session_vwap_t` is undefined and that bar cannot create or confirm an event.
- Once cumulative session volume is strictly positive, VWAP is computed
  normally.
- A completed bar with zero individual volume contributes zero to the
  cumulative numerator and denominator. If prior cumulative volume is
  positive, session VWAP remains defined and unchanged by that bar.
- Forward filling from another session is prohibited. Volume must not be
  replaced by one or by synthetic imputation.

This is a technical causal clarification, not a new mechanism, threshold, or
decision variant.

### B4-B5: Deviation And Threshold

Selection uses signed percentage deviation from causal session VWAP only:

```text
signed_deviation_t = close_t / session_vwap_t - 1
```

Negative values indicate price below VWAP. Positive values indicate price above
VWAP. ATR, RSI, rolling volatility, and standard-deviation bands are not
executable alternatives in HYP-VWAP-DEV-01.

B5 is approved with one symmetric strict boundary:

```text
tau = 0.005

long-oriented candidate: signed_deviation_t < -0.005
short-oriented candidate: signed_deviation_t > 0.005
```

Equality at either boundary is not a breach. The threshold is strict,
symmetric, percentage-based, unique, fixed ex ante, identical for QQQ and SPY,
and independent of ATR, RSI, rolling volatility, and standard-deviation bands.
It was not optimized against historical event counts or returns.

`tau=0.005` is a round, interpretable 0.50% displacement from causal session
VWAP. Its magnitude is economically material relative to the inherited
round-trip cost conventions. This does not imply that recoverable mean
reversion will exceed costs or assert profitability. No internal literature
establishes a uniquely correct threshold; this is an ex-ante economic design
decision, not an empirical calibration.

```text
approved: true
requires_human_approval: false
resolution_status: approved_by_human_review
implementation_allowed: false
justification_type: C
inherited_or_new: new
historical_calibration_used: false
selection_data_used: false
historical_returns_used: false
historical_event_counts_used: false
parameter_search_performed: false
historical_threshold_comparison_performed: false
```

### B6-B7: Window And Formation

#### B6: Approved Eligible Window

`session_open` and `session_close` come from the approved US equity calendar
for the specific session. Eligible boundaries use completed-bar close
timestamps in `America/New_York`:

```text
10:00 <= breach_close_timestamp <= session_close - 65 minutes
confirmation_close_timestamp = breach_close_timestamp + 5 minutes
executable_timestamp = confirmation_close_timestamp
executable_timestamp <= session_close - 60 minutes
```

The first eligible breach close is 10:00. The immediately following contiguous
five-minute bar is the only confirmation bar. Execution is at the open of the
five-minute bar immediately following confirmation; for contiguous bars, that
instant equals `confirmation_close_timestamp`. All permitted boundaries are
inclusive.

For a regular 16:00 close, the earliest breach, confirmation, and execution are
10:00, 10:05, and 10:05; the latest are 14:55, 15:00, and 15:00. For an early
13:00 close, the latest are 11:55, 12:00, and 12:00. No early-close hour may be
hard-coded independently of the approved calendar.

If the session cannot support the eligible breach, immediate confirmation,
execution open, and complete 15-minute, 30-minute, 60-minute, and session-close
horizons, the symbol-session has no eligible event. The 10:00 start excludes
the immediate opening interval and allows causal session VWAP to accumulate.
The close-minus-60-minute execution cutoff guarantees every fixed horizon.
No event-frequency or return data informed the window.

```text
approved: true
requires_human_approval: false
resolution_status: approved_by_human_review
implementation_allowed: false
justification_type: B/C
inherited_or_new: new
historical_calibration_used: false
selection_data_used: false
historical_returns_used: false
historical_event_counts_used: false
parameter_search_performed: false
historical_threshold_comparison_performed: false
```

#### B7-B9: Approved Integrated Causal Contract

1. The first completed five-minute bar whose close strictly breaches the
   approved symmetric deviation threshold is the symbol-session's only
   candidate breach.
2. Its orientation is fixed at the breach. Negative deviation is long-oriented
   mean reversion; positive deviation is short-oriented mean reversion.
   Continuation labels are prohibited.
3. The immediately following completed five-minute bar is the only eligible
   confirmation bar.
4. Confirmation requires all of the following:
   - the confirmation close remains strictly on the same side of its own causal
     session VWAP as the breach;
   - its absolute signed deviation is strictly smaller than the breach bar's
     absolute signed deviation;
   - it does not create a more extreme close away from VWAP than the breach
     close;
   - all required bars and causal VWAP states are complete and eligible.
5. Formally:

```text
sign(deviation_confirmation) = sign(deviation_breach)
and
abs(deviation_confirmation) < abs(deviation_breach)
```

6. If the immediately following bar fails any confirmation condition, the
   complete symbol-session is invalidated.
7. No subsequent breach, confirmation, opposite-side breach, reset, cooldown,
   re-entry, or replacement signal may restart that symbol-session.
8. `confirmation_timestamp` is the close timestamp of the immediately
   following completed bar.
9. `executable_timestamp` is the opening timestamp of the next five-minute bar
   after confirmation. `executable_price` is that bar's open.
10. The VWAP state available at `executable_timestamp` is the most recent causal
    VWAP computed from completed bars. The execution bar contributes no price
    or volume before its open.
11. Before recording execution, apply the direction-specific crossing rule
    using `executable_price` and the causal VWAP available at
    `executable_timestamp`:

```text
long-oriented candidate: cancel when executable_price >= executable_vwap
short-oriented candidate: cancel when executable_price <= executable_vwap
```

12. Equality with VWAP counts as a completed crossing and cancels the event.
13. A canceled execution does not permit rescanning or another event during the
    same symbol-session.
14. The eligible window and threshold are the approved B5 and B6 rules above.

```text
B7_resolution_status: approved_by_human_review_with_corrected_wording
B8_resolution_status: approved_by_human_review_with_corrected_wording
B9_resolution_status: approved_by_human_review_with_corrected_wording
approved: true
requires_human_approval: false
implementation_allowed: false
```

### B10: Horizons

All forward returns are measured from `executable_timestamp` and
`executable_price`. The sole primary horizon is 30 minutes. Secondary horizons
are 15 minutes, 60 minutes, and session close. Secondary horizons are
descriptive and cannot rescue a failed primary horizon or primary gate. No
horizon may cross session close.

### B11: Unconditional Control

For each event and horizon, the unconditional control matches:

- the same symbol;
- the same calendar year;
- the exact local `HH:MM` on the 5-minute grid;
- the same horizon;
- an approved session other than the event's own `session_date`.

Control returns use the same long/short orientation as the event. Controls
outside discovery are prohibited. Use equal timestamp weights. Do not select
controls using deviation, future return, regime, gap, volume, or event status.
An exact-time control that is empty, non-finite, or non-estimable fails the
event and therefore the required gate. A different time, year, or symbol must
not be substituted.

### B12: Costs

The inherited project cost conventions are:

```text
baseline_cost = 0.0002 + 0.02 / executable_price
stress_cost = 0.0004 + 0.04 / executable_price
```

These are project conventions inherited ex ante and are not optimized
parameters of HYP-VWAP-DEV-01.

### B13: Approved All-Required Discovery Gate

```text
approved: true
requires_human_approval: false
resolution_status: approved_by_human_review
implementation_allowed: false
gate_type: all_required
primary_horizon: 30min
secondary_horizons_cannot_override_primary_fail: true
minimum_pooled_events: 150
minimum_events_per_symbol: 50
minimum_events_per_year: 40
minimum_events_per_orientation: 40
selection_data_used: false
historical_returns_used: false
historical_event_counts_used: false
parameter_search_performed: false
historical_threshold_comparison_performed: false
```

Every required criterion must pass. A false, missing, non-finite,
insufficient, or non-estimable required criterion produces:

```text
classification: discovery_failed
validation_2025_unlocked: false
paper_eligible: false
live_eligible: false
strategy_created: false
position_sizing_used: false
orders_created: false
```

There is no discretionary `promising despite failed gate` status. Economic
metrics cannot compensate for an integrity failure. Results may be retained
descriptively after a failed gate but cannot promote the hypothesis.

#### Sample, Representation, And Economics

QQQ and SPY must each have at least 50 primary events. Each of 2022, 2023, and
2024 must have at least 40, and long and short orientations must each have at
least 40. Both symbols and both orientations are mandatory; absence or
insufficiency fails. The pooled minimum is 150. The 150/50 minima are inherited
cross-project conventions; 40 per year and orientation are new ex-ante
statistical decisions. These minima do not guarantee power for any specified
effect size.

All decisional economic metrics use only the 30-minute primary horizon:

- pooled gross mean must be strictly positive;
- QQQ and SPY gross means must each be strictly positive;
- long and short gross mean and median must each be strictly positive;
- pooled, QQQ, and SPY baseline-net means must each be strictly positive;
- pooled stress-net mean must be non-negative;
- pooled incremental mean versus the approved control must be strictly
  positive.

Both mean and median must pass where both are named. Stress net cannot rescue a
negative baseline-net result. A positive pooled mean cannot hide a mandatory
symbol with a non-positive required mean. Unlisted cuts remain descriptive.

#### Bootstrap

```text
confidence_level: 0.95
bootstrap_method: percentile
bootstrap_replicates: 10000
bootstrap_seed: 20260802
bootstrap_cluster_unit: session_date
```

Build clusters by `session_date`, keeping all QQQ and SPY events from the same
date together. Resample clusters with replacement; each replicate contains the
same number of clusters as the original sample. Recompute each pooled mean for
every replicate. The bilateral 95% percentile interval uses the 2.5th and
97.5th percentiles.

The bootstrap lower bounds for pooled gross mean, pooled incremental mean, and
pooled baseline-net mean must each be strictly greater than zero. Stress net
has no bootstrap lower-bound requirement; its pooled mean must be non-negative.
Fewer than two `session_date` clusters, non-finite results, absent groups, or a
non-estimable bootstrap fails. Independent row resampling is prohibited when
symbols share a session date.

#### Annual Stability, Concentration, And Leave-One-Out

All 2022, 2023, and 2024 groups must exist, contain at least 40 events, and
produce finite metrics. At least two years must have strictly positive gross
mean, and at least two must have strictly positive incremental mean. A missing,
insufficient, or non-finite year fails. A zero or negative mean counts as not
positive and no year may be silently omitted.

For each required year:

```text
C_y = sum(incremental_return for all required primary events in year y)
annual_concentration = max_y(abs(C_y)) / sum_y(abs(C_y))
```

Annual concentration must be at most 0.70. The limit is an inherited
cross-project ex-ante convention against single-year dominance. A zero
denominator, missing year, non-finite value, or non-estimable result fails.

For leave-one-out, sum incremental contribution by `session_date`, keeping QQQ
and SPY together, and remove the complete date with the largest absolute total
incremental contribution. Do not remove only one row or symbol. After removal:

- every year must still have at least 40 events;
- annual concentration must remain at most 0.70;
- pooled incremental mean must remain strictly positive;
- at least two years must retain strictly positive incremental mean.

A missing or insufficient year, one remaining observation or cluster, zero
denominator, non-finite metric, or non-estimable result fails the leave-one-out
block.

#### Normative Gate Matrix

| criterion_id | category | scope | metric | operator | threshold | required | missing_data_policy | failure_classification | justification_type | justification | inherited_or_new |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| INT-01 | integrity | global | causal_integrity_passed | = | true | true | FAIL | discovery_failed | A/B | causal event integrity | inherited |
| INT-02 | integrity | global | dataset_contract_passed | = | true | true | FAIL | discovery_failed | A | approved dataset contract | inherited |
| INT-03 | integrity | global | manifest_validation_passed | = | true | true | FAIL | discovery_failed | A | manifest traceability | inherited |
| INT-04 | integrity | global | lookahead_violations | = | 0 | true | FAIL | discovery_failed | B | causal boundary | inherited |
| INT-05 | integrity | global | unresolved_data_quality_failures | = | 0 | true | FAIL | discovery_failed | A | complete data quality | inherited |
| INT-06 | integrity | global | 2025_or_2026_contamination | = | false | true | FAIL | discovery_failed | A | temporal partition | inherited |
| INT-07 | integrity | every confirmed event | required_horizons_available_and_path_complete | = | true | true | FAIL | discovery_failed | B | complete causal paths | new |
| INT-08 | integrity | global | decision_variants | = | 1 | true | FAIL | discovery_failed | A | multiplicity control | inherited |
| SMP-01 | sample | pooled | event_count | >= | 150 | true | FAIL | discovery_failed | A/D | minimum precision | inherited |
| SMP-02 | sample | each QQQ and SPY | event_count | >= | 50 | true | FAIL | discovery_failed | A/D | symbol representation | inherited |
| SMP-03 | sample | each 2022, 2023, 2024 | event_count | >= | 40 | true | FAIL | discovery_failed | D | annual representation | new |
| REP-01 | representation | each long and short | event_count | >= | 40 | true | FAIL | discovery_failed | D | symmetric orientation representation | new |
| ECO-01 | economy | pooled | gross_mean_30min | > | 0 | true | FAIL | discovery_failed | C | favorable primary effect | inherited |
| ECO-02 | economy | each QQQ and SPY | gross_mean_30min | > | 0 | true | FAIL | discovery_failed | C/D | no pooled masking | inherited |
| ECO-03 | economy | each long and short | gross_mean_and_median_30min | > | 0 | true | FAIL | discovery_failed | C/D | bilateral consistency | inherited |
| ECO-04 | economy | pooled and each symbol | baseline_net_mean_30min | > | 0 | true | FAIL | discovery_failed | C | exceeds inherited baseline cost | expanded |
| ECO-05 | economy | pooled | stress_net_mean_30min | >= | 0 | true | FAIL | discovery_failed | C | adverse-cost robustness | inherited |
| INC-01 | incremental | pooled | incremental_mean_30min | > | 0 | true | FAIL | discovery_failed | C/D | value over exact-time control | inherited |
| UNC-01 | uncertainty | pooled | gross_incremental_baseline_95pct_lower_bounds | > | 0 | true | FAIL | discovery_failed | A/D | session-clustered uncertainty | inherited |
| STB-01 | stability | 2022-2024 | years_with_positive_gross_mean_30min | >= | 2 | true | FAIL | discovery_failed | A/D | annual persistence | inherited |
| STB-02 | stability | 2022-2024 | years_with_positive_incremental_mean_30min | >= | 2 | true | FAIL | discovery_failed | D | incremental persistence | new |
| CON-01 | concentration | annual | max_abs_annual_incremental_share | <= | 0.70 | true | FAIL | discovery_failed | A/D | no annual dominance | inherited |
| CON-02 | concentration | leave-largest-session-out | max_abs_annual_incremental_share | <= | 0.70 | true | FAIL | discovery_failed | A/D | session influence robustness | inherited |
| CON-03 | concentration | leave-largest-session-out | pooled_incremental_mean_30min | > | 0 | true | FAIL | discovery_failed | D | effect survives largest session | new |
| CON-04 | concentration | leave-largest-session-out | positive_incremental_years_with_minimum_40 | >= | 2 | true | FAIL | discovery_failed | A/D | residual annual stability | expanded |
| PRO-01 | promotion | global | all_required_criteria | = | true | true | FAIL | discovery_failed | A | sole validation unlock condition | inherited |

No criterion has further human approval pending. `PRO-01` is the sole condition
for `validation_2025_unlocked=true`; any failure keeps validation, strategy,
paper, live, sizing, and orders disabled.

### B14: Temporal Partitions

The approved governance split is:

- discovery: 2022-01-01 through 2024-12-31;
- validation: 2025-01-01 through 2025-12-31, locked until every required
  discovery gate passes;
- historical 2026: non-decisional and unavailable for selection, tuning, gate
  construction, or promotion.

### B15: Safety And Scope

HYP-VWAP-DEV-01 is a causal event study. It is not yet a trading strategy.

```text
strategy_created: false
position_sizing_used: false
orders_created: false
orders_sent: false
broker_connected: false
paper_broker_enabled: false
paper_eligible: false
live_trading: false
live_eligible: false
```

## EX ANTE FREQUENCY EXPECTATION

Qualitative classification: `moderate`.

This classification is based only on logical complexity: one deviation breach,
one immediate closed-bar confirmation, and a maximum of one event per
symbol-session. It is not based on historical counts or an attempt to reach a
specific sample threshold.

The design intentionally avoids chained EMA, RSI, gap, FVG, OR, RVOL, and
multi-bar persistence conditions. Actual frequency is unknown and must remain
unknown until the design, threshold, gate, and implementation are frozen and a
separate discovery authorization is granted.

## DATA SNOOPING RISKS

Permitted:

- select an independent hypothesis that was documented before DRIVE-PB closed;
- use reviewed common conventions for causal VWAP, timestamps, controls, costs,
  temporal partitions, and safety;
- simplify research architecture;
- document that DRIVE-PB failed for insufficient frequency.

Not permitted:

- relax DRIVE-PB under a VWAP name;
- use DRIVE-PB exclusions to select `tau`, the VWAP window, or confirmation;
- reuse the historically observed two-ATR/RSI rule as a favorable candidate;
- select threshold, window, scaling, orientation, or gate from 2022-2024
  outcomes;
- compare mean reversion and continuation historically before freeze;
- create multiple executable variants;
- open 2025 or use historical 2026.

## Blockers For Preregistration

| blocker_id | decision_id | description | human_decision_required | resolved | resolution |
| --- | --- | --- | --- | --- | --- |

## Resolved By Human Review

All 15 conceptual blockers are resolved:

- `VWAP-DEV-BLK-01` through `VWAP-DEV-BLK-04`: approved by human review;
- `VWAP-DEV-BLK-05`: approved with strict symmetric `tau=0.005`;
- `VWAP-DEV-BLK-06`: approved with the calendar-relative eligible window;
- `VWAP-DEV-BLK-07` through `VWAP-DEV-BLK-09`: approved with corrected causal
  wording;
- `VWAP-DEV-BLK-10` through `VWAP-DEV-BLK-12`: approved by human review;
- `VWAP-DEV-BLK-13`: approved with the complete balanced all-required gate;
- `VWAP-DEV-BLK-14` and `VWAP-DEV-BLK-15`: approved by human review.

Resolved decisions authorize preregistration drafting only. They do not freeze
methodology or authorize implementation.

```text
human_review_performed: true
human_approved: true
ready_for_preregistration: true
methodology_frozen: false
blockers_remaining: 0
implementation_allowed: false
```
