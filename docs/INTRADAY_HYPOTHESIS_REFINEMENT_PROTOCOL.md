# Intraday Hypothesis Refinement Protocol

Date: 2026-07-13

This protocol defines the next offline/local research stage after the base Opening Range Breakout and Opening Range FVG evaluation on QQQ and SPY 1-minute curated Alpaca SIP data from 2022-01-01 through 2026-07-06.

The base OR/FVG strategies remain discarded. They must not be retroactively optimized as if an edge had been found.

Safety state is fixed:

| Field | Required Value |
| --- | --- |
| `live_trading` | `false` |
| `broker_connected` | `false` |
| `orders_sent` | `false` |
| `paper_broker_enabled` | `false` |

DayTrade Lab, the curated CSVs, approved manifests, and reproducible local backtests are the source of truth. TradingView may be used for visual inspection, chart review, and prototyping, but not as the final source of approval.

## Objective

The objective is to discover and validate new intraday hypotheses with a controlled scientific workflow. The stage is not an optimization pass over failed OR/FVG parameters. It is a structured search for economically or behaviorally motivated effects that may later justify strategy prototyping.

The protocol separates:

| Stage | Purpose | Output |
| --- | --- | --- |
| Event study | Measure whether a defined event has directional or distributional evidence before strategy rules are introduced | Event-level statistics and pass/fail decision |
| Strategy prototype | Convert a passing event into explicit entry, exit, risk, and cost assumptions | A deterministic strategy specification |
| Validation | Test whether the prototype survives independent time and symbol checks | Validation report |
| Final holdout | One-time frozen assessment after all choices are fixed | Final holdout report |
| Replay | Manual or semi-automated market replay only after holdout approval | Replay notes and failure log |
| Internal paper | Simulated broker workflow only after replay approval | Paper readiness report |

No stage may skip the prior stage.

## Temporal Split

Use only dates available in the approved 2022-01-01 to 2026-07-06 dataset range.

| Split | Dates | Purpose |
| --- | --- | --- |
| Discovery | 2022-01-01 to 2024-12-31 | Generate and test initial event hypotheses |
| Validation | 2025-01-01 to 2025-12-31 | Independent check for stability before strategy promotion |
| Final holdout | 2026-01-01 to 2026-07-06 | Frozen final assessment only |

The final holdout must not be used to choose parameters, select variants, adjust filters, remove trades, or decide which hypothesis family to keep. Any change made after viewing holdout results invalidates that holdout pass and requires a new future holdout period.

## Research Budget

The search budget is deliberately small.

| Budget Item | Limit |
| --- | ---: |
| Hypothesis families | 4 |
| Variants per family | 6 |
| Total event-study runs | 24 |
| Strategy prototypes promoted from event studies | 4 |
| Prototype variants per promoted hypothesis | 3 |
| Total prototype backtest runs before validation | 12 |
| Validation runs per prototype | 1 primary run plus predefined robustness slices |
| Final holdout runs | 1 per frozen prototype |

Every test must be registered, including failed tests, rejected variants, implementation errors, and abandoned ideas. Unlogged tests count as protocol violations.

## Initial Variable Set

Allowed initial variables:

- overnight gap;
- opening range;
- VWAP;
- relative volume;
- ATR or realized volatility;
- prior returns;
- time of day;
- QQQ/SPY cross-confirmation.

Initially prohibited:

- redundant indicators added without a stated hypothesis;
- broad combinatorial searches;
- excessively precise parameters;
- any selection based on final holdout behavior;
- discretionary removal of losing trades;
- changing split dates after seeing results;
- optimizing failed OR/FVG base parameters retroactively.

## Initial Hypothesis Families

### HYP-GAP: Gap Continuation Versus Gap Reversal

Required rationale: explain why overnight inventory imbalance, news absorption, or liquidity provision should create continuation or reversal pressure.

Required event definition:

- gap size definition;
- sign of gap;
- reference close and open;
- minimum and maximum gap thresholds;
- eligible time window.

Return horizons:

- 5 minutes;
- 15 minutes;
- 30 minutes;
- 60 minutes;
- session close.

Expected direction must be declared before testing. Invalidation conditions must include weak sample size, unstable direction by year, inconsistent QQQ/SPY behavior, and poor validation-period replication.

