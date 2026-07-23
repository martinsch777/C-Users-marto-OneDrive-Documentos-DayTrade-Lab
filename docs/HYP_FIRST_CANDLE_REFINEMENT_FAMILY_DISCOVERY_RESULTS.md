# HYP First Candle Refinement Family Discovery Results

## Status

Family: `FCR-REFINEMENT-FAMILY-01`

The first preregistered family discovery batch was executed as one indivisible
run for:

- `HYP-FCR-02`
- `HYP-FCR-03`
- `HYP-FCR-04`

The three variants were completed before family selection was applied.

Final family status: `discovery_failed`

Selected hypothesis: `null`

Validation 2025 unlocked: `false`

No validation 2025, 2026, holdout, optimization, parameter sweep, broker/API
call, data download, paper trading, or live trading was executed.

## Pre-Run

- Observed pre-run commit: `135c3e67cf5d74d99da3bed53be2e1543d22aca0`
- Working tree before execution: clean
- HYP-FCR-01 state: `discovery_failed`, `validation_2025_unlocked=false`, `closed_for_parameter_changes=true`
- Execution mode: `research_primary`
- Discovery range: `2022-01-01` to `2024-12-31`

Canonical hashes confirmed before opening data:

| Config | SHA-256 |
| --- | --- |
| HYP-FCR-02 | `2276cd958aaf5e982e393fcaa29611fe46bb9a483bd606a0a681a5613922c8e6` |
| HYP-FCR-03 | `c7e69addf98b2e35a34bafaadc7b55e6139c79a6cc7f06538e83673584eb70ec` |
| HYP-FCR-04 | `1ddd959bc559503be511b6ac1e9b62bd60e8f413b6cfdc3d98ab89cd6682799b` |
| FCR-REFINEMENT-FAMILY-01 | `1ecacc828b91533458ae112ed7c749936612f94a26b2d0b48ea2da0b5948d7ad` |

Pre-run tests:

- FCR-01, discovery, variants, and family runner: 52 passed
- Full suite: 330 passed

## Data

Only local curated, audited, approved QQQ and SPY one-minute datasets were used.

| Symbol | Dataset SHA-256 | Effective start | Effective end | Sessions | Rows 1m | Bars 5m | Excluded sessions |
| --- | --- | --- | --- | ---: | ---: | ---: | --- |
| QQQ | `2e9fd658e31c698f79bb5bcfcc7077a25e2c7b245d5b5d5f1fc3a158e7931fe4` | 2022-01-03 | 2024-12-31 | 753 | 292410 | 58482 | none |
| SPY | `4c28001891013c098a5e1c8050c4a8b539b53756410b6d0502ab4aa18569e787` | 2022-01-03 | 2024-12-31 | 752 | 292020 | 58404 | 2023-06-05 |

SPY 2023-06-05 remained excluded per manifest because RTH bars were missing.

## Rules

All variants inherited HYP-FCR-01 data, costs, Opening Range, FVG confirmation,
position sizing, `research_primary` execution semantics, conservative intrabar
resolution, true session close exit, and no overnight positions.

Variant-specific changes:

- `HYP-FCR-02`: FVG confirmation only at offsets 1, 2, or 3 after the latest sweep.
- `HYP-FCR-03`: strict sweep of at least one tick beyond the Opening Range extreme.
- `HYP-FCR-04`: structural stop behind the full latest-sweep-to-signal segment.

## Pooled Metrics

| Variant | Scenario | Trades | Net PnL | Net expectancy R | PF net | Max DD | Win rate |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| HYP-FCR-02 | baseline | 973 | -82.02 | -0.1309 | 0.9377 | 11.56% | 36.28% |
| HYP-FCR-02 | stress | 973 | -250.01 | -0.2594 | 0.8170 | 18.14% | 35.87% |
| HYP-FCR-02 | severe | 973 | -404.57 | -0.3879 | 0.7146 | 24.73% | 35.25% |
| HYP-FCR-03 | baseline | 1025 | -136.82 | -0.1524 | 0.9014 | 12.76% | 35.41% |
| HYP-FCR-03 | stress | 1025 | -295.86 | -0.2821 | 0.7953 | 19.11% | 35.02% |
| HYP-FCR-03 | severe | 1025 | -454.34 | -0.4117 | 0.6928 | 25.99% | 34.54% |
| HYP-FCR-04 | baseline | 1025 | -70.38 | -0.1022 | 0.9519 | 9.91% | 36.68% |
| HYP-FCR-04 | stress | 1025 | -250.26 | -0.2214 | 0.8329 | 17.14% | 36.49% |
| HYP-FCR-04 | severe | 1025 | -414.82 | -0.3407 | 0.7330 | 24.29% | 36.00% |

