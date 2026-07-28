# HYP-OR-CONT-EVENT-01 Discovery Results

## Executive Summary

`HYP-OR-CONT-EVENT-01` tested whether an Opening Range sweep followed by three
complete bars without an opposing FVG produced executable post-confirmation
continuation from the next available bar.

The 2022-2024 discovery is closed as `discovery_failed`. The descriptive pattern
observed around the sweep did not become an executable edge after waiting for the
causal confirmation timestamp. `continuation_long` failed the primary gate.
`continuation_short` was descriptively positive, but weak, below the frozen
baseline round-trip cost on average, and not stable enough to unlock validation.

No 2025 validation, 2026 historical run, strategy, orders, position sizing,
paper eligibility, or live eligibility was created.

## Origin From HYP-FCR-EVENT-01

This hypothesis came from `HYP-FCR-EVENT-01`, which found stable but
non-economic descriptive event-study effects in the Opening Range sweep family.
The parent result was useful diagnostically, but it did not define an executable
strategy or an economic threshold.

The new hypothesis was created to remove the timing ambiguity in the parent
event study. Because the absence of an opposing FVG can only be known after
three complete bars, measurement from the sweep timestamp would be descriptive,
not executable.

## Descriptive Pattern Versus Causal Signal

The descriptive pattern asks what happened after a sweep once later information
is known. The causal signal asks what could be known at the time of action.

For this study, the signal only exists after:

- the Opening Range high or low has been swept;
- three complete 5-minute bars after the sweep have closed;
- no opposing FVG appeared inside those three bars;
- the event is deduplicated as the first confirmed signal for that symbol and
  session.

Only then can the path be measured from `executable_timestamp`.

## Confirmation Rules

For a low sweep, the event orientation is `continuation_short`. The next three
complete 5-minute bars must not contain an opposing bullish FVG.

For a high sweep, the event orientation is `continuation_long`. The next three
complete 5-minute bars must not contain an opposing bearish FVG.

The confirmation is recorded at the close of the third confirmation bar, and
`executable_timestamp` is the opening timestamp of the next 5-minute bar.

## Lookahead Prevention

The event does not exist before the third confirmation bar has closed. Future
path data after `executable_timestamp` is used only for measurement, not event
selection.

The run manifest and gate both preserve `no_lookahead=true`. Validation 2025 and
historical 2026 remained closed.

## Session Deduplication

Only the first confirmed signal per symbol-session was eligible. The discovery
artifact contains a maximum of one primary event per symbol-session, independent
of side.

## Dataset And Manifests

Artifacts audited:

- `artifacts/research/HYP-OR-CONT-EVENT-01/discovery_2022_2024/run_manifest.json`
- `dataset_manifest_snapshot.json`
- `config_snapshot.yaml`
- `confirmed_events.csv`
- `path_metrics.csv`
- `unconditional_control.csv`
- `incremental_metrics.csv`
- `metrics_by_symbol.csv`
- `metrics_by_year.csv`
- `bootstrap_intervals.csv`
- `cost_threshold_comparison.csv`
- `discovery_gate.json`
- `execution_progress.json`
- `checksums.json`

The run used QQQ and SPY, limited to 2022-01-01 through 2024-12-31.

## Frozen Identifiers

| Field | Value |
| --- | --- |
| Preregistration commit | `fe13dfe94a6b679a5abf33f079ef8497e368b4f5` |
| Execution freeze commit | `ec8803fae45ec7f07f338350e6d77b80ec6a8929` |
| Canonical payload hash | `d76572e7534e8cf66104ceb2d30dd08a7c0b080fc4460e496b58a08d3736060b` |

## Counts

| Item | Count |
| --- | ---: |
| Confirmed events | 1496 |
| QQQ confirmed events | 748 |
| SPY confirmed events | 748 |
| Path metric rows | 5967 |

Path rows by horizon:

| Horizon | Rows |
| --- | ---: |
| 15min | 1492 |
| 30min | 1492 |
| 60min | 1490 |
| session_close | 1493 |

## Horizons

The primary approval horizon was `30min` from `executable_timestamp`.

Secondary horizons were:

- `15min`
- `60min`
- `session_close`

Secondary horizons cannot override a primary-horizon fail.

## Unconditional Control

The unconditional control was matched by symbol, year, executable timestamp hour
bucket, and horizon. Incremental return was measured as event return minus the
matched unconditional return.

At the primary 30-minute horizon:

| Orientation | Mean event return | Mean control return | Mean incremental return |
| --- | ---: | ---: | ---: |
| continuation_long | -0.00000548 | -0.00000167 | -0.00000381 |
| continuation_short | 0.00022201 | 0.00000393 | 0.00021808 |

The positive incremental result on `continuation_short` is descriptive only. It
does not override the all-required gate.

## Costs

Frozen baseline round-trip cost:

`0.0002 + 0.02 / executable_price`

Frozen stress round-trip cost:

`0.0004 + 0.04 / executable_price`

At the primary 30-minute horizon, all symbol/orientation combinations failed
baseline and stress cost comparison.

## continuation_long Results

At the primary 30-minute horizon:

| Symbol | Count | Mean return | Bps | Mean baseline cost | Bootstrap CI |
| --- | ---: | ---: | ---: | ---: | --- |
| QQQ | 387 | -0.00008716 | -0.87 | 0.00025534 | [-0.00045338, 0.00026232] |
| SPY | 388 | 0.000075995 | 0.76 | 0.00024429 | [-0.00016384, 0.00032302] |

`continuation_long` did not keep the expected sign across both symbols. QQQ was
negative, SPY was small positive, and both bootstrap intervals crossed zero.

## continuation_short Results

At the primary 30-minute horizon:

