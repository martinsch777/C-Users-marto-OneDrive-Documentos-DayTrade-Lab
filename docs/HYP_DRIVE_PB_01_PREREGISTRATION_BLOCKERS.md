# HYP-DRIVE-PB-01 Preregistration Blockers

Audit date: 2026-07-28

Proposed hypothesis: `HYP-DRIVE-PB-01`

Conceptual name: Opening Drive + Controlled Pullback Continuation

Decision: **material blockers found; canonical preregistration stopped**.

This report follows the ambiguity policy for HYP-DRIVE-PB-01. The internal
sources do not define every decision-bearing event parameter or every numeric
gate rule. Choosing those values now without an explicit human research
decision would create an arbitrary historical specification and expose the
project to data snooping.

Accordingly, this task did not create:

- `configs/research/hypotheses/HYP-DRIVE-PB-01.yaml`;
- `docs/HYP_DRIVE_PB_01_PREREGISTRATION.md`;
- `src/research/hyp_drive_pb_01.py`;
- `tests/test_hyp_drive_pb_01.py`;
- a registry row;
- a canonical payload hash.

No historical or real OHLC was read or executed.

## Sources Audited

Primary:

- `docs/NEXT_RESEARCH_PRIORITY.md`
- `docs/RESEARCH_HYPOTHESIS_REGISTRY.md`
- `docs/INTRADAY_HYPOTHESIS_REFINEMENT_PROTOCOL.md`

Supporting governance and comparison sources:

- `configs/research/hypotheses/HYP-FCR-01.yaml`
- `configs/research/hypotheses/HYP-OR-CONT-EVENT-01.yaml`
- `configs/research/hypotheses/HYP-GAP.yaml`
- `configs/research/hypotheses/QQQ-S2-S5-COMBO.yaml`
- `docs/HYP_OR_CONT_EVENT_01_PREREGISTRATION.md`
- `docs/HYP_GAP_EVENT_STUDY_SPEC.md`
- `docs/QQQ_S2_S5_COMBO_RESEARCH_RESULTS.md`
- `docs/OR_FVG_BASE_RESEARCH_SUMMARY.md`
- `docs/DAYTRADE_LAB.md`
- `docs/DAYTRADE_REAL_DATA_VALIDATION.md`

The prior hypotheses were read only to establish governance boundaries,
canonical costs, and conceptual non-duplication. Their favorable or unfavorable
results were not used to select HYP-DRIVE-PB-01 parameters.

## Requirements Already Defined

The following items are sufficiently explicit and do not require a new
research choice:

| Field | Frozen source requirement |
| --- | --- |
| Research type | Event study only; not a strategy |
| Symbols | QQQ and SPY, both mandatory |
| Source data | Approved local curated Alpaca SIP raw-adjusted 1-minute data and manifests |
| Research bars | Causal 5-minute RTH bars |
| Calendar | US equity RTH, `America/New_York` |
| Discovery | 2022-01-01 through 2024-12-31 |
| Validation | 2025-01-01 through 2025-12-31, blocked until discovery passes and separate authorization exists |
| Historical 2026 | Contaminated/non-decisional and blocked |
| Forward shadow | May begin only after a future commit freezes preregistration and implementation |
| Primary horizon | 30 minutes from `executable_timestamp` |
| Secondary horizons | 15 minutes, 60 minutes, session close; descriptive only |
| Primary control | Matched by symbol, year, executable-time hour bucket, and horizon |
| Primary control metrics | `event_return`, `unconditional_return`, `incremental_return` |
| Baseline costs | Commission 0.0001 per side and 1 tick slippage per execution |
| Baseline round trip | `0.0002 + 0.02 / executable_price` |
| Stress costs | Commission 0.0002 per side and 2 ticks slippage per execution |
| Stress round trip | `0.0004 + 0.04 / executable_price` |
| Minimum sample | At least 150 pooled events and at least 50 per symbol |
| Expected orientation | Positive same-drive-direction return for both continuation_long and continuation_short |
| Annual sign | Expected sign in at least two of the three discovery years |
| Annual concentration threshold | No more than 70%, subject to unresolved denominator definition below |
| Variant budget | One primary event definition and zero historical variants |
| Safety | No strategy, sizing, PnL curve, paper/live trading, broker, or orders |

The canonical cost source was verified in
`configs/research/hypotheses/HYP-FCR-01.yaml`. The same values and round-trip
formulas are also documented in the HYP-OR-CONT preregistration. Other strategy
configs contain strategy-specific cost profiles, but
`docs/NEXT_RESEARCH_PRIORITY.md` explicitly selects the FCR profile for this
proposed event study; therefore costs are not a blocker.

