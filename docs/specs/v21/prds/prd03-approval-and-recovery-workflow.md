# PRD: v21 PRD 03 Approval And Recovery Workflow
> **상태**: 📋 구현 예정
> 상위 SPEC: [v21 SPEC](../SPEC.md)

## 의존성

- [PRD 01](prd01-unified-operator-cli.md)의 strict request, idempotency, response와 redaction
- [PRD 02](prd02-status-observability-and-incidents.md)의 operator event, incident와 consistent SQLite composition
- [v20 Lifecycle PRD](../../v20/prds/prd03-promotion-rollback-and-kill-lifecycle.md)의 단일 authorization predicate, exact action binding과 recovery 조건
- [v19 SPEC](../../v19/SPEC.md)의 durable execution resume
- [v17 SPEC](../../v17/SPEC.md)의 append-only transaction/reconciliation

## 목표

한 local operator의 human approval을 서명된 immutable record로 발급·조회·철회하고, v20 authorization predicate가 허용한 action에 한 번 binding·소비한다. Incident 복구는 root cause와 reconciliation을 확인한 뒤 승인 필요 여부를 v20에 위임하며, 승인·authorization·recovery action·audit를 crash-safe하게 연결한다.

## 책임 경계

| 책임 | Owner |
| --- | --- |
| Approval request/body schema, issue/revoke/expiry/consume lifecycle | v21 |
| Local operator public trust anchor와 signature verification | v21 |
| Gate/evidence/manifest/lifecycle/reconciliation predicate | v20 |
| Approval이 필요한 action class 판정 | v20 |
| `(approval_id, action_identity)` authorization check | v20 |
| Session step resume와 lease semantics | v19 |
| Account/event transaction과 replay | v17 |
| Strategy/risk/promotion/rollback/kill/recovery business rule | v12~v20 기존 owner |

V21은 signed approval이 valid하다는 사실만으로 action을 authorize하지 않는다. V20이 `AUTHORIZED`를 반환해야 한다. V20이 `NOT_REQUIRED`를 반환한 automatic/safety action에 v21이 approval requirement를 추가하지 않는다.

## 구현 표면

| 경로 | 책임 |
| --- | --- |
| `src/v21/approval_models.py` | trust anchor, issue/revoke body와 lifecycle schema |
| `src/v21/approvals.py` | signature verification, issue/list/show/revoke/consume service |
| `src/v21/approval_repository.py` | immutable records/events/bindings와 projection replay |
| `src/v21/audit.py` | approval/recovery audit-chain verifier |
| `src/v21/recovery.py` | incident preflight, v19/v20 public recovery orchestration |
| `src/v21/migrations/008_approval_recovery.sql` | Global head `007`→`008`; approval/recovery tables와 constraints |

## 단일 운영자 Trust Anchor

Trust-anchor document schema `v21.trust-anchor.1`:

```json
{"schema_version":"v21.trust-anchor.1","algorithm":"Ed25519","public_key":"base64url-no-padding","key_id":"sha256:..."}
```

- `key_id = sha256("trading-oracle:v21:trust-anchor:1" || raw_public_key)`이며 32-byte Ed25519 public key만 허용한다.
- `operator_id = "op_" + key_id hex 앞 16자`다. Display name, email, OS username과 raw account identity를 저장하지 않는다.
- `init`은 public bytes, full key ID, operator ID와 algorithm을 SQLite `operator_metadata`에 등록한다.
- Private key는 v21이 생성·열기·저장·출력하지 않는다. Environment variable, keychain, network signer와 private-key option도 없다.
- Signature는 external local signer가 만든 detached Ed25519 signature document로 입력한다. Acceptance는 repository fixture의 deterministic test vector만 사용한다.
- 한 database에는 trust anchor 하나만 존재한다. Rotation, delegation, quorum, recovery key와 second operator는 v21 범위 밖이다.
- Public trust anchor file은 init bootstrap input일 뿐 init 이후 truth가 아니다. 이후 검증은 SQLite의 immutable anchor bytes를 사용한다.

