# Trading Oracle v17 SPEC: Durable Paper Account, Event And State Foundation
> **상태**: ✅ 구현 완료

v17은 [v16](../v16/SPEC.md)이 검증한 runtime input identity 위에 durable paper account를 세운다. SQLite event log가 유일한 상태 진실이며 projection과 JSON report는 언제든 event replay로 재생성할 수 있어야 한다.

## 0. 구현 완결성 계약

- v17은 구현 완료된 v16 public contract와 v17 로컬 fixture만 의존하며 v18 이후 package를 import하거나 후속 주문·전략 기능을 요구하지 않는다.
- `uv run python -m src.v17.cli acceptance`는 임시 SQLite database에서 migration, append, duplicate retry, conflict, crash rollback, projection replay, reconciliation과 boundary를 실행하고 canonical JSON report를 출력한 뒤 exit 0이어야 한다.
- SQLite는 v17부터 paper account·event·projection·migration의 유일한 durable state truth다. JSON, in-memory cache, `data/portfolio.json`은 recovery 또는 reconciliation truth가 될 수 없다.
- Offline replay는 network, wall clock, random ID, filesystem enumeration 없이 동일 event rows에서 byte-identical projection·report hash를 만들어야 한다.
- Unknown event/schema/policy, stale runtime identity, hash-chain mismatch, projection reconciliation mismatch는 모든 추가 mutation 전에 fail closed 한다.
- 모든 event·projection·idempotency key는 KR/US, KRW/USD, account, arm, policy/config version을 격리한다.
- Acceptance는 temp database만 변경하며 tracked file과 `data/portfolio.json`의 존재·bytes·hash를 바꾸지 않는다.
- 이 조건과 아래 Acceptance Criteria가 모두 통과하면 v17은 후속 버전 없이 단독 완료다.

최종 구현은 `uv run python -m src.v17.cli acceptance`에서 33개 check,
18개 mutation, 8개 hard boundary를 통과하며 두 연속 실행이 byte-identical하다.
Canonical report hash는
`sha256:96b365dce2d0ef6527e4db4869417911712e20c0f4f80ca76e97a0f66fe88c34`,
projection hash는
`sha256:b5ba04603a6d87251ba6cbdf8dec6cf4dc7f82ab5196375adad760058b7e6aac`다.

## Local PRD Map

| PRD | Local document | Implementation owner | Produces |
| --- | --- | --- | --- |
| PRD 01 | [SQLite Store And Migrations](prds/prd01-sqlite-store-and-migrations.md) | `src/v17/store.py`, `src/v17/migrations.py`, `src/v17/schema.py` | transactional SQLite store |
| PRD 02 | [Event Envelope And Idempotency](prds/prd02-event-envelope-and-idempotency.md) | `src/v17/events.py`, `src/v17/idempotency.py`, `src/v17/event_log.py` | hash-chained semantic event log |
| PRD 03 | [Account Projection And Reconciliation](prds/prd03-account-projection-and-reconciliation.md) | `src/v17/accounts.py`, `src/v17/projections.py`, `src/v17/reconciliation.py` | replayable paper account state |
| PRD 04 | [Durability Acceptance](prds/prd04-durability-acceptance.md) | `src/v17/acceptance.py`, `src/v17/boundaries.py`, `src/v17/cli.py` | standalone durability report |

PRD 01→04 순서로 구현한다. PRD 04는 v16 canonical input fixture를 public contract로 읽되 v16 acceptance를 다시 실행하지 않으며 v18 이후 기능을 요구하지 않는다.

## 1. v16과 v17 경계

v16은 config, policy, calendar와 data를 검증하고 immutable `runtime_identity`를 제공한다. v17은 이 값을 event의 필수 lineage로 저장하지만 data health를 재해석하지 않는다. v17의 책임은 paper account state의 atomic persistence, semantic duplicate 억제, replay와 reconciliation이다.

v17은 주문 routing, fill simulation, risk strategy를 구현하지 않는다. Acceptance에 쓰는 account event는 foundation contract를 검증하는 synthetic command다.

## 2. SQLite 유일 진실 계약

