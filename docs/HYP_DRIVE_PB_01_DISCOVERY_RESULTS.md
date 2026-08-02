# HYP-DRIVE-PB-01 Discovery Results

## 1. Executive Summary

`HYP-DRIVE-PB-01` tested Opening Drive + Controlled Pullback Continuation as
a frozen causal event study over QQQ and SPY from 2022-01-01 through
2024-12-31. The run completed successfully and its artifact contract is valid,
but the discovery gate failed.

The final classification is `discovery_failed`. The dominant failure reason is
`insufficient_event_frequency`: only 3 events were confirmed, versus a frozen
minimum of 150 pooled events and 50 events per symbol. All 3 events were in QQQ;
SPY had none. The frozen variant is not promotable to validation, paper, or live
use.

This result does not universally refute opening-drive continuation. It closes
this preregistered variant on this discovery sample. No economic causality is
inferred from three observations.

## 2. Freeze Status

| Freeze | Commit or hash |
| --- | --- |
| Conceptual design freeze | `925cede00f3d9c1b4de46e225f98d4636c19a831` |
| Implementation clarification freeze | `764478b86a01619620166848204e527f2fb55c55` |
| Preregistration freeze | `adb7f7b59b08389883777103e23f98ea298a5965` |
| Execution freeze | `3341d439cab38222c023c6657edb0300e503b1f8` |
| Canonical payload hash | `b763e7d2d01f1d12f9be85fa0238a4ccb21b251baee966f8e421410aaecc651b` |

The run manifest records the execution freeze as both `execution_freeze_commit`
and `head_commit`. Its runtime configuration hash equals the canonical payload
hash.

## 3. Dataset And Period

The discovery period was 2022-01-01 through 2024-12-31, using QQQ and SPY RTH
minute data under the frozen dataset and calendar contracts.

| Symbol | Approved sessions | Excluded sessions |
| --- | ---: | --- |
| QQQ | 753 | None |
| SPY | 752 | 2023-06-05 |

Only the closed run artifacts were used for this results review. No 2025 or
2026 market data was opened.

## 4. Causal And Temporal Integrity

The run records `causal_integrity_passed=true` and
`contamination_absent=true`. Specifically:

- manifest, dataset, calendar-session, resampling, event timestamp, horizon,
  and control integrity checks passed;
- lookahead violations: 0;
- unresolved data-quality failures: 0;
- accepted incomplete sessions: 0;
- event and control rows outside discovery: 0;
- rows materialized after the discovery end: 0;
- historical 2025 and 2026 rows materialized: 0;
- horizons crossing a session or period boundary: 0.

## 5. Event Count

| Scope | Confirmed events |
| --- | ---: |
| Pooled | 3 |
| QQQ | 3 |
| SPY | 0 |
| 2022 | 2 |
| 2023 | 1 |
| 2024 | 0 |

The artifact also contains 1,503 excluded candidates. These exclusions remain
audit context and do not change the confirmed-event count.

## 6. Confirmed Events

All values below are returns at the frozen primary horizon of 30 minutes.

| Event | Direction | Gross return | Incremental return | Net baseline | Net stress |
| --- | --- | ---: | ---: | ---: | ---: |
| `QQQ-2022-03-28` | `continuation_long` | -0.003971537315902718 | -0.0037321775060017728 | -0.004226697556401367 | -0.004481857796900015 |
| `QQQ-2022-06-21` | `continuation_long` | 0.0007439158312372296 | 0.0010021374537267347 | 0.0004730667044527172 | 0.0002022175776682048 |
| `QQQ-2023-03-28` | `continuation_short` | 0.0038338030015072633 | 0.0038538952904837516 | 0.003568518196545618 | 0.0033032333915839728 |

## 7. Primary 30-Minute Results

| Measure | Mean return | Basis points |
| --- | ---: | ---: |
| Gross event return | 0.000202060505613925 | +2.02 bps |
| Incremental return | 0.0003746184127362379 | +3.75 bps |
| Net baseline return | -0.00006170421846767706 | -0.62 bps |
| Net stress return | -0.0003254689425492791 | -3.25 bps |

