# Trading Oracle v20 SPEC: Runtime Strategy/Router Integration And Lifecycle Safety
> **상태**: 📋 구현 예정

v20은 [v12](../v12/SPEC.md)의 15-strategy runtime과 [v13](../v13/SPEC.md)의 mixed router를 실제 typed adapter로 실행해 [v19](../v19/SPEC.md)의 `DecisionEnvelope`와 session execution에 연결한다. [v14](../v14/SPEC.md)의 qualification·holdout evidence와 [v15](../v15/SPEC.md)의 mirror·promotion·rollback·kill·recovery 계약은 새로 계산하거나 완화하지 않고 [v17](../v17/SPEC.md) SQLite 유일 진실 위의 durable lifecycle transition으로 번역한다.

## 0. 구현 완결성 계약

- v20은 v12~v19 public typed contract와 v20 local recorded inputs/responses만 의존하며 v21 human approval command나 v22 public CLI black-box suite를 import하지 않는다.
- `uv run python -m src.v20.cli acceptance`는 실제 v12 15-strategy·60 registered parameter-arm adapter, ORB baseline, v13 mixed-router adapter, recorded Codex replay, v19 multi-session execution과 v15 lifecycle 판정을 임시 SQLite에서 offline으로 실행하고 canonical JSON 한 줄과 exit 0을 낸다.
- Fixture는 immutable market input, source evidence, recorded Codex response와 이미 발급된 approval evidence만 제공한다. Fixture builder가 candidate, router selection, mirror economics, winner, rollback, kill 또는 recovery 결과를 미리 만들 수 없다.
- V12의 전략·parameter·score, v13의 weight·fallback·circuit·NO_TRADE, v14의 metric·sample·verdict와 v15의 promotion·rollback·kill threshold를 복사해 변형하거나 새 값을 추가하지 않는다.
- 모든 producer output은 strict v20 adapter result를 거쳐 v19 `DecisionEnvelope`와 `DecisionBatch`가 된다. Raw v12/v13 artifact를 v19 intake에 직접 넣거나 producer label로 dispatch하지 않는다.
- SQLite는 adapter invocation/result, router call/circuit state, lifecycle event/projection, mirror binding, authorization decision와 v19/v17 execution effect의 유일한 durable truth다. JSON bundle, report와 in-memory state는 recovery truth가 아니다.
- Adapter invocation부터 envelope intake, lifecycle transition과 관련 v17/v19 write는 각 의미 단위의 단일 SQLite connection·transaction에서 commit하거나 모두 rollback한다.
- Semantic retry는 stored result를 반환한다. 같은 semantic key의 input, response, policy, evidence 또는 approval hash 변경은 추가 mutation 전에 fail closed 한다.
- 모든 실행은 paper-only이며 KR/US, KRW/USD, account, arm, session, comparison epoch와 policy/manifest version을 격리한다. Cross-arm cash·slot·position·reservation·NAV 공유와 cross-market fallback은 없다.
- V20은 어떤 human approval도 발급, 철회, 대체 또는 자동 생성하지 않는다. Approval이 필요한 transition을 판정하고 caller가 제공한 기존 evidence를 검증·binding·기록할 뿐이다. Operator command와 approval record lifecycle은 v21 소유다.
- Acceptance는 network, live broker, credential, vendor 호출 없이 recorded inputs/responses로 결정적이며 tracked file과 `data/portfolio.json`의 존재·bytes·hash를 바꾸지 않는다.
- 이 조건과 아래 Acceptance Criteria가 모두 통과하면 v20은 v21/v22 없이 standalone 완료다.

## Local PRD Map

