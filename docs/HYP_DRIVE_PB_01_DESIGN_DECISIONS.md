# HYP-DRIVE-PB-01 Design Decisions

Decision date: 2026-07-28

Proposed hypothesis: `HYP-DRIVE-PB-01`

Conceptual name: Opening Drive + Controlled Pullback Continuation

Document status: **ex ante design recommendation pending human approval**

This memo resolves the 15 conceptual blockers identified in
`docs/HYP_DRIVE_PB_01_PREREGISTRATION_BLOCKERS.md`. It is not the canonical
preregistration and does not authorize implementation or discovery.

## 1. Summary

The recommended event is a symmetric continuation event on QQQ and SPY:

1. Measure the signed close-to-open displacement during the first 15 minutes of
   RTH.
2. Require that displacement to be at least 0.25 of the mean true range of the
   previous 20 approved sessions.
3. Freeze the drive extreme at 09:45.
4. Require the first post-drive 5-minute bar to establish a pullback of at least
   one tick without exceeding 50% of the drive excursion.
5. Allow at most five post-drive bars, including the initial pullback bar.
6. Confirm on the first later completed bar that closes through the immediately
   preceding bar's high for long or low for short.
7. Measure from the open of the next 5-minute bar.
8. Keep at most one event per symbol and session.

VWAP and RVOL are descriptive fields, not event filters or gate components.
Only the matched unconditional control is decisional. A drive-only comparator
is rejected for this version because absence of a valid pullback is not known
until the observation window expires, which is incompatible with the event's
immediate next-bar executable timestamp.

All recommendations remain subject to explicit human approval. No decision in
this memo is approved merely by being written here.

## 2. Principles Applied

The decisions use the following hierarchy:

1. Causal observability before simulated execution.
2. Algebraic symmetry between long and short.
3. Minimum parameter count.
4. Opening-auction interpretation.
5. Price- and volatility-scale invariance.
6. Exactly one event variant.
7. Deterministic reproducibility.
8. Identical rules for QQQ and SPY.
9. No dependence on First Candle, FVG, sweeps, gaps, EVENT-07, EVENT-08,
   S2/S5, or prior favorable directions.
10. Conservative all-required promotion criteria.

No event count, historical return, chart, prior favorable slice, or 2025/2026
observation informed the choices.

## 3. Blocker Decision Matrix

`DOF` is the number of event-selection or gate choices introduced by the
recommendation, not the number of output fields.

