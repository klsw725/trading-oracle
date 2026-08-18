# Trading Oracle v19 SPEC: Market-Session Orchestration And Decision-to-Paper Execution
> **상태**: 📋 구현 예정

v19는 [v16](../v16/SPEC.md)의 검증된 runtime input과 [v17](../v17/SPEC.md)의 durable paper account 위에서 한 시장 session의 plan, lease, deterministic recommendation intake, v11 risk·sizing, reservation, intent와 paper fill을 SQLite transaction으로 오케스트레이션한다. Producer는 strict `DecisionEnvelope`만 제공하며 v19는 v12·v13 adapter나 multi-arm promotion을 구현하지 않는다.

## 0. 구현 완결성 계약

- v19는 v11·v16·v17 public contract, global ordinal continuity를 위한 v18 `002` migration asset과 v19 local fixture만 의존한다. V18 business API/table은 소비하지 않으며 v20 이후 runtime adapter를 import하거나 v12·v13 producer 실행을 요구하지 않는다.
- `uv run python -m src.v19.cli acceptance`는 임시 SQLite에서 session planning, lease contention/expiry, cutoff, missed-session policy, resume, recommendation intake, risk→reservation→intent→fill atomic commit, marks, close, reconciliation과 restart를 offline으로 실행하고 canonical JSON 한 줄과 exit 0을 낸다.
- 입력은 producer-neutral `DecisionEnvelope`다. Acceptance는 local fixture를 직접 전달하며 producer process, network, LLM, vendor와 strategy를 실행하지 않는다.
- 모든 execution은 paper-only다. Live broker route, credential, real order object와 external destination은 schema와 code path에 존재하지 않는다.
- SQLite는 session plan/run/lease, intake receipt, execution intent/fill, marks, close, reconciliation과 v17 account event의 유일한 durable truth다.
- 모든 deadline, lease와 close 판정은 caller가 제공한 `as_of`와 official calendar cutoff를 사용한다. Wall clock, sleep, process ID, random ID는 business identity를 바꾸지 않는다.
- Semantic retry는 stored result를 반환하고 conflict, stale lease, cutoff breach, reconciliation mismatch는 추가 mutation 전에 fail closed 한다.
- KR/US, KRW/USD, account, arm, session, policy/config version을 격리하고 cross-namespace netting, FX conversion과 result pooling을 하지 않는다.
- Acceptance는 tracked file과 `data/portfolio.json`의 존재·bytes·hash를 바꾸지 않으며 network가 없어도 완료된다.
- 이 조건과 아래 Acceptance Criteria가 모두 통과하면 v19는 v20 이후 producer adapter 없이 단독 완료다.

## Local PRD Map

| PRD | Local document | Implementation owner | Produces |
| --- | --- | --- | --- |
| PRD 01 | [Session Plan And Lease](prds/prd01-session-plan-and-lease.md) | `src/v19/session_plans.py`, `src/v19/leases.py`, `src/v19/runs.py` | immutable `SessionPlan`과 resumable `SessionRun` |
| PRD 02 | [Decision Envelope And Intake](prds/prd02-decision-envelope-and-intake.md) | `src/v19/decisions.py`, `src/v19/intake.py`, `src/v19/receipts.py` | producer-neutral accepted decision set |
| PRD 03 | [Risk Intent And Paper Fill](prds/prd03-risk-intent-and-paper-fill.md) | `src/v19/execution.py`, `src/v19/intents.py`, `src/v19/paper_fills.py` | atomic v17 account commit와 paper execution records |
| PRD 04 | [Session Close And Restart Acceptance](prds/prd04-session-close-and-restart-acceptance.md) | `src/v19/marks.py`, `src/v19/session_close.py`, `src/v19/acceptance.py`, `src/v19/cli.py` | reconciled close·run outcome와 standalone report |

PRD 01→04 순서로 구현한다. Plan/run/lease는 PRD 01, producer boundary와 intake identity는 PRD 02, risk부터 fill commit은 PRD 03, mark·close·reconciliation·run outcome·통합 restart 검증은 PRD 04만 소유한다.

## 1. 선행 버전과 v19 경계

