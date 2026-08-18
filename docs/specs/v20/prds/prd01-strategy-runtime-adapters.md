# PRD: v20 PRD 01 V12 15-Strategy Runtime Adapters
> **상태**: 📋 구현 예정
> 상위 SPEC: [v20 SPEC](../SPEC.md)

## 의존성

- [v12 SPEC](../../v12/SPEC.md), [Strategy Grids](../../v12/STRATEGY-GRIDS.md)와 [v12 PRD 01](../../v12/prds/prd01-strategy-runtime-candidate-contract.md)의 15-strategy runtime/candidate contract
- [v14 SPEC](../../v14/SPEC.md)의 frozen strategy manifest와 verdict evidence
- [v15 SPEC](../../v15/SPEC.md)의 ORB-first activation과 qualification contract
- [v16 SPEC](../../v16/SPEC.md)의 verified runtime/data/calendar identity
- [v17 SPEC](../../v17/SPEC.md)의 SQLite transaction/idempotency contract
- [v19 Decision Envelope PRD](../../v19/prds/prd02-decision-envelope-and-intake.md)의 neutral intake schema

## 목표

Recorded market input을 실제 v12 typed evaluator에 전달해 15개 strategy·60개 registered parameter arm의 candidate/no-candidate 결과를 검증하고, run manifest가 활성화한 ORB baseline과 자격을 갖춘 14개 shadow arm을 v19 `DecisionEnvelope` batch로 변환·영속화한다.

## 구현 표면

| 경로 | 책임 |
| --- | --- |
| `src/v20/strategy_models.py` | Strategy adapter request/result와 mapping strict schemas |
| `src/v20/strategy_adapter.py` | V12 registry/evaluator 호출과 result assembly |
| `src/v20/decision_mapping.py` | V12/V13 result의 단일 v19 envelope mapping |
| `src/v20/adapter_repository.py` | Invocation/result/mapping semantic idempotency |
| `src/v20/migrations/004_runtime_adapters.sql` | Global head `003`→`004`; runtime invocation/result/mapping tables |

PRD 01은 router score, lifecycle transition, multi-session orchestration과 approval을 구현하지 않는다. `decision_mapping.py`의 schema/version은 이 PRD가 소유하고 PRD 02는 같은 mapping을 소비한다.

## 호출해야 하는 V12 Runtime

Adapter는 다음 public surface를 typed call로 사용한다.

- `src.v12.models.StrategyInput`과 등록 input/evidence types
- `src.v12.registry.REGISTRY`, `strategy()`, `validate_registry()`
- `src.v12.evaluators.evaluate_gate()`
- V12 candidate identity, eligibility, execution-feasible와 attribution public functions

다음 fixture path는 runtime과 v20 acceptance에서 호출할 수 없다.

- `src/v12/fixture_factory.py`
- `src/v12/strategy_input_fixture.py`
- `src/v12/acceptance.py`의 `load_fixture()`와 `build_path()`
- 미리 직렬화된 candidate, gate result 또는 expected decision builder

Recorded input loader는 strict `StrategyInput`을 만들 수 있지만 gate/candidate/result를 만들지 않는다. V12 runtime만 feature·gate·score와 candidate identity를 결정한다.

## Adapter Schema

`v20.strategy-adapter-request.1`:

| Field | Contract |
| --- | --- |
| `invocation` | `v20.runtime-invocation.1`, producer `V12_STRATEGY` |
| `plan_id` | target v19 plan |
| `strategy_manifest_hash` | v14/v15가 동결한 exact manifest |
| `active_parameter_sets` | strategy ID별 등록 parameter set 하나 |
| `inputs` | symbol·strategy에 필요한 typed `StrategyInput` ordered tuple |
| `eligibility_refs` | universe/data/action/borrow/regulation/risk evidence |
| `qualification_ref` | ORB 또는 shadow activation state/evidence hash |

`v20.strategy-adapter-result.1`:

| Field | Contract |
| --- | --- |
| `invocation_id` | request identity |
| `registry_hash` | 정확히 15 strategy와 shared grid hash |
| `evaluations` | strategy·symbol·parameter canonical order |
| `candidate_refs` | V12 candidate IDs와 canonical hashes |
| `no_candidate_refs` | gate/eligibility 실패의 stable reason/evidence |
| `decision_batch_ref` | mapped v19 batch hash |
| `result_hash` | strict body hash |

