# PRD: v21 PRD 02 Status, Observability And Incidents
> **상태**: 📋 구현 예정
> 상위 SPEC: [v21 SPEC](../SPEC.md)

## 의존성

- [PRD 01](prd01-unified-operator-cli.md)의 command, schema, idempotency, redaction와 exit 계약
- [v16 SPEC](../../v16/SPEC.md)의 runtime/config/calendar/data health public service
- [v17 SPEC](../../v17/SPEC.md)의 migration, event/projection replay와 reconciliation
- [v19 SPEC](../../v19/SPEC.md)의 session plan/run/lease/receipt/close public service
- [v20 SPEC](../../v20/SPEC.md)의 adapter, circuit, lifecycle, authorization와 failure evidence

## 목표

한 운영자가 v21 CLI로 fresh database를 초기화하고, 실행 가능성을 진단하고, 한 paper session을 실행하며, 일관된 SQLite snapshot에서 상태·보고서·event·incident를 조사할 수 있게 한다. 관측성은 기존 durable evidence를 참조하며 별도 log/state store를 만들지 않는다.

## 구현 표면

| 경로 | 책임 |
| --- | --- |
| `src/v21/operator_service.py` | init/doctor/run composition |
| `src/v21/observability.py` | cross-version read model과 consistent snapshot |
| `src/v21/incidents.py` | typed failure→incident projection과 deduplication |
| `src/v21/reporting.py` | status/report/events output data |
| `src/v21/repository.py` | operator event/receipt/incident append |
| `src/v21/migrations/007_operator_control_plane.sql` | Global head `006`→`007`; v21 control-plane tables |

## SQLite와 Migration

V21 migration은 v20 global head `006` 뒤에 `007`, `008` 순서로 forward-only 적용한다. `schema_migrations.version`과 `PRAGMA user_version`은 전 버전 공통 global ordinal이고 최종 v21 head는 `008`이다. 기존 v17~v20 migration row/table을 수정하지 않는다.

| Table | 역할 | Mutation owner |
| --- | --- | --- |
| `operator_metadata` | v21 schema/contract, runtime initialization과 trust anchor identity | `init` only |
| `operator_events` | redacted hash-chained command/audit timeline | v21 repository |
| `operator_receipts` | mutating request idempotency outcome | v21 repository |
| `incidents` | incident current replay projection | incident reducer only |
| `incident_events` | immutable incident lifecycle event | incident repository |
| `approval_*`, `recovery_attempts` | PRD 03 소유 | PRD 03 only |

`operator_events`는 v16~v20 원본 event payload를 복제하지 않는다. `{source_version, source_kind, source_id, source_hash}` reference와 safe summary만 가진다. Operator/incident event, projection과 receipt는 한 transaction에 commit한다. Projection row direct update API는 reducer 밖에 없다.

## `init` 계약

`init`은 다음 순서 하나로 실행한다.

1. V16 project root/config path를 resolve하고 config/runtime identity를 검증한다.
2. Database path가 root 내부이고 `data/portfolio.json`이 아님을 확인한다.
3. V17 store를 열고 required PRAGMA를 검증한 뒤 global `001`~`008` inventory에서 pending migration만 적용한다.
4. Existing event/projection/lifecycle chain이 있으면 전체 reconciliation한다.
5. Ed25519 public trust-anchor document를 strict parse·검증한다.
6. Config/runtime identity, trust-anchor fingerprint, public paper namespace를 `operator_metadata`에 기록한다.
7. `operator.initialized` event와 idempotency receipt를 같은 transaction에 append한다.

Trust-anchor public bytes는 verification metadata이며 business state를 대체하지 않는다. Empty database에서 init은 parent directory를 생성할 수 있다. `doctor/status/report/events/incidents`는 missing path를 생성하지 않는다.

Same request/body init은 stored result다. 이미 initialized database에서 runtime identity, trust anchor 또는 namespace가 다르면 `TRUST_ANCHOR_IMMUTABLE` 또는 `INITIALIZATION_CONFLICT`, exit 4다. Init은 opening cash, account, strategy manifest를 임의 생성하지 않고 configured v17/v20 bootstrap public service만 호출한다. Config에 bootstrap namespace가 없으면 account_refs는 빈 배열이며 `run`은 precondition failure다.

## `doctor` 계약

Doctor는 read-only이며 아래 순서와 exact check ID를 사용한다.

Doctor와 모든 read command는 SQLite URI `mode=ro`, `PRAGMA query_only=ON`인 connection의 한 snapshot을 사용한다. Read path는 migration apply, WAL checkpoint, audit/incident append와 temp table 생성을 수행하지 않는다.