| ID | Alternatives documented | Recommended decision | Exact parameter | Information available | Lookahead risk and control | DOF | Rejected alternative |
| --- | --- | --- | --- | --- | --- | ---: | --- |
| B1 | 09:30-09:45; 09:30-10:00; variable bar count | Fixed 09:30-09:45 window | Three completed 5-minute bars | Known at 09:45 | Fixed before data; no window search | 2 | 30-minute OR-like window increases family overlap |
| B2 | Endpoint return; excursion; directional range | Close-to-open signed displacement | `(C_0945 / O_0930) - 1`; range descriptive | Three drive bars at 09:45 | No post-window extreme used for qualification | 1 | Excursion can label a rejected move as a drive |
| B3 | Historical volatility; ATR; same-window median | Previous-session ATR family | Mean TR of previous 20 approved sessions, shifted one session | Fully known before 09:30 | Current session excluded; no future normalization | 1 | Same-window median adds clock-specific estimation complexity |
| B4 | 0.25; 0.35; 0.50 normalized move | Quarter-ATR threshold | `abs(C_0945-O_0930)/ATR20 >= 0.25` | Known at 09:45 | One threshold; no grid | 1 | 0.35/0.50 have no stronger ex ante justification |
| B5 | Return sign; range location; bar-count agreement | Sign of normalized endpoint displacement | long `>= +0.25`; short `<= -0.25` | Known at 09:45 | Exact sign inversion; zero/in-between rejected | 1 | Extra close-location/bar-count filters add parameters |
| B6 | Opposing close; adverse wick; close anchor; extreme anchor | Immediate adverse wick from frozen drive extreme | First post-drive bar must retrace at least one tick; extreme frozen at 09:45 | Drive extreme known at 09:45; pullback known at first bar close | No later extreme may redefine anchor | 1 | Updating the extreme after 09:45 changes the event with later data |
| B7 | Fraction of drive; ATR depth; combined | Fraction of causal drive excursion | Maximum depth `0.50`; equality valid | Updated at each completed bar | Threshold frozen; violation permanently invalidates | 1 | ATR depth disconnects pullback from the move being tested |
| B8 | Mandatory VWAP; descriptive; excluded | Descriptive only | Causal session VWAP recorded through confirmation | Known at each completed bar | Cannot include/exclude events | 0 | Mandatory VWAP adds a redundant, ambiguous filter |
| B9 | Mandatory RVOL; descriptive; excluded | Descriptive only | 09:30-09:45 volume / prior-20-session median same-window volume | Known at 09:45 | Shifted one session; cannot filter events | 0 | Mandatory RVOL imports an unmotivated momentum filter |
| B10 | Prior-bar break; pivot break; drive-close reclaim | Prior completed bar breakout after an established pullback | Long close `>` previous bar high; short close `<` previous bar low; five-bar deadline | Known only at confirmation bar close | Execution deferred to a strictly later bar open; no same-boundary fill | 2 | Pivot/reclaim definitions add state and thresholds |
| B11 | Require all horizons; primary only; fixed cutoff | Fixed latest confirmation and primary availability | Last confirmation bar `[10:05,10:10)`; latest executable bar label/open 10:15; primary must remain in RTH | Calendar and bar availability known at execution | Confirmation at 10:15 is ineligible; no overnight | 1 | Secondary-horizon availability must not select events |
| B12 | First per session; first per direction; largest drive | Single fixed-drive candidate and at most one valid event | Maximum one event per symbol/session; earliest valid confirmation | Known causally | No comparison among later candidates | 1 | Largest drive requires later information |
| B13 | Omit; descriptive cohort; second gate | Exclude drive-only comparator from this version | No drive-only metric or gate | N/A | Absence is known only at expiry, later than many event executions | 0 | A pseudo-execution time would add landmark bias |
| B14 | Absolute contribution; positive contribution; event count | Absolute annual incremental-effect contribution | `max(abs(C_y))/sum(abs(C_y)) <= 0.70`, plus leave-one-session-out repeat | Computed only after frozen discovery | Formula fixed; negative years cannot be ignored | 1 | Positive-only denominator hides contradictory years |
| B15 | CI lower bound; tolerance; opposite-sign veto | Conservative clustered percentile bootstrap | 95% CI; 10,000 resamples; seed 20260728; lower bounds `> 0` | Uses only frozen primary event results | Session blocks preserve same-date dependence | 3 | Vague veto is not reproducible |

Every row requires human approval before it can be copied into a canonical YAML.

## 4. Recommended Complete Specification

### 4.1 Universe And Session

| Field | Value |
| --- | --- |
| Symbols | QQQ, SPY |
| Source bars | Approved curated 1-minute Alpaca SIP, future use only |
| Research bars | 5-minute bars |
| Calendar | US equity RTH |
| Timezone | `America/New_York` |
| RTH | 09:30 through 16:00, adjusted by approved early-close calendar |
| Overnight | Prohibited |
| Rules by symbol | Identical |
| Rules by direction | Algebraic sign inversion only |

Five-minute bars are half-open intervals `[bar_open, bar_end)`. A bar is
decision-available only at `bar_end`.

### 4.2 Opening Drive

Drive interval:

```text
drive_start_timestamp = session_date 09:30 America/New_York
drive_end_timestamp   = session_date 09:45 America/New_York
drive_bars            = [09:30,09:35), [09:35,09:40), [09:40,09:45)
drive_initial_price   = open of [09:30,09:35)
drive_final_price     = close of [09:40,09:45)
```

Required fields and formulas:

