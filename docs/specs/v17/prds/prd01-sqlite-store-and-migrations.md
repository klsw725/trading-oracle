# PRD: v17 PRD 01 SQLite Store And Migrations
> **상태**: ✅ 구현 완료
> 상위 SPEC: [v17 SPEC](../SPEC.md)

`uv run python -m src.v17.cli prd01-acceptance`가 canonical `PASS`와 exit 0을 반환한다.

## 의존성

- [v16 SPEC](../../v16/SPEC.md)의 project root와 `RuntimeIdentity` public contract
- Python 표준 `sqlite3`
- v17 local empty·versioned database fixtures

## 목표

Paper state를 위한 단일 SQLite store를 생성하고, hash-verified forward migration을 atomic하게 적용하며 불완전하거나 알 수 없는 schema를 mutation 전에 차단한다.

## 구현 표면

| 경로 | 책임 |
| --- | --- |
| `src/v17/schema.py` | Table·constraint와 supported schema version |
| `src/v17/migrations.py` | Ordered migration inventory와 hash 검증 |
| `src/v17/migrations/001_initial.sql` | Initial durable tables |
| `src/v17/store.py` | Connection, PRAGMA, transaction, open health |
| `src/v17/models.py` | Database path·migration typed result/failure |

## Database 경로

모든 API는 명시적 path를 받는다. 기본 CLI path는 `<root>/data/paper/v17/paper.sqlite3`이며 resolved path가 root 밖이면 production command에서 거부한다. Acceptance만 OS temp root를 명시적으로 허용한다. Parent directory 생성은 `migrate`의 명시적 책임이며 `verify`와 `replay`는 만들지 않는다.

`data/portfolio.json`은 존재 여부와 관계없이 읽지 않는다. Legacy JSON import code를 initial migration에 넣지 않는다.

## Connection 계약

연결마다 다음 값을 set한 뒤 query로 확인한다.

- `PRAGMA foreign_keys=ON`
- `PRAGMA journal_mode=WAL`
- `PRAGMA synchronous=FULL`
- `PRAGMA busy_timeout=5000`

확인 실패는 `STORE_PRAGMA_MISMATCH`다. Write transaction은 `BEGIN IMMEDIATE`를 사용하고 nested implicit transaction을 금지한다. 모든 SQL parameter는 bound parameter다.

## Migration Inventory

Inventory는 `(version, name, resource, sha256)`의 code constant이며 단일 database 전체에서 global ordinal `001`부터 gap 없이 증가해야 한다. V17이 소유하는 migration은 `001_initial.sql` 하나이고 적용 후 global schema head는 `001`이다. 후속 버전은 이 sequence를 다시 `001`부터 시작하지 않는다. SQL resource directory scan으로 순서를 만들지 않는다.

`schema_migrations`는 모든 후속 버전이 공유하는 global version primary key, name, SHA-256를 저장한다. `PRAGMA user_version`도 version-local 값이 아니라 latest applied global ordinal이다. Host apply time은 state identity나 acceptance output에 사용하지 않는다. Migration SQL과 row insert, `user_version` 변경은 하나의 transaction이다.

## Open 상태

| 상태 | 동작 |
| --- | --- |
| Empty path + `migrate` | parent 생성 후 latest까지 적용 |
| Current database | hash와 user_version 확인 후 open |
| Behind database + `migrate` | pending만 순서대로 적용 |
| Behind database + `verify` | `MIGRATION_REQUIRED`, no mutation |
| Ahead database | `DATABASE_VERSION_AHEAD` |
| Applied hash drift | `MIGRATION_HASH_MISMATCH` |
| Gap·duplicate inventory | application configuration failure |

실패 migration은 DDL, migration row, user_version을 모두 rollback한다. 적용된 SQL을 수정하는 repair는 금지하며 새 migration으로만 진화한다.

## Initial Table 계약

Initial schema는 `schema_migrations`, `accounts`, `events`, `idempotency_keys`, `account_balances`, `account_positions`, `account_reservations`, `projection_checkpoints`를 만든다. Foreign key와 namespace unique constraint는 database level에 존재해야 한다. Event와 migration row는 update/delete application API를 갖지 않는다.

## CLI

```bash
uv run python -m src.v17.cli migrate --database data/paper/v17/paper.sqlite3
uv run python -m src.v17.cli prd01-acceptance
```

## Acceptance와 Mutation

- Empty global head `000`→`001`, current `001` no-op, behind→`001` 경로
- `migration_hash_drift`, version ahead, inventory gap·duplicate 차단
- 실패 SQL 직전·직후 schema와 migration row 동일
- 모든 연결의 PRAGMA 확인
- `verify`가 missing parent·database를 생성하지 않음
- 두 account namespace unique constraint와 foreign key enforcement

## 완료 조건

- Migration이 atomic, ordered, hash-verified, forward-only다.
- Invalid schema에서 event·projection mutation API가 열리지 않는다.
- SQLite 밖의 파일을 durable account truth로 사용하지 않는다.

## 비목표

- Downgrade, destructive auto-repair, online multi-host migration
- JSON portfolio import 또는 backup restore
- Event business semantics와 projection reducer
