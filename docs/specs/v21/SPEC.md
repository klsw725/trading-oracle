# Trading Oracle v21 SPEC: Operator Control Plane, Observability And Approval Workflow
> **상태**: 📋 구현 예정

v21은 [v16](../v16/SPEC.md)의 검증된 runtime input, [v17](../v17/SPEC.md)의 단일 SQLite, [v19](../v19/SPEC.md)의 paper session 실행과 [v20](../v20/SPEC.md)의 runtime/lifecycle authorization을 한 운영자용 공개 CLI로 합성한다. 운영자는 SQLite나 JSON을 직접 편집하지 않고 설치 초기화, 진단, 실행, 상태·이벤트·incident 조회, 보고서 생성, human approval 발급·철회와 허용된 복구를 수행한다.

## 0. 구현 완결성 계약

- 공개 executable은 항상 `uv run python -m src.v21.cli <command>`다. Canonical acceptance는 `uv run python -m src.v21.cli acceptance`다.
- v21은 v16~v20의 public typed service를 같은 process에서 호출한다. 선행 버전 CLI를 subprocess로 호출하거나 private repository/table을 우회하지 않는다.
- v21은 strategy, risk, sizing, fill, promotion, rollback, kill, recovery 허용 조건을 만들거나 완화하지 않는다. 특히 authorization predicate와 approval 필요 여부는 v20 소유다.
- v21은 human approval request/issue/revoke/consume projection과 immutable audit event의 수명주기를 소유한다. v20은 approval evidence를 검증하고 `(approval_id, action_identity)`를 authorization decision에 binding한다.
- SQLite는 runtime, account, session, lifecycle, operator event, incident, approval과 recovery receipt의 유일한 durable truth다. JSON 출력, report file, key file, cache와 `data/portfolio.json`은 state 또는 recovery truth가 아니다.
- 기존 `src.v16.cli`~`src.v20.cli`는 개발자·버전 acceptance 표면으로 남는다. 운영자와 후속 독립 qualification 소비자는 v21 CLI만 호출한다.
- Machine command는 성공과 예상 실패 모두 canonical JSON 한 줄을 stdout에 출력하고 stable exit code를 사용한다. 예상 실패의 stderr는 비운다.
- CLI는 secret, private signing material, raw broker/provider account ID, lease owner token, raw provider response, 절대 home/temp path를 출력·event payload 저장·오류 문자열 삽입하지 않는다.
- 모든 mutating command는 `--request-id`와 caller-supplied `--as-of`를 요구한다. Exact retry는 stored receipt를 반환하고 같은 request ID의 다른 body는 mutation 전에 conflict다.
- Acceptance는 OS temp SQLite와 local immutable fixtures만 사용하며 network, credential, live broker, daemon, scheduler, external monitoring vendor와 v22 import 없이 결정적이다.
- Acceptance 전후 tracked files와 `data/portfolio.json`의 존재·bytes·hash가 같아야 한다.
- 이 문서와 네 PRD의 조건을 구현하면 v21은 v22 없이 standalone 완료이며, v22는 v21 executable만 subprocess로 호출해 별도 release qualification을 수행할 수 있다.

## Local PRD Map

| PRD | Local document | Implementation owner | Produces |
| --- | --- | --- | --- |
| PRD 01 | [Unified Operator CLI](prds/prd01-unified-operator-cli.md) | `src/v21/cli.py`, `src/v21/commands.py`, `src/v21/schemas.py`, `src/v21/errors.py`, `src/v21/redaction.py` | stable command, canonical JSON와 exit contract |
| PRD 02 | [Status, Observability And Incidents](prds/prd02-status-observability-and-incidents.md) | `src/v21/operator_service.py`, `src/v21/observability.py`, `src/v21/incidents.py`, `src/v21/reporting.py` | init/doctor/run/status/report/events/incidents |
| PRD 03 | [Approval And Recovery Workflow](prds/prd03-approval-and-recovery-workflow.md) | `src/v21/approvals.py`, `src/v21/approval_repository.py`, `src/v21/audit.py`, `src/v21/recovery.py` | signed approval lifecycle와 recover receipt |
| PRD 04 | [Operator Journey Acceptance](prds/prd04-operator-journey-acceptance.md) | `src/v21/acceptance.py`, `src/v21/boundaries.py`, `src/v21/cli_harness.py` | fresh-install E2E, runbook와 mutation report |

