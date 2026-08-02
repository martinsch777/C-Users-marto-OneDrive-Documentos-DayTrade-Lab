# HYP-VWAP-DEV-01 Implementation Plan

```text
hypothesis_id: HYP-VWAP-DEV-01
plan_status: approved_for_implementation
classification: PLAN_READY
human_approved: true
implementation_allowed: true
implementation_started: false
historical_data_access_allowed: false
discovery_execution_allowed: false
blockers_remaining: 0
preregistration_metadata_commit: 236ca1c6c83695962b51f4ed67b57898130d8f6e
```

## 1. Executive Summary

This document translates the frozen HYP-VWAP-DEV-01 preregistration into a
technical implementation plan. It does not authorize or contain implementation
code. The minimum proposed shape is one pure methodology module, one governed
discovery runner, and one test module for each.

The plan is `PLAN_READY`. Amendment `HYP-VWAP-DEV-01-AMD-01` resolves the
leave-one-out blocker by freezing an exact, deterministic oldest-date tie-break.
Implementation is authorized only for core methodology and synthetic tests;
historical-data access and discovery execution remain prohibited.

## 2. Freezes And Canonical Hash

```text
conceptual_design_freeze_commit: 5a0c3dee3af99093fb5ff5eb2ab641767d1e086f
clarification_freeze_commit: 9d2bbf721c70da7a4b02df49d9973cffc77c09f6
preregistration_freeze_commit: 6fbd8f09b279c0b83d31602c7c75a42787c70b42
preregistration_metadata_commit: 236ca1c6c83695962b51f4ed67b57898130d8f6e
amendment_id: HYP-VWAP-DEV-01-AMD-01
canonical_payload_sha256_previous: 7a88b21a6ce007d3f607e36e380b8e1ece84bd053728b42acddb934ea285452c
canonical_payload_sha256_previous_status: superseded
canonical_payload_sha256: 8420c66ffb97da893a9dcd3ebbc4903af116a4104891204397f554a0d12118eb
```

The preregistration commit is external metadata and is not part of the
canonical payload. Implementation must validate, never rewrite, the YAML and
canonical hash.

## 3. Permitted Scope

- Design pure, deterministic functions and explicit typed inputs/outputs.
- Design synthetic unit tests and structural runner integration tests.
- Reuse stable calendar, manifest, hashing, progress, and atomic-write patterns.
- Design `validate_implementation` so it opens no dataset or real manifest.
- Design `run_discovery` preflight, without executing it in this task.

## 4. Prohibited Scope

- No code, executable tests, runner, artifacts, YAML changes, or hash changes.
- No OHLC, real dataset, real manifest, 2025, 2026, or discovery access.
- No new threshold, filter, tie-break, variant, cost, control, or partition.
- No strategy, sizing, order, broker, paper, or live surface.

## 5. Reuse Audit

Classification values are `reusable_as_is`, `reusable_with_adapter`,
`hypothesis_specific`, and `missing_shared_capability`.