- [v11](../v11/SPEC.md)은 risk gate, sizing, reservation, deterministic paper fill의 normative calculation contract를 제공한다. v19는 그 typed service를 호출하고 결과를 오케스트레이션하며 risk 규칙을 재정의하지 않는다.
- v16은 runtime, calendar와 market-input health identity를 제공한다. v19는 plan cutoff와 lineage를 binding하지만 source data를 다운로드하거나 health를 다시 계산하지 않는다.
- v17은 account namespace, event/idempotency transaction과 replay/reconciliation을 제공한다. v19의 fill commit은 같은 transaction에서 v17 reservation/cash/position event를 append한다.
- [v18](../v18/SPEC.md)의 advisory horizon outcome/candidate는 v19 execution의 입력도 출력도 아니다. v19 run outcome은 session operation 결과이며 recommendation correctness나 adaptive learning을 뜻하지 않는다.
- v20은 실제 v12~v15 runtime producer adapter를 `DecisionEnvelope` boundary에 연결한다. v19는 adapter interface나 producer-specific field mapping을 구현하지 않는다.

V19의 database prerequisite는 global schema head `002`다. Standalone acceptance는 v17 `001` 다음에 v18 `002_measurement.sql`을 storage migration으로 설치한 뒤 v19 `003_orchestration.sql`을 적용해 head `003`을 만든다. 이는 ordinal continuity와 shared-table constraints를 위한 schema bootstrap일 뿐이며 v19는 v18 business API를 import·호출하거나 measurement table을 읽고 쓰지 않는다. `schema_migrations`와 `PRAGMA user_version`은 v17~v21 공통 global head다.

## 2. SessionPlan Identity

`SessionPlan` schema는 `v19.session-plan.1`이고 다음을 가진다.

| Field | Contract |
| --- | --- |
| `plan_id` | canonical plan body의 `sha256:` hash |
| namespace | market, currency, account ID, arm ID |
| `session_date` | versioned official open session |
| `decision_cutoff` | recommendation intake deadline UTC |
| `execution_cutoff` | 새 intent 생성 deadline UTC |
| `mark_cutoff` | official close mark deadline UTC |
| `runtime_identity` | v16 validated bundle identity |
| versions | config, orchestration, risk, sizing, fill, missed-session policy |
| `expected_steps` | registered step ID의 고정 ordered tuple |
| `created_as_of` | caller-supplied canonical UTC timestamp |

Cutoff는 decision < execution ≤ official close ≤ mark 순서여야 한다. Plan identity는 random run token이나 lease owner를 포함하지 않는다. 같은 namespace/session에는 plan 하나만 허용하며 같은 body retry는 no-op, 다른 body는 `SESSION_PLAN_CONFLICT`다.

## 3. SessionRun과 Lease

Run schema는 `v19.session-run.1`이고 `run_id = hash(plan_id, attempt_ordinal)`이다. Attempt ordinal은 plan별 SQLite transaction에서 1부터 부여하며 gap이 없다. Resume는 기존 nonterminal run ID를 사용하고 새 run을 만들지 않는다.

| Run state | 허용 전이 |
| --- | --- |
| `PLANNED` | → `RUNNING`, `MISSED` |
| `RUNNING` | → `INTAKE_CLOSED`, `FAILED` |
| `INTAKE_CLOSED` | → `EXECUTING`, `FAILED` |
| `EXECUTING` | → `AWAITING_CLOSE`, `FAILED` |
| `AWAITING_CLOSE` | → `RECONCILING`, `FAILED` |
| `RECONCILING` | → `COMPLETED`, `FAILED` |
| `MISSED`, `COMPLETED`, `FAILED` | 없음 |

Lease schema `v19.session-lease.1`은 plan ID, lease generation, owner token hash, acquired `as_of`, expires `as_of`, last completed step와 row version을 가진다. SQLite `BEGIN IMMEDIATE` compare-and-swap으로 한 plan에 active lease 하나만 허용한다.

Owner token 원문은 durable state나 report에 저장하지 않는다. Explicit `as_of < expires_at`이면 다른 owner acquire는 `LEASE_HELD`; 같거나 이후면 generation을 1 증가시킨 takeover가 가능하다. Stale generation의 heartbeat, step commit, release는 `STALE_LEASE`다. Lease 획득 자체는 completed step을 되돌리거나 다시 실행하지 않는다.

## 4. Cutoff, Resume와 Missed Session

각 step은 시작 전 lease generation, run state, explicit `as_of`, plan cutoff와 semantic completion receipt를 확인한다. Step commit은 business writes와 completion receipt를 같은 transaction에 둔다.

