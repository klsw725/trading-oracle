# PRD 03: Statistical Verification
> **상태**: ✅ 완료
> **SPEC 참조**: [../SPEC.md](../SPEC.md)

## Problem

PRD 01 gives each causal graph node a stable canonical identity. PRD 02 gives each node an approved quantitative series mapping. The next contract must decide whether an approved mapped pair has enough statistical evidence to be called a stable predictive relationship.

This document defines that decision boundary. A Granger result can support a statistical lead relationship, but it must not be described as true causality. A pair can pass only when the same direction survives stationarity handling, lag search, multiple testing correction, train and holdout split, structural break checks, and out of sample stability gates.

## Scope

This PRD covers:

1. Statistical verification schema version `causal-statistical-verification.1`.
2. Stationarity checks and deterministic transforms.
3. Lag search and corrected alpha policy.
4. Direction consistency from mapped series and relation sign.
5. Train and holdout split with leakage prevention.
6. Structural break checks and out of sample stability.
7. Verification state machine with `inconclusive` as a first class result.
8. Reproducible fixtures for stable pass and in sample only failure.

This PRD excludes:

1. Node canonicalization rules owned by PRD 01.
2. Series mapping provenance and manual approval rules owned by PRD 02.
3. Prompt injection eligibility.
4. Recommendation attribution.
5. Claims that Granger output proves true causality.

## Exact Evidence From The Current Codebase

| Evidence | Exact observation | Contract impact |
| --- | --- | --- |
| `docs/specs/v5/prds/prd01-node-canonicalization.md:25` to `:28` | PRD 01 excludes statistical verification, Granger test, p value, lag, prompt injection, and series mapping provenance. | PRD 03 owns statistical verification only after canonical nodes exist. |
| `docs/specs/v5/prds/prd02-series-mapping-provenance.md:20` to `:24` | PRD 02 excludes Granger p value, lag, Bonferroni, confidence policy, and prompt injection ordering. | PRD 03 owns p value, lag, correction, confidence, and stability policy. |
| `docs/specs/v5/prds/prd02-series-mapping-provenance.md:45` to `:60` | PRD 02 input requires `schema_version = causal-node-canonicalization.1` and `canonical_node_id`. | PRD 03 consumes approved mappings by canonical node ID, not legacy text. |
| `docs/specs/v5/prds/prd02-series-mapping-provenance.md:175` to `:194` | Approved mappings require transform, unit, direction, source, as_of, provenance hash, suitability, manual approval, and expiry. | PRD 03 can test only non expired approved mapping links. |
| `src/causal/verifier.py:59` to `:73` | Current stationarity handling runs ADF and applies up to two differences. | PRD 03 must make stationarity decisions explicit and reproducible. |
| `src/causal/verifier.py:76` to `:121` | Current pair test searches lag 1 through actual max lag and chooses the minimum p value. | PRD 03 must control lag search so p hacking is rejected. |
| `src/causal/verifier.py:157` to `:168` | Current correction uses `alpha = 0.05` and `corrected_alpha = alpha / max(mappable_count, 1)`. | PRD 03 keeps corrected alpha as a required output field. |
| `src/causal/verifier.py:199` to `:207` | Current direction check compares relation text with raw series correlation sign. | PRD 03 must define direction using approved mapping direction and relation sign. |
| `src/causal/verifier.py:211` to `:238` | Current output separates verified and failed by corrected alpha plus direction match. | PRD 03 must add holdout, break, stability, and inconclusive outcomes before promotion. |
| `src/causal/verifier.py:240` to `:253` | Current verified artifact has metadata plus `verified_triples`, `failed_triples`, and `unmappable_triples`. | PRD 03 output must be a new versioned artifact, not a silent reuse of legacy buckets. |
| `data/causal_graph_verified.json:1` to `:10` | Existing metadata records total triples, mappable count, verified count, failed count, unmappable count, alpha, corrected alpha, and verified timestamp. | PRD 03 keeps run level counts, alpha, corrected alpha, and generated timestamp. |
| `data/causal_graph_verified.json:19` to `:28` | Existing verified item stores status, p value, lag, f statistic, direction match, confidence, and series pair. | PRD 03 keeps those fields but fixes type and split specific evidence. |
| `data/causal_graph_verified.json:21` and `:23` | Existing `lag` and `direction_match` can appear as strings in stored data. | PRD 03 requires integer lag and boolean direction match in the new schema. |
| `docs/specs/v2/SPEC.md:594` to `:596` | The legacy spec says Granger is predictive contribution, not true causality, and notes non stationarity plus structural breaks. | PRD 03 must label results as statistical lead evidence and must test stability. |
| `기존 v2 인과 검증 문서` | The legacy causal verification document listed ADF, Granger, max lag 30, minimum p value lag, direction match, and Bonferroni correction. | PRD 03 preserves these as explicit contract pieces and adds leakage and holdout gates. |