| capability | existing_file | existing_symbol | reuse_directly | adaptation_required | new_code_required | classification | reason | risk |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| preregistration validation | `src/research/hyp_drive_pb_01.py` | `load_config_yaml`, `_validate_full_mapping` | no | yes | yes | reusable_with_adapter | Strict config model is sound but schema is hypothesis-specific | medium |
| canonical hash validation | `src/research/hyp_drive_pb_01.py` | `canonical_payload_bytes`, `canonical_payload_hash` | no | yes | yes | reusable_with_adapter | Serialization contract matches; excluded key name differs | low |
| dataset manifest gate | `src/data/dataset_manifest.py` | `require_approved_dataset_manifest_file` | yes | no | no | reusable_as_is | Public approved-file and SHA gate | low |
| approved-session calendar | `src/data/sessions.py` | `EquitySessionCalendar.us_equity` | yes | no | no | reusable_as_is | Handles RTH, holidays, DST, and early closes | low |
| temporal cropping | `src/research/hyp_drive_pb_01_discovery.py` | `crop_discovery_period` | no | yes | yes | reusable_with_adapter | Correct pattern; constants must come from VWAP config | low |
| causal 1m-to-5m resample | `src/research/hyp_drive_pb_01_discovery.py` | `resample_rth_1min_to_5min` | no | yes | yes | reusable_with_adapter | Logic reusable; must accept calendar and reject dependent events explicitly | medium |
| completed-bar validation | `src/research/hyp_drive_pb_01_discovery.py` | `validate_minute_frame`, `build_daily_approved_sessions` | no | yes | yes | reusable_with_adapter | Strong validation; contracts and diagnostics need VWAP names | medium |
| VWAP calculation | none suitable | none | no | no | yes | hypothesis_specific | Existing DRIVE VWAP is descriptive and not the frozen event selector | high |
| event detection | none suitable | none | no | no | yes | hypothesis_specific | Breach, immediate confirmation, crossing cancellation are unique | high |
| path metrics | `src/research/hyp_drive_pb_01_discovery.py` | `compute_path_metrics` | no | yes | yes | reusable_with_adapter | Horizon geometry reusable; event object differs | medium |
| oriented returns | `src/research/hyp_drive_pb_01.py` | `oriented_return` | yes | small enum adapter | yes | reusable_with_adapter | Formula is identical; direction type differs | low |
| MFE/MAE | `src/research/hyp_drive_pb_01_discovery.py` | `compute_path_metrics` | no | yes | yes | reusable_with_adapter | Same formulas, different event origin contract | medium |
| cost calculation | `src/research/hyp_or_cont_event_01.py` | `round_trip_cost_return` | no | yes | yes | reusable_with_adapter | Price-dependent shape reusable; exact VWAP formulas differ | low |
| unconditional control | `src/research/hyp_or_cont_event_01.py` | `compute_unconditional_control` | no | yes | yes | reusable_with_adapter | Optimized exact-time matching and progress are suitable | medium |
| aggregation | `src/research/hyp_drive_pb_01_discovery.py` | `_summary_record`, `_grouped_metric_table` | no | yes | yes | reusable_with_adapter | Output schema and required groups differ | medium |
| bootstrap | `src/research/hyp_drive_pb_01_discovery.py` | `clustered_percentile_bootstrap_arrays` | no | yes | yes | reusable_with_adapter | Vectorized cluster sums and progress match the frozen method | low |
| annual stability | `src/research/hyp_drive_pb_01.py` | gate helpers | no | yes | yes | reusable_with_adapter | VWAP requires separate gross and incremental yearly rules | medium |
| concentration | `src/research/hyp_drive_pb_01.py` | `annual_concentration` | no | yes | yes | reusable_with_adapter | Formula and failure policy match; config type differs | low |
| leave-one-out | `src/research/hyp_drive_pb_01.py` | `leave_one_largest_session_out_concentration` | no | yes | yes | reusable_with_adapter | Amendment freezes maximum absolute contribution then oldest ISO date | medium |
| PRO-01 aggregation | none suitable | none | no | no | yes | hypothesis_specific | Must validate exact 25 inputs and terminal states | high |
| progress reporting | `src/research/hyp_drive_pb_01_discovery.py` | `ExecutionProgress` | no | yes | yes | reusable_with_adapter | Stable stage/progress model; hypothesis stage names differ | low |
| atomic JSON writes | `src/research/hyp_drive_pb_01_discovery.py` | `_atomic_replace_with_retry`, `_write_json_atomic` | no | expose shared API | maybe | missing_shared_capability | Correct WinError 5 behavior exists but is private | medium |
| interruption handling | `src/research/hyp_drive_pb_01_discovery.py` | `run_discovery` exception paths | no | yes | yes | reusable_with_adapter | Preserve temp/progress and no final directory | low |
| implementation-only validation | `src/research/hyp_drive_pb_01_discovery.py` | `validate_implementation` | no | yes | yes | reusable_with_adapter | Must validate VWAP freezes/hash without opening data | low |
| checksum/output closure | `src/research/hyp_drive_pb_01_discovery.py` | `_write_checksums`, `_verify_checksums` | no | yes | yes | reusable_with_adapter | Closed inventory pattern is reusable | low |

No stable private symbol should be copied silently. During implementation review,
either expose the atomic retry as a shared public helper with its existing
behavior and tests, or explicitly approve a temporary dependency on the private
symbol. This is an engineering review item, not a methodological blocker.

## 6. Proposed Architecture

### Pure Methodology Module

`src/research/hyp_vwap_dev_01.py` would contain config loading/validation,
canonical validation adapters, immutable records, causal transformations,
event formation, path metrics, controls, aggregate metrics, gate criteria, and
PRO-01. It must have no filesystem, subprocess, CLI, or output-directory state.

### Governed Runner