| Symbol | Count | Mean return | Bps | Mean baseline cost | Bootstrap CI |
| --- | ---: | ---: | ---: | ---: | --- |
| QQQ | 359 | 0.00020744 | 2.07 | 0.00025585 | [-0.00020419, 0.00061847] |
| SPY | 358 | 0.00023661 | 2.37 | 0.00024444 | [-0.00006145, 0.00052112] |

`continuation_short` was descriptively positive, but it was not profitable after
the frozen baseline cost threshold and its bootstrap intervals crossed zero. It
is not a new strategy and not a new approved hypothesis.

## Results By Symbol

The all-horizon aggregate in `metrics_by_symbol.csv` is retained for audit
traceability, but it is not the primary gate. The primary gate is symbol,
orientation, and 30-minute horizon specific.

At 30 minutes, QQQ failed long sign and short cost. SPY had a small positive
long mean and a positive short mean, but neither side cleared the full gate.

## Results By Year

Primary 30-minute results by orientation:

| Year | Orientation | Count | Mean return | Mean incremental | Mean baseline cost |
| --- | --- | ---: | ---: | ---: | ---: |
| 2022 | continuation_long | 244 | -0.00009019 | -0.00005620 | 0.00025717 |
| 2022 | continuation_short | 250 | 0.00015183 | 0.00011424 | 0.00025710 |
| 2023 | continuation_long | 261 | -0.00007774 | -0.00011106 | 0.00025287 |
| 2023 | continuation_short | 235 | 0.00017347 | 0.00020566 | 0.00025266 |
| 2024 | continuation_long | 270 | 0.00014093 | 0.00014722 | 0.00024020 |
| 2024 | continuation_short | 232 | 0.00034680 | 0.00034256 | 0.00024013 |

The annual evidence was insufficient for the full gate and contributed to the
failed criteria `effect_in_at_least_two_of_three_years=false` and
`not_dominated_by_single_year=false`.

## Bootstrap

Bootstrap intervals were grouped by `session_date` with seed `17`. The primary
30-minute intervals crossed zero for both symbols and both orientations.

This is compatible with weak descriptive evidence, but not with a robust
economic continuation edge.

## Cost Comparison

Primary 30-minute cost comparison:

| Symbol | Orientation | Mean return | Baseline cost | Baseline passed | Stress passed |
| --- | --- | ---: | ---: | --- | --- |
| QQQ | continuation_long | -0.00008716 | 0.00025534 | false | false |
| QQQ | continuation_short | 0.00020744 | 0.00025585 | false | false |
| SPY | continuation_long | 0.000075995 | 0.00024429 | false | false |
| SPY | continuation_short | 0.00023661 | 0.00024444 | false | false |

The short side did not leave sufficient margin after costs. It must not be
called profitable.

## Gate Result

| Criterion | Result |
| --- | --- |
| `continuation_short_expected_sign` | true |
| `continuation_long_expected_sign` | false |
| `qqq_and_spy_same_sign` | true |
| `effect_in_at_least_two_of_three_years` | false |
| `incremental_return_vs_control_positive` | true |
| `mean_return_exceeds_baseline_round_trip_cost` | false |
| `not_dominated_by_single_year` | false |
| `bootstrap_grouped_by_session_not_strongly_contradictory` | true |
| `no_lookahead` | true |
| `no_2025_or_2026_contamination` | true |

The gate required all criteria. `passed=false`.

## Why The Aggregate Mean Does Not Replace The Gate

The broad aggregate mixes symbol, year, orientation, and horizon. It can obscure
a failed primary 30-minute long side, cost failure, unstable annual structure,
and zero-crossing bootstrap intervals.

The preregistered decision rule is the primary 30-minute gate. Aggregate
descriptive summaries are audit context only.

## Final Classification

Final status: `discovery_failed`

Final classification:
`causal_post_confirmation_continuation_failed`

There is no eligibility for validation, paper, or live use.

## Methodological Conclusion

The descriptive pattern observed from the Opening Range sweep did not convert
into an executable advantage after waiting for causal confirmation.

`continuation_long` failed. `continuation_short` was weakly positive, but
insufficient after costs and without enough stability. The result does not
support validation, paper trading, live trading, strategy creation, orders, or
position sizing.

## Limitations

This is a closed discovery result over 2022-2024 only. It does not estimate
whether new forward regimes will behave differently. It also does not authorize
post hoc variants, symbol-only rescue, side-only rescue, or horizon rescue.

## Allowed And Prohibited Next Steps

Allowed:

- preserve the artifacts and documentation as a failed discovery record;
- cite the result as evidence that this family has not produced an executable
  edge;
- revisit only with genuinely new external evidence or future forward data.

Prohibited:

- open 2025 validation from this result;
- execute 2026 historical data;
- create `HYP-OR-CONT-SHORT-02`;
- select only `continuation_short` retrospectively;
- create strategy code, orders, paper deployment, live deployment, or sizing;
- modify the preregistration or gate after seeing results.

## Family State

The family is closed for now:

| Hypothesis | Status |
| --- | --- |
| HYP-FCR-01 | discovery_failed |
| HYP-FCR-02 | discovery_failed |
| HYP-FCR-03 | discovery_failed |
| HYP-FCR-04 | discovery_failed |
| HYP-FCR-EVENT-01 | stable_but_not_economic |
| HYP-OR-CONT-EVENT-01 | discovery_failed |

Any future review of this family must come from new external evidence or forward
data, not new cuts over 2022-2024.

## Safety Confirmation

2025 remains closed. 2026 was not executed. No strategy, orders, position
sizing, paper eligibility, or live eligibility were created.

Safety flags remain false:

- `live_trading=false`
- `broker_connected=false`
- `orders_sent=false`
- `paper_broker_enabled=false`
