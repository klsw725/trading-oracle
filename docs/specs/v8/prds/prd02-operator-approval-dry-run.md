# PRD: v8 PRD 02 operator approval dry-run
> **상태**: ✅ 구현 완료
> 상위 SPEC: [v8 SPEC](../SPEC.md)

## 사용법

```bash
uv run python -m src.v8.cli prd02-acceptance
uv run python -m src.v8.cli prd02-build
uv run python -m src.v8.cli prd02-build --input docs/specs/v8/fixtures/prd02-operator-approval-dry-run.json --output data/paper/v8/approvals/prd02-artifact.json
uv run python -m src.v8.cli prd02-verify
uv run python -m src.v8.cli prd02-verify --artifact data/paper/v8/approvals/prd02-artifact.json
```

`prd02-build`는 `--output`이 없으면 stdout에만 canonical artifact를 출력한다. `--output`을 지정한 경우에만 `data/paper/v8/**` 아래에 immutable artifact를 생성하며, live 주문 API와 `data/portfolio.json`은 읽거나 쓰지 않는다.

## 문제

`scripts/portfolio.py`는 `add`, `remove`, `cash` 명령에서 `data/portfolio.json`을 바로 바꾼다. `add`는 현금을 차감하고 포지션을 추가한다. `remove`는 보유 수량을 줄이고 현금을 더한다. 이 흐름에는 proposed order, operator checklist, 승인 거절 만료 기록, quote freshness, broker dry-run 응답, 권한 분리가 없다.

v8 PRD 01의 paper ledger는 실제 주문 없이 virtual order와 fill을 남긴다. PRD 02는 그 다음 경계만 정의한다. 운영자가 추천을 보고 주문 의도를 승인해도 시스템은 broker live order를 절대 만들지 않는다. 승인 뒤에는 broker dry-run 또는 내부 dry-run 검증만 호출하고, live destination, live order ID, 계좌번호, credential, `data/portfolio.json` mutation을 모두 금지한다.

## 목표

1. Proposed order envelope와 operator checklist를 정의한다.
2. Approve, reject, expire의 승인 흐름과 전이를 고정한다.
3. Idempotency key가 중복 승인, 중복 dry-run, 반복 interruption을 막게 한다.
4. Quote freshness 기준을 승인과 dry-run 양쪽에 적용한다.
5. Broker dry-run response schema를 정의하되, strict no real order를 계약으로 고정한다.
6. 역할별 permission과 자기 승인 금지 규칙을 둔다.
7. Happy approval dry-run fixture와 stale, duplicate, expired failure fixture를 제공한다.

## 비목표

1. 실제 broker 주문을 만들거나 전송하지 않는다.
2. Live account balance, live order ID, account number, access token, client secret을 읽거나 저장하지 않는다.
3. `scripts/portfolio.py add`, `remove`, `cash`를 dry-run 승인 구현으로 바꾸지 않는다.
4. PRD 03의 broker order reconciliation, partial fill, submitted order 처리를 정의하지 않는다.
5. PRD 04의 kill switch 정책을 여기서 확정하지 않는다.

## 현재 코드에서 소비하는 사실

| 파일 | 확인한 사실 | PRD에서 쓰는 방식 |
| --- | --- | --- |
| `scripts/portfolio.py` | `add`는 ticker, price, shares, stop loss를 받아 현금을 차감하고 포지션을 저장한다. | Proposed order는 같은 핵심 입력을 참조할 수 있지만 저장 경로와 목적지는 dry-run 전용이다. |
| `scripts/portfolio.py` | `remove`는 보유 수량을 확인하고 현금을 더하며, 가격이 없으면 최근 OHLCV 종가를 쓴다. | Quote freshness가 없으면 승인과 dry-run이 모두 막혀야 한다. 최근 가격 fallback이 승인 근거가 되면 안 된다. |
| `scripts/portfolio.py` | `--json` 출력은 성공이나 오류 payload를 stdout에 출력한다. | PRD 02 fixture도 parseable JSON을 제공하고 misleading success를 실패로 둔다. |
| `docs/specs/v8/prds/prd01-paper-portfolio-ledger.md` | Paper order, fill, ledger, reconciliation은 paper namespace와 hash chain을 사용한다. | PRD 02는 `paper_order_id`를 입력으로 받을 수 있지만 live order로 승격하지 않는다. |

## Strict no real order boundary