| PRD | Local document | Implementation owner | Produces |
| --- | --- | --- | --- |
| PRD 01 | [V12 15-Strategy Runtime Adapter](prds/prd01-strategy-runtime-adapters.md) | `src/v20/strategy_adapter.py`, `src/v20/strategy_models.py` | 실제 strategy result와 ORB/shadow decision batch |
| PRD 02 | [V13 Router Runtime And Fallback](prds/prd02-router-runtime-and-fallback.md) | `src/v20/router_adapter.py`, `src/v20/router_models.py`, `src/v20/router_state.py` | mixed/quant router result와 durable circuit state |
| PRD 03 | [Promotion, Rollback And Kill Lifecycle](prds/prd03-promotion-rollback-and-kill-lifecycle.md) | `src/v20/lifecycle.py`, `src/v20/authorization.py`, `src/v20/lifecycle_repository.py` | mirror/promotion/rollback/kill/recovery transitions |
| PRD 04 | [Runtime Integration Acceptance](prds/prd04-runtime-integration-acceptance.md) | `src/v20/session_integration.py`, `src/v20/acceptance.py`, `src/v20/boundaries.py`, `src/v20/cli.py` | 실제 adapter multi-session standalone report |

PRD 01→04 순서로 구현한다. Adapter 공통 schema와 canonical identity는 PRD 01, router call·fallback·circuit persistence는 PRD 02, lifecycle state와 authorization predicate는 PRD 03, v19 session 연결·fault/restart·전체 acceptance는 PRD 04만 소유한다.

## 1. 선행 버전과 v20 경계

- [v12 Strategy Grids](../v12/STRATEGY-GRIDS.md)는 15개 strategy, 60 arm, feature·gate·score·parameter의 유일한 정의다. V20은 `StrategyInput`, registry와 evaluator를 호출하고 새 strategy 또는 threshold를 만들지 않는다.
- [v13](../v13/SPEC.md)은 80:20 mixed score, 허용된 6개 `NO_TRADE` policy, item/market fallback, 20초 no-retry와 circuit semantics를 소유한다. V20은 call result와 circuit projection을 SQLite session state에 연결한다.
- [v14](../v14/SPEC.md)은 development/validation/untouched holdout, metric, bootstrap, cost stress와 verdict를 소유한다. V20은 canonical evidence/hash를 qualification input으로 소비할 뿐 재연구하지 않는다.
- [v15](../v15/SPEC.md)은 paper lifecycle의 상태, sample gate, winner, rollback, kill scope와 recovery 조건을 소유한다. V20은 typed functions를 실제 session 결과에 적용하고 transition을 영속화한다.
- [v16](../v16/SPEC.md)은 runtime/config/calendar/data-health identity를 제공한다. Adapter는 verified input만 받고 source download나 current-time 보정을 하지 않는다.
- [v17](../v17/SPEC.md)은 SQLite event, idempotency, account projection과 reconciliation의 유일 진실이다. V20 migration은 같은 database와 transaction discipline을 사용한다.
- [v18](../v18/SPEC.md)의 prediction/outcome/candidate는 v20 strategy promotion 입력이 아니다. Measurement table을 읽거나 쓰지 않는다.
- [v19](../v19/SPEC.md)은 plan/run/lease, neutral envelope intake와 decision-to-paper execution을 소유한다. V20은 producer boundary 밖에서 envelope를 만들고 v19 public service를 호출한다.

## 2. Runtime Adapter 공통 계약

Adapter invocation schema는 `v20.runtime-invocation.1`이다.

| Field | Contract |
| --- | --- |
| `invocation_id` | canonical body의 `sha256:` hash |
| producer | `V12_STRATEGY` 또는 `V13_ROUTER` |
| namespace | market, currency, account ID, arm ID |
| session identity | plan ID, session date, cutoff, watermark |
| runtime identity | v16 runtime/config/data identity |
| contract identity | producer schema, strategy/router/parameter/policy versions |
| input refs | ordered immutable source/candidate/response hashes |
| `semantic_key` | producer·namespace·plan·cutoff·contract identity hash |
| `requested_as_of` | caller-supplied canonical UTC timestamp |

