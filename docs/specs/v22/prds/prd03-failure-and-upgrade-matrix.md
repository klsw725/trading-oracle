# PRD: v22 PRD 03 Crash, Restart, Corruption, Upgrade And Write-Boundary Matrix
> **상태**: 📋 구현 예정
> 상위 SPEC: [v22 SPEC](../SPEC.md)

## 의존성

- [PRD 01](prd01-black-box-harness-and-oracle.md)의 public transcript와 semantic relation
- [PRD 02](prd02-runtime-containment.md)의 temp state, timeout, trap과 write-set evidence
- [v21 Operator Journey](../../v21/prds/prd04-operator-journey-acceptance.md)의 documented crash/restart/failure 계약
- [v17 durability](../../v17/SPEC.md), [v19 restart](../../v19/SPEC.md), [v20 lifecycle](../../v20/SPEC.md)의 ownership reference

## 목표

공개 CLI 외부에서 process crash, restart, copied-state corruption, supported schema upgrade와 file-write boundary를 체계적으로 변이한다. V22는 내부 transaction을 판정하지 않고 재시작 후 public status/doctor/events/report와 file evidence가 uninterrupted baseline의 의미 관계를 만족하는지 확인한다.

## 구현 표면

| 경로 | 책임 |
| --- | --- |
| `src/v22/scenarios.py` | Baseline, crash/restart, corruption과 upgrade scenario inventory |
| `src/v22/fault_driver.py` | Named checkpoint 종료와 copied-state mutation 구동 |
| `src/v22/mutations.py` | 독립 mutation, public relation 비교와 owning-spec 귀속 |

## Fixture와 Fault Injection 계약

Fixture는 manually authored input causes, prior-version database bytes, public config/operator trust anchor/request template와 fault checkpoint name만 포함한다. Dynamic action identity를 가진 approval signature는 fixture가 아니라 complete canonical body를 받은 local operator signer subprocess가 만든다. Product output, expected table rows, migration result와 public hash는 포함하지 않는다.

Fault key, exact enum, `os._exit(70)` behavior와 temp-root restriction의 normative owner는 [v21 PRD 04 Test-Only Fault Checkpoint Contract](../../v21/prds/prd04-operator-journey-acceptance.md)다. V22는 그 enum을 그대로 전달할 뿐 새 alias, checkpoint 또는 activation rule을 정의하지 않는다.

V22는 fault hook 구현을 import하지 않는다. Child exit, files와 다음 public CLI response만 관측한다. Unknown checkpoint가 성공하면 FAIL이다.

## Uninterrupted Baseline

각 crash family는 같은 source fixture의 clean root에서 uninterrupted journey를 먼저 한 번 실행한다. Baseline은 public IDs의 exact value가 아니라 다음 normalized public projection을 보존한다.

- doctor overall/check statuses와 evidence relation
- status의 initialized/run/lifecycle/incident/approval states와 public heads
- report sections, counts와 independently verified report hash
- events의 stable identity/reference set
- final allowed file inventory와 leak/network/process count

Crash root는 baseline DB를 copy하지 않고 같은 cause input에서 fresh init한다. Crash/restart와 baseline 결과를 `SAME_AS`/set equality로 비교한다.

## Crash/Restart Matrix

| ID | Crash boundary | Restart action | Required public result |
| --- | --- | --- | --- |
| `crash_init_migration` | migration/metadata commit 경계 | same `init`, doctor | initialized 한 번, exact retry semantics |
| `crash_operator_receipt` | source commit 후 v21 receipt 전 | same request | source result 재실행 없이 receipt 보충, duplicate 0 |
| `crash_adapter_intake` | adapter/mapping/intake unit | status then same `run` | no partial public graph, baseline terminal heads |
| `crash_reservation_fill` | reservation/fill/account unit | status then resume | account reconciliation PASS, one economic effect |
| `crash_session_close` | close/outcome receipt unit | status then resume | one terminal run outcome |
| `crash_lifecycle_event` | event/projection/auth unit | doctor then same action | projection/head baseline equality |
| `crash_approval_issue` | record/event/receipt unit | same issue | one approval, one issue history |
| `crash_approval_consume` | binding/action/consume unit | same recover | all-or-none action and one consume |
| `crash_incident_recovery` | RECOVERING/action/RESOLVED unit | incident show then recover | OPEN 또는 complete RESOLVED, partial state 없음 |
| `kill_mid_output` | commit 후 response write 중 child kill | read status then exact retry | durable stored result, malformed partial output는 prior invocation FAIL evidence |