## Material Blockers

Every item below affects event inclusion or the primary PASS/FAIL decision.
None has a unique answer in the audited sources.

### B1. Opening Drive Window

Undefined: exact start and end timestamps used to form the drive.

Reasonable alternatives:

- 09:30 through the 09:45 close;
- 09:30 through the 10:00 close;
- first two, three, or another fixed number of completed 5-minute bars.

Methodological risk: changing the window changes both event frequency and
directional strength. Selecting it after examining 2022-2024 would be a direct
time-window search. HYP-GAP-03 used information through 09:45 and prior OR work
used 09:30-10:00, but neither value may be imported silently because both
families have observed results and different causal definitions.

Required decision: one fixed RTH start and one fixed completed-bar end.

### B2. Drive Displacement Formula

Undefined: whether the drive is measured by endpoint return, close-to-extreme
excursion, high-low range, signed true range, or a combination.

Reasonable alternatives:

- signed return from the 09:30 open to the drive-end close;
- signed maximum favorable excursion from the 09:30 open within the window;
- signed close displacement plus a required close-location fraction;
- directional range conditioned on the drive-end close.

Methodological risk: excursion-based definitions can label a rejected move as a
drive, while endpoint definitions can ignore strong intrawindow pressure.
Testing several formulas would create unlogged variants.

Required decision: exact algebraic formula, equality policy, and the role of
`drive_return` versus `drive_range`.

### B3. Drive Normalization Measure

Undefined: the protocol permits ATR or realized volatility, but no source
selects one or defines its lookback.

Reasonable alternatives:

- previous 20 approved RTH sessions' ATR, excluding the current session;
- causal realized volatility from a fixed number of prior approved sessions;
- causal rolling intraday volatility available before the drive starts.

Opening-range width is not an acceptable silent choice because it would increase
dependence on the closed OR family.

Methodological risk: normalization changes event membership and cross-symbol
comparability. Choosing the measure or lookback after seeing event counts or
returns is parameter selection.

Required decision: measure, lookback, warmup, missing-session policy, and
whether the current session is excluded.

### B4. Minimum Drive Magnitude

Undefined: no numeric normalized-drive threshold exists.

Reasonable alternatives include a single fixed fraction such as 0.25, 0.35, or
0.50 of the selected normalization measure. These are examples of the decision
surface, not recommendations.

Methodological risk: lower thresholds increase sample size and noise; higher
thresholds reduce sample size and can concentrate results in volatile periods.
The 0.35 value in HYP-GAP-03 belongs to a gap-conditioned study and cannot be
reused as evidence for this independent event.

Required decision: exactly one threshold, inclusive/exclusive comparison, and
tick/rounding policy.

### B5. Operational Drive Direction

Undefined: long and short are conceptually symmetric, but the exact direction
rule is absent.

Reasonable alternatives:

- positive/negative drive-end return;
- return sign plus close in a fixed fraction of the drive range;
- return sign plus a minimum number of same-direction closes.

Methodological risk: adding close-location or bar-count confirmation changes
the event and introduces more parameters. Direction must not be chosen from
which side performed better in prior work.

Required decision: one algebraically symmetric sign rule and tie/zero policy.

### B6. Pullback Start And Reference Extreme

Undefined: when the pullback starts and which price defines the completed drive
extreme.

Reasonable alternatives:

- first opposing 5-minute close after the fixed drive window;
- first bar whose low/high moves against the drive;
- pullback measured from the most extreme high/low established by the drive-end
  timestamp;
- pullback measured from the drive-end close.

Methodological risk: using a later extreme can improve apparent structure with
hindsight. A pullback cannot be anchored to an extreme known only after the
candidate pullback begins.

Required decision: causal anchor, start trigger, and whether wicks or closes
control the trigger.

### B7. Pullback Depth Formula And Maximum

Undefined: exact depth formula and maximum allowed retracement.

Reasonable alternatives:

- retracement as a fraction of signed opening-drive displacement;
- pullback distance divided by the selected ATR/volatility measure;
- both, with one primary and the other descriptive.

Possible maximums such as one-third, one-half, or two-thirds of the drive are
not interchangeable and are not recommendations.

Methodological risk: pullback depth is the central hypothesis parameter.
Selecting the most favorable depth is precisely the retrospective optimization
this preregistration is intended to prevent.

Required decision: formula, maximum, equality policy, and invalidation level.

### B8. VWAP Preservation Semantics

