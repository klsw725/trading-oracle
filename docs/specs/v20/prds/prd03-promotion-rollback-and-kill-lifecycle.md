# PRD: v20 PRD 03 Promotion, Rollback And Kill Lifecycle
> **상태**: 📋 구현 예정
> 상위 SPEC: [v20 SPEC](../SPEC.md)

## 의존성

- [PRD 01](prd01-strategy-runtime-adapters.md)의 ORB/shadow runtime results
- [PRD 02](prd02-router-runtime-and-fallback.md)의 router/circuit results
- [v14 SPEC](../../v14/SPEC.md)과 [Holdout PRD](../../v14/prds/prd04-manifest-holdout-acceptance.md)의 qualification/verdict/approval-lease history
- [v15 SPEC](../../v15/SPEC.md), [Promotion PRD](../../v15/prds/prd01-approval-promotion-activation.md), [Mirror PRD](../../v15/prds/prd02-mirror-challenger-comparison.md), [Kill PRD](../../v15/prds/prd03-kill-switch-recovery.md), [Rollback PRD](../../v15/prds/prd04-rollback-report-acceptance.md)
- [v17 SPEC](../../v17/SPEC.md)의 append-only SQLite source of truth
- [v19 SPEC](../../v19/SPEC.md)의 session execution, marks, close와 reconciliation heads

## 목표

Actual ORB/router v19 session economics를 v15 mirror·winner·rollback·kill·recovery typed contract에 연결하고, 모든 lifecycle transition과 authorization decision을 v17 SQLite 위에 append-only로 영속화한다.

## 구현 표면

| 경로 | 책임 |
| --- | --- |
| `src/v20/lifecycle_models.py` | Lifecycle transition/evidence/authorization schemas |
| `src/v20/mirrors.py` | V17/V19 arm binding과 actual paired-series projection |
| `src/v20/lifecycle.py` | V15 gate/transition orchestration |
| `src/v20/authorization.py` | 단일 approval-required predicate와 evidence 검증 |
| `src/v20/lifecycle_repository.py` | Event append, projection replay와 idempotency |
| `src/v20/migrations/006_lifecycle.sql` | Global head `005`→`006`; mirror/lifecycle/authorization tables |

V20은 approval command, reviewer authentication, issue/revoke storage와 operator UI를 구현하지 않는다. 그 소유자는 v21이다.

## Mirror Binding Schema

`v20.mirror-binding.1`은 market, comparison epoch, ORB/router account·arm namespaces, equal initial NAV hash, market data/universe/risk/cost identities, v15 mirror hashes와 binding hash를 가진다.

Binding은 v15 `create_mirrors()`와 `verify_isolation()`을 호출해 만든다. ORB/router account, slot, position namespace는 모두 달라야 하고 shared evidence는 모두 같아야 한다. 기존 ORB operating ledger는 comparison series에 포함하지 않는다.

Mirror binding retry는 same IDs/hash를 반환한다. 다른 initial NAV, epoch, identity 또는 namespace로 같은 comparison identity를 재등록하면 `MIRROR_BINDING_CONFLICT`다.

## Actual Paired Economics

Mirror day schema `v20.mirror-day.1`은 common official session, 각 arm의 v19 plan/run/close IDs, v17 event/projection heads, decision/fill/cost counts, net daily return, completed trades, kill/circuit state와 evidence hash를 가진다.

Mirror day는 v19 close와 v17 replay에서 계산한다. 다음 경로는 금지한다.

- `src/v15/operation_fixture.py`와 `src/v15/fixtures.py`
- `OperationSourceFixture`에서 mirror economics/winner를 읽는 경로
- `build_operation_bundle()`로 synthetic session·trade·kill·rollback history를 생성하는 경로
- Expected P&L, winner, transition 또는 report fixture field

No-trade day와 loss-kill day를 common official series에서 제거하지 않는다. Missing arm close, event/projection mismatch와 market/session drift는 day append 전에 fail closed 한다.

## Lifecycle Transition Schema

`v20.lifecycle-transition.1`:

| Field | Contract |
| --- | --- |
| `transition_id` | canonical transition body hash |
| namespace | market, currency, account/arm or lifecycle scope |
| states | exact `from_state`, `to_state` |
| `effective_session` | v16 official session |
| identities | code/config/strategy/risk/cost/router/prompt/model/schema/manifest |
| evidence refs | v14/v15 gate와 v17/v19 runtime/economic heads |
| `authorization_check_id` | persisted predicate result |
| chain | previous lifecycle hash와 transition hash |

Lifecycle projection은 event replay로만 갱신한다. Current-state row를 직접 덮거나 history를 삭제하지 않는다.

## 상태 전이

