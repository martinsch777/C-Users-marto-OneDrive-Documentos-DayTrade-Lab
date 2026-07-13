# HYP-GAP Discovery Results

## Scope

This document records the first preregistered HYP-GAP discovery run for QQQ and SPY using approved curated Alpaca SIP 1-minute datasets. This is a discovery event study only. It is not a strategy approval, replay approval, paper approval, or live-trading approval.

Permanent safety state:

- live_trading=False
- broker_connected=False
- orders_sent=False
- paper_broker_enabled=False

No broker was connected, no orders were sent, no live trading was enabled, and no paper broker was enabled.

## Execution Control

| Item | Value |
| --- | --- |
| Branch | codex/intraday-hypothesis-refinement |
| Code commit | 5e219c378af631ce55bd3e8e95ffe22149903ed8 |
| Last commit subject | Normalize HYP-GAP discovery session boundaries |
| Python | Python 3.13.2 |
| Pre-run unit tests | Ran 242 tests in 164.213s - OK |
| Discovery requested start | 2022-01-01 |
| Discovery requested end | 2024-12-31 |
| Effective start | 2022-01-03 |
| Effective end | 2024-12-31 |
| Warmup loaded from | 2022-01-03 |
| Symbols | QQQ, SPY |
| Timeframe | 1min |
| Variants | HYP-GAP-01 through HYP-GAP-06 |
| Horizons | 5min, 15min, 30min, 60min, session_close |

The run used committed code and the existing preregistered configuration. No code, methodology, thresholds, datasets, manifests, strategy parameters, signals, costs, reports, or backtest results were changed as part of execution.

## Inputs

| Symbol | Curated CSV | Approved manifest | Dataset sha256 |
| --- | --- | --- | --- |
| QQQ | data/curated/QQQ_1min_2022-01-01_2026-07-06_curated.csv | data/manifests/QQQ_1min_2022-01-01_2026-07-06_curated_manifest.json | 2e9fd658e31c698f79bb5bcfcc7077a25e2c7b245d5b5d5f1fc3a158e7931fe4 |
| SPY | data/curated/SPY_1min_2022-01-01_2026-07-06_curated.csv | data/manifests/SPY_1min_2022-01-01_2026-07-06_curated_manifest.json | 4c28001891013c098a5e1c8050c4a8b539b53756410b6d0502ab4aa18569e787 |

SPY retained the approved excluded session `2023-06-05`. That session did not appear in detected events or result rows.

## Output Artifacts

Each symbol produced exactly five run files.

### QQQ

| File | sha256 |
| --- | --- |
| outputs/hyp_gap_discovery_2022_2024_v1/QQQ/run_manifest.json | 8f794adae9848858a6ebe77d92b467939bac55935b19cb8285935d04d17ecf47 |
| outputs/hyp_gap_discovery_2022_2024_v1/QQQ/events.csv | 62d2559cb22a94d3a074a3a2829e395fd679839542d918b774150e37bada8be3 |
| outputs/hyp_gap_discovery_2022_2024_v1/QQQ/event_results.csv | d108959f022287737bfc6739f07d2789d3dfeae16a03c61d920a6ed065cbd7f1 |
| outputs/hyp_gap_discovery_2022_2024_v1/QQQ/aggregate_results.csv | f2991f630df4283489542055fc22bb6864f32eef3c5ac3984b4f382f7a77ab8f |
| outputs/hyp_gap_discovery_2022_2024_v1/QQQ/detection_summary.json | 4ea930d82562753999f606ab382be831d1d86247c3d7f492de4392f9cbad9fd0 |

Run id: `HYP-GAP__discovery__QQQ__1min__2022-01-01__2024-12-31__885321b799af3e5b`

Fingerprint: `885321b799af3e5b7d2c21f4ad7dffe1c0cdd378847aee302df1de40bab6b48c`

### SPY

| File | sha256 |
| --- | --- |
| outputs/hyp_gap_discovery_2022_2024_v1/SPY/run_manifest.json | 62f63268d9ffaf7f43ded025cf7aff931216e9d7204c90ae1c55d3a855e92cf1 |
| outputs/hyp_gap_discovery_2022_2024_v1/SPY/events.csv | 2334a7f9a1b68a520ce1012175ac3ada294bce4d953c826fb8ed2b9dab6fa7a1 |
| outputs/hyp_gap_discovery_2022_2024_v1/SPY/event_results.csv | 81144248deb84e46405ea09e2670332716b80ab86a59d819bc8e0b4de7cd8084 |
| outputs/hyp_gap_discovery_2022_2024_v1/SPY/aggregate_results.csv | 3e4b526503e759e2bf09ada831afcba25cca3186e776df83b61951e748aecedd |
| outputs/hyp_gap_discovery_2022_2024_v1/SPY/detection_summary.json | 46ea66fac6f9670f3b32456e44e930b5a367b40208a9680adb4d75bf74500bc1 |

