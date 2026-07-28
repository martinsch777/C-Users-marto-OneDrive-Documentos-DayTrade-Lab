# Next Research Priority

Audit date: 2026-07-28

Repository audit commit: `1c3b3b56153d2a067f14eea688b5c9d86540f0f2`

Scope: research governance and planning only. This audit did not execute OHLC,
open 2025 or 2026, change frozen hypotheses, optimize parameters, create a
strategy, or authorize paper/live trading.

## 1. Global Project State

The central registry has 15 rows: 14 hypothesis or strategy records and one
family-control record (`FCR-REFINEMENT-FAMILY-01`). The broader documentation
contains 44 identifiable hypothesis/rule records and four infrastructure or
family-control records. The difference is material: the registry is not yet a
complete project inventory.

Of the 44 hypothesis/rule records:

| Lifecycle state | Count |
| --- | ---: |
| Executed and closed/rejected | 27 |
| Executed, diagnostic only, no promotion | 2 |
| Executed historically, now forward-only lead | 2 |
| Conceptual family requiring full preregistration | 3 |
| Missing required alternative-data history | 10 |
| Ready to execute now (category A) | 0 |

The lifecycle rows are disjoint and sum to 44. The first three rows account for
the 31 records with historical execution; the ten alternative-data records were
not executed.

Fully preregistered and genuinely not executed: **0**. The preparation statuses
still present in several YAML files are stale metadata, not pending research.
There are three protocol-level concepts not yet fully preregistered:
HYP-DRIVE-PB, HYP-VWAP-DEV, and HYP-CROSS.

Permanent operational state:

| Control | State |
| --- | --- |
| Live trading | `false` |
| Broker connected | `false` |
| Orders sent | `false` |
| Paper broker enabled | `false` |
| Paper eligible hypotheses | 0 |
| Live eligible hypotheses | 0 |

## 2. Complete Inventory

Audit aliases beginning with `LEGACY-` are labels used only in this report to
make unregistered work traceable. They are not new registered hypothesis IDs.
`P` means preregistered, `E` means executed, and `N/A` means the stage does not
apply.

### 2.1 Identity And Scope