기본 개발 경로는 `<project_root>/data/paper/v17/paper.sqlite3`이지만 모든 store open은 명시적 `database_path`를 받는다. Production path는 root 내부여야 하고 acceptance는 OS temp directory의 새 database를 사용한다.

다음만 durable state다.

- `schema_migrations`: 적용된 migration identity
- `accounts`: account namespace와 opening identity
- `events`: immutable ordered envelope와 payload
- `idempotency_keys`: semantic request outcome
- `account_balances`, `account_positions`, `account_reservations`: 재생성 가능한 projection
- `projection_checkpoints`: 적용 event sequence와 hash

JSON export, acceptance report, cache, snapshot file은 관측용이며 database를 복구하거나 덮어쓰는 입력으로 사용할 수 없다. `data/portfolio.json`을 읽거나 migration source로 사용하지 않는다.

## 3. Database Open과 PRAGMA

연결마다 `foreign_keys=ON`, `journal_mode=WAL`, `synchronous=FULL`, `busy_timeout=5000`을 확인한다. 필수 PRAGMA가 설정·확인되지 않으면 store를 열지 않는다. Application mutation은 single-process writer transaction으로 제한하고 multi-host coordination은 범위 밖이다.

Database open 순서는 header 확인→migration 검증·적용→event chain 검증→projection reconciliation이다. 어느 단계든 실패하면 read-only diagnostic 외 mutation API를 제공하지 않는다.

## 4. Migration 계약

Migration은 `src/v17/migrations`의 정수 증가 SQL asset이며 application code에 선언한 ordered inventory만 실행한다. Directory listing 순서에 의존하지 않는다.

단일 SQLite database의 migration ordinal은 버전별로 다시 시작하지 않는 전역 sequence다. V17은 global ordinal `001`을 소유하고 global schema head `001`을 만든다. `schema_migrations.version`과 `PRAGMA user_version`은 v17~v21 전체가 공유하는 global ordinal이며 version-local counter가 아니다. V17 acceptance는 empty global head `000`에서 시작해 `001`을 적용한다.

각 migration은 version, name, SQL bytes SHA-256를 가진다. `BEGIN IMMEDIATE` 한 transaction 안에서 SQL 적용과 `schema_migrations` insert를 함께 수행한다. 성공하면 `PRAGMA user_version`도 같은 version이 된다.

- Applied hash가 code inventory와 다르면 `MIGRATION_HASH_MISMATCH`다.
- Database version이 code보다 높으면 `DATABASE_VERSION_AHEAD`다.
- Version gap, duplicate, out-of-order inventory는 application start 실패다.
- 실패 migration은 schema와 migration row를 모두 rollback한다.
- 기존 migration SQL은 적용 후 수정할 수 없고 새 migration만 추가한다.

## 5. Namespace와 계정 계약

`AccountNamespace`는 `(account_id, market, currency, arm_id)`다. `account_id`와 `arm_id`는 opaque non-empty canonical string이며 raw broker account ID가 아니다.

- `KR`은 `KRW`, `US`는 `USD`만 허용한다.
- Namespace는 database의 unique key이고 event, idempotency, projection 모든 table에 동일하게 전달한다.
- 한 namespace의 cash, positions, reservations를 다른 market·currency·account·arm과 합산하지 않는다.
- Cross-currency conversion과 통합 NAV는 v17 범위 밖이다.

Account create는 `paper` mode, opening currency, opening cash minor units, `runtime_identity`, config·policy version을 고정한다. Opening cash와 이후 금액은 signed 64-bit integer minor units이며 float를 저장하지 않는다.

## 6. Event Envelope

모든 event는 다음 immutable envelope를 가진다.

| Field | Contract |
| --- | --- |
| `event_schema_version` | `v17.event.1` |
| `event_id` | canonical envelope에서 계산한 `sha256:` ID |
| `sequence` | database가 namespace별 1부터 부여하는 연속 integer |
| `event_type` | 등록된 enum |
| `semantic_key` | command 의미 identity의 SHA-256 |
| namespace fields | account, market, currency, arm |
| identity fields | runtime, config, policy version |
| `effective_at` | caller가 제공한 UTC RFC 3339 timestamp |
| `payload` | event type별 strict canonical JSON |
| `previous_event_hash` | 같은 namespace 직전 event hash 또는 genesis |
| `event_hash` | envelope canonical bytes SHA-256 |