Run id: `HYP-GAP__discovery__SPY__1min__2022-01-01__2024-12-31__effda882f2143cc8`

Fingerprint: `effda882f2143cc8019d5227b4181839c3ab8449373d4e781bb6d3a3298652f0`

## Detection Summary

| Symbol | Sessions examined | Eligible sessions | Ineligible sessions | Event date range |
| --- | ---: | ---: | ---: | --- |
| QQQ | 753 | 732 | 21 | 2022-02-02 to 2024-12-30 |
| SPY | 753 | 730 | 23 | 2022-02-03 to 2024-12-30 |

| Symbol | missing_previous_session | insufficient_atr_warmup | excluded_session | invalid_gap_direction |
| --- | ---: | ---: | ---: | ---: |
| QQQ | 1 | 20 | 0 | 0 |
| SPY | 1 | 20 | 1 | 1 |

| Variant | QQQ events | SPY events | Combined events |
| --- | ---: | ---: | ---: |
| HYP-GAP-01 | 151 | 153 | 304 |
| HYP-GAP-02 | 134 | 143 | 277 |
| HYP-GAP-03 | 78 | 76 | 154 |
| HYP-GAP-04 | 0 | 0 | 0 |
| HYP-GAP-05 | 107 | 118 | 225 |
| HYP-GAP-06 | 26 | 16 | 42 |

No 2025 or 2026 events or result rows were present in the discovery outputs.

## Combined Results by Variant and Horizon

All return values below are directional future returns in basis points. Positive values mean the event moved in the preregistered expected direction for the variant.

| Variant | Horizon | Events | Mean bps | Median bps | Positive % | SD bps | SE bps | 95% CI bps |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| HYP-GAP-01 | 5min | 304 | -1.02 | 0.35 | 50.0% | 18.55 | 1.06 | -3.11 to 1.06 |
| HYP-GAP-01 | 15min | 304 | 3.82 | 4.37 | 59.5% | 27.87 | 1.60 | 0.69 to 6.95 |
| HYP-GAP-01 | 30min | 304 | 5.81 | 5.93 | 56.6% | 39.26 | 2.25 | 1.40 to 10.22 |
| HYP-GAP-01 | 60min | 304 | 2.25 | 3.88 | 53.9% | 52.72 | 3.02 | -3.68 to 8.17 |
| HYP-GAP-01 | session_close | 304 | 0.99 | 15.14 | 56.2% | 114.00 | 6.54 | -11.82 to 13.81 |
| HYP-GAP-02 | 5min | 277 | 0.49 | 1.65 | 54.2% | 14.80 | 0.89 | -1.25 to 2.24 |
| HYP-GAP-02 | 15min | 277 | 2.98 | 3.13 | 58.1% | 25.36 | 1.52 | -0.00 to 5.97 |
| HYP-GAP-02 | 30min | 277 | 6.35 | 7.40 | 58.1% | 35.40 | 2.13 | 2.18 to 10.52 |
| HYP-GAP-02 | 60min | 277 | 3.68 | 5.65 | 57.4% | 45.50 | 2.73 | -1.68 to 9.04 |
| HYP-GAP-02 | session_close | 277 | 9.62 | 13.53 | 56.7% | 98.52 | 5.92 | -1.99 to 21.22 |
| HYP-GAP-03 | 5min | 154 | 1.96 | 3.80 | 61.0% | 14.01 | 1.13 | -0.25 to 4.17 |
| HYP-GAP-03 | 15min | 154 | 6.51 | 6.90 | 63.6% | 26.92 | 2.17 | 2.26 to 10.76 |
| HYP-GAP-03 | 30min | 154 | 13.63 | 15.96 | 67.5% | 36.64 | 2.95 | 7.84 to 19.42 |
| HYP-GAP-03 | 60min | 154 | 11.91 | 12.07 | 65.6% | 42.63 | 3.44 | 5.18 to 18.65 |
| HYP-GAP-03 | session_close | 154 | 12.83 | 14.65 | 57.1% | 95.68 | 7.71 | -2.28 to 27.94 |
| HYP-GAP-04 | 5min | 0 |  |  |  |  |  |  |
| HYP-GAP-04 | 15min | 0 |  |  |  |  |  |  |
| HYP-GAP-04 | 30min | 0 |  |  |  |  |  |  |
| HYP-GAP-04 | 60min | 0 |  |  |  |  |  |  |
| HYP-GAP-04 | session_close | 0 |  |  |  |  |  |  |
| HYP-GAP-05 | 5min | 225 | 1.68 | 1.38 | 52.4% | 17.84 | 1.19 | -0.65 to 4.01 |
| HYP-GAP-05 | 15min | 225 | -3.19 | -3.14 | 44.4% | 28.69 | 1.91 | -6.94 to 0.56 |
| HYP-GAP-05 | 30min | 225 | -4.98 | -6.23 | 42.2% | 42.61 | 2.84 | -10.54 to 0.59 |
| HYP-GAP-05 | 60min | 225 | 0.78 | 4.58 | 53.8% | 56.96 | 3.80 | -6.66 to 8.22 |
| HYP-GAP-05 | session_close | 225 | 8.78 | -0.18 | 49.8% | 112.49 | 7.50 | -5.92 to 23.48 |
| HYP-GAP-06 | 5min | 42 | 0.61 | -0.91 | 45.2% | 13.50 | 2.08 | -3.47 to 4.70 |
| HYP-GAP-06 | 15min | 42 | -3.13 | 0.55 | 52.4% | 26.67 | 4.12 | -11.20 to 4.94 |
| HYP-GAP-06 | 30min | 42 | -1.33 | -5.98 | 40.5% | 36.60 | 5.65 | -12.40 to 9.74 |
| HYP-GAP-06 | 60min | 42 | 0.88 | -1.18 | 50.0% | 54.24 | 8.37 | -15.52 to 17.29 |
| HYP-GAP-06 | session_close | 42 | 1.69 | 13.91 | 52.4% | 94.73 | 14.62 | -26.96 to 30.34 |