Crash invocation 자체는 expected signal/70과 malformed-or-empty output을 허용하는 check다. 다른 exit, timeout 또는 descendant는 FAIL이다. Restart는 새 process에서만 수행하고 same process memory를 사용하지 않는다.

## Corruption Matrix

Corruption은 정상 scenario가 종료된 copied database에서 수행한다. Original baseline은 불변이어야 한다. V22는 표준 file byte operation 또는 independently authored SQLite statement로 한 mutation만 적용하되 product table 결과를 expected 계산에 사용하지 않는다.

| ID | Mutation | Public probe | Required result/write invariant |
| --- | --- | --- | --- |
| `truncate_database` | copied DB tail truncate | doctor, run | integrity exit 6; run write 0 |
| `database_header_bitflip` | SQLite header bit flip | doctor | integrity/internal documented failure; auto replace 0 |
| `migration_identity_corrupt` | prior fixture의 migration evidence 변조 | doctor, init | exit 6; migration rewrite 0 |
| `event_chain_corrupt` | authored fixture의 immutable event byte 변조 | doctor, run | `EVENT_CHAIN_INVALID`, run 0 |
| `projection_corrupt` | authored fixture의 projection mismatch | doctor, recover | projection integrity exit 6, repair 0 |
| `audit_chain_corrupt` | approval/operator chain byte 변조 | doctor, approval issue | `AUDIT_CHAIN_INVALID`, approval 0 |
| `wal_missing` | crash fixture의 required WAL 제거 | doctor | fail closed 또는 committed public baseline; 추정 repair 금지 |
| `report_forgery` | exported report 1 byte 변경 | product state probe | report는 input 불가, DB 불변 |

Table-aware corruption fixture는 v17/v21 문서 schema만 보고 독립 author가 고정한 prior bytes다. V22가 current product migration/repository를 호출해 만들지 않는다. 각 integrity probe는 mutation 직후 copied state set의 main DB와 존재하는 WAL의 existence, length와 bytes hash, public integrity failure와 logical heads를 고정한다. 이후 `doctor`, `run`, `recover`, `init` 때문에 main DB·WAL 또는 public logical state가 바뀌면 automatic repair FAIL이다. SHM와 lock의 bytes·existence는 corruption probe에서도 volatile SQLite coordination으로 제외하며 repair evidence나 durable state로 사용할 수 없다.

## Schema Upgrade Matrix

Upgrade fixture manifest는 source schema version, fixture bytes SHA-256, authoring provenance, expected supported/unsupported classification과 public seed facts를 가진다. Current product code로 fixture를 생성하지 않는다.

| ID | Source | Action | Required result |
| --- | --- | --- | --- |
| `fresh_empty_current` | empty path | init→doctor→reopen | current schema, READY, second init no-op |
| `initial_release_upgrade` | v20 global schema head `006` fixture | init/migrate→doctor | global `007`→`008`, public facts preserved, READY |
| `supported_previous` | initial release 이후 last shipped v21 global head `008` fixture | init/migrate→doctor | pending global migrations only, public facts preserved, READY |
| `supported_previous_restart` | same source, upgrade checkpoint crash | init again→doctor | baseline-equivalent public state |
| `already_current` | upgraded copied state | exact init/doctor | no extra semantic write/head change |
| `version_ahead` | declared future schema | doctor/init | fail closed, bytes unchanged |
| `migration_hash_drift` | prior applied identity changed | doctor/init | integrity exit 6, bytes unchanged |
| `unsupported_legacy` | pre-v17/JSON state | init/recover attempt | usage/precondition failure, no import |

