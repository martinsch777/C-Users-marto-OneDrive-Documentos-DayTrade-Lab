# HYP-GAP-ASYM-01 Retrospective Results

Analysis label: retrospective discovery / research-pool analysis. This is not independent validation.

Classification: **rechazada**. Reason: efecto debil o inestable entre simbolos/anios.

2025 was previously observed during HYP-GAP-03 validation and regime review, so it is hypothesis-generation evidence only. 2026 remains closed.

## Core Results

| gap_direction_label | outcome | horizon | event_count | mean_return_bps | median_return_bps | positive |
| --- | --- | --- | --- | --- | --- | --- |
| gap_down | gap_continuation | 15min | 685 | -1.74 | -3.15 | 44.5% |
| gap_up | gap_continuation | 15min | 777 | -0.38 | 0.92 | 51.2% |
| gap_down | gap_continuation | 30min | 685 | -1.05 | -2.06 | 48.2% |
| gap_up | gap_continuation | 30min | 777 | 0.63 | 0.88 | 51.6% |
| gap_down | gap_continuation | 60min | 685 | -0.89 | -2.20 | 48.0% |
| gap_up | gap_continuation | 60min | 777 | 0.15 | 2.07 | 52.0% |
| gap_down | gap_continuation | session_close | 685 | 0.16 | -2.68 | 47.7% |
| gap_up | gap_continuation | session_close | 777 | 5.58 | 11.99 | 55.6% |
| gap_down | gap_reversal | 15min | 685 | 1.74 | 3.15 | 55.3% |
| gap_up | gap_reversal | 15min | 777 | 0.38 | -0.92 | 48.5% |
| gap_down | gap_reversal | 30min | 685 | 1.05 | 2.06 | 51.7% |
| gap_up | gap_reversal | 30min | 777 | -0.63 | -0.88 | 47.9% |
| gap_down | gap_reversal | 60min | 685 | 0.89 | 2.20 | 51.8% |
| gap_up | gap_reversal | 60min | 777 | -0.15 | -2.07 | 47.7% |
| gap_down | gap_reversal | session_close | 685 | -0.16 | 2.68 | 52.1% |
| gap_up | gap_reversal | session_close | 777 | -5.58 | -11.99 | 44.4% |

## Symbol Check

| symbol | gap_direction_label | outcome | event_count | mean_return_bps | median_return_bps | positive |
| --- | --- | --- | --- | --- | --- | --- |
| QQQ | gap_down | gap_continuation | 349 | -0.10 | -1.73 | 48.7% |
| QQQ | gap_up | gap_continuation | 383 | 0.80 | 1.47 | 52.2% |
| SPY | gap_down | gap_continuation | 336 | -2.04 | -2.92 | 47.6% |
| SPY | gap_up | gap_continuation | 394 | 0.46 | 0.59 | 51.0% |
| QQQ | gap_down | gap_reversal | 349 | 0.10 | 1.73 | 51.0% |
| QQQ | gap_up | gap_reversal | 383 | -0.80 | -1.47 | 47.8% |
| SPY | gap_down | gap_reversal | 336 | 2.04 | 2.92 | 52.4% |
| SPY | gap_up | gap_reversal | 394 | -0.46 | -0.59 | 48.0% |

## Outputs

- `outputs\next_gap_hypotheses_research_pool_v2\HYP-GAP-ASYM-01\events.csv`
- `outputs\next_gap_hypotheses_research_pool_v2\HYP-GAP-ASYM-01\metrics.csv`
- `outputs\next_gap_hypotheses_research_pool_v2\HYP-GAP-ASYM-01\metrics_by_symbol.csv`
- `outputs\next_gap_hypotheses_research_pool_v2\HYP-GAP-ASYM-01\metrics_by_year.csv`
- `outputs\next_gap_hypotheses_research_pool_v2\HYP-GAP-ASYM-01\outliers.csv`
- `outputs\next_gap_hypotheses_research_pool_v2\HYP-GAP-ASYM-01\mfe_mae.csv`
- `outputs\next_gap_hypotheses_research_pool_v2\HYP-GAP-ASYM-01\run_manifest.json`