따라서 “credential 없음” 경계는 유지된다. V21은 broker/provider/private credential을 취급하지 않으며 public verification key와 detached signature만 받는다.

## Approval Issue Body

Schema `v21.approval-issue-body.1`은 다음 exact field만 가진다.

| Field | Contract |
| --- | --- |
| `schema_version` | exact `v21.approval-issue-body.1` |
| `operator_id` | initialized anchor에서 파생한 exact ID |
| `action_class` | v20 registered approval-required enum |
| `action_identity` | v20 canonical proposed action `sha256:` |
| `scope` | market, currency, account_ref, arm, optional symbol의 exact v20 scope |
| `effective_session` | v16 official session date |
| `manifest_hash` | v20 exact unchanged/target manifest hash |
| `evidence_hashes` | unique full hashes, lexicographic order, non-empty |
| `reason_code` | registered enum; free text 금지 |
| `issued_as_of` | command `--as-of`와 exact equality |
| `expires_as_of` | issued 뒤, effective session official close 이하 |
| `request_id` | CLI request ID와 exact equality |

Registered action class는 v20이 approval-required로 정의한 `OPERATION_KILL_RECOVERY`, `SAME_VERSION_ROLLBACK_RECOVERY`, `SOURCE_DATA_EXCEPTION`, `POLICY_IDENTITY_CHANGE`만 허용한다. Registered reason은 각각 `ROOT_CAUSE_RESOLVED`, `DETERMINISTIC_REPLAY_MATCHED`, `SOURCE_EXCEPTION_REVIEWED`, `POLICY_CHANGE_REVIEWED`이며 action class별 allowlist를 v20 contract mapping으로 고정한다.

Approval ID는 아래 canonical bytes의 prefixed hash다.

```text
approval_id = "apr_" + sha256("trading-oracle:v21:approval:1" || canonical(issue_body)).hex()
```

Signature message도 같은 domain separator와 canonical body다. Signature document `v21.detached-signature.1`은 `{schema_version,key_id,algorithm,body_hash,signature}`만 가진다. `body_hash`, anchor와 signature verification이 모두 일치해야 한다.

## Approval Lifecycle

Durable record body는 immutable하고 lifecycle은 event replay로 계산한다.

```text
ISSUED -> ACTIVE
ACTIVE -> REVOKED
ACTIVE -> CONSUMED
ACTIVE -> EXPIRED   (조회 as_of에서 파생, event append 없음)
```

| 상태 | 사용 | revoke | 의미 |
| --- | --- | --- | --- |
| `ACTIVE` | exact action에 가능 | 가능 | signature/body/anchor valid, 미만료, 미소비 |
| `REVOKED` | 불가 | exact retry만 | signed revocation terminal event 존재 |
| `CONSUMED` | same action exact retry만 | 불가 | v20 authorization/action binding terminal |
| `EXPIRED` | 불가 | 불가 | caller `as_of >= expires_as_of`인 derived terminal view |

Expiry는 wall clock이 아니라 consuming command의 explicit `as_of`로 평가한다. 과거 `as_of`를 사용한 time travel을 막기 위해 consume/revoke `as_of`는 approval issue, database의 해당 namespace latest effective event와 incident last effective time 이상이어야 한다.

Exact issue retry는 query `as_of`의 ACTIVE/후속 terminal current state, 최초 issue receipt와 latest lifecycle/audit head를 반환하며 상태를 되돌리지 않는다. 같은 action identity라도 다른 request ID/body는 다른 approval이 될 수 있으나 v20은 현재 exact action/evidence에 맞는 하나만 binding한다. 여러 ACTIVE approval이 있어도 자동 선택하지 않고 caller가 ID를 명시한다.

## `approval issue`

처리 순서:

1. Request와 signature file의 size/schema/forbidden fields를 검증한다.
2. Initialized anchor, operator ID, command request ID와 `as_of` equality를 검증한다.
3. Signature와 body hash를 검증한다.
4. V16 official session, scope/manifest/evidence lexical identity를 검증한다.
5. V20 public `describe_authorization(action_identity)`가 registered approval-required action과 exact body를 반환하는지 확인한다.
6. Existing semantic key/approval ID의 duplicate/conflict를 판정한다.
7. Approval record, `approval.issued`, operator audit event와 receipt를 한 transaction에 append한다.

