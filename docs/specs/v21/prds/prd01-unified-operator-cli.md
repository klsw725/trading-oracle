# PRD: v21 PRD 01 Unified Operator CLI, Schemas And Exit Codes
> **상태**: 📋 구현 예정
> 상위 SPEC: [v21 SPEC](../SPEC.md)

## 의존성

- [v16 Leaf CLI Contract](../../v16/prds/prd03-leaf-cli-contract.md)의 canonical JSON, path와 deterministic error 원칙
- [v17 SPEC](../../v17/SPEC.md)의 SQLite transaction, semantic idempotency와 reconciliation
- [v19 SPEC](../../v19/SPEC.md)의 plan/run/lease/receipt identity
- [v20 SPEC](../../v20/SPEC.md)의 adapter/lifecycle public models와 authorization result

## 목표

운영자와 subprocess consumer가 하나의 stable executable만 호출하도록 command grammar, strict input, canonical response, error registry, exit code와 redaction을 고정한다. V16~v20 leaf CLI는 개발용으로 유지하지만 v21 public response에 노출하지 않는다.

## 구현 표면

| 경로 | 책임 |
| --- | --- |
| `src/v21/cli.py` | parser, public `main()`, exit dispatch |
| `src/v21/commands.py` | command registry와 typed handler routing |
| `src/v21/schemas.py` | request/response command schema |
| `src/v21/canonical.py` | canonical JSON와 hashing |
| `src/v21/errors.py` | stable public error→exit registry |
| `src/v21/redaction.py` | safe typed output와 forbidden-field detection |
| `src/v21/idempotency.py` | mutating request semantic key와 stored receipt |

## Public Executable 계약

```bash
uv run python -m src.v21.cli <command> [subcommand] [options]
```

`src.v21.cli` import는 stdout/stderr/file/SQLite mutation 0건이다. `main(argv: Sequence[str] | None) -> int`만 process exit를 결정한다. Shell wrapper, alternate executable name과 legacy alias는 v21 public contract가 아니다.

### Command registry

| Canonical command key | Syntax | Request schema | Response data schema |
| --- | --- | --- | --- |
| `init` | `init --database PATH --config PATH --trust-anchor PATH --as-of TS --request-id ID` | `v21.init-request.1` | `v21.init-result.1` |
| `doctor` | `doctor --database PATH --config PATH --as-of TS` | `v21.doctor-request.1` | `v21.doctor-result.1` |
| `run` | `run --database PATH --config PATH --market M --session-date DATE --account-ref REF --arm-id ID [--approval-id ID] --as-of TS --request-id ID` | `v21.run-request.1` | `v21.run-result.1` |
| `status` | `status --database PATH [selectors] --as-of TS` | `v21.status-request.1` | `v21.status-result.1` |
| `report` | `report --database PATH --from-session DATE --through-session DATE [selectors] --as-of TS [--output PATH]` | `v21.report-request.1` | `v21.report-result.1` |
| `events` | `events --database PATH [filters] [--cursor C] [--limit N] --as-of TS` | `v21.events-request.1` | `v21.events-result.1` |
| `incidents.list` | `incidents list --database PATH [filters] [--cursor C] [--limit N] --as-of TS` | `v21.incident-list-request.1` | `v21.incident-list-result.1` |
| `incidents.show` | `incidents show --database PATH --incident-id ID --as-of TS` | `v21.incident-show-request.1` | `v21.incident-show-result.1` |
| `approval.issue` | `approval issue --database PATH --request PATH --signature PATH --as-of TS --request-id ID` | `v21.approval-issue-request.1` | `v21.approval-result.1` |
| `approval.list` | `approval list --database PATH [filters] [--cursor C] [--limit N] --as-of TS` | `v21.approval-list-request.1` | `v21.approval-list-result.1` |
| `approval.show` | `approval show --database PATH --approval-id ID --as-of TS` | `v21.approval-show-request.1` | `v21.approval-show-result.1` |
| `approval.revoke` | `approval revoke --database PATH --request PATH --signature PATH --as-of TS --request-id ID` | `v21.approval-revoke-request.1` | `v21.approval-result.1` |
| `recover` | `recover --database PATH --incident-id ID --mode MODE [--approval-id ID] --as-of TS --request-id ID` | `v21.recovery-request.1` | `v21.recovery-result.1` |
| `acceptance` | `acceptance` | no external input | `v21.acceptance.1` |