| Check ID | Public service/검증 | Blocking |
| --- | --- | --- |
| `project_root` | v16 root/config path | yes |
| `runtime_identity` | config/policy/lock identity | yes |
| `calendar_data_health` | requested/current initialized markets | yes for run |
| `schema_migrations` | global `001`~`008` inventory hashes와 `user_version=008` | yes |
| `sqlite_pragmas` | foreign key/WAL/FULL/busy timeout | yes |
| `event_chains` | v17/v20/v21 hash chains | yes |
| `account_projections` | v17 replay reconciliation | yes |
| `session_graph` | v19 plan→run→receipt→fill→close refs | yes |
| `lifecycle_projection` | v20 lifecycle/auth heads | yes |
| `approval_audit` | PRD 03 event/signature/binding consistency | yes for approval/recovery |
| `portfolio_boundary` | configured path가 JSON portfolio를 참조하지 않음 | yes |

Check item schema는 `{check_id,status,blocking,code,evidence_refs,evidence_hash}`이고 status는 `PASS|FAIL|NOT_APPLICABLE`이다. Raw database row, SQL과 sensitive payload는 없다. `overall`은 blocking FAIL이 하나라도 있으면 `BLOCKED`, 아니면 `READY`다.

Doctor가 typed failure를 발견하면 read-only 원칙을 유지하므로 incident를 자동 append하지 않는다. `run` 또는 다른 mutating command가 같은 failure를 만났을 때 incident를 원자적으로 open/deduplicate한다. Doctor 결과는 deterministic candidate incident identity를 보여줄 수 있지만 durable incident라고 부르지 않는다.

## `run` 계약

Run은 한 market/session/account/arm만 실행한다. 흐름은 다음이다.

```text
v16 runtime/calendar/data validation
-> v17/v19/v20/v21 reconciliation
-> v19 existing plan/run/lease lookup
-> v20 actual adapter + mapping or stored result
-> v19 intake/risk/reservation/intent/paper fill/mark/close
-> v17 economic event/projection
-> v20 mirror/lifecycle/authorization projection
-> v21 operator event/receipt and incident projection
```

- Config와 database의 initialized runtime identity가 같아야 한다.
- Session은 requested market의 official session이며 explicit `as_of`가 각 v19 cutoff와 일치해야 한다.
- Existing incomplete run은 v19 public resume semantics를 사용한다. New attempt나 lease takeover를 v21이 추정하지 않는다.
- Active unexpired lease면 `LEASE_HELD`, exit 8이다. Sleep/poll/자동 retry하지 않는다.
- V20 adapter와 lifecycle은 실제 public service를 호출한다. V21은 strategy result, fallback, risk, kill scope와 transition을 만들지 않는다.
- Automatic/safety transition은 v20 result에 따라 즉시 진행한다. Approval prompt나 interactive wait가 없다.
- V20이 `SOURCE_DATA_EXCEPTION` 또는 `POLICY_IDENTITY_CHANGE` approval을 요구하면 approval ID 없는 `run`은 `APPROVAL_REQUIRED`, exit 5와 exact action identity를 반환하고 transition은 0건이다. `run --approval-id`는 PRD 03 consumption transaction으로 exact approval을 검증·소비할 수 있다.
- `OPERATION_KILL_RECOVERY`와 `SAME_VERSION_ROLLBACK_RECOVERY`는 일반 `run`으로 수행하지 않으며 PRD 03 `recover`만 소유한다.
- `RunOutcome`은 `run_outcome`으로 출력하며 v18 `measurement_outcome`과 합치지 않는다.

Run의 각 v20/v19/v17 의미 단위 transaction은 선행 버전 boundary를 유지한다. V21 receipt는 해당 unit의 마지막 transaction에 참여하거나 이미 committed source receipt를 참조하는 별도 append transaction이다. 후자의 fault는 source business commit을 되돌리지 않고 retry가 missing v21 receipt를 exact source hash에서 idempotently 보충한다. Business result를 재실행해 보충하지 않는다.

## Structured Operator Event

Schema `v21.operator-event.1`:

| Field | Contract |
| --- | --- |
| `event_id` | canonical event body `sha256:` |
| `sequence` | database-wide v21 operator sequence, 1부터 gap 없음 |
| `event_type` | registered enum |
| `effective_at` | command caller `as_of` 또는 referenced source effective time |
| `command` / `request_id` | public command identity; read-only query는 audit append하지 않으므로 없음 |
| `namespace` | optional market/account_ref/arm/session safe selector |
| `outcome` | `SUCCEEDED|FAILED|BLOCKED` |
| `source_refs` | ordered v16~v20 IDs/hashes |
| `incident_id` | failure가 durable incident를 open/advance하면 exact ref |
| `previous_event_hash` / `event_hash` | global v21 audit chain |