```text
foundation_candidate -> foundation_ready
orb_candidate -> orb_holdout_passed -> orb_paper
strategies_candidate -> strategies_shadow
router_candidate -> router_shadow -> router_challenger -> router_primary
router_primary -> router_operational_rollback -> router_primary
router_primary -> router_performance_rollback -> router_retired
any_active -> kill_switch_active -> next_session|manual_recovery
```

전이별 evidence는 v14/v15 public typed verifier가 판정한다. V20은 pass/fail 값을 fixture에서 받거나 threshold를 재계산하는 대체 구현을 만들지 않는다. `authorize_transition()`은 verifier가 반환한 typed decision/hash, current SQLite heads와 approval clause를 결합하는 integration predicate일 뿐 v14/v15 gate·winner·rollback·kill classifier를 재구현하지 않는다.

## Promotion Evidence

| Transition | Required existing contract evidence |
| --- | --- |
| `orb_holdout_passed → orb_paper` | v14 validation/untouched holdout PASS, approval→lease→history chain, next official session |
| `strategies_candidate → strategies_shadow` | ORB paper, first post-gate 20 sessions, 30 completed trades, critical incident 0, sample hash |
| `router_candidate → router_shadow` | frozen v14 router development/validation/holdout evidence |
| `router_shadow → router_challenger` | ORB paper와 router gate/sample pass |
| `router_challenger → router_primary` | fresh mirror epoch, arm별 60 independent trading days·300 trades, v15 winner 3 conditions |

V20은 새 approval로 failed gate를 통과시키지 않는다. Market별 promotion은 독립이며 one market evidence를 다른 market/version에 재사용하지 않는다.

## Rollback Evidence

Operational rollback은 critical ledger/replay/reconciliation/risk invariant evidence가 있으면 즉시 `router_primary → router_operational_rollback`과 ORB primary 복귀를 기록한다. Approval을 기다리지 않는다.

Same-version `router_operational_rollback → router_primary`는 원인이 외부 운영 복구이고 code/config/prompt/model/schema/cost/strategy/risk/manifest hash가 모두 그대로이며 deterministic replay 일치와 exact manual approval evidence가 있어야 한다. Hash 하나라도 바뀌면 recovery는 금지하고 새 version의 v14 full gate가 필요하다.

Performance rollback은 v15 최근 20 common official days, 각 arm completed trades 100건 이상과 paired excess-return 95% CI upper bound `<= 0` typed result를 요구한다. Sample 미달은 hold이고, pass하면 ORB primary 복귀와 router version retirement를 원자적으로 기록한다. Retired version은 approval이 있어도 재활성화할 수 없다.

## Kill과 Recovery

Actual v17 account projection, v19 intents/fills/marks와 adapter integrity events를 v15 kill classifier에 전달한다.

| Trigger class | Scope |
| --- | --- |
| Isolated symbol data/action/borrow defect | 관련 market arms의 해당 symbol만 cancel/flatten |
| Arm ledger/reservation/reconciliation mismatch | 해당 market·arm |
| Shared calendar/source/universe/regulation failure | 해당 market의 모든 arms |
| Manifest/code/policy/common hash-chain failure | global paper system |

V20은 v15 kill classifier의 typed scope를 그대로 적용한다. Scope를 증명할 수 없을 때의 확대도 v15 service가 결정하며 v20 enum ordering이나 자체 escalation table은 없다. Acceptance는 v15 classifier output hash와 persisted scope가 field-by-field 같은지 검증하고, 과도하거나 축소된 scope를 모두 실패시킨다.

Loss kill은 market·arm prior-close NAV 대비 비용 포함 2% v15 rule을 호출한다. 해당 arm만 pending cancel, new entry block, trusted next-1m flatten과 same-day no-reentry를 수행하고 다음 official session에 자동 reset한다.

Operation kill은 root cause 해소, replay 일치와 manual approval 전까지 유지한다. Same-day recovery가 승인돼도 당일 재진입하지 않는다. V13 circuit open/quant-only는 kill이 아니지만 manifest mismatch는 global operation kill input이다.

## Authorization Predicate

`authorize_transition()`은 다음 predicate 하나만 구현한다.

```text
registered_edge
AND exact_current_state
AND exact_namespace_version_session
AND required_gate_evidence_verified
AND v17_v19_reconciliation_passed
AND no_blocking_kill_or_retirement
AND approval_clause
```

`approval_clause`는 action class가 automatic/safety이면 `NOT_REQUIRED`, manual이면 exact recorded approval evidence의 valid binding과 one-action consumption reference다.

