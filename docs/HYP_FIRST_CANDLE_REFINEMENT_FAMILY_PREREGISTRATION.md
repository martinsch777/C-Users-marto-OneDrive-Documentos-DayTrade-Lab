# HYP First Candle Refinement Family Preregistration

## Status

Family: `FCR-REFINEMENT-FAMILY-01`

This family was generated after observing the `discovery_failed` result of
`HYP-FCR-01`. Therefore, the 2022-2024 window remains discovery for these
variants and is not independent evidence. The 2025 validation period remains
closed and unobserved for these variants. The 2026 period remains contaminated
by TradingView observations and may only be used for non-decisional parity or
debug work.

No discovery, validation, 2026 decisional run, holdout, optimization, parameter
sweep, broker access, Alpaca call, data download, paper trading, or live trading
is authorized by this preregistration task.

## Variants

The family contains exactly three variants:

- `HYP-FCR-02`: FVG confirmation must occur within offsets 1, 2, or 3 after
  the latest sweep.
- `HYP-FCR-03`: sweep must exceed the opening range extreme by at least one
  tick.
- `HYP-FCR-04`: stop is structural behind the full sweep-to-signal segment.

No fourth variant is allowed. No combinations among these variants are allowed.
Each variant changes exactly one conceptual component relative to `HYP-FCR-01`.

## Inherited Rules

All variants inherit from `HYP-FCR-01`:

- Audited QQQ and SPY curated one-minute datasets.
- Source timeframe `1min`, signal timeframe `5min`.
- `America/New_York` session alignment.
- Opening Range `09:30-10:00`, exactly six five-minute bars.
- Entries from `10:00` through before `15:55`.
- Long and short signals enabled.
- At most one valid trade per symbol and session.
- No pyramiding.
- `Solo FVG` confirmation only.
- No same-bar sweep confirmation.
- Strict close back inside the Opening Range.
- `minimum_fvg_ticks = 0`.
- Target `2R` from `signal_close`.
- Risk target `0.50%` of equity before trade.
- Maximum notional exposure `100%`.
- Whole-share quantity, `quantity_step = 1`, `minimum_quantity = 1`.
- `quantity < 1` is rejected.
- A sizing-rejected signal does not consume the daily trade.
- Baseline, stress, and severe cost models from `HYP-FCR-01`.
- `research_primary` execution mode.
- Conservative one-minute intrabar resolution.
- True session close forced exit.
- No overnight positions.

## Difference Matrix

| Rule | FCR-01 | FCR-02 | FCR-03 | FCR-04 |
| --- | --- | --- | --- | --- |
| Sweep definition | Touch counts: long `low <= OR low`, short `high >= OR high` | Same as FCR-01 | Strict break: long `low <= OR low - 1 tick`, short `high >= OR high + 1 tick` | Same as FCR-01 |
| Sweep validity | Valid until replaced or session ends | Valid only for confirmation offsets 1, 2, 3 | Same as FCR-01 | Same as FCR-01 |
| Stop | Three-bar body stop plus one tick | Same as FCR-01 | Same as FCR-01 | Structural high/low from latest sweep bar through signal bar, inclusive, plus one tick |
| Target | 2R from `signal_close` | Same as FCR-01 | Same as FCR-01 | 2R from `signal_close` using structural stop risk |
| Sizing | 0.50% equity before trade with 100% notional cap | Same as FCR-01 | Same as FCR-01 | Same formula, using structural stop distance |
| Confirmation mode | Solo FVG, strict close inside OR | Same as FCR-01 | Same as FCR-01 | Same as FCR-01 |

## Individual Gate

Each variant must pass every criterion individually:

1. Minimum 150 completed trades pooled.
2. Minimum 50 completed trades in QQQ.
3. Minimum 50 completed trades in SPY.
4. Baseline net expectancy R greater than 0.
5. Baseline net profit factor at least 1.15.
6. QQQ baseline net PnL positive.
7. SPY baseline net PnL positive.
8. Stress net expectancy R at least 0.
9. Stress profit factor at least 1.00.
10. At least two of the three discovery years positive.
11. No year contributes more than 70% of positive baseline net profit.
12. Baseline maximum drawdown no greater than 10%.

All criteria are mandatory. Failing one criterion blocks validation.

## Diagnostics

Common diagnostics are preregistered for all variants: trades, net PnL,
expectancy R, profit factor, drawdown, win rate, results by symbol, year,
direction, and hour, sweep-to-confirmation time, FVG ticks, FVG/ATR, stop
distance, effective risk, sizing rejections, and TP/SL/session-close exits.

Variant-specific diagnostics:

- `HYP-FCR-02`: offset distribution for 1, 2, and 3; expired sweeps.
- `HYP-FCR-03`: exact touches rejected; sweep depth in ticks.
- `HYP-FCR-04`: body stop versus structural stop distance, additional sizing
  rejections, sweep-to-signal duration, structural segment length.

Diagnostics cannot be used to add filters or alter rules inside the same run.

## Safety

`live_trading=false`, `broker_connected=false`, `orders_sent=false`, and
`paper_broker_enabled=false` remain mandatory. Broker APIs, credential changes,
and data downloads are not allowed.
