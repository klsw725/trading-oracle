# PRD: v19 PRD 03 Risk Intent And Paper Fill
> **상태**: 📋 구현 예정
> 상위 SPEC: [v19 SPEC](../SPEC.md)

## 의존성

- [PRD 01](prd01-session-plan-and-lease.md)의 current execution lease와 cutoff
- [PRD 02](prd02-decision-envelope-and-intake.md)의 immutable accepted trade receipt
- [v11 SPEC](../../v11/SPEC.md)의 risk, sizing, reservation와 deterministic paper fill contract
- [v17 SPEC](../../v17/SPEC.md)의 account event/idempotency/projection transaction

## 목표

Accepted decision에 v11 risk·sizing을 적용하고 reservation, execution intent, deterministic paper fill과 v17 account 경제 효과를 한 SQLite transaction으로 commit한다.

## 구현 표면

| 경로 | 책임 |
| --- | --- |
| `src/v19/risk_mapping.py` | DecisionEnvelope→v11 typed risk input mapping |
| `src/v19/execution.py` | Gate orchestration과 cross-store transaction |
| `src/v19/intents.py` | Immutable `ExecutionIntent` identity·repository |
| `src/v19/paper_fills.py` | V11 fill policy 호출과 immutable fill receipt |
| `src/v19/account_commit.py` | V17 reservation/cash/position event atomic append |
| `src/v19/faults.py` | Named commit-checkpoint fault injection |

## Risk와 Sizing 계약

Mapping schema `v19.v11-risk-mapping.1`은 decision ID, account projection/head, market-input hash, reference price, quantity, gate inputs, risk/sizing policy versions를 v11 typed request에 binding한다. V19는 gate threshold나 sizing formula를 재정의하지 않는다.

| Risk result | Required effect |
| --- | --- |
| `accepted` | bounded quantity와 reservation으로 intent 단계 진행 |
| `blocked` | immutable reason receipt, reservation/intent/fill/account write 0건 |
| unknown/incomplete | fail closed, write 0건 |

Available cash, concentration, market hours, freshness, daily loss, kill switch와 accounting consistency를 모두 평가한다. Gate bypass, quantity increase after acceptance와 stale account head는 허용하지 않는다.

## Reservation 계약

Reservation ID는 run, decision, risk result, v17 account head와 policy hashes의 canonical identity다. V17 `reservation.placed` event와 projection을 사용한다. Reservation amount는 accepted sizing의 cash+cost bound와 정확히 일치한다.

Account, market, currency, arm 또는 decision을 바꾼 reuse는 conflict다. Available cash를 초과하면 risk blocked이며 reservation row를 먼저 만들었다가 해제하는 보상 transaction을 사용하지 않는다.

## Intent Schema와 상태

`v19.execution-intent.1`은 intent ID, decision/risk/reservation IDs, namespace/session, action, quantity, reference price, execution cutoff, policy versions와 input hashes를 가진다.

| State | 허용 전이 |
| --- | --- |
| `RESERVED` | → `FILL_SIMULATED`, `CANCELLED` |
| `FILL_SIMULATED` | → `COMMITTED` |
| `CANCELLED` | 없음 |
| `COMMITTED` | 없음 |

Intent body와 terminal state는 update하지 않고 state event를 append한다. Live destination, broker order ID와 acknowledgement field는 schema에 없다.

## Paper Fill 계약

`v19.paper-fill.1`은 fill ID, intent ID, target session/time, requested/filled/cancelled integer quantity, minor-unit price와 costs, `PARTIAL|COMPLETE|CANCELLED`, fill policy와 market-input hash를 가진다.

V11 deterministic simulator를 사용하고 random partial fill, current network quote 또는 retry attempt count를 입력으로 사용하지 않는다. Unsupported short/margin과 policy/input drift는 fill 생성 전에 실패한다.

## Atomic Commit

단일 `BEGIN IMMEDIATE` transaction의 write set은 다음이다.

- V17 semantic idempotency, reservation event와 projection
- V19 risk receipt, reservation binding, intent와 state event
- V19 fill과 execution receipt
- V17 fill 경제 효과를 표현하는 cash/position/reservation-release events와 projection checkpoint
- V19 step receipt와 execution head

모든 hash와 account invariant를 확인한 뒤에만 commit한다. Fault 또는 reconciliation mismatch는 전 write set을 rollback한다. V17과 V19를 별도 connection/transaction으로 나누거나 compensating event로 partial commit을 숨기지 않는다.

## Idempotency와 Failure 계약

| Code/result | 조건 | State |
| --- | --- | --- |
| stored fill | same execution key/request hash | write 0건 |
| `RISK_NOT_ACCEPTED` | blocked/unknown gate에서 intent 요청 | account 불변 |
| `ACCOUNT_HEAD_STALE` | risk binding 뒤 v17 head 변경 | 전체 rollback |
| `RESERVATION_OVERCOMMITTED` | accepted amount가 available 초과 | 전체 rollback |
| `EXECUTION_CUTOFF_MISSED` | cutoff 뒤 새 intent | write 0건 |
| `FILL_POLICY_MISMATCH` | intent와 fill version/input drift | write 0건 |
| `EXECUTION_IDEMPOTENCY_CONFLICT` | same key, different quantity/price/body | write 0건 |
| `PAPER_ONLY_BOUNDARY` | live destination/broker object 요청 | write 0건 |
| `EXECUTION_RECONCILIATION_FAILED` | v17/v19 heads 또는 economics mismatch | quarantine, further writes 0건 |

## CLI

```bash
uv run python -m src.v19.cli prd03-acceptance
uv run python -m src.v19.cli verify-session --run-id sha256:... --database data/paper/v17/paper.sqlite3
```

## Acceptance와 Mutation

| Probe | Mutation | Required result |
| --- | --- | --- |
| `risk_happy_blocked` | accepted와 각 blocked gate fixture | exact effects/write 0 |
| `reservation_overcommit` | cash 한도 초과 | no reservation/event |
| `gate_bypass` | blocked receipt로 intent 생성 | risk failure |
| `fill_determinism` | same input reopen/retry | same fill/hash |
| `fill_policy_drift` | policy/input hash 변경 | state 불변 failure |
| `crash_after_reservation` | reservation 뒤 fault | v17/v19 pre-state 복원 |
| `crash_after_fill` | fill 뒤 projection/receipt fault | v17/v19 pre-state 복원 |
| `execution_conflict` | same key amount/price 변경 | conflict, economics 불변 |

## 완료 조건

- V11 risk/sizing 결과만 reservation과 intent를 허용한다.
- Reservation, fill과 v17 account effect가 하나의 SQLite transaction이다.
- Exact retry가 duplicate economic event나 fill을 만들지 않는다.
- Reconciliation mismatch와 paper-only boundary 위반이 fail closed 한다.

## 비목표

- Live broker route, real order, credential와 external acknowledgement
- Risk formula·sizing policy 재설계
- Margin, short, FX conversion과 tax reporting
- Strategy/arm promotion과 advisory outcome scoring