Maximum variants: 6.

### HYP-DRIVE-PB: Opening Drive With Pullback

Required rationale: explain why early directional auction pressure followed by controlled pullback should indicate continuation instead of exhaustion.

Required event definition:

- opening drive window;
- drive magnitude relative to ATR or realized volatility;
- pullback depth;
- VWAP relation;
- relative volume condition;
- time-of-day eligibility.

Expected direction must be declared before testing. Invalidation conditions must include dependence on a single year, failure after costs, or excessive sensitivity to exact pullback depth.

Maximum variants: 6.

### HYP-VWAP-DEV: VWAP Deviation Continuation Or Reversion

Required rationale: explain why distance from VWAP should represent either temporary dislocation or institutional trend pressure.

Required event definition:

- VWAP deviation unit;
- volatility scaling;
- time-of-day bucket;
- relative volume condition;
- prior return filter;
- continuation or reversal direction.

Expected direction must be declared before testing. Invalidation conditions must include symmetric noise around VWAP, unstable sign across symbols, and failure in validation.

Maximum variants: 6.

### HYP-CROSS: QQQ/SPY Cross-Confirmation

Required rationale: explain why index ETF confirmation or divergence should improve signal quality through market-wide participation or relative strength.

Required event definition:

- leader and confirmer symbol;
- confirmation window;
- return or range threshold;
- relative volume agreement;
- conflict rule when symbols diverge.

Expected direction must be declared before testing. Invalidation conditions must include one-symbol-only dependence, asynchronous timestamp issues, and validation instability.

Maximum variants: 6.

## Event Study Requirements

Each event study must define:

- hypothesis family ID;
- economic or behavioral rationale;
- exact event definition;
- future return to measure;
- expected direction;
- invalidation conditions;
- maximum number of variants;
- symbols included;
- temporal split used;
- cost assumptions if any are included at this stage.

Minimum metrics:

| Metric | Required |
| --- | --- |
| Number of events | Yes |
| Mean return | Yes |
| Median return | Yes |
| Percentage positive | Yes |
| Standard deviation | Yes |
| Standard error | Yes |
| Confidence intervals | Yes |
| Results by year | Yes |
| Results by symbol | Yes |
| Discovery versus validation stability | Yes |

Event studies are not strategies. Passing an event study only permits a strategy prototype to be specified.

## Early Discard Criteria

Discard a hypothesis family or variant early if any of the following occurs:

- fewer than 100 events in discovery, unless the hypothesis explicitly targets rare events and has a pre-registered rare-event threshold;
- mean and median returns disagree in a way that implies outlier dependence;
- direction flips between QQQ and SPY without a pre-stated divergence rationale;
- direction flips across years in discovery;
- validation effect is less than half of discovery effect with no pre-stated reason;
- confidence intervals are too wide to support a directional claim;
- results depend on one year, one symbol, one month, or one small group of events;
- effect disappears under conservative transaction-cost assumptions;
- any evidence of lookahead, leakage, timestamp misalignment, or discretionary filtering appears.

## Promotion From Event Study To Strategy Prototype

An event study can become a strategy prototype only if:

- the event definition is deterministic;
- discovery and validation show the same expected direction;
- both QQQ and SPY behavior are understood, even if only one is selected later;
- sample size is sufficient for the claimed effect;
- entry timing is based only on information available at that time;
- exit logic is specified before backtesting;
- risk per trade and maximum exposure are specified before backtesting;
- cost and slippage assumptions are specified before backtesting;
- invalidation rules are written before backtesting.

The prototype must not add extra filters unless those filters were part of the registered event-study family or are documented as a new variant within the research budget.

## Validation Criteria

A prototype advances through validation only if:

- validation total return is positive after costs;
- profit factor is above 1.20 after costs;
- expectancy is positive after costs;
- trade count is sufficient for the frequency class;
- performance is not dominated by one trade, one week, one month, or one symbol;
- drawdown is consistent with the proposed risk limits;
- year and symbol slices do not contradict the stated rationale;
- parameter sensitivity is smooth, not dependent on a precise threshold.

These criteria are necessary, not sufficient. Passing validation allows one frozen holdout test.