| boundary | 규칙 | 실패 예 |
| --- | --- | --- |
| Destination | `destination`은 `broker_dry_run` 또는 `internal_dry_run`만 허용한다. | `broker_live`, `toss_live`, `real_account`, `paper_engine`을 live 주문처럼 재사용한다. |
| Submission | Dry-run 호출은 broker가 제공하는 validation mode만 사용한다. Broker가 validation mode를 제공하지 않으면 내부 검증으로 닫고 live API를 호출하지 않는다. | Dry-run을 흉내 내려고 live submit endpoint에 flag를 붙인다. |
| Identifiers | `broker_order_id`, `live_order_id`, `account_number`는 response에 존재하면 안 된다. | 값이 null이어도 key가 payload에 있다. |
| Storage | Approval artifact는 `data/paper/v8/approvals/**` 같은 dry-run 전용 경로만 쓴다. | `data/portfolio.json`이나 live credential file을 읽거나 갱신한다. |
| Cash and position | Approval dry-run은 cash와 position을 mutate하지 않는다. | 승인 성공 뒤 cash, shares, history가 바뀐다. |

## Proposed order envelope

Proposed order는 실행 요청이 아니다. 운영자에게 검토할 의도를 보여주는 immutable envelope다.

| field | required | rule |
| --- | --- | --- |
| `schema_version` | yes | `v8.operator_approval_dry_run.proposed_order.1` |
| `proposed_order_id` | yes | `aprop_v8_` + canonical JSON seed hash first 20 hex |
| `paper_order_id` | yes | PRD 01 order ID, 없으면 proposal 생성 실패 |
| `paper_recommendation_id` | yes | PRD 01 recommendation ID |
| `ticker` | yes | Proposal과 quote, checklist, dry-run response가 모두 같은 ticker여야 한다. |
| `side` | yes | `BUY` 또는 `SELL` |
| `order_type` | yes | `market` 또는 `limit` |
| `quantity` | yes | Decimal string, positive only |
| `limit_price` | conditional | Limit order에는 required, market order에는 null 금지 대신 field omission |
| `currency` | yes | `KRW` 또는 `USD` |
| `estimated_notional` | yes | Decimal string |
| `quote_ref` | yes | Quote ID, as-of, expires-at, source hash |
| `checklist_id` | yes | Checklist artifact ID |
| `idempotency_key` | yes | Approval과 dry-run을 묶는 caller supplied key |
| `permission_context` | yes | proposer, approver eligibility, role snapshot |
| `forbidden_fields_absent` | yes | Credential과 live order field absence proof |

Canonical seed는 schema version, paper order ID, ticker, side, order type, quantity, limit price, quote ID, quote as-of, idempotency key를 정렬 key JSON으로 직렬화해 만든다. 같은 seed는 같은 `proposed_order_id`를 만든다.

## Operator checklist

Checklist는 승인 전에 사람에게 보여야 하는 최소 확인 항목이다. 모든 항목은 checked, rejected, not_applicable 중 하나를 가진다.

| checklist item | applies to | pass rule |
| --- | --- | --- |
| `intent_matches_recommendation` | all | Ticker, side, quantity, limit price가 source paper order와 같다. |
| `quote_is_fresh` | all | `approved_at`과 `dry_run_requested_at`이 `quote_expires_at`보다 빠르다. |
| `notional_under_operator_limit` | all | Estimated notional이 approver permission limit 이하이다. |
| `cash_or_position_reviewed` | all | BUY는 available dry-run cash, SELL은 dry-run holding이 표시된다. |
| `stop_loss_visible` | BUY | Source sizing에 stop loss가 있으면 표시된다. |
| `no_live_destination_visible` | all | Destination label이 dry-run only로 표시된다. |
| `risk_notice_acknowledged` | all | Known risk notice를 운영자가 확인한다. |

Checklist 중 required 항목이 rejected 또는 missing이면 approval은 blocked다. Not applicable은 rule과 reason을 함께 저장한다.

## Approval state machine

필드명 `state`와 `stage`는 금지한다. Artifact는 `approval_status`만 쓴다.

