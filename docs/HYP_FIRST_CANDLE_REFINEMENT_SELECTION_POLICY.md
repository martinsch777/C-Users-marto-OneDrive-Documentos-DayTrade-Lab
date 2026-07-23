# HYP First Candle Refinement Selection Policy

## Scope

This policy applies only to `FCR-REFINEMENT-FAMILY-01`:

- `HYP-FCR-02`
- `HYP-FCR-03`
- `HYP-FCR-04`

`HYP-FCR-01` is excluded because it already failed discovery. No additional
variant may be added after any family discovery result is observed.

## Batch Rule

The three variants must be run later in one batch task. Partial results may not
be inspected to modify another variant, alter thresholds, add filters, add
variants, or change execution assumptions.

## Selection

If no variant passes its individual discovery gate:

- `family_status = discovery_failed`
- validation remains blocked

If exactly one variant passes:

- that variant is the selected variant
- only that variant may become eligible for validation 2025

If two or three variants pass, select exactly one by this deterministic order:

1. Higher stress net expectancy R.
2. If the absolute stress-expectancy difference is less than `0.01 R`, higher
   baseline profit factor.
3. If still tied, lower baseline maximum drawdown.
4. If still tied, lower `hypothesis_id`.

Passed variants that are not selected receive
`discovery_passed_not_selected`.

Validation is never executed automatically.

## Period Lock

- Discovery: `2022-01-01` to `2024-12-31`.
- Validation: `2025-01-01` to `2025-12-31`, closed until selection.
- 2026: observed, contaminated, non-decisional parity/debug only.
- True holdout: forward paper after validation and final freeze.