Step 5는 action을 실행하거나 authorization을 확정하지 않는다. Gate가 아직 충족되지 않아도 exact proposed action descriptor가 유효하면 approval을 미리 issue할 수 있지만 consume 때 모든 v20 predicate를 다시 평가한다. Unknown action, manifest, evidence 또는 scope는 issue 전에 실패한다.

Signature raw bytes는 business payload에 저장하지 않는다. Forensic verification에 필요한 signature hash, body hash, key ID, algorithm과 verification result를 저장한다. 원본 detached file은 durable truth가 아니다. Issue/revoke request와 signature document는 local signer가 생성하는 immutable input artifact이며 운영자가 SQLite 또는 JSON state를 수동 편집하는 절차가 아니다.

## `approval list/show`

List filter는 status/action class/market/effective session이며 stable order는 `(issued_as_of,approval_id)`다. Summary는 approval ID, operator ID, action class/identity, safe scope, session, manifest/evidence hashes, reason code, expiry와 current status만 가진다.

Show는 immutable body safe fields, issue/revoke/consume event history, signature/body hashes, v20 authorization check ID와 recovery/action receipt ref를 추가한다. Raw public key, signature, source evidence payload와 account ID는 반환하지 않는다.

`EXPIRED`는 query `as_of`에 따른 view임을 `status_as_of`와 함께 표시한다. Historical event를 새 expiry event로 만들어 read command가 mutation하지 않는다.

## Signed Revoke

Revoke body schema `v21.approval-revoke-body.1`:

```json
{"schema_version":"v21.approval-revoke-body.1","operator_id":"op_...","approval_id":"apr_...","approval_body_hash":"sha256:...","reason_code":"APPROVAL_WITHDRAWN","revoked_as_of":"2026-08-18T01:00:00Z","request_id":"req_..."}
```

Signature domain은 `trading-oracle:v21:approval-revoke:1`이다. `OPERATION_CONTEXT_CHANGED`, `EVIDENCE_SUPERSEDED`, `APPROVAL_WITHDRAWN`만 revoke reason으로 허용한다. Free text는 없다.

ACTIVE이며 미소비인 approval만 revoke할 수 있다. Expired 또는 consumed approval revoke는 `IMMUTABLE_STATE_CONFLICT`, exit 4다. Same signed revoke retry는 stored result다. Revoke는 original record/event를 update/delete하지 않고 `approval.revoked` event, audit event와 receipt를 append한다.

## Consumption과 V20 Authorization

Approval consumption은 독립 public command가 아니다. `run --approval-id` 또는 `recover --approval-id`가 v20 approval-required action을 실행할 때만 발생한다.

```text
load ACTIVE approval at explicit as_of
-> verify anchor/body/event/audit chain
-> exact action/scope/session/manifest/evidence binding
-> v17/v19 reconciliation
-> v20 authorize_transition/equivalent predicate
-> append v20 authorization check + action binding
-> execute source action
-> append v21 approval.consumed + recovery/operator event + receipts
-> verify all heads
-> commit
```

V20 predicate가 `NOT_REQUIRED`면 supplied approval ID를 소비하지 않고 `APPROVAL_NOT_APPLICABLE`, exit 2로 거부한다. 이로써 safety action에 의미 없는 approval side effect가 생기지 않는다.

V20 authorization check, action의 source writes와 v21 consumption/binding이 하나의 transaction에 참여할 수 있는 public unit이어야 한다. 선행 service가 nested connection을 강제하면 구현 전에 transaction-aware service boundary를 추가하되 business rule은 바꾸지 않는다. Fault는 binding/consumption/action/event를 모두 rollback한다.

`approval_action_bindings`는 이 transaction이 반환한 v20 `authorization_check_id`와 action identity를 v21 approval consume event에 참조시키는 projection이다. V21은 여기서 predicate를 재평가하거나 별도 `AUTHORIZED` 결론을 만들지 않으며, v20 check가 없는 binding은 audit integrity failure다.

