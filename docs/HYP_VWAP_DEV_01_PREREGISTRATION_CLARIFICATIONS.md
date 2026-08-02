# HYP-VWAP-DEV-01 Preregistration Clarifications

## Metadata

```yaml
hypothesis_id: HYP-VWAP-DEV-01
clarification_id: HYP-VWAP-DEV-01-CLAR-01
clarification_status: approved_for_freeze
conceptual_design_freeze_commit: 5a0c3dee3af99093fb5ff5eb2ab641767d1e086f
audit_trigger: Final preregistration audit found PRO-01 to be self-referential.
classification: non-methodological logical clarification
selection_changed: false
timing_changed: false
threshold_changed: false
returns_changed: false
costs_changed: false
control_changed: false
bootstrap_changed: false
gate_thresholds_changed: false
temporal_partitions_changed: false
decision_variants_changed: false
```

## Normative Substantive Criteria

The complete and exclusive set of substantive required criteria is:

1. `INT-01`
2. `INT-02`
3. `INT-03`
4. `INT-04`
5. `INT-05`
6. `INT-06`
7. `INT-07`
8. `INT-08`
9. `SMP-01`
10. `SMP-02`
11. `SMP-03`
12. `REP-01`
13. `ECO-01`
14. `ECO-02`
15. `ECO-03`
16. `ECO-04`
17. `ECO-05`
18. `INC-01`
19. `UNC-01`
20. `STB-01`
21. `STB-02`
22. `CON-01`
23. `CON-02`
24. `CON-03`
25. `CON-04`

This list contains exactly 25 criterion IDs. It is the normative input set for `PRO-01`.

## PRO-01 Normative Definition

```yaml
criterion_id: PRO-01
category: promotion
metric: all_substantive_required_criteria_passed
operator: "="
threshold: true
required: true
evaluation_order: after_all_substantive_criteria
input_criterion_ids:
  - INT-01
  - INT-02
  - INT-03
  - INT-04
  - INT-05
  - INT-06
  - INT-07
  - INT-08
  - SMP-01
  - SMP-02
  - SMP-03
  - REP-01
  - ECO-01
  - ECO-02
  - ECO-03
  - ECO-04
  - ECO-05
  - INC-01
  - UNC-01
  - STB-01
  - STB-02
  - CON-01
  - CON-02
  - CON-03
  - CON-04
self_inclusion: false
```

`PRO-01` is `true` if and only if every criterion listed in `input_criterion_ids` has terminal status `passed`. It must not include itself, directly or indirectly, in its inputs. It is evaluated only after all 25 substantive criteria have reached a terminal status.

If any substantive input is `false`, `failed`, missing, non-finite, insufficient, non-estimable, or unavailable, `PRO-01` is `false`. No such state may be treated as a pass or deferred to discretionary review.

`PRO-01` introduces no new economic, statistical, or methodological threshold. It is a deterministic promotion aggregation over the preregistered substantive criteria.

## Final Gate Semantics

- The substantive criteria are exactly the 25 IDs from `INT-01` through `CON-04` listed above.
- The promotion criterion is exactly one ID: `PRO-01`.
- The complete gate contains exactly 26 criterion IDs.
- `gate_passed = PRO-01`.
- Validation unlock is `true` only when `PRO-01` is `true`.
- When `PRO-01` is `false`, the outcome is `discovery_failed`, and validation, paper trading, live trading, strategy activation, sizing, and order generation remain disabled.
- No discretionary promotion is permitted.

## Canonical Payload Hash

Incorporating this clarification into a future YAML preregistration changes the canonical payload and therefore requires recomputation of `canonical_payload_sha256`. No replacement hash is calculated by this clarification.

The prior draft hash `0526e9fcd01865932c8dc77b02a1e793578c616eb9644acd8d635d784f92a465` is superseded only once the corrected YAML has been generated and validated.

## Scope

This clarification removes the `PRO-01` circularity and makes the promotion criterion mechanically calculable. It does not change selection, metrics, thresholds, decision variants, historical data, or the frozen conceptual design, and it does not reopen methodology.