| Condition | Versioned policy | Result |
| --- | --- | --- |
| decision cutoff 전 | 모든 policy | intake 허용 |
| decision cutoff 이상, intake 미완료 | `FAIL` | `DECISION_CUTOFF_MISSED`, run `FAILED` |
| decision cutoff 이상, intake 미완료 | `SKIP` | run `MISSED`, execution write 0건 |
| execution cutoff 이상, 새 intent 요청 | 모든 policy | `EXECUTION_CUTOFF_MISSED`, write 0건 |
| completed step resume | 모든 policy | stored receipt 반환, write 0건 |
| partial uncommitted step resume | 모든 policy | last committed step 다음부터 실행 |

Missed-session policy는 `v19.missed-session-policy.1`의 `FAIL|SKIP`만 허용한다. Catch-up execution, 다음 session 이월과 retrospective fill은 없다.

## 5. Producer-Neutral DecisionEnvelope

Schema `v19.decision-envelope.1`은 envelope ID, producer-neutral decision ID, plan ID, namespace/session, symbol/sector, `BUY|SELL|NO_TRADE`, target quantity, reference price minor units, decision cutoff, watermark, readiness timestamp, deterministic score, gate inputs, source evidence hashes와 producer contract name/version을 가진다.

Producer contract name/version은 provenance label일 뿐 dispatch key가 아니다. v19는 field mapping adapter, v12 bundle parser, v13 router importer, v14/v15 operation reader를 포함하지 않는다. 모든 producer는 boundary 밖에서 동일 envelope를 만들어야 한다.

Envelope ID는 strict body hash다. Intake batch schema `v19.decision-batch.1`은 plan ID, ordered unique envelopes, batch cutoff, batch hash를 가진다. Sorting은 market, symbol, decision ID 순이다.

## 6. Intake 계약

Intake는 lease/run/plan 확인→schema·namespace·lineage→cutoff/watermark/readiness→duplicate/conflict→batch completeness→immutable receipt commit 순서다.

| Decision | Intake result |
| --- | --- |
| Valid `BUY`/`SELL` | `ACCEPTED_FOR_RISK` |
| Valid `NO_TRADE` | `RECORDED_NO_TRADE`, execution 없음 |
| Exact semantic retry | stored receipt, write 0건 |
| Same decision identity, different body | `DECISION_IDENTITY_CONFLICT`, batch 전체 write 0건 |
| Late/stale/cross-namespace/unknown version | batch 전체 fail closed |

Partial batch acceptance는 없다. Unknown field와 action을 보존하거나 producer별 fallback으로 해석하지 않는다.

## 7. Risk, Sizing와 Reservation

Accepted trade decision을 v11 `Decision`, account snapshot과 `GateInputs`로 변환하는 mapping은 versioned `v19.v11-risk-mapping.1` 하나다. Risk/sizing result는 decision, account event head, marks/input hashes, risk·sizing policy version에 binding된다.

모든 gate가 pass한 accepted result만 reservation을 만든다. Blocked result는 immutable `risk.checked` record와 reason을 남기고 intent/fill/account mutation은 0건이다. Unknown gate, stale account head, negative/overflow quantity·cash, unsupported short/margin은 fail closed 한다.

Reservation ID는 plan/run/decision/risk result hash에서 결정한다. V17의 `reservation.placed` semantics를 사용하며 account·market·currency·arm을 바꾸어 재사용할 수 없다.

## 8. Intent와 Paper Fill Atomic Commit

`ExecutionIntent` schema는 `v19.execution-intent.1`, `PaperFill`은 `v19.paper-fill.1`이다. Intent ID는 decision, risk, reservation, execution policy와 target session hash다. Fill ID는 intent, deterministic fill policy, session market input hash에서 계산한다.

Paper fill은 v11 versioned simulation을 사용하며 external broker acknowledgement가 아니다. Fill price, quantity, costs와 status는 fixture market input과 policy로 결정하고 random partial fill이나 current quote fallback을 사용하지 않는다.

한 decision의 commit transaction은 다음 순서다.

1. Lease/run/cutoff와 v17 reconciliation 확인
2. Semantic execution key와 decision/risk/account head 확인
3. V17 reservation event append와 projection 적용
4. Immutable intent와 paper-fill record append
5. Fill 경제 효과에 맞는 v17 cash/position/reservation release event append
6. V17 account projection, v19 execution receipt와 both heads 갱신
7. Cross-store invariant와 hashes 확인 후 commit

