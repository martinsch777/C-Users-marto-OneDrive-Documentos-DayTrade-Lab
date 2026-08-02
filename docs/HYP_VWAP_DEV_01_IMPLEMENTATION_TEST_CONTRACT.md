# HYP-VWAP-DEV-01 Implementation Test Contract

```text
hypothesis_id: HYP-VWAP-DEV-01
test_contract_status: approved_for_implementation
classification: PLAN_READY
human_approved: true
tests_implemented: false
real_data_used: false
historical_data_used: false
implementation_allowed: true
historical_data_access_allowed: false
discovery_execution_allowed: false
blockers_remaining: 0
preregistration_metadata_commit: 236ca1c6c83695962b51f4ed67b57898130d8f6e
amendment_id: HYP-VWAP-DEV-01-AMD-01
canonical_payload_sha256: 8420c66ffb97da893a9dcd3ebbc4903af116a4104891204397f554a0d12118eb
specified_test_cases: 202
```

## Contract Rules

Every case below is synthetic or structural. No fixture may copy a historical
price, timestamp sequence, event count, or return. Production constants remain
frozen even when a dependency is injected to make a unit test small.

Table columns implement the required case schema:

- `src`: normative source and YAML path.
- `target`: target function or runner stage.
- `fixture`: synthetic fixture.
- `action`: operation under test.
- `expected`: required result.
- `failure`: required diagnostic if the expectation is violated.
- `sel`, `time`, `gate`: selection-, timing-, and gate-affecting booleans.
- `req`: required before implementation freeze.

Where a compact table uses `fixture/action`, the cell contains the synthetic
fixture mutation and the action together. The default action is `evaluate` for
GAT, PRO, CON, and LOO cases, `invoke runner or stage` for RUN cases, and
`inspect structure and outputs` for SEC cases unless the cell names a more
specific action. Thus every row has an explicit or category-defined action.

## Synthetic Fixture Catalog

| fixture_id | description |
| --- | --- |
| FX-GOV | Minimal exact frozen config mapping and controlled mutations |
| FX-NORMAL | Synthetic 09:30-16:00 QQQ/SPY RTH minute session |
| FX-EARLY | Synthetic calendar session with 13:00 close |
| FX-LONG | Negative breach, immediate valid confirmation, executable long |
| FX-SHORT | Positive breach, immediate valid confirmation, executable short |
| FX-EQUAL | Exact +/-0.005 threshold boundary bars |
| FX-CONF-FAIL | First breach followed by invalid immediate confirmation |
| FX-CROSS | Confirmed event whose execution open reaches/crosses VWAP |
| FX-ZERO | Zero cumulative volume followed by positive and zero-volume bars |
| FX-CLUSTER | QQQ and SPY events sharing synthetic session dates |
| FX-STABLE | Three synthetic years, all groups sufficient and stable |
| FX-CONCENTRATED | One synthetic year contributes over 70 percent |
| FX-LOO | Largest-date removal changes concentration/stability |
| FX-LOO-TIE | Two dates tie in absolute incremental contribution |
| FX-ALL-PASS | Synthetic metrics satisfying all 25 substantive criteria |
| FX-ONE-FAIL | Parameterized copy of FX-ALL-PASS with one criterion failing |
| FX-RUNNER | Temporary repository/filesystem with mocked Git/data openers |

## Governance And Preregistration Cases

| test_id | category | src | target | fixture | action | expected | failure | sel | time | gate | req |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| GOV-01 | governance | config root | `load_frozen_config` | FX-GOV | parse YAML | mapping accepted | `YAML_NOT_PARSEABLE` | no | no | yes | yes |
| GOV-02 | governance | `duplicate_keys_allowed=false` | strict loader | duplicate key | parse | reject | `DUPLICATE_YAML_KEY` | yes | yes | yes | yes |
| GOV-03 | governance | `canonical_payload` | hash validator | FX-GOV | serialize/hash | exact amended canonical hash | `CANONICAL_HASH_MISMATCH` | no | no | yes | yes |
| GOV-04 | governance | `canonical_payload_sha256` | hash validator | one leaf changed | validate | reject | `CANONICAL_HASH_MISMATCH` | yes | yes | yes | yes |
| GOV-05 | governance | conceptual freeze | config validator | wrong conceptual SHA | validate | reject | `CONCEPTUAL_FREEZE_MISMATCH` | no | no | yes | yes |
| GOV-06 | governance | clarification freeze | config validator | wrong clarification SHA | validate | reject | `CLARIFICATION_FREEZE_MISMATCH` | no | no | yes | yes |
| GOV-07 | governance | external prereg freeze | runner preflight | wrong expected SHA | validate | reject before data open | `PREREGISTRATION_FREEZE_MISMATCH` | no | no | yes | yes |
| GOV-08 | governance | `methodology_frozen=true` | config validator | false mutation | validate | reject | `METHODOLOGY_NOT_FROZEN` | no | no | yes | yes |
| GOV-09 | governance | `preregistration_frozen=true` | config validator | false mutation | validate | reject | `PREREGISTRATION_NOT_FROZEN` | no | no | yes | yes |
| GOV-10 | governance | implementation state | mode validator | both modes | validate | validation allowed; discovery requires separate auth | `MODE_NOT_AUTHORIZED` | no | no | yes | yes |
| GOV-11 | governance | `decision_variants=1` | config validator | 0/2 mutations | validate | reject both | `VARIANT_BUDGET_MISMATCH` | yes | no | yes | yes |
| GOV-12 | governance | `validation_2025.unlocked=false` | config validator | true mutation | validate | reject | `VALIDATION_2025_UNLOCKED` | yes | yes | yes | yes |
| GOV-13 | governance | `historical_2026.decisional=false` | config validator | true mutation | validate | reject | `HISTORICAL_2026_DECISIONAL` | yes | yes | yes | yes |
| GOV-14 | governance | `safety_flags` | config validator | each flag true in turn | validate | reject every mutation | `SAFETY_FLAG_TRUE` | no | no | yes | yes |
| GOV-15 | governance | aliases/schema | config validator | alias/type mismatch | validate | reject | `CONFIG_SCHEMA_MISMATCH` | yes | yes | yes | yes |

