# PRD: v21 PRD 04 Fresh-Install Operator Journey And Acceptance
> **상태**: 📋 구현 예정
> 상위 SPEC: [v21 SPEC](../SPEC.md)

## 의존성

- [PRD 01](prd01-unified-operator-cli.md)의 public executable, schemas, exit와 redaction
- [PRD 02](prd02-status-observability-and-incidents.md)의 init/doctor/run/status/report/events/incidents
- [PRD 03](prd03-approval-and-recovery-workflow.md)의 signed approval, audit와 recovery
- [v16](../../v16/SPEC.md)~[v20](../../v20/SPEC.md)의 public typed services와 standalone acceptance fixtures

## 목표

새 checkout의 한 운영자가 SQLite/JSON을 편집하지 않고 v21 CLI만으로 초기화, 사전 진단, 정상 실행, 조사, incident 확인, 승인 발급, recovery와 최종 보고를 완료함을 실제 subprocess에서 검증한다. 실패 메시지는 다음 행동을 결정할 만큼 구체적이고 안정적이어야 하며 acceptance는 offline·deterministic하고 v22를 요구하지 않는다.

## 구현 표면

| 경로 | 책임 |
| --- | --- |
| `src/v21/acceptance.py` | scenario inventory, checks, mutation와 final report |
| `src/v21/cli_harness.py` | real subprocess invocation/stdout/stderr/exit capture |
| `src/v21/boundaries.py` | network/live/credential/portfolio/later-import/leak traps |
| `src/v21/acceptance_fixtures.py` | immutable cause inputs와 Ed25519 public test vectors |
| `src/v21/faults.py` | named deterministic transaction faults |
| `src/v21/cli.py` | PRD별/canonical acceptance dispatch |

Acceptance 구현은 fixture에서 expected business result를 읽지 않는다. Expected public error code, invariant와 scenario order는 acceptance code의 frozen inventory가 소유한다.

## Canonical Acceptance

```bash
uv run python -m src.v21.cli acceptance
```

이 command는 `v21.acceptance.1` data를 `v21.cli-response.1` envelope에 담아 stdout 한 줄로 출력한다. 모든 check가 PASS면 exit 0, acceptance invariant failure는 `ACCEPTANCE_FAILED`, exit 1이다. PRD별 command는 해당 subset을 동일 방식으로 실행한다.

Acceptance command는 `uv run --frozen --offline python -m src.v21.cli ...` argv로 public command child를 호출한다. Lock/cache만으로 child environment를 만들 수 없으면 standalone acceptance는 실패하고 network fallback하지 않는다. Child environment는 allowlist만 전달하고 `TRADING_ORACLE_ACCEPTANCE_ROOT`로 명시한 temp root를 v16 path service가 acceptance mode에서 허용한다. Production command에는 이 bypass가 존재하지 않는다. Parent acceptance와 child CLI는 `src.v22` 또는 후속 package를 import하지 않는다.

## Acceptance Input Inventory

Fixture는 다음 immutable 원인만 제공한다.

- V16-valid config/runtime identity, KR/US calendar와 complete recorded market inputs
- V20 global schema head `006` database fixture, opening paper namespaces, global `001`~`006` migration inventory와 event commands
- V19 plan/session cutoffs, deterministic decision/risk/fill/mark inputs
- V20 actual adapter recorded inputs, lifecycle gate evidence와 incident trigger causes
- 한 Ed25519 public trust anchor, approval/revoke canonical bodies와 detached deterministic test signatures
- Root-cause-unresolved/resolved evidence, unchanged/drifted manifest와 deterministic replay inputs
- Named crash checkpoint와 expected error/invariant IDs

Fixture에 candidate/selection/fill/P&L/winner/kill scope/authorization decision/incident state/recovery result/report hash를 넣지 않는다. Private key file과 broker/provider credential은 fixture에 없다. V21 standalone acceptance의 valid signature는 body가 사전에 고정된 standard public test vector bytes이며 acceptance 중 signing을 수행하지 않는다. 후속 v22는 public incident output으로 action identity가 완성되는 body에 이 vector를 재사용할 수 없고 독립 operator signer port를 사용해야 한다.

