# HYP-DRIVE-PB-01 Implementation Clarification

## 1. Purpose And Scope

This governance clarification resolves two implementation ambiguities found
during the materialization audit of HYP-DRIVE-PB-01:

1. `tick_size = 0.01` affects event selection and both cost profiles but is not
   listed among the 17 frozen research design parameters.
2. The approved 30-minute primary horizon was represented by two independently
   configurable fields, `primary_horizon_minutes` and `primary_horizon`.

This document interprets the approved conceptual design freeze. It does not
amend the design, approve implementation changes, or authorize execution.

## 2. Frozen Source And Evidence

The controlling source is
`docs/HYP_DRIVE_PB_01_DESIGN_DECISIONS.md` at conceptual design freeze commit
`925cede00f3d9c1b4de46e225f98d4636c19a831`.

The approved memo provides the following direct evidence:

- Section 4.2 states `tick_size = 0.01`.
- Section 4.2 requires the first adverse move to be greater than or equal to
  `tick_size` for both long and short events.
- Section 8 fixes baseline cost as
  `0.0002 + 0.02 / executable_price` and stress cost as
  `0.0004 + 0.04 / executable_price`.
- Section 13 lists exactly 17 frozen numeric or time research constants. It
  counts the minimum pullback as one tick, not the monetary definition of a
  tick, and explicitly states that inherited tick size and baseline/stress
  costs are preserved decisions not counted as newly selected parameters.
- Section 13 fixes the primary horizon at 30 minutes.
- The human-approval section includes a minimum pullback of one tick and a
  primary horizon of 30 minutes.

The value `0.01` is therefore explicit, approved, and not inferential.

## 3. Tick Size Classification

`tick_size` is classified as a `frozen_market_convention`.

Its conceptual roles are:

- market convention: the approved price increment for QQQ and SPY;
- unit of measurement: the unit in which pullback and slippage ticks are
  expressed;
- selection input: one approved tick defines the minimum initial adverse
  pullback;
- cost input: the convention produces the approved monetary slippage terms in
  baseline and stress costs.

It is not an additional research design parameter and is not an optimization
dimension. Its canonical representation is:

```yaml
tick_size_by_symbol:
  QQQ: 0.01
  SPY: 0.01
```

The mapping must be frozen, validated by symbol, non-adjustable,
non-optimizable, and unavailable for runtime override.

## 4. Selected Governance Alternative

**Alternative A is selected.**

The approved memo both fixes `0.01` unequivocally and expressly excludes the
inherited tick size from the 17 newly selected research parameters. Treating it
as an eighteenth research parameter would contradict the approved
degrees-of-freedom classification.

Alternative B is rejected because it would reclassify an inherited market
convention as a new research choice. That would require a methodological
amendment, new human approval, and a new conceptual design freeze without
support in the frozen memo.

## 5. Consequences For Frozen Counts

`parameters_frozen` remains exactly 17.

There is one frozen market-convention family, represented by a symbol-keyed
mapping with two validated entries. The convention count is therefore 1, not 2.
QQQ and SPY each retain the same approved value of `0.01`.

## 6. Consequences For The Canonical Payload

The canonical payload must include `tick_size_by_symbol` under an explicit
frozen market-conventions section. It must not appear as a mutable scalar
default or as an eighteenth research parameter.

The symbol-keyed mapping participates in the canonical payload hash. Any
change, missing symbol, additional symbol, or override attempt must be rejected
or produce a different payload and hash.

This clarification alone does not change the current payload because this task
does not modify executable or canonical artifacts. A later approved
implementation of the clarified representation will change the serialized
payload structure and must therefore produce and propagate a newly calculated
canonical hash. No existing hash may be reused or edited by inference.

## 7. Consequences For Costs

The approved cost methodology remains unchanged:

```text
baseline_cost = 0.0002 + 0.02 / executable_price
stress_cost   = 0.0004 + 0.04 / executable_price
```

For both QQQ and SPY, these formulas preserve:

- baseline commission of `0.0001` per side and one tick of slippage per
  execution;
- stress commission of `0.0002` per side and two ticks of slippage per
  execution;
- `tick_size_by_symbol[symbol] = 0.01`.

The executable implementation must derive the monetary tick component from
the frozen symbol convention while also validating that the resulting
canonical formulas remain exactly those approved above.

## 8. Consequences For Event Selection

The approved selection rule remains:

```text
minimum_initial_adverse_move =
    minimum_initial_adverse_pullback_ticks
    * tick_size_by_symbol[symbol]
```

With the approved values, this is `1 * 0.01 = 0.01` for both QQQ and SPY.
Equality qualifies. Neither the tick count nor the symbol tick size may be
overridden.

