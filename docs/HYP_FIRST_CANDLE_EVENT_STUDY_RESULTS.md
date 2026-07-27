# HYP-FCR-EVENT-01 Event Study Results

Hypothesis: `HYP-FCR-EVENT-01`

Name: Opening Range Sweep and Post-Event Path Study

Execution commit: `d7af910b113ab4481f76b3cdb715bd1609d1fd70`

Canonical payload hash: `1b6ad06b974d996cdf6bd0a3a21eae097e94322e80fdec94c2cfc4ec3c18fe81`

Period audited: discovery `2022-01-01` through `2024-12-31`

Final audited status: `event_study_completed_stable_not_economic`

Final classification: `stable_but_not_economic`

This is a non-strategy descriptive event study. It creates no entries, exits,
orders, stops, targets, position sizing, PnL series, paper eligibility, live
eligibility, or validation unlock.

## Integrity

The post-run audit used persisted artifacts only:

- `artifacts/research/HYP-FCR-EVENT-01/discovery_2022_2024/events.csv`
- `artifacts/research/HYP-FCR-EVENT-01/discovery_2022_2024/path_metrics.csv`
- `artifacts/research/HYP-FCR-EVENT-01/discovery_2022_2024/aggregate_metrics.csv`
- `artifacts/research/HYP-FCR-EVENT-01/discovery_2022_2024/bootstrap_intervals.csv`
- `artifacts/research/HYP-FCR-EVENT-01/discovery_2022_2024/economic_threshold_comparison.csv`
- `artifacts/research/HYP-FCR-EVENT-01/discovery_2022_2024/postrun_integrity/`

The audit reconciled exactly `8498` events and `42490` path rows. Every event
has exactly five horizons: `5min`, `15min`, `30min`, `60min`,
`session_close`. There are no orphan path rows, missing horizons,
symbol/event-type mismatches, invalid duplicate ids, 2025/2026 rows, overnight
event-time crossings, or invalid infinity values.

The observed 312-event discrepancy was not missing data. It was the
`QQQ / EVENT-05` group, which contains `312` events and was omitted from the
visible manual grouping.

| Symbol | EVENT-01 | EVENT-02 | EVENT-03 | EVENT-04 | EVENT-05 | EVENT-06 | EVENT-07 | EVENT-08 | EVENT-09 | EVENT-10 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| QQQ | 515 | 515 | 531 | 531 | 312 | 317 | 495 | 512 | 232 | 205 |
| SPY | 550 | 548 | 576 | 573 | 336 | 321 | 517 | 557 | 174 | 181 |

All aggregate files were recomputed from `path_metrics.csv` and compared
field-by-field at tolerance `1e-12`. The value-level mismatch count is zero.
Recomputed byte checksums can differ because CSV formatting is not guaranteed
to be byte-identical.

## Economic Rule

The frozen YAML and preregistration do not define a formal economic magnitude
threshold for HYP-FCR-EVENT-01. The only one-tick language appears inside
EVENT-02 and EVENT-04 strict-break event definitions. It is not an approval
threshold. No two-tick rule, baseline friction rule, stress friction rule, PnL
model, execution model, or transaction-cost model is preregistered for this
event study.

The persisted `economic_threshold_comparison.csv` is consistent with this:
`economic_threshold_applicable = False` and the reason is
`non_strategy_event_study_no_pnl_no_cost_model`.

The audited operational tick size is `0.01`. Diagnostic thresholds were
computed event by event as:

- `one_tick_return = 0.01 / event_price`
- `two_tick_return = 2 * 0.01 / event_price`

Baseline and stress frictions were not applied because they are not defined in
the HYP-FCR-EVENT-01 YAML or preregistration. They remain `not_applicable`, not
zero.

## Orientations

`reversal_return` measures the return in the reversal direction named by the
stored orientation. For `EVENT-07 / long_reversal`, a negative reversal return
means the low sweep continued lower instead of reversing long. For
`EVENT-08 / short_reversal`, a negative reversal return means the high sweep
continued higher instead of reversing short.

Because `continuation_return = -reversal_return`, the economic audit uses the
positive effect direction for the six candidates. All six stable candidates are
continuation effects, not strategy signals.