| Hypothesis ID | Name | Family | Asset/symbol | Timeframe | Type |
| --- | --- | --- | --- | --- | --- |
| S2 | Multi-Timeframe Momentum | Momentum | QQQ | 1m input; 5m/60m signals | strategy |
| S5 | Opening Range Breakout Retest | Opening Range | QQQ | 1m input; 5m | strategy |
| S2+S5 | Combined S2/S5 modules | Momentum + OR | QQQ | 1m input; 5m/60m | strategy |
| HYP-GAP-01 | Large Gap Holds Previous Close | Gap continuation | QQQ/SPY | 1m; event at 09:45 | event_study |
| HYP-GAP-02 | Gap Continuation With VWAP Acceptance | Gap continuation | QQQ/SPY | 1m; event at 09:45 | event_study |
| HYP-GAP-03 | Gap Continuation With Opening Follow-Through | Gap continuation | QQQ/SPY | 1m; event at 09:45 | event_study |
| HYP-GAP-04 | Large Gap Rejected Through Previous Close | Gap reversal | QQQ/SPY | 1m; event at 09:45 | event_study |
| HYP-GAP-05 | Gap Reversal With VWAP Rejection | Gap reversal | QQQ/SPY | 1m; event at 09:45 | event_study |
| HYP-GAP-06 | Gap Reversal With Weak Participation | Gap reversal | QQQ/SPY | 1m; event at 09:45 | event_study |
| HYP-GAP-ASYM-01 | Gap-up/gap-down asymmetry | Gap | QQQ/SPY | 1m intraday horizons | event_study |
| HYP-GAP-OR-01 | Gap direction by OR width | Gap + OR | QQQ/SPY | 1m intraday horizons | event_study |
| HYP-REL-01 | Intraday Relative Divergence | Relative QQQ/SPY | QQQ/SPY | 1m source; 5m research | event_study |
| HYP-FCR-01 | OR 30m + FVG reentry | First Candle | QQQ/SPY | 1m source; 5m signals | strategy |
| HYP-FCR-02 | Near-sweep FVG confirmation | First Candle refinement | QQQ/SPY | 1m source; 5m signals | strategy |
| HYP-FCR-03 | Strict one-tick sweep | First Candle refinement | QQQ/SPY | 1m source; 5m signals | strategy |
| HYP-FCR-04 | Structural stop behind sweep | First Candle refinement | QQQ/SPY | 1m source; 5m signals | strategy |
| HYP-FCR-EVENT-01 | OR sweep post-event paths | First Candle diagnostic | QQQ/SPY | 1m source; 5m research | event_study |
| HYP-OR-CONT-EVENT-01 | Post-confirmation continuation | First Candle/OR continuation | QQQ/SPY | 5m; primary 30m | event_study |
| HYP-DRIVE-PB | Opening Drive With Pullback | Opening auction | QQQ/SPY proposed | 1m source; 5m proposed | event_study concept |
| HYP-VWAP-DEV | VWAP Deviation Continuation/Reversion | VWAP | QQQ/SPY proposed | 1m source; 5m proposed | event_study concept |
| HYP-CROSS | QQQ/SPY Cross-Confirmation | Relative market | QQQ/SPY | 1m source; 5m proposed | event_study concept |
| LEGACY-CRYPTO-ORB | Opening Range Breakout | Generic crypto strategy | BTC/ETH/SOL | 5m/15m/30m | strategy |
| LEGACY-CRYPTO-VWAP-PB | VWAP Pullback | Generic crypto strategy | BTC/ETH/SOL | 5m/15m/30m | strategy |
| LEGACY-CRYPTO-RVOL-MOM | Relative Volume Momentum | Generic crypto strategy | BTC/ETH/SOL | 5m/15m/30m | strategy |
| LEGACY-CRYPTO-EXT-MR | Extreme Mean Reversion | Generic crypto strategy | BTC/ETH/SOL | 5m/15m/30m | strategy |
| LEGACY-CRYPTO-TREND-CONT | Trend Day Continuation | Generic crypto strategy | BTC/ETH/SOL | 5m/15m/30m | strategy |
| LEGACY-EQ-OR-BASE | Base Opening Range Breakout | Equity OR | QQQ/SPY | 1m | strategy |
| LEGACY-EQ-OR-FVG | Base Opening Range FVG | Equity OR/FVG | QQQ/SPY | 1m | strategy |
| LEGACY-COMP-EXP | Compression to Expansion Breakout | Volatility regime | BTC/ETH/SOL/BNB/XRP | 1m/5m/15m/30m | strategy |
| LEGACY-WICK-VOL-REV | Large Wick + Volume Reversal | Event reversal | Five crypto assets | 5m/15m | strategy |
| LEGACY-POST-EXT-REV-15 | Post-Extreme Reversal 1.5R | Event reversal | Five crypto assets | 5m/15m | strategy |
| LEGACY-POST-EXT-REV-10 | Post-Extreme Reversal 1R | Event reversal | Five crypto assets | 5m/15m | strategy |
| LEGACY-EXT-MOVE-CONT | Extreme Move Continuation | Event continuation | Five crypto assets | 5m/15m | strategy |
| LEGACY-FVG-MSS-RVOL | FVG + MSS with RVOL > 3 | FVG/event filter | Five crypto assets | 1m/5m/15m/30m | strategy lead |
| funding_extreme_positive_anti_long | Extreme positive funding anti-long | Funding | Crypto, unspecified | event-aligned | event_study |
| funding_extreme_negative_anti_short | Extreme negative funding anti-short | Funding | Crypto, unspecified | event-aligned | event_study |
| funding_positive_price_drop_reversal | Positive funding + price-drop reversal | Funding | Crypto, unspecified | event-aligned | event_study |
| funding_negative_price_rise_squeeze | Negative funding + price-rise squeeze | Funding | Crypto, unspecified | event-aligned | event_study |
| oi_up_price_up | OI up / price up | Open interest | Crypto, unspecified | event-aligned | event_study |
| oi_up_price_down | OI up / price down | Open interest | Crypto, unspecified | event-aligned | event_study |
| oi_down_price_up | OI down / price up | Open interest | Crypto, unspecified | event-aligned | event_study |
| oi_down_price_down | OI down / price down | Open interest | Crypto, unspecified | event-aligned | event_study |
| oi_shock_regime_alert | OI shock regime alert | Open interest | Crypto, unspecified | event-aligned | diagnostic |
| funding_oi_volume_filter_fvg_mss | Funding/OI/volume filter on FVG+MSS | Alternative data + FVG | Crypto, unspecified | event-aligned | event_study |

