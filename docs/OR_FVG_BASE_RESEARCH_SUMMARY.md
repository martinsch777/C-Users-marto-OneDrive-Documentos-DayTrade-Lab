# OR/FVG Base Research Summary

Date: 2026-07-13

This report summarizes the first offline/local evaluation of the base opening range breakout and opening range FVG strategies on approved QQQ and SPY 1-minute curated datasets.

No broker was connected. No orders were sent. Live trading, paper broker, and paper execution remain disabled.

## Dataset Context

The evaluation used local curated equity datasets only:

| Symbol | CSV |
| --- | --- |
| QQQ | `data\curated\QQQ_1min_2022-01-01_2026-07-06_curated.csv` |
| SPY | `data\curated\SPY_1min_2022-01-01_2026-07-06_curated.csv` |

Approved manifests:

| Symbol | Manifest |
| --- | --- |
| QQQ | `data\manifests\QQQ_1min_2022-01-01_2026-07-06_curated_manifest.json` |
| SPY | `data\manifests\SPY_1min_2022-01-01_2026-07-06_curated_manifest.json` |

The OR/FVG gate requires an approved manifest, rejects `data\raw`, verifies `curated_file` or `output_file`, checks `sha256`, and requires all safety flags to be false.

SPY has one approved excluded session in the manifest: `2023-06-05`. That session was removed by audited data-quality policy because of a confirmed Alpaca SIP provider gap inside the first 30 minutes. The backtest quality check is allowed to ignore only missing bars that belong to approved excluded sessions.

Safety state:

| Field | Value |
| --- | --- |
| `broker_connected` | `false` |
| `orders_sent` | `false` |
| `live_trading_enabled` | `false` |
| `paper_broker_enabled` | `false` |

## Consolidated Results

| Symbol | Strategy | Total Return | Max Drawdown | Profit Factor | Win Rate | Expectancy | Sharpe | Trades | Decision |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| QQQ | opening_range_breakout | +0.2107% | n/a | inf | 100% | n/a | n/a | 2 | Discard |
| QQQ | opening_range_fvg | -9.5167% | 9.9229% | 0.505189 | 26.7606% | -16.754763 | -4.77473 | 568 | Discard |
| SPY | opening_range_breakout | -0.1133% | 0.1028% | 0.346292 | 37.5% | -14.163803 | -7.301532 | 8 | Discard |
| SPY | opening_range_fvg | -11.5347% | 11.5466% | 0.336931 | 21.9672% | -18.909279 | -7.866031 | 610 | Discard |

`n/a` means the metric was not provided in the recorded result summary.

## Out-of-Sample And Walk-Forward

| Symbol | Strategy | OOS Total Return | OOS Profit Factor | OOS Win Rate | OOS Trades | Walk-Forward |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| QQQ | opening_range_breakout | n/a | n/a | n/a | 0 | Not informative due to extremely low trade count |
| QQQ | opening_range_fvg | -1.995% | 0.572539 | 28.5714% | 154 | 8 folds; all negative or not robust |
| SPY | opening_range_breakout | -0.044% | 0.0 | 0% | 1 | Not informative due to extremely low trade count |
| SPY | opening_range_fvg | -3.152% | 0.327234 | 22.2222% | 180 | 8 folds; all negative |

## Cost Sensitivity

| Symbol | Strategy | Cost Multiplier | Total Return | Profit Factor |
| --- | --- | ---: | ---: | ---: |
| QQQ | opening_range_fvg | 0.5 | -4.1366% | 0.722098 |
| QQQ | opening_range_fvg | 1.0 | -9.5167% | 0.505189 |
| QQQ | opening_range_fvg | 2.0 | -20.0725% | 0.287203 |
| SPY | opening_range_fvg | 0.5 | -5.4615% | 0.561153 |
| SPY | opening_range_fvg | 1.0 | -11.5347% | 0.336931 |
| SPY | opening_range_fvg | 2.0 | -21.2074% | 0.197813 |

The FVG results remain negative even at reduced costs. The issue is not only execution cost; the base signal is not robust enough in this evaluation.

## Diagnostics

### QQQ opening_range_breakout

The result is positive, but only 2 trades were generated. That sample is too small for statistical inference. This run is discarded and is not eligible for replay or paper.

### QQQ opening_range_fvg

The strategy generated enough trades to evaluate, but results were negative in-sample, out-of-sample, walk-forward, and cost sensitivity. This run is discarded and is not eligible for replay or paper.

### SPY opening_range_breakout

The strategy generated only 8 trades and was negative overall. Out-of-sample had 1 trade and was also negative. This run is discarded and is not eligible for replay or paper.

### SPY opening_range_fvg

The strategy generated enough trades to evaluate, but results were negative in-sample, out-of-sample, across all 8 walk-forward folds, and under all listed cost multipliers. This run is discarded and is not eligible for replay or paper.

## Final Decision

The base OR/FVG research pass does not produce a replay candidate, an internal paper candidate, or a live-trading candidate for QQQ or SPY on the approved 1-minute 2022-01-01 to 2026-07-06 datasets.

Decisions:

| Action | Decision |
| --- | --- |
| Move OR/FVG base to replay | No |
| Move OR/FVG base to internal paper | No |
| Enable paper broker | No |
| Enable live trading | No |
| Connect broker | No |
| Send orders | No |

## Recommended Next Steps

Do not pass the base OR/FVG strategies to replay or paper.

Only open a separate hypothesis refinement stage if a reasonable hypothesis is defined in advance and anti-overfitting rules are written before testing.

Before any refinement, save:

- hypothesis;
- allowed variables;
- allowed ranges;
- temporal split;
- discard criterion;
- advancement criterion;
- maximum number of tests;
- reproducible report per run.

Do not optimize these base parameters directly as if an edge had already been found.

A small engineering cleanup remains: replace `pd.Timedelta(timeframe)` with explicit units to remove the warning. That should be a separate commit and should not change strategy results.
