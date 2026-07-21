# HYP-GAP-03 Validation and Regime Review

## Executive Decision

Methodological audit conclusion: `habilitada_para_validation`.

Final classification: **Rechazada**.

Reason: validation cambió o debilitó el signo en horizontes intradiarios centrales.

This remains an event study only. It does not authorize replay, paper trading, live trading, broker connection, strategy parameters, stops, entries, exits, or order routing.

Holdout status: **closed**. No 2026 events, returns, charts, summaries, or holdout results were generated or inspected.

## Pre-Validation Audit

- HYP-GAP-03 was present in the 2026-07-13 preregistration commit before the discovery report.
- The HYP-GAP YAML has no post-discovery diff against current HEAD before this task's validation infrastructure edits.
- Discovery outputs for QQQ and SPY end at 2024-12-30 and contain no 2025/2026 result rows.
- Validation is limited to 2025-01-01 through 2025-12-31.
- Final holdout is 2026-01-01 through 2026-07-06 and remains closed.
- Safety flags are false: `live_trading`, `broker_connected`, `orders_sent`, `paper_broker_enabled`.

Audit risks reviewed: lookahead, survivorship/data selection, post hoc selection, discovery-validation leakage, double-counting, incomplete sessions, warm-up, early closes, exclusions, and accidental holdout use. No serious blocker was found for opening validation 2025.

## Frozen Definition

Freeze manifest: `outputs\hyp_gap_03_validation_2025_v1\pre_validation_freeze_manifest.json`

Freeze hash: `dd7f7dfb358d9690b6d23851b4d25c2f57e763a61ad0fc3339175f33363aa9f1`

Frozen event:

- Variant: HYP-GAP-03, Gap Continuation With Opening Follow-Through.
- Confirmation: 09:45 America/New_York, event price is the confirmation bar close.
- Conditions: `normalized_gap >= 0.35`, opening return same sign as gap, `opening_move_atr >= 0.10`.
- Expected direction: `gap_direction`.
- Symbols: QQQ, SPY.
- Horizons: 5min, 15min, 30min, 60min, session_close.

## Discovery vs Validation

Directional returns are in bps. Positive means movement in the preregistered HYP-GAP-03 direction.

| period | horizon | event_count | mean_bps | median_bps | positive | bootstrap_ci_bps |
| --- | --- | --- | --- | --- | --- | --- |
| discovery | 15min | 154 | 6.51 | 6.90 | 63.6% | 0.06 to 9.92 |
| discovery | 30min | 154 | 13.63 | 15.96 | 67.5% | 4.48 to 17.62 |
| discovery | 5min | 154 | 1.96 | 3.80 | 61.0% | -1.08 to 3.95 |
| discovery | 60min | 154 | 11.91 | 12.07 | 65.6% | 1.82 to 17.61 |
| discovery | session_close | 154 | 12.83 | 14.65 | 57.1% | -6.16 to 30.75 |
| validation | 15min | 62 | -13.09 | 0.08 | 50.0% | -28.78 to 6.33 |
| validation | 30min | 62 | -26.09 | -3.12 | 45.2% | -62.85 to 11.64 |
| validation | 5min | 62 | -8.95 | -3.31 | 40.3% | -17.02 to -1.22 |
| validation | 60min | 62 | -12.76 | 3.67 | 56.5% | -35.91 to 16.21 |
| validation | session_close | 62 | -10.01 | 23.00 | 58.1% | -50.48 to 24.08 |

## Symbol Stability