Registered types는 `operator.initialized`, `session.run_succeeded`, `session.run_failed`, `safety.action_observed`, `incident.opened`, `incident.recovery_started`, `incident.resolved`, `approval.issued`, `approval.revoked`, `approval.consumed`, `recovery.failed`, `recovery.succeeded`다. PRD 03 event도 같은 chain에 참여한다.

Read-only `status/report/events/incidents` 호출을 event로 기록하지 않는다. 조회가 state를 바꾸면 동일 snapshot 재현성과 pagination이 깨지기 때문이다.

## Incident Model

Incident는 v16~v20 typed failure나 safety action을 운영자 조사 단위로 묶는 projection이다. V21은 failure severity, scope 또는 kill requirement를 재판정하지 않고 source typed result를 다음 공통 shape로 mapping한다.

Schema `v21.incident.1` 필수 field:

- `incident_id = "inc_" + sha256(trigger_code, source_scope, source_evidence_hash, first_effective_at).hex()`
- `trigger_code`, `severity`, exact source `scope`
- `state`, `first_effective_at`, `last_effective_at`
- source event/evidence refs와 current lifecycle/session heads
- `requires_recovery`, `recovery_mode`, optional `required_action_identity`
- incident event/audit heads

상태 전이는 다음만 허용한다.

```text
OPEN -> RECOVERING -> RESOLVED
OPEN -> RESOLVED
RECOVERING -> OPEN
```

- Safety action이 원인을 즉시 제거하고 별도 manual recovery가 필요 없으면 source reconciliation 후 `OPEN -> RESOLVED`를 같은 transaction에서 기록할 수 있다.
- Manual recovery가 필요한 operation kill/rollback incident는 OPEN을 유지한다.
- Recover 시작은 PRD 03만 `RECOVERING`을 append한다.
- Recover precondition/action/reconciliation failure는 `RECOVERING -> OPEN`과 failed attempt를 append한다.
- Incident close/acknowledge/contain command는 없다. Safety containment는 v20 source action이며 v21 manual 상태가 이를 지연하거나 대체하지 않는다.
- 같은 trigger/scope/evidence의 retry는 같은 incident다. 다른 evidence head나 재발은 새 incident다. Resolved incident를 reopen하지 않는다.

Severity enum `INFO|WARNING|ERROR|CRITICAL`은 source mapping table에 고정한다. V13 router circuit/fallback은 관측 event일 수 있지만 kill incident가 아니며 recovery mode도 없다. V15/v20 kill classifier가 반환한 scope를 확대·축소하지 않는다.

## `status` 계약

Status는 한 SQLite read transaction에서 다음을 합성한다.

- initialization/schema/runtime identity summary
- market별 v16 data/calendar health
- namespace별 v17 account event/projection heads와 reconciliation status
- v19 plan/run state, lease generation/expiry status, last completed step와 run outcome
- v20 adapter/router circuit/lifecycle state와 authorization head
- active incident count/IDs, active/expired/consumed approval counts

Economic value를 표시할 때 money는 `{currency,minor_units}`다. Cross-currency total, consolidated NAV와 account 간 합산은 없다. Raw positions는 `status` 기본 결과에 없고 `report`의 registered aggregate만 제공한다.

## `report` 계약

Report는 inclusive official session 범위와 exact selector를 요구한다. 다음 derived section만 갖는다.

| Section | Source |
| --- | --- |
| `runtime` | v16 identity와 health hashes |
| `sessions` | v19 plans/runs/receipts/closes/run outcomes |
| `paper_execution` | v17 account heads와 v19 decision/risk/fill count·cost aggregate |
| `runtime_lifecycle` | v20 adapter/circuit/mirror/lifecycle/authorization heads |
| `measurement` | 존재하면 v18 `measurement_outcome` aggregate, 실행 결과와 분리 |
| `incidents` | v21 opened/resolved/recovery counts와 IDs |
| `approvals` | issue/revoke/consume counts와 IDs; reason/signature 원문 없음 |

Report는 source IDs/hashes에서 결정적으로 재생성하며 recovery/evidence 입력이 아니다. `--output`은 parent가 존재해야 하고 새 파일만 `O_EXCL` temp→fsync→atomic rename으로 생성한다. Existing target은 `OUTPUT_EXISTS`, exit 4다. Export 실패는 SQLite를 바꾸지 않는다.

## `events`와 Pagination