## Symbol Comparison

Session-close directional returns by symbol:

| Symbol | Variant | Events | Mean bps | Median bps | Positive % |
| --- | --- | ---: | ---: | ---: | ---: |
| QQQ | HYP-GAP-01 | 151 | 1.41 | 20.40 | 57.6% |
| QQQ | HYP-GAP-02 | 134 | 8.04 | 12.27 | 55.2% |
| QQQ | HYP-GAP-03 | 78 | 12.55 | 16.27 | 57.7% |
| QQQ | HYP-GAP-05 | 107 | 6.86 | 3.71 | 50.5% |
| QQQ | HYP-GAP-06 | 26 | 6.63 | 28.39 | 61.5% |
| SPY | HYP-GAP-01 | 153 | 0.58 | 10.91 | 54.9% |
| SPY | HYP-GAP-02 | 143 | 11.09 | 13.81 | 58.0% |
| SPY | HYP-GAP-03 | 76 | 13.11 | 14.27 | 56.6% |
| SPY | HYP-GAP-05 | 118 | 10.52 | -0.20 | 49.2% |
| SPY | HYP-GAP-06 | 16 | -6.34 | -5.37 | 37.5% |

## Year Stability

Session-close directional returns by calendar year:

| Year | Variant | Events | Mean bps | Median bps | Positive % |
| --- | --- | ---: | ---: | ---: | ---: |
| 2022 | HYP-GAP-01 | 82 | 9.75 | 47.26 | 61.0% |
| 2022 | HYP-GAP-02 | 88 | 32.20 | 35.51 | 64.8% |
| 2022 | HYP-GAP-03 | 50 | 45.26 | 45.52 | 74.0% |
| 2022 | HYP-GAP-05 | 60 | 23.03 | 36.99 | 56.7% |
| 2022 | HYP-GAP-06 | 14 | -7.56 | 18.32 | 50.0% |
| 2023 | HYP-GAP-01 | 99 | -2.01 | 15.45 | 56.6% |
| 2023 | HYP-GAP-02 | 79 | -13.85 | -14.41 | 45.6% |
| 2023 | HYP-GAP-03 | 46 | -14.63 | -18.15 | 45.7% |
| 2023 | HYP-GAP-05 | 86 | 8.03 | -2.42 | 46.5% |
| 2023 | HYP-GAP-06 | 16 | 6.32 | -0.96 | 43.8% |
| 2024 | HYP-GAP-01 | 123 | -2.43 | 3.80 | 52.8% |
| 2024 | HYP-GAP-02 | 110 | 8.41 | 11.57 | 58.2% |
| 2024 | HYP-GAP-03 | 58 | 6.64 | 4.78 | 51.7% |
| 2024 | HYP-GAP-05 | 79 | -1.22 | -0.34 | 48.1% |
| 2024 | HYP-GAP-06 | 12 | 6.31 | 20.24 | 66.7% |