| from `approval_status` | action | guard | to `approval_status` | mutation |
| --- | --- | --- | --- | --- |
| `proposed` | checklist saved | Required items are checked or not applicable. | `checklisted` | Append checklist artifact. |
| `proposed` | reject | Operator has reject permission. | `rejected` | Append reject decision. |
| `checklisted` | approve | Quote fresh, permission valid, proposer differs from approver. | `approved` | Append approval decision. |
| `checklisted` | reject | Operator has reject permission. | `rejected` | Append reject decision. |
| `proposed` or `checklisted` | expire | Current time is later than `approval_expires_at` or quote expired. | `expired` | Append expiry record. |
| `approved` | request dry-run | Quote still fresh and idempotency key matches seed. | `dry_run_requested` | Append dry-run request artifact. |
| `dry_run_requested` | dry-run pass | Broker validation response says would accept and no forbidden field exists. | `dry_run_passed` | Append dry-run response artifact. |
| `dry_run_requested` | dry-run fail | Broker validation rejects or response malformed. | `dry_run_failed` | Append failure artifact. |

Terminal statuses are `rejected`, `expired`, `dry_run_passed`, and `dry_run_failed`. No terminal status may transition to a different terminal status. Resubmission with the same idempotency key returns the existing terminal artifact.

## Approve, reject, and expire rules

| action | actor permission | required reason | effect |
| --- | --- | --- | --- |
| approve | `orders.approve_dry_run` | Optional unless risk notice exists | Allows one dry-run request, not a live order. |
| reject | `orders.reject_dry_run` | Required | Stops this proposed order. Same paper order can create a new proposal only with a new idempotency key and fresh quote. |
| expire | system clock or operator | System reason generated | Stops approval and dry-run. Expired proposals cannot be revived. |

Approval expiration is the earlier of quote expiry and `approval_expires_at`. Default `approval_expires_at` is 5 minutes after proposal creation. Quote expiry can be shorter by market and source.

## Idempotency contract

| case | expected result |
| --- | --- |
| Same idempotency key, same canonical proposal seed | Return the existing proposed order, approval decision, and dry-run response. Do not append duplicates. |
| Same idempotency key, different ticker, side, quantity, limit, quote, paper order, or approver | Return `idempotency_conflict`. Do not create or mutate artifacts. |
| Same proposed order submitted after interruption before dry-run response | Resume from latest artifact and call dry-run at most once if no response exists. |
| Same dry-run request receives repeated broker validation response | Store one response hash and return the stored artifact. |

Idempotency index key is `approval_idempotency_key + proposed_order_seed_hash`. The index value stores proposed order ID, approval decision ID, dry-run request ID, dry-run response ID, terminal `approval_status`, and response hash.

## Quote freshness

| field | rule |
| --- | --- |
| `quote_id` | Required and tied to ticker, currency, side, source, and as-of. |
| `quote_as_of` | ISO 8601 with timezone. Must be no later than proposal creation. |
| `quote_expires_at` | ISO 8601 with timezone. Must be after proposal creation. |
| `max_quote_age_seconds` | Default 30 seconds for market orders and 120 seconds for limit orders unless source declares stricter TTL. |
| `freshness_result` | `fresh`, `stale`, or `missing`. Only `fresh` can be approved or dry-run requested. |

Freshness is checked twice. First at approval, then again immediately before dry-run request. A quote that becomes stale after approval blocks dry-run and appends `expired` with reason `quote_expired_before_dry_run`.

## Broker dry-run response

Broker dry-run response is a validation artifact. It is not a broker order.

| field | required | rule |
| --- | --- | --- |
| `schema_version` | yes | `v8.operator_approval_dry_run.broker_response.1` |
| `dry_run_response_id` | yes | `adry_v8_` + canonical response hash first 20 hex |
| `dry_run_request_id` | yes | Request artifact ID |
| `broker_adapter` | yes | Adapter name, version, and validation mode |
| `live_submission` | yes | Must be false |
| `would_accept` | yes | Boolean validation result |
| `estimated_fee` | yes | Decimal string or explicit `not_available` reason |
| `estimated_tax` | yes | Decimal string or explicit `not_available` reason |
| `estimated_cash_effect` | yes | Decimal string or explicit `not_available` reason |
| `reject_code` | conditional | Required when `would_accept` is false |
| `reject_message` | conditional | Required when `would_accept` is false |
| `forbidden_fields_absent` | yes | Must prove `broker_order_id`, `live_order_id`, account and credential keys are absent |

If the broker adapter cannot provide validation mode, response must be `dry_run_failed` with `reject_code` equal to `broker_validation_unavailable`. It must not call live submit to compensate.

## Permissions

