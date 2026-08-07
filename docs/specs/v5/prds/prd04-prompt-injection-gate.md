# PRD 04: Prompt Injection Gate
> **상태**: ✅ 완료
> **SPEC 참조**: [../SPEC.md](../SPEC.md)

## Problem

PRD 01 gives causal graph nodes stable identities. PRD 02 approves or rejects each node to series mapping. PRD 03 decides whether a mapped pair has stable statistical lead evidence. The macro perspective still needs a final gate before those results enter an LLM prompt.

The gate must keep verified, inconclusive, and rejected triples separate. A verified section can contain only fresh `verified_stable` results from the current schema. Inconclusive and rejected evidence can be retained for audit or debugging, but it must never appear under a verified label.

## Scope

This PRD covers:

1. Prompt injection schema version `causal-prompt-injection.1`.
2. Eligibility for verified, inconclusive, and rejected triple records.
3. Freshness, confidence, token budget, provenance, expiry, and rollback rules.
4. Deterministic prompt ordering and stable injection.
5. Exclusion of expired, malformed, stale, rejected, and budget overflow records.
6. Audit fixtures for stable inject and expired exclude.
7. Mutation records for prompt injection, stale exclusion, malformed exclusion, and budget exclusion.

This PRD excludes:

1. Node canonicalization rules owned by PRD 01.
2. Series mapping provenance rules owned by PRD 02.
3. Statistical verification rules owned by PRD 03.
4. Recommendation attribution.
5. Any claim that Granger output proves true causality.

## Exact Evidence From The Current Codebase

| Evidence | Exact observation | Contract impact |
| --- | --- | --- |
| `docs/specs/v5/prds/prd01-node-canonicalization.md:25` to `:28` | PRD 01 excludes statistical verification, prompt injection, series mapping provenance, and recommendation attribution. | PRD 04 owns only prompt injection after upstream artifacts exist. |
| `docs/specs/v5/prds/prd02-series-mapping-provenance.md:20` to `:24` | PRD 02 excludes Granger p value, lag, Bonferroni, confidence policy, and prompt injection ordering. | PRD 04 can require approved mapping provenance, but it does not redefine mapping approval. |
| `docs/specs/v5/prds/prd03-statistical-verification.md:23` to `:29` | PRD 03 excludes prompt injection eligibility and says Granger output must not be true causality. | PRD 04 owns injection eligibility and must keep the label as statistical evidence. |
| `docs/specs/v5/prds/prd03-statistical-verification.md:51` to `:64` | PRD 03 inputs require canonical graph, mapping artifact, non expired approved mappings, raw series cutoff, and verification config. | Prompt injection must consume only results that preserve those upstream hashes and cutoffs. |
| `docs/specs/v5/prds/prd03-statistical-verification.md:168` to `:197` | PRD 03 output is `causal-statistical-verification.1` with metadata, pair results, mutations, and QA checks. | Prompt injection input must require this schema version and read pair results, not legacy buckets. |
| `docs/specs/v5/prds/prd03-statistical-verification.md:250` to `:263` | PRD 03 field rules define statuses, `claim_label = statistical_lead_evidence`, integer lag, decimal strings, and boolean direction match. | Prompt records must reject type drift and must not relabel claims as causality. |
| `docs/specs/v5/prds/prd03-statistical-verification.md:264` to `:283` | PRD 03 terminal statuses are `verified_stable`, all `rejected_*` values, and `inconclusive`. | Prompt eligibility must treat these three classes separately. |
| `src/perspectives/macro.py:155` to `:188` | Current macro prompt adds a verified Granger section from `get_verified_chains(keywords, min_confidence=0.5)`. | The new gate must control that verified section before prompt text is built. |
| `src/perspectives/macro.py:192` to `:197` | Current macro prompt adds an unverified causal graph reference section. | Unverified background may exist only under a separate non verified label. |
| `src/causal/verifier.py:282` to `:299` | `get_verified_chains` reads legacy `verified_triples`, checks only confidence, and searches keyword text. | Eligibility must add schema, freshness, provenance, status, type, and budget gates. |
| `data/causal_graph_verified.json:1` to `:10` | Existing metadata has total, mappable, verified, failed, unmappable, alpha, corrected alpha, and verified timestamp. | The gate needs generated timestamp, expiry, and rollback metadata in a new artifact. |
| `data/causal_graph_verified.json:19` to `:28` | Existing verified records can store `status`, p value, lag, f statistic, direction match, confidence, and series pair. | The gate must preserve evidence fields while rejecting stale or malformed legacy types. |
| `data/causal_graph_verified.json:21` and `:23` | Existing `lag` and `direction_match` can appear as strings. | String lag or string direction match cannot enter the new verified prompt section. |