`src/research/hyp_vwap_dev_01_discovery.py` would contain CLI parsing, runtime
Git checks, manifest/data gates, bounded loading, stage progress, interruption
handling, checksums, atomic writes, and final-directory promotion.

### Separation Decision

- Methodological logic and dataset orchestration must be separate.
- Preregistration validation belongs in the pure module; runtime freeze/HEAD
  validation belongs in the runner.
- Outputs and progress belong only in the runner.
- Dependencies such as calendar, RNG, retry sleeper, clock, filesystem paths,
  and progress callbacks must be injectable for synthetic tests.

## 7. Files A Future Authorized Task Would Create

| file | purpose |
| --- | --- |
| `src/research/hyp_vwap_dev_01.py` | Pure frozen methodology and gate |
| `tests/test_hyp_vwap_dev_01.py` | Synthetic unit and property-style boundary tests |
| `src/research/hyp_vwap_dev_01_discovery.py` | Governed discovery orchestration and CLI |
| `tests/test_hyp_vwap_dev_01_discovery.py` | Structural integration, progress, atomicity, and safety tests |

A shared atomic-I/O file may be proposed only in the implementation review if
the project rejects importing the existing private helper. No broader framework
is proposed.

## 8. Existing Files To Reuse

- `src/data/sessions.py`: `EquitySessionCalendar`.
- `src/data/dataset_manifest.py`: approved manifest and file SHA validation.
- `src/research/hyp_drive_pb_01.py`: formulas/patterns for oriented returns,
  concentration, canonical serialization, and derived gates.
- `src/research/hyp_drive_pb_01_discovery.py`: bounded loading, resample,
  vectorized bootstrap, progress, checksums, atomic output, and interruptions.
- `src/research/hyp_or_cont_event_01.py`: exact-time control optimization and
  reference-equivalence testing pattern.

## 9. Input And Output Contracts

### Pure Inputs

- Parsed frozen config mapping with no duplicate keys.
- Timezone-aware one-minute or five-minute synthetic frames with explicit
  `symbol`, OHLCV, timestamp, and session identity.
- Explicit approved session calendar and excluded-session set.
- Explicit event/path/control frames for downstream pure stages.
- Injected bootstrap replicate count for tests; production must equal 10,000.

### Pure Outputs

- Immutable validated config and deterministic canonical hash result.
- Five-minute bars with completeness and causal availability fields.
- Candidate/exclusion/event records with reason codes.
- Path/control/aggregate tables with finite-status diagnostics.
- Ordered 25-criterion status mapping and separate PRO-01 result.

### Runner Inputs

- CLI mode and expected freeze/hash/implementation HEAD values.
- Fixed config, dataset, manifest, and output paths; no override/bypass flags.

### Runner Outputs

- `validate_implementation`: JSON-serializable status only; no files or data.
- `run_discovery`: one closed temporary artifact inventory promoted atomically
  to a final directory only after checksums and final manifest pass.

## 10. Exact Execution Flow