PRD 01→04 순서로 구현한다. PRD 01은 공통 transport 계약, PRD 02는 일반 운영과 관측, PRD 03은 human approval·recovery, PRD 04는 실제 CLI 경계의 standalone 검증만 소유한다.

## 1. 버전 소유권과 합성 경계

| Version | v21이 소비하는 public 책임 | v21이 하지 않는 일 |
| --- | --- | --- |
| v16 | project root, config/runtime identity, calendar/data health | config/data 의미 재해석, source download |
| v17 | migration, transaction, event replay, account projection/reconciliation | 두 번째 store, JSON restore, account 직접 UPDATE |
| v18 | 운영 report에 노출 가능한 advisory measurement read model | candidate activation 또는 policy 변경 |
| v19 | session plan/run/lease/resume/close와 paper execution receipt | intent/fill/risk 규칙 재구현 |
| v20 | adapter run, lifecycle state, incident trigger evidence, authorization predicate와 action binding | approval issue/revoke lifecycle 재구현 |

V21의 command handler는 typed request를 만들고 선행 public service 결과를 하나의 response envelope로 번역한다. Version별 raw model을 stdout에 그대로 직렬화하지 않으며 public schema mapping은 PRD 01에 versioned contract로 고정한다. Leaf/version CLI 명령 이름이나 출력 변화는 v21 public 계약을 바꾸지 않는다.

## 2. 공개 Command Model

공통 syntax는 다음이다.

```text
uv run python -m src.v21.cli <command> [subcommand] [options]
```

| Command | Mutation | 역할 |
| --- | --- | --- |
| `init` | 있음 | SQLite 생성·forward migration, runtime identity와 operator trust anchor 등록 |
| `doctor` | 없음 | config/data/store/event/projection/session/lifecycle/approval chain 진단 |
| `run` | 있음 | 한 explicit market session을 v20→v19→v17 public path로 실행 또는 resume |
| `status` | 없음 | 현재 system/market/account/arm/session/lifecycle 요약 |
| `report` | 없음 | 지정 session 범위의 deterministic 운영 보고서 |
| `events` | 없음 | redacted append-only event timeline 조회 |
| `incidents list` | 없음 | incident cursor 목록 |
| `incidents show` | 없음 | 한 incident와 evidence/recovery 상태 조회 |
| `approval issue` | 있음 | 서명 검증 후 exact action-bound approval 발급 |
| `approval list` | 없음 | redacted approval 목록 |
| `approval show` | 없음 | 한 approval, audit와 binding 조회 |
| `approval revoke` | 있음 | 아직 소비되지 않은 approval 철회 |
| `recover` | 있음 | incident가 허용하는 v19 resume 또는 v20 recovery action 실행 |
| `prd01-acceptance`~`prd04-acceptance` | temp 내부만 | PRD별 standalone 검증 |
| `acceptance` | temp 내부만 | v21 전체 offline deterministic 검증 |

`init`, `run`, `approval issue`, `approval revoke`, `recover` 외 command는 read-only다. `report --output`은 명시적 export 파일만 원자적으로 쓸 수 있으나 SQLite를 바꾸지 않으며 stdout의 report와 같은 canonical bytes여야 한다. 기본 동작은 파일을 만들지 않는다.

## 3. 공통 입력 계약