PRD acceptance command도 같은 envelope를 사용한다. Unknown command/subcommand/option, duplicate option, positional argument, abbreviation과 필수 option 누락은 argparse 기본 문구 대신 `CLI_USAGE_ERROR`, exit 2다. `--help`는 text/exit 0이며 database를 열지 않는다.

## 공통 Option과 Selector

| Option | Contract |
| --- | --- |
| `--database` | project-root-relative 또는 root 내부 absolute `.sqlite3`; symlink escape 금지 |
| `--config` | v16이 허용하는 root 내부 YAML path |
| `--as-of` | explicit UTC second precision RFC 3339 `Z`; wall clock fallback 금지 |
| `--request-id` | `req_[a-z0-9_-]{8,64}`; mutation command 필수 |
| `--market` | exact `KR|US`; case folding 없음 |
| `--account-ref` | `acct_[0-9a-f]{16}` public pseudonym; raw account 입력 금지 |
| `--arm-id` | initialized registered opaque arm ID |
| `--session-date` | exact ISO date and v16 official calendar member |
| `--cursor` | 같은 command/filter/database identity에서만 사용 가능한 opaque cursor |
| `--limit` | decimal integer 1~200; default 50 |
| `--output` | report 전용 root 내부 path; overwrite 금지, atomic create |

Selector를 생략할 수 있는 read command는 전체 initialized paper namespace를 stable `(market,account_ref,arm_id)` 순서로 반환한다. Mutating command는 wildcard, `ALL`, comma list를 허용하지 않는다.

`doctor`, `status`, output 없는 `report`, `events`, `incidents list/show`, `approval list/show`는 SQLite URI `mode=ro` connection과 `PRAGMA query_only=ON`을 사용한다. Read command가 read-write connection으로 열거나 migration, audit append, checkpoint를 수행하면 계약 위반이다. `report --output`도 같은 read-only SQLite snapshot을 사용하고 export 파일만 별도 원자 생성한다.

## Strict File Input

Approval request와 detached signature는 별도 file이다. `--request -` 또는 `--signature -` 중 하나만 stdin일 수 있고 둘 다 `-`이면 usage failure다. Inline JSON, environment variable expansion과 command substitution을 parser가 제공하지 않는다.

JSON parser 규칙:

- UTF-8, top-level object, exact `schema_version`
- duplicate/unknown key, trailing bytes, BOM, comments, NaN/Infinity 금지
- integer/boolean/string의 암묵적 coercion 금지
- RFC 3339/decimal/hash/enum은 lexical canonical form만 허용
- file size max 64 KiB, signature document max 4 KiB
- forbidden sensitive key는 depth와 무관하게 parse 후 즉시 전체 거부

## Mutating Request Idempotency

`semantic_key = sha256(command_key, request_id, request_schema_version, namespace)`이고 `request_hash`는 normalized body와 explicit options를 포함한다. Receipt 조회→same hash stored result 또는 conflict 판정→public service mutation→operator event/receipt append는 같은 SQLite transaction이다.

- Same semantic key + same request hash: original response data와 immutable receipt ID 반환, 새 event 0건
- Same semantic key + different hash/command/namespace: `OPERATOR_REQUEST_CONFLICT`, exit 4, write 0건
- Prior failed request가 durable state를 만들지 않았다면 같은 request ID를 다른 body로 재사용할 수 없다. Failure receipt도 conflict 방지를 위해 저장한다.
- Internal error로 transaction이 rollback된 경우 receipt도 남지 않는다. Caller는 같은 exact request를 재시도한다.

## Canonical Response Envelope

Schema `v21.cli-response.1`의 top-level key는 아래 순서와 타입을 고정한다.

| Key | Type | Contract |
| --- | --- | --- |
| `schema_version` | string | exact `v21.cli-response.1` |
| `command` | string | registry의 canonical key |
| `request_id` | string/null | mutation의 caller ID 또는 null |
| `status` | enum | `OK|FAILED|BLOCKED|ERROR` |
| `exit_code` | integer | actual process exit와 동일 |
| `data` | object/null | success면 command schema, failure면 null 또는 safe partial diagnostics |
| `error` | object/null | success면 null, failure면 exact error object |
| `meta` | object | contract/redaction versions만 포함 |

Error object `v21.cli-error.1`:

```json
{"code":"APPROVAL_REQUIRED","category":"APPROVAL","message":"이 작업에는 유효한 승인이 필요합니다.","remediation":"approval issue로 정확히 바인딩된 승인을 발급한 뒤 같은 요청을 다시 실행하십시오.","details":{"action_identity":"sha256:...","incident_id":"inc_..."}}
```

`details`는 error code별 allowlist schema이고 arbitrary exception context가 아니다. `meta`는 정확히 `{"contract_version":"v21.operator-cli.1","redaction":"v21.redaction.1"}`이다. Receipt time, host, PID, cwd, temp/database absolute path는 없다.

## Command Data 최소 Schema

| Schema | 필수 field |
| --- | --- |
| `v21.init-result.1` | `database_label`, global `schema_head=008`, `runtime_identity`, `operator_id`, `trust_anchor_fingerprint`, `account_refs`, `receipt_id` |
| `v21.doctor-result.1` | `overall`, ordered `checks`, `blocking_incident_ids`, `evidence_hash` |
| `v21.run-result.1` | namespace, `plan_id`, `run_id`, `run_state`, `last_step`, counts, v17/v19/v20 heads, `receipt_id` |
| `v21.status-result.1` | `initialized`, health, namespace states, active incidents, pending approvals, heads |
| `v21.report-result.1` | range, namespace summaries, run/incident/approval counts, heads, `report_hash` |
| `v21.events-result.1` | filters, redacted `items`, `next_cursor`, snapshot head |
| `v21.incident-list-result.1` | filters, summaries, `next_cursor`, snapshot head |
| `v21.incident-show-result.1` | incident identity/state/scope, evidence refs, event history, recovery refs |
| `v21.approval-result.1` | approval ID, `status_as_of`, current `status`, action identity, expiry, signature hash, latest lifecycle event/audit head와 command receipt ID |
| `v21.approval-list-result.1` | filters, redacted summaries, `next_cursor`, snapshot head |
| `v21.approval-show-result.1` | approval body safe fields, lifecycle events, action binding refs |
| `v21.recovery-result.1` | incident/mode, precondition and authorization result, approval binding, action receipt, final state/heads |

`outcome`이라는 unqualified field는 금지한다. v18 결과는 `measurement_outcome`, v19 결과는 `run_outcome`이다. `resume`은 `execution_resume`, v20 복귀는 `lifecycle_recovery`, rollback은 `lifecycle_rollback`으로 출력한다.

`approval issue` exact retry는 original issue receipt가 아니라 query `as_of`의 current lifecycle status와 latest lifecycle/audit head를 반환하고 `stored_issue_receipt_id`로 최초 issue를 참조한다. `approval revoke`는 revoke command receipt를 반환한다. List/show/issue/revoke의 `status`와 `status_as_of` 계산은 PRD 03의 동일 reducer를 사용하며 EXPIRED derived view가 event를 만들지 않는다.

## Canonical Serialization

- JSON UTF-8, `ensure_ascii=false`, compact `,`/`:` separators, trailing newline 하나
- Schema-declared object order; free map은 Unicode code point lexicographic order
- Event는 `(effective_at,event_family,sequence,event_id)`, namespace는 `(market,account_ref,arm_id)`, check는 `check_id` 순
- No set-derived or SQL implicit row order
- Decimal은 string, integer minor units만 money, timestamp UTC `Z`, Unicode NFC
- Response bytes hash는 envelope에 넣지 않는다. `report_hash`는 schema version과 `data` canonical bytes만 대상으로 하며 request ID/meta는 제외한다.
- Same SQLite snapshot, request와 `as_of`는 locale/CWD/terminal width/PYTHONHASHSEED와 무관하게 byte-identical하다.

## Error와 Exit Registry