## Baseline By Symbol

| Variant | Symbol | Trades | Net PnL | Expectancy R | PF net | Max DD | Win rate |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| HYP-FCR-02 | QQQ | 490 | -40.76 | -0.0990 | 0.9464 | 11.95% | 37.35% |
| HYP-FCR-02 | SPY | 483 | -41.26 | -0.1634 | 0.9258 | 11.87% | 35.20% |
| HYP-FCR-03 | QQQ | 518 | -60.41 | -0.1284 | 0.9252 | 13.39% | 36.29% |
| HYP-FCR-03 | SPY | 507 | -76.42 | -0.1770 | 0.8681 | 12.81% | 34.52% |
| HYP-FCR-04 | QQQ | 518 | -63.05 | -0.1333 | 0.9260 | 13.99% | 35.52% |
| HYP-FCR-04 | SPY | 507 | -7.32 | -0.0703 | 0.9880 | 6.28% | 37.87% |

## Baseline By Year

| Variant | 2022 PnL | 2023 PnL | 2024 PnL | Positive years |
| --- | ---: | ---: | ---: | ---: |
| HYP-FCR-02 | 36.73 | -41.97 | -76.78 | 1 |
| HYP-FCR-03 | -12.36 | -36.48 | -87.99 | 0 |
| HYP-FCR-04 | 34.29 | -11.50 | -93.16 | 1 |

Because baseline pooled net PnL was <= 0 for every variant, the single-year
profit concentration criterion failed automatically for every variant.

## Diagnostics

| Variant | Key diagnostics |
| --- | --- |
| HYP-FCR-02 | offset trades: 1 = 663, 2 = 250, 3 = 60; expired sweeps = 1077; offset 4+ rejections = 1077 |
| HYP-FCR-03 | exact/subtick touches rejected = 348; valid sweeps with trades = 1025; mean sweep depth = 28.90 ticks |
| HYP-FCR-04 | mean structural stop distance = 1.2139; mean structural-body stop difference = 0.2978; mean structural segment = 3.02 bars; additional sizing rejections = 0 |

All diagnostic metrics are non-decisional for rule modification and did not
alter selection.

## Gates

All individual gates are mandatory.

`HYP-FCR-02` passed only trade-count criteria. It failed baseline expectancy,
baseline PF, QQQ/ SPY positivity, stress expectancy, stress PF, annual
stability, annual concentration, and drawdown.

`HYP-FCR-03` passed only trade-count criteria. It failed baseline expectancy,
baseline PF, QQQ/ SPY positivity, stress expectancy, stress PF, annual
stability, annual concentration, and drawdown.

`HYP-FCR-04` passed trade-count criteria and baseline drawdown. It failed
baseline expectancy, baseline PF, QQQ/ SPY positivity, stress expectancy,
stress PF, annual stability, and annual concentration.

## Family Selection

Family policy was applied only after all three variants completed:

- Completed before selection: `HYP-FCR-02`, `HYP-FCR-03`, `HYP-FCR-04`
- Passing variants: none
- `family_status = discovery_failed`
- `selected_hypothesis_id = null`
- `validation_2025_unlocked = false`

## Benchmark

Frozen HYP-FCR-01 benchmark, diagnostic only:

| Hypothesis | Trades | Net PnL | Expectancy R | PF net | Max DD |
| --- | ---: | ---: | ---: | ---: | ---: |
| HYP-FCR-01 | 1025 | -125.248041 | -0.1465555726 | 0.9096245247 | 12.513798% |

Losing less than HYP-FCR-01 is not a success criterion and did not affect the
gate.

## Artifacts

Folder:

- `artifacts/research/FCR-REFINEMENT-FAMILY-01/discovery_2022_2024/`

Family artifacts:

- `family_run_manifest.json`
- `family_config_snapshot.yaml`
- `family_gate_evaluation.json`
- `family_selection_result.json`
- `family_metrics_comparison.csv`
- `dataset_manifest_snapshot.json`
- `checksums.json`

Each variant folder contains run manifest, config snapshot, trades for
baseline/stress/severe, metrics, diagnostics, sizing rejections, gate
evaluation, and checksums.

## Limitations

This was a multiple-comparison refinement family generated after seeing
HYP-FCR-01 fail. The discovery period is decisional for the family but not
independent evidence. Validation 2025 remains closed. The 2026 period remains
contaminated and non-decisional only.
