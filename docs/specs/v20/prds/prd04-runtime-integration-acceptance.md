# PRD: v20 PRD 04 Real-Adapter Multi-Session Integration Acceptance
> **상태**: 📋 구현 예정
> 상위 SPEC: [v20 SPEC](../SPEC.md)

## 의존성

- [PRD 01](prd01-strategy-runtime-adapters.md)
- [PRD 02](prd02-router-runtime-and-fallback.md)
- [PRD 03](prd03-promotion-rollback-and-kill-lifecycle.md)
- [v12](../../v12/SPEC.md) actual strategy runtime과 immutable recorded market inputs
- [v13](../../v13/SPEC.md) actual router runtime과 recorded raw responses
- [v14](../../v14/SPEC.md)/[v15](../../v15/SPEC.md) recorded qualification·approval evidence와 typed lifecycle services
- [v16](../../v16/SPEC.md) calendar/runtime identities, [v17](../../v17/SPEC.md) temp SQLite, [v19](../../v19/SPEC.md) session execution services

## 목표

Actual V12/V13 adapters가 생성한 decisions로 ORB/router 독립 v19 sessions를 여러 공식 거래일 실행하고, restart·fallback·promotion·rollback·kill/recovery까지 SQLite에서 재현해 v21/v22 없이 standalone offline acceptance를 증명한다.

## 구현 표면

| 경로 | 책임 |
| --- | --- |
| `src/v20/session_integration.py` | Adapter result→v19 plan/intake/execution atomic orchestration |
| `src/v20/recorded_inputs.py` | Raw market/context/response/approval evidence strict loader |
| `src/v20/reconciliation.py` | V17/V19/V20 cross-version graph/economics 검증 |
| `src/v20/restart.py` | Durable receipt/head 이후 multi-session resume |
| `src/v20/acceptance.py` | Baseline, scenarios, exact mutation inventory와 report |
| `src/v20/boundaries.py` | Synthetic builder/network/live/portfolio/later-import traps |
| `src/v20/cli.py` | PRD별·canonical acceptance entrypoint |

## Acceptance Input Contract

Local fixture inventory는 다음 immutable 원인만 가진다.

- V16-validated KR/US official sessions, cutoffs와 runtime identities
- Complete point-in-time bars, eligibility, borrow/regulation, context artifacts와 source hashes
- V12 active parameter manifests와 V14 frozen verdict/evidence artifacts
- V13 prompt/model/schema/policy identities와 recorded raw response bytes
- V15 qualification, holdout approval chain와 recovery approval evidence records
- Opening paper cash와 deterministic v11/v19 risk/fill/mark inputs
- Deterministic fault checkpoint IDs

Fixture에는 candidate, deterministic/LLM percentile, router selection, envelope, fill, daily return, mirror day, winner, transition, kill scope, recovery result 또는 expected report hash를 넣지 않는다. Expected mutation code와 invariant만 acceptance code inventory가 소유한다.

## 실제 Adapter Multi-Session Flow

각 official session은 다음 public service path를 실행한다.

```text
recorded raw market/context input
-> v16 identity/calendar validation
-> actual v12 strategy adapter
-> actual v13 router adapter or stored-response replay
-> v20 decision mapping
-> v19 plan/run/lease and all-or-nothing intake
-> v11 risk/fill through v19
-> v17 account events/projection
-> v19 marks/close/reconciliation/outcome
-> v20 mirror day projection
-> v15 promotion/rollback/kill/recovery typed decision
-> v20 lifecycle event/projection
```

ORB baseline과 router challenger는 same session input을 사용하지만 별도 account/arm/plan/run/lease/intake/reservation/intent/fill/close를 가진다. 한 arm의 result나 account snapshot을 다른 arm에 복사하지 않는다.

## Synthetic V15 경로 제거 증명

Baseline과 모든 scenario에서 다음 import/call count는 0이어야 한다.

- `src.v15.operation_fixture`
- `src.v15.fixtures`
- `src.v15.operation_build.build_operation_bundle`
- `OperationSourceFixture`를 이용한 lifecycle/mirror generation
- V12 fixture candidate/gate builder

대신 acceptance report는 실제 호출 증거를 포함한다.

- V12 strategy evaluator coverage 15·registered parameter-arm coverage 60과 invocation/result hashes
- V13 validator/scorer/fallback/replay call records와 provider call count
- V19 plan/run/intake/fill/close IDs per arm/session
- V17 event/projection heads per account/arm
- V15 mirror/winner/rollback/kill/recovery verifier·classifier typed service input/output hashes와 persisted decision/scope equality
- V20 lifecycle/authorization heads

## Scenario Inventory

Standalone acceptance는 최소 다음 deterministic scenario를 실행한다.