- Database 기본 경로는 `<project_root>/data/paper/v17/paper.sqlite3`이며 `--database`로 root 내부 경로를 지정할 수 있다. Acceptance만 temp root를 허용한다.
- 상대 config/database/export 경로는 v16 project root 기준이다. Symlink escape와 root 밖 production path는 거부한다.
- `--as-of`는 UTC RFC 3339 `YYYY-MM-DDTHH:MM:SSZ`, `--session-date`는 ISO date다. Wall clock fallback은 없다.
- `--market`은 `KR|US`, selector currency는 v16/v17 namespace에서 파생한다. `ALL` mutating run은 없다.
- Public account selector는 raw account ID가 아니라 `account_ref = acct_<sha256 prefix 16>`이다. CLI는 raw ID 입력도 받지 않으며 초기화된 local paper namespace 목록에서 ref를 해석한다.
- Mutating request ID는 `req_[a-z0-9_-]{8,64}`이고 request body, command name, schema version과 함께 semantic key를 만든다.
- JSON input은 UTF-8 strict object, duplicate key·unknown key·non-finite number 금지다. Inline JSON option은 금지하고 `--request PATH`만 허용한다. `-`는 stdin 한 개를 뜻한다.
- Secret이나 raw account ID로 분류된 key가 input에 나타나면 parse 단계에서 `FORBIDDEN_SENSITIVE_FIELD`로 거부하며 bytes를 log에 남기지 않는다.

## 4. Canonical JSON 출력 계약

모든 machine response는 `v21.cli-response.1`이며 top-level key 순서는 다음과 같다.

```json
{"schema_version":"v21.cli-response.1","command":"status","request_id":null,"status":"OK","exit_code":0,"data":{},"error":null,"meta":{"contract_version":"v21.operator-cli.1","redaction":"v21.redaction.1"}}
```

- `status`는 `OK|FAILED|BLOCKED|ERROR`다.
- `data`는 command별 strict schema object, `error`는 성공 때 `null`이고 실패 때 `{code,category,message,remediation,details}`다.
- `message`와 `remediation`은 등록된 한국어 template이다. Exception text, SQL, traceback, input bytes와 dynamic path를 이어 붙이지 않는다.
- Object key는 schema order, map key는 lexicographic, set 성격 배열은 documented stable key로 정렬한다. UTF-8, compact separators, trailing newline 하나를 사용한다.
- Decimal은 canonical decimal string, money는 currency와 integer minor units, hash는 `sha256:<64 lowercase hex>`, timestamp는 UTC `Z` 형식이다.
- Pagination은 `limit` 1~200과 opaque `next_cursor`를 사용한다. Cursor는 signed secret이 아니라 query identity와 last stable key의 canonical base64url encoding이며 다른 query에서 재사용하면 실패한다.
- `--help`만 사람용 text stdout와 exit 0을 허용한다. Machine command는 terminal 여부와 무관하게 JSON만 출력한다.

## 5. Stable Exit Code

| Exit | Category | 의미 | 재시도 |
| ---: | --- | --- | --- |
| 0 | `SUCCESS` | 요청 완료 또는 exact retry의 stored success | 불필요 |
| 1 | `INTERNAL` | 구현 결함·예상하지 못한 runtime failure | 원인 수정 후 |
| 2 | `USAGE_INPUT` | command/option/schema/path/selector 입력 오류 | 요청 수정 후 |
| 3 | `PRECONDITION` | 미초기화, health/cutoff/reconciliation 전제 실패 | 진단·전제 복구 후 |
| 4 | `CONFLICT` | idempotency, immutable state, concurrent lease conflict | 상태 조회 후 |
| 5 | `APPROVAL` | approval 필요·invalid·revoked·consumed·signature 실패 | 올바른 approval 후 |
| 6 | `INTEGRITY` | migration/event/projection/audit chain 손상 | run 중단, incident 확인 |
| 7 | `RECOVERY_BLOCKED` | v20 predicate 또는 recovery evidence가 복구 금지 | 원인 해소 후 새 evidence |
| 8 | `BUSY` | 유효 lease 또는 SQLite busy timeout | 명시적 후속 호출 |

