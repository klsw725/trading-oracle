# Trading Oracle v18 SPEC: Recommendation Outcome Measurement And Adaptive Policy Correctness
> **상태**: 📋 구현 예정

v18은 [v16](../v16/SPEC.md)의 검증된 session/data identity와 [v17](../v17/SPEC.md)의 SQLite durable foundation 위에서 advisory recommendation을 immutable prediction으로 등록하고, 정확한 N번째 공식 시장 session의 adjusted price로 성숙 결과를 측정한다. 학습 결과는 검토 가능한 bounded policy candidate일 뿐 active weight를 바꾸지 않는다.

## 0. 구현 완결성 계약

- v18은 v16·v17 public contract와 v18 local fixture만 의존하며 v19 이후 package, paper order 또는 fill을 import하거나 요구하지 않는다.
- `uv run python -m src.v18.cli acceptance`는 임시 SQLite에서 prediction 등록, legacy quarantine, horizon maturity, outcome 평가, eligible cohort, candidate 생성과 mutation rejection을 offline으로 실행하고 canonical JSON 한 줄과 exit 0을 낸다.
- Recommendation outcome은 advisory prediction horizon의 시장 수익률이다. Paper fill price, execution P&L, account NAV, 전략 또는 arm promotion은 측정하지 않는다.
- SQLite가 prediction, quarantine, evaluation, cohort manifest와 candidate의 유일한 durable truth다. JSON snapshot과 report는 복구·학습 truth가 아니다.
- 모든 평가 시각은 fixture의 `as_of`와 versioned official-session calendar를 사용한다. Wall clock, file mtime, row insertion order는 결과를 바꾸지 않는다.
- Prediction, outcome, cohort와 candidate는 KR/US, KRW/USD, account, arm, symbol, horizon, config/policy version을 격리한다.
- Duplicate retry는 no-op이고 같은 semantic identity의 다른 payload, 이미 확정된 evaluation의 재평가, active policy mutation은 state 불변으로 fail closed 한다.
- Acceptance는 tracked file과 `data/portfolio.json`의 존재·bytes·hash를 바꾸지 않고 network, broker, credential, live destination에 접근하지 않는다.
- 이 조건과 아래 Acceptance Criteria가 모두 통과하면 v18은 후속 버전 없이 단독 완료다.

## Local PRD Map

| PRD | Local document | Implementation owner | Produces |
| --- | --- | --- | --- |
| PRD 01 | [Prediction Identity And Quarantine](prds/prd01-prediction-identity-and-quarantine.md) | `src/v18/predictions.py`, `src/v18/quarantine.py`, `src/v18/repository.py` | immutable `PredictionRecord`와 quarantine ledger |
| PRD 02 | [Horizon Outcome Evaluation](prds/prd02-horizon-outcome-evaluation.md) | `src/v18/sessions.py`, `src/v18/prices.py`, `src/v18/evaluator.py` | exact-session `OutcomeEvaluation` |
| PRD 03 | [Adaptive Policy Candidates](prds/prd03-adaptive-policy-candidates.md) | `src/v18/cohorts.py`, `src/v18/candidates.py`, `src/v18/policy_repository.py` | bounded inactive `PolicyCandidate` |
| PRD 04 | [Measurement Acceptance](prds/prd04-measurement-acceptance.md) | `src/v18/acceptance.py`, `src/v18/boundaries.py`, `src/v18/cli.py` | standalone measurement acceptance report |

PRD 01→04 순서로 구현한다. Prediction identity와 quarantine은 PRD 01, maturity와 outcome 값은 PRD 02, cohort와 candidate는 PRD 03, 통합 검증만 PRD 04가 소유한다. 한 책임을 다른 PRD가 다시 계산하거나 수정하지 않는다.

## 1. v16·v17·v18 경계

v16은 calendar, adjusted-price fixture와 runtime identity를 검증한다. v18은 검증 결과를 lineage로 소비하며 data health를 다시 해석하지 않는다. v17은 SQLite transaction과 account namespace를 제공하지만 recommendation 의미를 정의하지 않는다. v18은 prediction 측정 table과 event를 별도 namespace에 추가하며 account projection을 변경하지 않는다.

Legacy `data/snapshots` 또는 JSON recommendation은 신뢰 가능한 prediction이 아니다. 명시적 quarantine command로 provenance와 bytes hash만 등록할 수 있고 outcome, cohort, candidate 입력으로 승격할 수 없다.

## 2. Prediction Identity 계약

`PredictionRecord` schema는 `v18.prediction.1`이며 다음 필드를 모두 가진다.