## Resample And VWAP Cases

| test_id | category | src | target | fixture | action | expected | failure | sel | time | gate | req |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| RSM-01 | resample | `causal_resample.aggregation` | resampler | FX-NORMAL first five rows | aggregate | first/max/min/last/sum exact | `OHLCV_AGGREGATION_ERROR` | yes | yes | yes | yes |
| RSM-02 | resample | complete contiguous five rows | resampler | four-minute bucket | aggregate | bucket absent and dependent event invalid | `INCOMPLETE_BUCKET_ACCEPTED` | yes | yes | yes | yes |
| RSM-03 | resample | gap policy | resampler | minute 3 missing | aggregate | reject bucket | `GAPPED_BUCKET_ACCEPTED` | yes | yes | yes | yes |
| RSM-04 | resample | early closes/calendar | resampler | FX-EARLY | aggregate | no bucket after 13:00 | `EARLY_CLOSE_IGNORED` | yes | yes | yes | yes |
| RSM-05 | resample | timezone/RTH | resampler | aware NY/UTC equivalents | aggregate | same bars and NY session dates | `TIMEZONE_SESSION_ERROR` | yes | yes | yes | yes |
| VWP-01 | VWAP | typical price formula | VWAP calculator | one synthetic bar | calculate | `(H+L+C)/3` exact | `TYPICAL_PRICE_ERROR` | yes | no | yes | yes |
| VWP-02 | VWAP | cumulative numerator/denominator | VWAP calculator | three bars | calculate | hand-computed sequence | `VWAP_CUMULATION_ERROR` | yes | yes | yes | yes |
| VWP-03 | VWAP | current bar included | VWAP calculator | current bar extreme | calculate | current bar changes VWAP | `CURRENT_BAR_EXCLUDED` | yes | yes | yes | yes |
| VWP-04 | VWAP | reset each session | VWAP calculator | two sessions | calculate | second session independent | `VWAP_NOT_RESET` | yes | yes | yes | yes |
| VWP-05 | VWAP | cumulative volume zero | VWAP calculator | FX-ZERO prefix | calculate | VWAP undefined; no candidate | `ZERO_VOLUME_VWAP_DEFINED` | yes | yes | yes | yes |
| VWP-06 | VWAP | individual zero after positive | VWAP calculator | FX-ZERO suffix | calculate | prior VWAP unchanged | `ZERO_INCREMENT_CHANGED_VWAP` | yes | yes | yes | yes |
| VWP-07 | VWAP | no future/forward fill | VWAP calculator | mutate future/next session | recalculate prefix | prior values unchanged and no cross-session fill | `VWAP_LOOKAHEAD_OR_FILL` | yes | yes | yes | yes |

## Threshold And Window Cases

| test_id | category | src | target | fixture | action | expected | failure | sel | time | gate | req |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| THR-01 | threshold | long `<-0.005` | candidate detector | deviation -0.0051 | detect | long candidate | `LONG_BREACH_MISSED` | yes | no | yes | yes |
| THR-02 | threshold | equality excluded | candidate detector | deviation -0.005 | detect | no candidate | `LONG_EQUALITY_BREACH` | yes | no | yes | yes |
| THR-03 | threshold | short `>0.005` | candidate detector | deviation 0.0051 | detect | short candidate | `SHORT_BREACH_MISSED` | yes | no | yes | yes |
| THR-04 | threshold | equality excluded | candidate detector | deviation 0.005 | detect | no candidate | `SHORT_EQUALITY_BREACH` | yes | no | yes | yes |
| THR-05 | window | earliest 10:00 inclusive | candidate detector | breach close 10:00 | detect | eligible | `EARLIEST_BOUNDARY_REJECTED` | yes | yes | yes | yes |
| THR-06 | window | before 10:00 excluded | candidate detector | breach close 09:55 | detect | excluded | `PRE_WINDOW_BREACH_ACCEPTED` | yes | yes | yes | yes |
| THR-07 | window | regular latest 14:55 | candidate detector | breach close 14:55 | detect | eligible | `LATEST_BREACH_REJECTED` | yes | yes | yes | yes |
| THR-08 | window | close-65m | candidate detector | breach close 15:00 | detect | excluded | `POST_WINDOW_BREACH_ACCEPTED` | yes | yes | yes | yes |
| THR-09 | window | latest execution 15:00 | state machine | 14:55 breach | execute | 15:00 open eligible | `LATEST_EXECUTION_REJECTED` | yes | yes | yes | yes |
| THR-10 | window | dynamic early close | state machine | FX-EARLY 11:55 breach | execute | 12:00 open eligible | `EARLY_CLOSE_WINDOW_ERROR` | yes | yes | yes | yes |
| THR-11 | window | inclusive boundaries | detector | exact earliest/latest | detect | both eligible | `INCLUSIVE_BOUNDARY_ERROR` | yes | yes | yes | yes |
| THR-12 | window | insufficient session | detector | session shorter than horizons | detect | no eligible event | `SHORT_SESSION_ACCEPTED` | yes | yes | yes | yes |

## Event Formation Cases