| permission | allowed action | restriction |
| --- | --- | --- |
| `orders.propose_dry_run` | Create proposed order from paper order. | Cannot approve own proposal. |
| `orders.review_dry_run` | View proposed order and checklist. | Cannot mutate. |
| `orders.approve_dry_run` | Approve checklisted proposal. | Requires notional limit and fresh quote. |
| `orders.reject_dry_run` | Reject proposal. | Requires reason. |
| `orders.expire_dry_run` | Manually expire proposal. | System can also expire by clock. |
| `orders.audit_dry_run` | Read artifacts and idempotency index. | Cannot approve, reject, or request dry-run. |

Permission context is captured when proposal is created and checked again at approval time. If the approver lost permission between proposal and approval, approval is blocked.

## JSON and mutation contracts

| artifact | append path | forbidden mutation |
| --- | --- | --- |
| Proposed order | `data/paper/v8/approvals/proposals.jsonl` | Editing existing proposal, changing quote, changing quantity |
| Checklist | `data/paper/v8/approvals/checklists.jsonl` | Replacing prior checklist without correction record |
| Decision | `data/paper/v8/approvals/decisions.jsonl` | Changing approver, reason, or approval time |
| Dry-run request | `data/paper/v8/approvals/dry_run_requests.jsonl` | Creating more than one request for same idempotency seed |
| Dry-run response | `data/paper/v8/approvals/dry_run_responses.jsonl` | Changing `would_accept`, fee, tax, reject code, or forbidden field proof |
| Idempotency index | `data/paper/v8/approvals/idempotency_index.json` | Pointing one key to a different canonical seed |

Every append record includes `record_hash`, `prev_record_hash`, and `source_hashes`. JSON parser failure, duplicate record hash, duplicate artifact ID, missing schema version, forbidden key, or invalid decimal string blocks the write before any artifact is appended.

## Failure probes

| probe | detection rule | expected result |
| --- | --- | --- |
| `stale_quote` | Approval or dry-run requested after `quote_expires_at`, or quote age exceeds TTL. | Append expiry record. Do not call dry-run. |
| `duplicate_approval` | Same idempotency key and same seed arrives after terminal status. | Return stored terminal artifact. Do not append. |
| `expired_approval` | Operator approves after `approval_expires_at`. | Return `approval_expired`. No dry-run request. |
| `malformed_json` | Missing schema version, invalid decimal, forbidden credential key, or field named `state` or `stage`. | Reject before append. |
| `dirty_declared_input` | Evidence or request declares source hashes that no longer match read inputs. | Return `dirty_input`. Do not trust dry-run result. |
| `misleading_success` | Response says success while `live_submission` is true, `would_accept` is false, or forbidden field exists. | Return `misleading_success_output`. Do not mark dry-run passed. |
| `idempotency_conflict` | Same key with different canonical seed. | Return conflict and preserve existing index. |
| `repeated_interruption` | Resume after interruption appends a second approval or dry-run response for same key. | Fail idempotence check and require correction artifact. |

## Happy approval dry-run fixture

The fixture is a contract sample. It validates one operator approved dry-run. It does not place an order.

