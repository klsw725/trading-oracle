# PRD: Phase 29 evidence gate
> **상태**: 📝 초안
> **SPEC 참조**: [../SPEC.md](../SPEC.md)

## 문제

Phase 22부터 Phase 28까지는 v4 측정, snapshot, legacy migration, market context, attribution, replay, calibration 계약을 각각 정의한다. 하지만 계약 문서가 존재한다는 사실만으로 v4가 완료됐다고 볼 수 없다. v4 완료 판정은 각 계약이 만든 증거 artifact를 사람이 읽고, 기계가 파싱하고, 실패 fixture가 실제로 실패하는지 확인한 뒤에만 가능하다.

Phase 29는 v4 전용 evidence gate다. 이 gate는 v4 release가 measurement, snapshot, migration, attribution, replay, calibration을 통과했는지 판정한다. 문서 작성 상태, 작업자 자기 보고, grep hit, 또는 후속 v5부터 v9까지의 문서 상태는 v4 completion evidence가 아니다.

## 목표

1. v4 전용 completion evidence를 measurement, snapshot, migration, attribution, replay, calibration으로 나눠 정의한다.
2. Phase 22부터 Phase 29까지 필요한 artifact, schema, identity, hash, tool version, pass/fail/inconclusive 상태를 표준화한다.
3. native v4 full-pass release manifest와 실패 fixture를 machine-readable JSON으로 제공한다.
4. legacy report가 invalid 또는 unverifiable일 때 표시 방법과 canonical metric 차단 범위를 고정한다.
5. 독립 review matrix와 deterministic parser, fixture mutation, manual Read 요구를 release gate에 포함한다.
6. stale, dirty, misleading, malformed, interrupted verification, resume, repeated interruption probe를 실패 우선으로 고정한다.
7. v5, v6, v7, v8, v9 문서와 completion status가 이 gate의 입력도 출력도 아님을 명시한다.

## 비목표

1. 제품 코드, data, config, source file을 변경하지 않는다.
2. legacy snapshot을 native v4로 승격하지 않는다.
3. 실제 market data fetch, LLM 호출, broker 주문, browser QA를 요구하지 않는다.
4. v5부터 v9까지의 문서 완료 여부를 검사하거나 차단하지 않는다.
5. 작업자 자기 보고서나 grep 결과만으로 통과시키지 않는다.

## 선행 계약

| 계약 | Phase 29에서 요구하는 증거 |
| --- | --- |
| [Phase 22 측정 계약](phase22-measurement-contract.md) | entry, exit, horizon, benchmark, corporate action, stale latest-close 차단 결과 |
| [Phase 23 snapshot 재현성](phase23-snapshot-reproducibility.md) | native snapshot schema, deterministic ID/hash, source freshness, parser/config/model version |
| [Phase 24 legacy backfill](phase24-legacy-backfill.md) | immutable source inventory, coverage report, audit-only marking, invalid legacy exclusion |
| [Phase 25 시장 컨텍스트 분리](phase25-market-context-separation.md) | market, exchange, calendar, timezone, benchmark, FX, blocked/degraded field evidence |
| [Phase 26 recommendation attribution](phase26-recommendation-attribution.md) | five-action denominator, ledger hash chain, blocked and rejected preservation |
| [Phase 27 full workflow replay](phase27-full-workflow-replay.md) | replay eligibility, outcome/verbatim/recompute separation, checkpoint and resume behavior |
| [Phase 28 HOLD confidence calibration](phase28-hold-confidence-calibration.md) | BUY/SELL/HOLD correctness labels, Brier, ECE, cohort separation, promotion no-op rules |
| 숙의 수용 기준 | before/after consensus trace와 code-based quant 변경 금지 evidence |

## v4-only scope boundary

This gate reads only v4 completion artifacts and v4 dependency evidence. It never reads v5, v6, v7, v8, or v9 document completion status. If a v5 through v9 document is missing, complete, malformed, or still draft, this Phase 29 gate result is unchanged.

| outside artifact | gate behavior |
| --- | --- |
| `docs/specs/v5/**` | ignored for Phase 29 pass, fail, and inconclusive states |
| `docs/specs/v6/**` | ignored for Phase 29 pass, fail, and inconclusive states |
| `docs/specs/v7/**` | ignored for Phase 29 pass, fail, and inconclusive states |
| `docs/specs/v8/**` | ignored for Phase 29 pass, fail, and inconclusive states |
| `docs/specs/v9/**` | ignored for Phase 29 pass, fail, and inconclusive states |

Any failure in this PRD closes only v4 promotion. It never marks v5 through v9 as failed, incomplete, complete, blocked, or ready.

## Gate state vocabulary