## Final Holdout Criteria

The final holdout is a frozen one-time test. It may be run only after:

- hypothesis;
- variables;
- parameters;
- symbols;
- entry rules;
- exit rules;
- risk rules;
- cost assumptions;
- discard criteria;
- advancement criteria;
- report template

are all fixed.

The final holdout cannot be used to choose parameters. A prototype fails holdout if net performance is negative after costs, if the rationale breaks, if trade quality depends on one isolated event, or if operational issues appear.

## Replay Criteria

A prototype may advance to replay only if it passes final holdout and has:

- reproducible local reports;
- no unresolved data-quality warnings;
- stable behavior across discovery, validation, and holdout;
- clear market-state narrative;
- explicit failure modes;
- defined screenshots or chart-review checklist;
- no requirement for discretionary hindsight.

Replay is still offline research. It does not permit paper broker or live trading.

## Internal Paper Criteria

Internal paper is allowed only after replay approval and a separate readiness review. Requirements:

- all replay observations logged;
- no unresolved execution assumptions;
- conservative cost model;
- daily risk limits;
- kill-switch rules;
- maximum number of paper trades;
- paper objectives and failure criteria;
- explicit approval record.

Paper broker remains disabled until a separate decision explicitly enables it. Live trading remains disabled.

## Cost Sensitivity Rules

Every strategy prototype must be tested with at least:

| Cost Scenario | Requirement |
| --- | --- |
| Baseline | Current configured costs |
| Low cost | Half baseline costs |
| High cost | Double baseline costs |

A strategy cannot advance if only the low-cost scenario works. High-cost sensitivity should degrade gracefully; catastrophic sensitivity is grounds for discard.

## Bias And Leakage Controls

Rules:

- use only timestamps and fields available at decision time;
- do not use future high, low, close, volume, VWAP, or volatility in event definitions;
- compute rolling features causally;
- align QQQ/SPY cross-confirmation by timestamp and decision availability;
- do not fill missing provider bars;
- use only curated datasets and approved manifests;
- respect approved excluded sessions only as documented in manifests;
- do not use final holdout for parameter choice;
- do not remove losing trades after review;
- keep symbol universe fixed to the stated research scope unless a new protocol revision expands it.

Survivorship bias is controlled by limiting this protocol to QQQ and SPY as explicitly selected ETFs, not by claiming broad equity-universe inference.

## Experiment Registry Format

Every experiment must be recorded before execution.

Required fields:

| Field | Description |
| --- | --- |
| `experiment_id` | Reproducible ID |
| `family_id` | Hypothesis family |
| `variant_id` | Variant number |
| `stage` | event_study, prototype, validation, holdout, replay, paper |
| `created_at` | Timestamp |
| `symbol_scope` | QQQ, SPY, or both |
| `split` | discovery, validation, holdout |
| `hypothesis` | Plain-language claim |
| `rationale` | Economic or behavioral rationale |
| `event_definition` | Exact deterministic event |
| `expected_direction` | Long, short, continuation, reversal, or conditional |
| `variables_used` | Approved variables only |
| `parameters` | Explicit values and ranges |
| `invalid_if` | Predefined invalidation conditions |
| `metrics_required` | Required output metrics |
| `result_status` | pending, pass, fail, invalidated, implementation_error |
| `notes` | Short notes, including failures |

## ID Convention

Use deterministic IDs:

```text
HYP-{FAMILY}-{NN}
RUN-{FAMILY}-{NN}-{STAGE}-{YYYYMMDD}-{SEQ}
```

Examples:

```text
HYP-GAP-01
RUN-GAP-01-EVENT-20260713-001
RUN-VWAP-DEV-03-VALIDATION-20260713-001
```

IDs must not be reused. Failed runs keep their IDs.

## Source Of Truth

TradingView can help with visual exploration and manual chart review. It cannot approve a strategy, replace reproducible event studies, or override local backtest results.

DayTrade Lab is the source of truth for:

- curated CSVs;
- approved manifests;
- quality gates;
- event-study outputs;
- backtest outputs;
- validation reports;
- holdout reports;
- replay logs;
- paper-readiness decisions.

No broker connection, order submission, paper broker, or live trading is allowed under this protocol.