### 2.2 Lifecycle, Eligibility, And Next Action

| Hypothesis ID/group | P | E | Discovery | Validation | Holdout | Classification | Paper/live | Allowed next action |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| S2 | yes | yes | 2022-2024 failed | not opened | 2026 closed | rejected | no/no | F - preserve only |
| S5 | yes | yes | 2022-2024 failed | not opened | 2026 closed | rejected | no/no | F - preserve only |
| S2+S5 | yes | yes | 2022-2024 failed | not opened | 2026 closed | rejected | no/no | F - preserve only |
| HYP-GAP-01 | yes | yes | inconclusive | not opened | 2026 closed | family closed | no/no | F - do not continue |
| HYP-GAP-02 | yes | yes | inconclusive | not opened | 2026 closed | family closed | no/no | F - do not continue |
| HYP-GAP-03 | yes | yes | strongest GAP candidate | 2025 failed | 2026 closed | rejected | no/no | F - do not continue |
| HYP-GAP-04 | yes | yes | zero events | not opened | 2026 closed | rejected | no/no | F - do not continue |
| HYP-GAP-05 | yes | yes | failed | not opened | 2026 closed | rejected | no/no | F - do not continue |
| HYP-GAP-06 | yes | yes | failed/small sample | not opened | 2026 closed | rejected | no/no | F - do not continue |
| HYP-GAP-ASYM-01 | research-pool | yes | retrospective/mixed | contaminated for clean validation | 2026 closed | rejected | no/no | F/E - external evidence only |
| HYP-GAP-OR-01 | research-pool | yes | retrospective/mixed | contaminated for clean validation | 2026 closed | rejected | no/no | F/E - external evidence only |
| HYP-REL-01 | yes | yes | insufficient | gate blocked | 2026 closed | exploratory insufficient | no/no | F - no strategy conversion |
| HYP-FCR-01 | yes | yes | failed | blocked | contaminated/non-decisional | discovery_failed | no/no | F - family closed |
| HYP-FCR-02/03/04 | yes | yes | all failed | blocked | contaminated/non-decisional | discovery_failed | no/no | F - no more variants |
| HYP-FCR-EVENT-01 | yes | yes | completed | blocked | blocked | stable_but_not_economic | no/no | F - diagnostic record only |
| HYP-OR-CONT-EVENT-01 | yes | yes | failed | 2025 locked | 2026 not executed | causal continuation failed | no/no | F - no short rescue |
| HYP-DRIVE-PB | partial protocol | no | not opened | not opened | closed | conceptual only | no/no | B - complete one-variant preregistration |
| HYP-VWAP-DEV | partial protocol | no | not opened | not opened | closed | conceptual only | no/no | B - complete preregistration |
| HYP-CROSS | partial protocol | no | not opened | not opened | closed | overlaps HYP-REL-01 | no/no | E - new motivation required |
| Five legacy crypto strategies | no formal registry | yes | train/OOS observed | embedded OOS | data through 2026 observed | rejected | no/no | F - do not retune |
| Two legacy equity OR/FVG strategies | no formal registry | yes | full/OOS observed | embedded OOS | 2026 observed | rejected | no/no | F - OR/FVG branch closed |
| LEGACY-COMP-EXP | partial/frozen rules | yes | historical evidence observed | expanded universe failed | 2026 observed | canonical rejected; strict cherry-pick | no/no | H - unchanged forward evidence only |
| Four rejected edge rules | partial/frozen rules | yes | historical/OOS failed | no clean unopened split | 2026 observed | rejected | no/no | F - preserve only |
| LEGACY-FVG-MSS-RVOL | partial/frozen rules | yes | retrospectively selected filter | expanded universe weak | no clean unopened split | weak lead, not edge | no/no | H - unchanged forward evidence only |
| Ten funding/OI hypotheses | no | no | unavailable | unavailable | unavailable | not_tested_missing_historical_data | no/no | D - obtain approved data, then preregister |