## Candidate Evidence

Bootstrap intervals are grouped by `session_date` with seed `17`; events from
the same session are not treated as independent. Full symbol/year rows are in:

- `artifacts/research/HYP-FCR-EVENT-01/discovery_2022_2024/postrun_integrity/economic_threshold_by_candidate.csv`

| Event | Orientation | Horizon | Symbol | Effect | Mean oriented return | Bootstrap CI | Mean net 1 tick | Mean net 2 ticks | Years positive |
| --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| EVENT-07 | long_reversal | 5min | QQQ | continuation | 0.0002535 | [0.0001173, 0.0003909] | 0.0002256 | 0.0001978 | 3 |
| EVENT-07 | long_reversal | 5min | SPY | continuation | 0.0001457 | [0.0000418, 0.0002371] | 0.0001236 | 0.0001014 | 3 |
| EVENT-07 | long_reversal | 15min | QQQ | continuation | 0.0003598 | [0.0001617, 0.0005629] | 0.0003319 | 0.0003040 | 3 |
| EVENT-07 | long_reversal | 15min | SPY | continuation | 0.0003039 | [0.0001657, 0.0004319] | 0.0002818 | 0.0002596 | 3 |
| EVENT-07 | long_reversal | 30min | QQQ | continuation | 0.0004517 | [0.0001576, 0.0007574] | 0.0004239 | 0.0003960 | 3 |
| EVENT-07 | long_reversal | 30min | SPY | continuation | 0.0004277 | [0.0002111, 0.0006367] | 0.0004056 | 0.0003834 | 3 |
| EVENT-08 | short_reversal | 15min | QQQ | continuation | 0.0004577 | [0.0002503, 0.0006620] | 0.0004299 | 0.0004022 | 3 |
| EVENT-08 | short_reversal | 15min | SPY | continuation | 0.0001981 | [0.0000631, 0.0003443] | 0.0001760 | 0.0001538 | 3 |
| EVENT-08 | short_reversal | 30min | QQQ | continuation | 0.0003971 | [0.0000783, 0.0006905] | 0.0003694 | 0.0003416 | 3 |
| EVENT-08 | short_reversal | 30min | SPY | continuation | 0.0003057 | [0.0001175, 0.0005051] | 0.0002836 | 0.0002614 | 3 |
| EVENT-08 | short_reversal | 60min | QQQ | continuation | 0.0006457 | [0.0001913, 0.0010580] | 0.0006180 | 0.0005903 | 3 |
| EVENT-08 | short_reversal | 60min | SPY | continuation | 0.0003808 | [0.0001115, 0.0007022] | 0.0003587 | 0.0003366 | 3 |

All six candidate combinations have the same continuation effect direction in
QQQ and SPY, positive mean net of one tick, positive mean net of two ticks,
positive yearly means in all three years, annual concentration below `50%`, and
nearby-horizon coherence.

## Multiple Comparisons

The preregistration does not specify an exact multiple-comparisons method. The
final economic audit therefore does not invent Bonferroni, Holm, FDR, or any
other corrected significance claim after seeing results.

The audit records `50` total event/orientation/horizon combinations in the
persisted event-study family and audits the six pre-identified candidates. Six
are stable descriptively. Zero pass all preregistered criteria for
`hypothesis_generating_signal` because no preregistered economic threshold
exists.

## Final Classification

The prior `hypothesis_generating_signal` classification is preserved in the
original `classification.json` and is not modified. The final post-run economic
audit closes the study as:

`event_study_completed_stable_not_economic`

Rationale: stable diagnostic continuation effects exist in EVENT-07 and
EVENT-08, but HYP-FCR-EVENT-01 did not preregister an economic threshold or cost
model. Under the stricter requirement that `hypothesis_generating_signal`
requires a preregistered economic threshold pass, the final classification is
`stable_but_not_economic`.

## Safety

No OHLC CSVs were reopened. No 2025 or 2026 data was opened. No strategy was
created. No orders, stops, targets, portfolio simulation, sizing, paper
eligibility, live eligibility, validation unlock, optimization, or parameter
change was created.