| Field | Contract |
| --- | --- |
| `prediction_id` | identity body의 `sha256:` canonical hash |
| `recommendation_id` | producer가 부여한 immutable opaque ID |
| `prediction_session` | recommendation cutoff가 속한 공식 market session |
| `horizon_sessions` | 1 이상의 registered integer horizon |
| `action` | `BUY`, `HOLD`, `SELL` 중 하나 |
| `reference_price_minor` | prediction cutoff의 adjusted close, positive integer |
| namespace | market, currency, account ID, arm ID, symbol |
| identity lineage | runtime, config, source policy, calendar, price-adjustment version |
| `perspective_scores` | registered perspective ID별 canonical decimal string |
| `source_payload_hash` | strict normalized recommendation payload hash |
| `recorded_as_of` | caller-supplied UTC RFC 3339 cutoff |

Identity body는 `prediction_id`와 receipt metadata를 제외한 모든 필드를 포함한다. Random UUID, database insertion time, host path는 identity가 아니다. 같은 `prediction_id`와 같은 bytes는 stored result를 반환하고, 같은 recommendation identity에 다른 body는 `PREDICTION_IDENTITY_CONFLICT`로 거부한다.

## 3. Prediction 상태와 Legacy Quarantine

| 상태 | 허용 전이 | 의미 |
| --- | --- | --- |
| `REGISTERED` | → `MATURE` | Immutable prediction, horizon 미도달 |
| `MATURE` | → `EVALUATED` | Exact target session과 adjusted price가 확정됨 |
| `EVALUATED` | 없음 | Outcome가 한 번 확정된 terminal state |
| `QUARANTINED` | 없음 | Legacy bytes의 provenance만 보존, 평가 불가 |

상태 전이는 append-only measurement event와 materialized state를 한 transaction으로 commit한다. Prediction body, target session, outcome을 `UPDATE`하는 API는 없다. 잘못된 등록은 새 identity로 다시 등록하며 기존 row를 고치지 않는다.

Quarantine schema `v18.legacy-quarantine.1`은 `quarantine_id`, relative source label, source bytes hash, observed schema hint, rejection codes, explicit `as_of`만 가진다. Legacy content를 parse해 누락 identity를 추정하거나 current policy로 보충하지 않는다.

## 4. Exact Nth Official-Session Horizon

Target은 `prediction_session` 다음의 open official session을 1로 세어 정확히 N번째 session이다. Prediction session 자체, `CLOSED` day와 비시장 day는 세지 않고 `EARLY_CLOSE`는 open session으로 한 번 센다. Market별 calendar version을 고정하며 KR calendar로 US maturity를 계산하지 않는다.

`as_of`가 target session의 official close보다 이르면 `IMMATURE`이고 evaluation row를 만들지 않는다. Calendar가 target까지 완전하지 않거나 version/hash가 prediction lineage와 다르면 fail closed 한다. 이후 calendar version으로 묵시적 재계산하지 않는다.

## 5. Adjusted Price와 Outcome

Price schema는 `v18.adjusted-close.1`이고 symbol, market, currency, session, positive minor-unit adjusted close, adjustment version, source dataset hash를 가진다. Split·distribution adjustment 계산 자체는 v16 input producer 책임이며 v18은 declared version과 hash를 검증해 소비한다. Raw close나 fill price로 fallback하지 않는다.

Outcome schema `v18.outcome.1`은 prediction ID, target session, target adjusted price, signed return basis points, directional verdict, maturity `as_of`, calendar/price hash와 evaluator policy version을 가진다. Return은 integer arithmetic과 명시적 half-away-from-zero rounding으로 계산한다.

| Action | `CORRECT` | `INCORRECT` | `NEUTRAL` |
| --- | --- | --- | --- |
| `BUY` | return > neutral band | return < -neutral band | 그 외 |
| `SELL` | return < -neutral band | return > neutral band | 그 외 |
| `HOLD` | absolute return ≤ neutral band | absolute return > neutral band | 없음 |

Neutral band는 evaluator policy version에 고정한다. Missing adjusted price, duplicate price, future row, currency mismatch는 평가 실패이며 `0` return으로 대체하지 않는다.

## 6. Eligible Cohort 계약

Candidate 입력 cohort는 query 결과가 아니라 immutable `v18.cohort-manifest.1` artifact다. Eligibility는 다음을 모두 요구한다.