```json
{
  "schema_version": "v8.operator_approval_dry_run.prd02.fixture.1",
  "fixture_name": "happy_operator_approval_dry_run",
  "strict_no_real_order": true,
  "forbidden_fields": [
    "access_token",
    "account_number",
    "broker_order_id",
    "client_secret",
    "live_order_id"
  ],
  "proposed_order": {
    "schema_version": "v8.operator_approval_dry_run.proposed_order.1",
    "proposed_order_id": "aprop_v8_f5e78bd2e22f115b7e08",
    "paper_order_id": "pord_v8_401fb2527af3008c3980",
    "paper_recommendation_id": "prec_v8_1df70a8e23b72f301477",
    "ticker": "005930",
    "side": "BUY",
    "order_type": "limit",
    "quantity": "10",
    "limit_price": "10000.00",
    "currency": "KRW",
    "estimated_notional": "100000.00",
    "destination": "broker_dry_run",
    "quote_ref": {
      "quote_id": "quote_v8_fixture_005930_20260806_090700",
      "quote_as_of": "2026-08-06T09:07:00+09:00",
      "quote_expires_at": "2026-08-06T09:07:30+09:00",
      "max_quote_age_seconds": 30,
      "source_hash": "sha256:2f0bf376dcfd0e69f391a01cbbe6a9f4d393c96a58e626e1f29de6290904588b"
    },
    "checklist_id": "achk_v8_8baf645186b964804411",
    "idempotency_key": "idem_approval_v8_fixture_1",
    "approval_expires_at": "2026-08-06T09:12:00+09:00",
    "permission_context": {
      "proposed_by": "operator_recommender",
      "eligible_approver_role": "execution_reviewer",
      "max_notional": "500000.00"
    },
    "forbidden_fields_absent": true
  },
  "checklist": {
    "checklist_id": "achk_v8_8baf645186b964804411",
    "checked_at": "2026-08-06T09:07:10+09:00",
    "items": [
      {
        "item": "intent_matches_recommendation",
        "result": "checked"
      },
      {
        "item": "quote_is_fresh",
        "result": "checked"
      },
      {
        "item": "notional_under_operator_limit",
        "result": "checked"
      },
      {
        "item": "no_live_destination_visible",
        "result": "checked"
      }
    ]
  },
  "approval_decision": {
    "approval_decision_id": "adec_v8_d71af0d8867d3f86aa2e",
    "approval_status": "approved",
    "approved_by": "operator_approver_01",
    "approved_role": "execution_reviewer",
    "approved_at": "2026-08-06T09:07:15+09:00",
    "approver_is_proposer": false,
    "idempotency_key": "idem_approval_v8_fixture_1"
  },
  "dry_run_request": {
    "dry_run_request_id": "adreq_v8_ba523e62b7dfcc309c8b",
    "requested_at": "2026-08-06T09:07:20+09:00",
    "destination": "broker_dry_run",
    "live_submission": false,
    "idempotency_key": "idem_approval_v8_fixture_1"
  },
  "broker_dry_run_response": {
    "schema_version": "v8.operator_approval_dry_run.broker_response.1",
    "dry_run_response_id": "adry_v8_7e7c2b4d21c7a6e5e38f",
    "dry_run_request_id": "adreq_v8_ba523e62b7dfcc309c8b",
    "broker_adapter": {
      "name": "fixture_broker",
      "version": "dry_run_only_1",
      "validation_mode": "dry_run"
    },
    "live_submission": false,
    "would_accept": true,
    "estimated_fee": "100.00",
    "estimated_tax": "0.00",
    "estimated_cash_effect": "-100100.00",
    "forbidden_fields_absent": true
  },
  "expected_after_replay": {
    "approval_status": "dry_run_passed",
    "real_order_created": false,
    "portfolio_mutated": false,
    "idempotency_index_entry": {
      "idempotency_key": "idem_approval_v8_fixture_1",
      "proposed_order_id": "aprop_v8_f5e78bd2e22f115b7e08",
      "approval_decision_id": "adec_v8_d71af0d8867d3f86aa2e",
      "dry_run_request_id": "adreq_v8_ba523e62b7dfcc309c8b",
      "dry_run_response_id": "adry_v8_7e7c2b4d21c7a6e5e38f",
      "approval_status": "dry_run_passed"
    }
  }
}
```

## Failure fixtures

| fixture | mutation | expected result |
| --- | --- | --- |
| `stale_quote_blocks_approval` | Change `approved_at` to `2026-08-06T09:07:45+09:00`. | `approval_status` becomes `expired`, dry-run request absent. |
| `duplicate_approval_returns_existing` | Submit same fixture twice with same idempotency key. | Same IDs returned, no appended duplicate artifacts. |
| `expired_approval_blocks_dry_run` | Change `requested_at` to `2026-08-06T09:12:01+09:00`. | Dry-run request rejected with `approval_expired`. |
| `malformed_response_blocks_pass` | Add `broker_order_id` to broker dry-run response. | `dry_run_failed` with `forbidden_field_present`. |
| `repeated_interruption_blocks_duplicate` | Simulate resume after response write and replay request again. | Stored response returned, second response append rejected. |

## Acceptance criteria

1. Line 1 title and line 2 implementation status marker are exact.
2. Proposed order, checklist, approve, reject, expire, idempotency, quote freshness, broker dry-run response, and permission contracts are all present.
3. The document states strict no real order and forbids live broker submission, live order IDs, credentials, live account fields, and `data/portfolio.json` mutation.
4. The approval state machine uses `approval_status` and explicitly forbids `state` and `stage` field names.
5. Happy fixture reaches `dry_run_passed` with `live_submission: false`, `would_accept: true`, and `portfolio_mutated: false`.
6. Failure fixtures cover stale quote, duplicate submission, expired approval, malformed response, and repeated interruption.
7. JSON and idempotence mutation rules block stale, dirty, misleading, malformed, and conflicting inputs before any live side effect.