단일 SQLite connection과 transaction을 사용한다. 단계 3~6 fault는 v17 event/idempotency/projection과 v19 reservation/intent/fill/receipt를 모두 rollback한다. Exact retry는 stored fill을 반환한다. 같은 key의 다른 fill은 `EXECUTION_IDEMPOTENCY_CONFLICT`다.

## 9. Marks, Close와 Reconciliation

Close mark schema `v19.close-mark.1`은 plan/session namespace, symbol, official session close, positive adjusted mark price minor units, currency, price version와 source hash를 가진다. Required held/filled symbol마다 정확히 하나여야 하며 nearest session 또는 stale quote fallback은 없다.

Close는 intake sealed, 모든 accepted trade decision terminal, execution cutoff 경과, required marks complete, active lease와 v17 reconciliation PASS를 요구한다. `SessionClose` schema `v19.session-close.1`은 opening/closing account hash, mark set hash, intent/fill counts, blocked/no-trade counts, last v17 event hash와 close policy를 저장한다.

Reconciliation은 plan→batch→decision→risk→reservation→intent→fill→v17 economic events→projection→marks→close 참조를 field-by-field 검증한다. Mismatch는 run을 `FAILED`로 기록할 수 있지만 forged close로 자동 repair하거나 후속 run으로 덮지 않는다.

## 10. Run Outcome Registration

`RunOutcome` schema `v19.run-outcome.1`은 run ID, terminal state, completed step receipts, accepted/blocked/no-trade/fill counts, close/reconciliation hashes와 explicit terminal `as_of`를 가진다. Reconciled `COMPLETED`, policy-driven `MISSED`, fail-closed `FAILED`를 한 번만 등록한다.

이 outcome은 운영 session 결과이며 recommendation horizon correctness, paper P&L score, adaptive candidate 또는 strategy promotion input이 아니다. v18 outcome table을 읽거나 쓰지 않는다.

## 11. Restart 계약

Process restart는 SQLite에서 plan, run, lease generation, step receipts와 durable heads를 읽고 먼저 v17/v19 reconciliation을 수행한다. Valid active lease가 남았으면 다른 owner는 대기하지 않고 `LEASE_HELD`를 반환한다. Expired lease takeover는 last completed step 다음에서 resume한다.

JSON report, in-memory queue, PID file, `data/portfolio.json`은 resume truth가 아니다. Committed step을 재실행해 duplicate fill을 만들거나 uncommitted step을 completed로 추정하지 않는다.

## 12. CLI 계약

| Command | 역할 |
| --- | --- |
| `plan-session` | Immutable plan 등록 |
| `run-session` | Plan lease 획득과 step orchestration |
| `resume-session` | Existing run을 durable receipt부터 재개 |
| `verify-session` | Read-only run/account reconciliation |
| `prd01-acceptance` | Plan·lease·cutoff·resume acceptance |
| `prd02-acceptance` | Decision envelope·intake acceptance |
| `prd03-acceptance` | Risk·intent·fill atomicity acceptance |
| `prd04-acceptance` | Close·restart·boundary acceptance |
| `acceptance` | v19 standalone acceptance |

Canonical 명령은 `uv run python -m src.v19.cli acceptance`다. 성공은 exit 0, 계약상 invalid input/state는 exit 2, 내부 결함은 exit 1이다. Machine command는 canonical JSON 한 줄을 stdout에 출력한다.

## 13. Failure와 Mutation 계약

