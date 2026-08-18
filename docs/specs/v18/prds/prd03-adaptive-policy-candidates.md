# PRD: v18 PRD 03 Adaptive Policy Candidates
> **상태**: 📋 구현 예정
> 상위 SPEC: [v18 SPEC](../SPEC.md)

## 의존성

- [PRD 01](prd01-prediction-identity-and-quarantine.md)의 prediction identity와 quarantine exclusion
- [PRD 02](prd02-horizon-outcome-evaluation.md)의 terminal `OutcomeEvaluation`
- v18 local objective·weight-bound policy fixtures

## 목표

Leakage 없는 eligible outcome cohort를 immutable하게 고정하고, registered perspective set에 대해 bounded·versioned weight candidate만 생성하며 active policy는 변경하지 않는다.

## 구현 표면

| 경로 | 책임 |
| --- | --- |
| `src/v18/eligibility.py` | Cohort inclusion/exclusion predicate와 codes |
| `src/v18/cohorts.py` | Ordered immutable cohort manifest와 hash |
| `src/v18/objective.py` | Deterministic candidate objective·tie-break |
| `src/v18/candidates.py` | Weight bounds, version, effective-session validation |
| `src/v18/policy_repository.py` | Candidate event/state persistence와 rollback history |

## Eligible Cohort 계약

Schema `v18.cohort-manifest.1`은 namespace, horizon, source/evaluator policy versions, calendar/price versions, eligibility policy version, explicit cutoff `as_of`, ordered member IDs, 각 inclusion/exclusion code, source outcome hashes와 manifest hash를 가진다.

Member는 terminal `EVALUATED`, cutoff 이하에서 available, complete perspective vector, exact namespace/version, unique prediction and economic observation이어야 한다. Quarantine, immature, superseded, duplicate, future-evaluated row는 제외한다. Minimum sample과 per-symbol cap은 eligibility policy에 고정한다.

Exclusion은 조용히 drop하지 않고 stable code와 evidence hash로 manifest에 남긴다. Excluded member를 zero-weight sample로 objective에 넣지 않는다.

## Candidate 계산 계약

Objective schema `v18.perspective-objective.1`은 perspective별 correctness contribution을 cohort member ID 순으로 합산한다. Decimal quantization과 tie-break는 policy에 고정하며 database row order, random seed 또는 host math library의 비결정적 최적화에 의존하지 않는다.

| Constraint | Required rule |
| --- | --- |
| Perspective set | Base policy와 정확히 동일 |
| Individual bound | 각 `[min_weight,max_weight]` 포함 |
| Sum | canonical decimal `1.000000` |
| Per-weight delta | base 대비 configured maximum 이하 |
| Total movement | L1 delta configured maximum 이하 |
| Candidate version | base와 다르고 namespace에서 unique |
| Effective session | created `as_of` 뒤 허용 official session |

Constraint를 만족하는 개선안이 없으면 `NO_ELIGIBLE_CANDIDATE`이며 current weight 복제 candidate를 만들지 않는다.

## Candidate 상태 계약

Candidate event schema는 `v18.policy-candidate-event.1`이다.

| Current | Command | Next | Active policy write |
| --- | --- | --- | ---: |
| 없음 | propose | `PROPOSED` | 0 |
| `PROPOSED` | approve | `APPROVED` | 0 |
| `PROPOSED`/`APPROVED` | reject | `REJECTED` | 0 |
| `APPROVED` | schedule | `SCHEDULED` | 0 |
| `SCHEDULED` | rollback | `ROLLED_BACK` | 0 |
| terminal | any transition | failure | 0 |

Review command는 caller ID가 아닌 deterministic review decision ID와 explicit `as_of`를 기록한다. 이 PRD의 `APPROVED`/`SCHEDULED`는 measurement candidate에 대한 domain-local review 상태일 뿐 human authorization, v20 authorization check, v21 signed approval 또는 promotion evidence가 아니다. Rollback은 history를 삭제하지 않고 `rollback_of_candidate_id`를 append한다. `ACTIVE`, automatic activation, base policy overwrite transition은 존재하지 않는다.

## Failure 계약

| Code | 조건 |
| --- | --- |
| `COHORT_MEMBER_INELIGIBLE` | immature, quarantine, lineage/vector mismatch |
| `COHORT_DUPLICATE_MEMBER` | prediction 또는 economic observation 중복 |
| `MEASUREMENT_LEAKAGE` | cutoff 뒤 feature/outcome을 earlier sample에 사용 |
| `COHORT_TOO_SMALL` | minimum eligible sample 미달 |
| `CANDIDATE_WEIGHT_BOUNDS` | set, individual, sum 또는 delta 위반 |
| `CANDIDATE_VERSION_CONFLICT` | candidate version 재사용 |
| `CANDIDATE_EFFECTIVE_SESSION_INVALID` | past/closed/wrong-market session |
| `CANDIDATE_TRANSITION_INVALID` | 상태표 밖 전이 |
| `ACTIVE_POLICY_MUTATION_FORBIDDEN` | config/active weight write 시도 |
| `CANDIDATE_HISTORY_IMMUTABLE` | event update/delete 또는 rollback 삭제 |

## CLI

```bash
uv run python -m src.v18.cli build-candidate --cohort cohort.json --as-of 2026-02-01T00:00:00Z --database data/paper/v17/paper.sqlite3
uv run python -m src.v18.cli candidate-transition --candidate-id sha256:... --transition approve --as-of 2026-02-01T00:00:00Z --database data/paper/v17/paper.sqlite3
uv run python -m src.v18.cli prd03-acceptance
```

## Acceptance와 Mutation

| Probe | Mutation | Required result |
| --- | --- | --- |
| `eligible_manifest` | 같은 outcomes 순서 shuffle | 같은 ordered members/hash |
| `future_leakage` | cutoff 뒤 outcome 주입 | leakage failure |
| `immature_or_quarantine` | ineligible member 추가 | explicit exclusion, objective 미사용 |
| `duplicate_observation` | ID alias로 같은 observation 반복 | duplicate failure |
| `bound_escape` | sum·min/max·delta 각각 위반 | candidate 미생성 |
| `effective_session` | past·closed·wrong market 지정 | stable failure |
| `rollback_history` | scheduled rollback | append-only terminal history |
| `active_overwrite` | active config bytes 변경 시도 | forbidden, bytes/hash 불변 |

## 완료 조건

- Cohort membership과 exclusion이 cutoff 기준으로 완전히 재현된다.
- Candidate 계산이 deterministic하고 모든 bound를 만족한다.
- Version, effective session, review와 rollback history가 immutable하다.
- Active perspective weights와 strategy/arm status를 변경하는 경로가 없다.

## 비목표

- Candidate 자동 승인·활성화·promotion
- Multi-arm 시험 배정과 승자 선택
- Paper execution P&L 기반 학습
- Perspective 추가·삭제 또는 objective 자동 탐색