## Test-Only Fault Checkpoint Contract

Fault injection의 유일한 environment key는 `TRADING_ORACLE_V21_FAULT_CHECKPOINT`다. 값은 `AFTER_MIGRATION_METADATA`, `AFTER_SOURCE_COMMIT_BEFORE_OPERATOR_RECEIPT`, `AFTER_ADAPTER_INTAKE`, `AFTER_RESERVATION_FILL`, `AFTER_SESSION_CLOSE`, `AFTER_LIFECYCLE_EVENT`, `AFTER_APPROVAL_ISSUE`, `AFTER_APPROVAL_BINDING`, `AFTER_RECOVERY_ACTION` 중 하나다. Key가 없으면 hook은 비활성이고 empty/unknown/복수 값은 child command를 mutation 전에 exit 2 `CLI_USAGE_ERROR`로 끝낸다. 명명된 boundary 도달 시 buffered checkpoint acknowledgement를 남긴 뒤 `os._exit(70)`으로 종료하며 business branch, commit 여부와 output을 바꾸지 않는다.

Hook은 resolved `TRADING_ORACLE_ACCEPTANCE_ROOT`가 `tempfile.gettempdir()` 아래의 새 mode `0700` directory이고 database, config, request, signature, CWD가 모두 그 root 내부일 때만 활성화된다. Root 밖 path, symlink escape, 일반 project database 또는 acceptance root 없는 invocation에서 key를 설정하면 database open 전에 exit 2이며 checkpoint code에 도달하지 않는다. 이 enum과 제한은 v21이 소유하고 v22는 public child exit/file evidence로만 소비한다.

## Fresh-Install Complete Operator Journey

각 step은 이전 step의 machine output에서 public ID만 추출해 다음 command option으로 전달한다. Database query, Python service import와 JSON state editing으로 ID를 얻지 않는다.

### 1. Fresh preflight

```bash
uv run python -m src.v21.cli doctor --database <temp>/paper.sqlite3 --config <fixture>/config.yaml --as-of 2026-08-18T00:00:00Z
```

Expected: exit 3, `NOT_INITIALIZED`, remediation은 `init` command를 지시하고 database/parent 생성 0건이다. Stdout는 canonical JSON, stderr는 empty다.

### 2. Initialize

```bash
uv run python -m src.v21.cli init --database <temp>/paper.sqlite3 --config <fixture>/config.yaml --trust-anchor <fixture>/operator-public-key.json --as-of 2026-08-18T00:01:00Z --request-id req_fresh_init_01
```

Expected: migrations current, initialized runtime identity, one operator ID, configured account_refs와 receipt. Exact command retry는 byte-identical data와 same heads를 반환하며 row count가 늘지 않는다.

### 3. Ready doctor and status

Doctor는 all blocking checks PASS/READY다. Status는 initialized runtime, v17 account heads, no active run, no incident와 no approval을 한 snapshot에서 반환한다. 두 status 호출은 audit mutation 없이 byte-identical하다.

### 4. Normal session run

```bash
uv run python -m src.v21.cli run --database <temp>/paper.sqlite3 --config <fixture>/config.yaml --market KR --session-date 2026-08-18 --account-ref <init-ref> --arm-id orb --as-of 2026-08-18T05:00:00Z --request-id req_run_kr_01
```

Expected: v20 adapter→v19 session→v17 economics→v20 lifecycle public path가 실행되고 terminal run receipt와 heads를 반환한다. Same request retry는 duplicate adapter/decision/fill/event 0건이다.

### 5. Inspect and report

Status에서 run state/head를 확인하고 events에서 request ID와 source refs를 조회한다. Report는 session range 한 건을 stdout과 명시적 export에 byte-identical하게 생성한다. Report file이나 stdout을 recovery input으로 전달하는 command는 거부된다.