1. ORB holdout evidence에서 market별 ORB paper activation과 no-signal의 exact `NO_TRADE`/trade sessions
2. ORB qualification hold와 exact pass 뒤 14-strategy shadow activation
3. V13 허용 6개 frozen policy, valid recorded Codex mixed route, item-level quant fallback, market·cutoff fallback와 circuit open/next-session reset
4. Router shadow→challenger와 same-input isolated ORB/router mirror sessions
5. V15 sample/winner evidence가 충족된 router primary transition
6. Critical invariant incident의 immediate operational rollback과 approved same-version recovery
7. Actual rolling paired economics의 performance rollback과 retirement
8. Market·arm 2% loss kill, next-session isolated reset
9. Symbol, arm, market와 global operation kill scopes와 approved manual recovery
10. Every named commit 직후 connection close/reopen과 exact retry

Scenario session/trade 수와 statistics는 v14/v15 contract의 recorded evidence/actual generated rows를 사용한다. Acceptance 편의를 위한 축소 threshold나 fast-path가 없다.

## Atomic Session Integration

한 producer session step은 다음 transaction boundary를 가진다.

1. Current v17/v19/v20 reconciliation, plan/run/lease와 lifecycle authorization 확인
2. Adapter semantic key 조회와 actual V12/V13 execution 또는 stored result 반환
3. Adapter result와 decision mapping append
4. V19 all-or-nothing intake와 step receipt append
5. Commit 후 다음 v19 risk/fill step으로 진행

Lifecycle decision과 append의 단일 owner는 PRD 03 `lifecycle.py`/repository다. PRD 04는 그 public service를 호출하고 결과를 검증할 뿐 transition을 별도로 구현하거나 append하지 않는다.

Lifecycle safety action transaction은 PRD 03 순서를 사용한다. Adapter와 intake 사이 crash는 result/mapping/intake를 전부 rollback한다. 일반 session의 v19 fill/close가 commit된 뒤 mirror/lifecycle projection unit에서 fault가 나면 committed session은 유지하고 uncommitted mirror day·authorization·lifecycle rows만 rollback한다. Resume는 close head부터 PRD 03 service를 다시 호출하며 mirror/lifecycle duplicate를 만들지 않는다. Cancel/flatten을 포함한 safety-action unit 내부 fault는 v17/v19/v20 safety write 전체를 rollback한다.

## Restart E2E

Baseline은 uninterrupted multi-session run이다. Restart scenario는 adapter result, mapping, intake, risk, reservation, fill, account projection, close, mirror day, authorization check와 lifecycle event commit 경계마다 connection을 닫고 새 owner와 explicit `as_of`로 연다.

Reopen은 SQLite migration/events/projections, v19 lease/step receipts와 V20 heads를 먼저 reconcile한다. Active lease는 `LEASE_HELD`, expired lease는 generation takeover 뒤 last committed receipt 다음부터 resume한다.

각 restart scenario는 baseline과 다음이 같아야 한다.

- Adapter result, decision/envelope/batch와 call/circuit hashes
- V17 account event/projection heads와 economic row counts
- V19 intent/fill/close/outcome hashes
- Mirror day/paired series와 lifecycle/authorization heads
- Final canonical acceptance report hash

## Exact Failure와 Mutation Inventory

| ID | Expected code/result | State invariant |
| --- | --- | --- |
| `strategy_registry_drift` | strategy adapter failure | all store pre-hash |
| `strategy_fixture_builder_attempt` | `UNSUPPORTED_SYNTHETIC_RESULT` | imports/writes 0 |
| `orb_contract_drift` | v12 contract failure | decision 0 |
| `shadow_qualification_early` | transition hold/failure | shadow executions 0 |
| `adapter_duplicate_retry` | stored result/mapping | rows 불변 |
| `adapter_payload_conflict` | `ADAPTER_IDEMPOTENCY_CONFLICT` | all store pre-hash |
| `router_recorded_replay_recall` | replay failure if called | provider call 0 |
| `router_partial_item_bad` | symbol quant-only | other symbols mixed |
| `router_envelope_bad` | market·cutoff quant-only | no partial mixed result |
| `router_circuit_same_session_reset` | circuit failure | provider call 0 |
| `router_circuit_cross_market` | isolation failure | other market head 불변 |
| `direct_v19_producer_artifact` | unsupported producer input | intake 0 |
| `cross_arm_mapping` | namespace mismatch | target arm rows 0 |
| `synthetic_mirror_result` | `UNSUPPORTED_SYNTHETIC_RESULT` | lifecycle writes 0 |
| `mirror_shared_account` | mirror isolation failure | binding 0 |
| `promotion_gate_bypass` | transition invalid | lifecycle head 불변 |
| `approval_missing_required` | `APPROVAL_REQUIRED` | recovery write 0 |
| `approval_forged_or_reused` | `APPROVAL_EVIDENCE_INVALID` | authorization/lifecycle head 불변 |
| `approval_substitutes_gate` | transition invalid | state 불변 |
| `safety_transition_waits_approval` | immediate safety expected | rollback/kill committed |
| `retired_router_reactivation` | transition invalid | retired state 유지 |
| `kill_scope_spread` | scope failure | unaffected namespaces 불변 |
| `loss_reset_cross_arm` | isolation failure | other arm kill state 유지 |
| `operation_recovery_manifest_drift` | recovery blocked | killed/rollback state 유지 |
| `crash_after_adapter_result` | deterministic rollback | v20/v19 pre-hash |
| `crash_after_lifecycle_event` | deterministic rollback | action/event/projection pre-hash |
| `restart_each_session_step` | baseline terminal hashes | duplicates 0 |
| `network_attempt` | call 0 | acceptance continues |
| `live_destination_attempt` | call/object 0 | tracked/DB state invariant |
| `portfolio_mutation` | mutation 0 | 존재·bytes·hash 불변 |
| `later_version_import` | import 0 | v21/v22 독립 PASS |