| Exit | Category | 대표 code |
| ---: | --- | --- |
| 0 | `SUCCESS` | `OK`, `STORED_RESULT` |
| 1 | `INTERNAL` | `INTERNAL_ERROR` |
| 2 | `USAGE_INPUT` | `CLI_USAGE_ERROR`, `INPUT_SCHEMA_INVALID`, `PATH_OUTSIDE_ROOT`, `FORBIDDEN_SENSITIVE_FIELD`, `CURSOR_INVALID` |
| 3 | `PRECONDITION` | `NOT_INITIALIZED`, `DOCTOR_BLOCKING_FAILURE`, `CUTOFF_MISSED`, `RECONCILIATION_REQUIRED` |
| 4 | `CONFLICT` | `OPERATOR_REQUEST_CONFLICT`, `TRUST_ANCHOR_IMMUTABLE`, `IMMUTABLE_STATE_CONFLICT` |
| 5 | `APPROVAL` | `APPROVAL_REQUIRED`, `APPROVAL_SIGNATURE_INVALID`, `APPROVAL_REVOKED`, `APPROVAL_EXPIRED`, `APPROVAL_ALREADY_CONSUMED` |
| 6 | `INTEGRITY` | `MIGRATION_INTEGRITY_FAILED`, `EVENT_CHAIN_INVALID`, `PROJECTION_INTEGRITY_FAILED`, `AUDIT_CHAIN_INVALID` |
| 7 | `RECOVERY_BLOCKED` | `RECOVERY_PRECONDITION_FAILED`, `RECOVERY_MANIFEST_DRIFT`, `LIFECYCLE_TRANSITION_INVALID` |
| 8 | `BUSY` | `LEASE_HELD`, `STORE_BUSY` |

선행 service error는 semantic mapping table을 통해 한 public code로 번역한다. Raw `V17Error` class명이나 SQLite message를 노출하지 않는다. 등록되지 않은 선행 error는 `INTERNAL_ERROR`, exit 1이며 자동으로 exit 2로 축소하지 않는다.

## Redaction과 Sensitive Input 차단

금지 key token은 `secret`, `token`, `password`, `credential`, `private_key`, `account_number`, `broker_account`, `authorization_header`다. Case/underscore/hyphen normalization 후 탐지한다. Signature file의 `signature`만 승인된 boundary input이며 raw bytes 대신 hash와 valid boolean만 저장한다.

Public safe identifiers:

- Account: `acct_` + canonical internal paper account ID hash 앞 16 hex
- Operator: `op_` + trust-anchor fingerprint 앞 16 hex
- Database: project-root-relative POSIX label
- Path: registered label 또는 root-relative POSIX path
- Evidence: full `sha256:` hash

해시 pseudonym은 raw ID를 복원할 수 없도록 domain-separated SHA-256를 사용한다. 같은 raw ID를 일반 SHA-256로 직접 노출하지 않는다. Redaction 이후 충돌하면 suffix를 붙이는 대신 init을 fail closed 한다.

## Failure와 Mutation

| Probe | Expected result | State invariant |
| --- | --- | --- |
| unknown/abbreviated command | `CLI_USAGE_ERROR`, exit 2 | database open 0 |
| duplicate/missing option | `CLI_USAGE_ERROR`, exit 2 | database open 0 |
| malformed/duplicate JSON | `INPUT_SCHEMA_INVALID`, exit 2 | write 0 |
| forbidden sensitive nested field | `FORBIDDEN_SENSITIVE_FIELD`, exit 2 | input bytes/event 0 |
| raw account option | `FORBIDDEN_SENSITIVE_FIELD`, exit 2 | account lookup 0 |
| response key reorder/drop/add | PRD acceptance FAIL | none |
| error exit remap | PRD acceptance FAIL | none |
| same request exact retry | exit 0, stored receipt | row/head 불변 |
| same request changed body | `OPERATOR_REQUEST_CONFLICT`, exit 4 | all heads 불변 |
| cursor filter/database swap | `CURSOR_INVALID`, exit 2 | read-only |
| exception contains secret/path | `INTERNAL_ERROR`, redacted | leak 0 |
| help invocation | text, exit 0 | import/open/write 0 |

## CLI

```bash
uv run python -m src.v21.cli prd01-acceptance
uv run python -m src.v21.cli acceptance
```

## 완료 조건

- 모든 public command가 하나의 parser, serializer, error registry와 redaction boundary를 사용한다.
- Command별 strict input/data schema와 실제 exit code가 response의 `exit_code`와 일치한다.
- Expected failure는 canonical JSON stdout와 empty stderr, internal error는 secret 없는 고정 diagnostic을 제공한다.
- 후속 consumer가 선행 leaf CLI나 Python model을 알지 않고 v21 response만 parse할 수 있다.

## 비목표

- Interactive prompt, shell completion, TUI, web API
- Legacy CLI alias 또는 선행 CLI output 호환 layer
- Streaming JSON, NDJSON, log tail
- Raw SQL/debug/traceback 출력
- V22 subprocess harness 구현