```text
O_D = drive_initial_price
C_D = drive_final_price
H_D = maximum high over the three drive bars
L_D = minimum low over the three drive bars

drive_return = C_D / O_D - 1
drive_range  = H_D - L_D
```

For each approved prior session `s`, compute daily RTH true range from that
session's complete approved regular-hours high and low:

```text
TR_s = max(
    session_high_s - session_low_s,
    abs(session_high_s - previous_approved_session_close_s),
    abs(session_low_s - previous_approved_session_close_s)
)
```

Normalization:

```text
ATR20_prior = arithmetic_mean(
    TR over the 20 immediately preceding sessions in the approved-session
    sequence before session_date
)

drive_displacement = C_D - O_D
drive_score = drive_displacement / ATR20_prior
```

Rules:

- `TR_s` is a daily RTH true range; premarket and after-hours prices never
  participate.
- `ATR20_prior` is the arithmetic mean, not an exponential or Wilder average.
- The feature is shifted by exactly one session: the current session never
  participates in its own ATR.
- The 20-session lookback must be complete before the current 09:30 open.
- A session excluded by an approved manifest is removed from the approved
  session sequence and never contributes high, low, close, or true range.
- The lookback walks backward to the 20 immediately preceding approved,
  complete RTH sessions. Excluded/incomplete sessions are not imputed and do
  not count toward 20.
- Computing 20 valid true ranges may require the close of an additional earlier
  approved session.
- If fewer than 20 valid prior-session true ranges are available, the current
  session and any event candidate in it are excluded.
- No rounding is applied before threshold comparison.

Direction:

```text
if drive_score >= +0.25:
    drive_direction = +1
    direction_orientation = continuation_long
    drive_extreme = H_D
elif drive_score <= -0.25:
    drive_direction = -1
    direction_orientation = continuation_short
    drive_extreme = L_D
else:
    no event candidate
```

Define:

```text
d = drive_direction
drive_excursion = d * (drive_extreme - O_D)
```

The causal drive extreme is frozen exactly at `drive_end_timestamp`:

```text
if d = +1:
    drive_extreme = maximum high observed in [09:30,09:45)
if d = -1:
    drive_extreme = minimum low observed in [09:30,09:45)
```

It is never updated during the pullback or confirmation window.
`drive_excursion` is measured from the 09:30 opening price to this frozen
extreme.

`drive_excursion` must be strictly positive. It is used only to normalize the
pullback. Qualification remains based on `drive_score`, not on intrawindow
maximum excursion.

### 4.3 Controlled Pullback

The only pullback candidate begins at 09:45, immediately after the fixed drive
window.

The first post-drive bar is `[09:45,09:50)`. It must establish the pullback:

```text
tick_size = 0.01

long_initial_adverse_move  = drive_extreme - first_pullback_bar.low
short_initial_adverse_move = first_pullback_bar.high - drive_extreme
```

For long:

- `long_initial_adverse_move >= tick_size`;
- first pullback bar high must be `<= drive_extreme`.

For short:

- `short_initial_adverse_move >= tick_size`;
- first pullback bar low must be `>= drive_extreme`.

Equality with the frozen drive extreme is allowed. A new same-direction extreme
inside the initial pullback bar invalidates the candidate because intrabar
ordering between extension and retracement is unknown.

At every completed post-drive bar through confirmation:

```text
long_pullback_depth_abs =
    drive_extreme - minimum_low_since_09_45_through_current_bar

short_pullback_depth_abs =
    maximum_high_since_09_45_through_current_bar - drive_extreme

pullback_depth_abs =
    long_pullback_depth_abs if d = +1 else short_pullback_depth_abs

pullback_depth_normalized = pullback_depth_abs / drive_excursion
```

Validity:

```text
0 < pullback_depth_normalized <= 0.50
```

- Equality at 0.50 remains valid.
- Any value greater than 0.50 permanently invalidates the candidate.
- Because the retracement is limited to half of the causal drive excursion, the
  pullback cannot cross the midpoint between the 09:30 open and drive extreme.