## Inputs

Statistical verification consumes PRD 01 and PRD 02 artifacts.

| Input | Required rule |
| --- | --- |
| Canonical graph | `schema_version` must be `causal-node-canonicalization.1`. |
| Mapping artifact | `schema_version` must be `causal-series-mapping.1`. |
| Mapping record | Both endpoints must have non expired `approved_manual` mappings. |
| Series link | `series_id`, `transform`, `unit`, `direction`, `source_id`, `as_of`, `provenance_hash`, and `manual_approval.expires_at` are required. |
| Raw series frame | It must include only observations at or before the verification cutoff. |
| Verification config | It must include alpha, max lag, train window, holdout window, embargo sessions, break windows, and random free split rule. |

Pairs with missing, stale, proxy, dirty, misleading, or malformed mappings are not tested. They receive `verification_status = "inconclusive"` or a rejected status with evidence from PRD 02.

## Statistical Terms

### Stationarity

Stationarity means the tested transformed series has stable mean and variance enough for the selected Granger test contract. The verifier runs ADF on the exact training slice for each endpoint after the PRD 02 transform is applied.

Rules:

1. Run ADF on the train slice before any holdout result is inspected.
2. If ADF p value is below `stationarity_alpha`, keep the transformed series as is.
3. If not stationary, apply one difference and rerun ADF.
4. If still not stationary, apply two differences and rerun ADF.
5. If no allowed transform reaches stationarity, return `verification_status = "inconclusive"` with reason `non_stationary_after_max_diff`.
6. The selected differencing order is locked before lag search and reused on holdout.

Stationarity output shape:

```json
{
  "stationarity": {
    "subject_diff_order": 1,
    "object_diff_order": 1,
    "subject_adf_p_value": "0.018400",
    "object_adf_p_value": "0.021700",
    "stationarity_alpha": "0.050000"
  }
}
```

### Lag Search

Lag search is a predeclared grid, not a free choice after seeing outcomes.

Rules:

1. `lag_grid` defaults to integer days 1 through 30.
2. The actual grid is capped by available train observations so every lag has at least `min_train_rows_after_lag` rows.
3. Select `candidate_lag` from train only by minimum corrected eligible p value.
4. Store the full train lag table so the selected lag is auditable.
5. Test only the selected lag on holdout.
6. Changing max lag after looking at results is a `p_hacking` mutation and must reject the run.

### Direction Consistency

Direction uses PRD 02 mapping direction plus edge relation.

Rules:

1. Convert each endpoint into a signed movement series using `series_links[].direction`.
2. Relation `increases`, `causes`, and `enables` expects positive signed association unless the relation has a reviewed non directional policy.
3. Relation `decreases` and `blocks` expects negative signed association.
4. Direction is measured separately on train and holdout.
5. A train pass with holdout direction mismatch cannot become verified stable.

### Multiple Testing Correction

The run alpha is `0.05` unless a config explicitly chooses a stricter value before execution.

Corrected alpha:

```text
corrected_alpha = alpha / number_of_tested_hypotheses
```

`number_of_tested_hypotheses` is the count of eligible pair and lag hypotheses inspected on train. It is not the count of pairs that later look promising.

Required fields:

| Field | Rule |
| --- | --- |
| `alpha` | Decimal string with six places. |
| `tested_hypotheses` | Positive integer. |
| `corrected_alpha` | Decimal string with twelve places. |
| `correction_method` | `bonferroni` for this schema version. |
| `correction_scope_hash` | Hash of the sorted eligible pair IDs and lag grid. |

### Train And Holdout

Train chooses stationarity transform and lag. Holdout decides whether the train finding survives unseen data.

Rules:

1. Split chronologically by timestamp.
2. The default split is 70 percent train, 10 percent embargo, 20 percent holdout, after row alignment and missing value removal.
3. No holdout row may affect stationarity, lag choice, corrected alpha scope, or direction policy.
4. A pair that passes train but fails holdout becomes `rejected_in_sample_only`.
5. A pair with too few holdout rows becomes `inconclusive`, not verified.
6. Duplicate timestamps across train and holdout are rejected as leakage.

### Structural Breaks And Out Of Sample Stability

Structural break means a material change in mean, variance, or relation sign across predeclared windows.

Rules:

1. Run break checks after stationarity transform is locked.
2. Use predeclared break windows from the config, such as market shock windows or equal rolling windows.
3. A pair passes stability only when train sign, holdout sign, and rolling window signs agree with the relation policy.
4. If any window lacks enough rows, mark that window inconclusive and exclude it from pass counts.
5. If more than `max_inconclusive_windows` are inconclusive, the pair result is `inconclusive`.
6. If any eligible window reverses sign, reject with reason `structural_break_direction_reversal`.

## Output Schema

The verifier writes a versioned artifact. It does not overwrite PRD 01 or PRD 02 artifacts.

```json
{
  "schema_version": "causal-statistical-verification.1",
  "source_node_schema_version": "causal-node-canonicalization.1",
  "source_mapping_schema_version": "causal-series-mapping.1",
  "verification_policy_version": "statistical-verifier.1",
  "generated_at": "2026-08-06T00:00:00+09:00",
  "run_config_hash": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "metadata": {
    "alpha": "0.050000",
    "tested_hypotheses": 60,
    "corrected_alpha": "0.000833333333",
    "correction_method": "bonferroni",
    "eligible_pairs": 2,
    "verified_stable": 1,
    "rejected": 1,
    "inconclusive": 0
  },
  "pair_results": [],
  "verification_mutations": [],
  "qa": {
    "read_checks": [],
    "json_checks": [],
    "mutation_checks": []
  }
}
```

Pair result shape:

```json
{
  "pair_id": "statpair_fa52b889d05d6dbf97ab",
  "subject_node_id": "cnode_0b6a943c2860b6e61893",
  "object_node_id": "cnode_96b23578f19cae76707f",
  "relation": "increases",
  "subject_series_id": "USD_KRW",
  "object_series_id": "KOSPI",
  "verification_status": "verified_stable",
  "method": "granger_predictive_lead",
  "claim_label": "statistical_lead_evidence",
  "selected_lag": 5,
  "train": {
    "p_value": "0.000400",
    "f_stat": "12.8400",
    "direction_match": true,
    "rows": 420
  },
  "holdout": {
    "p_value": "0.000600",
    "f_stat": "9.2100",
    "direction_match": true,
    "rows": 120
  },
  "stationarity": {
    "subject_diff_order": 1,
    "object_diff_order": 1,
    "subject_adf_p_value": "0.018400",
    "object_adf_p_value": "0.021700",
    "stationarity_alpha": "0.050000"
  },
  "multiple_testing": {
    "alpha": "0.050000",
    "tested_hypotheses": 60,
    "corrected_alpha": "0.000833333333",
    "correction_method": "bonferroni",
    "correction_scope_hash": "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
  },
  "stability": {
    "structural_break_check": "pass",
    "rolling_windows_checked": 3,
    "rolling_windows_passed": 3,
    "oos_stability": "pass"
  },
  "rejection_reason": null
}
```

Field rules:

| Field | Required | Rule |
| --- | --- | --- |
| `pair_id` | yes | Deterministic ID from schema version, subject node ID, object node ID, relation, mapping hashes, cutoff, and lag grid. |
| `verification_status` | yes | One of `candidate`, `train_pass`, `holdout_pass`, `verified_stable`, `rejected_in_sample_only`, `rejected_direction_mismatch`, `rejected_multiple_testing`, `rejected_structural_break`, `rejected_leakage`, `rejected_p_hacking`, `rejected_flaky`, `rejected_malformed`, `inconclusive`. |
| `method` | yes | Must be `granger_predictive_lead` for this schema version. |
| `claim_label` | yes | Must be `statistical_lead_evidence`, never `true_causality`. |
| `selected_lag` | yes for tested pairs | Integer days chosen from train only. |
| `train.p_value` | yes for tested pairs | Decimal string, not float. |
| `holdout.p_value` | yes for tested pairs | Decimal string, not float. |
| `direction_match` | yes for train and holdout | Boolean, not string. |
| `rejection_reason` | rejected only | Machine readable reason. |