| test_id | category | src | target | fixture | action | expected | failure | sel | time | gate | req |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| EVT-01 | event | orientation | state machine | FX-LONG/FX-SHORT | detect | long below, short above | `ORIENTATION_ERROR` | yes | no | yes | yes |
| EVT-02 | event | immediate confirmation | confirmer | FX-LONG | confirm | confirmed | `VALID_CONFIRMATION_REJECTED` | yes | yes | yes | yes |
| EVT-03 | event | immediate only | confirmer | valid second later bar | confirm | failed session | `LATE_CONFIRMATION_ACCEPTED` | yes | yes | yes | yes |
| EVT-04 | event | same VWAP side | confirmer | opposite-side close | confirm | fail | `OPPOSITE_SIDE_CONFIRMED` | yes | yes | yes | yes |
| EVT-05 | event | abs deviation smaller | confirmer | smaller deviation | confirm | pass | `SMALLER_DEVIATION_REJECTED` | yes | yes | yes | yes |
| EVT-06 | event | strict smaller | confirmer | equal deviation | confirm | fail | `EQUAL_DEVIATION_CONFIRMED` | yes | yes | yes | yes |
| EVT-07 | event | no VWAP crossing | confirmer | close at/across VWAP | confirm | fail | `CONFIRMATION_CROSS_ACCEPTED` | yes | yes | yes | yes |
| EVT-08 | event | no more extreme | confirmer | larger abs deviation | confirm | fail | `MORE_EXTREME_CONFIRMED` | yes | yes | yes | yes |
| EVT-09 | event | failed confirmation invalidates | state machine | FX-CONF-FAIL | scan session | no event | `FAILED_SESSION_REOPENED` | yes | yes | yes | yes |
| EVT-10 | event | first breach only | state machine | two breaches | scan | first is sole candidate | `SECOND_CANDIDATE_USED` | yes | yes | yes | yes |
| EVT-11 | event | no rescan | state machine | first fails, later valid | scan | no event | `RESCAN_OCCURRED` | yes | yes | yes | yes |
| EVT-12 | event | no opposite substitute/reentry | state machine | later opposite breach | scan | no event | `OPPOSITE_OR_REENTRY_USED` | yes | yes | yes | yes |
| EVT-13 | event | max one per symbol-session | state machine | many valid-looking bars | scan | at most one | `MULTIPLE_SESSION_EVENTS` | yes | yes | yes | yes |

## Execution Cases

| test_id | category | src | target | fixture | action | expected | failure | sel | time | gate | req |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| EXE-01 | execution | long below VWAP | executor | open below | evaluate | execute | `VALID_LONG_CANCELED` | yes | yes | yes | yes |
| EXE-02 | execution | long equality | executor | open equal | evaluate | cancel | `LONG_EQUALITY_EXECUTED` | yes | yes | yes | yes |
| EXE-03 | execution | long above | executor | open above | evaluate | cancel | `LONG_CROSS_EXECUTED` | yes | yes | yes | yes |
| EXE-04 | execution | short above VWAP | executor | open above | evaluate | execute | `VALID_SHORT_CANCELED` | yes | yes | yes | yes |
| EXE-05 | execution | short equality | executor | open equal | evaluate | cancel | `SHORT_EQUALITY_EXECUTED` | yes | yes | yes | yes |
| EXE-06 | execution | short below | executor | open below | evaluate | cancel | `SHORT_CROSS_EXECUTED` | yes | yes | yes | yes |
| EXE-07 | execution | timestamp identity/bar distinction | state machine | contiguous bars | inspect | same instant, distinct bars | `BAR_IDENTITY_COLLAPSED` | yes | yes | yes | yes |
| EXE-08 | execution | price is exact open | executor | distinctive OHLC | execute | open selected | `WRONG_EXECUTION_PRICE` | yes | yes | yes | yes |
| EXE-09 | execution | prior completed VWAP | executor | future execution volume extreme | execute | VWAP unchanged | `EXECUTION_BAR_LOOKAHEAD` | yes | yes | yes | yes |
| EXE-10 | execution | no execution volume pre-open | executor | mutate execution volume | execute | decision unchanged | `PREOPEN_VOLUME_USED` | yes | yes | yes | yes |
| EXE-11 | execution | cancel means no rescan | state machine | FX-CROSS plus later breach | scan | no event | `CANCELED_SESSION_REOPENED` | yes | yes | yes | yes |

## Horizon, Return, And Cost Cases

| test_id | category | src | target | fixture | action | expected | failure | sel | time | gate | req |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| PTH-01 | path | 15m origin | path metrics | FX-LONG | calculate | target at execution+15m | `HORIZON_15_ERROR` | no | yes | no | yes |
| PTH-02 | path | 30m origin | path metrics | FX-LONG | calculate | target at execution+30m | `HORIZON_30_ERROR` | no | yes | yes | yes |
| PTH-03 | path | 60m origin | path metrics | FX-LONG | calculate | target at execution+60m | `HORIZON_60_ERROR` | no | yes | no | yes |
| PTH-04 | path | session close | path metrics | FX-NORMAL/FX-EARLY | calculate | official close target | `SESSION_CLOSE_ERROR` | no | yes | no | yes |
| PTH-05 | path | no cross-close | path metrics | event too late | calculate | unavailable | `HORIZON_CROSSED_CLOSE` | no | yes | yes | yes |
| PTH-06 | path | path complete | path metrics | contiguous path | calculate | complete true | `COMPLETE_PATH_REJECTED` | no | yes | yes | yes |
| PTH-07 | path | missing horizon fails | path metrics | one target missing | calculate | required failure | `MISSING_HORIZON_ACCEPTED` | no | yes | yes | yes |
| PTH-08 | return | long formula | path metrics | 100 to 101 | calculate | 0.01 | `LONG_RETURN_ERROR` | no | no | yes | yes |
| PTH-09 | return | short formula | path metrics | 100 to 99 | calculate | 0.01 | `SHORT_RETURN_ERROR` | no | no | yes | yes |
| PTH-10 | excursion | MFE/MAE long | path metrics | hand path | calculate | exact max/min oriented | `LONG_EXCURSION_ERROR` | no | yes | no | yes |
| PTH-11 | excursion | MFE/MAE short | path metrics | hand path | calculate | exact max/min oriented | `SHORT_EXCURSION_ERROR` | no | yes | no | yes |
| PTH-12 | cost | baseline | cost function | price 100 | calculate | `0.0002+0.02/100` | `BASELINE_COST_ERROR` | no | no | yes | yes |
| PTH-13 | cost | stress | cost function | price 100 | calculate | `0.0004+0.04/100` | `STRESS_COST_ERROR` | no | no | yes | yes |
| PTH-14 | return | net formulas | path metrics | gross plus costs | calculate | gross minus each cost | `NET_RETURN_ERROR` | no | no | yes | yes |

## Unconditional Control Cases

