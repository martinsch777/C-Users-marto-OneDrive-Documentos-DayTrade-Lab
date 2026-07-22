# HYP-REL-01 Intraday Relative Divergence Results

## Reuse Audit

| Componente necesario | Codigo reutilizable | Archivo | Cambio requerido |
| --- | --- | --- | --- |
| OHLCV loading and validation | `load_csv` | `src/data/loader.py` | Reused |
| US equity RTH calendar, holidays, early closes, DST | `EquitySessionCalendar` | `src/data/sessions.py` | Reused |
| 1m to 5m RTH resampling | `resample_rth_1min_to_5min` | `src/research/qqq_s2_s5.py` | Reused |
| Dataset hashes/manifests | `sha256_file` and manifest records | `src/data/dataset_manifest.py` | Reused |
| Event-study style aggregation | mean/median/CI/bootstrap pattern | `src/research/event_study.py`; prior research runners | New relative-return wrapper |
| Reports and manifests | CSV/JSON/Markdown pattern | prior research runners | New HYP-REL-01 runner |

## Contamination Audit

2025 classification: **validation_elegible_with_documented_conceptual_prior**.

The audit found no prior calculated QQQ/SPY spread, QQQ minus SPY relative return event study, intraday beta, divergence z-score, or relative convergence/continuation result. A protocol document mentioned QQQ/SPY cross-confirmation/divergence conceptually, so the prior is documented, but 2025 remains methodologically eligible if discovery passes.

## Discovery Decision

Classification: **exploratoria_e_insuficiente**.

Reason: hay senal parcial, pero no cumple estabilidad/costos/direcciones.

Validation was not executed because discovery did not pass the preregistered gate.

## Discovery Core Metrics

| interpretation | horizon | event_count | mean_bps | median_bps | favorable |
| --- | --- | --- | --- | --- | --- |
| mean_reversion | 5min | 840 | 0.16 | 0.15 | 51.4% |
| mean_reversion | 15min | 840 | 0.09 | 0.33 | 51.8% |
| mean_reversion | 30min | 840 | 0.18 | 0.25 | 51.2% |
| mean_reversion | 60min | 840 | 0.39 | 0.26 | 50.8% |
| mean_reversion | session_close | 840 | 0.92 | 1.07 | 51.8% |
| continuation | 5min | 840 | -0.16 | -0.15 | 48.6% |
| continuation | 15min | 840 | -0.09 | -0.33 | 48.2% |
| continuation | 30min | 840 | -0.18 | -0.25 | 48.8% |
| continuation | 60min | 840 | -0.39 | -0.26 | 49.2% |
| continuation | session_close | 840 | -0.92 | -1.07 | 48.2% |

## Direction Stability

| direction | interpretation | event_count | mean_bps | median_bps | favorable |
| --- | --- | --- | --- | --- | --- |
| qqq_overperformance | mean_reversion | 437 | -0.05 | 0.18 | 51.3% |
| qqq_underperformance | mean_reversion | 403 | 0.42 | 0.31 | 51.1% |
| qqq_overperformance | continuation | 437 | 0.05 | -0.18 | 48.7% |
| qqq_underperformance | continuation | 403 | -0.42 | -0.31 | 48.9% |

## Year Stability

| year | event_count | mean_bps | median_bps | favorable |
| --- | --- | --- | --- | --- |
| 2022 | 260 | 0.73 | 0.19 | 50.8% |
| 2023 | 288 | 0.21 | 0.90 | 54.2% |
| 2024 | 292 | -0.35 | -0.14 | 48.6% |

## Two-Leg Cost Relevance

| interpretation | scenario | two_leg_friction_bps | gross_mean_bps | gross_median_bps | net_mean_bps | net_median_bps |
| --- | --- | --- | --- | --- | --- | --- |
| mean_reversion | low | 2.9 | 0.18 | 0.25 | -2.72 | -2.65 |
| mean_reversion | normal | 6.0 | 0.18 | 0.25 | -5.82 | -5.75 |
| mean_reversion | high | 12.0 | 0.18 | 0.25 | -11.82 | -11.75 |
| continuation | low | 2.9 | -0.18 | -0.25 | -3.08 | -3.15 |
| continuation | normal | 6.0 | -0.18 | -0.25 | -6.18 | -6.25 |
| continuation | high | 12.0 | -0.18 | -0.25 | -12.18 | -12.25 |

## Holdout 2026

2026 remains closed:

- 0 events of 2026.
- 0 metrics of 2026.
- 0 thresholds calculated with 2026.
- 0 charts with 2026.
- 0 decisions based on 2026.

## Outputs

- `outputs\hyp_rel_01_intraday_divergence_v1\discovery\events.csv`
- `outputs\hyp_rel_01_intraday_divergence_v1\discovery\metrics.csv`
- `outputs\hyp_rel_01_intraday_divergence_v1\discovery\metrics_by_direction.csv`
- `outputs\hyp_rel_01_intraday_divergence_v1\discovery\metrics_by_year.csv`
- `outputs\hyp_rel_01_intraday_divergence_v1\discovery\metrics_by_month.csv`
- `outputs\hyp_rel_01_intraday_divergence_v1\discovery\metrics_by_time_of_day.csv`
- `outputs\hyp_rel_01_intraday_divergence_v1\discovery\outliers.csv`
- `outputs\hyp_rel_01_intraday_divergence_v1\discovery\mfe_mae.csv`
- `outputs\hyp_rel_01_intraday_divergence_v1\discovery\cost_relevance.csv`
- `outputs\hyp_rel_01_intraday_divergence_v1\discovery\blocked_events.csv`
- `outputs\hyp_rel_01_intraday_divergence_v1\discovery\config.json`
- `outputs\hyp_rel_01_intraday_divergence_v1\discovery\run_manifest.json`

## Commands

- `.\.venv\Scripts\python.exe -m unittest discover -s tests`
- `.\.venv\Scripts\python.exe -m src.research.hyp_rel_01 --output-root outputs\hyp_rel_01_intraday_divergence_v1`
- `git diff --check`
- `git status --short`

## Safety

- live_trading=false
- broker_connected=false
- orders_sent=false
- paper_broker_enabled=false