- `EVALUATED` terminal prediction이며 horizon과 evaluator policy가 cohort specification과 일치
- Prediction cutoff 이후 target session data만 사용했고 maturity `as_of`가 target close 이상
- Quarantine 또는 superseded identity가 아님
- Market, currency, account, arm, source policy와 calendar/price version이 정확히 일치
- Perspective score vector가 완전하고 registered perspective set과 동일
- 같은 prediction ID와 economic observation이 한 번만 포함
- Versioned minimum sample count와 per-symbol cap 충족

Manifest는 ordered prediction IDs, inclusion/exclusion code, source outcome hashes와 cohort hash를 가진다. Excluded sample을 가중치 0으로 넣지 않으며 KR/US 또는 arm 간 pooling은 없다.

## 7. Bounded Perspective-Weight Candidate

`PolicyCandidate` schema는 `v18.policy-candidate.1`이다. Candidate는 base policy version, candidate version, namespace, cohort hash, objective version, perspective weight decimal strings, effective session, created `as_of`, evidence hash, status를 가진다.

Candidate generation은 fixture에 고정된 deterministic objective와 tie-break를 사용한다. 각 weight는 policy별 `[min_weight,max_weight]`, 합은 정확히 `1.000000`, base 대비 per-weight delta와 total L1 delta는 bound 이내여야 한다. Registered perspective를 추가·삭제하지 않는다.

| 상태 | 허용 전이 | 소유자 |
| --- | --- | --- |
| `PROPOSED` | → `APPROVED` 또는 `REJECTED` | v18 명시적 review command |
| `APPROVED` | → `SCHEDULED` 또는 `REJECTED` | v18 명시적 schedule command |
| `SCHEDULED` | → `ROLLED_BACK` | 후속 runtime activation 전 기록 상태 |
| `REJECTED` | 없음 | terminal |
| `ROLLED_BACK` | 없음 | terminal |

이 표의 `APPROVED`와 `SCHEDULED`는 v18 measurement domain 내부의 candidate review 기록이다. Human authorization, v20 lifecycle authorization, v21 signed approval 또는 activation evidence가 아니며 그 어느 계약도 대체하지 않는다. `effective_session`은 생성 `as_of` 뒤 해당 시장의 첫 허용 session 이상이어야 한다. Rollback은 candidate를 삭제하거나 active policy를 덮는 행위가 아니라 `rollback_of_candidate_id`를 가진 새 terminal event다. v18에는 `ACTIVE` 전이가 없고 어떤 command도 v16 config 또는 active weight를 수정하지 않는다.

## 8. SQLite와 Transaction 계약

v18 forward migration `002_measurement.sql`은 v17 global head `001`에서 시작해 global head `002`를 만들고 `predictions`, `legacy_prediction_quarantine`, `measurement_events`, `outcome_evaluations`, `cohort_manifests`, `policy_candidates`, `candidate_events`, `measurement_idempotency`를 추가한다. `schema_migrations`와 `PRAGMA user_version`은 단일 database의 global ordinal을 사용하며 v18에서 다시 시작하지 않는다. Migration inventory는 v17 store의 hash·transaction 규칙을 따른다.

Registration, evaluation, cohort freeze, candidate state transition은 각각 semantic key 확인→current invariant 확인→immutable row/event append→projection update→hash 검증→commit 순서의 단일 transaction이다. Crash는 전부 또는 아무것도 남기지 않는다. v17 account balance·position·reservation table은 write set에 포함되지 않는다.

## 9. CLI 계약

| Command | 역할 |
| --- | --- |
| `register-prediction` | Strict normalized prediction 등록 |
| `quarantine-legacy` | Legacy snapshot hash와 rejection만 격리 등록 |
| `evaluate` | 명시적 `--as-of`에서 mature prediction 평가 |
| `build-candidate` | Frozen eligible cohort로 inactive candidate 생성 |
| `candidate-transition` | approve, reject, schedule 또는 rollback 기록 |
| `prd01-acceptance` | Identity·quarantine acceptance |
| `prd02-acceptance` | Horizon·outcome acceptance |
| `prd03-acceptance` | Cohort·candidate acceptance |
| `prd04-acceptance` | Mutation·boundary acceptance |
| `acceptance` | v18 standalone acceptance |

Canonical 명령은 `uv run python -m src.v18.cli acceptance`다. 성공은 exit 0, 계약상 invalid input/state는 exit 2, 내부 결함은 exit 1이다. 모든 machine command는 canonical JSON 한 줄을 stdout에 출력한다.

## 10. Failure와 Mutation 계약