결과 schema `v20.adapter-result.1`은 invocation ID, result kind, ordered decisions, input/output hash, evidence refs, fallback/circuit metadata와 producer contract version을 가진다. 각 필드는 `SOURCE_OUTPUT` 또는 `V20_MAPPING` provenance를 가진다. Score, gate, candidate, percentile, fallback과 circuit outcome은 v12/v13 typed output을 그대로 보존하고 v20은 identity·namespace·v19 field mapping만 계산한다. Result는 v19 field를 채우는 데 필요한 정보만 보존하며 raw provider payload를 envelope에 넣지 않는다.

같은 semantic key와 request hash는 stored adapter result와 기존 envelope mapping을 반환한다. 같은 key의 다른 input/response/policy hash는 `ADAPTER_IDEMPOTENCY_CONFLICT`다. Adapter success와 result row 사이의 crash는 둘 다 rollback되어야 하며 replay 때 strategy/provider를 재호출해 빈 row를 추정하지 않는다.

## 3. V12 Strategy Adapter와 ORB Baseline

V12 adapter는 registry 15개와 명시적으로 동결된 parameter set을 순회하며 v12 public `strategy()`, `validate_registry()`, `evaluate_gate()`와 candidate contract를 호출한다. `src/v12/fixture_factory.py`, `strategy_input_fixture.py`, `acceptance.build_path()`는 runtime path에서 금지한다.

`v20.strategy-adapter-request.1`은 invocation, typed v12 `StrategyInput` inventory, active parameter manifest, eligibility/risk references와 v19 plan namespace를 가진다. `v20.strategy-adapter-result.1`은 v12 candidate identity·side·score·feature/evidence hash, gate result, execution-feasible 여부와 mapped decision을 가진다.

- `long_orb_15m`은 최초 ORB baseline이며 v12의 range·window·entry·exit contract를 그대로 사용한다.
- ORB 외 14개는 v15 qualification 전까지 execution-producing primary가 아니라 격리된 shadow arm이다.
- Signal 없음 또는 eligibility failure는 synthetic trade가 아니라 explicit no-candidate evidence다. V20 integrated plan은 target symbol inventory를 고정하고 각 no-candidate symbol에 quantity 0의 `NO_TRADE` envelope 하나를 만들어 v19 intake를 완결한다. 이는 candidate를 생성하거나 다른 strategy로 대체하지 않는 producer-neutral 번역이다.
- Candidate의 quantity, gate inputs와 reference price mapping은 v11/v19 typed contract가 소유하며 adapter가 새 sizing·risk 규칙을 만들지 않는다.

## 4. V13 Router Adapter와 Recorded Replay

Router request schema `v20.router-adapter-request.1`은 같은 market/cutoff의 v12 execution-feasible candidate 전부, frozen router policy, prompt/model/schema identity, context artifact refs와 current durable circuit projection을 가진다.

Result schema `v20.router-adapter-result.1`은 per-candidate validation, deterministic/LLM percentile, composite 또는 quant-only score, veto/abstain, per-symbol selection/`NO_TRADE`, fallback reason, call outcome와 circuit transition을 가진다.

Acceptance와 replay는 recorded raw response bytes를 provider port에 반환한다. Validation, percentile, 80:20 score, quant fallback, selection과 circuit update는 실제 v13 code path가 수행하며 fixture가 expected selection을 반환하지 않는다. Stored successful/failed response를 replay할 때 provider call은 0회다.

Item failure는 해당 symbol quant-only, envelope/identity/timeout/provider/overflow failure는 해당 market·cutoff quant-only라는 v13 범위를 보존한다. Circuit은 시장별 session state이며 v13의 3회 연속 또는 최근 20회 20% 조건과 다음 공식 session reset만 사용한다. V20은 다른 threshold, retry 또는 cross-market breaker를 추가하지 않는다.

## 5. DecisionEnvelope Mapping과 Session Intake

`v20.decision-mapping.1`은 adapter result를 v19 `v19.decision-envelope.1`로 변환하는 유일한 mapping version이다.