There were 3 available observations, with a gross and incremental win rate of
2/3. The positive gross and incremental averages are not sufficient evidence:
the sample is extremely small, both pooled net means are negative, and the
bootstrap intervals cross zero.

## 8. Results By Direction

| Direction | n | Gross mean | Gross median | Incremental mean | Net baseline mean | Net stress mean |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `continuation_long` | 2 | -0.0016138107423327441 | -0.0016138107423327441 | -0.001365020026137519 | -0.0018768154259743246 | -0.002139820109615905 |
| `continuation_short` | 1 | 0.0038338030015072633 | 0.0038338030015072633 | 0.0038538952904837516 | 0.003568518196545618 | 0.0033032333915839728 |

The positive short mean and median are based on one observation. They are not
sufficient statistical evidence and cannot rescue the failed primary gate.

## 9. Results By Symbol

QQQ supplied all 3 events. Its 30-minute values therefore equal the pooled
values: gross mean +2.02 bps, incremental mean +3.75 bps, baseline net mean
-0.62 bps, and stress net mean -3.25 bps.

SPY supplied zero events and consequently has no estimated event-return mean.
The `qqq_and_spy_positive_primary_means` criterion fails because a required
symbol has no events, not because a zero-event SPY mean can be treated as zero.

## 10. Results By Year

| Year | n | Gross mean | Incremental mean | Net baseline mean | Net stress mean |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2022 | 2 | -0.0016138107423327441 | -0.001365020026137519 | -0.0018768154259743246 | -0.002139820109615905 |
| 2023 | 1 | 0.0038338030015072633 | 0.0038538952904837516 | 0.003568518196545618 | 0.0033032333915839728 |
| 2024 | 0 | Not estimable | Not estimable | Not estimable | Not estimable |

Gross return was positive in only one observed year. With no 2024 event, the
required three-year stability and sign-robustness conditions cannot be shown.

## 11. Baseline And Stress Costs

The event-level frozen baseline round-trip costs were approximately 2.55 to
2.71 bps; their pooled mean was 2.64 bps. Stress costs were twice those amounts,
with a pooled mean of 5.28 bps.

Two of three individual event returns exceeded each cost profile, but the
negative first event was large enough that pooled baseline and stress net means
were both negative. Individual exceedance frequency does not override the
preregistered pooled net criteria.

## 12. Unconditional Control And Incremental Return

Incremental return is gross event return minus the matched unconditional
control return. At 30 minutes, the pooled unconditional-control mean was
approximately -0.000172557907122313 (-1.73 bps), producing a pooled incremental
mean of +0.0003746184127362379 (+3.75 bps).

This is a descriptive comparison from three events. It is not evidence of
economic causality and does not compensate for the event-frequency, net-return,
cross-symbol, annual-stability, or bootstrap failures.

## 13. Bootstrap

| Metric | 95% lower bound | 95% upper bound | Crosses zero |
| --- | ---: | ---: | --- |
| `event_return` | -0.003971537315902718 | 0.0038338030015072633 | Yes |
| `incremental_return` | -0.0037321775060017728 | 0.0038538952904837516 | Yes |
| `net_return_baseline` | -0.004226697556401367 | 0.003568518196545618 | Yes |

All three intervals cross zero. None supplies a strictly positive lower bound.

## 14. Complete Gate

The gate required every criterion to pass. Final result: `passed=false`.