| state | meaning | promotion effect |
| --- | --- | --- |
| `pass` | Required artifact exists, identity and hashes match, schema and tool version are accepted, manual Read and parser checks agree, and failure fixtures fail as expected. | v4 promotion can continue. |
| `fail` | Required artifact is absent, malformed, stale, hash-mismatched, dirty, misleading, or legacy is incorrectly promoted. | v4 promotion is blocked. |
| `inconclusive` | Artifact is structurally valid but cannot prove completion, usually because a horizon is pending, sample size is insufficient, independent review is missing, or verification was interrupted without a valid resume. | v4 promotion is blocked until remediation supplies evidence. |

`inconclusive` is not a soft pass. It is a closed v4 gate state with a remediation path.

## Artifact identity contract

Every evidence artifact must carry the fields below. The gate rejects artifacts that omit identity, schema, hash, or tool version.

| field | required rule |
| --- | --- |
| `artifact_id` | Stable ID with type prefix and first 20 hex of canonical input hash. |
| `artifact_type` | One of the full allowed list in `artifact_contract.allowed_artifact_types`: `measurement_report`, `measurement_fixture_result`, `snapshot_manifest`, `snapshot_schema_validation`, `snapshot_hash_report`, `legacy_coverage_report`, `invalid_legacy_report`, `legacy_source_inventory`, `market_context_report`, `blocked_degraded_field_report`, `attribution_ledger_report`, `denominator_report`, `ledger_hash_chain_report`, `replay_report`, `checkpoint_report`, `resume_report`, `calibration_report`, `calibration_fixture_result`, `promotion_noop_report`, `release_manifest`, `review_matrix`, `gate_decision_report`. |
| `schema_version` | Contract version that matches the producing Phase. |
| `producer_tool` | Deterministic tool or script name, not a human name. |
| `producer_tool_version` | Semantic or content hash version of the tool. |
| `generated_at` | ISO 8601 timestamp with timezone. |
| `input_refs[]` | Path, artifact ID, artifact type, schema version, and expected hash for each input. Empty list is allowed only for genesis or self-describing fixture artifacts. |
| `content_hash` | `sha256:<64 lowercase hex>` over canonical redacted artifact body with hash fields removed. |
| `tool_config_hash` | Hash of redacted tool config that affects output. |
| `review_refs[]` | Manual Read, deterministic parser, fixture mutation, independent review, or resume review evidence IDs. |

Canonical JSON follows Phase 23 rules: UTF-8, sorted object keys, semantic array order preserved, redaction before hash, no insignificant whitespace, and hash fields excluded from their own hash.

## Required artifacts by Phase

| Phase | required artifacts | pass condition | fail condition | inconclusive condition |
| --- | --- | --- | --- | --- |
| Phase 22 | `measurement_report`, `measurement_fixture_result` | Entry and exit sessions, N-session horizons, benchmark excess, absolute return, corporate action provenance, and stale latest-close rejection all match fixtures. | Latest close substitutes an N-session exit, corporate action provenance is missing but numeric success is reported, invalid horizon is accepted. | Horizon is still pending or price source is within allowed grace period. |
| Phase 23 | `snapshot_manifest`, `snapshot_schema_validation`, `snapshot_hash_report` | Native v4 snapshot has required timestamps, market context, source freshness, candidate audit, provider/prompt/config/parser versions, raw/parsed result state, content hashes. | Hash mismatch, parser version missing, redaction after hash, source freshness hidden, worker prose replaces artifact. | Raw text retention is hash-only and verbatim replay eligibility is therefore explicitly false. |
| Phase 24 | `legacy_coverage_report`, `invalid_legacy_report`, `legacy_source_inventory` | All legacy sources are inventoried by path and hash, derived records are audit-only, canonical metric eligible count is zero, invalid legacy is marked. | Coverage report missing, source mutation detected, legacy marked native, unverifiable legacy reported as success. | External backfill source is unavailable but source inventory and exclusion marking are valid. |
| Phase 25 | `market_context_report`, `blocked_degraded_field_report` | KR and US contexts use correct calendar, timezone, benchmark, currency, FX, regime source, blocked and degraded fields. | KOSPI regime used as direct US regime, benchmark substituted across markets, US market-cap KRW contamination unblocked. | Market is unsupported but absolute return is separated from benchmark excess with `insufficient_context`. |
| Phase 26 | `attribution_ledger_report`, `denominator_report`, `ledger_hash_chain_report` | BUY, SELL, HOLD, BLOCKED, and CANDIDATE_REJECTED are preserved in denominator evidence with immutable event hashes. | Rejected candidate disappears, blocked BUY disappears, HOLD has an order, hash chain breaks. | Corrected duplicate exists and latest correction chain is valid but older event is excluded. |
| Phase 27 | `replay_report`, `checkpoint_report`, `resume_report` | Verbatim, outcome, and recompute eligibility are separated, full workflow states are asserted, cancellation and resume prove idempotence. | Signal-only backtest is labeled full replay, cancelled run reports success, dirty recompute starts, stale state passes. | Recompute is disabled by missing budget or provider unavailability while outcome replay remains valid. |
| Phase 28 | `calibration_report`, `calibration_fixture_result`, `promotion_noop_report` | BUY/SELL/HOLD labels, Brier, ECE, cohort keys, minimum sample no-op, and legacy exclusion match fixtures. | Calibration report missing, label-only confidence accepted, HOLD trade PnL used, cohort keys mixed. | Sample is below promotion minimum and report correctly returns `insufficient_sample`. |
| Phase 29 | `release_manifest`, `review_matrix`, `gate_decision_report` | All required artifacts above are present, fresh, hash-matched, independently reviewed, and mutation failures close only v4. | Any required artifact fails, review matrix missing, self-report or grep is used as pass evidence. | Verification was interrupted and has a valid checkpoint but no completed resume yet. |