| test_id | category | src | target | fixture | action | expected | failure | sel | time | gate | req |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| CTL-01 | control | symbol match | control builder | mixed symbols | match | same symbol only | `CONTROL_SYMBOL_LEAK` | no | no | yes | yes |
| CTL-02 | control | year match | control builder | mixed years | match | same year only | `CONTROL_YEAR_LEAK` | no | no | yes | yes |
| CTL-03 | control | exact HH:MM | control builder | adjacent times | match | exact time only | `CONTROL_TIME_LEAK` | no | no | yes | yes |
| CTL-04 | control | horizon match | control builder | mixed horizons | match | same horizon only | `CONTROL_HORIZON_LEAK` | no | no | yes | yes |
| CTL-05 | control | orientation applied | control builder | long/short event | orient | matching oriented returns | `CONTROL_ORIENTATION_ERROR` | no | no | yes | yes |
| CTL-06 | control | own date excluded | control builder | own plus other dates | match | own absent | `EVENT_DATE_IN_CONTROL` | no | no | yes | yes |
| CTL-07 | control | no other symbol fallback | control builder | only other symbol | match | fail | `CONTROL_SYMBOL_FALLBACK` | no | no | yes | yes |
| CTL-08 | control | no other time fallback | control builder | only adjacent time | match | fail | `CONTROL_TIME_FALLBACK` | no | no | yes | yes |
| CTL-09 | control | no other year fallback | control builder | only other year | match | fail | `CONTROL_YEAR_FALLBACK` | no | no | yes | yes |
| CTL-10 | control | no other horizon fallback | control builder | only other horizon | match | fail | `CONTROL_HORIZON_FALLBACK` | no | no | yes | yes |
| CTL-11 | control | empty/nonfinite fail | control builder | empty then NaN | match | explicit fail both | `INVALID_CONTROL_ACCEPTED` | no | no | yes | yes |
| CTL-12 | control | discovery-only | control builder | 2024 event plus 2025/2026 rows | match | future rows excluded | `FUTURE_CONTROL_USED` | no | yes | yes | yes |

## Bootstrap Cases

| test_id | category | src | target | fixture | action | expected | failure | sel | time | gate | req |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| BST-01 | bootstrap | cluster=session_date | bootstrap | FX-CLUSTER | inspect samples | dates are indivisible | `ROWS_RESAMPLED_INDEPENDENTLY` | no | no | yes | yes |
| BST-02 | bootstrap | same-date symbols together | bootstrap | FX-CLUSTER | sample | QQQ/SPY co-occur | `SYMBOL_CLUSTER_SPLIT` | no | no | yes | yes |
| BST-03 | bootstrap | replacement | bootstrap | tiny clusters/injected RNG | sample | duplicate cluster possible | `NO_REPLACEMENT` | no | no | yes | yes |
| BST-04 | bootstrap | same cluster count | bootstrap | 3 clusters | sample | each replicate has 3 draws | `CLUSTER_COUNT_CHANGED` | no | no | yes | yes |
| BST-05 | bootstrap | seed 20260802 | bootstrap | FX-CLUSTER | run twice | identical arrays/CIs | `BOOTSTRAP_NOT_DETERMINISTIC` | no | no | yes | yes |
| BST-06 | bootstrap | productive 10000 | runner | config mutation | validate | only 10000 accepted | `PRODUCTIVE_REPLICATES_CHANGED` | no | no | yes | yes |
| BST-07 | bootstrap | injected small count | bootstrap | synthetic callback | run 20 | unit path allowed; config unchanged | `TEST_OVERRIDE_LEAKED_TO_CONFIG` | no | no | yes | yes |
| BST-08 | bootstrap | percentiles 2.5/97.5 | bootstrap | fixed statistic array | quantify | exact percentiles | `PERCENTILE_ERROR` | no | no | yes | yes |
| BST-09 | bootstrap | gross LB | bootstrap | FX-STABLE | calculate | finite lower bound | `GROSS_LB_MISSING` | no | no | yes | yes |
| BST-10 | bootstrap | incremental LB | bootstrap | FX-STABLE | calculate | finite lower bound | `INCREMENTAL_LB_MISSING` | no | no | yes | yes |
| BST-11 | bootstrap | baseline LB | bootstrap | FX-STABLE | calculate | finite lower bound | `BASELINE_LB_MISSING` | no | no | yes | yes |
| BST-12 | bootstrap | strict LB >0 | gate | lower bound 0 | evaluate | fail | `ZERO_LOWER_BOUND_PASSED` | no | no | yes | yes |
| BST-13 | bootstrap | stress non-bootstrap | outputs | FX-STABLE | inspect | no decisional stress CI | `STRESS_BOOTSTRAP_DECISIONAL` | no | no | yes | yes |
| BST-14 | bootstrap | fewer than two clusters | bootstrap | one cluster | calculate | fail | `ONE_CLUSTER_ACCEPTED` | no | no | yes | yes |
| BST-15 | bootstrap | finite/estimable | bootstrap | NaN/Inf input | calculate | fail | `NONFINITE_BOOTSTRAP_ACCEPTED` | no | no | yes | yes |

## Gate Criterion And Boundary Cases

Each `GAT-01` through `GAT-25` starts from FX-ALL-PASS, changes only the named
metric to a failing value, and requires exactly that substantive criterion to
fail. Caller-supplied criterion booleans are never authoritative.