## Inputs

The prompt injection gate consumes PRD 03 output and emits a prompt ready evidence package for the macro perspective.

| Input | Required rule |
| --- | --- |
| Statistical verification artifact | `schema_version` must be `causal-statistical-verification.1`. |
| Pair result | Must include PRD 03 `pair_id`, node IDs, relation, `verification_status`, `claim_label`, selected lag, train evidence, holdout evidence, stationarity, multiple testing, and stability. |
| Mapping provenance | Must be reachable through PRD 03 mapping hashes and must not be expired at the prompt cutoff. |
| Prompt config | Must declare token budget, minimum confidence, freshness window, ordering policy, and verified section label. |
| Rollback pointer | Must point to the last accepted prompt package hash when a new package is rejected after assembly. |

Legacy `verified_triples` can seed rejection fixtures only. They are not eligible for verified injection under this schema.

## Output Schema

The gate writes a versioned prompt package. It does not overwrite PRD 01, PRD 02, or PRD 03 artifacts.

```json
{
  "schema_version": "causal-prompt-injection.1",
  "source_verification_schema_version": "causal-statistical-verification.1",
  "prompt_policy_version": "prompt-injection-gate.1",
  "generated_at": "2026-08-06T00:00:00+09:00",
  "prompt_cutoff": "2026-08-06T00:00:00+09:00",
  "expires_at": "2026-08-07T00:00:00+09:00",
  "source_artifact_hash": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "package_hash": "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
  "rollback_to_package_hash": "sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
  "budget": {
    "max_tokens": 900,
    "reserved_tokens": 120,
    "used_tokens": 214,
    "overflow_count": 0
  },
  "verified_prompt_records": [],
  "excluded_prompt_records": [],
  "prompt_mutations": [],
  "qa": {
    "read_checks": [],
    "json_checks": [],
    "mutation_checks": []
  }
}
```

## Verified Prompt Record

Only verified prompt records may be rendered inside the verified causal evidence section.

```json
{
  "pair_id": "statpair_fa52b889d05d6dbf97ab",
  "prompt_record_id": "promptrec_2af7c8b7135131b2e450",
  "eligibility": "verified_prompt_eligible",
  "claim_label": "statistical_lead_evidence",
  "render_label": "데이터 검증됨, 통계적 선행 근거",
  "subject_node_id": "cnode_0b6a943c2860b6e61893",
  "object_node_id": "cnode_96b23578f19cae76707f",
  "relation": "increases",
  "selected_lag": 5,
  "confidence": "0.910000",
  "freshness": {
    "verification_generated_at": "2026-08-06T00:00:00+09:00",
    "verification_expires_at": "2026-08-07T00:00:00+09:00",
    "mapping_expires_at": "2026-09-05T00:00:00+09:00",
    "is_fresh": true
  },
  "provenance": {
    "source_artifact_hash": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "run_config_hash": "sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
    "correction_scope_hash": "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    "subject_mapping_hash": "sha256:1111111111111111111111111111111111111111111111111111111111111111",
    "object_mapping_hash": "sha256:2222222222222222222222222222222222222222222222222222222222222222"
  },
  "evidence": {
    "train_p_value": "0.000400",
    "holdout_p_value": "0.000600",
    "corrected_alpha": "0.000833333333",
    "direction_match_train": true,
    "direction_match_holdout": true,
    "stability": "pass"
  },
  "token_estimate": 43,
  "render_text": "원달러 환율 상승 increases 수출기업 마진 개선, lag 5일, train p=0.000400, holdout p=0.000600, confidence=0.910000"
}
```

Field rules:

| Field | Required | Rule |
| --- | --- | --- |
| `prompt_record_id` | yes | Deterministic ID from schema version, pair ID, prompt cutoff, source artifact hash, and render text. |
| `eligibility` | yes | Must be `verified_prompt_eligible` for records in `verified_prompt_records`. |
| `claim_label` | yes | Must remain `statistical_lead_evidence`. |
| `render_label` | yes | Must not say true causality or guaranteed causality. |
| `confidence` | yes | Decimal string with six places. It must meet `minimum_confidence`. |
| `freshness.is_fresh` | yes | Must be true at prompt cutoff. |
| `provenance` | yes | Must include source artifact, run config, correction scope, and both mapping hashes. |
| `token_estimate` | yes | Positive integer used before render ordering. |
| `render_text` | yes | Built only from verified evidence fields. It must not add explanation from inconclusive or rejected records. |