| Adapter source | V19 mapping |
| --- | --- |
| candidate/selection identity | producer-neutral decision ID와 evidence refs |
| market/session/cutoff | plan namespace, watermark, ready time |
| long/short/none | v19/v11이 허용하는 `BUY|SELL|NO_TRADE` action |
| deterministic score | v19 deterministic score field |
| sizing/risk refs | v11-compatible gate inputs와 target quantity |
| producer identity | provenance-only contract name/version |

Mapping은 action 의미를 추정하지 않는다. V19이 지원하지 않는 short/margin 결과는 새 action으로 확장하지 않고 risk/intake 전 fail closed 한다. Mapped batch는 v19 canonical order와 all-or-nothing intake를 사용한다.

Adapter invocation/result, mapping receipt와 v19 intake receipt는 같은 SQLite transaction boundary에 있어야 한다. Fault 후 retry가 새로운 candidate/router decision ID를 만들거나 같은 result를 다른 arm/session에 재사용하면 안 된다.

Transaction 의미 단위는 분리해 고정한다.

| Unit | Atomic write set |
| --- | --- |
| producer intake | adapter invocation/result, mapping, v19 batch/intake receipt |
| paper execution | v19 risk/reservation/intent/fill과 v17 economic event/projection |
| session close | v19 marks/close/outcome과 해당 step receipt |
| mirror/lifecycle projection | committed close refs, mirror day, authorization check, lifecycle event/projection |
| lifecycle safety action | cancel/flatten의 v19/v17 effects와 v20 authorization/lifecycle event/projection |

앞 unit의 committed truth를 뒤 unit fault 때문에 되돌리지 않는다. 뒤 unit은 receipt가 없으면 durable predecessor head에서 재실행한다. 단, 각 unit 내부 fault는 표의 write set 전체를 rollback한다.

## 6. SQLite 소유권과 Projection

V20은 v19 global schema head `003` database에 forward-only global migrations `004_runtime_adapters.sql`, `005_router_runtime.sql`, `006_lifecycle.sql`을 순서대로 적용해 head `006`을 만든다. `schema_migrations`와 `PRAGMA user_version`은 선행 버전과 공유하며 v20-local ordinal로 다시 시작하지 않는다. 세 migration은 다음 durable 영역을 추가한다.

- `runtime_invocations`, `adapter_results`, `decision_mappings`
- `router_calls`, `router_circuit_events`, `router_circuit_projection`
- `mirror_bindings`, `lifecycle_events`, `lifecycle_projection`
- `authorization_checks`, `runtime_integration_idempotency`

Raw market fixture와 recorded response file은 immutable acceptance input일 뿐 durable runtime state가 아니다. V19 plan/run/intake/fill과 v17 account events는 각 버전 table의 소유권을 유지한다. V20 repository는 그 row를 복제하지 않고 ID/hash를 참조한다.

Lifecycle projection은 append-only event를 순서대로 replay해 재생성한다. Direct state update, event delete, JSON restore와 `portfolio.json` migration은 금지한다. Store open과 mutation 전 v17/v19 reconciliation, v20 event chain과 projection 일치를 확인한다.

## 7. Mirror와 실제 경제 효과

V15 `create_mirrors()`의 account/slot/position namespace와 동일-input isolation을 보존하되, mirror session 결과는 fixture가 만든 `MirrorLedger`나 `OperationBundle`에서 가져오지 않는다.

1. Comparison epoch에 ORB와 router용 독립 v17 account/arm namespace를 binding한다.
2. 같은 recorded market input을 두 arm의 실제 v12/v13 adapter에 전달한다.
3. 각 arm의 mapped envelope를 독립 v19 plan/run/intake/risk/fill/close에 제출한다.
4. V17 account events와 v19 fills/marks/close에서 일별 순비용 경제 효과를 재생한다.
5. Common official session series를 v15 paired/winner/rollback service에 typed input으로 전달한다.
6. Winner/rollback/kill/recovery decision과 evidence hash를 v20 lifecycle event로 append한다.