| test_id | category | src | target | fixture/action | expected | failure | sel | time | gate | req |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| GAT-01 | gate | INT-01 | criteria derivation | FX-ONE-FAIL causal false | INT-01 false only | `INT_01_NOT_DERIVED` | no | no | yes | yes |
| GAT-02 | gate | INT-02 | criteria derivation | dataset contract false | INT-02 false only | `INT_02_NOT_DERIVED` | no | no | yes | yes |
| GAT-03 | gate | INT-03 | criteria derivation | manifest false | INT-03 false only | `INT_03_NOT_DERIVED` | no | no | yes | yes |
| GAT-04 | gate | INT-04 | criteria derivation | lookahead=1 | INT-04 false only | `INT_04_BOUNDARY` | no | no | yes | yes |
| GAT-05 | gate | INT-05 | criteria derivation | quality failures=1 | INT-05 false only | `INT_05_BOUNDARY` | no | no | yes | yes |
| GAT-06 | gate | INT-06 | criteria derivation | contamination=true | INT-06 false only | `INT_06_BOUNDARY` | no | no | yes | yes |
| GAT-07 | gate | INT-07 | criteria derivation | one incomplete path | INT-07 false only | `INT_07_NOT_DERIVED` | no | no | yes | yes |
| GAT-08 | gate | INT-08 | criteria derivation | variants=2 | INT-08 false only | `INT_08_BOUNDARY` | no | no | yes | yes |
| GAT-09 | gate | SMP-01 | criteria derivation | pooled=149 | SMP-01 false only | `SMP_01_BOUNDARY` | no | no | yes | yes |
| GAT-10 | gate | SMP-02 | criteria derivation | SPY=49 | SMP-02 false only | `SMP_02_BOUNDARY` | no | no | yes | yes |
| GAT-11 | gate | SMP-03 | criteria derivation | 2023=39 | SMP-03 false only | `SMP_03_BOUNDARY` | no | no | yes | yes |
| GAT-12 | gate | REP-01 | criteria derivation | short=39 | REP-01 false only | `REP_01_BOUNDARY` | no | no | yes | yes |
| GAT-13 | gate | ECO-01 | criteria derivation | pooled gross=0 | ECO-01 false only | `ECO_01_STRICTNESS` | no | no | yes | yes |
| GAT-14 | gate | ECO-02 | criteria derivation | SPY gross=0 | ECO-02 false only | `ECO_02_STRICTNESS` | no | no | yes | yes |
| GAT-15 | gate | ECO-03 | criteria derivation | short median=0 | ECO-03 false only | `ECO_03_STRICTNESS` | no | no | yes | yes |
| GAT-16 | gate | ECO-04 | criteria derivation | QQQ baseline=0 | ECO-04 false only | `ECO_04_STRICTNESS` | no | no | yes | yes |
| GAT-17 | gate | ECO-05 | criteria derivation | stress=-epsilon | ECO-05 false only | `ECO_05_BOUNDARY` | no | no | yes | yes |
| GAT-18 | gate | INC-01 | criteria derivation | incremental=0 | INC-01 false only | `INC_01_STRICTNESS` | no | no | yes | yes |
| GAT-19 | gate | UNC-01 | criteria derivation | one LB=0 | UNC-01 false only | `UNC_01_STRICTNESS` | no | no | yes | yes |
| GAT-20 | gate | STB-01 | criteria derivation | one gross-positive year | STB-01 false only | `STB_01_BOUNDARY` | no | no | yes | yes |
| GAT-21 | gate | STB-02 | criteria derivation | one incremental-positive year | STB-02 false only | `STB_02_BOUNDARY` | no | no | yes | yes |
| GAT-22 | gate | CON-01 | criteria derivation | concentration 0.7001 | CON-01 false only | `CON_01_BOUNDARY` | no | no | yes | yes |
| GAT-23 | gate | CON-02 | criteria derivation | LOO concentration 0.7001 | CON-02 false only | `CON_02_BOUNDARY` | no | no | yes | yes |
| GAT-24 | gate | CON-03 | criteria derivation | LOO incremental=0 | CON-03 false only | `CON_03_STRICTNESS` | no | no | yes | yes |
| GAT-25 | gate | CON-04 | criteria derivation | LOO positive years=1 | CON-04 false only | `CON_04_BOUNDARY` | no | no | yes | yes |
| GAT-26 | gate | all substantive | criteria derivation | FX-ALL-PASS | all 25 passed | `ALL_PASS_FIXTURE_INVALID` | no | no | yes | yes |
| GAT-27 | boundary | SMP-01 | criteria derivation | compare 149/150 | fail/pass | `POOLED_150_BOUNDARY` | no | no | yes | yes |
| GAT-28 | boundary | SMP-02 | criteria derivation | compare 49/50 | fail/pass | `SYMBOL_50_BOUNDARY` | no | no | yes | yes |
| GAT-29 | boundary | SMP-03 | criteria derivation | compare 39/40 | fail/pass | `YEAR_40_BOUNDARY` | no | no | yes | yes |
| GAT-30 | boundary | REP-01 | criteria derivation | compare 39/40 | fail/pass | `ORIENTATION_40_BOUNDARY` | no | no | yes | yes |
| GAT-31 | boundary | strict positive | criteria derivation | zero | all `>0` fail | `STRICT_ZERO_PASSED` | no | no | yes | yes |
| GAT-32 | boundary | nonnegative stress | criteria derivation | zero | ECO-05 passes | `NONNEGATIVE_ZERO_FAILED` | no | no | yes | yes |
| GAT-33 | boundary | yearly stability | criteria derivation | two positive years | STB pass | `TWO_YEARS_FAILED` | no | no | yes | yes |
| GAT-34 | boundary | yearly stability | criteria derivation | one positive year | STB fail | `ONE_YEAR_PASSED` | no | no | yes | yes |
| GAT-35 | boundary | concentration | concentration | 0.70 | pass | `POINT_70_FAILED` | no | no | yes | yes |
| GAT-36 | boundary | concentration | concentration | 0.7000001 | fail | `ABOVE_POINT_70_PASSED` | no | no | yes | yes |
| GAT-37 | missing | required years | criteria derivation | omit 2023 | fail affected criteria | `MISSING_YEAR_PASSED` | no | no | yes | yes |
| GAT-38 | finite | required metric | criteria derivation | NaN/Inf each | fail | `NONFINITE_GATE_PASSED` | no | no | yes | yes |
| GAT-39 | authority | no caller booleans | criteria derivation | supplied all true plus bad metrics | derived fail | `CALLER_BOOLEAN_ACCEPTED` | no | no | yes | yes |

## PRO-01 Cases