## Domain evidence requirements

| domain | required evidence | cannot pass with |
| --- | --- | --- |
| measurement | Phase 22 report with mature and pending examples, independent return arithmetic, stale latest-close mutation failure. | A chart, a current price lookup, or prose saying N-day was checked. |
| snapshot | Phase 23 native snapshot manifest, schema validation, redaction-before-hash proof, parser version proof. | A grep hit for `schema_version` or a screenshot of JSON. |
| migration | Phase 24 coverage and invalid legacy reports, source inventory hashes, zero native promotion proof. | A count typed by a worker or modified legacy source files. |
| attribution | Phase 26 ledger validation, five-action denominator count, hash chain verification. | Only executed BUY trades or missing rejected candidates. |
| replay | Phase 27 report with mode eligibility, state transitions, checkpoint and resume records. | Signal-only backtest success or cancelled run success text. |
| calibration | Phase 28 calibration artifact with cohort key, Brier, ECE, sample eligibility, promotion no-op. | Confidence labels, legacy hit rates, or insufficient sample promoted as success. |

## Invalid legacy report marking

Legacy evidence must be visible and explicitly excluded. The required invalid legacy report fields are:

| field | required value or rule |
| --- | --- |
| `legacy_audit_only` | `true` for every legacy source and derived record. |
| `native_v4_eligible` | `false` for every legacy source and derived record. |
| `canonical_metric_eligible` | `false` for every legacy source and derived record. |
| `calibration_eligible` | `false` unless a future native record, not this legacy source, supplies Phase 28 requirements. |
| `invalid_reason[]` | Must include missing native fields such as raw prompt, data cutoff, candidate universe, portfolio state, or unverifiable market context. |
| `source_hash` | Hash of the immutable legacy source file. |
| `derived_hash` | Hash of the audit-only derived artifact when it exists. |

An unverifiable legacy record can support audit coverage only. If a report says it proves native v4 performance, the gate fails with `legacy_promoted_to_native`.

## Review matrix

| review lane | reviewer | input | required action | pass evidence |
| --- | --- | --- | --- | --- |
| manual_read | human or agent reader | PRD and artifact paths | Read full artifact content, not only filename or grep line. | `manual_read_evidence_id` with observed sections and line-independent findings. |
| deterministic_parser | local parser | release manifest and all referenced artifacts | Parse JSON, verify schema versions, hashes, required states, and local scope. | `parser_result_id` with pass/fail fixture counts. |
| fixture_mutation | local parser | copied fixture objects in memory | Remove or alter required fields and prove the gate fails. | `mutation_result_id` with each expected failure. |
| independent_review | reviewer not producing the artifact | manifest, parser output, mutation output | Confirm no self-report, grep-only, stale, dirty, or misleading evidence passes. | `independent_review_id` and decision. |
| resume_review | local parser | checkpoint and resume artifacts | Confirm interrupted verification resumes with same input hash and idempotency key. | `resume_result_id` with no duplicated side effects. |

At least one independent review lane must pass after deterministic parser and mutation evidence exist. The artifact producer cannot be the only reviewer.

## Promotion, blocking, and remediation

| gate result | release action | remediation |
| --- | --- | --- |
| `pass` | v4 release manifest can be promoted for downstream Task 9 SPEC synthesis. | Keep artifacts immutable and store hashes in the manifest. |
| `fail` | Block v4 promotion. Do not mark any v5 through v9 document or SPEC. | Fix the failing artifact, regenerate the affected hash chain, rerun parser, mutation, manual Read, and independent review. |
| `inconclusive` | Block v4 promotion without declaring the domain successful. Do not mark any v5 through v9 document or SPEC. | Provide missing sample, mature pending horizon, complete resume, or add a clear exclusion report. |

Remediation must be append-only when artifacts have already been referenced. Existing reports are not rewritten unless the same canonical content is reproduced byte for byte.

## Required probes