Evaluation row는 strategy ID/version, parameter set ID, side, signal cutoff, feature snapshot hash, deterministic score, gate status, execution-feasible status와 evidence refs를 가진다. V12에 없는 score, confidence, metric 또는 fallback field를 추가하지 않는다.

Evaluation row의 score, gate, candidate와 execution-feasible 값은 `SOURCE_OUTPUT`이며 v12 typed result를 변형하지 않는다. Invocation/mapping ID, namespace check와 v19 action field만 `V20_MAPPING`이다. Acceptance report는 provenance별 field inventory를 고정해 v20이 score·gate를 재계산하지 않았음을 검증한다.

## Registry와 Parameter 불변식

- Registry는 Long 10개, Short 5개 총 15개여야 한다.
- Strategy마다 V12에 등록된 4개 parameter set만 허용하고 KR/US grid가 같아야 한다.
- Run은 strategy별 `active_parameter_set_id` 하나를 시작 전에 manifest에 동결한다.
- Acceptance는 15 strategy의 등록 parameter set 4개를 각각 actual evaluator로 실행해 총 60 arm coverage와 독립 namespace를 검증한다. Production session은 동결된 active set만 실행한다.
- Fifth grid, unregistered strategy/evaluator, changed threshold와 output을 본 뒤 parameter 교체는 fail closed 한다.
- Short result는 v11/v12 borrow·regulation eligibility 없이는 execution-feasible이 될 수 없다.
- Same strategy-symbol-session은 최초 valid gate emission 하나만 가질 수 있다.

정확한 feature, gate, score, ORB window와 exit 숫자는 [Strategy Grids](../../v12/STRATEGY-GRIDS.md)와 v12가 소유한다. V20 문서나 code에 duplicate 상수로 재정의하지 않는다.

## ORB Baseline

`long_orb_15m`은 v15 lifecycle의 최초 paper baseline이다. Adapter는 다른 strategy와 같은 evaluator path를 사용하되 lifecycle projection이 `orb_paper`인 market·arm에만 primary-producing envelope를 만든다.

- V12 complete 5분봉·watermark·15~60분 first-close breakout·first 1m entry·no stop/target·close exit를 그대로 호출한다.
- ORB v14 validation/untouched holdout evidence와 effective session이 request manifest에 exact binding되어야 한다.
- KR pass가 US ORB를 활성화하지 않으며 KRW/USD account를 공유하지 않는다.
- ORB no-signal은 다른 strategy를 primary로 대체하는 규칙이 아니다.

## 14-Strategy Shadow Qualification

ORB 외 14개 strategy는 [v15 qualification](../../v15/prds/prd01-approval-promotion-activation.md)을 통과한 market에서만 shadow execution을 만든다.

Qualification evidence는 별도 ORB v11/v17 ledger의 첫 post-gate official session부터 20 official sessions, completed trades 30건 이상, critical ledger/replay/risk incident 0건과 sample inventory hash를 가져야 한다. V20은 이 수치를 설정값으로 바꾸거나 자체 metric으로 대체하지 않는다.

`strategies_candidate → strategies_shadow` 전이는 PRD 03이 소유한다. PRD 01은 current lifecycle projection과 qualification ref를 읽어 허용된 shadow arm만 실행한다. Qualification 전 결과는 연구 evaluation으로 기록할 수 있지만 v19 execution batch에 제출하지 않는다.

## Arm과 Namespace Mapping

각 strategy·parameter shadow는 독립 account/arm namespace를 사용한다. ORB baseline, router challenger와 strategy shadows 사이에 다음을 공유하지 않는다.

- cash, reservation와 slot
- position와 owner
- candidate/intake/execution semantic key
- daily loss NAV와 kill overlay

Mapping 전에 request namespace, candidate market/session, v19 plan namespace와 SQLite account identity를 field-by-field 비교한다. 하나라도 다르면 batch를 만들지 않는다.

## DecisionEnvelope Mapping

Candidate result는 `v20.decision-mapping.1`을 통해 v19 schema로 변환한다.

- Candidate ID와 hash는 source evidence와 producer-neutral decision identity에 binding한다.
- Side/action mapping은 v11/v19 supported action만 허용한다.
- Quantity와 gate inputs는 기존 v11/v19 sizing/risk mapping 결과를 사용한다.
- Signal cutoff, watermark, ready time이 v19 plan decision cutoff보다 늦으면 mapping 실패다.
- Integrated plan의 fixed target symbol마다 no-candidate evidence는 quantity 0의 `NO_TRADE` envelope 정확히 하나로 번역한다. 이는 trade candidate가 아니며 risk/reservation/intent/fill을 만들지 않는다.
- Producer contract name/version은 provenance이며 v19 dispatch key가 아니다.