| Probe | Mutation | Required result |
| --- | --- | --- |
| `session_plan_duplicate` | 같은 plan body 반복 | 같은 plan ID, row 불변 |
| `session_plan_conflict` | 같은 namespace/session cutoff 변경 | `SESSION_PLAN_CONFLICT` |
| `lease_contention` | expiry 전 두 owner acquire | 하나 성공, 하나 `LEASE_HELD` |
| `stale_lease_generation` | takeover 뒤 이전 owner commit | `STALE_LEASE`, write 0건 |
| `decision_cutoff_missed` | incomplete intake를 cutoff 뒤 실행 | versioned `FAILED` 또는 `MISSED` |
| `execution_cutoff_missed` | cutoff 뒤 새 intent | `EXECUTION_CUTOFF_MISSED` |
| `resume_completed_step` | committed step에서 restart | stored receipt, duplicate 0건 |
| `decision_duplicate_retry` | 같은 envelope/batch 반복 | stored receipts, rows 불변 |
| `decision_identity_conflict` | 같은 decision ID payload 변경 | `DECISION_IDENTITY_CONFLICT` |
| `cross_namespace_decision` | KR plan에 US/USD envelope | `DECISION_NAMESPACE_MISMATCH` |
| `stale_decision_watermark` | cutoff 뒤 watermark/readiness | `DECISION_STALE` |
| `producer_adapter_attempt` | v12/v13 artifact 직접 전달 | `UNSUPPORTED_PRODUCER_INPUT` |
| `risk_gate_bypass` | blocked decision에 intent 생성 | `RISK_NOT_ACCEPTED`, account 불변 |
| `reservation_overcommit` | available cash 초과 sizing | risk blocked, reservation 0개 |
| `fill_policy_drift` | intent 뒤 fill version/hash 변경 | `FILL_POLICY_MISMATCH` |
| `execution_duplicate_retry` | reopen 뒤 같은 execution | 같은 fill, economic event 불변 |
| `execution_payload_conflict` | 같은 key에 quantity/price 변경 | `EXECUTION_IDEMPOTENCY_CONFLICT` |
| `crash_after_reservation` | fill 전 deterministic fault | v17/v19 전체 rollback |
| `crash_after_fill` | projection/receipt 전 fault | v17/v19 전체 rollback |
| `missing_close_mark` | required symbol mark 삭제 | `CLOSE_MARK_INCOMPLETE` |
| `cross_session_mark` | 다른 session/market mark 주입 | `CLOSE_MARK_IDENTITY_MISMATCH` |
| `projection_drift_before_close` | v17 balance/position 변조 | reconciliation failure, close 금지 |
| `restart_after_each_step` | 모든 step 직후 reopen | terminal hash baseline과 동일 |
| `run_outcome_reevaluation` | terminal outcome body 변경 | `RUN_OUTCOME_IMMUTABLE` |
| `live_destination_attempt` | broker/credential/real order 생성 | 호출·객체 0건 |
| `portfolio_mutation` | acceptance 전후 portfolio 감시 | 존재·bytes·hash 불변 |
| `network_attempt` | socket/DNS/HTTP trap | 호출 0건 |
| `later_version_import` | v20 이후 import trap | import 0건 |

## 14. 의존성과 비목표

의존성은 Python 표준 라이브러리, v11 risk/sizing/fill public typed service, v16 runtime/calendar contract, v17 SQLite account transaction, v18 global migration `002` asset, v19 package와 local fixtures다. V18 business API/table은 사용하지 않고 v11/v16/v17/v18 CLI를 subprocess로 실행하지 않는다.

다음은 v19 비목표다.

- V12·v13·v14·v15 producer adapter와 실제 runtime producer 호출
- Multi-arm allocation, experiment qualification, winner 또는 strategy promotion
- Advisory recommendation correctness와 v18 policy candidate activation
- Live broker, credential, real order routing, external acknowledgement
- Web UI, multi-user, multi-host, daemon과 distributed lease
- 새 vendor, strategy, calendar 또는 network-required acceptance
- FX conversion, margin, short, tax reporting과 `data/portfolio.json` mutation

## 15. Acceptance Criteria

- Session plan/run identity, SQLite lease generation, cutoff와 missed-session policy가 deterministic하다.
- Restart는 durable step receipt 이후부터 resume하고 duplicate decision, reservation, intent와 fill을 만들지 않는다.
- Producer-neutral `DecisionEnvelope`와 batch가 strict·immutable·all-or-nothing intake를 가진다.
- V12/V13 producer artifact 직접 입력과 후속 adapter import를 거부한다.
- V11 risk/sizing, v17 reservation, intent와 paper fill의 경제 효과가 한 SQLite transaction으로 commit된다.
- Risk block, stale lease/cutoff, conflict와 reconciliation mismatch가 state 불변으로 fail closed 한다.
- Marks, session close, reconciliation과 run outcome이 restart 후 같은 hashes를 만든다.
- KR/US, currency, account, arm, session과 version namespace가 교차하지 않는다.
- Canonical acceptance가 offline·deterministic·paper-only이며 v20 이후를 import하지 않는다.
- SQLite만 resume/recovery truth이고 `data/portfolio.json`은 변하지 않는다.