The primary recommendation says the pullback preserves session VWAP, but does
not define preservation.

Reasonable alternatives:

- every pullback close remains on the drive side of causal session VWAP;
- pullback wicks may cross VWAP but closes may not;
- only the confirmation close must be on the drive side of VWAP;
- a fixed tick or volatility-scaled tolerance around VWAP.

Methodological risk: wick-versus-close and tolerance choices materially change
event count. A tolerance creates another tunable parameter.

Required decision: exact comparison, equality/touch policy, VWAP calculation
through which completed bar, and whether any tolerance is allowed.

### B9. Relative Volume Policy

The protocol requires a relative-volume condition and the priority document
says the RVOL policy must be frozen, but neither says whether RVOL is mandatory,
what threshold applies, or how it is calculated.

Reasonable alternatives:

- no RVOL filter, with RVOL recorded only as a diagnostic;
- minimum causal RVOL at drive end;
- minimum causal RVOL at confirmation;
- cumulative opening volume relative to the same clock interval over prior
  approved sessions.

Methodological risk: RVOL has been used in prior momentum and crypto research.
Importing a favorable threshold would compromise independence; adding it as a
filter also reduces sample size and expands the parameter surface.

Required decision: filter versus diagnostic, formula, lookback, timestamp, and
threshold if decisional.

### B10. Pullback End, Confirmation Rule, And Deadline

Undefined: what confirms continuation potential and when an unconfirmed
pullback expires.

Reasonable alternatives:

- first same-direction close above/below the prior completed bar;
- first close through the pullback's causal countertrend pivot;
- first close that reclaims the drive-end close;
- fixed number of pullback bars followed by a directional confirmation close.

Methodological risk: stronger confirmation usually reduces sample size while
moving the executable timestamp later. Trying several confirmation rules or
deadlines is a variant search.

Required decision: confirmation predicate, maximum pullback bars,
confirmation deadline, and treatment of a new drive extreme before
confirmation.

### B11. Maximum Signal Time And Horizon Availability

Undefined: latest permissible `confirmation_timestamp` or
`executable_timestamp`.

Reasonable alternatives:

- require all primary and secondary horizons to be available before session
  close;
- require only the 30-minute primary horizon and mark later secondary horizons
  unavailable;
- impose a fixed latest executable time.

Methodological risk: a late cutoff changes the time-of-day distribution and
event count. Requiring secondary horizons can unintentionally make descriptive
horizons decisional.

Required decision: latest confirmation/execution time and exact same-session
horizon availability rule, including early-close sessions.

### B12. Deduplication And Overlap

Undefined:

- maximum events per symbol/session;
- priority between long and short candidates;
- simultaneous-signal policy;
- consecutive-drive policy;
- overlapping-pullback policy.

Reasonable alternatives:

- first causally valid event per symbol/session, independent of side;
- one event per direction per symbol/session;
- earliest drive wins and later/overlapping candidates are ignored;
- invalidate simultaneous opposite signals rather than prioritize a side.

Methodological risk: multiple events from one session break independence and can
overweight volatile days. Side-priority rules can create long/short asymmetry.
The first-event rule used elsewhere is simple, but
`docs/NEXT_RESEARCH_PRIORITY.md` does not explicitly adopt it for this
hypothesis.

Required decision: all five policies, with algebraic long/short symmetry.

### B13. Drive-Only Comparator

The matched unconditional control is defined. The recommended additional
comparator, "opening drive without valid pullback", is not.

Undefined:

- whether it is decisional or descriptive;
- what timestamp is assigned when no pullback confirms;
- how its event time is matched to a confirmed pullback event;
- whether failed/invalidation pullbacks are included;
- whether drives are sampled once per session.

Reasonable alternatives:

- omit it from the gate and document it as future non-decisional analysis;
- include a descriptive drive-only cohort frozen before discovery;
- make it decisional only after defining an exact pseudo-executable timestamp
  and matching rule.

Methodological risk: a comparator assembled after event outcomes are known can
be selected to improve incremental return. A no-pullback event does not have a
natural confirmation timestamp, so matching is not mechanical.

Required decision: exact cohort, timestamp, matching, and decisional status.

### B14. Annual Concentration Formula

The threshold is known (70%), but the denominator is not.

Reasonable alternatives:

- largest positive year's contribution divided by the sum of positive annual
  contributions;
- largest year's event-weighted contribution divided by pooled positive effect;
- concentration of total gross event return rather than mean effect.