| period | symbol | horizon | event_count | mean_bps | median_bps | positive |
| --- | --- | --- | --- | --- | --- | --- |
| discovery | QQQ | 15min | 78 | 7.46 | 7.83 | 61.5% |
| discovery | QQQ | 30min | 78 | 14.29 | 15.38 | 62.8% |
| discovery | QQQ | 5min | 78 | 1.71 | 5.32 | 56.4% |
| discovery | QQQ | 60min | 78 | 13.82 | 18.67 | 65.4% |
| discovery | QQQ | session_close | 78 | 12.55 | 16.27 | 57.7% |
| discovery | SPY | 15min | 76 | 5.54 | 6.90 | 65.8% |
| discovery | SPY | 30min | 76 | 12.95 | 15.96 | 72.4% |
| discovery | SPY | 5min | 76 | 2.22 | 3.46 | 65.8% |
| discovery | SPY | 60min | 76 | 9.96 | 9.16 | 65.8% |
| discovery | SPY | session_close | 76 | 13.11 | 14.27 | 56.6% |
| validation | QQQ | 15min | 33 | -15.36 | 0.80 | 51.5% |
| validation | QQQ | 30min | 33 | -29.60 | -5.65 | 45.5% |
| validation | QQQ | 5min | 33 | -10.46 | -3.13 | 39.4% |
| validation | QQQ | 60min | 33 | -15.24 | 4.65 | 54.5% |
| validation | QQQ | session_close | 33 | -15.93 | 13.38 | 54.5% |
| validation | SPY | 15min | 29 | -10.51 | -0.29 | 48.3% |
| validation | SPY | 30min | 29 | -22.09 | -2.06 | 44.8% |
| validation | SPY | 5min | 29 | -7.24 | -3.50 | 41.4% |
| validation | SPY | 60min | 29 | -9.94 | 2.68 | 58.6% |
| validation | SPY | session_close | 29 | -3.28 | 23.69 | 62.1% |

## Validation Monthly And Quarterly Stability

Monthly validation results are stored in `outputs\hyp_gap_03_validation_2025_v1\validation_monthly_results.csv`.

| quarter | horizon | event_count | mean_bps | median_bps | positive |
| --- | --- | --- | --- | --- | --- |
| 2025Q1 | 15min | 17 | -2.12 | 2.01 | 52.9% |
| 2025Q1 | 30min | 17 | -2.40 | 13.72 | 52.9% |
| 2025Q1 | 5min | 17 | 1.16 | 7.35 | 52.9% |
| 2025Q1 | 60min | 17 | -6.06 | 8.96 | 64.7% |
| 2025Q1 | session_close | 17 | 4.05 | 33.82 | 76.5% |
| 2025Q2 | 15min | 13 | -54.66 | -7.00 | 23.1% |
| 2025Q2 | 30min | 13 | -109.05 | -11.49 | 30.8% |
| 2025Q2 | 5min | 13 | -24.39 | -7.27 | 38.5% |
| 2025Q2 | 60min | 13 | -40.35 | 4.65 | 53.8% |
| 2025Q2 | session_close | 13 | -61.50 | -24.98 | 46.2% |
| 2025Q3 | 15min | 17 | 8.05 | 9.26 | 76.5% |
| 2025Q3 | 30min | 17 | 2.87 | 0.16 | 52.9% |
| 2025Q3 | 5min | 17 | -3.07 | 0.48 | 52.9% |
| 2025Q3 | 60min | 17 | -7.53 | -24.68 | 47.1% |
| 2025Q3 | session_close | 17 | -0.64 | -3.20 | 47.1% |
| 2025Q4 | 15min | 15 | -13.48 | -5.16 | 40.0% |
| 2025Q4 | 30min | 15 | -13.85 | -2.06 | 40.0% |
| 2025Q4 | 5min | 15 | -13.71 | -14.69 | 13.3% |
| 2025Q4 | 60min | 15 | -2.37 | 6.97 | 60.0% |
| 2025Q4 | session_close | 15 | 8.05 | 34.38 | 60.0% |

## Regime Event Study

Regime cuts for normalized gap, gap percent, volatility, early volume, and opening range were estimated from discovery only. These regime tables are exploratory diagnostics, not new validation filters.

Validation 30min regime snapshot:

| regime_dimension | regime_bucket | event_count | mean_bps | median_bps | positive |
| --- | --- | --- | --- | --- | --- |
| gap_direction_label | gap_down | 25 | -73.88 | -40.36 | 24.0% |
| gap_direction_label | gap_up | 37 | 6.20 | 6.58 | 59.5% |
| normalized_gap_bucket | normalized_gap_high | 21 | -74.05 | -7.90 | 38.1% |
| normalized_gap_bucket | normalized_gap_low | 21 | 6.04 | 0.16 | 52.4% |
| normalized_gap_bucket | normalized_gap_mid | 20 | -9.46 | -3.19 | 45.0% |
| volatility_bucket | volatility_high | 41 | -40.46 | -7.90 | 41.5% |
| volatility_bucket | volatility_low | 5 | -11.51 | -10.65 | 20.0% |
| volatility_bucket | volatility_mid | 16 | 6.18 | 9.97 | 62.5% |
| relative_volume_bucket | early_volume_high | 28 | -54.83 | -11.07 | 39.3% |
| relative_volume_bucket | early_volume_low | 17 | -8.61 | -14.71 | 47.1% |
| relative_volume_bucket | early_volume_normal | 17 | 3.78 | 1.77 | 52.9% |
| opening_range_bucket | opening_range_narrow | 16 | -0.40 | 2.26 | 50.0% |
| opening_range_bucket | opening_range_normal | 19 | 6.09 | 1.77 | 57.9% |
| opening_range_bucket | opening_range_wide | 27 | -63.96 | -27.50 | 33.3% |
| gap_fill_relation_0930_0945 | no_fill_follow_through | 3 | 1.16 | 8.12 | 66.7% |
| gap_fill_relation_0930_0945 | partial_fill_no_full | 59 | -27.47 | -4.18 | 44.1% |
| day_of_week | Friday | 18 | 12.62 | -4.91 | 38.9% |
| day_of_week | Monday | 18 | -79.46 | 11.53 | 66.7% |
| day_of_week | Thursday | 11 | -34.43 | -39.83 | 18.2% |
| day_of_week | Tuesday | 6 | -13.50 | -16.50 | 16.7% |
| day_of_week | Wednesday | 9 | 5.03 | 8.12 | 66.7% |
| symbol | QQQ | 33 | -29.60 | -5.65 | 45.5% |
| symbol | SPY | 29 | -22.09 | -2.06 | 44.8% |
| quarter | 2025Q1 | 17 | -2.40 | 13.72 | 52.9% |
| quarter | 2025Q2 | 13 | -109.05 | -11.49 | 30.8% |
| quarter | 2025Q3 | 17 | 2.87 | 0.16 | 52.9% |
| quarter | 2025Q4 | 15 | -13.85 | -2.06 | 40.0% |

Full regime output: `outputs\hyp_gap_03_validation_2025_v1\regime_results.csv`.

Validation event count by gap direction:

| gap_direction_label | symbol | events |
| --- | --- | --- |
| gap_down | QQQ | 13 |
| gap_down | SPY | 12 |
| gap_up | QQQ | 20 |
| gap_up | SPY | 17 |

## Outliers And Winsorization

| period | horizon | events | mean_bps | winsor_mean_bps | change_bps | top3_share_of_total_return | bottom3_share_of_total_return |
| --- | --- | --- | --- | --- | --- | --- | --- |
| discovery | 15min | 154 | 6.51 | 7.17 | 0.66 | 0.1914101720986029 | -0.2231328931403813 |
| discovery | 30min | 154 | 13.63 | 13.11 | -0.51 | 0.1596901880751964 | -0.1053072389903755 |
| discovery | 5min | 154 | 1.96 | 2.12 | 0.16 | 0.3113829216956916 | -0.4333563264385346 |
| discovery | 60min | 154 | 11.91 | 11.56 | -0.36 | 0.2222298042696491 | -0.1454572703869552 |
| discovery | session_close | 154 | 12.83 | 14.71 | 1.89 | 0.3965076148203076 | -0.4482784710407878 |
| validation | 15min | 62 | -13.09 | -5.44 | 7.65 | -0.2262889331465428 | 0.8715670413305555 |
| validation | 30min | 62 | -26.09 | -5.51 | 20.58 | -0.1743817102230656 | 0.9763055177996004 |
| validation | 5min | 62 | -8.95 | -6.86 | 2.09 | -0.1675163765885693 | 0.5335919051430082 |
| validation | 60min | 62 | -12.76 | -5.56 | 7.20 | -0.4814373005862596 | 1.1871356592944151 |
| validation | session_close | 62 | -10.01 | -10.15 | -0.14 | -1.1607147494878252 | 1.9008542048516277 |