### 2.3 Primary Files And Frozen Identifiers

| Hypothesis/group | Primary files | Commit/hash where available |
| --- | --- | --- |
| S2, S5, S2+S5 | `configs/research/hypotheses/QQQ-S2-S5-COMBO.yaml`; `docs/QQQ_S2_S5_COMBO_RESEARCH_RESULTS.md`; `outputs/QQQ_S2_S5_COMBO` | config SHA-256 `d7cb9752d07e874e9cff24de8031604d3fa1029b0ab183c9ecb1d109951e8eaf` |
| HYP-GAP-01..06 | `configs/research/hypotheses/HYP-GAP.yaml`; `docs/HYP_GAP_EVENT_STUDY_SPEC.md`; `docs/HYP_GAP_DISCOVERY_RESULTS.md` | run commit `5e219c378af631ce55bd3e8e95ffe22149903ed8`; config SHA-256 `6ff3878accbd17da11d6d75e39a528eb81f06051bdacbb0e6ca5af61764abeb7` |
| HYP-GAP-03 | above plus `docs/HYP_GAP_03_VALIDATION_AND_REGIME_REVIEW.md` | inherited HYP-GAP freeze |
| HYP-GAP-ASYM-01 | YAML, retrospective results, research-pool outputs | config is source of freeze |
| HYP-GAP-OR-01 | YAML, retrospective results, research-pool outputs | config is source of freeze |
| HYP-REL-01 | YAML, results doc, `outputs/hyp_rel_01_intraday_divergence_v1` | config SHA-256 `05caa8f4dd96dbecee7b8c6fca2a06579cd379bddf6090ab9835c992cce3fe60` |
| HYP-FCR-01 | YAML, preregistration, discovery results, research artifacts | preregistration commit `c86e1f48932222d2fab74875e3c0923ff9f8e1d0`; canonical hash in YAML |
| HYP-FCR-02/03/04 | variant YAMLs, family preregistration/results, family artifacts | creation commit `0c1fbe55297cf71972554cc8d79ae786014a68d2`; per-variant canonical hashes in YAML |
| HYP-FCR-EVENT-01 | YAML, preregistration/results, event artifacts | canonical hash `1b6ad06b974d996cdf6bd0a3a21eae097e94322e80fdec94c2cfc4ec3c18fe81` |
| HYP-OR-CONT-EVENT-01 | YAML, preregistration/results, discovery artifacts | preregistration `fe13dfe94a6b679a5abf33f079ef8497e368b4f5`; execution freeze `ec8803fae45ec7f07f338350e6d77b80ec6a8929`; hash `d76572e7534e8cf66104ceb2d30dd08a7c0b080fc4460e496b58a08d3736060b` |
| Conceptual HYP-DRIVE-PB/VWAP-DEV/CROSS | `docs/INTRADAY_HYPOTHESIS_REFINEMENT_PROTOCOL.md` | no hypothesis freeze commit/hash |
| Legacy crypto strategies | `docs/DAYTRADE_REAL_DATA_VALIDATION.md`; `outputs/daytrade` | no central preregistration hash |
| Legacy equity OR/FVG | `docs/OR_FVG_BASE_RESEARCH_SUMMARY.md`; corresponding outputs | no central hypothesis ID/hash |
| Edge and lead validation | `docs/EDGE_DISCOVERY.md`; `docs/LEAD_VALIDATION.md`; corresponding outputs | no central hypothesis ID/hash |
| Funding/OI hypotheses | `outputs/lead_validation/funding_oi_hypothesis_status.csv` | no preregistration hash |