### 6. Trigger safety incident

Recorded invariant failure session을 실행한다. V20 typed classifier가 operation kill과 exact scope를 결정하고 approval 없이 즉시 safety action을 수행한다. Run response와 `incidents list/show`에서 OPEN incident, source evidence, required recovery mode/action identity를 얻는다. Acceptance가 scope/severity를 fixture expected field에서 읽지 않고 v20 classifier result와 v21 projection을 field-by-field 비교한다.

### 7. Recovery blocked before remediation

Incident output의 ID/action을 사용해 approval 없이 recovery를 시도한다. Root cause가 unresolved이므로 exit 7 `RECOVERY_PRECONDITION_FAILED`; incident OPEN, lifecycle/account/approval heads 불변이다. Approval을 먼저 issue해도 failed gate를 우회하지 못함을 별도 검증한다.

### 8. Issue approval

V21 standalone fixture가 사전에 고정한 exact action body와 그 body 전용 detached signature test vector를 `approval issue`에 전달한다. ACTIVE approval ID를 output에서 얻고 `approval list/show`로 signature hash, action binding, expiry와 audit head를 확인한다. Raw key/signature/account는 어느 output에도 없다. Dynamic action identity를 관측하는 v22 journey는 이 fixture를 소비하지 않는다.

### 9. Recover

```bash
uv run python -m src.v21.cli recover --database <temp>/paper.sqlite3 --incident-id <incident-id> --mode OPERATION_KILL_RECOVERY --approval-id <approval-id> --as-of 2026-08-19T00:10:00Z --request-id req_recover_kr_01
```

Expected: unchanged manifest, replay/reconciliation, v20 authorization, approval binding/consume, source recovery와 incident RESOLVED가 atomic하다. Same-day re-entry를 시도하지 않고 effective session semantics를 v20에서 보존한다. Exact retry는 same receipt이며 approval consume/action/audit duplicate가 없다.

### 10. Final verification

Doctor READY, incident RESOLVED, approval CONSUMED, final report와 event timeline의 source/audit heads가 모두 일치한다. Close/reopen 후 같은 status/report hash가 나온다.

## Secondary Journey: Interrupted Session Resume

V19 commit boundary 뒤 child process를 deterministic fault로 종료하고 새 process에서 먼저 `status`를 호출한 뒤 `recover --mode RESUME_SESSION`을 호출한다.

- Harness는 `status` machine output에서 last committed step, lease generation과 source heads를 읽으며 SQLite를 직접 query하지 않는다.
- Active lease면 exit 8이며 자동 wait/takeover하지 않는다.
- Fixture `as_of`가 expiry 이상일 때 v19 takeover/resume public semantics를 사용한다.
- Approval을 받거나 소비하지 않는다.
- Operation kill이 active하면 resume는 exit 7이고 lifecycle recovery를 먼저 요구한다.
- Final source/v21 heads와 report hash는 uninterrupted baseline과 같다.

## Secondary Journey: Approval Revoke

Recovery와 별개의 exact action에 valid approval을 issue하고 `approval show`에서 ACTIVE를 확인한 뒤 signed `approval revoke`를 호출한다. Response, list와 show는 같은 `status_as_of`에서 REVOKED, same revoke retry는 same receipt/latest audit head, source authorization/action mutation은 0건이어야 한다. 이후 해당 ID를 `run` 또는 `recover`에 주입하면 exit 5 `APPROVAL_REVOKED`이며 original issue/revoke history는 그대로다.

## Operator Runbook

### 매 session 전

1. `doctor`를 explicit `--as-of`로 실행한다.
2. Exit 0/`READY`가 아니면 `run`하지 않는다.
3. Exit 6이면 integrity incident를 확인하고 database를 편집하지 않는다.
4. `status`에서 active kill, incident, lease와 이전 run state를 확인한다.
5. 한 market/account/arm/session의 `run`을 unique request ID로 호출한다.

### 정상 run 후