## Triple Prompt Eligibility

Verified, inconclusive, and rejected triples have different prompt rights.

| Triple class | Eligibility | Prompt section | Required handling |
| --- | --- | --- | --- |
| Verified | `verification_status = verified_stable`, `claim_label = statistical_lead_evidence`, fresh source, confidence above threshold, valid provenance, valid JSON types, and within token budget. | Verified causal evidence only. | Render with lag, train p value, holdout p value, confidence, and provenance hash reference. |
| Inconclusive | `verification_status = inconclusive`. | Not eligible for verified causal evidence. | Exclude from verified prompt. Keep audit record with reason. |
| Rejected | Any terminal `rejected_*` status. | Not eligible for verified causal evidence. | Exclude from verified prompt. Keep audit record with rejection reason. |

The gate must never combine rejected or inconclusive evidence into a verified sentence. If a verified pair and an inconclusive pair share a node or series, only the verified pair may render, and its text must name only its own pair ID and evidence.

## Freshness And Expiry Rules

Freshness is checked before confidence and budget. A stale record cannot reserve prompt tokens.

Rules:

1. `prompt_cutoff` must be at or before package `expires_at`.
2. PRD 03 `generated_at` and `verification_cutoff` must not be after `prompt_cutoff`.
3. PRD 03 verification `generated_at` must be within the configured freshness window.
4. Every referenced mapping approval and source catalog expiry from PRD 02 must be after `prompt_cutoff`.
5. A record with missing expiry becomes `excluded_malformed`, not verified.
6. A record with an expired verification or mapping becomes `excluded_stale`.
7. A package generated from a stale source artifact must not replace the last accepted package.

## Confidence Rules

Confidence is a prompt prioritization signal, not proof of causality.

Rules:

1. `minimum_confidence` defaults to `0.500000` unless prompt config chooses a stricter value before assembly.
2. Confidence must be a decimal string with six places.
3. Confidence below threshold becomes `excluded_low_confidence`.
4. Confidence cannot override stale, malformed, rejected, inconclusive, leakage, p hacking, or flaky evidence.
5. The prompt must display confidence as evidence weight, not as certainty.

## Token Budget And Ordering

Budget ordering is deterministic and runs after malformed, stale, status, and confidence gates.

Budget order:

| Order | Sort key | Direction | Reason |
| --- | --- | --- | --- |
| 1 | `freshness.verification_generated_at` | newest first | Prefer fresher statistical evidence. |
| 2 | `confidence` | highest first | Prefer stronger verified evidence after freshness passes. |
| 3 | `holdout_p_value` | lowest first | Prefer stronger unseen sample evidence. |
| 4 | `selected_lag` | lowest first | Prefer shorter lead time when evidence is otherwise tied. |
| 5 | `pair_id` | ascending | Stable tie breaker. |

Budget rules:

1. `reserved_tokens` is kept for section heading, provenance note, and fallback text.
2. A record is accepted only when `used_tokens + token_estimate <= max_tokens - reserved_tokens`.
3. Overflow records become `excluded_budget_overflow` with their rank and token estimate.
4. Changing ordering after inspecting prompt quality is a mutation and must reject the package.
5. Running the same input, config, and cutoff must produce the same accepted record order and package hash.

## Provenance And Rollback

Every prompt package must be auditable back to the verification artifact and upstream mapping hashes.

Rules:

1. `source_artifact_hash` is a hash of the complete PRD 03 artifact consumed by the gate.
2. `package_hash` is a hash of the canonical prompt package after exclusions and ordering.
3. Each rendered record stores `pair_id`, `run_config_hash`, `correction_scope_hash`, subject mapping hash, and object mapping hash.
4. Every pair `input_fingerprint`, run config, correction scope, split policy, window policy, and verification cutoff must equal the PRD 03 root values.
5. `rollback_to_package_hash` is required when a prior accepted package exists.
6. If assembly fails after any record is accepted, the caller must keep the prior package and append `rollback_package` mutation.
7. Rollback rechecks package expiry, evidence expiry, and verification freshness at the rollback `generated_at`; it never extends the prior expiry.
8. Rollback cannot resurrect expired records. It can only restore the last package that was valid at its own cutoff.