| stage | inputs | outputs | preconditions | postconditions | terminal errors | progress | reuse |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 Parse CLI | argv | validated request | known mode | no bypass flags | unknown/missing args | mode | runner patterns |
| 2 Verify HEAD/freeze | request, Git | runtime state | repository available | expected commits valid | wrong/missing/non-ancestor SHA | preflight | DRIVE runner |
| 3 Verify canonical hash | YAML bytes | matching hash | no duplicate keys | exact frozen hash | mismatch | preflight | canonical adapter |
| 4 Verify frozen state | config | frozen config | parsed config | required booleans exact | state/type mismatch | preflight | config adapter |
| 5 Verify working tree | Git | clean state | discovery mode only | clean execution tree | staged/unstaged/untracked | preflight | DRIVE runner |
| 6 Validate datasets/manifests | paths | manifest contracts | run mode only | QQQ/SPY approved | missing/bad hash/safety | per symbol | manifest API |
| 7 Crop discovery | bounded frames | 2022-2024 only | timezone valid | no 2025/2026 rows | contamination | per symbol | crop adapter |
| 8 Build approved sessions | frames, calendar, exclusions | session contracts | calendar loaded | complete approved RTH sessions | bad/missing session | per symbol | calendar/session adapter |
| 9 Resample 1m-to-5m | minute rows | complete 5m bars | five contiguous minutes | causal OHLCV buckets | invalid dependent block | rows | resample adapter |
| 10 Calculate VWAP | 5m bars | causal VWAP states | ordered per session | reset and current bar included | invalid volume/state | sessions | hypothesis-specific |
| 11 Detect breach | VWAP bars | one candidate/session | window and VWAP valid | orientation fixed | none; reason-coded exclusion | sessions | hypothesis-specific |
| 12 Confirm immediate bar | candidate, next bar | confirmed/failed | contiguous next bar | no later confirmation | missing/invalid bar | candidates | hypothesis-specific |
| 13 Cancel at execution open | confirmed, next open, prior VWAP | executable/canceled | execution bar exists | crossing equality canceled | incomplete execution | candidates | hypothesis-specific |
| 14 Deduplicate | outcomes | max one event/session | first candidate fixed | no rescan/reentry | contradictory duplicates | sessions | hypothesis-specific |
| 15 Path metrics | events, 5m bars, calendar | horizon rows | execution valid | all paths marked complete | horizon gap/close crossing | events/horizons | path adapter |
| 16 Controls | path rows, approved sessions | controls/incremental | discovery-only pool | exact match and own date excluded | empty/nonfinite pool | groups | OR-CONT adapter |
| 17 Aggregate | primary and descriptive rows | metric tables | finite primary rows | fixed group coverage | missing group/nonfinite | groups | DRIVE adapter |
| 18 Bootstrap | primary rows, seed | three CIs | at least two clusters | 10,000 production replicates | nonfinite/non-estimable | replicates | vectorized DRIVE adapter |
| 19 Stability/concentration | primary rows | yearly/concentration metrics | all years present | threshold states explicit | missing year/zero denominator | groups | DRIVE adapter |
| 20 Leave-one-out | primary rows | LOO metrics | finite date contributions | exactly one complete date selected by `(-abs(contribution), session_date)` | missing/nonfinite contribution | groups | shared adapter |
| 21 Evaluate INT-01..CON-04 | derived metrics | 25 terminal statuses | no caller booleans | exact ordered IDs | missing/nonterminal input | criteria | hypothesis-specific |
| 22 Calculate PRO-01 | 25 statuses | promotion status | all terminal, exact IDs | nonrecursive boolean | recursion/nonterminal/missing | criteria | hypothesis-specific |
| 23 Classify discovery | PRO-01 | pass/fail state | PRO terminal | no discretion | invalid promotion state | classification | simple adapter |
| 24 Atomic artifacts | all outputs | verified temp tree | final absent | `results_written` after writes | write/checksum/replace failure | files | DRIVE runner |
| 25 Manifest/checksums/final progress | temp tree | final directory | closed inventory | final appears once | checksum/inventory mismatch | final | DRIVE runner |

## 11. Proposed Pure Functions

| function | responsibility |
| --- | --- |
| `load_frozen_config(path)` | Strict YAML, duplicate-key and type validation |
| `canonical_payload_bytes(mapping)` | Frozen JSON serialization excluding only hash |
| `validate_frozen_config(mapping, expected_hash)` | Freeze, state, safety, IDs, and hash checks |
| `crop_discovery_period(frame, start, end, timezone)` | Inclusive 2022-2024 crop |
| `resample_complete_rth_1m_to_5m(frame, calendar)` | Complete causal buckets only |
| `attach_causal_session_vwap(frame)` | Typical-price cumulative VWAP and zero-volume states |
| `signed_deviation(close, vwap)` | Exact proportion or undefined |
| `detect_first_candidate(session_bars, config, close_time)` | Strict threshold/window and fixed orientation |
| `evaluate_immediate_confirmation(candidate, next_bar)` | Same side and smaller absolute deviation |
| `evaluate_execution_open(confirmed, open_price, prior_vwap)` | Crossing/equality cancellation |
| `detect_session_event(session_bars, config, calendar)` | Single-candidate state machine |
| `compute_path_metrics(events, bars, calendar)` | Horizons, returns, MFE/MAE, costs |
| `build_exact_time_control(events, candidates)` | Exact symbol/year/time/horizon/orientation control |
| `clustered_percentile_bootstrap(rows, config, callback, replicates=None)` | Session-date percentile CIs |
| `annual_stability(rows)` | Required yearly counts and signs |
| `annual_concentration(rows)` | Frozen contribution ratio |
| `select_leave_one_out_session(session_contributions)` | Pure finite-input selection by `(-abs(value), ISO date)`; oldest exact tie, one date, input-order independent, no RNG |
| `leave_one_largest_session_out(rows)` | Remove all QQQ/SPY events for the single selected date and recompute LOO metrics |
| `derive_substantive_criteria(metrics, reports, config)` | Exact 25 derived statuses |
| `evaluate_pro_01(statuses, config)` | Exact, terminal, nonrecursive aggregation |
| `classify_discovery(pro_status)` | Frozen classification and safety state |