Database insertion time, random UUID, host identity는 event identity에 포함하지 않는다. Unknown field, event type, schema, policy, non-canonical amount·timestamp는 append 전에 거부한다.

v17 registered event type은 `account.opened`, `cash.credited`, `cash.debited`, `position.adjusted`, `reservation.placed`, `reservation.released`로 제한한다. 주문·fill 의미를 미리 정의하지 않는다.

## 7. Semantic Idempotency

Idempotency는 transport retry가 아니라 business command 의미를 기준으로 한다. `semantic_key`는 command type, namespace, caller의 `command_id`, config·policy version을 canonical hash한 값이다.

같은 semantic key와 같은 canonical request hash가 다시 오면 기존 event ID·sequence·result를 반환하고 새 row나 projection mutation을 만들지 않는다. 같은 key에 다른 request hash, namespace, payload, policy identity가 오면 `IDEMPOTENCY_CONFLICT`로 fail closed 한다.

다른 command ID가 경제적으로 같은 요청이어도 별도 의미 event다. 반대로 process 재시작, timestamp of receipt, retry count가 달라도 command ID와 의미 payload가 같으면 duplicate다. Idempotency row, event append, projection update는 한 transaction이다.

## 8. Transaction과 Crash 계약

하나의 command transaction은 다음 순서다.

1. Store health와 current projection checkpoint 확인
2. Semantic key 조회·conflict 판정
3. Current event head와 precondition 읽기
4. Event와 idempotency outcome append
5. Projection 적용과 checkpoint 갱신
6. Event head·projection invariant 검증
7. Commit

단계 4~6 어느 지점의 예외·process interruption도 event, key, projection을 전부 남기거나 전부 남기지 않아야 한다. Partial commit을 복구용 JSON으로 메우지 않는다.

## 9. Account Projection

Projection은 events sequence 1부터 strict reducer로 계산한다. Reducer는 순수 함수이며 database connection, current time, network를 읽지 않는다.

- `account.opened`: opening cash와 identity를 생성하며 sequence 1에서 한 번만 허용
- `cash.credited`: available cash 증가
- `cash.debited`: available cash 감소, 음수 금지
- `position.adjusted`: symbol별 integer quantity와 average cost minor unit 갱신
- `reservation.placed`: available cash 감소, reserved cash 증가, reservation ID unique
- `reservation.released`: active reservation을 available cash로 반환, 중복 release 금지

`total_cash = available_cash + reserved_cash`가 event 경제 효과와 일치해야 한다. Position quantity가 0이면 row를 제거한다. v17은 short position과 negative cash를 허용하지 않는다.

## 10. Reconciliation과 Replay

Store open과 모든 mutation 직전에 다음을 검증한다.

- Namespace별 sequence가 1부터 gap 없이 증가
- `previous_event_hash`와 `event_hash` chain 일치
- Event schema·runtime/config/policy identity가 account 계약과 일치
- 모든 event를 빈 state에서 replay한 결과와 projection table이 field-by-field 일치
- Checkpoint sequence·hash가 event head와 일치
- Idempotency outcome이 참조하는 event가 존재하고 request hash가 일치

불일치 시 `RECONCILIATION_FAILED` 또는 더 구체적인 hash/sequence code로 store를 quarantine한다. 자동 projection overwrite, event 삭제, JSON import, 마지막 정상 checkpoint로의 묵시적 rollback은 금지한다. Diagnostic report는 차이와 evidence hash만 제공하고 mutation은 operator가 원인을 해결한 새 명시적 도구가 생기기 전까지 차단한다.

## 11. Deterministic Offline Replay

Replay 입력은 migration inventory와 SQLite event rows뿐이다. 빈 in-memory SQLite database에 동일 event를 sequence 순으로 적용한 projection의 canonical hash가 원 database projection hash와 같아야 한다.

Event row 순서를 SQL 기본 순서에 맡기지 않고 namespace와 sequence를 명시한다. Locale, CWD, WAL checkpoint timing, rowid, insertion timestamp는 replay 결과에 영향을 주지 않는다.

## 12. CLI 계약