| Probe | Mutation | Required result |
| --- | --- | --- |
| `prediction_duplicate_retry` | 같은 identity/body 10회 등록 | 같은 ID, row/event count 불변 |
| `prediction_identity_conflict` | 같은 recommendation ID에 symbol/action 변경 | `PREDICTION_IDENTITY_CONFLICT`, state 불변 |
| `legacy_missing_identity` | legacy snapshot을 prediction으로 직접 import | `LEGACY_SNAPSHOT_QUARANTINED` |
| `quarantine_promotion` | quarantine ID를 evaluation/cohort에 주입 | `INELIGIBLE_QUARANTINE_RECORD` |
| `weekend_horizon` | closed days를 N에 포함 | exact official target 불일치 탐지 |
| `early_close_horizon` | early close를 제외 | exact official target 불일치 탐지 |
| `immature_as_of` | target close 1초 전 평가 | `OUTCOME_IMMATURE`, write 0건 |
| `calendar_version_drift` | prediction 뒤 calendar version 교체 | `CALENDAR_IDENTITY_MISMATCH` |
| `raw_price_substitution` | adjusted close 대신 raw close | `PRICE_ADJUSTMENT_MISMATCH` |
| `missing_target_price` | exact target row 제거 | `TARGET_PRICE_MISSING`, write 0건 |
| `duplicate_target_price` | target price row 복제 | `TARGET_PRICE_AMBIGUOUS` |
| `cross_market_price` | KR prediction에 US/USD price | `NAMESPACE_MISMATCH` |
| `immature_cohort_member` | REGISTERED prediction을 cohort에 포함 | `COHORT_MEMBER_INELIGIBLE` |
| `duplicate_cohort_member` | prediction ID 또는 observation 중복 | `COHORT_DUPLICATE_MEMBER` |
| `leakage_future_input` | prediction cutoff 뒤 perspective feature 주입 | `MEASUREMENT_LEAKAGE` |
| `candidate_bound_escape` | min/max, delta 또는 sum 위반 | `CANDIDATE_WEIGHT_BOUNDS` |
| `candidate_effective_past` | effective session을 생성 이전으로 이동 | `CANDIDATE_EFFECTIVE_SESSION_INVALID` |
| `active_weight_overwrite` | candidate command로 active config 변경 시도 | `ACTIVE_POLICY_MUTATION_FORBIDDEN` |
| `evaluation_payload_conflict` | 확정 prediction을 다른 price/as-of로 재평가 | `EVALUATION_IMMUTABLE`, state 불변 |
| `rollback_deletes_history` | rollback 시 candidate/event 삭제 시도 | `CANDIDATE_HISTORY_IMMUTABLE` |
| `portfolio_mutation` | acceptance 전후 legacy portfolio 감시 | 존재·bytes·hash 불변 |
| `network_attempt` | socket/DNS/HTTP trap | 호출 0건 |
| `later_version_import` | v19 이후 import trap | import 0건 |

## 11. 의존성과 비목표

의존성은 Python 표준 라이브러리, v16 identity/calendar/data public models, v17 SQLite transaction public contract, v18 package와 local fixtures다. v16/v17 CLI를 subprocess로 실행하지 않는다.

다음은 v18 비목표다.

- Paper fill P&L, execution quality, realized account return, NAV
- Strategy, arm 또는 model의 promotion·activation과 active weight overwrite
- Recommendation producer, order, risk, sizing, reservation 또는 fill simulation
- Live broker, credential, web UI, multi-user, multi-host, daemon
- 새 data vendor·calendar·strategy 또는 network-required acceptance
- Legacy snapshot migration, 자동 보정 또는 `data/portfolio.json` mutation

## 12. Acceptance Criteria

- Prediction identity가 immutable하고 semantic duplicate와 conflict를 구분한다.
- Identity가 불완전한 legacy snapshot은 quarantine되며 평가·학습에 들어가지 않는다.
- 정확한 N번째 official session, adjusted price, maturity와 explicit `as_of`로 outcome을 한 번만 확정한다.
- Leakage, immature, duplicate, namespace/version mismatch가 모든 mutation 전에 fail closed 한다.
- Eligible cohort가 immutable manifest와 evidence hash로 재현된다.
- Perspective-weight candidate가 deterministic·bounded이고 version/effective session/rollback history를 가진다.
- Candidate는 active policy를 절대 덮지 않으며 v18은 promotion을 수행하지 않는다.
- SQLite가 measurement truth이고 account projection과 `data/portfolio.json`은 변하지 않는다.
- Canonical acceptance가 offline·deterministic하며 v19 이후를 import하지 않는다.