### 2.4 Infrastructure And Family-Control Records

| Record | Type | State | Classification |
| --- | --- | --- | --- |
| HYP-GAP | family config | six variants executed; family closed | G - family control, not one additional hypothesis |
| FCR-REFINEMENT-FAMILY-01 | family selection control | batch executed; none selected | G - infrastructure/family control |
| INTRADAY_HYPOTHESIS_REFINEMENT_PROTOCOL | research protocol | active governance reference | G - infrastructure |
| FORWARD_MICROSTRUCTURE_COLLECTOR | data collector | disabled; quality gate not complete | G/H - infrastructure for forward-only data |

## 3. Families Closed

The following branches are closed against further retrospective variants:

- First Candle / Opening Range Sweep: HYP-FCR-01 through HYP-FCR-04,
  HYP-FCR-EVENT-01, and HYP-OR-CONT-EVENT-01.
- Gap: HYP-GAP-01 through HYP-GAP-06, HYP-GAP-ASYM-01, and HYP-GAP-OR-01.
- Generic crypto indicator strategies: ORB, VWAP pullback, RVOL momentum,
  extreme mean reversion, and trend continuation under their tested rules.
- Base equity OR and OR/FVG.
- S2, S5, and S2+S5.
- Relative divergence as defined by HYP-REL-01.

Closing a branch does not claim the underlying market idea is universally
false. It prohibits rescue through new cuts of already observed data.

## 4. Governance Problems

1. **Registry incompleteness.** HYP-GAP-01, 02, 04, 05, and 06 were
   preregistered and executed but are absent as rows. `HYP-GAP` exists as a
   family config but is absent as a family-control row.
2. **Config state drift.** HYP-FCR-01/02/03/04,
   FCR-REFINEMENT-FAMILY-01, HYP-FCR-EVENT-01, HYP-OR-CONT-EVENT-01,
   HYP-GAP, HYP-REL-01, and the research-pool GAP configs retain pre-execution
   status fields although reports and artifacts prove later states.
3. **ID mismatch.** The combo config ID is `QQQ-S2-S5-COMBO`, while the registry
   represents three rows (`S2`, `S5`, `S2+S5`) and uses a different spelling
   (`S2+S5` versus output variant `S2_S5`).
4. **Results without central preregistration.** Legacy crypto, base equity
   OR/FVG, edge-discovery, lead-validation, and funding/OI work is documented
   outside the central registry.
5. **Documentation without registry rows.** The three conceptual families
   HYP-DRIVE-PB, HYP-VWAP-DEV, and HYP-CROSS appear in the protocol but not in
   the registry. They are concepts, not executable preregistrations.
6. **Abandoned items without central closure.** Compression/expansion and
   FVG+MSS+RVOL remain described as forward leads but have no registry-level
   `forward_only` closure. Ten funding/OI ideas have machine-readable missing
   data status but no ledger presence.
7. **Mixed classification vocabulary.** `Rejected`, `discovery_failed`,
   `exploratoria_e_insuficiente`, `stable_but_not_economic`, and uppercase
   preparation statuses coexist without a normalized state model.
8. **Historical split contamination.** Several legacy studies include data
   through 2026. Their OOS labels are internal to those studies and cannot be
   treated as currently unopened project validation or holdout.

These are documentary inconsistencies, but changing frozen YAML status fields
could alter hashes and historical evidence. They should be corrected through a
separate human-approved ledger migration, not by editing frozen configs.

No duplicate executable ID was found. There are conceptual overlaps, especially
HYP-CROSS versus HYP-REL-01, VWAP studies versus prior VWAP pullback/GAP work,
and opening-drive ideas versus GAP/OR research. Those are independence risks,
not literal duplicate IDs.

## 5. Pending Classification A-H