- No VWAP, gap, FVG, sweep, opening-range extreme, EMA, or RVOL condition can
  include or exclude the event.

### 4.4 Confirmation

The initial pullback bar can establish the pullback but cannot also confirm it.
This avoids assuming the intrabar order of high and low.

Starting with the second post-drive bar, the first bar satisfying the symmetric
rule confirms:

```text
long_confirmation:
    current_bar.close > previous_completed_bar.high

short_confirmation:
    current_bar.close < previous_completed_bar.low
```

Strict inequality is required. Equality does not confirm.

The confirmation bar remains subject to the maximum 0.50 pullback depth. Its
full OHLC is available at confirmation, but no later bar may participate in
event selection.

Observation budget:

```text
post_drive_bar_1 = [09:45,09:50)  # establish pullback only
post_drive_bar_2 = [09:50,09:55)  # first possible confirmation
post_drive_bar_3 = [09:55,10:00)
post_drive_bar_4 = [10:00,10:05)
post_drive_bar_5 = [10:05,10:10)  # last possible confirmation
```

If confirmation does not occur by the 10:10 close of bar 5, no event exists.
The bar `[10:10,10:15)` is not eligible to confirm.

### 4.5 Causal Execution Boundary

```text
confirmation_timestamp =
    end boundary of the first completed confirmation bar

executable_timestamp =
    project timestamp of the first 5-minute bar whose labeled open is
    strictly later than confirmation_timestamp

executable_price =
    raw open of that executable bar, before simulated adverse slippage
```

Project convention: 5-minute bars are labeled by their opening timestamp. The
confirmation decision becomes available at the interval end. To keep
`executable_timestamp` strictly later than that decision boundary, the bar whose
open equals the confirmation close is not executable; execution uses the next
5-minute bar label.

```text
confirmation_bar interval = [t, t + 5min)
confirmation_timestamp = t + 5min
executable_timestamp = t + 10min
```

Earliest:

```text
confirmation bar = [09:50,09:55)
confirmation_timestamp = 09:55
executable_timestamp = 10:00
```

Latest:

```text
confirmation bar = [10:05,10:10)
confirmation_timestamp = 10:10
executable_timestamp = 10:15
```

A confirmation at the 10:15 close of `[10:10,10:15)` is ineligible because its
strictly later executable timestamp would be 10:20. If the bar labeled/opened
at 10:15 does not exist, is outside the approved session, or is
manifest-invalid, the event is excluded. No substitute price, later fill,
carry, or overnight execution is allowed.

### 4.6 Deduplication

- There is one fixed opening drive per symbol/session.
- There is one pullback candidate tied to that drive.
- Maximum primary events: one per symbol/session.
- The earliest causally valid confirmation wins.
- Later confirmations are ignored.
- No separate event is allowed per direction.
- A qualifying drive has exactly one direction, so normal long/short
  simultaneity is impossible.
- If an implementation produces simultaneous opposite directions, classify the
  session as `EXCLUDED_DIRECTION_CONFLICT`; do not prioritize either side.
- A failed, invalidated, or expired pullback consumes the only candidate; no
  restart or overlapping pullback is allowed.
- "Largest drive" or "best confirmation" selection is prohibited.

## 5. Temporal Diagram

```text
09:30                 09:45       09:50       ...      10:10      10:15
  |---------------------|-----------|--------------------|-----------|
  | fixed opening drive | PB bar 1  | confirm bars 2-5   | no conf.  |
  | 3 completed 5m bars | PB needed | last closes 10:10 | exec only |
  |                     | no conf.   |                    |           |
  + drive fixed 09:45   + PB known at close              |
                                      |
                                      + confirmation decision at bar close
                                      + first strictly later 5m label executes
                                      + latest executable_timestamp = 10:15
                                      + future path measurement starts
```

No event exists before the confirmation bar closes. Prices after the
executable boundary are outcome data only.

## 6. Information Available By Timestamp