Error code 하나는 정확히 한 exit category에 속한다. 새 세부 error code 추가는 minor schema evolution이지만 기존 code의 exit와 의미를 바꿀 수 없다. Expected failure는 canonical JSON stdout, empty stderr다. Exit 1만 redacted 고정 문구를 stderr에도 한 줄 낼 수 있다.

## 6. Structured Local Observability

V21은 같은 SQLite migration에 다음 append-only/control-plane 영역을 추가한다.

- `operator_events`: command request/result, audit chain과 redacted evidence refs
- `operator_receipts`: mutating semantic request의 stored outcome
- `incidents`, `incident_events`: OPEN→RECOVERING→RESOLVED lifecycle projection
- `approval_records`, `approval_events`, `approval_action_bindings`: signed approval lifecycle와 v20 binding refs
- `recovery_attempts`: precondition, v20 authorization, action receipt와 terminal result

관측 event는 business event를 복제하지 않고 v16~v20 event/receipt ID와 hash를 참조한다. `status`, `report`, `events`, `incidents`는 한 read transaction의 consistent SQLite snapshot에서 생성한다. Log file, stdout scrape, metrics daemon과 external vendor는 truth가 아니다.

V21은 v20 global schema head `006`에 `007_operator_control_plane.sql`, `008_approval_recovery.sql`을 적용해 head `008`을 만든다. `schema_migrations`와 `PRAGMA user_version`은 v17~v21 단일 global inventory이며 version별 counter가 아니다. `approval_action_bindings`는 v20 `authorization_checks`의 immutable check ID/hash와 v21 approval consumption을 연결하는 replay projection일 뿐, action authorization을 다시 판정하는 두 번째 truth가 아니다.

Severity는 `INFO|WARNING|ERROR|CRITICAL`, outcome은 `SUCCEEDED|FAILED|BLOCKED`로 고정한다. Incident는 등록된 trigger mapper가 v16~v20 typed failure를 분류한 관측 projection이며 kill scope나 severity business rule을 다시 계산하지 않는다.

## 7. Approval와 Trust Model

단일 local operator trust anchor는 Ed25519 public key다. `init --trust-anchor PATH`가 strict public-key document를 읽고 key fingerprint와 canonical public bytes를 SQLite metadata에 한 번 등록한다. Fingerprint와 `key_id`는 모두 `sha256("trading-oracle:v21:trust-anchor:1" || raw_public_key)`인 동일 값이며 public schema field name은 문맥에 따라 `trust_anchor_fingerprint`를 사용한다. Private key 생성·보관·읽기·서명은 v21 범위 밖이며 CLI는 detached signature file만 검증한다.

- Trust anchor 변경, 다중 signer, delegation, quorum과 remote identity provider는 지원하지 않는다.
- `operator_id`는 fingerprint에서 파생한 `op_<16 hex>` pseudonym이며 key bytes나 filesystem path를 출력하지 않는다.
- Approval signature 대상은 domain separator `trading-oracle:v21:approval:1`과 canonical approval body bytes다.
- Approval body는 action class/identity, namespace, exact manifest/evidence hashes, effective session, expiry, reason code와 request ID에 binding된다.
- Free-text reason은 받지 않는다. 등록된 reason code만 사용해 secret·account 정보가 audit에 들어오는 경로를 없앤다.
- Revoke도 별도 domain separator와 approval ID, revoke reason, `as_of`, request ID를 서명한다.
- Issue/revoke/consume event와 previous hash는 immutable하다. Revoked/expired approval은 사용할 수 없고 consumed approval은 같은 action의 exact retry 외 재사용할 수 없다.
- Approval은 v20 gate, reconciliation, manifest equality, retirement와 kill 조건을 대체하지 않는다. V20 predicate가 `NOT_REQUIRED`인 safety action은 approval을 기다리지 않는다.