No variant showed clean monotonic stability across all three discovery years at session close. HYP-GAP-03 had the strongest intraday horizon evidence, but its 2023 session-close result was negative.

## Concentration and Outlier Checks

| Variant | Events | Largest year | Largest-year events | Largest-year share |
| --- | ---: | --- | ---: | ---: |
| HYP-GAP-01 | 304 | 2024 | 123 | 40.5% |
| HYP-GAP-02 | 277 | 2024 | 110 | 39.7% |
| HYP-GAP-03 | 154 | 2024 | 58 | 37.7% |
| HYP-GAP-04 | 0 | n/a | 0 | n/a |
| HYP-GAP-05 | 225 | 2023 | 86 | 38.2% |
| HYP-GAP-06 | 42 | 2023 | 16 | 38.1% |

Outlier sensitivity across all horizons:

| Variant | Result rows | Mean return | Median return | Min return | Max return | Max abs / abs mean |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| HYP-GAP-01 | 1520 | 0.000237 | 0.000375 | -0.054350 | 0.026646 | 229x |
| HYP-GAP-02 | 1385 | 0.000462 | 0.000414 | -0.037526 | 0.032792 | 81x |
| HYP-GAP-03 | 770 | 0.000937 | 0.000817 | -0.037526 | 0.028700 | 40x |
| HYP-GAP-05 | 1125 | 0.000061 | -0.000079 | -0.025952 | 0.054350 | 884x |
| HYP-GAP-06 | 210 | -0.000025 | -0.000085 | -0.021913 | 0.018139 | 861x |

The reversal variants were especially sensitive to small mean effects and outlier influence. HYP-GAP-05 had a positive session-close mean but a negative median and sub-50% positive rate, so it does not provide a clean reversal signal.

## Discovery Classification

| Variant | Family | Classification | Rationale |
| --- | --- | --- | --- |
| HYP-GAP-01 | Gap continuation | Inconclusive discovery | Adequate sample and positive 15min/30min evidence, but 5min mean was negative, 60min/session-close confidence intervals included zero, and yearly session-close stability was weak. |
| HYP-GAP-02 | Gap continuation | Inconclusive discovery | Adequate sample and positive 30min evidence, but session-close confidence interval included zero and 2023 session-close performance was negative. |
| HYP-GAP-03 | Gap continuation | Eligible for validation review only | Strongest discovery candidate: positive 15min/30min/60min means with confidence intervals above zero and consistent positive symbol-level session-close means. It still failed clean yearly stability at session close, so it is not approved beyond validation review. |
| HYP-GAP-04 | Gap reversal | Reject discovery | Zero detected events. |
| HYP-GAP-05 | Gap reversal | Reject discovery | Adequate sample, but the core 15min/30min horizons were negative and the session-close mean was not supported by median or positive-rate evidence. |
| HYP-GAP-06 | Gap reversal | Reject discovery | Small sample, weak mixed returns, SPY session-close result negative, and high outlier sensitivity. |

## Decision

No HYP-GAP variant is approved for replay, paper trading, live trading, or strategy deployment.

Only HYP-GAP-03 is eligible for a separate validation review, and that eligibility is limited to testing whether the discovery-period intraday continuation behavior survives out of sample. This does not authorize parameter optimization, retroactive threshold changes, strategy implementation, replay, paper trading, live trading, or broker connection.

No reversal-family variant is eligible for validation based on this discovery run.

## Methodological Notes

- The outputs are discovery event-study outputs, not backtest profitability results.
- No 2025 or 2026 data was used in discovery events or discovery results.
- The final holdout remains frozen and must not be used for parameter selection.
- TradingView may be used for visualization or prototyping, but DayTrade Lab curated CSVs, approved manifests, committed code, and reproducible outputs remain the source of truth.
- Any next validation step must be separately preregistered before execution.
