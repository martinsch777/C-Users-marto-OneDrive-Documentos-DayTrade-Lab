# HYP-VWAP-DEV-01 Preregistration Traceability

## Status

```text
hypothesis_id: HYP-VWAP-DEV-01
hypothesis_name: Causal Session VWAP Deviation Mean Reversion
conceptual_design_freeze_commit: 5a0c3dee3af99093fb5ff5eb2ab641767d1e086f
clarification_id: HYP-VWAP-DEV-01-CLAR-01
clarification_freeze_commit: 9d2bbf721c70da7a4b02df49d9973cffc77c09f6
clarification_status: frozen
status: preregistered_not_executed
preregistration_status: frozen
preregistration_created: true
preregistration_frozen: true
preregistration_freeze_commit: 6fbd8f09b279c0b83d31602c7c75a42787c70b42
preregistration_freeze_commit_message: Freeze HYP-VWAP-DEV-01 preregistration
methodology_frozen: true
implementation_allowed: false
implementation_started: false
discovery_executed: false
validation_2025_unlocked: false
historical_2026_decisional: false
decision_variants: 1
translation_complete: true
unresolved_translation_blockers: 0
traceability_complete: true
material_blockers_remaining: 0
canonical_payload_sha256: 7a88b21a6ce007d3f607e36e380b8e1ece84bd053728b42acddb934ea285452c
```

The normative source is `docs/HYP_VWAP_DEV_01_DESIGN_DECISIONS.md` at the
conceptual-design freeze commit above. The complete machine-readable preregistration is
`configs/research/hypotheses/HYP-VWAP-DEV-01.yaml`. This traceability record
also incorporates the non-methodological logical clarification frozen in
`docs/HYP_VWAP_DEV_01_PREREGISTRATION_CLARIFICATIONS.md`. The preregistration
payload is frozen, but implementation and historical access remain prohibited.

The final preregistration audit previously returned `AUDIT_FAIL` because
`PRO-01` was self-referential. `HYP-VWAP-DEV-01-CLAR-01`, frozen at commit
`9d2bbf721c70da7a4b02df49d9973cffc77c09f6`, resolves that blocker without
changing B1-B15, any gate threshold, or any decision variant. No material
blocker remains after this correction.

## B1-B15 Coverage

| design_decision | yaml_path | represented | exact_match | notes |
| --- | --- | --- | --- | --- |
| B1 | `mechanism` | true | true | Mean reversion only; negative long, positive short; continuation prohibited |
| B2 | `universe_and_data`; `causal_resample` | true | true | Mandatory QQQ/SPY, approved 1min RTH source, causal 5min research bars |
| B3 | `causal_vwap` | true | true | Typical-price cumulative session VWAP, current completed bar included, exact zero-volume policy |
| B4 | `deviation.formula`; `deviation.unit` | true | true | Signed percentage deviation only |
| B5 | `deviation.threshold` | true | true | Strict symmetric `tau=0.005`; equality excluded; identical for both symbols |
| B6 | `eligible_window` | true | true | Breach close 10:00 through close-65m; execution through close-60m; dynamic early closes |
| B7 | `event_formation` | true | true | First breach and immediate next-bar confirmation only |
| B8 | `execution` | true | true | Next-bar-open execution using prior completed VWAP; crossing/equality cancellation |
| B9 | `deduplication`; `event_formation` | true | true | One candidate and event per symbol-session; no rescan, reset, reentry, or replacement |
| B10 | `horizons`; `returns_and_path_metrics` | true | true | 30min primary; 15min, 60min, close descriptive; all originate at execution |
| B11 | `unconditional_control` | true | true | Exact symbol/year/HH:MM/horizon control; own date excluded; same orientation |
| B12 | `costs` | true | true | Inherited baseline and stress round-trip formulas |
| B13 | `bootstrap`; `annual_stability`; `concentration`; `missing_data_policy`; `discovery_gate` | true | true | Complete 25-criterion substantive gate plus non-recursive PRO-01 promotion aggregation |
| B14 | `temporal_splits` | true | true | Discovery 2022-2024; 2025 locked; 2026 non-decisional |
| B15 | `current_state`; `safety_flags`; `forbidden_actions` | true | true | Event study only; implementation, strategy, sizing, orders, broker, paper/live disabled |

## Normative Rule Coverage