1. Run response의 `run_state`, source heads와 receipt ID를 저장하지 않고 출력 소비자가 기록한다.
2. `status`로 terminal state와 reconciliation을 확인한다.
3. `report`로 필요한 official session 범위를 조회한다.
4. 상세 조사 때만 `events` cursor를 사용한다. Event export를 state로 import하지 않는다.

### 실패 시

1. Process exit와 response `exit_code`가 같은지 확인한다.
2. `error.code`, `remediation`, safe IDs를 읽는다. stderr/traceback/SQLite를 조사 경로로 사용하지 않는다.
3. Exit 2는 요청을 수정한다. Exit 3은 doctor 전제를 복구한다. Exit 4는 stored state를 조회한다.
4. Exit 5는 action identity에 맞는 approval workflow를 사용한다. Exit 6은 모든 mutation을 중단한다.
5. Exit 7은 root cause/evidence/manifest 조건을 해결한다. Exit 8은 lease 상태와 explicit expiry를 확인한다.
6. `incidents show`의 required mode/action identity 외 recovery를 추측하지 않는다.

### Approval과 recovery

1. Incident와 v20 action descriptor에서 canonical issue body를 만든다. Raw account ID/free text/secret을 넣지 않는다.
2. V21 밖의 local signer로 body를 서명한다. Private key를 CLI option/env에 전달하지 않는다.
3. `approval issue` 후 `approval show`로 ACTIVE, exact scope/session/manifest/evidence를 검증한다.
4. Root cause resolved doctor evidence가 PASS한 뒤 `recover`에 approval ID를 명시한다.
5. Recovery 후 incident RESOLVED, approval CONSUMED, doctor READY와 final heads를 확인한다.
6. 더 이상 필요 없는 ACTIVE approval은 signed `approval revoke`로 철회한다. Record를 삭제하지 않는다.

### Integrity failure

Migration hash, immutable event chain 또는 audit chain failure는 v21 automatic recovery 대상이 아니다. Run/recover를 중단하고 신뢰 가능한 SQLite file 운영 복구 절차를 수행한 뒤 `doctor`로 검증한다. V21에는 SQL repair, JSON restore, projection 강제 overwrite와 “ignore integrity” flag가 없다.

## Failure Message Acceptance

Error message는 exact code/category/exit, 고정 한국어 message와 실행 가능한 remediation command family를 가진다. Dynamic safe ID만 details에 있고 message string에 붙이지 않는다.

| Error code | Exit | Required message intent | Required remediation |
| --- | ---: | --- | --- |
| `NOT_INITIALIZED` | 3 | database가 초기화되지 않음 | `init` 실행 |
| `DOCTOR_BLOCKING_FAILURE` | 3 | run 전 blocking check 실패 | `doctor`의 failed check 해결 |
| `CLI_USAGE_ERROR` | 2 | command/option 계약 오류 | `--help`와 canonical syntax 확인 |
| `FORBIDDEN_SENSITIVE_FIELD` | 2 | sensitive input은 허용되지 않음 | public ref/hash만 사용 |
| `LEASE_HELD` | 8 | 다른 valid lease가 있음 | `status`로 expiry 확인 후 명시 재호출 |
| `APPROVAL_REQUIRED` | 5 | exact action approval 필요 | `approval issue` 후 approval ID 전달 |
| `APPROVAL_SIGNATURE_INVALID` | 5 | detached signature/body/anchor 불일치 | canonical body를 active local anchor로 다시 서명 |
| `APPROVAL_REVOKED` | 5 | revoked approval 사용 불가 | 새 exact approval issue |
| `APPROVAL_ALREADY_CONSUMED` | 5 | 다른 action 재사용 불가 | 해당 action용 새 approval issue |
| `EVENT_CHAIN_INVALID` | 6 | immutable event integrity 실패 | mutation 중단, incident/doctor 확인 |
| `RECOVERY_PRECONDITION_FAILED` | 7 | root cause/reconciliation/gate 미충족 | incident show의 failed precondition 해결 |
| `RECOVERY_MANIFEST_DRIFT` | 7 | same-version identity 변경 | old version recovery 금지, 선행 full gate 절차 |
| `INTERNAL_ERROR` | 1 | 예상하지 못한 구현 오류 | redacted diagnostic과 request ID로 개발 조사 |