따라서 v15 `OperationSourceFixture`, `operation_fixture.py`, `fixtures.py`와 `build_operation_bundle()`은 runtime 또는 v20 acceptance의 mirror·winner 생성 경로가 아니다. Recorded input은 재현 가능한 원인이고, 결과는 실제 adapter와 session execution의 산출물이다.

## 8. Lifecycle 상태와 전이

V20은 v15 상태를 그대로 영속화한다.

```text
foundation_candidate -> foundation_ready
orb_candidate -> orb_holdout_passed -> orb_paper
strategies_candidate -> strategies_shadow
router_candidate -> router_shadow -> router_challenger -> router_primary
router_primary -> router_operational_rollback -> router_primary
router_primary -> router_performance_rollback -> router_retired
any_active -> kill_switch_active -> next_session|manual_recovery
```

Transition schema `v20.lifecycle-transition.1`은 transition ID, namespace, from/to state, effective session, manifest/policy identity, v14/v15 evidence refs, v17/v19 session/economic heads, authorization check ID, previous lifecycle hash와 transition hash를 가진다.

금지 전이는 state mutation 0건이다. Retired version 재활성화, holdout/qualification/winner gate 우회, router-before-ORB, operation recovery의 manifest drift와 paper-to-live 전이는 approval이 있어도 허용하지 않는다.

## 9. Lifecycle Authorization Predicate

모든 transition은 다음 단일 predicate를 통과해야 한다.

```text
authorized = state_edge_registered
          AND namespace_and_version_exact
          AND required_v14_v15_evidence_valid
          AND v17_v19_reconciled
          AND kill_scope_allows_transition
          AND (approval_not_required
               OR recorded_approval_exact_and_unconsumed_for_action)
```

Approval은 gate를 대체하지 않는다. Approval reference는 manifest hash, effective session, action/transition, reason, reviewer와 evidence hash에 exact binding되어야 한다. V20은 immutable approval record 자체를 수정하지 않고 검증 snapshot과 `(approval_ref, action_identity)` authorization binding만 `authorization_checks`에 기록한다. 같은 reference의 exact retry는 stored check이고 다른 action/session/manifest binding은 conflict다. Approval 생성·철회·상태 변경은 v21 소유다.

| Action/transition | Human approval requirement |
| --- | --- |
| 변경 없는 정상 session run | 불필요, v15 automatic path |
| `orb_holdout_passed → orb_paper` | v20 신규 승인 불필요, 유효한 v14 holdout approval/lease/history chain은 필수 |
| `strategies_candidate → strategies_shadow` | 불필요, v15 ORB qualification evidence 필수 |
| `router_candidate → router_shadow → router_challenger` | 불필요, v14 router gate와 ORB paper state 필수 |
| `router_challenger → router_primary` | 불필요, v15 mirror sample·winner evidence 필수 |
| operational/performance rollback 또는 kill activation | 불필요, safety transition은 즉시 수행 |
| loss kill의 다음 공식 session 해당 arm reset | 불필요, v15 automatic reset evidence 필수 |
| operation kill recovery 또는 같은-version operational rollback recovery | 필수, root cause 해소·replay 일치·unchanged manifest도 필수 |
| v15이 정의한 source fallback/data exception evidence 아래 session 실행 | 필수, v15 기존 data-exception approval rule의 번역 |
| strategy/parameter/risk/cost/router/prompt/model/schema 등 policy identity 변경 적용 | 필수이며 새 manifest면 별도 v14 full gate도 필수 |

Missing, mismatched, forged 또는 다른 action에서 소비된 approval은 `APPROVAL_REQUIRED` 또는 `APPROVAL_EVIDENCE_INVALID`다. V21 부재를 자동 승인으로 해석하지 않는다. Acceptance는 local recorded approval evidence port를 사용하며 `src.v21`을 import하지 않는다.

## 10. Rollback, Kill과 Recovery 연결

Operational rollback, performance rollback, 2% loss kill, symbol/arm/market/global operation kill, cancel/flatten과 recovery 조건은 v15 그대로다. V20은 실제 v19 intent/fill과 v17 projection을 trigger input으로 사용한다.