| Action class | Approval clause |
| --- | --- |
| unchanged normal session | `NOT_REQUIRED` |
| ORB/strategy/router gate-based promotion | `NOT_REQUIRED`, 선행 v14 holdout approval chain은 evidence로 검증 |
| operational/performance rollback | `NOT_REQUIRED`, 즉시 safety transition |
| kill activation/cancel/flatten | `NOT_REQUIRED`, 즉시 safety transition |
| next-session loss reset | `NOT_REQUIRED` |
| operation kill manual recovery | `REQUIRED` |
| same-version operational rollback recovery | `REQUIRED` |
| source fallback/data exception session authorization | `REQUIRED` |
| policy identity change application | `REQUIRED`와 해당 시 새 v14 gate |

Approval evidence schema는 v15의 exact manifest hash, effective session, reason, reviewer, data exception/source hash와 action binding을 보존한다. V20은 caller가 제공한 immutable evidence를 검증하고 authorization snapshot/hash와 `(approval_ref, action_identity)` binding만 SQLite에 저장한다. Source approval record의 consumed/revoked/status 필드는 쓰지 않는다. Exact action retry는 stored binding이며 같은 approval ref의 다른 action/session/manifest 사용은 conflict다.

- Missing evidence: `APPROVAL_REQUIRED`
- Forged, stale, wrong action/session/manifest 또는 already-consumed binding: `APPROVAL_EVIDENCE_INVALID`
- Approval로 gate/retirement/manifest-drift 금지 조건 우회: `LIFECYCLE_TRANSITION_INVALID`
- V21 package 부재: manual action은 fail closed, automatic/safety action semantics는 변하지 않음

Acceptance는 recorded approval fixtures를 read-only port로 공급한다. Issuance와 revocation API는 없고 `src.v21` import도 없다.

## Transaction과 Idempotency

Transition transaction은 다음 순서다.

1. V17/V19/V20 reconciliation과 current lifecycle head 확인
2. Semantic transition key와 exact retry/conflict 판정
3. V14/V15 evidence typed verification
4. Authorization predicate와 approval evidence 검증
5. Safety transition이면 cancel/flatten의 v19/v17 economic writes 수행
6. Lifecycle event, authorization check와 projection append
7. All heads/economics/hash invariant 확인 후 commit

Safety-action unit의 fault는 cancel/flatten, v17 account event, v19 execution record와 v20 lifecycle event를 전부 rollback한다. 이미 완료된 일반 session fill/close를 입력으로 하는 mirror/lifecycle projection unit의 fault는 그 committed session을 되돌리지 않고 mirror day·authorization·lifecycle writes만 rollback한다. Exact retry는 각 unit의 stored result를 반환한다.

## Failure와 Mutation

| Probe | Mutation | Required result |
| --- | --- | --- |
| `synthetic_mirror_result` | prebuilt P&L/winner 전달 | unsupported synthetic result |
| `mirror_shared_account` | ORB/router namespace 공유 | mirror isolation failure |
| `mirror_missing_common_day` | no-trade/loss day 삭제 | paired-series failure |
| `promotion_gate_bypass` | holdout/qualification/winner ref 제거 | transition invalid |
| `approval_missing_required` | recovery approval 없음 | approval required, state 불변 |
| `approval_forged_or_reused` | hash/action/session 변경·재사용 | evidence invalid |
| `approval_substitutes_gate` | approval만으로 winner 우회 | transition invalid |
| `safety_transition_waits_approval` | rollback/kill 지연 | safety contract failure |
| `retired_router_reactivation` | retired version promote | transition invalid |
| `kill_scope_spread` | isolated symbol을 market/global kill | scope failure |
| `loss_reset_cross_arm` | next session 다른 arm reset | isolation failure |
| `operation_recovery_manifest_drift` | changed hash same version recovery | recovery blocked |
| `llm_circuit_as_kill` | quant-only circuit에 liquidation | classification failure |
| `crash_after_lifecycle_event` | projection 전 deterministic fault | all stores pre-hash |

## CLI

```bash
uv run python -m src.v20.cli verify-lifecycle --database data/paper/v17/paper.sqlite3
uv run python -m src.v20.cli prd03-acceptance
```

## 완료 조건

- Mirror economics가 actual v12/v13→v19→v17 path에서만 생성된다.
- V15 promotion/rollback/kill/recovery typed contract가 변경 없이 실행된다.
- V15 verifier/classifier output hash와 persisted transition/scope가 직접 대응하고 v20 predicate는 gate business rule을 중복 계산하지 않는다.
- Authorization predicate가 approval-required와 immediate safety action을 정확히 구분한다.
- Lifecycle event/projection/authorization이 SQLite replay로 재생성된다.

## 비목표

- Approval issue/revoke/list/operator command와 reviewer authentication
- 새 metric, bootstrap, sample, promotion·rollback·kill threshold
- Live broker liquidation과 credential
- Multi-host incident coordination
- V18 policy activation