| Criterion | Result | Interpretation |
| --- | --- | --- |
| `minimum_pooled_events` | FAIL | 3 events versus minimum 150 |
| `minimum_events_per_symbol` | FAIL | QQQ 3 and SPY 0 versus minimum 50 each |
| `continuation_long_positive_mean_and_median` | FAIL | Both were negative |
| `continuation_short_positive_mean_and_median` | PASS | Positive, but based on n=1 |
| `qqq_and_spy_positive_primary_means` | FAIL | SPY had zero events |
| `gross_mean_positive_in_at_least_two_of_three_years` | FAIL | Positive only in 2023; 2024 absent |
| `pooled_incremental_mean_positive` | PASS | +0.0003746184127362379 |
| `pooled_baseline_net_mean_positive` | FAIL | -0.00006170421846767706 |
| `pooled_stress_net_mean_non_negative` | FAIL | -0.0003254689425492791 |
| `annual_concentration_at_most_0_70` | FAIL | `MISSING_REQUIRED_YEAR`; value not calculated |
| `leave_one_session_out_concentration_at_most_0_70` | FAIL | `MISSING_REQUIRED_YEAR`; value not calculated |
| `annual_signs_positive_in_at_least_two_of_three_years_original_and_leave_one_out` | FAIL | Annual sign robustness not demonstrated |
| `all_three_bootstrap_lower_bounds_strictly_positive` | FAIL | All intervals cross zero |
| `no_lookahead_or_unresolved_data_quality_failure` | PASS | Causal integrity passed |
| `no_2025_or_2026_contamination` | PASS | No temporal contamination |
| `one_variant_budget_respected` | PASS | One decision variant |

Annual and leave-one-out concentration did not fail because a computed value
exceeded 0.70. Both values are null and carry `MISSING_REQUIRED_YEAR`, so the
required concentration validations could not be completed. Secondary horizons
and descriptive criteria cannot override failure at the primary horizon.

## 15. Dominant Failure Reason

`dominant_failure_reason=insufficient_event_frequency`

Only 3 events were found against `minimum_pooled_events=150`. At symbol level,
QQQ had 3 and SPY had 0 against `minimum_events_per_symbol=50`.

## 16. Secondary Failure Reasons

- SPY had zero events.
- No events occurred in 2024.
- `continuation_long` had negative mean and median returns.
- Pooled baseline and stress net means were negative.
- All reported bootstrap intervals crossed zero.
- Annual and leave-one-out stability could not be demonstrated.
- The evidence is insufficient statistically and economically.

## 17. Promotion Decision

`validation_2025_unlocked=false`, `paper_eligible=false`, and
`live_eligible=false`. The frozen variant failed discovery and is not
promotable. It must not be described as a profitable strategy.

## 18. 2025 Status

`validation_2025_executed=false`. The 2025 validation holdout remains locked
because the all-required discovery gate did not pass. No 2025 data was opened
for this documentation task.

## 19. 2026 Status

`historical_2026_executed=false`. No 2026 data was opened or used for this
documentation task.

## 20. Safety

The final artifacts record:

- `strategy_created=false`;
- `orders_created=false` and `orders_sent=false`;
- `position_sizing_used=false`;
- `paper_eligible=false` and `paper_broker_enabled=false`;
- `live_eligible=false`, `live_trading=false`, and `broker_connected=false`.

No strategy, sizing, order, paper, or live workflow is authorized by this
result.

## 21. Artifact Location And Verification

Canonical artifact directory:

`artifacts/research/HYP-DRIVE-PB-01/discovery_2022_2024/`

The review covered `run_manifest.json`, `checksums.json`,
`discovery_gate.json`, `confirmed_events.csv`, `event_exclusions.csv`,
`path_metrics.csv`, `unconditional_control.csv`, `metrics_pooled.csv`,
`metrics_by_symbol.csv`, `metrics_by_year.csv`, `metrics_by_direction.csv`,
`metrics_by_horizon.csv`, `bootstrap_intervals.csv`,
`cost_threshold_comparison.csv`, `concentration_metrics.csv`, and
`leave_one_out_metrics.csv`.

The output inventory is closed: all 20 expected files are present. The SHA-256
and size of every output listed in `checksums.json` were recomputed and all 19
records matched. `checksums.json` is intentionally excluded from its own hash.
No artifact was rewritten.

## 22. Final Conclusion

The real 2022-2024 discovery run completed with valid artifacts, causal
integrity, and no temporal contamination. The frozen hypothesis variant failed
its preregistered gate, predominantly because event frequency was far below the
minimum required sample and SPY produced no events.

The result is formally closed as `discovery_failed` with
`dominant_failure_reason=insufficient_event_frequency`. The variant is not
eligible for 2025 validation, strategy construction, paper trading, or live
trading. This is a failure of the frozen discovery variant, not a universal
refutation of every possible opening-drive pullback hypothesis.
