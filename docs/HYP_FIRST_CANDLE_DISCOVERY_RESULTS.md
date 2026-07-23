# HYP-FCR-01 Discovery Results

## Status

HYP-FCR-01 was preregistered before this run and executed for the first discovery period only.

- Hypothesis: HYP-FCR-01 - First Candle Rule: OR 30m + FVG Reentry
- Execution mode: research_primary
- Requested discovery range: 2022-01-01 to 2024-12-31
- Effective range: 2022-01-03 to 2024-12-31
- Symbols: QQQ, SPY
- Discovery status: discovery_failed
- Validation 2025 unlocked: false
- Validation executed: false
- 2026 executed: false
- Holdout executed: false
- Optimization executed: false
- Parameter sweep executed: false

This report is the first economic discovery run for HYP-FCR-01. The prior 2026 parity work remains non_decisional.

## Pre-Run Controls

- Pre-run commit: `b509a5a84d8f0b5c4f5fa0ed19dfcdc919d0f8f3`
- Working tree before discovery: clean
- Canonical payload SHA-256: `bac53f3ff97176b9be5bd5b52a9d6589747587a313b34f24644e1d99bb4cd2ab`
- Pine SHA-256: `91604D14B6DAA95758AF3D97617F3F2278E771A5A30ADC61F24E10D83B166D22`
- Technical parity gate: PASS
- Validation guard: blocked without discovery approval
- Holdout guard: blocked
- Safety: live_trading=false, broker_connected=false, orders_sent=false, paper_broker_enabled=false

Pre-run tests:

- HYP-FCR-01 tests: 28 passed
- Full suite: 306 passed

## Data

Only local curated one-minute datasets and approved manifests were used.

| Symbol | Dataset SHA-256 | Effective sessions | Rows 1m | Bars 5m | Excluded sessions |
| --- | --- | ---: | ---: | ---: | --- |
| QQQ | `2e9fd658e31c698f79bb5bcfcc7077a25e2c7b245d5b5d5f1fc3a158e7931fe4` | 753 | 292410 | 58482 | none |
| SPY | `4c28001891013c098a5e1c8050c4a8b539b53756410b6d0502ab4aa18569e787` | 752 | 292020 | 58404 | 2023-06-05 |

SPY 2023-06-05 remained excluded per manifest because the provider was missing RTH bars.

## Execution Semantics

The run used `research_primary` only:

- Signal known at five-minute bar close.
- Entry at next available one-minute open.
- Adverse slippage applied.
- Stop and target frozen from `signal_close`.
- One-minute TP/SL resolution.
- Stop first when stop and target touch in the same one-minute bar.
- Conservative gap-through-stop fill.
- No favorable price improvement through target.
- Real session close exit.
- No overnight positions.

## Pooled Metrics

| Scenario | Trades | Net expectancy R | Profit factor net | Net PnL | Max drawdown | Win rate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| baseline | 1025 | -0.1466 | 0.9096 | -125.25 | 12.51% | 35.71% |
| stress | 1025 | -0.2757 | 0.8010 | -287.08 | 18.97% | 35.32% |
| severe | 1025 | -0.4048 | 0.6967 | -449.14 | 26.00% | 34.63% |

Diagnostic pooled metrics, baseline:

- Gross expectancy R: -0.0421
- Average win R: 1.5750
- Average loss R: -1.1027
- Median trade R: -1.0660
- Longest losing streak: 15
- Exposure time: 86038 minutes
- Sizing rejections: 0
- TP exits: 277
- SL exits: 626
- Session close exits: 122
- Mean time from last touch to confirmation: 10.09 minutes
- Mean FVG size: 27.87 ticks
- Mean FVG / ATR: 0.3820

## Results By Symbol

| Scenario | Symbol | Trades | Net PnL | Expectancy R | Profit factor | Win rate | Drawdown |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| baseline | QQQ | 518 | -59.41 | -0.1283 | 0.9265 | 36.29% | 13.30% |
| baseline | SPY | 507 | -65.83 | -0.1652 | 0.8861 | 35.11% | 12.42% |
| stress | QQQ | 518 | -142.48 | -0.2337 | 0.8269 | 36.10% | 20.17% |
| stress | SPY | 507 | -144.60 | -0.3186 | 0.7667 | 34.52% | 18.93% |
| severe | QQQ | 518 | -226.43 | -0.3390 | 0.7282 | 35.33% | 27.36% |
| severe | SPY | 507 | -222.71 | -0.4720 | 0.6562 | 33.93% | 25.52% |

Both QQQ and SPY were net negative under baseline.

## Results By Year

Baseline pooled:

| Year | Trades | Net PnL | Expectancy R | Profit factor | Win rate |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2022 | 342 | 1.48 | -0.0436 | 1.0023 | 36.55% |
| 2023 | 351 | -38.58 | -0.1515 | 0.9107 | 37.04% |
| 2024 | 332 | -88.14 | -0.2473 | 0.7149 | 33.43% |

Positive years: 1 of 3.

For the 70% stability criterion, the formula is:

`year_net_pnl / pooled_baseline_total_net_pnl`

Because pooled baseline total net PnL is <= 0, the criterion is automatically failed and no absolute-value contribution is used.

## Gate Evaluation

| Criterion | Observed | Threshold | Passed |
| --- | --- | --- | --- |
| Minimum completed trades pooled | 1025 | >= 150 | true |
| Minimum completed trades per symbol | QQQ 518, SPY 507 | each >= 50 | true |
| Baseline net expectancy R | -0.1466 | > 0 | false |
| Baseline profit factor net | 0.9096 | >= 1.15 | false |
| QQQ baseline net PnL | -59.41 | > 0 | false |
| SPY baseline net PnL | -65.83 | > 0 | false |
| Stress net expectancy R | -0.2757 | >= 0 | false |
| Stress profit factor net | 0.8010 | >= 1.00 | false |
| Positive discovery years | 1 | >= 2 | false |
| Max single-year profit share | ineligible, total <= 0 | <= 70% and total > 0 | false |
| Maximum drawdown | 12.51% | <= 10% | false |

All criteria were mandatory. Multiple criteria failed.

Final classification: discovery_failed.

Validation 2025 remains locked and was not executed.

Formal final state:

- status: discovery_failed
- validation_2025_unlocked: false
- validation_executed: false
- holdout_executed: false
- paper_eligible: false
- live_eligible: false
- closed_for_parameter_changes: true

## Artifacts

Folder:

- `artifacts/research/HYP-FCR-01/discovery_2022_2024/`

Files:

- `run_manifest.json`
- `dataset_manifest_snapshot.json`
- `config_snapshot.yaml`
- `trades_baseline.csv`
- `trades_stress.csv`
- `trades_severe.csv`
- `metrics_summary.json`
- `metrics_by_symbol.csv`
- `metrics_by_year.csv`
- `metrics_by_direction.csv`
- `sizing_rejections.csv`
- `execution_diagnostics.csv`
- `gate_evaluation.json`
- `checksums.json`
- `determinism_check.json`

The deterministic metric recomputation from persisted trades matched the stored primary metrics.

## Limitations

- This is only the preregistered discovery period.
- 2025 validation was not opened.
- 2026 remains contaminated and non_decisional.
- No variants, filters, parameter sweeps, or optimizations were tested.
- Secondary cuts by symbol, year, direction, hour, FVG size, and timing are diagnostic only and cannot be used to rescue or modify the hypothesis.