- Router operational rollback은 즉시 ORB primary를 다음 허용 action source로 복원한다. Same-version resume는 unchanged identity, deterministic replay와 approval이 모두 있어야 한다.
- Performance rollback은 v15 최근 20 common day·arm별 100 trades·CI upper bound 계약만 호출하며 해당 router version을 retired로 기록한다.
- Loss kill은 market·arm account의 v15 1분 MTM 2% rule을 사용하고 다른 arm/market에 전파하지 않는다.
- Operation kill scope는 v15 classifier가 반환한 isolated-symbol, market·arm, all-market-arms 또는 global 결과를 그대로 사용하며 범위를 증명하지 못할 때의 확대도 v15 classifier에 위임한다. V20이 별도 scope 순서나 분류 규칙을 구현하지 않는다.
- Kill 직후 pending intent cancel, new entry block, trusted next-1m flatten과 no-reentry를 v19/v17 transaction으로 기록한다.
- V13 circuit open은 quant-only이며 kill이 아니다. Manifest integrity failure는 fallback이 아니라 operation kill이다.

## 11. CLI 계약

| Command | 역할 |
| --- | --- |
| `run-strategies` | V12 typed strategy adapter를 plan/cutoff에 실행 |
| `run-router` | V13 mixed/quant router adapter를 caller-supplied recorded response로 실행; built-in network provider 없음 |
| `run-integrated-session` | Adapter→envelope→v19 paper session 실행 |
| `verify-lifecycle` | V17/v19/v20 reconciliation과 authorization read-only 검증 |
| `prd01-acceptance` | 15-strategy/ORB/shadow adapter acceptance |
| `prd02-acceptance` | Router replay/fallback/circuit acceptance |
| `prd03-acceptance` | Mirror/promotion/rollback/kill/recovery authorization acceptance |
| `prd04-acceptance` | Real-adapter multi-session/restart acceptance |
| `acceptance` | V20 standalone acceptance |

Canonical 명령은 `uv run python -m src.v20.cli acceptance`다. 성공은 exit 0, 계약상 invalid input/state는 exit 2, 내부 결함은 exit 1이다. Machine command는 canonical JSON 한 줄만 stdout에 출력한다.

## 12. Failure와 Mutation 계약

| Probe | Mutation | Required result |
| --- | --- | --- |
| `strategy_registry_drift` | 15개 inventory/grid 변경 | adapter failure, write 0건 |
| `strategy_fixture_builder_attempt` | fixture-built candidate 주입 | `UNSUPPORTED_SYNTHETIC_RESULT` |
| `orb_contract_drift` | window/stop/exit 변경 | v12 contract failure |
| `shadow_qualification_early` | 19 sessions/trades 또는 incident 주입 | transition failure |
| `adapter_duplicate_retry` | reopen 뒤 same invocation 반복 | stored result/envelope, rows 불변 |
| `adapter_payload_conflict` | same key input hash 변경 | `ADAPTER_IDEMPOTENCY_CONFLICT` |
| `router_recorded_replay_recall` | replay 중 provider 호출 | replay failure |
| `router_partial_item_bad` | 한 symbol item invalid | 해당 symbol만 quant-only |
| `router_envelope_bad` | response identity/hash 변경 | 해당 market/cutoff quant-only |
| `router_circuit_same_session_reset` | open 뒤 같은 session mixed 호출 | circuit failure |
| `router_circuit_cross_market` | KR failure로 US circuit 변경 | isolation failure |
| `direct_v19_producer_artifact` | raw v12/v13 artifact intake | unsupported input |
| `cross_arm_mapping` | ORB result를 router plan에 mapping | namespace mismatch |
| `synthetic_mirror_result` | fixture-built winner/economics 주입 | `UNSUPPORTED_SYNTHETIC_RESULT` |
| `mirror_shared_account` | ORB/router namespace 공유 | mirror isolation failure |
| `promotion_gate_bypass` | v14/v15 evidence 제거 | transition failure |
| `approval_missing_required` | operation recovery approval 제거 | `APPROVAL_REQUIRED` |
| `approval_forged_or_reused` | hash/action/session 변경 또는 재사용 | `APPROVAL_EVIDENCE_INVALID` |
| `approval_substitutes_gate` | approval만으로 holdout/winner 우회 | transition failure |
| `safety_transition_waits_approval` | rollback/kill을 approval 대기로 지연 | safety contract failure |
| `retired_router_reactivation` | performance-retired version 승격 | transition failure |
| `kill_scope_spread` | symbol incident를 market/global로 확대 | scope failure |
| `loss_reset_cross_arm` | 다음 session 다른 arm reset | isolation failure |
| `operation_recovery_manifest_drift` | changed hash로 same-version resume | recovery blocked |
| `crash_after_adapter_result` | mapping/intake 전 fault | v20/v19 전체 rollback |
| `crash_after_lifecycle_event` | projection/authorization 전 fault | event/projection 전체 rollback |
| `restart_each_session_step` | commit마다 reopen | baseline terminal hashes |
| `network_attempt` | socket/DNS/HTTP/vendor trap | 호출 0건 |
| `live_destination_attempt` | broker/credential/order 생성 | 호출·객체 0건 |
| `portfolio_mutation` | acceptance 전후 감시 | 존재·bytes·hash 불변 |
| `later_version_import` | v21/v22 import trap | import 0건 |