## Verification State Machine

Allowed transitions:

| From | To | Gate |
| --- | --- | --- |
| `candidate` | `inconclusive` | Missing approved mapping, insufficient rows, or non stationary after max diff. |
| `candidate` | `rejected_malformed` | Required input or JSON type is invalid. |
| `candidate` | `train_pass` | Train p value is below corrected alpha and train direction matches. |
| `candidate` | `rejected_multiple_testing` | Train p value is not below corrected alpha. |
| `candidate` | `rejected_direction_mismatch` | Train direction conflicts with relation policy. |
| `train_pass` | `rejected_in_sample_only` | Holdout p value fails corrected alpha or holdout direction fails. |
| `train_pass` | `holdout_pass` | Holdout p value passes corrected alpha and direction matches. |
| `holdout_pass` | `rejected_structural_break` | Any eligible break window reverses direction. |
| `holdout_pass` | `verified_stable` | Break checks and rolling windows pass. |
| any non terminal | `rejected_leakage` | Holdout or future rows influenced train decisions. |
| any non terminal | `rejected_p_hacking` | Lag grid, alpha, split, or correction scope changed after results were inspected. |
| any non terminal | `rejected_flaky` | Same fixture and config produce different status, lag, p value string, or pair ID. |

Terminal statuses are `verified_stable`, all `rejected_*` values, and `inconclusive`.

## Deterministic Math

All calculations must be reproducible from input artifacts and config.

Rules:

1. Sort pairs by `subject_node_id`, `object_node_id`, `relation`, and mapping provenance hash.
2. Align series by timestamp intersection before split.
3. Apply mapping transform before stationarity checks.
4. Split chronologically after alignment and before stationarity checks.
5. Use decimal string serialization for p values, alpha, corrected alpha, f statistics, and confidence.
6. Use canonical JSON with sorted keys and compact separators for every hash seed.
7. Do not use randomness in split, lag search, or break windows.

Pair ID seed:

```json
{
  "schema_version": "causal-statistical-verification.1",
  "subject_node_id": "cnode_0b6a943c2860b6e61893",
  "object_node_id": "cnode_96b23578f19cae76707f",
  "relation": "increases",
  "subject_mapping_hash": "sha256:1111111111111111111111111111111111111111111111111111111111111111",
  "object_mapping_hash": "sha256:2222222222222222222222222222222222222222222222222222222222222222",
  "verification_cutoff": "2026-08-06T00:00:00+09:00",
  "lag_grid": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
}
```

`pair_id` is `statpair_` plus first 20 hex characters of SHA 256 over the canonical seed.

## Verification Mutations

Verification changes are recorded as append only mutations inside the verification artifact.

Allowed mutations:

| Mutation | Required result |
| --- | --- |
| `mark_inconclusive` | Pair is not promoted and reason is stored. |
| `reject_in_sample_only` | Train pass cannot become verified stable without holdout pass. |
| `reject_p_hacking` | Lag grid, alpha, correction scope, split, or break window changed after result inspection. |
| `reject_leakage` | Future row, holdout row, duplicate timestamp, or post cutoff source influenced train. |
| `reject_flaky` | Same input and config produce different output. |
| `reject_malformed` | JSON shape, type, schema version, or required field fails. |

Mutation shape:

```json
{
  "mutation": "reject_in_sample_only",
  "pair_id": "statpair_fa52b889d05d6dbf97ab",
  "from_status": "train_pass",
  "to_status": "rejected_in_sample_only",
  "reason": "holdout_p_value_above_corrected_alpha",
  "evidence": {
    "train_p_value": "0.000400",
    "holdout_p_value": "0.120000",
    "corrected_alpha": "0.000833333333",
    "selected_lag": 5
  },
  "mutated_at": "2026-08-06T00:00:00+09:00",
  "mutated_by": "statistical-verifier.1"
}
```

## Fixtures

### F1 Stable Verified Pair

Input summary:

```json
{
  "pair_id": "statpair_fa52b889d05d6dbf97ab",
  "subject_node_id": "cnode_0b6a943c2860b6e61893",
  "object_node_id": "cnode_96b23578f19cae76707f",
  "relation": "increases",
  "lag_grid": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
  "alpha": "0.050000",
  "tested_hypotheses": 60
}
```

Expected result:

```json
{
  "verification_status": "verified_stable",
  "claim_label": "statistical_lead_evidence",
  "selected_lag": 5,
  "train": {
    "p_value": "0.000400",
    "direction_match": true,
    "rows": 420
  },
  "holdout": {
    "p_value": "0.000600",
    "direction_match": true,
    "rows": 120
  },
  "multiple_testing": {
    "corrected_alpha": "0.000833333333"
  },
  "stability": {
    "structural_break_check": "pass",
    "oos_stability": "pass"
  }
}
```

### F2 In Sample Only Failure

Input summary:

```json
{
  "pair_id": "statpair_9c4db4e263c69950e170",
  "subject_node_id": "cnode_0b6a943c2860b6e61893",
  "object_node_id": "cnode_96b23578f19cae76707f",
  "relation": "increases",
  "selected_lag": 5,
  "alpha": "0.050000",
  "tested_hypotheses": 60
}
```

Expected result:

```json
{
  "verification_status": "rejected_in_sample_only",
  "selected_lag": 5,
  "train": {
    "p_value": "0.000400",
    "direction_match": true,
    "rows": 420
  },
  "holdout": {
    "p_value": "0.120000",
    "direction_match": true,
    "rows": 120
  },
  "multiple_testing": {
    "corrected_alpha": "0.000833333333"
  },
  "rejection_reason": "holdout_p_value_above_corrected_alpha"
}
```

### F3 Inconclusive Pair

```json
{
  "pair_id": "statpair_35a2c78c8d91b32aa016",
  "verification_status": "inconclusive",
  "reason": "insufficient_holdout_rows",
  "holdout_rows": 18,
  "minimum_holdout_rows": 60
}
```

### F4 P Hacking Rejection

```json
{
  "pair_id": "statpair_fa52b889d05d6dbf97ab",
  "verification_status": "rejected_p_hacking",
  "reason": "lag_grid_changed_after_result_inspection",
  "original_lag_grid": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
  "mutated_lag_grid": [1, 2, 3, 4, 5]
}
```

### F5 Leakage Rejection

```json
{
  "pair_id": "statpair_fa52b889d05d6dbf97ab",
  "verification_status": "rejected_leakage",
  "reason": "holdout_timestamp_used_in_train_lag_selection",
  "leaked_timestamp": "2026-07-30"
}
```

### F6 Flaky Rejection

```json
{
  "pair_id": "statpair_fa52b889d05d6dbf97ab",
  "verification_status": "rejected_flaky",
  "reason": "same_fixture_changed_selected_lag",
  "first_run_selected_lag": 5,
  "second_run_selected_lag": 7
}
```

## Read, JSON, And Mutation QA

| QA area | Fixture | Required result |
| --- | --- | --- |
| Read QA | PRD 01 artifact has `schema_version = causal-node-canonicalization.1`. | Pair input reads canonical node IDs. |
| Read QA | Canonical node is missing or its label no longer matches its ID. | Pair becomes `rejected_malformed` before statistics run. |
| Read QA | PRD 02 `source_node_artifact_hash` differs from the supplied PRD 01 artifact. | Pair becomes `rejected_malformed`. |
| Read QA | PRD 02 mapping has expired manual approval. | Pair becomes inconclusive or rejected before Granger runs. |
| Read QA | Existing verified artifact stores `lag` as string. | New parser rejects it as malformed for this schema. |
| JSON QA | `direction_match` is string `"True"`. | Rejected as malformed. |
| JSON QA | `claim_label` is `true_causality`. | Rejected as malformed. |
| JSON QA | `corrected_alpha` is missing. | Rejected as malformed. |
| Mutation QA | Holdout p value fails after train pass. | `reject_in_sample_only` mutation is appended. |
| Mutation QA | Lag grid is narrowed after seeing p values. | `reject_p_hacking` mutation is appended. |
| Mutation QA | Holdout row appears in train decision log. | `reject_leakage` mutation is appended. |
| Mutation QA | Same fixture changes selected lag across two runs. | `reject_flaky` mutation is appended. |

## Acceptance Criteria