| Pending item | Category | Justification |
| --- | --- | --- |
| Any immediate historical run | A: none | No candidate has both a complete current preregistration and sufficient independence. |
| HYP-DRIVE-PB | B | Has protocol-level rationale and required fields, but lacks exact event, primary horizon, costs, control, gate, config, and freeze. |
| HYP-VWAP-DEV | B | Same preregistration gaps; prior VWAP work requires explicit non-duplication. |
| FCR/GAP/REL config-state reconciliation | C | Artifacts and docs contradict preparation status fields; hashes must be preserved. |
| Ten funding/OI ideas | D | Zero symbols with approved historical funding/OI data; no result can be inferred. |
| HYP-CROSS | E | Substantially overlaps failed HYP-REL-01 and needs a new causal distinction or external motivation. |
| Closed families and rejected legacy rules | F | Additional retrospective variants would be rescue attempts. |
| Family configs, protocols, collectors | G | They govern or collect; they are not trading hypotheses. |
| Compression/expansion strict lead | H | Favorable strict variant was observed retrospectively with only 16 OOS trades. |
| FVG+MSS+RVOL > 3 lead | H | The filter was selected from prior comparisons and weakened on the expanded universe. |
| Microstructure/order-book hypotheses | H | Only auditable forward collection can create an independent sample. |

## 6. Priority Matrix

Scoring is 0 to 5, where 5 is favorable. For risk and cost columns, 5 means low
risk or low computational burden. `MC` means low multiple-comparison risk.
Maximum raw score is 60. Penalties are then subtracted explicitly.

| Candidate | Indep. | Causal | Lookahead | Data | Prereg. | Compute | Control | Economic | Robust | MC | Reuse | PASS/FAIL | Raw | Penalty | Net |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: |
| HYP-DRIVE-PB-01 proposed | 4 | 4 | 4 | 5 | 2 | 4 | 4 | 4 | 3 | 4 | 5 | 5 | 48 | -3 parameters; -2 opening-family proximity | 43 |
| HYP-VWAP-DEV-01 proposed | 3 | 4 | 5 | 5 | 2 | 5 | 5 | 3 | 3 | 3 | 5 | 4 | 47 | -4 prior VWAP research; -2 parameter surface | 41 |
| HYP-CROSS next variant | 2 | 3 | 3 | 5 | 2 | 4 | 5 | 2 | 2 | 3 | 5 | 4 | 40 | -5 HYP-REL overlap; -3 two-leg costs | 32 |
| Compression/expansion forward | 4 | 4 | 4 | 4 | 3 | 4 | 4 | 2 | 1 | 2 | 5 | 4 | 41 | -5 retrospective strict selection; -4 few events; -2 parameters | 30 |
| FVG+MSS+RVOL forward | 3 | 4 | 4 | 3 | 3 | 3 | 3 | 3 | 2 | 1 | 4 | 4 | 37 | -5 retrospective filter; -3 family saturation; -2 cost sensitivity | 27 |
| Funding/OI family | 5 | 4 | 4 | 0 | 1 | 2 | 3 | 4 | 3 | 2 | 3 | 3 | 34 | -5 missing data; -3 ten comparisons; -2 cost complexity | 24 |

Past profitability is not used as the sole ranking criterion. The first two
rank because they can be made causal, controlled, low-lookahead, and
decisive using approved data. Neither is category A until preregistration is
complete and independently reviewed.

## 7. Main Recommendation

### Proposed ID

`HYP-DRIVE-PB-01`

This is a proposed child of the existing conceptual family `HYP-DRIVE-PB`. The
next task is preregistration only, not execution or strategy implementation.

### Exact Question

After a causally observed directional opening drive in QQQ or SPY, does an
orderly pullback that preserves session VWAP predict positive same-direction
30-minute return from the next available 5-minute open, relative to matched
unconditional returns and after conservative round-trip costs?

### Independence

The proposed mechanism is continuation after an opening auction imbalance and
controlled retracement. It must not use:

- opening-range high/low sweeps;
- FVG presence or absence;
- First Candle confirmation rules;
- gap direction as a required signal;
- EVENT-07/EVENT-08 labels;
- `continuation_short` selection from HYP-OR-CONT-EVENT-01.

This separates it from the closed First Candle family. It also differs from
HYP-GAP-03 because eligibility is based on regular-session drive and pullback,
not overnight gap continuation. Gap must be retained only as a preregistered
diagnostic/control variable and may not become a post hoc filter.