## 12. Shared Infrastructure Integrations

Use dependency injection for calendar, filesystem, Git subprocess runner,
monotonic clock, sleep, RNG, progress callback, and atomic replacer. Public
shared APIs may be imported directly; hypothesis-private helpers require an
adapter or explicit architecture approval.

## 13. Error Handling

- `ValueError`: malformed synthetic/data/config values.
- `PermissionError`: governance, freeze, hash, temporal, manifest, or safety
  violation.
- `FileNotFoundError`/`FileExistsError`: required inputs absent or final output
  already present.
- Required missing/nonfinite/non-estimable metrics become explicit failed
  criterion states, never silent omission.
- Unexpected errors preserve temp/progress, keep final absent, and propagate.

## 14. Progress And Interruptions

Use one immutable stage record per stage plus in-place progress counters for
groups and bootstrap replicates. Retries must not duplicate stages.
`KeyboardInterrupt` records one interruption marker, preserves the temp tree,
sets `results_written=false`, and never creates the final directory.

## 15. Atomic Writes

JSON writes use a same-directory unique temp file and `os.replace` with the
existing bounded progressive retry policy for `PermissionError` and
`OSError.winerror==5` only. CSVs are written inside the run temp directory.
The final directory is promoted once after closed-inventory checksum
verification. A write is not successful before replacement completes.

## 16. Performance And Memory

- Process symbols and sessions in deterministic order.
- Compute VWAP vectorially by session cumulative sums.
- Index bars by `(symbol, session_date, timestamp)` for event/path lookup.
- Pre-group control pools by symbol/year/HH:MM/horizon/orientation.
- Use NumPy cluster sums/counts for 10,000 bootstrap replicates in bounded
  blocks; do not approximate the statistic.
- Materialize path rows once; avoid retaining duplicate full minute frames.
- Emit progress by completed group/block, not every row.

## 17. Security

No broker imports, network calls, dynamic code, arbitrary output roots, strategy
objects, sizing, or orders. Validate paths against fixed repository contracts.
All safety flags must remain false in validation, runtime manifests, and gate
outputs.

## 18. CLI Modes

| mode | behavior |
| --- | --- |
| `validate_implementation` | Validate code/config/freeze contracts; open no dataset or manifest; write nothing |
| `run_discovery` | Future-only authorized path requiring expected preregistration, implementation freeze HEAD, canonical hash, clean tree, and approved inputs |

No prepare, override, output-path, replicate, symbol, period, threshold, or
bypass flags are proposed.

## 19. Implementation Validation

Validation must prove imports, callable signatures, strict config parsing,
canonical hash, freeze ancestry metadata, exact constants, criterion graph,
PRO-01 nonrecursion, safety flags, and absence of data-opening calls. It must
report `datasets_opened=false`, `manifests_opened=false`,
`artifacts_created=false`, and `discovery_executed=false`.

## 20. Acceptance Criteria

- Every B1-B15 rule maps to a function/stage and required test.
- All 25 substantive criteria are derived from metrics, not caller booleans.
- PRO-01 validates exact inputs and terminal status before aggregation.
- Synthetic suites cover causal boundaries, gate boundaries, runner atomicity,
  interruptions, and safety.
- Production bootstrap remains 10,000/seed 20260802/session-date clustered.
- No real data is needed for unit or implementation-validation suites.
- The leave-one-out selection is covered by exact deterministic synthetic tests.
- `implementation_allowed=true` authorizes only core methodology and synthetic tests.
- Historical-data access and discovery execution remain prohibited.

## 21. Risks

| risk | mitigation |
| --- | --- |
| Lookahead at bar close/open identity | Separate bar identity from timestamp and test future mutation |
| Incomplete 5m bucket silently retained | Completeness reason codes and dependent-event rejection |
| Control pool explosion | Pre-group/index without changing equal weights |
| Bootstrap time/memory | Vectorized cluster sums in deterministic blocks |
| OneDrive transient locks | Existing bounded `os.replace` retry and retained temp tree |
| OneDrive sync exposes partial final | Final directory appears only after all checksums pass |
| Private helper coupling | Public shared atomic API review before implementation |
| Leave-one-out tie changes gate | Enforce amendment key `(-abs(contribution), session_date)` and its synthetic tests |