Mutation ID set은 [v20 SPEC](../SPEC.md)의 Failure와 Mutation 표와 정확히 같아야 한다. 누락, duplicate, skip, unexpected success 또는 expected failure의 state drift는 acceptance failure다.

## Acceptance Database와 Fault

각 scenario는 OS temp root의 독립 v19 global schema head `003` SQLite fixture에서 시작해 v20 global migrations `004`→`005`→`006`을 적용한다. `schema_migrations`, `PRAGMA user_version`, required PRAGMA, migration hash, event chains와 projections를 매 reopen마다 검증한다.

Mutation은 temp database와 immutable input copy에만 적용한다. Fault는 named deterministic exception이며 sleep, signal race, wall clock, random failure와 OS process kill 확률을 사용하지 않는다.

SQLite 외 report/cache는 resume input이 아니다. Temp root path, rowid, lease owner token, current timestamp와 random value는 report identity에 포함하지 않는다.

## Hard Boundary

- Socket, DNS, HTTP, vendor SDK와 credential access 0건
- Broker client, live destination, real order와 external acknowledgement 객체 0건
- `src.v21`, `src.v22`와 이후 package import 0건
- Approval issue/revoke command 또는 approval-store mutation 0건
- V12/v15 synthetic candidate/mirror/lifecycle fixture builder import/call 0건
- V18 outcome/candidate table read/write 0건
- `data/portfolio.json`과 모든 non-SQLite portfolio state, tracked config/input/fixture의 존재·bytes·hash 불변; paper economics mutation은 temp SQLite에만 존재

## Report 계약

Schema `v20.acceptance.1`은 version/status, adapter/mapping/circuit/lifecycle schema versions, actual-call inventory, scenarios, mutations, boundaries, per-market/arm/session V17/V19/V20 terminal heads와 report hash를 가진다.

Array는 stable ID 오름차순이다. Approval evidence는 reviewer 원문이나 secret이 아니라 reference/hash와 authorization result만 보고한다. Recorded raw response body와 owner token도 report에 포함하지 않는다.

모든 actual-call check, scenario, 31개 mutation과 hard boundary가 PASS이고 temp cleanup·portfolio/tracked-state 불변이 확인될 때만 top-level PASS와 exit 0이다. 같은 recorded inputs의 두 실행은 byte-identical stdout을 만든다.

## CLI

```bash
uv run python -m src.v20.cli prd04-acceptance
uv run python -m src.v20.cli acceptance
```

Canonical 명령은 다음 하나다.

```bash
uv run python -m src.v20.cli acceptance
```

## Acceptance Criteria

- Actual V12 evaluator와 V13 router code path가 recorded raw inputs/responses에서 decisions를 생성한다.
- Synthetic V12 candidate와 V15 mirror/operation bundle builder의 import/call이 0건이다.
- ORB/router independent sessions가 v19 execution과 v17 account economics를 실제로 생성한다.
- V14/V15 evidence가 promotion/rollback/kill/recovery에 그대로 적용되고 새 threshold가 없다.
- Approval-required recovery와 automatic/safety transition이 exact predicate로 구분된다.
- Every-step restart와 fault 뒤 terminal hashes/row counts가 uninterrupted baseline과 같다.
- Network/live/later-version/portfolio boundary가 모두 지켜진다.
- `uv run python -m src.v20.cli acceptance`가 v21/v22 없이 offline exit 0과 canonical JSON 한 줄을 낸다.

## 완료 조건

- Multi-session lifecycle 전체가 SQLite만으로 replay/reconcile된다.
- Acceptance fixture는 원인 input/response/evidence만 제공하고 business result를 만들지 않는다.
- Runtime adapter ownership, lifecycle authorization과 failure mutation 경계가 report에서 증명된다.

## 비목표

- V21 operator commands와 human approval issue/revoke records
- V22 public CLI black-box qualification
- Live broker/network smoke test와 credential
- Web UI, daemon, scheduler, multi-user/multi-host failover
- 새 strategy/vendor/model/metric/threshold/business rule
