# Research Hypothesis Registry

This registry is the central methodological ledger for DayTrade Lab research hypotheses. It preserves rejected work and blocks retroactive parameter rescue.

Permanent safety state:

- live_trading=false
- broker_connected=false
- orders_sent=false
- paper_broker_enabled=false

| ID | Description | Preregistered | Discovery used | Validation used | Holdout status | Events/trades | Result | Final classification | Rejection reason | Related files | Reopen policy |
| --- | --- | --- | --- | --- | --- | ---: | --- | --- | --- | --- | --- |
| S2 | QQQ Multi-Timeframe Momentum | 2026-07-20 | QQQ 2022-2024 | Not opened | 2026 closed | 147 trades | Net PnL -USD 103.03; PF 0.602 | Rejected | Net negative and PF below threshold | `docs/QQQ_S2_S5_COMBO_RESEARCH_RESULTS.md`; `outputs/QQQ_S2_S5_COMBO` | Do not reopen by adjusting parameters retrospectively |
| S5 | QQQ Opening Range Breakout Retest | 2026-07-20 | QQQ 2022-2024 | Not opened | 2026 closed | 169 trades | Net PnL -USD 66.72; PF 0.730 | Rejected | Net negative and PF below threshold | `docs/QQQ_S2_S5_COMBO_RESEARCH_RESULTS.md`; `outputs/QQQ_S2_S5_COMBO` | Do not reopen by adjusting parameters retrospectively |
| S2+S5 | Combined QQQ S2/S5 modules | 2026-07-20 | QQQ 2022-2024 | Not opened | 2026 closed | 305 trades | Net PnL -USD 136.65; PF 0.712 | Rejected | Net negative and PF below threshold | `configs/research/hypotheses/QQQ-S2-S5-COMBO.yaml`; `docs/QQQ_S2_S5_COMBO_RESEARCH_RESULTS.md` | Do not reopen by changing module priority, stops, costs, or filters retrospectively |
| HYP-GAP-03 | Gap Continuation With Opening Follow-Through | 2026-07-13 | QQQ/SPY 2022-2024 | QQQ/SPY 2025 | 2026 closed | 154 discovery events; 62 validation events | 2025 mean returns: 5m -8.95 bps, 15m -13.09 bps, 30m -26.09 bps, 60m -12.76 bps | Rejected | Validation changed or weakened sign in core intraday horizons | `configs/research/hypotheses/HYP-GAP.yaml`; `docs/HYP_GAP_DISCOVERY_RESULTS.md`; `docs/HYP_GAP_03_VALIDATION_AND_REGIME_REVIEW.md` | Do not reopen by adding post hoc gap direction, normalized gap, Opening Range, quarter, or volatility filters |
| HYP-GAP-ASYM-01 | Gap-up/gap-down asymmetry event study | 2026-07-21 | QQQ/SPY 2022-2024 research pool | None clean; 2025 observed only as hypothesis generation | 2026 closed | 1462 events | Weak/mixed continuation and reversal effects | Rejected | Effect weak or unstable across symbols/years | `configs/research/hypotheses/HYP-GAP-ASYM-01.yaml`; `docs/HYP_GAP_ASYM_01_RETROSPECTIVE_RESULTS.md`; `outputs/next_gap_hypotheses_research_pool_v2/HYP-GAP-ASYM-01` | Do not reopen by selecting only favorable direction/horizon after seeing results |
| HYP-GAP-OR-01 | Gap direction by Opening Range width event study | 2026-07-21 | QQQ/SPY 2022-2024 research pool | None clean; 2025 observed only as hypothesis generation | 2026 closed | 1462 events | Weak/mixed OR bucket effects | Rejected | Effect weak or unstable across symbols/years | `configs/research/hypotheses/HYP-GAP-OR-01.yaml`; `docs/HYP_GAP_OR_01_RETROSPECTIVE_RESULTS.md`; `outputs/next_gap_hypotheses_research_pool_v2/HYP-GAP-OR-01` | Do not reopen by selecting only favorable OR/gap buckets after seeing results |

## Methodological Lock

Rejected hypotheses are closed as research records. Historical code and outputs remain preserved, but a rejected hypothesis cannot be made eligible again by changing thresholds, filters, time windows, symbols, costs, exits, stops, or execution assumptions after seeing results.

For HYP-GAP-ASYM-01 and HYP-GAP-OR-01, 2025 is already contaminated because it motivated the questions. The maximum classification available before genuinely new data is `elegible_para_futura_validacion`.
