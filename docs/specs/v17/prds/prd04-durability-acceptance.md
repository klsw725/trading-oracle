# PRD: v17 PRD 04 Durability Acceptance
> **상태**: ✅ 구현 완료
> 상위 SPEC: [v17 SPEC](../SPEC.md)

`uv run python -m src.v17.cli prd04-acceptance`가 canonical `PASS`와 exit 0을 반환한다.

## 의존성

- [PRD 01](prd01-sqlite-store-and-migrations.md)
- [PRD 02](prd02-event-envelope-and-idempotency.md)
- [PRD 03](prd03-account-projection-and-reconciliation.md)
- v16 canonical `RuntimeIdentity` fixture와 v17 local event fixtures

## 목표

Migration, crash atomicity, semantic idempotency, event replay, reconciliation, namespace 격리와 hard boundary를 임시 SQLite에서 standalone으로 증명한다.

## 구현 표면

| 경로 | 책임 |
| --- | --- |
| `src/v17/acceptance.py` | Scenario, mutation, result assembly |
| `src/v17/faults.py` | Transaction 단계별 deterministic fault injection |
| `src/v17/boundaries.py` | Network·portfolio·later import guard |
| `src/v17/fixtures.py` | Runtime identity·event fixture inventory |
| `src/v17/cli.py` | PRD 04와 version acceptance entrypoint |

## Acceptance Database

각 scenario는 OS temp root 아래 empty global schema head `000`인 독립 database를 만들고 v17 global migration `001`만 적용한다. Scenario 간 database를 공유하지 않는다. Fixture inventory가 source file hash를 고정하며 mutation은 database temp copy에만 적용한다. Acceptance 종료 뒤 temp root를 제거한다.

## 필수 시나리오

- Empty head `000`→global head `001`, current `001` no-op, pending migration, migration rollback
- KR/KRW와 US/USD, 두 account, 두 arm의 독립 opening과 state
- Credit, debit, position adjust, reserve, release end-to-end commit
- 동일 semantic request를 process reopen 전후 반복한 no-op
- 같은 key의 payload·identity conflict state 불변 실패
- Event insert, idempotency insert, projection write, checkpoint 직후 각각 fault injection과 전부 rollback
- Full replay와 stored projection hash 일치
- Event, sequence, projection, checkpoint, idempotency row mutation 탐지
- Unknown event/schema/policy와 stale runtime identity fail closed

## Crash 검증

Fault injection은 transaction의 명명된 checkpoint에서 deterministic exception을 발생시킨다. Connection을 강제 close하고 새 process-equivalent connection으로 reopen한 뒤 event, idempotency, projection, checkpoint row count와 hash가 command 이전과 같은지 확인한다. Sleep, signal timing, OS kill 확률에 의존하지 않는다.

## Hard Boundary

- Socket connect, DNS, HTTP client를 trap하고 호출 0건을 요구한다.
- `src.v18` 이후 import를 trap하고 호출 0건을 요구한다.
- `data/portfolio.json` 시작 전 존재·bytes·hash와 종료 후 값을 비교한다.
- Database 외 JSON을 recovery input으로 전달하면 `UNSUPPORTED_RECOVERY_SOURCE`다.
- Broker, credential, live destination 객체 생성은 0건이어야 한다.

## Report 계약

Schema는 `v17.acceptance.1`이다. Top-level은 version, status, migration schema hash, event schema version, projection hash, checks, mutations, boundaries를 가진다. Array는 ID 오름차순이고 temp path·wall-clock timestamp·random value를 포함하지 않는다.

기대된 fail-closed를 보인 mutation은 test `PASS`다. 모든 check·mutation·boundary가 PASS일 때만 top-level PASS와 exit 0이다. 누락, skip, unexpected success, cleanup 실패는 exit 1이다.

## CLI

```bash
uv run python -m src.v17.cli prd04-acceptance
uv run python -m src.v17.cli acceptance
```

Version acceptance는 v16 CLI나 PRD subprocess를 호출하지 않고 typed public contract와 local fixture를 직접 사용한다. v18 이후 directory를 삭제해도 결과가 같아야 한다.

## Acceptance와 Mutation

- SPEC의 18개 mutation probe를 모두 stable ID로 실행
- 동일 acceptance 두 번의 stdout bytes 동일
- Fault point별 pre-command state hash 복원
- Reconciliation mismatch 뒤 append API write 0건
- Fixture inventory 시작·종료 hash 동일
- Network 0, later import 0, portfolio mutation 0, live object 0
- Temp cleanup 후 tracked worktree 변화 없음

## 완료 조건

- `uv run python -m src.v17.cli acceptance`가 network 없이 exit 0이다.
- Migration, append, idempotency, projection을 transaction·reopen 표면에서 직접 사용해 검증한다.
- SQLite event truth에서 replay한 account state가 결정적으로 일치한다.
- v18 이후 모듈, JSON recovery, legacy portfolio에 의존하지 않는다.

## 비목표

- 실제 disk-full·power-loss certification
- Multi-process contention benchmark, multi-host failover
- Live broker integration과 network smoke test
- 주문·fill·risk·strategy acceptance