| Timestamp/state | Available | Prohibited |
| --- | --- | --- |
| Before 09:30 | Prior approved sessions, ATR20, prior same-window volumes | Current-session open, drive, pullback, future path |
| 09:30 | Current session open | Any completed drive information |
| 09:45 | Three drive bars, drive score/direction/extreme, cumulative volume, causal VWAP | Post-drive bars |
| First PB bar close | Whether initial pullback exists, depth, invalidation | Later confirmation bars |
| Each later bar close | Current depth and prior-bar confirmation predicate | Next bar open and later path |
| Confirmation boundary | Complete confirmation bar and event existence | Executable bar high/low/close |
| Executable boundary | Next bar open and executable price | Any subsequent path value for event selection |
| After execution | Horizon returns, MFE, MAE, controls | Retrospective changes to event membership |

## 7. Descriptive VWAP And RVOL

### VWAP

Policy: descriptive, non-decisional.

At drive end and confirmation:

```text
typical_price_1m = (high_1m + low_1m + close_1m) / 3

session_vwap_t =
    sum(typical_price_1m * volume_1m from 09:30 through t) /
    sum(volume_1m from 09:30 through t)
```

Only completed 1-minute bars through `t` are used. Record price distance and
drive-side relation, but neither can filter, rank, rescue, or invalidate events.

### RVOL

Policy: descriptive, non-decisional.

```text
opening_volume_current =
    sum(volume_1m from 09:30 through 09:45)

opening_volume_reference =
    median(opening_volume over the 20 most recent approved prior sessions)

opening_rvol = opening_volume_current / opening_volume_reference
```

The reference is shifted one session, requires 20 complete observations, and
uses no current-session volume. No RVOL threshold exists.

## 8. Returns, Horizons, And Costs

For event orientation `d`:

```text
event_return_h =
    d * (price_at_horizon_h / executable_price - 1)
```

Horizons:

- primary: 30 minutes from `executable_timestamp`;
- secondary descriptive: 15 minutes, 60 minutes, session close.

The primary horizon must remain in the same approved RTH session. A secondary
horizon that is unavailable in-session is marked unavailable and cannot remove
an otherwise valid event or rescue primary failure.

Cost-adjusted returns:

```text
baseline_cost =
    0.0002 + 0.02 / executable_price

stress_cost =
    0.0004 + 0.04 / executable_price

baseline_net_return =
    event_return_30min - baseline_cost

stress_net_return =
    event_return_30min - stress_cost
```

These are event-study economic comparisons, not portfolio PnL.

## 9. Controls

### Primary Matched Unconditional Control

This remains the only decisional control.

For each event and horizon, form a future control pool from valid approved
discovery timestamps matched on:

- symbol;
- calendar year;
- exact local `executable_timestamp` time-of-day on the 5-minute grid
  (`HH:MM`, for example 10:00, 10:05, 10:10, or 10:15);
- horizon.

QQQ and SPY remain separate control pools; no cross-symbol pooling or averaging
is allowed. Hour-wide or other broader time buckets are prohibited.

Exclude the event's own `session_date` from its control pool. Apply the event's
orientation `d` to control returns:

```text
control_return_j =
    d * (control_price_j_at_horizon / control_price_j_at_timestamp - 1)

unconditional_return =
    arithmetic_mean(control_return_j over the matched pool)

incremental_return =
    event_return - unconditional_return
```

Each valid timestamp is equally weighted. Controls must satisfy the same
calendar, manifest, same-session horizon, and bar-availability requirements.
No event variable other than orientation is used to select the unconditional
pool.

### Drive-Only Comparator

Decision: not included in HYP-DRIVE-PB-01.

The absence of a valid pullback cannot be known until 10:10. Many valid events
become executable before then. Assigning an earlier pseudo-executable timestamp
to the no-pullback cohort would use future knowledge; delaying all valid events
to 10:15 would change the primary question and violate immediate next-bar
execution.

Therefore:

- no drive-only comparator is computed;
- it is not a primary or secondary gate;
- it cannot be added after discovery;
- a future landmark study at a fixed 10:15 decision time would require a
  separate preregistration and hypothesis ID.

## 10. Annual Concentration

Use primary 30-minute incremental returns.

For event `i`:

```text
r_i_inc = event_return_i_30min - unconditional_return_i_30min
```

Annual contribution:

```text
C_y = sum(r_i_inc for events in year y)

annual_concentration =
    max_y(abs(C_y)) / sum_y(abs(C_y))
```

PASS requires:

```text
sum_y(abs(C_y)) > 0
annual_concentration <= 0.70
all three discovery years have valid events and valid controls
```

Treatment:

- Negative annual contributions remain in the denominator through absolute
  value; they cannot be hidden.
- If the denominator is zero, concentration FAILS.
- If only two years have valid events or controls, concentration FAILS.
- Event-count concentration is reported but is not a substitute for effect
  concentration.

Outlier veto:

1. Compute each `session_date` contribution as the sum of its event-level
   incremental returns across symbols.
2. Remove exactly one date with the largest absolute session contribution.
3. If tied, remove the earliest ISO `session_date`.
4. Recompute `C_y`, annual concentration, and each year's gross directional
   primary mean.
5. Both the original and leave-one-session-out versions must pass the 70% rule
   and must have strictly positive gross directional means in at least two of
   the three years.

The leave-one-session-out result can only veto; it cannot rescue an original
failure.

## 11. Bootstrap

Unit of resampling: unique `session_date`, pooled across QQQ and SPY.

Parameters:

```text
resamples = 10000
seed = 20260728
confidence_level = 0.95
interval_method = percentile
lower_quantile = 0.025
upper_quantile = 0.975
```

For each resample:

1. Draw the original number of unique session dates with replacement.
2. Include every event from each selected date; if a date is drawn multiple
   times, include its full block the same number of times.
3. Preserve all QQQ/SPY observations inside the session block.
4. Compute equal-event-weight primary 30-minute statistics:
   - gross directional mean;
   - mean incremental return versus unconditional control;
   - mean baseline-net return.

Boolean bootstrap PASS:

```text
lower_95_ci(gross_directional_mean) > 0
and lower_95_ci(mean_incremental_return) > 0
and lower_95_ci(mean_baseline_net_return) > 0
```

No tolerance below zero is allowed. Stress net return is evaluated by the
point-estimate gate, not as a fourth bootstrap claim.

This is a conservative research-governance rule. It is not presented as a
family-wise-error-controlled or false-discovery-rate-controlled significance
claim.

## 12. Proposed Discovery Gate

The 30-minute primary horizon passes only if every item below is true:

1. At least 150 pooled events.
2. At least 50 events for QQQ and at least 50 for SPY.
3. `continuation_long` primary mean and median are strictly positive.
4. `continuation_short` primary mean and median are strictly positive.
5. QQQ and SPY primary means are strictly positive.
6. Primary gross mean is positive in at least two of 2022, 2023, and 2024.
7. Pooled primary incremental mean versus unconditional control is strictly
   positive.
8. Pooled primary mean baseline-net return is strictly positive.
9. Pooled primary mean stress-net return is non-negative.
10. Original annual concentration is at most 0.70.
11. Leave-one-session-out annual concentration is at most 0.70.
12. Original and leave-one-session-out annual signs are positive in at least
    two of three years.
13. All three bootstrap lower-bound conditions pass.
14. No event-selection lookahead, timestamp misalignment, invalid manifest use,
    or unresolved data-quality failure exists.
15. No 2025 or historical 2026 observation, metric, count, chart, or derived
    value informed any rule.
16. The one-variant budget was respected.

Any false item yields `discovery_failed`. Secondary horizons, VWAP, RVOL, gap,
direction, symbol, month, time, or favorable diagnostic cuts cannot override
the primary failure.

## 13. Degrees Of Freedom

There is one event variant, one primary horizon, one normalization, one drive
threshold, one pullback threshold, one confirmation rule, one deadline, and one
deduplication policy.