Acceptance는 각 message의 exact UTF-8 bytes를 golden registry와 비교한다. Locale, terminal width와 exception text가 message를 바꾸면 실패다. Remediation은 존재하지 않는 command, SQL 편집, JSON 수정, credential 입력, web URL과 v22를 지시할 수 없다.

## Complete Failure And Mutation Matrix

| ID | Mutation | Expected public result | State/mutation invariant |
| --- | --- | --- | --- |
| `unknown_command_option` | unknown/abbreviated option | exit 2 `CLI_USAGE_ERROR` | DB open 0 |
| `canonical_response_drift` | key/type/order 변경 | acceptance FAIL | none |
| `stable_exit_drift` | code→exit 변경 | acceptance FAIL | none |
| `fresh_doctor_no_db` | missing DB doctor | exit 3 `NOT_INITIALIZED` | path 생성 0 |
| `init_exact_retry` | same init 10회 | same result/head | duplicate 0 |
| `init_anchor_conflict` | 다른 public key | exit 4 | metadata 불변 |
| `raw_account_input` | forbidden account key/value | exit 2 | bytes/event 0 |
| `secret_error_injection` | exception에 token/key/path | safe error | stdout/stderr/DB leak 0 |
| `run_exact_retry` | reopen 뒤 same request | same source receipt | fill/event duplicate 0 |
| `run_request_conflict` | same ID session 변경 | exit 4 | all heads 불변 |
| `run_lease_held` | active lease 경쟁 | exit 8 | takeover 0 |
| `doctor_event_forgery` | source event byte 변경 | exit 6 | repair/run 0 |
| `doctor_audit_forgery` | v21 audit hash 변경 | exit 6 | approval/recovery 0 |
| `incident_duplicate_trigger` | same typed failure retry | same incident | event duplicate 0 |
| `incident_recurrence` | resolved 후 new evidence | new incident | old history 불변 |
| `circuit_not_kill` | router circuit open | valid fallback/status | kill/recovery incident 0 |
| `safety_without_approval` | operation kill trigger | immediate action | approval lookup/wait 0 |
| `approval_signature_bitflip` | signature 1 bit 변경 | exit 5 | approval row 0 |
| `approval_body_mutation` | signed action/session 변경 | exit 5 | approval row 0 |
| `approval_revoke_then_use` | signed revoke 후 run | exit 5 | source action 0 |
| `approval_second_action` | consumed ID 다른 action | exit 5 | all heads 불변 |
| `approval_gate_bypass` | failed gate + valid approval | exit 7 | approval ACTIVE, action 0 |
| `recovery_root_cause_open` | unresolved evidence | exit 7 | incident OPEN |
| `recovery_manifest_drift` | changed manifest | exit 7 | lifecycle/approval 불변 |
| `recovery_wrong_scope` | incident보다 확대/축소 | exit 7 | unaffected scope 불변 |
| `fault_after_approval_binding` | source action 전 fault | internal failure | binding/consume/action 0, failure audit 1 |
| `fault_after_recovery_action` | resolved event 전 fault | internal failure | source transaction pre-head, failure audit 1 |
| `approval_revoke_happy_retry` | ACTIVE approval signed revoke 2회 | same REVOKED result | revoke event/audit 1, source action 0 |
| `resume_after_each_step` | every v19 commit reopen | baseline hashes | duplicate 0 |
| `report_as_restore` | report path를 input으로 사용 | exit 2 unsupported | SQLite 불변 |
| `events_cursor_cross_query` | cursor filter 변경 | exit 2 | read-only |
| `report_export_collision` | existing target | exit 4 | target/SQLite 불변 |
| `cwd_locale_clock_variation` | CWD/locale/wall clock 변경 | byte-identical | none |
| `network_attempt` | socket/DNS/HTTP/vendor trap | call 0 | acceptance PASS |
| `live_destination_attempt` | broker/order object trap | call/object 0 | all state invariant |
| `credential_access_attempt` | private key/env/keychain trap | access 0 | acceptance PASS |
| `portfolio_mutation` | portfolio before/after | unchanged | existence/bytes/hash same |
| `later_version_import` | `src.v22` import trap | import 0 | acceptance standalone PASS |