Result, mapping receipt와 v19 intake는 PRD 04가 동일 transaction으로 묶는다.

## SQLite와 Idempotency

Semantic key는 producer, namespace, plan, cutoff, strategy/parameter manifest와 input inventory hash를 포함한다. Exact retry는 stored request/result/mapping IDs를 반환한다.

같은 key에서 bar, eligibility, active parameter, runtime identity 또는 evidence hash가 바뀌면 `ADAPTER_IDEMPOTENCY_CONFLICT`다. Result row만 있고 mapping이 없는 partial state, 같은 candidate를 다른 arm에 mapping한 row와 registry drift는 reconciliation failure다.

SQLite row 순서는 identity가 아니다. 모든 tuple과 report는 strategy ID, symbol, parameter ID, cutoff의 명시적 canonical order를 사용한다.

## Failure 계약

| Code | 조건 | Mutation |
| --- | --- | ---: |
| `STRATEGY_REGISTRY_INVALID` | 15 inventory/shared grid 불일치 | 0 |
| `STRATEGY_PARAMETER_UNREGISTERED` | fifth/unknown parameter | 0 |
| `STRATEGY_INPUT_INVALID` | incomplete/stale/cross-session typed input | 0 |
| `STRATEGY_RUNTIME_CONTRACT_FAILED` | evaluator/gate/candidate invariant 위반 | 0 |
| `STRATEGY_NOT_ACTIVATED` | qualification 전 execution 요청 | 0 |
| `STRATEGY_NAMESPACE_MISMATCH` | market/currency/account/arm/session 교차 | 0 |
| `STRATEGY_MAPPING_UNSUPPORTED` | v19이 지원하지 않는 action/result | 0 |
| `UNSUPPORTED_SYNTHETIC_RESULT` | fixture-built candidate/gate/result 주입 | 0 |
| `ADAPTER_IDEMPOTENCY_CONFLICT` | 같은 semantic key의 다른 meaning | 0 |

## CLI

```bash
uv run python -m src.v20.cli run-strategies --plan-id sha256:... --input recorded-market.json --database data/paper/v17/paper.sqlite3
uv run python -m src.v20.cli prd01-acceptance
```

## Acceptance와 Mutation

| Probe | Mutation | Required result |
| --- | --- | --- |
| `all_registered_strategies` | 15 strategy와 active set 실행 | actual evaluator coverage 15 |
| `all_registered_parameter_arms` | 각 strategy의 등록 set 순회 | actual evaluator coverage 60, namespace 60 |
| `strategy_registry_drift` | strategy/grid 추가·삭제 | fail, DB pre-hash |
| `strategy_fixture_builder_attempt` | prebuilt candidate 전달 | unsupported synthetic result |
| `orb_contract_drift` | hidden stop/window/exit 변경 | v12 contract failure |
| `shadow_qualification_early` | 19 sessions/trades 또는 incident | no shadow execution |
| `short_without_eligibility` | borrow ref 제거 | candidate 없음 |
| `duplicate_session_emission` | 같은 first gate 재실행 | stored result, candidate 하나 |
| `cross_arm_mapping` | ORB result를 shadow/router plan에 사용 | namespace failure |
| `adapter_duplicate_retry` | close/reopen 뒤 exact retry | rows/hash 불변 |
| `adapter_payload_conflict` | same key bar/parameter 변경 | conflict, DB pre-hash |

## 완료 조건

- 모든 15 strategy·60 registered parameter arm이 실제 v12 typed runtime을 통해 평가되고 production run은 frozen active set만 실행한다.
- ORB baseline과 14개 shadow 실행 경계가 v14/v15 evidence와 lifecycle state에 binding된다.
- Candidate/result/mapping이 SQLite에서 semantic retry와 replay를 보존한다.
- Fixture builder 없이 recorded raw input만으로 같은 canonical result를 만든다.

## 비목표

- 새 strategy, feature, parameter, score, risk 또는 sizing rule
- Parameter selection, qualification threshold 변경과 promotion 판정
- V13 router score/fallback/circuit
- Human approval command·record lifecycle
- Live data download, broker와 network-required acceptance