## 8. Incident와 Recovery Workflow

```text
mutating command의 typed failure
-> redacted operator event
-> registered incident OPEN
-> 원인 제거 및 doctor evidence PASS
-> recover dry validation
-> v20 authorization predicate
-> approval required이면 exact ACTIVE approval binding
-> RECOVERING event
-> v19 resume 또는 v20 registered recovery service
-> reconciliation PASS
-> RESOLVED event와 immutable recovery receipt
```

Read-only `doctor` failure는 이 workflow를 시작하지 않고 같은 canonical incident identity candidate와 blocking evidence만 반환한다. Durable incident는 `run`, `recover` 등 mutating command가 같은 failure를 관측할 때만 append한다.

`recover`는 `RESUME_SESSION`, `OPERATION_KILL_RECOVERY`, `SAME_VERSION_ROLLBACK_RECOVERY`만 받는다. `RESUME_SESSION`은 v19 receipt 이후 resume이며 active kill이 있으면 차단된다. 나머지 두 mode의 허용 조건과 approval requirement는 v20 결과를 그대로 사용한다. Changed manifest, retired version, failed reconciliation, 미해소 root cause, same-day re-entry와 scope mismatch는 approval이 있어도 차단한다.

Migration/hash-chain 손상과 immutable event corruption은 CLI가 자동 repair하거나 DELETE/UPDATE하지 않는다. `doctor`와 incident는 fail closed evidence를 제공하고 `run/recover`를 차단한다. V21은 JSON restore나 임의 projection overwrite를 복구로 부르지 않는다.

## 9. Redaction 계약

| 분류 | 입력 허용 | SQLite 저장 | stdout/stderr |
| --- | --- | --- | --- |
| Private signing key, token, credential | 금지 | 금지 | 금지 |
| Raw broker/provider account ID | 금지 | 금지 | 금지 |
| Public paper `account_ref` | 허용 | 허용 | 허용 |
| Trust-anchor public key bytes | init만 | metadata에 허용 | fingerprint만 |
| Detached signature bytes | issue/revoke만 | signature hash와 검증 결과만 | hash만 |
| Absolute home/temp/database path | option으로 허용 | root-relative label만 | redacted label만 |
| Raw provider response/prompt | 금지 | 선행 hash ref만 | hash ref만 |
| Exception/SQL/traceback | 내부만 | 금지 | fixed internal code만 |

Redaction은 serialization 직전 masking이 아니라 parse allowlist와 typed safe model로 강제한다. 금지 필드 탐지 failure 자체도 원문 key/value를 출력하지 않고 JSON pointer의 schema-safe 위치와 `FORBIDDEN_SENSITIVE_FIELD`만 제공한다.

## 10. Failure와 Mutation 계약