Consumed approval의 same action + same request retry는 stored action/authorization result를 반환한다. 다른 request/body/action/session/manifest/evidence로 사용하면 `APPROVAL_ALREADY_CONSUMED`, exit 5다.

## Recovery Command

`recover` mode는 정확히 세 개다.

| Mode | Owner service | Approval | Result |
| --- | --- | --- | --- |
| `RESUME_SESSION` | v19 resume | v20이 active kill 없음 확인; approval 불필요 | last committed step 다음 실행 |
| `OPERATION_KILL_RECOVERY` | v20 lifecycle recovery | 필수 | kill state에서 registered manual recovery |
| `SAME_VERSION_ROLLBACK_RECOVERY` | v20 lifecycle recovery | 필수 | unchanged version operational rollback 복귀 |

Source data exception과 policy identity change approval은 `run --approval-id`가 v20 predicate를 호출할 때 소비하며 `recover` mode가 아니다.

Recovery preflight:

1. Incident가 OPEN이고 requested mode/action/scope와 일치한다.
2. V17/V19/V20/V21 migration/event/projection/audit reconciliation이 PASS다.
3. Root-cause evidence가 incident 이후이고 v20 verifier에서 resolved다.
4. `RESUME_SESSION`은 v19 nonterminal run과 valid lease semantics를 가진다.
5. Lifecycle recovery는 exact unchanged code/config/strategy/risk/cost/router/prompt/model/schema/manifest hashes와 deterministic replay equality를 가진다.
6. Retired version, failed gate, blocking kill, wrong scope와 same-day re-entry는 차단한다.
7. V20 authorization result가 요구하면 exact ACTIVE approval을 검증한다.

Preflight만 성공하면 incident `OPEN -> RECOVERING`을 action transaction 안에서 append한다. Action 후 모든 source와 audit reconciliation이 PASS하면 `RECOVERING -> RESOLVED`; action/final reconciliation failure면 transaction 전체 rollback하여 incident는 OPEN이다. Rollback 뒤 별도 immutable `recovery.failed` audit transaction을 반드시 append하며 pre-action hashes와 safe code만 기록한다. 따라서 source business/lifecycle/approval binding·consume heads는 pre-attempt와 같고 v21 operator audit head만 한 failure event만큼 증가한다. 같은 failed request retry는 stored failure receipt를 반환해 failure event도 중복하지 않는다.

`RESUME_SESSION`은 interrupted work 재개이지 lifecycle recovery가 아니다. Operation kill이 active하거나 incident가 manual lifecycle recovery를 요구하면 `RECOVERY_PRECONDITION_FAILED`다. JSON report, PID, in-memory queue와 event export를 resume input으로 사용하지 않는다.

## Recovery Receipt

Schema `v21.recovery-receipt.1` 필수 field:

- recovery ID, request ID, mode, incident ID와 source scope
- preflight evidence/hash와 starting source/audit heads
- v20 authorization result/check ID, approval ID/binding ID 또는 `NOT_REQUIRED`
- v19 resume receipt 또는 v20 transition/action receipt
- ending v17/v19/v20/v21 heads와 reconciliation hash
- final incident state와 explicit `as_of`

Receipt에는 raw reason/evidence/signature/account/path가 없다. Recovery ID는 semantic request/action identity hash이며 random UUID가 아니다.

## Immutable Audit 검증

Approval/recovery audit는 global `operator_events` chain과 approval별 event chain을 모두 확인한다.

- Sequence gap/duplicate와 previous/event hash mismatch
- Approval record body hash, signature hash, key ID와 issue event mismatch
- Revoke/consume terminal event order와 duplicate terminal event
- V20 authorization binding이 없는 consumed event
- Source action receipt가 없는 successful recovery
- Incident state와 recovery receipt final state mismatch
- Request receipt가 참조하는 missing event/action

Mismatch는 `AUDIT_CHAIN_INVALID`, exit 6이며 issue/revoke/run/recover를 차단한다. 자동 event 삭제·재서명·status overwrite는 없다.