| design_section | yaml_path | represented | exact_match | notes |
| --- | --- | --- | --- | --- |
| Identity and governance | root; `approval`; `configuration_governance` | true | true | Human-approved frozen preregistration; implementation remains prohibited |
| Selection provenance | root selection/history flags | true | true | All selection, return, event-count, search, and threshold-comparison flags false |
| Causal resample | `causal_resample` | true | true | Standard OHLCV, five contiguous source bars, completed-bar availability, calendar early closes |
| VWAP formula | `causal_vwap` | true | true | Session-reset cumulative typical-price-volume formula through completed bar t |
| Zero cumulative volume | `causal_vwap.zero_volume_policy` | true | true | Undefined VWAP cannot select or confirm; no cross-session or synthetic imputation |
| Deviation and threshold | `deviation` | true | true | Signed proportion with strict symmetric 0.005 boundary and no equality breach |
| Eligible window | `eligible_window` | true | true | Inclusive close timestamps; dynamic close-65m/close-60m boundaries |
| Confirmation | `event_formation.confirmation_requirements` | true | true | Same sign and VWAP side, strictly smaller absolute deviation, no more extreme close |
| Confirmation failure | `event_formation` | true | true | Entire symbol-session invalidated; no later alternative |
| Execution price and state | `execution` | true | true | Following 5min open; completed-bar VWAP only; execution bar contributes nothing pre-open |
| Crossing cancellation | `execution.pre_execution_cancellation` | true | true | Long `>=` VWAP and short `<=` VWAP cancel, including equality |
| Deduplication | `deduplication` | true | true | Maximum one candidate and one confirmed event per symbol-session |
| Horizons | `horizons` | true | true | All required, path complete, same-session; secondary non-decisional |
| Returns and paths | `returns_and_path_metrics` | true | true | Favorable-positive gross, MFE/MAE, net, control, and incremental formulas |
| Exact-time control | `unconditional_control` | true | true | No fallback to another timestamp, year, or symbol; missing control fails |
| Costs | `costs` | true | true | `0.0002+0.02/price` and `0.0004+0.04/price` |
| Partitions | `temporal_splits` | true | true | Validation unlock only after PRO-01; 2026 prohibited for decisions |
| Bootstrap | `bootstrap` | true | true | Session clusters, same-date symbols together, percentile 95%, 10,000, seed 20260802 |
| Annual stability | `annual_stability` | true | true | All three years with n>=40; gross and incremental positive in >=2 years |
| Concentration | `concentration` | true | true | Annual incremental contribution share <=0.70 |
| Leave-one-out | `concentration.leave_one_largest_session_out` | true | true | Complete largest-contribution date removed; annual n>=40 reapplied |
| Missing required data | `missing_data_policy`; gate criterion policies | true | true | False/missing/non-finite/insufficient/non-estimable always fails |
| Promotion and safety | `discovery_gate`; `current_state`; `safety_flags` | true | true | PRO-01 aggregates exactly 25 substantive criteria and is the sole validation unlock; no discretionary promotion or trading capability |

## Gate Coverage

| criterion_id | yaml_path | represented | exact_match | normative requirement |
| --- | --- | --- | --- | --- |
| INT-01 | `discovery_gate.criteria[criterion_id=INT-01]` | true | true | `causal_integrity_passed = true` |
| INT-02 | `discovery_gate.criteria[criterion_id=INT-02]` | true | true | `dataset_contract_passed = true` |
| INT-03 | `discovery_gate.criteria[criterion_id=INT-03]` | true | true | `manifest_validation_passed = true` |
| INT-04 | `discovery_gate.criteria[criterion_id=INT-04]` | true | true | `lookahead_violations = 0` |
| INT-05 | `discovery_gate.criteria[criterion_id=INT-05]` | true | true | `unresolved_data_quality_failures = 0` |
| INT-06 | `discovery_gate.criteria[criterion_id=INT-06]` | true | true | `2025_or_2026_contamination = false` |
| INT-07 | `discovery_gate.criteria[criterion_id=INT-07]` | true | true | Every confirmed event has all required complete causal paths |
| INT-08 | `discovery_gate.criteria[criterion_id=INT-08]` | true | true | `decision_variants = 1` |
| SMP-01 | `discovery_gate.criteria[criterion_id=SMP-01]` | true | true | Pooled events `>=150` |
| SMP-02 | `discovery_gate.criteria[criterion_id=SMP-02]` | true | true | QQQ and SPY events each `>=50` |
| SMP-03 | `discovery_gate.criteria[criterion_id=SMP-03]` | true | true | 2022, 2023, and 2024 events each `>=40` |
| REP-01 | `discovery_gate.criteria[criterion_id=REP-01]` | true | true | Long and short events each `>=40` |
| ECO-01 | `discovery_gate.criteria[criterion_id=ECO-01]` | true | true | Pooled 30min gross mean `>0` |
| ECO-02 | `discovery_gate.criteria[criterion_id=ECO-02]` | true | true | QQQ and SPY 30min gross means each `>0` |
| ECO-03 | `discovery_gate.criteria[criterion_id=ECO-03]` | true | true | Long/short 30min gross means and medians each `>0` |
| ECO-04 | `discovery_gate.criteria[criterion_id=ECO-04]` | true | true | Pooled/QQQ/SPY baseline-net means each `>0` |
| ECO-05 | `discovery_gate.criteria[criterion_id=ECO-05]` | true | true | Pooled stress-net mean `>=0` |
| INC-01 | `discovery_gate.criteria[criterion_id=INC-01]` | true | true | Pooled incremental mean `>0` |
| UNC-01 | `discovery_gate.criteria[criterion_id=UNC-01]` | true | true | Gross/incremental/baseline 95% lower bounds each `>0` |
| STB-01 | `discovery_gate.criteria[criterion_id=STB-01]` | true | true | Gross mean positive in at least 2 required years |
| STB-02 | `discovery_gate.criteria[criterion_id=STB-02]` | true | true | Incremental mean positive in at least 2 required years |
| CON-01 | `discovery_gate.criteria[criterion_id=CON-01]` | true | true | Annual concentration `<=0.70` |
| CON-02 | `discovery_gate.criteria[criterion_id=CON-02]` | true | true | Leave-one-session-out annual concentration `<=0.70` |
| CON-03 | `discovery_gate.criteria[criterion_id=CON-03]` | true | true | Leave-one-session-out pooled incremental mean `>0` |
| CON-04 | `discovery_gate.criteria[criterion_id=CON-04]` | true | true | Leave-one-session-out positive incremental years `>=2`, each year n>=40 |
| PRO-01 | `discovery_gate.criteria[criterion_id=PRO-01]` | true | true | All 25 explicitly listed substantive criteria pass before validation unlock; `self_inclusion=false`; evaluated after all substantive criteria |