## Decision Table

| Case | Input status | Fresh | Confidence | JSON shape | Budget | Decision | Prompt effect |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Stable inject | `verified_stable` | yes | pass | valid | fits | `inject_verified` | Appears in verified causal evidence. |
| Expired exclude | `verified_stable` | no | pass | valid | fits | `exclude_stale` | Does not appear in prompt. |
| Inconclusive exclude | `inconclusive` | yes | not checked | valid | not checked | `exclude_inconclusive` | Does not appear in verified section. |
| Rejected exclude | `rejected_in_sample_only` | yes | not checked | valid | not checked | `exclude_rejected` | Does not appear in verified section. |
| Malformed exclude | `verified_stable` | yes | pass | invalid | not checked | `exclude_malformed` | Does not appear in prompt. |
| Budget exclude | `verified_stable` | yes | pass | valid | overflow | `exclude_budget_overflow` | Does not appear in prompt, but audit stores rank. |
| Low confidence exclude | `verified_stable` | yes | fail | valid | not checked | `exclude_low_confidence` | Does not appear in prompt. |

## Prompt Mutations

Prompt gate changes are append only and local to the prompt package.

Allowed mutations:

| Mutation | Required result |
| --- | --- |
| `inject_verified` | A fresh verified stable pair is added to the verified prompt records. |
| `exclude_stale` | Expired verification, mapping, or package source is excluded before budget. |
| `exclude_inconclusive` | Inconclusive pair is excluded from verified prompt records. |
| `exclude_rejected` | Rejected pair is excluded from verified prompt records. |
| `exclude_malformed` | Schema, type, missing field, or invalid claim label is excluded. |
| `exclude_budget_overflow` | Eligible pair is excluded because it does not fit the token budget. |
| `rollback_package` | New package is rejected and the caller keeps the previous accepted package. |

Mutation shape:

```json
{
  "mutation": "exclude_stale",
  "pair_id": "statpair_fa52b889d05d6dbf97ab",
  "from_status": "verified_stable",
  "to_eligibility": "excluded_stale",
  "reason": "mapping_approval_expired_before_prompt_cutoff",
  "evidence": {
    "mapping_expires_at": "2026-08-05T00:00:00+09:00",
    "prompt_cutoff": "2026-08-06T00:00:00+09:00",
    "subject_mapping_hash": "sha256:1111111111111111111111111111111111111111111111111111111111111111"
  },
  "mutated_at": "2026-08-06T00:00:00+09:00",
  "mutated_by": "prompt-injection-gate.1"
}
```

## Audit Fixture

### F1 Stable Inject

Input pair result:

```json
{
  "pair_id": "statpair_fa52b889d05d6dbf97ab",
  "verification_status": "verified_stable",
  "claim_label": "statistical_lead_evidence",
  "selected_lag": 5,
  "confidence": "0.910000",
  "holdout": {
    "p_value": "0.000600",
    "direction_match": true,
    "rows": 120
  },
  "freshness": {
    "verification_expires_at": "2026-08-07T00:00:00+09:00",
    "mapping_expires_at": "2026-09-05T00:00:00+09:00"
  },
  "token_estimate": 43
}
```

Expected prompt package record:

```json
{
  "eligibility": "verified_prompt_eligible",
  "mutation": "inject_verified",
  "pair_id": "statpair_fa52b889d05d6dbf97ab",
  "render_label": "데이터 검증됨, 통계적 선행 근거"
}
```

### F2 Expired Exclude

Input pair result:

```json
{
  "pair_id": "statpair_33dfc3fb94c33f122e60",
  "verification_status": "verified_stable",
  "claim_label": "statistical_lead_evidence",
  "confidence": "0.920000",
  "freshness": {
    "verification_expires_at": "2026-08-05T00:00:00+09:00",
    "mapping_expires_at": "2026-09-05T00:00:00+09:00"
  },
  "prompt_cutoff": "2026-08-06T00:00:00+09:00"
}
```

Expected exclusion:

```json
{
  "eligibility": "excluded_stale",
  "mutation": "exclude_stale",
  "pair_id": "statpair_33dfc3fb94c33f122e60",
  "reason": "verification_expired_before_prompt_cutoff"
}
```