| probe | detection rule | expected result |
| --- | --- | --- |
| `stale_evidence` | Artifact `generated_at`, source `as_of`, or manifest input hash is older than the allowed freshness window, or latest close is used as Phase 22 exit. | `fail` for v4 only. |
| `dirty_worktree` | Verification starts with source, data, config, or gate-affecting docs different from declared input hash. | Block v4 promotion before parser result is trusted. |
| `misleading_success_output` | Report says passed while a required artifact is missing, failed, inconclusive, cancelled, stale, legacy-only, or hash-mismatched. | `fail` for v4 only. |
| `malformed_artifact` | Invalid JSON, missing schema version, bad hash format, duplicate artifact ID, broken ledger hash chain, or unsupported state. | `fail` before domain aggregation. |
| `interrupted_verification_resume` | Verification stops mid-run and resume lacks checkpoint, same input hash, or same idempotency key. | `inconclusive` if checkpoint is valid but resume incomplete, else `fail`. |
| `repeated_interruption` | Second or later resume repeats completed side effect, skips mutation proof, or changes output hash for same input. | `fail` for v4 only. |

## Fixture matrix

| fixture | expected state | required proof |
| --- | --- | --- |
| `native_full_pass_release_manifest` | `pass` | All six domains plus Phase 29 review artifacts present and hash-matched. |
| `missing_migration_coverage` | `fail` | Phase 24 coverage artifact missing, v4 only blocked. |
| `missing_calibration_report` | `fail` | Phase 28 calibration report missing, v4 only blocked. |
| `mismatched_hashes` | `fail` | Snapshot or ledger artifact hash differs from manifest, v4 only blocked. |
| `stale_evidence` | `fail` | Evidence freshness window exceeded or stale latest close used, v4 only blocked. |
| `unverifiable_legacy` | `fail` | Legacy source lacks invalid marking or is promoted to native, v4 only blocked. |
| `interrupted_with_valid_checkpoint` | `inconclusive` | Checkpoint exists and input hash matches, but resume has not completed. |
| `repeated_interruption_bad_resume` | `fail` | Resume duplicates side effect or skips mutation proof. |

## Machine-readable gate fixture