The exact normative substantive input set is:

```text
INT-01, INT-02, INT-03, INT-04, INT-05, INT-06, INT-07, INT-08,
SMP-01, SMP-02, SMP-03, REP-01, ECO-01, ECO-02, ECO-03, ECO-04,
ECO-05, INC-01, UNC-01, STB-01, STB-02, CON-01, CON-02, CON-03,
CON-04
```

`PRO-01` is a non-recursive deterministic aggregation evaluated
`after_all_substantive_criteria`. Its `input_criterion_ids` are exactly the 25
IDs above, `self_inclusion=false`, and the set equals all criterion IDs except
`PRO-01`. A `failed`, `false`, missing, non-finite, insufficient,
non-estimable, or unavailable substantive status makes `PRO-01=false` and the
classification `discovery_failed`. The gate reports 26 IDs in total: 25
substantive criteria plus one promotion criterion. `gate_passed=PRO-01`, and
2025 validation unlocks only when `PRO-01=true`.

## Canonical Payload

All YAML fields are canonical except the declared integrity field
`canonical_payload_sha256`, which is excluded solely to avoid self-reference.
External non-methodological fields listed in
`canonical_payload.explicitly_non_methodological_excluded` are removed if
supplied outside the canonical YAML.

Serialization is deterministic JSON with:

```text
encoding: UTF-8
ensure_ascii: true
sort_keys: true
separators: (",", ":")
variable_timestamps: excluded
absolute_paths: excluded
local_environment_information: excluded
algorithm: SHA-256
superseded_canonical_payload_sha256: 0526e9fcd01865932c8dc77b02a1e793578c616eb9644acd8d635d784f92a465
canonical_payload_sha256: 7a88b21a6ce007d3f607e36e380b8e1ece84bd053728b42acddb934ea285452c
independent_hash_run_1: 7a88b21a6ce007d3f607e36e380b8e1ece84bd053728b42acddb934ea285452c
independent_hash_run_2: 7a88b21a6ce007d3f607e36e380b8e1ece84bd053728b42acddb934ea285452c
serialized_payload_bytes: 24437
```

The included payload is every YAML path, including deterministic governance
and clarification metadata, except `canonical_payload_sha256`. The excluded
paths are the integrity hash itself and the declared non-methodological fields:
variable timestamps, absolute paths, local user/host/environment state,
working-tree state, future execution or preregistration commit metadata,
results, historical counts, and run-derived data. These exclusions prevent
self-reference and machine-local or post-execution metadata from changing the
frozen methodological payload.

The preregistration freeze commit SHA
`6fbd8f09b279c0b83d31602c7c75a42787c70b42` was registered after the freeze
to avoid self-reference. The commit SHA is documentary metadata and is not
part of the canonical payload or the YAML. This post-freeze update does not
modify methodology, B1-B15, or any gate criterion. The canonical hash remains
`7a88b21a6ce007d3f607e36e380b8e1ece84bd053728b42acddb934ea285452c`
without recalculation, the preregistration remains frozen, and implementation
is still not authorized.

## Translation Conclusion

Every approved decision, normative rule, and gate criterion is represented
with `represented=true` and `exact_match=true`. The prior `AUDIT_FAIL` blocker
is resolved, traceability is complete, and zero material blockers remain. The
preregistration and methodology are frozen; implementation stays prohibited.