Seventeen explicit numeric/time constants are frozen by the combined design:

| # | Constant | Value |
| ---: | --- | --- |
| 1 | Drive start | 09:30 |
| 2 | Drive end | 09:45 |
| 3 | Historical ATR lookback | 20 approved sessions |
| 4 | Minimum normalized drive | 0.25 ATR |
| 5 | Minimum initial adverse pullback | 1 tick |
| 6 | Maximum normalized pullback depth | 0.50 |
| 7 | Maximum post-drive observation | 5 five-minute bars |
| 8 | Latest confirmation/executable boundary | 10:10 / 10:15 |
| 9 | Maximum events per symbol/session | 1 |
| 10 | Primary horizon | 30 minutes |
| 11 | Minimum pooled events | 150 |
| 12 | Minimum events per symbol | 50 |
| 13 | Minimum positive discovery years | 2 of 3 |
| 14 | Maximum annual effect concentration | 0.70 |
| 15 | Bootstrap confidence level | 0.95 |
| 16 | Bootstrap resamples | 10,000 |
| 17 | Bootstrap seed | 20260728 |

The inherited discovery/validation dates, secondary horizons, tick size, and
baseline/stress costs are preserved decisions and are not counted as newly
selected parameters. VWAP and RVOL add diagnostic fields but zero decisional
degrees of freedom.

## 14. Risks

- A quarter-ATR displacement is an ex ante convention, not a known natural law.
- A 15-minute drive may still be conceptually adjacent to other opening-session
  research even though it uses no gap, OR extreme, sweep, or FVG.
- Requiring an immediate first-bar pullback is parsimonious but may exclude
  drives that extend before retracing.
- Five-minute OHLC cannot reveal intrabar high/low order; the design avoids
  same-bar pullback-and-confirmation but cannot reconstruct microstructure.
- The 50% retracement limit is interpretable but remains a human design choice.
- Excluding VWAP and RVOL from the event improves independence but weakens the
  original verbal idea that the pullback preserves VWAP.
- A stringent three-statistic bootstrap may make promotion difficult; this is
  intentional and must not be relaxed after results.
- The unconditional control depends on adequate valid timestamps in each match
  group.
- A single event per session improves dependence control but may discard later
  information.
- No formal multiple-comparison correction is claimed.

## 15. Human Approval Record

All B1-B15 decisions required approval as one indivisible specification. The
project owner has now approved the full design specification. No row was
approved selectively and no decision was reinterpreted.

Human review should focus especially on:

- the 0.25 ATR drive threshold;
- immediate first-bar pullback requirement;
- 50% maximum pullback;
- prior-bar breakout confirmation;
- removal of VWAP from the decisional rule despite the earlier conceptual
  wording;
- exclusion of the drive-only comparator;
- strict positive bootstrap lower bounds.

This approval task does not itself create canonical artifacts or authorize
historical execution. Separate tasks are still required:

- canonical YAML and final preregistration remain absent;
- no module or hypothesis tests were implemented;
- no registry row or canonical payload hash was created;
- 2022-2024 discovery remains unauthorized;
- 2025 remains blocked;
- historical 2026 remains contaminated/non-decisional;
- no strategy, paper, live, broker, orders, or sizing is permitted.

## HUMAN_APPROVAL_READINESS

| Field | Value |
| --- | --- |
| `ready_for_human_approval` | `true` |
| `blockers_remaining` | `0` |
| `total_parameters` | `17` explicit numeric/time constants |
| `decision_variants` | `1` |
| `all_B1_B15_approved` | `true` |
| `ready_for_canonical_preregistration` | `true` |
| Canonical YAML | absent |
| Final preregistration | absent |
| Python module | absent |
| Hypothesis tests | absent |
| Registry row | absent |
| Canonical payload hash | absent |

`ready_for_human_approval=true` records that the memo was precise enough for
review. Human approval has now been granted. Canonical preregistration is ready
as a separate future task, but implementation and execution remain
unauthorized.