```json
{
  "schema_version": "v4.evidence_gate.phase29.1",
  "gate_id": "gate_v4_phase29_release_fixture",
  "scope": {
    "version": "v4",
    "included_phases": ["Phase 22", "Phase 23", "Phase 24", "Phase 25", "Phase 26", "Phase 27", "Phase 28", "Phase 29"],
    "excluded_versions": ["v5", "v6", "v7", "v8", "v9"],
    "excluded_versions_never_affected": true
  },
  "artifact_contract": {
    "hash_algorithm": "sha256",
    "canonical_json_version": "phase23-canonical-json.1",
    "allowed_artifact_types": [
      "measurement_report",
      "measurement_fixture_result",
      "snapshot_manifest",
      "snapshot_schema_validation",
      "snapshot_hash_report",
      "legacy_coverage_report",
      "invalid_legacy_report",
      "legacy_source_inventory",
      "market_context_report",
      "blocked_degraded_field_report",
      "attribution_ledger_report",
      "denominator_report",
      "ledger_hash_chain_report",
      "replay_report",
      "checkpoint_report",
      "resume_report",
      "calibration_report",
      "calibration_fixture_result",
      "promotion_noop_report",
      "release_manifest",
      "review_matrix",
      "gate_decision_report"
    ],
    "required_identity_fields": [
      "artifact_id",
      "artifact_type",
      "schema_version",
      "producer_tool",
      "producer_tool_version",
      "generated_at",
      "input_refs",
      "content_hash",
      "tool_config_hash",
      "review_refs"
    ],
    "artifact_entry_required_fields": [
      "phase",
      "artifact_id",
      "artifact_type",
      "schema_version",
      "producer_tool",
      "producer_tool_version",
      "generated_at",
      "content_hash",
      "tool_config_hash",
      "evidence_refs",
      "state"
    ],
    "self_report_can_pass": false,
    "grep_hit_can_pass": false
  },
  "native_full_pass_release_manifest": {
    "artifact_id": "rel_v4_7f42d2c91b4e6a1c8d03",
    "artifact_type": "release_manifest",
    "schema_version": "v4.evidence_gate.release_manifest.phase29.1",
    "producer_tool": "v4-evidence-gate-validator",
    "producer_tool_version": "sha256:1111111111111111111111111111111111111111111111111111111111111111",
    "generated_at": "2026-08-06T12:00:00+09:00",
    "freshness_window_hours": 24,
    "input_refs": [],
    "artifact_entries": [
      {"phase": "Phase 22", "artifact_id": "meas_v4_phase22_report", "artifact_type": "measurement_report", "schema_version": "v4.measurement.phase22.1", "producer_tool": "phase22-measurement-validator", "producer_tool_version": "sha256:1212121212121212121212121212121212121212121212121212121212121212", "generated_at": "2026-08-06T12:00:00+09:00", "content_hash": "sha256:2222222222222222222222222222222222222222222222222222222222222222", "tool_config_hash": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "evidence_refs": ["read_v4_phase29_fixture", "parser_v4_phase29_fixture"], "state": "pass"},
      {"phase": "Phase 22", "artifact_id": "meas_v4_phase22_fixture_result", "artifact_type": "measurement_fixture_result", "schema_version": "v4.measurement.fixture_result.phase22.1", "producer_tool": "phase22-measurement-fixture-validator", "producer_tool_version": "sha256:1313131313131313131313131313131313131313131313131313131313131313", "generated_at": "2026-08-06T12:00:00+09:00", "content_hash": "sha256:2323232323232323232323232323232323232323232323232323232323232323", "tool_config_hash": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "evidence_refs": ["mutation_v4_phase29_fixture"], "state": "pass"},
      {"phase": "Phase 23", "artifact_id": "snap_v4_phase23_manifest", "artifact_type": "snapshot_manifest", "schema_version": "v4.snapshot.phase23.1", "producer_tool": "phase23-snapshot-validator", "producer_tool_version": "sha256:1414141414141414141414141414141414141414141414141414141414141414", "generated_at": "2026-08-06T12:00:00+09:00", "content_hash": "sha256:3333333333333333333333333333333333333333333333333333333333333333", "tool_config_hash": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "evidence_refs": ["read_v4_phase29_fixture", "parser_v4_phase29_fixture"], "state": "pass"},
      {"phase": "Phase 23", "artifact_id": "snap_v4_phase23_schema_validation", "artifact_type": "snapshot_schema_validation", "schema_version": "v4.snapshot.schema_validation.phase23.1", "producer_tool": "phase23-snapshot-schema-validator", "producer_tool_version": "sha256:1515151515151515151515151515151515151515151515151515151515151515", "generated_at": "2026-08-06T12:00:00+09:00", "content_hash": "sha256:3434343434343434343434343434343434343434343434343434343434343434", "tool_config_hash": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "evidence_refs": ["parser_v4_phase29_fixture"], "state": "pass"},
      {"phase": "Phase 23", "artifact_id": "snap_v4_phase23_hash_report", "artifact_type": "snapshot_hash_report", "schema_version": "v4.snapshot.hash_report.phase23.1", "producer_tool": "phase23-snapshot-hash-validator", "producer_tool_version": "sha256:1616161616161616161616161616161616161616161616161616161616161616", "generated_at": "2026-08-06T12:00:00+09:00", "content_hash": "sha256:3535353535353535353535353535353535353535353535353535353535353535", "tool_config_hash": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "evidence_refs": ["parser_v4_phase29_fixture", "mutation_v4_phase29_fixture"], "state": "pass"},
      {"phase": "Phase 24", "artifact_id": "legacy_v4_phase24_coverage", "artifact_type": "legacy_coverage_report", "schema_version": "v4.legacy_backfill.coverage.phase24.1", "producer_tool": "phase24-legacy-coverage-validator", "producer_tool_version": "sha256:1717171717171717171717171717171717171717171717171717171717171717", "generated_at": "2026-08-06T12:00:00+09:00", "content_hash": "sha256:4444444444444444444444444444444444444444444444444444444444444444", "tool_config_hash": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "evidence_refs": ["parser_v4_phase29_fixture"], "state": "pass"},
      {"phase": "Phase 24", "artifact_id": "legacy_v4_phase24_invalid_report", "artifact_type": "invalid_legacy_report", "schema_version": "v4.legacy_backfill.invalid_report.phase24.1", "producer_tool": "phase24-invalid-legacy-validator", "producer_tool_version": "sha256:1818181818181818181818181818181818181818181818181818181818181818", "generated_at": "2026-08-06T12:00:00+09:00", "content_hash": "sha256:4545454545454545454545454545454545454545454545454545454545454545", "tool_config_hash": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "evidence_refs": ["parser_v4_phase29_fixture", "mutation_v4_phase29_fixture"], "state": "pass"},
      {"phase": "Phase 24", "artifact_id": "legacy_v4_phase24_source_inventory", "artifact_type": "legacy_source_inventory", "schema_version": "v4.legacy_backfill.source_inventory.phase24.1", "producer_tool": "phase24-legacy-source-inventory", "producer_tool_version": "sha256:1919191919191919191919191919191919191919191919191919191919191919", "generated_at": "2026-08-06T12:00:00+09:00", "content_hash": "sha256:4646464646464646464646464646464646464646464646464646464646464646", "tool_config_hash": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "evidence_refs": ["read_v4_phase29_fixture"], "state": "pass"},
      {"phase": "Phase 25", "artifact_id": "ctx_v4_phase25_report", "artifact_type": "market_context_report", "schema_version": "v4.market_context.phase25.1", "producer_tool": "phase25-market-context-validator", "producer_tool_version": "sha256:2020202020202020202020202020202020202020202020202020202020202020", "generated_at": "2026-08-06T12:00:00+09:00", "content_hash": "sha256:5555555555555555555555555555555555555555555555555555555555555555", "tool_config_hash": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "evidence_refs": ["parser_v4_phase29_fixture"], "state": "pass"},
      {"phase": "Phase 25", "artifact_id": "ctx_v4_phase25_blocked_degraded", "artifact_type": "blocked_degraded_field_report", "schema_version": "v4.market_context.blocked_degraded.phase25.1", "producer_tool": "phase25-blocked-degraded-validator", "producer_tool_version": "sha256:2121212121212121212121212121212121212121212121212121212121212121", "generated_at": "2026-08-06T12:00:00+09:00", "content_hash": "sha256:5656565656565656565656565656565656565656565656565656565656565656", "tool_config_hash": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "evidence_refs": ["mutation_v4_phase29_fixture"], "state": "pass"},
      {"phase": "Phase 26", "artifact_id": "att_v4_phase26_ledger", "artifact_type": "attribution_ledger_report", "schema_version": "v4.recommendation_attribution.phase26.1", "producer_tool": "phase26-attribution-validator", "producer_tool_version": "sha256:2424242424242424242424242424242424242424242424242424242424242424", "generated_at": "2026-08-06T12:00:00+09:00", "content_hash": "sha256:6666666666666666666666666666666666666666666666666666666666666666", "tool_config_hash": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "evidence_refs": ["parser_v4_phase29_fixture"], "state": "pass"},
      {"phase": "Phase 26", "artifact_id": "att_v4_phase26_denominator", "artifact_type": "denominator_report", "schema_version": "v4.recommendation_attribution.denominator.phase26.1", "producer_tool": "phase26-denominator-validator", "producer_tool_version": "sha256:2525252525252525252525252525252525252525252525252525252525252525", "generated_at": "2026-08-06T12:00:00+09:00", "content_hash": "sha256:6767676767676767676767676767676767676767676767676767676767676767", "tool_config_hash": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "evidence_refs": ["parser_v4_phase29_fixture"], "state": "pass"},
      {"phase": "Phase 26", "artifact_id": "att_v4_phase26_ledger_hash_chain", "artifact_type": "ledger_hash_chain_report", "schema_version": "v4.recommendation_attribution.ledger_hash_chain.phase26.1", "producer_tool": "phase26-ledger-hash-validator", "producer_tool_version": "sha256:2626262626262626262626262626262626262626262626262626262626262626", "generated_at": "2026-08-06T12:00:00+09:00", "content_hash": "sha256:6868686868686868686868686868686868686868686868686868686868686868", "tool_config_hash": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "evidence_refs": ["mutation_v4_phase29_fixture"], "state": "pass"},
      {"phase": "Phase 27", "artifact_id": "replay_v4_phase27_report", "artifact_type": "replay_report", "schema_version": "v4.full_workflow_replay.phase27.1", "producer_tool": "phase27-replay-validator", "producer_tool_version": "sha256:2727272727272727272727272727272727272727272727272727272727272727", "generated_at": "2026-08-06T12:00:00+09:00", "content_hash": "sha256:7777777777777777777777777777777777777777777777777777777777777777", "tool_config_hash": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "evidence_refs": ["parser_v4_phase29_fixture"], "state": "pass"},
      {"phase": "Phase 27", "artifact_id": "replay_v4_phase27_checkpoint", "artifact_type": "checkpoint_report", "schema_version": "v4.full_workflow_replay.checkpoint.phase27.1", "producer_tool": "phase27-checkpoint-validator", "producer_tool_version": "sha256:2828282828282828282828282828282828282828282828282828282828282828", "generated_at": "2026-08-06T12:00:00+09:00", "content_hash": "sha256:7878787878787878787878787878787878787878787878787878787878787878", "tool_config_hash": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "evidence_refs": ["resume_v4_phase29_fixture"], "state": "pass"},
      {"phase": "Phase 27", "artifact_id": "replay_v4_phase27_resume", "artifact_type": "resume_report", "schema_version": "v4.full_workflow_replay.resume.phase27.1", "producer_tool": "phase27-resume-validator", "producer_tool_version": "sha256:2929292929292929292929292929292929292929292929292929292929292929", "generated_at": "2026-08-06T12:00:00+09:00", "content_hash": "sha256:7979797979797979797979797979797979797979797979797979797979797979", "tool_config_hash": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "evidence_refs": ["resume_v4_phase29_fixture"], "state": "pass"},
      {"phase": "Phase 28", "artifact_id": "cal_v4_phase28_report", "artifact_type": "calibration_report", "schema_version": "v4.hold_confidence_calibration.phase28.1", "producer_tool": "phase28-calibration-validator", "producer_tool_version": "sha256:3030303030303030303030303030303030303030303030303030303030303030", "generated_at": "2026-08-06T12:00:00+09:00", "content_hash": "sha256:8888888888888888888888888888888888888888888888888888888888888888", "tool_config_hash": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "evidence_refs": ["parser_v4_phase29_fixture"], "state": "pass"},
      {"phase": "Phase 28", "artifact_id": "cal_v4_phase28_fixture_result", "artifact_type": "calibration_fixture_result", "schema_version": "v4.hold_confidence_calibration.fixture_result.phase28.1", "producer_tool": "phase28-calibration-fixture-validator", "producer_tool_version": "sha256:3131313131313131313131313131313131313131313131313131313131313131", "generated_at": "2026-08-06T12:00:00+09:00", "content_hash": "sha256:8989898989898989898989898989898989898989898989898989898989898989", "tool_config_hash": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "evidence_refs": ["mutation_v4_phase29_fixture"], "state": "pass"},
      {"phase": "Phase 28", "artifact_id": "cal_v4_phase28_promotion_noop", "artifact_type": "promotion_noop_report", "schema_version": "v4.hold_confidence_calibration.promotion_noop.phase28.1", "producer_tool": "phase28-promotion-noop-validator", "producer_tool_version": "sha256:3232323232323232323232323232323232323232323232323232323232323232", "generated_at": "2026-08-06T12:00:00+09:00", "content_hash": "sha256:9090909090909090909090909090909090909090909090909090909090909090", "tool_config_hash": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "evidence_refs": ["parser_v4_phase29_fixture"], "state": "pass"},
      {"phase": "Phase 29", "artifact_id": "rel_v4_7f42d2c91b4e6a1c8d03", "artifact_type": "release_manifest", "schema_version": "v4.evidence_gate.release_manifest.phase29.1", "producer_tool": "v4-evidence-gate-validator", "producer_tool_version": "sha256:1111111111111111111111111111111111111111111111111111111111111111", "generated_at": "2026-08-06T12:00:00+09:00", "content_hash": "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", "tool_config_hash": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "evidence_refs": ["read_v4_phase29_fixture", "parser_v4_phase29_fixture"], "state": "pass"},
      {"phase": "Phase 29", "artifact_id": "review_v4_phase29_matrix", "artifact_type": "review_matrix", "schema_version": "v4.evidence_gate.review_matrix.phase29.1", "producer_tool": "phase29-review-matrix-validator", "producer_tool_version": "sha256:3333333333333333333333333333333333333333333333333333333333333333", "generated_at": "2026-08-06T12:00:00+09:00", "content_hash": "sha256:9999999999999999999999999999999999999999999999999999999999999999", "tool_config_hash": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "evidence_refs": ["independent_v4_phase29_fixture"], "state": "pass"},
      {"phase": "Phase 29", "artifact_id": "gate_v4_phase29_decision", "artifact_type": "gate_decision_report", "schema_version": "v4.evidence_gate.decision_report.phase29.1", "producer_tool": "phase29-gate-decision-validator", "producer_tool_version": "sha256:3434343434343434343434343434343434343434343434343434343434343434", "generated_at": "2026-08-06T12:00:00+09:00", "content_hash": "sha256:9a9a9a9a9a9a9a9a9a9a9a9a9a9a9a9a9a9a9a9a9a9a9a9a9a9a9a9a9a9a9a9a", "tool_config_hash": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "evidence_refs": ["parser_v4_phase29_fixture", "independent_v4_phase29_fixture"], "state": "pass"}
    ],
    "manifest_summary": {
      "required_artifact_count": 22,
      "artifact_entry_count": 22,
      "all_artifact_entries_state": "pass",
      "missing_required_artifact_count": 0,
      "artifact_set_hash": "sha256:abababababababababababababababababababababababababababababababab"
    },
    "tool_config_hash": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "content_hash": "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    "review_refs": [
      {"lane": "manual_read", "artifact_id": "read_v4_phase29_fixture", "state": "pass"},
      {"lane": "deterministic_parser", "artifact_id": "parser_v4_phase29_fixture", "state": "pass"},
      {"lane": "fixture_mutation", "artifact_id": "mutation_v4_phase29_fixture", "state": "pass"},
      {"lane": "independent_review", "artifact_id": "independent_v4_phase29_fixture", "state": "pass"}
    ],
    "domain_states": {
      "measurement": "pass",
      "snapshot": "pass",
      "migration": "pass",
      "attribution": "pass",
      "replay": "pass",
      "calibration": "pass",
      "phase29_review": "pass"
    },
    "legacy_report": {
      "legacy_audit_only": true,
      "native_v4_eligible": false,
      "canonical_metric_eligible": false,
      "calibration_eligible": false,
      "invalid_reason": ["raw_prompt_unknown", "decision_data_cutoff_unknown", "candidate_universe_unknown", "portfolio_state_unknown"],
      "source_count": 82,
      "canonical_metric_eligible_count": 0
    },
    "gate_decision": {
      "state": "pass",
      "promotion_scope": "v4_only",
      "affected_versions": ["v4"],
      "unaffected_versions": ["v5", "v6", "v7", "v8", "v9"]
    }
  },
  "failure_fixtures": [
    {
      "fixture": "missing_migration_coverage",
      "mutation": "remove Phase 24 legacy_coverage_report artifact entry",
      "expected_state": "fail",
      "expected_reason": "missing_required_artifact:legacy_coverage_report",
      "closes": ["v4"],
      "must_not_affect": ["v5", "v6", "v7", "v8", "v9"]
    },
    {
      "fixture": "missing_calibration_report",
      "mutation": "remove Phase 28 calibration_report artifact entry",
      "expected_state": "fail",
      "expected_reason": "missing_required_artifact:calibration_report",
      "closes": ["v4"],
      "must_not_affect": ["v5", "v6", "v7", "v8", "v9"]
    },
    {
      "fixture": "mismatched_hashes",
      "mutation": "change Phase 23 snapshot content_hash without changing artifact body",
      "expected_state": "fail",
      "expected_reason": "content_hash_mismatch",
      "closes": ["v4"],
      "must_not_affect": ["v5", "v6", "v7", "v8", "v9"]
    },
    {
      "fixture": "stale_evidence",
      "mutation": "set generated_at outside freshness_window_hours",
      "expected_state": "fail",
      "expected_reason": "stale_evidence",
      "closes": ["v4"],
      "must_not_affect": ["v5", "v6", "v7", "v8", "v9"]
    },
    {
      "fixture": "unverifiable_legacy",
      "mutation": "set legacy native_v4_eligible true while raw_prompt and data_cutoff are unknown",
      "expected_state": "fail",
      "expected_reason": "legacy_promoted_to_native",
      "closes": ["v4"],
      "must_not_affect": ["v5", "v6", "v7", "v8", "v9"]
    },
    {
      "fixture": "interrupted_with_valid_checkpoint",
      "mutation": "cancel verification after parser with checkpoint_report present but before resume_report and independent_review complete",
      "expected_state": "inconclusive",
      "expected_reason": "verification_interrupted_resume_required",
      "closes": ["v4"],
      "must_not_affect": ["v5", "v6", "v7", "v8", "v9"]
    },
    {
      "fixture": "repeated_interruption_bad_resume",
      "mutation": "resume twice after cancellation and skip fixture_mutation evidence",
      "expected_state": "fail",
      "expected_reason": "repeated_interruption_skipped_required_probe",
      "closes": ["v4"],
      "must_not_affect": ["v5", "v6", "v7", "v8", "v9"]
    }
  ]
}
```

