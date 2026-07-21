# HYP-GAP-OR-01 Retrospective Results

Analysis label: retrospective discovery / research-pool analysis. This is not independent validation.

Classification: **rechazada**. Reason: efecto debil o inestable entre simbolos/anios.

Frozen tercile limits were calculated from 2022-2024 feature distributions before reading outcome summaries:

- opening_range_width_atr narrow <= 0.276246
- opening_range_width_atr wide >= 0.382232
- normalized_gap small <= 0.151423
- normalized_gap large >= 0.369072

2025 was previously observed during HYP-GAP-03 regime review, so it is hypothesis-generation evidence only. 2026 remains closed.

## Core Results

| gap_direction_label | opening_range_bucket | outcome | event_count | mean_return_bps | median_return_bps | positive |
| --- | --- | --- | --- | --- | --- | --- |
| gap_down | narrow | gap_continuation | 214 | 0.34 | 0.48 | 50.5% |
| gap_down | normal | gap_continuation | 220 | -0.44 | -3.76 | 46.8% |
| gap_down | wide | gap_continuation | 251 | -2.78 | -7.61 | 47.4% |
| gap_up | narrow | gap_continuation | 274 | 2.01 | 1.67 | 54.4% |
| gap_up | normal | gap_continuation | 266 | 2.06 | 2.16 | 53.4% |
| gap_up | wide | gap_continuation | 237 | -2.59 | -10.77 | 46.4% |
| gap_down | narrow | gap_reversal | 214 | -0.34 | -0.48 | 49.5% |
| gap_down | normal | gap_reversal | 220 | 0.44 | 3.76 | 52.7% |
| gap_down | wide | gap_reversal | 251 | 2.78 | 7.61 | 52.6% |
| gap_up | narrow | gap_reversal | 274 | -2.01 | -1.67 | 44.9% |
| gap_up | normal | gap_reversal | 266 | -2.06 | -2.16 | 46.2% |
| gap_up | wide | gap_reversal | 237 | 2.59 | 10.77 | 53.2% |

## Regime Results

| gap_direction_label | opening_range_bucket | gap_size_bucket | event_count | mean_return_bps | median_return_bps | positive |
| --- | --- | --- | --- | --- | --- | --- |
| gap_down | narrow | large | 52 | 1.50 | 1.14 | 53.8% |
| gap_down | narrow | medium | 78 | -1.08 | -1.64 | 46.2% |
| gap_down | narrow | small | 84 | 0.94 | 1.43 | 52.4% |
| gap_down | normal | large | 81 | 6.13 | 1.30 | 55.6% |
| gap_down | normal | medium | 68 | 3.50 | 9.65 | 55.9% |
| gap_down | normal | small | 71 | -11.70 | -17.27 | 28.2% |
| gap_down | wide | large | 89 | 4.44 | 17.39 | 56.2% |
| gap_down | wide | medium | 86 | -2.66 | -9.62 | 44.2% |
| gap_down | wide | small | 76 | -11.38 | -19.11 | 40.8% |
| gap_up | narrow | large | 74 | 4.76 | 5.55 | 59.5% |
| gap_up | narrow | medium | 97 | 1.60 | 1.96 | 53.6% |
| gap_up | narrow | small | 103 | 0.42 | 0.26 | 51.5% |
| gap_up | normal | large | 92 | 2.20 | 0.96 | 52.2% |
| gap_up | normal | medium | 83 | 5.47 | 7.64 | 59.0% |
| gap_up | normal | small | 91 | -1.19 | -0.00 | 49.5% |
| gap_up | wide | large | 100 | -8.93 | -21.31 | 40.0% |
| gap_up | wide | medium | 75 | 5.28 | 14.63 | 53.3% |
| gap_up | wide | small | 62 | -1.86 | -7.31 | 48.4% |

## Outputs

- `outputs\next_gap_hypotheses_research_pool_v2\HYP-GAP-OR-01\events.csv`
- `outputs\next_gap_hypotheses_research_pool_v2\HYP-GAP-OR-01\metrics.csv`
- `outputs\next_gap_hypotheses_research_pool_v2\HYP-GAP-OR-01\metrics_by_symbol.csv`
- `outputs\next_gap_hypotheses_research_pool_v2\HYP-GAP-OR-01\metrics_by_year.csv`
- `outputs\next_gap_hypotheses_research_pool_v2\HYP-GAP-OR-01\regime_results.csv`
- `outputs\next_gap_hypotheses_research_pool_v2\HYP-GAP-OR-01\outliers.csv`
- `outputs\next_gap_hypotheses_research_pool_v2\HYP-GAP-OR-01\mfe_mae.csv`
- `outputs\next_gap_hypotheses_research_pool_v2\HYP-GAP-OR-01\run_manifest.json`