Best/worst event details are stored in `outputs\hyp_gap_03_validation_2025_v1\outlier_events.csv`.

## Economic Relevance

No trading strategy was implemented. The table below subtracts conservative illustrative frictions from the gross event movement to judge whether the raw effect is large enough to merit a future strategy preregistration.

| horizon | gross_mean_bps | gross_median_bps | friction_bps | mean_after_friction_bps | median_after_friction_bps | gross_mean_exceeds_friction | gross_median_exceeds_friction |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 15min | -13.09 | 0.08 | 2.0 | -15.09 | -1.92 | False | False |
| 15min | -13.09 | 0.08 | 5.0 | -18.09 | -4.92 | False | False |
| 15min | -13.09 | 0.08 | 10.0 | -23.09 | -9.92 | False | False |
| 30min | -26.09 | -3.12 | 2.0 | -28.09 | -5.12 | False | False |
| 30min | -26.09 | -3.12 | 5.0 | -31.09 | -8.12 | False | False |
| 30min | -26.09 | -3.12 | 10.0 | -36.09 | -13.12 | False | False |
| 5min | -8.95 | -3.31 | 2.0 | -10.95 | -5.31 | False | False |
| 5min | -8.95 | -3.31 | 5.0 | -13.95 | -8.31 | False | False |
| 5min | -8.95 | -3.31 | 10.0 | -18.95 | -13.31 | False | False |
| 60min | -12.76 | 3.67 | 2.0 | -14.76 | 1.67 | False | True |
| 60min | -12.76 | 3.67 | 5.0 | -17.76 | -1.33 | False | False |
| 60min | -12.76 | 3.67 | 10.0 | -22.76 | -6.33 | False | False |
| session_close | -10.01 | 23.00 | 2.0 | -12.01 | 21.00 | False | True |
| session_close | -10.01 | 23.00 | 5.0 | -15.01 | 18.00 | False | True |
| session_close | -10.01 | 23.00 | 10.0 | -20.01 | 13.00 | False | True |

MFE/MAE event-level diagnostics are stored in `outputs\hyp_gap_03_validation_2025_v1\mfe_mae_events.csv`.

## Confirmatory vs Exploratory

Confirmatory:

- Same frozen HYP-GAP-03 event definition.
- Same symbols and horizons.
- Validation period fixed to calendar year 2025.
- Primary comparison of discovery vs validation directional returns by horizon and symbol.

Exploratory:

- Regime breakdowns.
- MFE/MAE diagnostics.
- Winsorization sensitivity.
- Conservative friction comparison.
- Any future strategy idea derived from these observations.

## Outputs

- `outputs\hyp_gap_03_validation_2025_v1\pre_validation_methodology_audit.json`
- `outputs\hyp_gap_03_validation_2025_v1\pre_validation_freeze_manifest.json`
- `outputs\hyp_gap_03_validation_2025_v1\combined_events.csv`
- `outputs\hyp_gap_03_validation_2025_v1\combined_event_results.csv`
- `outputs\hyp_gap_03_validation_2025_v1\comparison_discovery_validation.csv`
- `outputs\hyp_gap_03_validation_2025_v1\validation_monthly_results.csv`
- `outputs\hyp_gap_03_validation_2025_v1\validation_quarterly_stability.csv`
- `outputs\hyp_gap_03_validation_2025_v1\regime_results.csv`
- `outputs\hyp_gap_03_validation_2025_v1\outlier_winsorization.csv`
- `outputs\hyp_gap_03_validation_2025_v1\economic_relevance.csv`

## Next Scientific Step

If the event is used further, the next task should be a new independent preregistration for a tradable strategy. It must separate event definition, entry timing, stop, exit, sizing, costs, and approval criteria, and it must not reuse 2025 to optimize those parameters.