## HUMAN_APPROVAL

```text
approval_status: approved
approved_decisions: B1-B15
approval_scope: full_design_specification
approved_by: project_owner
approval_date: 2026-07-28
parameters_frozen: 17
decision_variants: 1
ready_for_canonical_preregistration: true
blockers_remaining: 0
```

The approval explicitly includes:

- opening drive from 09:30 through 09:45;
- displacement equal to the 09:45 close minus the 09:30 open;
- daily RTH ATR20 shifted by one session;
- absolute threshold of 0.25 ATR20;
- algebraic long/short symmetry;
- causal drive extreme frozen at 09:45;
- minimum pullback of one tick;
- maximum pullback depth of 50%;
- five eligible post-drive bars;
- last causal confirmation at 10:10;
- last executable timestamp at 10:15;
- maximum one event per symbol and session;
- VWAP and RVOL as descriptive, non-decisional fields;
- unconditional control matched on exact `HH:MM`;
- no drive-only comparator;
- annual concentration limit of 70%;
- session-clustered bootstrap with 10,000 resamples and seed 20260728;
- discovery gate with 16 mandatory conditions;
- primary horizon of 30 minutes;
- validation 2025 blocked;
- historical 2026 contaminated and non-decisional.

The commit that contains this approved document will be the conceptual design
freeze commit. Its SHA must not be invented inside the document before that
commit is made.

## 16. No-Data Confirmation

This memo was produced from governance and conceptual documents only.

- No OHLC file was opened.
- No dataset manifest was opened.
- No event count was calculated.
- No historical return was calculated.
- No prior result was used to choose a parameter.
- No 2025 or 2026 data was opened.
- No backtest, discovery, validation, or holdout was executed.

## Final Decision Table

| decision_id | decision | recommended_value | human_approval_required | approved | notes |
| --- | --- | --- | --- | --- | --- |
| B1 | Opening drive window | 09:30-09:45 ET; three completed 5-minute bars | true | true | Fixed opening auction window |
| B2 | Drive displacement | Signed 09:45 close minus 09:30 open; return also recorded | true | true | Intrawindow range descriptive |
| B3 | Normalization | Arithmetic mean of daily RTH true range for the 20 immediately preceding approved sessions; shifted one session | true | true | Current session excluded; manifest-excluded sessions omitted; fewer than 20 excludes event |
| B4 | Minimum drive | Absolute displacement at least 0.25 ATR20 | true | true | Equality qualifies |
| B5 | Direction | Long at score >= +0.25; short at score <= -0.25 | true | true | Exact algebraic symmetry |
| B6 | Pullback start/anchor | First post-drive bar; long uses 09:30-09:45 maximum, short uses minimum, both frozen at 09:45 | true | true | Excursion starts at 09:30 open; extreme never updates |
| B7 | Pullback depth | At least 1 tick and at most 50% of drive excursion | true | true | Equality at 50% valid |
| B8 | VWAP | Descriptive only | true | true | Cannot filter or gate |
| B9 | RVOL | Descriptive 09:30-09:45 RVOL using prior-20 median | true | true | No threshold |
| B10 | Confirmation | First later close beyond previous bar high/low; maximum five post-drive bars | true | true | Last eligible confirmation bar is `[10:05,10:10)` |
| B11 | Timing cutoff | Last confirmation close 10:10; latest executable timestamp/bar label 10:15 | true | true | A 10:15 close is ineligible; missing 10:15 bar excludes; no overnight |
| B12 | Deduplication | Earliest valid event; maximum one per symbol/session | true | true | No restart after failure |
| B13 | Drive-only comparator | Excluded from this hypothesis | true | true | Separate landmark study required |
| B14 | Annual concentration | Max absolute annual incremental contribution share <= 70%, original and leave-one-session-out | true | true | All three years required |
| B15 | Bootstrap | Session cluster; percentile 95%; 10,000; seed 20260728; three lower bounds > 0 | true | true | Governance gate, not multiplicity-corrected significance |