1. The PRD defines `causal-statistical-verification.1`.
2. It consumes PRD 01 canonical node IDs and PRD 02 approved mappings.
3. Stationarity, lag search, direction consistency, corrected alpha, train and holdout split, structural breaks, and out of sample stability are explicit.
4. The state machine includes `verified_stable`, rejected statuses, and `inconclusive`.
5. Granger output is labeled as statistical lead evidence, not true causality.
6. Corrected alpha uses a declared hypothesis count and Bonferroni correction.
7. Train pass alone cannot promote a pair without holdout and stability pass.
8. Fixtures include happy stable pair and in sample only failure.
9. Mutation QA covers p hacking, leakage, flaky output, malformed JSON, and in sample only rejection.
10. Missing nodes, canonical identity drift, and PRD 01/02 lineage hash drift are terminal `rejected_malformed` results.

## 구현 및 실행

- strict build, raw pair-local mapping boundary, series observation, and audit lock models: `src/causal/statistical_models.py`
- complete PRD 04 pair-result reader and decimal range checks: `src/causal/statistical_output_models.py`
- mapping hash recomputation and input/config/split/window/result fingerprints: `src/causal/statistical_hashes.py`
- pandas alignment/mapping transforms and statsmodels ADF/Granger primitives: `src/causal/statistical_math.py`
- pair preparation, 70/10/20 split, embargo, lag scope, and rolling checks: `src/causal/statistical_engine.py`
- terminal state evidence and append-only mutations: `src/causal/statistical_results.py`
- immutable versioned artifact assembly: `src/causal/statistical_pipeline.py`
- deterministic executable acceptance checks: `src/causal/statistical_acceptance.py`
- production JSON CLI: `scripts/verify_causal_statistical.py`

```bash
uv run scripts/verify_causal_statistical.py verify-fixture
uv run scripts/verify_causal_statistical.py build \
  --input data/causal_statistical_verification_input.json \
  --output data/causal_statistical_verification.json
```

`build` 입력은 canonical graph, approved mapping artifact, cutoff 이전의 explicit timestamp/value observations, predeclared config, audit locks를 한 JSON 문서로 전달한다. 출력 경로는 upstream 입력과 분리되며, 같은 canonical build를 다시 쓰면 `write_status = unchanged`, 다른 내용으로 기존 경로를 바꾸려 하면 immutable conflict를 반환한다.

### 구현된 split 및 audit lock 계약

- `split_policy`는 `chronological_70_10_20`으로 고정하며 `train_fraction`, `embargo_fraction`, `holdout_fraction`은 각각 `0.700000`, `0.100000`, `0.200000`이다.
- `embargo_sessions`가 실제 `train_end`와 `holdout_start` 사이의 row 경계를 결정한다. 정렬된 row 수의 10%와 일치하지 않으면 자동 보정하지 않고 terminal result를 만든다.
- `window_policy`는 `split_segments_and_equal_rolling`이다. `train`, `embargo`, `holdout` predeclared window와 전체 aligned frame의 equal rolling window를 모두 검사한다.
- 각 structural window는 실제 timestamp 범위에 대한 direction, mean shift, variance ratio evidence를 생성한다. embargo도 full structural frame에 보존된다.
- audit은 `input_fingerprint`, `run_config_hash`, `correction_scope_hash`, `split_policy_hash`, `window_policy_hash`를 독립적으로 잠근다. 잠금 이후 변경은 `rejected_p_hacking` mutation을 append한다.
- flaky 비교는 동일 `input_fingerprint`의 prior result에만 적용한다. 동일 입력에서 pair ID 집합 또는 complete result fingerprint가 달라지면 `rejected_flaky`가 된다.
- PRD 02 `mapping_hash`는 저장값을 신뢰하지 않고 approved mapping body로 재계산한다. 불일치는 pair-local `rejected_malformed`로 남는다.
- PRD 02 `source_node_artifact_hash`를 현재 PRD 01 canonical artifact에서 재계산한다. node 누락, canonical ID/label/direction 불일치, root hash drift는 통계 실행 전에 pair-local `rejected_malformed`로 닫힌다.
- 식별 가능한 malformed mapping과 duplicate timestamp는 build 전체를 중단하지 않고 각각 `rejected_malformed`, `rejected_leakage` pair result와 mutation을 생성한다.
- `verified_stable` reader는 `structural_break_check = pass`와 `oos_stability = pass`를 모두 요구하며 window 상태와 모순되는 structural 결과를 거부한다.
- `rolling_windows_checked`와 `rolling_windows_passed`는 `train`, `embargo`, `holdout` segment를 제외하고 `rolling_*` window만으로 재계산·검증한다.