### Proposed Frozen Design

| Field | Recommendation |
| --- | --- |
| Dataset | Approved local curated Alpaca SIP raw-adjusted 1-minute datasets and manifests |
| Symbols | QQQ and SPY, both mandatory |
| Research timeframe | Causal 5-minute bars built from 1-minute RTH data |
| Discovery | 2022-01-01 through 2024-12-31 only |
| Validation | 2025 remains blocked unless discovery gate passes and a separate authorization is given |
| Holdout | 2026 remains blocked/non-decisional |
| Primary horizon | 30 minutes from next 5-minute open after pullback confirmation |
| Secondary horizons | 15 minutes, 60 minutes, session close; cannot override primary failure |
| Control | Matched unconditional return by symbol, year, executable-time bucket, and horizon; preregister a drive-only comparator |
| Baseline costs | 1 bp commission per side plus 1 tick adverse slippage per execution |
| Stress costs | 2 bps commission per side plus 2 ticks adverse slippage per execution |
| Strategy status | Event study only; no stops, targets, sizing, PnL curve, or orders |

Exact drive magnitude, drive window, pullback depth, confirmation deadline, and
RVOL policy must be frozen once in the preregistration. They must not be supplied
as ranges or swept. The preferred budget is one primary definition and zero
historical variants.

### Proposed Discovery Gate

All criteria must pass at the 30-minute primary horizon:

- at least 150 pooled events and at least 50 per symbol;
- same-direction mean and median are positive;
- QQQ and SPY means have the expected sign;
- expected sign in at least two of three discovery years;
- incremental mean versus matched unconditional control is positive;
- mean return exceeds baseline round-trip cost;
- stress-cost result is non-negative;
- no single year contributes more than 70% of positive aggregate effect;
- session-clustered bootstrap is not strongly contradictory;
- no lookahead, timestamp misalignment, manifest violation, or 2025/2026 use.

Failure of any criterion closes the hypothesis. Secondary horizons, symbol
slices, gap slices, direction slices, and favorable calendar cuts cannot rescue
it.

### Risks

- Conceptual proximity to prior opening-session research.
- Too many plausible definitions of drive and pullback.
- Event scarcity if the definition is too strict.
- VWAP can accidentally become an optimized filter.
- A pooled result can hide symbol or annual disagreement.
- The event-study return may be too small relative to costs.

### Files Required Before Any Discovery

- `configs/research/hypotheses/HYP-DRIVE-PB-01.yaml`
- `docs/HYP_DRIVE_PB_01_PREREGISTRATION.md`
- a canonical payload hash and preregistration commit
- documentary tests for schema, periods, costs, gate, safety, and blocked stages
- a human-approved registry row with status `preregistered_not_executed`

Implementation, runner, and discovery artifacts are explicitly out of scope
until those items are reviewed and frozen.

## 8. Alternative

Proposed `HYP-VWAP-DEV-01`: a one-variant equity event study asking whether a
volatility-scaled, causally measured VWAP deviation at a fixed intraday
timestamp exhibits 30-minute reversion or continuation relative to matched
unconditional returns.

It also requires category B work before execution. The preregistration must:

- select reversion or continuation in advance, not report both as competing
  rescue paths;
- use one fixed timestamp and one fixed normalized-deviation threshold;
- explain why it is not the rejected generic crypto VWAP Pullback strategy;
- avoid gap/OR/FVG filters;
- freeze the same symbol, year, control, cost, and bootstrap gates as the main
  proposal.

This alternative ranks slightly lower because VWAP has already appeared in
failed generic and GAP research, reducing conceptual independence.

## 9. Hypotheses That Must Not Continue

- Do not create `HYP-OR-CONT-SHORT-02`.
- Do not select `continuation_short` retrospectively.
- Do not add FCR-05 or further FCR refinement variants.
- Do not reopen HYP-GAP with new thresholds, direction cuts, OR buckets, or
  volatility filters.