첫 v21 release의 upgrade source는 반드시 v20 global schema head `006` fixture다. v21이 한 번 ship된 뒤 후속 release는 마지막 shipped v21 global head `008` fixture를 source로 추가하며 initial `006` coverage를 삭제하지 않는다. Upgrade의 성공은 public doctor READY, retained public seed refs, report/event relation과 idempotent reopen으로 증명한다. Internal table count 또는 `PRAGMA user_version`을 oracle로 읽지 않는다.

## File-Write Boundary Matrix

| Command/result | Allowed write set |
| --- | --- |
| `--help`, usage failure | 0 files, DB open/create 0 |
| missing DB `doctor/status` | 0 files, parent create 0 |
| `init` success | designated DB/WAL/SHM와 documented parent only |
| exact mutating retry | transient SQLite lock activity는 허용하되 terminal logical public head와 non-SQLite files 불변 |
| `status/events/incidents/approval show/doctor` | read-only connection; main DB/WAL frame·size growth 0, logical heads/report equality, non-SQLite writes 0; SHM/lock bytes 제외 |
| `report` no output | 0 files |
| `report --output` | exact new export 하나; collision은 0 writes |
| integrity/corruption failure | main DB·기존 WAL과 public logical heads 불변; SHM/lock coordination 제외 |
| timeout/crash | designated DB atomicity 결과만; temp/output outside set 0 |

Physical SQLite file changes가 allowed인 command도 public semantic invariant와 root 경계를 모두 통과해야 한다. Allowed는 성공 증명이 아니라 containment 범위다.

## Failure/Mutation Table

| ID | Injected defect | Expected detector | Owning spec on failure |
| --- | --- | --- | --- |
| `duplicate_fill_after_restart` | resume가 fill 재생성 | public count/head mismatch | v19/v17 |
| `approval_consumed_without_action` | partial consume | show/recover relation mismatch | v21/v20 |
| `incident_stuck_recovering` | crash 뒤 partial projection | incident state oracle | v21 |
| `corruption_repaired` | doctor가 DB bytes 변경 | write-set diff | v17/v21 |
| `upgrade_drops_seed` | public account/event ref 소실 | retained-fact oracle | migration owner v17~v21 |
| `future_schema_downgrade` | version-ahead accepted | response/write invariant | v17/v21 |
| `readonly_command_writes` | status grows main DB/WAL or changes logical head/report | file boundary | v21 |
| `fault_hook_production` | temp root 없이 hook 활성 | usage/security boundary | v21 |
| `scenario_order_dependency` | matrix 순서 변경 시 결과 변화 | clean-root repeat | v22 harness 또는 owning product |
| `mutation_not_observed` | seeded defect에도 suite PASS | mutation adequacy FAIL | v22 oracle |

## Determinism

Matrix는 scenario ID lexical order로 실행하지만 각 root는 독립이므로 reverse/sharded order에서도 normalized result가 같다. Explicit timestamps와 request IDs는 inventory constants다. Sleep, current date, PID와 random UUID는 expectation에 없다.

동일 matrix를 두 clean roots에서 실행해 transcript/evidence artifact를 stable label로 normalize한 뒤 SHA-256가 같아야 한다. Crash signal timing은 named checkpoint acknowledgement와 exit로 결정하며 arbitrary millisecond kill을 사용하지 않는다.

## CLI

```bash
uv run --frozen --offline python -m src.v22.cli prd03-acceptance
uv run --frozen --offline python -m src.v22.cli acceptance
```

## 완료 조건

- 모든 documented commit family에 uninterrupted baseline과 named crash/restart scenario가 있다.
- Corruption은 copy에만 적용되고 doctor/run/recover가 자동 repair하지 않음을 file bytes로 확인한다.
- Supported previous/current/future/legacy schema가 public CLI로 명확히 판정된다.
- Read-only, expected failure, report export와 crash의 allowed write-set이 각각 고정된다.
- Mutation이 실제 결함을 검출하며 failure를 owning v16~v21 spec으로 귀속한다.

## 비목표

- SQLite repair/recovery tool 구현
- Arbitrary power-loss 또는 filesystem durability 인증
- Product migration SQL introspection
- 모든 OS signal timing 조합과 load/soak test
- Business logic defect 수정