Events는 v17 account, v19 session, v20 runtime/lifecycle, v21 operator/approval/recovery event를 normalized summary로 조회한다. Source event 종류별 safe mapper가 없으면 payload를 생략하고 ID/hash/type만 반환한다.

Filter는 `--market`, `--account-ref`, `--arm-id`, `--session-date`, `--event-family`, `--severity`, `--after`, `--through`이다. Stable order는 `(effective_at,event_family,source_sequence,event_id)`다. Snapshot head를 첫 page cursor에 binding해 이후 append가 기존 page 구성에 들어오지 않는다.

Cursor body는 `{schema,command,filter_hash,snapshot_heads,last_sort_key}`다. Cursor는 confidentiality/authorization 수단이 아니며 canonical base64url이다. Malformed, 다른 query/database snapshot 또는 unsupported schema cursor는 `CURSOR_INVALID`다.

## `incidents list/show`

`list` filter는 state/severity/market/recovery mode와 time range이며 result summary는 ID, trigger, severity, scope, state, first/last effective time, required action identity만 가진다. `show`는 immutable event history, source refs, current precondition summary, approval/recovery refs를 추가한다.

존재하지 않는 ID는 `INCIDENT_NOT_FOUND`, exit 2다. Incident evidence의 raw payload나 operator signature는 반환하지 않는다. `show` 결과는 현재 v17~v20 head와 incident-open head를 모두 표시해 stale recovery 여부를 알 수 있게 한다.

## Failure/Mutation과 관측 결과

| Failure | CLI result | Durable mutation |
| --- | --- | --- |
| Config/data invalid before init | exit 3, doctor data | 없음 |
| Migration/event/audit chain invalid | exit 6 | 없음, run/recover 차단 |
| Projection mismatch | exit 6 | auto repair 없음 |
| Run cutoff missed | exit 3 | v19 policy가 허용한 terminal receipt + incident만 |
| Active lease | exit 8 | 없음 |
| Adapter/idempotency conflict | exit 4 | failure receipt + deduplicated incident only |
| Risk blocked | exit 0 if valid business result | risk receipt/event, account economics 없음 |
| Router circuit open | exit 0 if quant fallback valid | source circuit state, kill incident 없음 |
| Safety kill/rollback | exit 0 if source action succeeds | v17/v19/v20 action + observed incident atomically |
| Approval-required recovery found during run | exit 5 | source transition 없음, incident OPEN 유지 |

## Acceptance와 Mutation

| Probe | Expected result |
| --- | --- |
| empty init then exact retry | same IDs/heads, row count 불변 |
| changed trust anchor/config init | conflict, metadata 불변 |
| doctor missing database | `NOT_INITIALIZED`, path 생성 0 |
| doctor source chain forgery | exact integrity failure, repair 0 |
| run each commit restart | uninterrupted terminal source/v21 heads와 동일 |
| run lease contention | one owner result, other exit 8 |
| run approval-required path | transition 0, incident OPEN |
| safety action path | approval 조회 없이 immediate commit |
| duplicate incident trigger | incident/event 중복 0 |
| resolved trigger recurrence | new incident ID |
| circuit treated as kill | acceptance FAIL |
| status query repeated | byte-identical, audit mutation 0 |
| report range reordered | same canonical report hash |
| event pagination during append | original snapshot pages unchanged |
| report export existing target | exit 4, file/SQLite 불변 |
| raw source payload mapper attempt | safe summary only, leak 0 |

## CLI

```bash
uv run python -m src.v21.cli init --database data/paper/v17/paper.sqlite3 --config config.yaml --trust-anchor operator-public-key.json --as-of 2026-08-18T00:00:00Z --request-id req_initialize_01
uv run python -m src.v21.cli doctor --database data/paper/v17/paper.sqlite3 --config config.yaml --as-of 2026-08-18T00:00:00Z
uv run python -m src.v21.cli status --database data/paper/v17/paper.sqlite3 --as-of 2026-08-18T00:00:00Z
uv run python -m src.v21.cli prd02-acceptance
```

## 완료 조건

- Init/doctor/run/status/report/events/incidents가 같은 public schema와 SQLite composition root를 사용한다.
- Operator event와 incident가 source evidence를 복제하지 않고 immutable references로 재생성된다.
- Read command는 mutation 0건이고 consistent snapshot/pagination이 deterministic하다.
- Failure message가 운영자가 다음 command를 선택할 수 있는 stable code/remediation을 제공하며 민감 정보가 없다.

## 비목표

- Background health polling, scheduler, daemon과 alert delivery
- External metrics/log vendor와 network export
- Incident 수동 acknowledge/contain/close 또는 ticket integration
- Automatic DB/event repair, JSON restore와 report import
- Cross-account/currency consolidated reporting
