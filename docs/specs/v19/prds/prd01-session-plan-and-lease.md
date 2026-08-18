# PRD: v19 PRD 01 Session Plan And Lease
> **상태**: 📋 구현 예정
> 상위 SPEC: [v19 SPEC](../SPEC.md)

## 의존성

- [v16 SPEC](../../v16/SPEC.md)의 official calendar, runtime/config identity
- [v17 SPEC](../../v17/SPEC.md)의 SQLite transaction과 reconciliation public contract
- v19 local session·cutoff·lease fixtures

## 목표

Market session별 immutable plan/run identity와 SQLite lease를 만들고, cutoff·missed-session·resume를 explicit `as_of`와 durable step receipt로 결정한다.

## 구현 표면

| 경로 | 책임 |
| --- | --- |
| `src/v19/session_models.py` | `SessionPlan`, `SessionRun`, `SessionLease`, failure types |
| `src/v19/session_plans.py` | Plan canonical identity와 conflict 검증 |
| `src/v19/leases.py` | SQLite lease CAS, heartbeat, takeover, release |
| `src/v19/runs.py` | Run state machine과 durable step receipts |
| `src/v19/missed_sessions.py` | Versioned `FAIL`/`SKIP` cutoff policy |
| `src/v19/migrations/003_orchestration.sql` | Global head `002`→`003`; plan/run/lease/step tables |

## Plan 계약

`v19.session-plan.1`은 namespace, official session date, decision/execution/mark cutoffs, runtime/config/orchestration/risk/sizing/fill/missed policy versions, ordered expected step IDs와 `created_as_of`를 요구한다.

Cutoff는 official calendar에 binding되고 decision < execution ≤ close ≤ mark다. `plan_id`는 canonical body hash다. Namespace/session unique constraint 아래 exact retry는 no-op, 다른 body는 `SESSION_PLAN_CONFLICT`다.

## Run State

| Current | Command | Next |
| --- | --- | --- |
| `PLANNED` | start | `RUNNING` |
| `PLANNED` | skip missed | `MISSED` |
| `RUNNING` | seal intake | `INTAKE_CLOSED` |
| `INTAKE_CLOSED` | begin execution | `EXECUTING` |
| `EXECUTING` | execution terminal | `AWAITING_CLOSE` |
| `AWAITING_CLOSE` | begin reconciliation | `RECONCILING` |
| `RECONCILING` | reconciled | `COMPLETED` |
| nonterminal | fail closed | `FAILED` |

Terminal state는 재개·변경하지 않는다. `run_id`는 plan ID와 SQLite-assigned gapless attempt ordinal hash다. Resume는 run ID를 유지한다.

## Lease 계약

Acquire는 `BEGIN IMMEDIATE`에서 row를 읽고 active 여부와 generation을 판정한다. Lease row는 owner token hash, acquired/expires `as_of`, generation, row version과 last completed step을 가진다.

| Operation | Preconditions | Result |
| --- | --- | --- |
| acquire empty | valid plan/run | generation 1 lease |
| acquire active | `as_of < expires_at` | `LEASE_HELD`, write 0건 |
| takeover expired | `as_of >= expires_at` | generation +1 |
| heartbeat | owner hash와 generation current | explicit expiry 갱신 |
| commit step | current lease, expected prior step | business write와 receipt atomic |
| release | current lease | released marker append |

Stale owner/generation은 `STALE_LEASE`다. Lease expiry는 caller `as_of`로만 비교하며 sleep, monotonic clock 또는 database current timestamp를 사용하지 않는다.

## Cutoff와 Missed Session

`v19.missed-session-policy.1`은 `FAIL`과 `SKIP`만 등록한다. Decision cutoff 전에 intake를 시작하지 못한 run은 policy에 따라 `FAILED` 또는 `MISSED`가 되고 execution write는 0건이다. Execution cutoff 뒤 새 intent는 항상 금지한다.

Catch-up, next-session carry, retrospective timestamp와 cutoff extension은 없다. Policy version을 plan 생성 뒤 바꾸면 plan conflict다.

## Resume 계약

Step receipt `v19.step-receipt.1`은 run/plan ID, step ID, input/output hash, lease generation과 committed account/execution heads를 가진다. Completed step exact retry는 stored receipt를 반환한다. Uncommitted fault는 receipt가 없으므로 takeover 후 해당 step을 다시 시작한다.

Resume 전 v17 store와 v19 orchestration table reconciliation을 수행한다. JSON report, PID file와 in-memory status로 step을 건너뛰지 않는다.

## Failure 계약

| Code | 조건 |
| --- | --- |
| `SESSION_PLAN_CONFLICT` | 같은 namespace/session의 다른 plan body |
| `SESSION_CALENDAR_INVALID` | closed session 또는 cutoff/calendar mismatch |
| `LEASE_HELD` | unexpired lease에 다른 owner acquire |
| `STALE_LEASE` | stale owner/generation heartbeat·commit·release |
| `RUN_TRANSITION_INVALID` | 상태표 밖 전이 |
| `DECISION_CUTOFF_MISSED` | policy `FAIL`의 late intake |
| `SESSION_MISSED` | policy `SKIP`의 terminal no-execution result |
| `EXECUTION_CUTOFF_MISSED` | cutoff 뒤 새 intent |
| `STEP_RECEIPT_CONFLICT` | completed step의 다른 input/output |

## CLI

```bash
uv run python -m src.v19.cli plan-session --input session-plan.json --database data/paper/v17/paper.sqlite3
uv run python -m src.v19.cli resume-session --run-id sha256:... --as-of 2026-01-05T21:00:00Z --database data/paper/v17/paper.sqlite3
uv run python -m src.v19.cli prd01-acceptance
```

## Acceptance와 Mutation

| Probe | Mutation | Required result |
| --- | --- | --- |
| `plan_retry_conflict` | same/different body 반복 | no-op/conflict 구분 |
| `lease_contention` | 두 owner 동시 CAS | active lease 하나 |
| `lease_expiry_takeover` | exact expiry 전·정각 acquire | held/takeover 경계 |
| `stale_generation` | old owner step commit | write 0건 |
| `missed_policy` | decision cutoff 뒤 FAIL/SKIP | exact terminal state |
| `execution_cutoff` | late intent | write 0건 |
| `resume_receipt` | every step 뒤 reopen | completed step 중복 0건 |

## 완료 조건

- Plan/run/lease identity와 transition이 SQLite state로 재현된다.
- Explicit `as_of`만 lease와 cutoff를 결정한다.
- Resume가 durable last step 이후에서 시작하고 semantic duplicate를 만들지 않는다.
- Multi-host/distributed coordination 없이 single-host fail-closed contract를 지킨다.

## 비목표

- OS scheduler, cron, daemon, queue worker
- Distributed lock, multi-host lease, leader election
- Missed session catch-up·carry-forward
- Decision producer와 execution economics