| Probe | Mutation | Required result |
| --- | --- | --- |
| `unknown_command_option` | 미등록 command/option | `CLI_USAGE_ERROR`, exit 2 |
| `response_schema_drift` | key/order/type 변경 | acceptance FAIL |
| `exit_mapping_drift` | 같은 error의 exit 변경 | acceptance FAIL |
| `raw_account_input` | account number 형태/key 주입 | `FORBIDDEN_SENSITIVE_FIELD`, bytes 미저장 |
| `secret_output_attempt` | token/key/signature/raw account를 error에 주입 | redacted output, leak 0 |
| `init_duplicate` | same anchor/config/database 재호출 | stored receipt, row 불변 |
| `init_anchor_conflict` | initialized DB에 다른 anchor | `TRUST_ANCHOR_IMMUTABLE`, exit 4 |
| `doctor_corrupt_chain` | event hash 변경 | exit 6, run mutation 0 |
| `run_request_conflict` | same request ID, 다른 session/body | exit 4, state 불변 |
| `run_lease_held` | active v19 lease | exit 8, takeover 0 |
| `events_cursor_cross_query` | 다른 filter cursor 재사용 | exit 2 |
| `incident_duplicate_trigger` | 같은 trigger/evidence 재관측 | 같은 OPEN incident, event 중복 0 |
| `approval_bad_signature` | body/signature/key 불일치 | exit 5, approval row 0 |
| `approval_wrong_binding` | action/session/manifest 변경 | exit 5, authorization/lifecycle 불변 |
| `approval_revoke_consumed` | consumed approval 철회 | exit 4, audit head 불변 |
| `approval_reuse` | 다른 action에 consumed ID 사용 | exit 5, recovery 0 |
| `approval_bypasses_gate` | failed v20 gate와 valid signature | exit 7, state 불변 |
| `safety_waits_approval` | kill/rollback을 approval 대기로 변경 | acceptance FAIL |
| `recovery_root_cause_open` | doctor evidence 실패 상태 recover | exit 7, incident OPEN 유지 |
| `recovery_manifest_drift` | same-version recovery hash 변경 | exit 7, lifecycle 불변 |
| `recovery_fault_after_binding` | action 전 deterministic fault | approval binding/recovery/action rollback, deduplicated `recovery.failed` audit 1건 |
| `report_as_state` | JSON report로 restore 시도 | unsupported input, SQLite 불변 |
| `network_attempt` | socket/DNS/HTTP/vendor trap | 호출 0건 |
| `live_or_credential_attempt` | broker/order/private key open trap | 호출·객체 0건 |
| `portfolio_mutation` | 전후 `data/portfolio.json` 감시 | 존재·bytes·hash 불변 |
| `later_version_import` | `src.v22` import trap | import 0건 |

## 11. 의존성과 비목표

의존성은 Python 표준 라이브러리, lockfile의 검증된 crypto/serialization dependency, v16~v20 public typed services, v21 package와 local fixtures다. V21은 선행 CLI나 v22를 import/subprocess 호출하지 않는다.

다음은 v21 비목표다.

- 새 strategy, parameter, risk, sizing, fill, promotion, rollback, kill, authorization 또는 recovery 허용 규칙
- Web UI, TUI, daemon, background scheduler, external monitoring/logging vendor
- Live broker, real order, external account, broker/provider credential와 network-required command
- Multi-user, multi-key, quorum, role, delegation, remote approval, multi-host와 distributed lock
- Trust-anchor rotation·key recovery·private key custody
- JSON backup/restore, 두 번째 database, log-file state와 `data/portfolio.json` import/mutation
- V22 release qualification 구현 또는 v22 package import

## 12. Acceptance Criteria

- 한 운영자가 v21 CLI만으로 init→doctor→run→status→events/report→incident→approval→recover를 완료한다.
- 모든 공개 command, strict input, canonical output schema, stable error/exit mapping과 redaction이 고정된다.
- V16~v20 public service를 합성하고 leaf CLI/table 직접 접근 없이 같은 SQLite transaction discipline을 지킨다.
- SQLite만 durable truth이며 report/audit projection은 immutable event와 receipt에서 재생성된다.
- V20이 authorization predicate를, v21이 signed human approval record lifecycle을 소유하는 경계가 모든 recovery path에서 유지된다.
- Approval signature, immutable trust anchor, exact action binding, revoke/expiry/consume와 retry가 deterministic하게 검증된다.
- Integrity failure와 failed recovery condition은 mutation 전에 차단되고 safety transition은 approval 때문에 지연되지 않는다.
- Fresh-install와 failure-message acceptance가 offline·deterministic하고 network/live/credential/v22 없이 통과한다.
- Acceptance가 `data/portfolio.json`과 tracked files를 변경하지 않는다.
- V22가 문서화된 v21 executable과 JSON/exit 계약만으로 독립 subprocess qualification을 작성할 수 있다.
