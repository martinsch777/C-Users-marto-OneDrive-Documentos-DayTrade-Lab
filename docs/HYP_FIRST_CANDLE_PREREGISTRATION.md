# HYP-FCR-01 Preregistration

Status: `preregistered_not_run`

Research type: `intraday_strategy`

Source version: `FIRST_CANDLE_RULE_TV_V1`

No discovery, validation, holdout, paper trading, live trading, broker API call, or live data use was executed for this preregistration.

## Source Lock

| Item | Value |
| --- | --- |
| Pine source | `docs/research/source_pine/FIRST_CANDLE_RULE_TV_V1.pine` |
| Pine SHA-256 | `91604D14B6DAA95758AF3D97617F3F2278E771A5A30ADC61F24E10D83B166D22` |
| YAML config | `configs/research/hypotheses/HYP-FCR-01.yaml` |
| YAML full file SHA-256 | `DA40A9F690117A2D138CD43C5C9F57CD8D04112E52CBD15E0CA5979C0BFA1779` |
| YAML canonical payload SHA-256 | `bac53f3ff97176b9be5bd5b52a9d6589747587a313b34f24644e1d99bb4cd2ab` |
| Python | `Python 3.13.2` |
| Git commit at preregistration | `c86e1f48932222d2fab74875e3c0923ff9f8e1d0` |
| Created at | `2026-07-21T23:17:53-03:00` |

The canonical payload hash excludes the `configuration_hash` block to avoid a self-referential hash. The full file hash above is the SHA-256 of the materialized YAML file.

## Canonical Hash Semantics

Primary methodological identifier:

`canonical_payload_sha256 = bac53f3ff97176b9be5bd5b52a9d6589747587a313b34f24644e1d99bb4cd2ab`

Included keys:

- Every top-level key in `configs/research/hypotheses/HYP-FCR-01.yaml` except the explicitly excluded keys below.
- All nested strategy rules, periods, universe, data requirements, costs, execution modes, gates, post-preregistration locks, run state, and safety declarations.

Excluded keys:

- `configuration_hash`, because it contains the hash itself.
- `yaml_sha256`, if present in a future materialized metadata wrapper.
- `yaml_sha256_excluding_self`, if present in a future materialized metadata wrapper.

The canonical hash does not depend on:

- Runtime timestamps.
- Git commits after preregistration.
- Discovery, validation, holdout, or parity results.
- Output paths or run manifests.
- Accidental YAML key order.

Serialization:

- Load YAML with `yaml.safe_load`.
- Convert to JSON-compatible values with `json.dumps(..., sort_keys=True, default=str)`.
- Remove excluded top-level keys.
- Serialize with `json.dumps(cleaned, sort_keys=True, separators=(",", ":"))`.
- Encode as UTF-8.
- Hash with SHA-256.

Reproduction command before discovery or validation:

```powershell
@'
from pathlib import Path
import yaml
from src.research.hyp_first_candle import canonical_config_hash
payload = yaml.safe_load(Path("configs/research/hypotheses/HYP-FCR-01.yaml").read_text(encoding="utf-8"))
print(canonical_config_hash(payload))
'@ | .\.venv\Scripts\python.exe -
```

Any legitimate canonical hash change before discovery must be documented before any research period is opened. Removing the duplicate Pine copy from `configs/research/hypotheses` did not change the canonical payload because the YAML already referenced the canonical Pine path.

## Repository Audit

| Need | Existing component | File | Decision |
| --- | --- | --- | --- |
| Pine source lock | New SHA-256 helper | `src/research/hyp_first_candle.py` | Created for HYP-FCR-01 |
| Approved curated OHLCV manifests | `require_or_fvg_backtest_dataset_manifest` | `src/data/dataset_manifest.py` | Reused unchanged |
| US equity RTH calendar, holidays, DST, early closes | `EquitySessionCalendar` | `src/data/sessions.py` | Reused unchanged |
| 1m to 5m RTH bars | `resample_rth_1min_to_5min` | `src/research/qqq_s2_s5.py` | Reused unchanged |
| Existing OR/FVG strategy | `OpeningRangeFVGStrategy` | `src/strategies/opening_range_fvg.py` | Audited but not reused as signal logic; it is an opening range breakout, while HYP-FCR-01 is a reentry after sweep |
| Intrabar execution | `ExecutionSimulator` concepts | `src/execution_simulator/engine.py` | Audited; HYP-FCR-01 needs frozen target from signal close and two execution modes, so execution is local to the research module |
| Backtest result registry | Research hypothesis registry | `docs/RESEARCH_HYPOTHESIS_REGISTRY.md` | Updated with preregistered-not-run row |

No historical strategy, result document, or output from prior hypotheses was modified.