| test_id | category | src | target | fixture/action | expected | failure | sel | time | gate | req |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| PRO-01 | promotion | exact input IDs | PRO evaluator | config list | equals other 25 | `PRO_INPUT_SET_MISMATCH` | no | no | yes | yes |
| PRO-02 | promotion | no self inclusion | PRO evaluator | include PRO-01 | reject | `PRO_DIRECT_RECURSION` | no | no | yes | yes |
| PRO-03 | promotion | all passed | PRO evaluator | 25 passed | true | `PRO_ALL_PASS_FALSE` | no | no | yes | yes |
| PRO-04 | promotion | failed state | PRO evaluator | one failed | false | `PRO_FAILED_INPUT_PASSED` | no | no | yes | yes |
| PRO-05 | promotion | missing state | PRO evaluator | one missing | false | `PRO_MISSING_INPUT_PASSED` | no | no | yes | yes |
| PRO-06 | promotion | non-estimable | PRO evaluator | one non-estimable | false | `PRO_NONESTIMABLE_PASSED` | no | no | yes | yes |
| PRO-07 | promotion | no indirect recursion | PRO evaluator | input graph points back | reject | `PRO_INDIRECT_RECURSION` | no | no | yes | yes |
| PRO-08 | promotion | terminal ordering | PRO evaluator | one pending status | reject evaluation | `PRO_EVALUATED_EARLY` | no | no | yes | yes |
| PRO-09 | promotion | unavailable/false/nonfinite/insufficient | PRO evaluator | each status in turn | false each | `PRO_INVALID_STATUS_PASSED` | no | no | yes | yes |

## Concentration And Leave-One-Out Cases

| test_id | category | src | target | fixture/action | expected | failure | sel | time | gate | req |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| CON-01 | concentration | contribution by year | annual concentration | FX-STABLE | exact sums | `ANNUAL_SUM_ERROR` | no | no | yes | yes |
| CON-02 | concentration | absolute ratio | annual concentration | hand contributions | exact ratio | `CONCENTRATION_FORMULA_ERROR` | no | no | yes | yes |
| CON-03 | concentration | required years | annual concentration | omit year | fail | `CONCENTRATION_MISSING_YEAR` | no | no | yes | yes |
| CON-04 | concentration | denominator | annual concentration | all sums zero | fail | `ZERO_DENOMINATOR_PASSED` | no | no | yes | yes |
| CON-05 | concentration | finite values | annual concentration | NaN/Inf | fail | `NONFINITE_CONCENTRATION_PASSED` | no | no | yes | yes |
| CON-06 | concentration | 0.70 inclusive | annual concentration | exact 0.70 | pass | `CONCENTRATION_EQUALITY_FAILED` | no | no | yes | yes |
| CON-07 | concentration | above 0.70 | annual concentration | 0.7001 | fail | `CONCENTRATION_ABOVE_PASSED` | no | no | yes | yes |
| CON-08 | concentration | concentrated sample | annual concentration | FX-CONCENTRATED | fail | `CONCENTRATED_SAMPLE_PASSED` | no | no | yes | yes |
| LOO-01 | leave-one-out | session contribution | LOO | FX-LOO | aggregate by date | exact totals | `LOO_SESSION_SUM_ERROR` | no | no | yes | yes |
| LOO-02 | leave-one-out | same-date symbols together | LOO | FX-CLUSTER | remove date | QQQ/SPY both removed | `LOO_SYMBOL_SPLIT` | no | no | yes | yes |
| LOO-03 | leave-one-out | maximum absolute | LOO | signed contributions | select largest abs | `LOO_WRONG_SESSION` | no | no | yes | yes |
| LOO-04 | leave-one-out | exact tie behavior | selector | FX-LOO-TIE | request selection | oldest ISO `session_date` selected | `LOO_TIE_BREAK_ERROR` | no | no | yes | yes |
| LOO-05 | leave-one-out | concentration recalc | LOO | FX-LOO | remove/recalc | exact new ratio | `LOO_CONCENTRATION_ERROR` | no | no | yes | yes |
| LOO-06 | leave-one-out | pooled incremental recalc | LOO | FX-LOO | remove/recalc | exact mean | `LOO_INCREMENTAL_ERROR` | no | no | yes | yes |
| LOO-07 | leave-one-out | positive years recalc | LOO | FX-LOO | remove/recalc | exact count | `LOO_YEAR_SIGN_ERROR` | no | no | yes | yes |
| LOO-08 | leave-one-out | annual minimum reapplied | LOO | year remains 40 | evaluate | eligible | `LOO_MINIMUM_40_FAILED` | no | no | yes | yes |
| LOO-09 | leave-one-out | annual 39 fails | LOO | year drops to 39 | evaluate | fail CON-04 | `LOO_YEAR_39_PASSED` | no | no | yes | yes |
| LOO-10 | leave-one-out | zero denominator | LOO | residual sums zero | evaluate | fail | `LOO_ZERO_DENOMINATOR_PASSED` | no | no | yes | yes |
| LOO-11 | leave-one-out | one cluster | LOO | single date | evaluate | fail | `LOO_ONE_CLUSTER_PASSED` | no | no | yes | yes |
| LOO-12 | leave-one-out | finite input | LOO | NaN/Inf contribution | evaluate | fail before selection | `LOO_NONFINITE_PASSED` | no | no | yes | yes |
| LOO-13 | leave-one-out | equal absolute, same sign | selector | two positive equal contributions on different dates | select | oldest date | `LOO_SAME_SIGN_TIE_ERROR` | no | no | yes | yes |
| LOO-14 | leave-one-out | equal absolute, opposite signs | selector | equal-magnitude positive/negative dates | select | oldest date | `LOO_OPPOSITE_SIGN_TIE_ERROR` | no | no | yes | yes |
| LOO-15 | leave-one-out | row permutation invariance | selector/LOO | same events in multiple row orders | aggregate/select | same removed date | `LOO_ROW_ORDER_DEPENDENT` | no | no | yes | yes |
| LOO-16 | leave-one-out | cross-symbol date grouping | LOO | QQQ/SPY events on selected date | remove | both symbols removed together | `LOO_CROSS_SYMBOL_SPLIT` | no | no | yes | yes |
| LOO-17 | leave-one-out | three-way exact tie | selector | three equal absolute date contributions | select/remove | oldest date only | `LOO_THREE_WAY_TIE_ERROR` | no | no | yes | yes |
| LOO-18 | leave-one-out | non-finite contribution | selector | each of NaN, +Inf, -Inf | select | FAIL before ordering | `LOO_NONFINITE_PASSED` | no | no | yes | yes |
| LOO-19 | leave-one-out | no randomness | selector | tied mapping, repeated calls | select repeatedly | identical oldest date every run | `LOO_NONDETERMINISTIC_SELECTION` | no | no | yes | yes |
| LOO-20 | leave-one-out | non-tied absolute contributions | selector | unique largest absolute contribution | select | unique largest date | `LOO_MAX_ABS_REGRESSION` | no | no | yes | yes |
| LOO-21 | leave-one-out | selected deletion feeds gate | LOO/gate | selected date changes residual metrics | evaluate | same deletion feeds CON-02, CON-03, CON-04 | `LOO_GATE_INPUT_MISMATCH` | no | no | yes | yes |
| LOO-22 | leave-one-out | symbol-order invariance | selector/LOO | reverse QQQ/SPY ordering within dates | aggregate/select | same contribution and removed date | `LOO_SYMBOL_ORDER_DEPENDENT` | no | no | yes | yes |

