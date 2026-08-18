# PRD: v17 PRD 02 Event Envelope And Idempotency
> **상태**: 📋 구현 예정
> 상위 SPEC: [v17 SPEC](../SPEC.md)

## 의존성

- [PRD 01](prd01-sqlite-store-and-migrations.md)의 current SQLite store
- [v16 SPEC](../../v16/SPEC.md)의 runtime/config/policy identity

## 목표

엄격한 event envelope, namespace별 hash chain과 semantic idempotency를 정의해 retry는 no-op, 의미 충돌은 state 불변 실패로 만든다.

## 구현 표면

| 경로 | 책임 |
| --- | --- |
| `src/v17/events.py` | Event type별 strict payload와 envelope |
| `src/v17/canonical.py` | Canonical bytes, event·request hash |
| `src/v17/idempotency.py` | Semantic key lookup과 conflict verdict |
| `src/v17/event_log.py` | Namespace sequence·chain append/read |
| `src/v17/commands.py` | Typed command에서 event 생성 |

## Namespace 계약

모든 command와 event는 account ID, market, currency, arm ID를 가진다. `KR/KRW`, `US/USD`만 허용한다. Runtime, config, policy version도 envelope와 request hash에 포함한다. Namespace 또는 identity가 account opening contract와 다르면 append 전에 실패한다.

## Event Type

v17 허용 type은 다음 여섯 개뿐이다.

- `account.opened`
- `cash.credited`
- `cash.debited`
- `position.adjusted`
- `reservation.placed`
- `reservation.released`

Payload schema는 unknown field를 거부한다. Money는 currency minor-unit integer, quantity는 integer, timestamp는 UTC RFC 3339 canonical string이다. Float, NaN, implicit local time을 허용하지 않는다.

## Envelope와 Hash Chain

Sequence는 namespace별 transaction 안에서 `max(sequence)+1`이 아니라 current head row를 잠그고 1씩 증가시킨다. 첫 event의 previous hash는 schema가 지정한 genesis constant다. Event hash는 event ID와 event hash 자체를 제외한 canonical envelope bytes에서 계산하고, event ID는 `sha256:<event hash body>`로 동일하게 고정한다.

Event는 append 후 application API로 update/delete할 수 없다. Read는 항상 namespace, sequence explicit order를 사용한다.

## Semantic Idempotency

`semantic_key = hash(command_type, namespace, command_id, config_version, policy_version)`이고 `request_hash = hash(runtime_identity, effective_at, canonical payload, precondition)`다.

- Key 없음: event·outcome·projection을 한 transaction으로 생성
- Key 있음 + request hash 동일: 저장된 event ID·sequence·result 반환, write 0건
- Key 있음 + request hash 다름: `IDEMPOTENCY_CONFLICT`, write 0건

Retry reception time, process ID와 attempt count는 key나 request hash에 없다. Command ID 재사용은 account·arm 범위 안에서만 충돌하지만 market/currency를 바꾼 재사용도 cross-namespace 참조로 거부한다.

## Precondition

Command는 expected previous event hash를 가진다. Current head와 다르면 `STALE_EVENT_HEAD`이고 새 event를 만들지 않는다. Duplicate retry는 저장된 request hash가 같으면 stale head 검사보다 먼저 기존 result를 반환한다.

## Failure 계약

Unknown event/schema/policy, stale runtime identity, hash mismatch, sequence gap을 발견하면 append를 금지한다. Conflict report에는 semantic key와 evidence hash만 포함하며 민감한 raw payload를 반환하지 않는다.

## CLI

```bash
uv run python -m src.v17.cli prd02-acceptance
uv run python -m src.v17.cli verify --database data/paper/v17/paper.sqlite3
```

## Acceptance와 Mutation

- 각 event type canonical append와 chain 연속성
- 같은 request 1회·10회 결과와 row count 동일
- `idempotency_payload_conflict`, stale head, unknown type/schema/policy state 불변 실패
- Event payload/hash forgery와 sequence gap 탐지
- KR/US, account, arm, config/policy key isolation
- Process restart 뒤 duplicate retry도 동일 stored result

## 완료 조건

- Event identity와 duplicate 결과가 wall clock·randomness 없이 deterministic하다.
- Event, idempotency outcome, projection update가 하나의 transaction이다.
- 의미 충돌과 chain 이상이 어떤 후속 mutation도 허용하지 않는다.

## 비목표

- Kafka·message broker·distributed deduplication
- 주문·fill·broker event
- Event schema 자동 upgrade 또는 unknown event 보존