## Hypotheses

Alternative hypothesis:

After price touches one extreme of the 09:30-10:00 opening range, a contrary FVG confirmed by a strict close back inside the range has positive net expectancy using a 2R target.

Null hypothesis:

Net expectancy is less than or equal to zero after commissions, slippage, and conservative intrabar resolution.

## Frozen Periods

| Period | Dates | Status |
| --- | --- | --- |
| Discovery | 2022-01-01 to 2024-12-31 | Registered, not run |
| Validation | 2025-01-01 to 2025-12-31 | Blocked until discovery passes every gate |
| 2026 | 2026 calendar year | `observed_contaminated_non_decisional` |
| True holdout | Future data | Forward paper after final freeze |

2026 is contaminated because TradingView results were already observed for QQQ, VOO, SMH, and SOXL. It may only be used later for Pine/Python parity debugging, not for profitability conclusions, parameter selection, or approval.

## Universe And Data

Primary initial universe:

- QQQ
- SPY

Only curated 1-minute datasets with approved manifests may be used. Expected manifests:

- `data/manifests/QQQ_1min_2022-01-01_2026-07-06_curated_manifest.json`
- `data/manifests/SPY_1min_2022-01-01_2026-07-06_curated_manifest.json`

VOO, SMH, and SOXL are not downloaded, run, or evaluated in this task. Their possible transfer test is documented only as future independent hypothesis `HYP-FCR-XFER-01`.

## Frozen Signal Rules

- Signal timeframe: 5 minutes, built only from audited 1-minute RTH data.
- Bars align to `America/New_York`: 09:30, 09:35, ..., 15:55.
- Opening range: six bars from 09:30 inclusive to 10:00 exclusive.
- Entry window: 10:00 inclusive to before 15:55.
- Long sweep: `low <= opening_low`.
- Short sweep: `high >= opening_high`.
- Exact touches count; tolerance is zero ticks.
- Every new touch updates the most recent touch index.
- Confirmation must occur after the most recent touch, never on the same bar.
- Confirmation mode is frozen to `Solo FVG`.
- Bullish FVG: `low[t] > high[t-2]`.
- Bearish FVG: `high[t] < low[t-2]`.
- `minimum_fvg_ticks = 0`, but the gap must still be strictly positive.
- Close back inside the opening range uses strict inequalities.
- If long and short signals occur on the same bar, no trade is opened and a diagnostic is recorded.
- Maximum one trade per symbol per session.

## Frozen Risk Rules

- Initial capital for parity: USD 1,000.
- Risk: 0.50% of equity before the trade.
- Max notional exposure: 100% of equity.
- Integer shares only, step 1, minimum 1.
- ETF pointvalue equivalent: 1.
- Long stop: lowest body among signal bar and two previous bars minus one tick.
- Short stop: highest body among signal bar and two previous bars plus one tick.
- Target: fixed 2R from `signal_close`.
- Stop and target are not recalculated after actual fill.

## Costs

| Model | Commission per side | Slippage per execution |
| --- | ---: | ---: |
| Baseline | 0.01% | 1 tick |
| Stress | 0.02% | 2 ticks |
| Severe | 0.03% | 3 ticks |

## Execution Modes

`tradingview_parity` is for operation-by-operation comparison with Pine. It decides at the signal bar close, simulates entry from `signal_close` with adverse slippage, keeps Pine fixed 15:55-16:00 close semantics, and intentionally preserves the early-close bug risk.

`research_primary` is the only mode eligible for economic conclusions. It enters at the next available audited 1-minute open after signal close, applies adverse slippage, resolves stop/target on 1-minute data with stop-first ambiguity, exits at the true `US_EQUITY_RTH` session close, respects early closes, and prohibits overnight positions.

## Gates

Discovery opens validation only if every criterion passes:

- At least 150 completed pooled trades.
- At least 50 completed trades per symbol.
- Baseline net expectancy R > 0.
- Baseline net profit factor >= 1.15.
- QQQ and SPY both net positive under baseline.
- Stress net expectancy R >= 0.
- Stress profit factor >= 1.00.
- At least two of three discovery years positive.
- No single year explains more than 70% of total net profit.
- Maximum drawdown <= 10%.

If any criterion fails, classification is `discovery_failed`, 2025 remains closed, parameters are not optimized, and no variant is created inside this hypothesis.

Validation gate is registered but not run:

- No parameter changes from discovery.
- At least 40 completed trades.
- Baseline net expectancy R > 0.
- Baseline net profit factor >= 1.10.
- Maximum drawdown <= 10%.

## Safety State

- live_trading=false
- broker_connected=false
- orders_sent=false
- paper_broker_enabled=false