Mutation ID는 [v21 SPEC](../SPEC.md)의 semantic probe를 모두 포함하며 PRD별 세부 probe를 확장할 수 있다. Skip, duplicate ID, unexpected success, wrong error/exit 또는 expected failure 뒤 state drift는 top-level failure다.

## Determinism And Restart Matrix

Baseline은 uninterrupted journey다. 다음 commit 직후 child를 종료하고 새 child로 exact request/resume를 실행한다.

- v21 migration/metadata, operator event/receipt
- v20 adapter result/mapping, v19 intake
- v19 risk/reservation/fill/close와 v17 account projection
- v20 lifecycle/authorization event
- v21 approval issue/revoke/consume event
- incident OPEN/RECOVERING/RESOLVED와 recovery receipt

각 restart 결과는 baseline과 source table logical row count, v17/v19/v20/v21 terminal heads, public status/report hash와 approval/incident state가 같다. Mutating restart scenario의 SQLite physical layout, WAL frame placement, rowid와 temp path는 equality 기준이 아니다. 별도로 read command는 read-only connection을 사용해 main DB와 WAL의 frame count/size를 증가시키지 않아야 하며 logical heads/report는 호출 전후 같아야 한다. SHM와 lock bytes는 SQLite의 volatile coordination state이므로 byte 비교에서 제외한다.

## Hard Boundary

- Network socket, DNS, HTTP, vendor SDK call 0건
- Broker client, live destination, real order/external acknowledgement 객체 0건
- Private key, token, credential, environment secret와 OS keychain access 0건
- Web UI, daemon, scheduler, background process/thread 0건
- `src.v22`와 이후 import/call 0건
- V16~v20 leaf CLI subprocess call 0건; public typed service만 composition
- `data/portfolio.json`, tracked config/fixture/source의 존재·bytes·hash 불변
- SQLite 외 state/recovery store 0개; report export는 derived artifact만
- Acceptance temp root 밖 file write 0건

## Acceptance Report

Schema `v21.acceptance.1`은 다음을 가진다.

- `version`, `status`, public contract/schema/error registry versions
- fresh journey와 resume journey step별 command/exit/status/evidence hash
- PRD check counts와 exact mutation inventory/results
- subprocess stdout/stderr schema checks와 byte-determinism checks
- v16~v21 public-service call inventory와 final logical heads
- redaction leak scan counts, network/live/credential/later-import call counts
- portfolio/tracked/temp cleanup boundary results

Array는 stable ID 순이다. Temp absolute path, raw account/key/signature/provider payload, current time와 child PID는 report에 없다. 같은 fixture의 두 clean acceptance 실행은 byte-identical stdout이다.

## CLI

```bash
uv run python -m src.v21.cli prd04-acceptance
uv run python -m src.v21.cli acceptance
```

## 완료 조건

- Fresh install부터 approved recovery와 final report까지 실제 v21 subprocess만으로 완료된다.
- Happy path, expected failure, crash/restart와 failure messages가 strict public 계약으로 검증된다.
- Acceptance는 V22 없이 standalone이며 후속 qualification에 필요한 command/JSON/exit 계약을 전부 제공한다.
- Offline, deterministic, paper-only, single-store와 secret/account/portfolio boundary가 증명된다.

## 비목표

- V22 독립 release qualification과 packaging/install matrix
- Network/live smoke test, broker credential와 external monitoring
- Performance/load/soak benchmark와 multi-host failover
- Private-key signing tool 또는 key lifecycle acceptance
- Web/TUI/operator dashboard