Linking the implementation to both approved inputs corrects configuration
governance without changing which events qualify under the canonical design.

## 9. Primary Horizon Resolution

The sole canonical and executable source is:

```yaml
primary_horizon_minutes: 30
```

Any textual label must be derived by a pure operation equivalent to:

```python
f"{primary_horizon_minutes}min"
```

`primary_horizon` must not remain an independent configuration parameter.
Payload labels, matching keys, return columns, bootstrap inputs, and gate
validation must all derive from `primary_horizon_minutes`.

This is a pure implementation correction. The frozen methodology already
specifies one indivisible primary horizon of 30 minutes, so removing the
possibility of `15` versus `"30min"` divergence does not alter the design.

## 10. Single Source Of Truth Architecture

The expected architecture is:

1. The YAML is the sole source of canonical values.
2. The canonical mapping is parsed and validated before constructing
   `DrivePullbackConfig`.
3. `DrivePullbackConfig` contains no duplicated decisional defaults.
4. Python research functions require an explicit validated configuration.
5. A stable list of the 17 research-parameter names may exist in code, but
   `FROZEN_CONSTANTS` must not contain a second copy of their values.
6. Frozen market conventions are loaded from the same canonical mapping and
   validated by symbol.
7. Tests load or construct canonical configuration through the same mapping
   used to verify the YAML.
8. The canonical hash is computed from the validated canonical mapping,
   excluding the hash field itself and non-decisional external metadata.
9. A different value must produce a different validated configuration,
   payload, and hash, or be rejected before research logic executes.
10. Derived labels and formulas must not introduce independent configuration
    values.

This architecture preserves the approved design exactly. It removes duplicate
representations and override paths; it does not select a new parameter,
threshold, horizon, cost, or event rule.

## 11. Methodology Assessment

`methodology_changed` is `false`.

The tick size, one-tick selection threshold, cost formulas, 30-minute horizon,
17-parameter count, and one-variant budget were all fixed by the approved
memo. This clarification only assigns an explicit governance class and
specifies how software must represent already approved decisions.

A new conceptual design freeze is not required for this clarification.
Implementation still requires normal human approval and a separately
identifiable implementation change and verification cycle.

## 12. Permitted Technical Actions

After human approval of this clarification, a later implementation task may:

- make the YAML the sole canonical value source;
- add and validate `tick_size_by_symbol` as a frozen market convention;
- construct configuration explicitly from the validated YAML mapping;
- remove duplicated decisional defaults and duplicated frozen values;
- derive the primary-horizon label from `primary_horizon_minutes`;
- link minimum pullback and costs to the validated symbol tick size;
- add counterexample, validation, payload, and hash tests;
- regenerate and consistently propagate the canonical payload hash;
- update downstream preregistration and registry representations without
  changing approved values or formulas.

## 13. Prohibited Technical Actions

This clarification does not permit:

- modifying the approved conceptual-design memo;
- changing `parameters_frozen` from 17;
- changing either symbol's tick size from `0.01`;
- changing the one-tick pullback threshold;
- changing baseline or stress cost formulas;
- changing the 30-minute primary horizon;
- adding variants, optimization paths, or runtime overrides;
- reusing an old hash after payload structure changes;
- reading OHLC or manifests;
- executing discovery or opening 2025 or 2026;
- creating strategies, sizing, orders, paper execution, or live execution.

## 14. HUMAN_APPROVAL

The project owner reviewed and approved this implementation-governance
clarification on 2026-07-28.

The conceptual design freeze remains
`925cede00f3d9c1b4de46e225f98d4636c19a831`. This document does not replace,
amend, or otherwise modify that freeze.

The future commit containing this approved clarification will be the
implementation clarification freeze commit. Its SHA does not yet exist and
must not be invented, abbreviated, or inferred before that commit is created.

```yaml
approval_status: approved
approved_by: project_owner
approval_date: 2026-07-28
approval_scope: implementation_governance_clarification
selected_alternative: A
research_parameters_count: 17
frozen_market_conventions_count: 1
methodology_changed: false
requires_new_conceptual_design_freeze: false
ready_for_implementation_correction: true
```

## 15. Clarification Status

```yaml
clarification_id: HYP-DRIVE-PB-01-IMPL-CLAR-01
conceptual_design_freeze_commit:
  925cede00f3d9c1b4de46e225f98d4636c19a831
tick_size_classification: frozen_market_convention
selected_alternative: A
research_parameters_count: 17
frozen_market_conventions_count: 1
primary_horizon_source: primary_horizon_minutes
methodology_changed: false
requires_new_conceptual_design_freeze: false
ready_for_human_approval: true
human_approved: true
```
