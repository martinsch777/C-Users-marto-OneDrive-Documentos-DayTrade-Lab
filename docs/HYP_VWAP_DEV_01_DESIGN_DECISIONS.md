# HYP-VWAP-DEV-01 Design Decisions

```text
hypothesis_id: HYP-VWAP-DEV-01
design_status: draft_for_human_review
human_review_performed: true
human_approved: false
methodology_frozen: false
ready_for_preregistration: false
implementation_started: false
implementation_allowed: false
historical_discovery_opened: false
validation_2025_unlocked: false
historical_2026_decisional: false
decision_variants: 1
```

## Document Purpose

This document is a conceptual decision draft. It is not a preregistration,
configuration, implementation specification, or authorization to inspect
historical outcomes. Only B5, B6, and B13 remain pending human approval.

Human review partially approved the design. B1-B4, B7-B12, B14, and B15 are
approved. Full design approval remains withheld because B5, B6, and B13 are
still blocked. Approval of individual decisions does not authorize
preregistration or implementation.

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

Decisions still absent include the mechanism, deviation unit, exact threshold,
eligible time window, confirmation rule, event timing, deduplication, primary
horizon, gate thresholds, and human approval.

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
| B5 | false | true | blocked | false | One strict symmetric threshold; numeric value and ex-ante source pending |
| B6 | false | true | blocked | false | Bounded eligible intraday window; exact bounds and early-close policy pending |
| B7 | true | false | approved_by_human_review_with_corrected_wording | false | First breach and immediate next-bar confirmation contract |
| B8 | true | false | approved_by_human_review_with_corrected_wording | false | Next-bar-open causal execution with pre-execution crossing cancellation |
| B9 | true | false | approved_by_human_review_with_corrected_wording | false | One candidate per symbol-session; no rescanning or replacement signal |
| B10 | true | false | approved_by_human_review | false | 30-minute primary; 15-minute, 60-minute, and session-close secondary horizons |
| B11 | true | false | approved_by_human_review | false | Exact-time matched unconditional control |
| B12 | true | false | approved_by_human_review | false | Inherited baseline and stress costs |
| B13 | false | true | blocked | false | Complete hypothesis-specific all-required gate pending |
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
- A zero-volume bar contributes zero numerator and denominator increment.
- If cumulative session volume is zero, VWAP is unavailable and no event may
  exist.

### B4-B5: Deviation And Threshold

Selection uses signed percentage deviation from causal session VWAP only:

```text
signed_deviation_t = close_t / session_vwap_t - 1
```

Negative values indicate price below VWAP. Positive values indicate price above
VWAP. ATR, RSI, rolling volatility, and standard-deviation bands are not
executable alternatives in HYP-VWAP-DEV-01.

B5 remains blocked. The pending selection boundary is:

Use one symmetric strict boundary:

```text
abs(deviation_t) > tau
```

`tau` has no numeric value or approved ex-ante source. The boundary must remain
strict and symmetric for long/short orientations. No historical frequency or
return may inform it.

```text
approved: false
requires_human_approval: true
resolution_status: blocked
implementation_allowed: false
historical_frequency_used: false
historical_returns_used: false
parameter_optimization_performed: false
```

### B6-B7: Window And Formation

#### B6: Blocked Eligible Window

The eligible interval is bounded within RTH. These items remain pending:

- earliest eligible breach time;
- latest eligible executable time;
- exact early-close policy.

The already agreed constraint is:

```text
executable_timestamp + primary_horizon <= session_close
```

No eligible time may be chosen from historical event counts or returns.

```text
approved: false
requires_human_approval: true
resolution_status: blocked
implementation_allowed: false
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
14. The eligible window and threshold remain governed by unresolved B5 and B6.

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

### B12: Costs

The inherited project cost conventions are:

```text
baseline_cost = 0.0002 + 0.02 / executable_price
stress_cost = 0.0004 + 0.04 / executable_price
```

These are project conventions inherited ex ante and are not optimized
parameters of HYP-VWAP-DEV-01.

### B13: Proposed Gate Dimensions

B13 remains blocked. The eventual all-required gate must define:

- minimum pooled sample and minimum sample for each mandatory symbol;
- adequate representation of both deviation orientations, or an explicit
  preregistered rule for handling an absent orientation;
- positive oriented gross mean and median;
- positive incremental mean versus the matched control;
- positive baseline-net mean and non-negative stress-net mean;
- consistent expected sign across QQQ and SPY;
- expected sign in a preregistered number of discovery years;
- session-clustered bootstrap intervals;
- annual and leave-one-session-out concentration;
- causal, calendar, manifest, timestamp, and contamination integrity;
- one-variant compliance.

Numeric minimum samples, annual thresholds, concentration limits, bootstrap
method/seed/resamples, and exact pass logic are unresolved. They must not be
copied automatically from DRIVE-PB or selected from historical counts.

The missing-required-year policy and treatment of an absent orientation are
also unresolved.

```text
approved: false
requires_human_approval: true
resolution_status: blocked
implementation_allowed: false
```

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
| VWAP-DEV-BLK-05 | B5 | Approve strict symmetric boundary and set one ex-ante numeric threshold | true | false | Pending |
| VWAP-DEV-BLK-06 | B6 | Approve exact earliest/latest eligible times and early-close policy | true | false | Pending |
| VWAP-DEV-BLK-13 | B13 | Approve complete gate, numeric thresholds, bootstrap, and concentration policy | true | false | Pending |

## Resolved By Human Review

`VWAP-DEV-BLK-01` through `VWAP-DEV-BLK-04`, `VWAP-DEV-BLK-07` through
`VWAP-DEV-BLK-12`, and `VWAP-DEV-BLK-14` through `VWAP-DEV-BLK-15` are resolved.
B7-B9 were resolved with corrected causal wording; all other listed decisions
were approved without correction. Resolved items are not preregistration
blockers and do not authorize implementation.

```text
ready_for_human_review: true
human_review_performed: true
human_approved: false
ready_for_preregistration: false
blockers_remaining: 3
implementation_allowed: false
```