## 22. Blocker Resolution

`VWAP-IMPL-BLK-01` is resolved by `HYP-VWAP-DEV-01-AMD-01`. There are zero
methodological blockers remaining. The selected date is the first date under
`(-abs(session_incremental_contribution[d]), session_date)`, with ISO dates
ascending, and all QQQ/SPY events on that date are removed together.

The private atomic helper exposure remains an engineering review item and does
not block implementation or change selection, timing, or gate behavior.

## 23. Recommended Implementation Sequence

1. Implement core methodology and synthetic tests while keeping data access closed.
2. Implement strict config/hash validation and pure records first.
3. Implement resample, VWAP, event state machine, paths, and controls.
4. Implement aggregation, bootstrap, concentration, resolved LOO, and gate.
5. Implement runner validation, preflight, progress, atomic outputs, and CLI.
6. Complete all synthetic tests before any separately authorized real-data preflight.
7. Run `validate_implementation` only and freeze implementation separately.

## Implementation Traceability Matrix

| yaml_path | normative_rule | proposed_function_or_stage | test_ids | shared_or_hypothesis_specific | selection_affecting | timing_affecting | gate_affecting |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `mechanism` (B1) | Mean reversion; negative long, positive short | `signed_deviation`, event state machine | EVT-01, RET-01, RET-02 | hypothesis_specific | true | false | true |
| `universe_and_data`; `causal_resample` (B2) | QQQ/SPY, approved RTH 1m to causal 5m | stages 6-9 | GOV-11, RSM-01..05 | shared_adapter | true | true | true |
| `causal_vwap` (B3) | Current completed-bar cumulative typical-price VWAP | `attach_causal_session_vwap` | VWP-01..07 | hypothesis_specific | true | true | true |
| `deviation` (B4) | Signed percentage deviation | `signed_deviation` | THR-01..04 | hypothesis_specific | true | false | true |
| `deviation.threshold` (B5) | Strict symmetric tau 0.005 | `detect_first_candidate` | THR-01..04 | hypothesis_specific | true | false | true |
| `eligible_window` (B6) | 10:00 through close-65m | `detect_first_candidate` | THR-05..12 | hypothesis_specific | true | true | true |
| `event_formation` (B7) | Immediate smaller-deviation confirmation | `evaluate_immediate_confirmation` | EVT-02..09 | hypothesis_specific | true | true | true |
| `execution` (B8) | Next-open execution and crossing cancellation | `evaluate_execution_open` | EXE-01..11 | hypothesis_specific | true | true | true |
| `deduplication` (B9) | First candidate only; no rescan | `detect_session_event` | EVT-10..13 | hypothesis_specific | true | true | true |
| `horizons`; `returns_and_path_metrics` (B10) | 30m primary; 15m/60m/close secondary | `compute_path_metrics` | PTH-01..14 | shared_adapter | false | true | true |
| `unconditional_control` (B11) | Exact-time matched control | `build_exact_time_control` | CTL-01..12 | shared_adapter | false | false | true |
| `costs` (B12) | Frozen baseline/stress formulas | `compute_path_metrics` | PTH-11..14 | shared_adapter | false | false | true |
| `discovery_gate` (B13) | All required and no discretion | criteria/PRO stages | GAT-01..39, PRO-01..09 | hypothesis_specific | false | false | true |
| `temporal_splits` (B14) | Discovery 2022-2024; 2025/2026 closed | crop/preflight | GOV-12, GOV-13, RUN-05 | shared_adapter | true | true | true |
| `safety_flags`; `forbidden_actions` (B15) | Event study only; all trading false | validation/classification | GOV-14, SEC-01..05 | shared_adapter | false | false | true |
| `bootstrap` | Session-date percentile 10,000, seed 20260802 | `clustered_percentile_bootstrap` | BST-01..15 | shared_adapter | false | false | true |
| `concentration` | Annual max absolute share <=0.70 | `annual_concentration` | CON-01..08 | shared_adapter | false | false | true |
| `concentration.leave_one_largest_session_out` | Select by `(-abs(contribution), session_date)`, remove one complete date, and re-evaluate | `select_leave_one_out_session`, `leave_one_largest_session_out` | LOO-01..22 | shared_adapter | false | false | true |
| `discovery_gate.criteria[INT-01]` | Causal integrity true | `derive_substantive_criteria` | GAT-01 | hypothesis_specific | false | false | true |
| `discovery_gate.criteria[INT-02]` | Dataset contract true | same | GAT-02 | hypothesis_specific | false | false | true |
| `discovery_gate.criteria[INT-03]` | Manifest validation true | same | GAT-03 | hypothesis_specific | false | false | true |
| `discovery_gate.criteria[INT-04]` | Lookahead violations =0 | same | GAT-04 | hypothesis_specific | false | false | true |
| `discovery_gate.criteria[INT-05]` | Data-quality failures =0 | same | GAT-05 | hypothesis_specific | false | false | true |
| `discovery_gate.criteria[INT-06]` | No 2025/2026 contamination | same | GAT-06 | hypothesis_specific | false | false | true |
| `discovery_gate.criteria[INT-07]` | Every path complete | same | GAT-07 | hypothesis_specific | false | false | true |
| `discovery_gate.criteria[INT-08]` | One decision variant | same | GAT-08 | hypothesis_specific | false | false | true |
| `discovery_gate.criteria[SMP-01]` | Pooled n>=150 | same | GAT-09, GAT-27 | hypothesis_specific | false | false | true |
| `discovery_gate.criteria[SMP-02]` | Each symbol n>=50 | same | GAT-10, GAT-28 | hypothesis_specific | false | false | true |
| `discovery_gate.criteria[SMP-03]` | Each year n>=40 | same | GAT-11, GAT-29 | hypothesis_specific | false | false | true |
| `discovery_gate.criteria[REP-01]` | Each orientation n>=40 | same | GAT-12, GAT-30 | hypothesis_specific | false | false | true |
| `discovery_gate.criteria[ECO-01]` | Pooled gross mean >0 | same | GAT-13, GAT-31 | hypothesis_specific | false | false | true |
| `discovery_gate.criteria[ECO-02]` | Each symbol gross mean >0 | same | GAT-14 | hypothesis_specific | false | false | true |
| `discovery_gate.criteria[ECO-03]` | Each orientation mean/median >0 | same | GAT-15 | hypothesis_specific | false | false | true |
| `discovery_gate.criteria[ECO-04]` | Pooled/each-symbol baseline net >0 | same | GAT-16 | hypothesis_specific | false | false | true |
| `discovery_gate.criteria[ECO-05]` | Stress net >=0 | same | GAT-17, GAT-32 | hypothesis_specific | false | false | true |
| `discovery_gate.criteria[INC-01]` | Incremental mean >0 | same | GAT-18 | hypothesis_specific | false | false | true |
| `discovery_gate.criteria[UNC-01]` | Three bootstrap lower bounds >0 | same | GAT-19, BST-08..12 | hypothesis_specific | false | false | true |
| `discovery_gate.criteria[STB-01]` | Gross positive in >=2 years | same | GAT-20, GAT-33..34 | hypothesis_specific | false | false | true |
| `discovery_gate.criteria[STB-02]` | Incremental positive in >=2 years | same | GAT-21, GAT-33..34 | hypothesis_specific | false | false | true |
| `discovery_gate.criteria[CON-01]` | Annual concentration <=0.70 | same | GAT-22, GAT-35..36 | hypothesis_specific | false | false | true |
| `discovery_gate.criteria[CON-02]` | LOO concentration <=0.70 | same | GAT-23, LOO-05, LOO-21 | hypothesis_specific | false | false | true |
| `discovery_gate.criteria[CON-03]` | LOO pooled incremental >0 | same | GAT-24, LOO-06, LOO-21 | hypothesis_specific | false | false | true |
| `discovery_gate.criteria[CON-04]` | LOO >=2 positive years with n>=40 | same | GAT-25, LOO-07..09, LOO-21 | hypothesis_specific | false | false | true |
| `discovery_gate.criteria[PRO-01]` | Exact 25 terminal passed statuses | `evaluate_pro_01` | PRO-01..09 | hypothesis_specific | false | false | true |
| `safety_flags` | Trading surfaces remain false | validation/output | SEC-01..05 | shared_adapter | false | false | true |
| `canonical_payload_sha256` | Exact deterministic hash | config validation | GOV-03, GOV-04 | shared_adapter | false | false | true |