- Do not retune S2, S5, S2+S5, base OR/FVG, or generic crypto strategies.
- Do not promote the strict compression variant from its 16 favorable trades.
- Do not promote FVG+MSS+RVOL > 3 from already observed historical comparisons.
- Do not use the isolated SOLUSDT/30m mean-reversion result as validation.
- Do not treat funding/OI hypotheses as tested while approved data is absent.

## 10. Research Sequence

1. Human governance decision: approve or reject `HYP-DRIVE-PB-01` as the sole
   next preregistration target.
2. Perform a ledger migration plan for missing rows and stale statuses without
   modifying frozen payloads or hashes.
3. Write the exact one-variant preregistration and documentary tests.
4. Freeze config, costs, primary horizon, control, gate, report schema, and
   canonical hash in a dedicated commit.
5. Run an integrity/preflight review that does not read result-period OHLC.
6. Only after explicit authorization, execute 2022-2024 discovery once.
7. Close as pass/fail from the primary gate; do not inspect new variants.
8. Keep 2025 closed until a separate post-discovery governance decision.
9. Keep 2026 closed regardless of discovery outcome.

## 11. Conditions To Open Discovery

Discovery may open only when:

- the hypothesis is in the central registry;
- exact causal rules are machine-readable;
- one primary horizon and expected direction are frozen;
- approved dataset manifests and exclusions are named;
- baseline and stress costs are frozen;
- unconditional control and comparator are frozen;
- sample, stability, economic, concentration, and bootstrap gates are frozen;
- variant budget is one;
- no 2025/2026 data or derived metric was consulted;
- paper/live/broker/order flags remain false;
- an independent preregistration review records no unresolved ambiguity.

## 12. 2025 Policy

2025 is validation-only. It remains closed during prioritization,
preregistration, implementation, preflight, and discovery. It may be opened
exactly once only after:

- the 2022-2024 primary discovery gate passes;
- all rules remain unchanged;
- discovery closure is committed;
- validation is separately authorized.

2025 cannot select thresholds, directions, horizons, symbols, costs, controls,
or variants.

## 13. 2026 Policy

Historical 2026 is closed and non-decisional. It cannot be used for hypothesis
selection, parameter choice, validation, rescue, or approval. Existing 2026
observations in legacy work and TradingView parity make it unsuitable as a clean
holdout for these lines.

A true holdout must be future data accumulated after final freeze, with no rule
changes after observation.

## 14. Forward Testing Policy

Forward-only leads must:

- freeze rules before the first eligible observation;
- timestamp and checksum each data batch;
- record missingness, outages, venue, schema, and alignment age;
- prohibit backfilling the decision sample with already inspected history;
- define minimum sample and calendar duration in advance;
- remain event studies until an independent promotion preregistration exists;
- remain disconnected from broker, paper broker, and orders.

Compression/expansion and FVG+MSS+RVOL may only continue unchanged under this
policy. Funding, OI, spread, book, aggressor, and liquidation research first
requires an approved data-quality gate.

## 15. Variant Limit And Abandonment Rule

Default limit: one historical variant per newly approved family. A second
variant requires a separate external rationale written before any result is
seen. Closed First Candle and GAP families have a limit of zero.

A line is abandoned when any of the following occurs:

- the primary preregistered gate fails;
- the causal rule cannot be stated without discretionary hindsight;
- approved data are unavailable after the predefined acquisition window;
- event count is below the frozen minimum;
- expected direction disagrees by symbol or by most years;
- effect does not exceed conservative costs;
- matched control removes the effect;
- results depend on one year, asset, or small event cluster;
- continuing would require changing a threshold, horizon, direction, cost, or
  filter after observing results;
- the family reaches its variant budget.

Abandonment preserves code, reports, configs, and artifacts. It blocks
retrospective rescue; it does not erase the research record.

## Final Recommendation

There is no legitimate hypothesis ready for immediate execution.

The next research task should be the preregistration-only preparation of
`HYP-DRIVE-PB-01`. `HYP-VWAP-DEV-01` is the alternative. The proposed
`HYP-OR-CONT-SHORT-02` and any equivalent retrospective short rescue must remain
frozen and uncreated.