| Command | 역할 |
| --- | --- |
| `migrate --database PATH` | Pending migration atomic 적용 |
| `verify --database PATH` | Schema, chain, projection, idempotency reconciliation |
| `replay --database PATH` | Read-only deterministic projection hash 출력 |
| `prd01-acceptance` | Store·migration acceptance |
| `prd02-acceptance` | Event·idempotency acceptance |
| `prd03-acceptance` | Projection·reconciliation acceptance |
| `prd04-acceptance` | Durability boundary acceptance |
| `acceptance` | v17 standalone acceptance |

Canonical 명령은 `uv run python -m src.v17.cli acceptance`다. 성공은 exit 0, 계약상 invalid database/input은 exit 2, 내부 오류는 exit 1이다. 모든 machine command는 canonical JSON 한 줄을 stdout에 출력한다.

## 13. Failure와 Mutation 계약

| Probe | Mutation | Required result |
| --- | --- | --- |
| `migration_hash_drift` | applied migration SQL hash 변경 | open failure |
| `migration_partial_failure` | migration 중간 SQL 오류 | schema·row 전체 rollback |
| `database_version_ahead` | user_version을 inventory보다 높임 | fail closed |
| `duplicate_retry` | 같은 semantic key·request 재전송 | 동일 result, row count 불변 |
| `idempotency_payload_conflict` | 같은 key에 amount 변경 | conflict, state 불변 |
| `event_hash_forgery` | payload byte 변경, hash 유지 | chain failure |
| `event_sequence_gap` | 중간 sequence 삭제 | reconciliation failure |
| `unknown_event_policy` | unknown event/schema/policy 삽입 | append/open failure |
| `stale_runtime_identity` | account와 다른 runtime identity append | append failure |
| `crash_after_event_insert` | projection 전 강제 예외 | event·key·projection 모두 rollback |
| `projection_cash_drift` | projection cash 직접 변경 | mutation 전 reconciliation failure |
| `projection_position_drift` | quantity 직접 변경 | replay mismatch |
| `cross_namespace_reference` | KR event가 US reservation 참조 | isolation failure |
| `market_currency_swap` | KR/USD account 생성 | validation failure |
| `json_recovery_attempt` | forged JSON로 DB 복구 시도 | unsupported input failure |
| `portfolio_mutation` | acceptance 전후 portfolio 감시 | 존재·bytes·hash 불변 |
| `network_attempt` | socket/DNS/HTTP trap | 호출 0건 |
| `later_version_import` | v18 이후 import trap | import 0건 |

## 14. 의존성과 비목표

v17은 Python 표준 `sqlite3`, v16 public identity model, v17 package와 local fixtures만 사용한다. v16 CLI를 subprocess로 실행하거나 v18 이후 schema를 참조하지 않는다.

다음은 비목표다.

- live broker·credential·실계좌 account ID
- 주문 routing, fill engine, risk, 전략, 시장 데이터 vendor 추가
- web UI, multi-user, multi-host, daemon, distributed lock
- cross-currency conversion 또는 consolidated account
- JSON backup을 통한 recovery
- network-required acceptance
- `data/portfolio.json` import·migration·mutation

## 15. Acceptance Criteria

- Migration inventory와 hash가 atomic·forward-only이며 drift와 partial failure를 차단한다.
- Global migration ordinal `001`이 empty head에서 적용되고 `schema_migrations`와 `user_version`이 모두 global head `001`로 일치한다.
- SQLite가 account, event, idempotency, projection의 유일 durable truth다.
- Event envelope와 semantic key가 deterministic하고 hash chain으로 연결된다.
- Duplicate retry는 no-op이고 같은 key의 의미 충돌은 state 불변으로 실패한다.
- Account projection이 event replay로 완전히 재생성된다.
- Hash, stale identity, unknown schema/policy, reconciliation mismatch가 mutation 전에 fail closed 한다.
- KR/US, KRW/USD, account, arm, config/policy namespace가 교차하지 않는다.
- Canonical acceptance가 temp SQLite에서 offline·deterministic하게 동작하고 v18 이후를 import하지 않는다.
- JSON과 `data/portfolio.json`은 recovery truth가 아니며 어떤 acceptance에서도 변하지 않는다.