Methodological risk: the formulas behave differently when one year is negative
or event counts differ. Choosing the denominator after seeing annual results
can flip PASS/FAIL.

Required decision: exact numerator, denominator, weighting, and behavior when
aggregate or annual contributions are non-positive.

### B15. Session-Clustered Bootstrap Rule

Undefined:

- confidence level;
- number of resamples;
- deterministic seed;
- whether sessions are clustered jointly across symbols;
- statistic bootstrapped;
- exact meaning of "not strongly contradictory";
- PASS/FAIL boundary and tolerance.

Reasonable alternatives:

- require the 95% CI lower bound of primary mean return to be non-negative;
- require the 95% CI lower bound of incremental return to be non-negative;
- permit a fixed lower-bound tolerance while treating the gate as governance,
  not formal significance;
- use bootstrap only as a veto when the CI is wholly opposite the expected
  sign.

Methodological risk: "not strongly contradictory" is not reproducible. Different
bootstrap targets and boundaries can change the gate result.

Required decision: all bootstrap parameters and one exact Boolean gate rule.

## Confirmation And Executable Timestamp

The event-specific confirmation predicate is blocked by B10. Once that
predicate is selected, the sources sufficiently support this causal timing:

- `confirmation_timestamp` is the close timestamp of the completed 5-minute bar
  that first satisfies the frozen confirmation predicate;
- the event does not exist before that close;
- `executable_timestamp` is the opening timestamp of the next available
  same-session 5-minute bar;
- `executable_price` is that bar's open before simulated adverse slippage;
- `executable_timestamp` must be strictly later than
  `confirmation_timestamp`;
- prices after `executable_timestamp` may measure paths but cannot select the
  event.

This timing cannot become canonical until the confirmation predicate and latest
signal time are resolved.

## Metrics That Can Be Preregistered After Resolution

The requested metric set is not itself a blocker:

- event and session counts;
- mean and median same-direction return;
- directional win rate;
- MFE and MAE;
- session-date-clustered bootstrap CI;
- results by symbol, year, and long/short orientation;
- annual concentration;
- horizon availability;
- incremental return versus control;
- gross return minus baseline and stress costs;
- fraction of events whose return exceeds baseline and stress costs.

No portfolio PnL, entries/exits, stops, targets, sizing, or strategy equity curve
is permitted.

## Primary Gate After Blocker Resolution

The non-ambiguous part of the future all-required 30-minute gate is:

1. `continuation_long` mean and median have positive expected sign.
2. `continuation_short` mean and median have positive expected sign.
3. QQQ and SPY primary means have positive expected sign.
4. The expected sign is present in at least two of the three discovery years.
5. Pooled event count is at least 150 and each symbol has at least 50 events.
6. Incremental mean versus the matched unconditional control is positive.
7. Mean return exceeds baseline round-trip cost.
8. Stress-cost result is non-negative.
9. No lookahead, timestamp misalignment, manifest violation, or 2025/2026
   contamination exists.
10. Secondary horizons cannot override any primary failure.

Annual concentration cannot become executable until B14 is resolved. The
bootstrap criterion cannot become executable until B15 is resolved.

## Multiple Comparisons

The allowed research budget is one event variant. There is no parameter grid.

Decision-bearing combinations would be limited to:

- two orientations: continuation_long and continuation_short;
- two symbols: QQQ and SPY;
- three discovery years: 2022, 2023, 2024;
- one primary horizon: 30 minutes.

The 15-minute, 60-minute, and session-close horizons are descriptive and cannot
rescue the primary result. Pooled, symbol, orientation, and annual checks are
mandatory gate components, not separately selectable hypotheses.

No formal family-wise-error or false-discovery-rate method is specified in the
internal sources. Under the task instruction, the future gate must therefore be
described as a conservative research-governance rule, not as a formal claim of
multiplicity-corrected statistical significance. The bootstrap ambiguity in
B15 still requires a numeric decision before canonical preregistration.

## Required Human Decisions

A single approved specification must resolve B1 through B15 without consulting
2022-2024, 2025, or 2026 OHLC, event counts, returns, or charts. The decisions
should be motivated by auction mechanics, causal observability, and operational
simplicity.

After those decisions are recorded, a new task may create the YAML,
preregistration document, validation-only Python module, synthetic tests,
canonical payload hash, and one registry row in state
`preregistered_not_executed`.

Until then:

- 2022-2024 discovery is not authorized;
- 2025 validation remains closed;
- historical 2026 remains contaminated and non-decisional;
- no shadow-forward period has begun;
- no strategy, orders, sizing, paper, or live transition is authorized.