## 13. 의존성과 비목표

의존성은 Python 표준 라이브러리, v12~v15 producer/lifecycle public typed services, v16 runtime identity, v17 SQLite store, v19 session execution, v20 package와 local recorded inputs/responses다. 선행 CLI를 subprocess로 실행하지 않는다. Paper account/economic mutation은 명시적 temp 또는 configured SQLite에만 허용하며 `data/portfolio.json`을 포함한 모든 non-SQLite portfolio state는 읽기·쓰기·복구 입력이 아니다.

다음은 v20 비목표다.

- 새 strategy, parameter grid, metric, sample gate, promotion threshold, risk·cost·fallback business rule
- Human approval 발급·철회·목록·operator command와 approval UI; 이는 v21 소유
- Public CLI black-box qualification과 배포 호환성 suite; 이는 v22 소유
- Live broker, credential, real order, external acknowledgement와 network-required acceptance
- Web UI, multi-user, multi-host, daemon, scheduler와 distributed lease
- 새 vendor, model, strategy, metric, calendar 또는 adaptive learning
- Cross-currency/consolidated account, arm 간 capital sharing과 `data/portfolio.json` mutation

## 14. Acceptance Criteria

- V12의 15개 strategy·60개 registered parameter arm과 고정 registry가 fixture builder가 아닌 실제 typed evaluator로 실행되고 arm별 격리가 검증된다.
- ORB baseline과 14개 shadow activation이 v14/v15 qualification evidence와 정확히 연결된다.
- V13 router가 recorded response로 실제 validation·80:20/quant fallback·circuit path를 실행하고 replay에서 provider를 호출하지 않는다.
- Adapter output이 유일한 versioned mapping으로 v19 `DecisionEnvelope`가 되어 all-or-nothing intake와 paper execution을 통과한다.
- ORB/router 독립 v19 sessions의 v17 economic events에서 mirror paired series를 만들고 v15 winner/rollback/kill/recovery를 호출한다.
- SQLite만 invocation, circuit, lifecycle, authorization과 session recovery의 durable truth다.
- Authorization predicate가 approval-required transition과 즉시 safety transition을 구분하며 approval이 gate를 대체하지 않는다.
- V20은 approval을 발급·철회하지 않고 v21/v22 없이 recorded approval evidence로 standalone acceptance를 통과한다.
- Semantic retry, crash와 restart가 duplicate candidate, envelope, fill, lifecycle event 또는 economic effect를 만들지 않는다.
- Paper-only, deterministic replay, fail-closed와 market/currency/account/arm/session isolation을 지키고 `data/portfolio.json`을 변경하지 않는다.