## Approval Security Failure Table

| Failure | Error/exit | Mutation |
| --- | --- | --- |
| Missing/mismatched trust anchor | `TRUST_ANCHOR_INVALID`, 5 | 0 |
| Invalid signature/body hash | `APPROVAL_SIGNATURE_INVALID`, 5 | 0 |
| Wrong operator/action/scope/session/manifest/evidence | `APPROVAL_EVIDENCE_INVALID`, 5 | 0 |
| Approval absent for required action | `APPROVAL_REQUIRED`, 5 | 0 |
| Expired approval | `APPROVAL_EXPIRED`, 5 | 0 |
| Revoked approval | `APPROVAL_REVOKED`, 5 | 0 |
| Consumed approval different action | `APPROVAL_ALREADY_CONSUMED`, 5 | 0 |
| Approval supplied to NOT_REQUIRED action | `APPROVAL_NOT_APPLICABLE`, 2 | 0 |
| Valid approval but failed v20 gate | `LIFECYCLE_TRANSITION_INVALID`, 7 | 0 |
| Consumed approval revoke | `IMMUTABLE_STATE_CONFLICT`, 4 | 0 |
| Audit chain mismatch | `AUDIT_CHAIN_INVALID`, 6 | 0 |

## Acceptance와 Mutation

| Probe | Expected result |
| --- | --- |
| known Ed25519 test vector issue | ACTIVE approval, signature hash/audit PASS |
| signature bit flip/body field mutation | exit 5, rows 0 |
| trust-anchor replacement after init | exit 4, metadata 불변 |
| issue exact retry/reopen | same approval/event/head |
| signed revoke then use | REVOKED, action mutation 0 |
| consume exact action then retry | stored result, duplicate 0 |
| consume different action/session/manifest | exit 5, all heads 불변 |
| valid approval with failed gate/retired version | exit 7, approval ACTIVE 유지 |
| safety kill with no approval | immediate source action, approval query/consume 0 |
| fault after v20 binding before action | binding/consume/action rollback, failure audit 1건 |
| fault after action before resolved event | source/action/consume/incident rollback, failure audit 1건 |
| unresolved root cause recover | exit 7, incident OPEN, approval ACTIVE |
| same-version manifest drift | exit 7, lifecycle/approval 불변 |
| v19 session resume | last receipt 이후, approval 0 |
| operation kill blocks resume | exit 7, run/lifecycle 불변 |
| raw key/signature/account leak scan | stdout/stderr/SQLite safe payload에서 match 0 |

## CLI

```bash
uv run python -m src.v21.cli approval issue --database data/paper/v17/paper.sqlite3 --request approval-request.json --signature approval-request.sig.json --as-of 2026-08-18T01:00:00Z --request-id req_approval_01
uv run python -m src.v21.cli approval show --database data/paper/v17/paper.sqlite3 --approval-id apr_example --as-of 2026-08-18T01:00:01Z
uv run python -m src.v21.cli recover --database data/paper/v17/paper.sqlite3 --incident-id inc_example --mode OPERATION_KILL_RECOVERY --approval-id apr_example --as-of 2026-08-18T01:05:00Z --request-id req_recovery_01
uv run python -m src.v21.cli prd03-acceptance
```

## 완료 조건

- 한 immutable trust anchor로 issue/revoke signature를 검증하고 private key를 취급하지 않는다.
- Approval lifecycle, v20 authorization binding, action과 audit가 exact retry/crash에서 일관된다.
- V20은 authorization predicate, v21은 human approval record lifecycle이라는 소유권이 코드/DB/CLI에 반영된다.
- Recovery가 root cause, unchanged identity, replay/reconciliation, approval과 incident 상태를 모두 만족할 때만 수행된다.

## 비목표

- Private key generation/custody, OS keychain와 remote signer
- Trust-anchor rotation/recovery, 다중 operator, role, quorum와 delegation
- Approval이 gate/risk/kill/retirement/manifest condition을 override하는 기능
- Arbitrary SQL/event repair, JSON restore와 database rollback
- Live broker recovery 또는 same-day re-entry