### F3 Prompt Injection Exclusion

```json
{
  "pair_id": "statpair_aa0b2fdab5a7a78f139e",
  "verification_status": "verified_stable",
  "claim_label": "true_causality",
  "expected_decision": "exclude_malformed",
  "reason": "claim_label_must_be_statistical_lead_evidence"
}
```

### F4 Stale Mutation

```json
{
  "mutation": "exclude_stale",
  "pair_id": "statpair_33dfc3fb94c33f122e60",
  "evidence": {
    "verification_expires_at": "2026-08-05T00:00:00+09:00",
    "prompt_cutoff": "2026-08-06T00:00:00+09:00"
  }
}
```

### F5 Malformed Mutation

```json
{
  "mutation": "exclude_malformed",
  "pair_id": "statpair_legacy_string_lag",
  "json_pointer": "/pair_results/0/selected_lag",
  "parse_error": "selected_lag must be an integer"
}
```

### F6 Budget Mutation

```json
{
  "mutation": "exclude_budget_overflow",
  "pair_id": "statpair_overflow_0000000001",
  "rank": 6,
  "token_estimate": 58,
  "used_tokens_before_record": 762,
  "max_tokens": 900,
  "reserved_tokens": 120
}
```

## Read, JSON, And Mutation QA

| QA area | Fixture | Required result |
| --- | --- | --- |
| Read QA | PRD 03 artifact has `schema_version = causal-statistical-verification.1`. | Gate reads `pair_results` and ignores legacy `verified_triples`. |
| Read QA | Verification or mapping expiry is before prompt cutoff. | Record is excluded as stale before confidence and budget. |
| Read QA | Last accepted package hash exists and new package assembly fails. | Caller keeps rollback package and records rollback mutation. |
| JSON QA | `selected_lag` is a string. | Record is excluded as malformed. |
| JSON QA | `direction_match` is a string. | Record is excluded as malformed. |
| JSON QA | `claim_label` is `true_causality`. | Record is excluded as malformed. |
| Mutation QA | Fresh verified stable pair fits budget. | `inject_verified` mutation is appended. |
| Mutation QA | Expired verified stable pair is present. | `exclude_stale` mutation is appended. |
| Mutation QA | Rejected or inconclusive pair is present. | Exclusion mutation is appended and no verified render text is produced. |
| Mutation QA | Eligible pair overflows budget. | `exclude_budget_overflow` mutation is appended with rank and token evidence. |

## Acceptance Criteria

1. The PRD defines `causal-prompt-injection.1`.
2. Only fresh `verified_stable` results with `claim_label = statistical_lead_evidence` can enter the verified prompt section.
3. `inconclusive` and `rejected_*` records are never mixed into verified prompt evidence.
4. Freshness, confidence, token budget, provenance, expiry, and rollback are explicit.
5. Decision table covers stable inject, expired exclude, inconclusive exclude, rejected exclude, malformed exclude, budget exclude, and low confidence exclude.
6. Budget ordering is deterministic and produces stable injection for equal inputs.
7. Audit fixtures cover stable inject and expired exclude.
8. Mutation QA covers prompt injection, stale exclusion, malformed exclusion, and budget exclusion.
9. The prompt label describes statistical lead evidence, never true causality.

## 구현 및 실행

- strict source, package, record, budget, and rollback models: `src/causal/prompt_injection_models.py`
- eligibility, ordering, budget, provenance, and rollback gate: `src/causal/prompt_injection_gate.py`
- deterministic record construction: `src/causal/prompt_injection_records.py`
- package/source hash verified runtime reader: `src/causal/prompt_injection_runtime.py`
- executable acceptance checks: `src/causal/prompt_injection_acceptance.py`
- macro prompt integration: `src/perspectives/macro.py`, `src/perspectives/macro_prompt.py`
- immutable package CLI: `scripts/build_causal_prompt.py`

```bash
uv run scripts/build_causal_prompt.py verify-fixture
uv run scripts/build_causal_prompt.py build \
  --source data/causal_statistical_verification.json \
  --config data/causal_prompt_config.json \
  --output data/causal_prompt_injection.json
```

Runtime은 package와 원본 PRD 03 artifact hash를 함께 검증한다. 누락·변조·만료 시 verified record를 반환하지 않으며 legacy `verified_triples`로 fallback하지 않는다.