## Manual Read and deterministic parser requirements

Task 8 and downstream implementation must use both surfaces below before any DoneClaim.

1. Manual Read must read this PRD and the release manifest artifact body. It must record observed section coverage for artifact identity, Phase table, review matrix, fixture matrix, v4-only scope, and legacy invalid marking.
2. Deterministic parser must parse every JSON fixture in this PRD, derive required artifact types from the `Required artifacts by Phase` table, assert exact set equality against `native_full_pass_release_manifest.artifact_entries`, assert each phase's artifact set is a subset of that phase's entries, validate every artifact entry's identity, hash, schema, tool, generated timestamp, evidence refs, and `state="pass"`, and run in-memory fixture mutations.
3. Parser success alone cannot pass the gate. It must be paired with Manual Read and independent review.
4. Grep success alone cannot pass the gate. A search hit for a required phrase is not completion evidence.
5. Worker self-report cannot pass the gate. A DoneClaim can summarize evidence but cannot replace artifacts.

## Acceptance criteria

1. The PRD defines v4-only completion evidence for measurement, snapshot, migration, attribution, replay, and calibration.
2. Phase 22 through Phase 29 required artifacts, pass/fail/inconclusive states, artifact identity, schema, hash, and tool version requirements are explicit.
3. Invalid legacy reports are marked audit-only, not native, not canonical metric eligible, and not calibration eligible.
4. Native full-pass release manifest fixture and failures for missing migration coverage, missing calibration report, mismatched hashes, stale evidence, and unverifiable legacy are present as parseable JSON.
5. Each failure fixture closes only v4 and explicitly leaves v5 through v9 unaffected.
6. Independent review, Manual Read, deterministic parser, fixture mutation, interrupted verification, resume, and repeated interruption behavior are part of the gate.
7. Worker self-report and grep hit cannot pass.
8. v5 through v9 document or completion status is outside this gate and never affected.