## Runner, Output, And Safety Cases

| test_id | category | src | target | fixture/action | expected | failure | sel | time | gate | req |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| RUN-01 | runner | validate mode | CLI/validator | mock data openers to fail | validate | no opener called | `VALIDATION_OPENED_DATA` | no | no | yes | yes |
| RUN-02 | runner | run requires freezes/hash | preflight | omit each arg | run | reject | `RUN_ARGUMENT_BYPASS` | no | no | yes | yes |
| RUN-03 | runner | expected HEAD | preflight | wrong HEAD | run | reject before data | `HEAD_MISMATCH_ACCEPTED` | no | no | yes | yes |
| RUN-04 | runner | clean tree | preflight | staged/unstaged/untracked | run | reject each | `DIRTY_TREE_ACCEPTED` | no | no | yes | yes |
| RUN-05 | runner | discovery crop | loader/crop | synthetic 2021-2026 rows | run stages | only 2022-2024 materialized | `TEMPORAL_CROP_LEAK` | yes | yes | yes | yes |
| RUN-06 | runner | no 2025/2026 materialization | all stages | poison future rows | run | no future frame/output | `FUTURE_ROWS_MATERIALIZED` | yes | yes | yes | yes |
| RUN-07 | runner | progress stages | progress | FX-RUNNER | run | exact ordered stages once | `PROGRESS_STAGE_ERROR` | no | no | no | yes |
| RUN-08 | runner | interruption | runner | interrupt each long stage | run | temp retained, final absent | `INTERRUPTION_ATOMICITY_ERROR` | no | no | no | yes |
| RUN-09 | runner | results_written timing | runner | block final JSON replace | run | false until replacement success | `RESULTS_WRITTEN_EARLY` | no | no | yes | yes |
| RUN-10 | runner | WinError 5 retry | atomic helper | two locks then success | write | bounded sleeps and success | `ATOMIC_RETRY_ERROR` | no | no | no | yes |
| RUN-11 | runner | temp retained on failure | atomic helper | all retries fail | write | temp exists, error propagated | `TEMP_LOST_ON_FAILURE` | no | no | no | yes |
| RUN-12 | runner | final directory atomicity | runner | fail before promotion | run | final absent | `PARTIAL_FINAL_VISIBLE` | no | no | yes | yes |
| RUN-13 | runner | checksums reproducible | checksum writer | fixed temp bytes | run twice | identical inventory/digests | `CHECKSUM_NOT_REPRODUCIBLE` | no | no | yes | yes |
| RUN-14 | runner | run manifest coherence | manifest writer | FX-RUNNER | inspect | freezes/hash/states/counts agree | `RUN_MANIFEST_INCOHERENT` | no | no | yes | yes |
| RUN-15 | runner | final success | runner | fully mocked synthetic run | run | one complete final, no temp promotion leak | `FINAL_OUTPUT_CONTRACT_ERROR` | no | no | yes | yes |
| SEC-01 | safety | no strategy | outputs/imports | structural AST/output scan | inspect | absent/false | `STRATEGY_SURFACE_PRESENT` | no | no | yes | yes |
| SEC-02 | safety | no orders | outputs/imports | structural scan | inspect | absent/false | `ORDER_SURFACE_PRESENT` | no | no | yes | yes |
| SEC-03 | safety | no sizing | outputs/imports | structural scan | inspect | absent/false | `SIZING_SURFACE_PRESENT` | no | no | yes | yes |
| SEC-04 | safety | no broker/paper/live | outputs/imports | structural scan | inspect | absent/false | `TRADING_CONNECTION_PRESENT` | no | no | yes | yes |
| SEC-05 | safety | closed CLI | parser | override/output/symbol/period flags | parse | reject unknown flags | `CLI_BYPASS_PRESENT` | no | no | yes | yes |

## Structural Integration Suites

1. `tests.test_hyp_vwap_dev_01`: GOV, RSM, VWP, THR, EVT, EXE, PTH,
   CTL, BST, GAT, PRO, CON, and LOO cases.
2. `tests.test_hyp_vwap_dev_01_discovery`: RUN and SEC cases plus a fully
   synthetic end-to-end run with injected loaders.
3. Core regression suites to retain: `tests.test_equity_sessions`,
   `tests.test_dataset_manifest`, `tests.test_hyp_drive_pb_01`, and the atomic
   retry subset of `tests.test_hyp_drive_pb_01_discovery`.

## Implementation Traceability Matrix

