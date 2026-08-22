# PRD: v17 PRD 03 Account Projection And Reconciliation
> **상태**: ✅ 구현 완료
> 상위 SPEC: [v17 SPEC](../SPEC.md)

`uv run python -m src.v17.cli prd03-acceptance`가 canonical `PASS`와 exit 0을 반환한다.

## 의존성

- [PRD 01](prd01-sqlite-store-and-migrations.md)의 transaction store
- [PRD 02](prd02-event-envelope-and-idempotency.md)의 ordered event log

## 목표

Paper account cash·position·reservation projection을 순수 event reducer로 만들고, SQLite event truth와 projection이 다르면 mutation 전에 fail closed 한다.

## 구현 표면

| 경로 | 책임 |
| --- | --- |
| `src/v17/accounts.py` | Account namespace·opening invariant |
| `src/v17/reducers.py` | Event별 pure state transition |
| `src/v17/projections.py` | Projection table write와 canonical hash |
| `src/v17/replay.py` | Empty state부터 deterministic replay |
| `src/v17/reconciliation.py` | Event·projection·checkpoint·idempotency 비교 |

## Account State

Projection은 namespace별 다음 state를 가진다.

- account status와 opening runtime/config/policy identity
- available cash와 reserved cash minor units
- symbol별 integer quantity와 average cost minor units
- reservation ID별 amount, status와 생성 event ID
- last applied sequence와 event hash

Market/currency/account/arm을 생략한 query는 없다. KR과 US cash를 합산하거나 currency conversion을 하지 않는다.

## Reducer 계약

Reducer 입력은 이전 immutable state와 한 event이고 출력은 새 state 또는 typed invariant failure다.

| Event | Transition |
| --- | --- |
| `account.opened` | sequence 1에서 opening cash와 identity 생성 |
| `cash.credited` | available 증가 |
| `cash.debited` | available 감소, 결과 음수 거부 |
| `position.adjusted` | quantity·average cost 갱신, 0 quantity row 제거 |
| `reservation.placed` | available 감소·reserved 증가, duplicate ID 거부 |
| `reservation.released` | active amount 전액 available로 복귀, 재해제 거부 |

Cash와 cost는 64-bit minor-unit integer다. Overflow, negative cash/reservation, negative position quantity는 fail closed 한다. Short, partial reservation release와 realized P&L은 후속 버전 범위다.

## Projection Commit

Event append와 같은 transaction에서 reducer 결과를 balances, positions, reservations에 반영하고 checkpoint를 event sequence·hash로 갱신한다. Projection row에는 event 밖의 business 값을 추가하지 않는다.

Canonical projection hash는 namespace 순, symbol 순, reservation ID 순으로 정렬한 typed state에서 계산한다. SQLite rowid와 insertion order는 제외한다.

## Replay

Replay는 migration이 적용된 빈 in-memory database 또는 빈 typed state에 event sequence 1부터 적용한다. Current projection table, JSON export, cache를 seed로 사용하지 않는다. 같은 events와 reducer version이면 projection bytes와 hash가 같아야 한다.

## Reconciliation

Store open과 mutation 직전에 다음을 전부 비교한다.

1. Account와 event namespace·identity
2. Sequence gap·duplicate와 hash chain
3. Full replay state와 stored projection field
4. Checkpoint와 event head
5. Idempotency key의 event reference와 result hash

Mismatch는 typed evidence와 함께 database를 quarantine한다. `reconcile`은 검사 의미이며 projection을 자동 수정하지 않는다. 정상 event를 삭제하거나 forged snapshot으로 덮지 않는다.

## CLI

```bash
uv run python -m src.v17.cli replay --database data/paper/v17/paper.sqlite3
uv run python -m src.v17.cli verify --database data/paper/v17/paper.sqlite3
uv run python -m src.v17.cli prd03-acceptance
```

`replay`와 `verify`는 read-only이며 WAL checkpoint를 business result로 취급하지 않는다.

## Acceptance와 Mutation

- Opening, credit/debit, position, reserve/release happy path
- Negative cash, duplicate release, overflow, second opening state 불변 실패
- Event replay와 stored projection canonical hash 일치
- `projection_cash_drift`, position drift, checkpoint drift 탐지
- Reconciliation 실패 뒤 모든 command mutation 차단
- JSON forged projection을 replay seed로 거부
- Namespace별 독립 replay와 account/arm 교차 참조 차단

## 완료 조건

- Projection 전체가 SQLite event만으로 재생성된다.
- Open과 mutation 전 reconciliation이 불일치를 fail closed 한다.
- JSON, cache, `data/portfolio.json`이 state 또는 recovery truth가 아니다.

## 비목표

- 주문 matching, fill accounting, tax, FX, NAV
- Short position과 margin
- 자동 repair·snapshot restore