| yaml_path | normative_rule | proposed_function_or_stage | test_ids | shared_or_hypothesis_specific | selection_affecting | timing_affecting | gate_affecting |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `mechanism` (B1) | Mean reversion orientation | event state machine | EVT-01, PTH-08..09 | hypothesis_specific | true | false | true |
| `universe_and_data`; `causal_resample` (B2) | QQQ/SPY causal RTH | input/resample stages | GOV-11, RSM-01..05 | shared_adapter | true | true | true |
| `causal_vwap` (B3) | Cumulative current-bar VWAP | VWAP calculator | VWP-01..07 | hypothesis_specific | true | true | true |
| `deviation` (B4) | Signed proportion | deviation/candidate | THR-01..04 | hypothesis_specific | true | false | true |
| `deviation.threshold` (B5) | Strict tau | candidate detector | THR-01..04 | hypothesis_specific | true | false | true |
| `eligible_window` (B6) | Calendar-relative window | candidate detector | THR-05..12 | hypothesis_specific | true | true | true |
| `event_formation` (B7) | Immediate confirmation | confirmer | EVT-02..09 | hypothesis_specific | true | true | true |
| `execution` (B8) | Next-open/cross cancel | executor | EXE-01..11 | hypothesis_specific | true | true | true |
| `deduplication` (B9) | First only/no rescan | state machine | EVT-10..13 | hypothesis_specific | true | true | true |
| `horizons`; `returns_and_path_metrics` (B10) | Fixed horizons and paths | path metrics | PTH-01..11 | shared_adapter | false | true | true |
| `unconditional_control` (B11) | Exact-time control | control builder | CTL-01..12 | shared_adapter | false | false | true |
| `costs` (B12) | Exact baseline/stress | cost function | PTH-12..14 | shared_adapter | false | false | true |
| `discovery_gate` (B13) | All required | criteria/PRO | GAT-01..39, PRO-01..09 | hypothesis_specific | false | false | true |
| `temporal_splits` (B14) | 2022-2024 only | preflight/crop | GOV-12..13, RUN-05..06 | shared_adapter | true | true | true |
| `safety_flags` (B15) | No trading surfaces | validation/output | GOV-14, SEC-01..05 | shared_adapter | false | false | true |
| `bootstrap` | 10,000 clustered percentile | bootstrap | BST-01..15 | shared_adapter | false | false | true |
| `annual_stability` | Exact years/counts/signs | criteria derivation | GAT-11, GAT-20..21, GAT-29, GAT-33..34 | hypothesis_specific | false | false | true |
| `concentration` | Annual share <=0.70 | concentration | CON-01..08, GAT-22, GAT-35..36 | shared_adapter | false | false | true |
| `concentration.leave_one_largest_session_out` | Select by maximum absolute contribution, oldest exact tie; remove one complete date | selector/LOO | LOO-01..22 | shared_adapter | false | false | true |
| `criteria[INT-01]` | causal integrity | criteria derivation | GAT-01 | hypothesis_specific | false | false | true |
| `criteria[INT-02]` | dataset contract | criteria derivation | GAT-02 | hypothesis_specific | false | false | true |
| `criteria[INT-03]` | manifest validation | criteria derivation | GAT-03 | hypothesis_specific | false | false | true |
| `criteria[INT-04]` | lookahead=0 | criteria derivation | GAT-04 | hypothesis_specific | false | false | true |
| `criteria[INT-05]` | quality failures=0 | criteria derivation | GAT-05 | hypothesis_specific | false | false | true |
| `criteria[INT-06]` | no contamination | criteria derivation | GAT-06 | hypothesis_specific | false | false | true |
| `criteria[INT-07]` | all paths complete | criteria derivation | GAT-07 | hypothesis_specific | false | false | true |
| `criteria[INT-08]` | variants=1 | criteria derivation | GAT-08 | hypothesis_specific | false | false | true |
| `criteria[SMP-01]` | pooled>=150 | criteria derivation | GAT-09, GAT-27 | hypothesis_specific | false | false | true |
| `criteria[SMP-02]` | symbols>=50 | criteria derivation | GAT-10, GAT-28 | hypothesis_specific | false | false | true |
| `criteria[SMP-03]` | years>=40 | criteria derivation | GAT-11, GAT-29 | hypothesis_specific | false | false | true |
| `criteria[REP-01]` | orientations>=40 | criteria derivation | GAT-12, GAT-30 | hypothesis_specific | false | false | true |
| `criteria[ECO-01]` | pooled gross>0 | criteria derivation | GAT-13, GAT-31 | hypothesis_specific | false | false | true |
| `criteria[ECO-02]` | symbol gross>0 | criteria derivation | GAT-14 | hypothesis_specific | false | false | true |
| `criteria[ECO-03]` | orientation mean/median>0 | criteria derivation | GAT-15 | hypothesis_specific | false | false | true |
| `criteria[ECO-04]` | baseline net>0 | criteria derivation | GAT-16 | hypothesis_specific | false | false | true |
| `criteria[ECO-05]` | stress net>=0 | criteria derivation | GAT-17, GAT-32 | hypothesis_specific | false | false | true |
| `criteria[INC-01]` | incremental>0 | criteria derivation | GAT-18 | hypothesis_specific | false | false | true |
| `criteria[UNC-01]` | three LBs>0 | criteria derivation | GAT-19, BST-09..12 | hypothesis_specific | false | false | true |
| `criteria[STB-01]` | gross positive >=2 years | criteria derivation | GAT-20, GAT-33..34 | hypothesis_specific | false | false | true |
| `criteria[STB-02]` | incremental positive >=2 years | criteria derivation | GAT-21, GAT-33..34 | hypothesis_specific | false | false | true |
| `criteria[CON-01]` | concentration<=0.70 | criteria derivation | GAT-22, CON-06..07 | hypothesis_specific | false | false | true |
| `criteria[CON-02]` | LOO concentration<=0.70 | criteria derivation | GAT-23, LOO-05, LOO-21 | hypothesis_specific | false | false | true |
| `criteria[CON-03]` | LOO incremental>0 | criteria derivation | GAT-24, LOO-06, LOO-21 | hypothesis_specific | false | false | true |
| `criteria[CON-04]` | LOO years/counts | criteria derivation | GAT-25, LOO-07..09, LOO-21 | hypothesis_specific | false | false | true |
| `criteria[PRO-01]` | Exact terminal 25-input aggregation | PRO evaluator | PRO-01..09 | hypothesis_specific | false | false | true |
| `safety_flags`; `forbidden_actions` | Always false/no surface | runner/AST/output | SEC-01..05 | shared_adapter | false | false | true |
| `canonical_payload_sha256` | Exact deterministic hash | config validator | GOV-03..04 | shared_adapter | false | false | true |

## Blocker And Approval Gate

Amendment `HYP-VWAP-DEV-01-AMD-01` resolves the former LOO blocker. The
contract is `PLAN_READY`, human-approved, and authorizes implementation of core
methodology and synthetic tests only. Historical-data access and discovery
execution remain prohibited, and no executable tests are created by this task.
