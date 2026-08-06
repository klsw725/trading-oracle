# PRD: v8 PRD 03 order state reconciliation
> **상태**: 📝 초안
> 상위 SPEC: [v8 SPEC](../SPEC.md)

## 문제

PRD 01은 paper ledger를 만들고 PRD 02는 operator approval dry-run을 정의한다. 그 다음 경계에서는 주문 의도, broker가 말하는 주문 상태, 부분 체결, 수수료, 현금, 포지션이 서로 맞는지 대사해야 한다. 이 계약이 없으면 같은 idempotency key로 재시도한 요청이 중복 주문처럼 보이거나, broker 응답을 잃은 뒤 `unknown` 상태에서 다시 주문하는 위험이 생긴다.

이 PRD는 실주문을 만들지 않는다. 이미 존재한다고 선언된 redacted broker truth snapshot과 내부 ledger를 비교하는 문서 계약만 정의한다. Raw account number, access token, client secret, live order ID 원문, 실제 주문 전송 호출은 이 범위에 없다.

## 목표

1. `submitted`, `accepted`, `partial`, `filled`, `cancelled`, `rejected`, `unknown`의 의미와 전이를 고정한다.
2. Broker truth를 최종 관찰 소스로 정의하되, raw credential과 raw broker order ID를 저장하지 않는다.
3. Retry와 idempotent recovery 규칙을 두어 같은 의도가 중복 주문이나 중복 체결로 변하지 않게 한다.
4. Partial fill accounting, fee, tax, cash delta, remaining quantity, position delta를 decimal string으로 대사한다.
5. Cash와 position reconciliation mismatch를 fail closed로 처리한다.
6. `unknown`에서는 재주문하지 않고 operator review와 broker truth refresh만 허용한다.
7. Happy partial fill fixture와 unknown failure fixture를 제공한다.

## 범위 밖

1. Broker submit endpoint를 호출하지 않는다.
2. 실제 broker 주문을 만들거나 전송하지 않는다.
3. 계좌번호, credential, raw live order ID를 읽거나 저장하지 않는다.
4. `data/portfolio.json`을 직접 갱신하지 않는다.
5. PRD 04의 kill switch, 손실 제한, 시장 시간 정책을 확정하지 않는다.
6. PRD 05의 자동화 승격 정책을 확정하지 않는다.

## 현재 계약에서 소비하는 사실

| 출처 | 확인한 사실 | PRD에서 쓰는 방식 |
| --- | --- | --- |
| `docs/specs/v8/prds/prd01-paper-portfolio-ledger.md` | Paper order, fill, position, cash, reconciliation은 append-only event와 hash chain을 사용한다. | PRD 03도 append-only reconciliation artifact와 hash를 사용한다. |
| `docs/specs/v8/prds/prd02-operator-approval-dry-run.md` | Approval dry-run은 live submission이 아니며 `data/portfolio.json`을 mutate하지 않는다. | PRD 03 입력은 dry-run 통과 artifact를 참조할 수 있지만, 그 자체를 broker truth로 취급하지 않는다. |
| `src/portfolio/tracker.py` | 현재 포트폴리오는 `cash_krw`, `cash_usd`, `positions`, `history`를 mutable JSON으로 저장한다. | 대사는 portfolio hash와 expected delta만 남기고, 이 PRD가 파일을 직접 바꾸지 않는다. |
| `scripts/portfolio.py` | `add`와 `remove`는 현금과 포지션을 즉시 바꾸며 부분 매도를 지원한다. | PRD 03은 즉시 mutation 대신 broker truth를 기준으로 partial fill accounting을 남긴다. |
| `data/portfolio.json` | positions, history, cash 값은 float와 timestamp를 포함한다. | Reconciliation fixture는 decimal string과 snapshot hash를 써서 float drift를 막는다. |

## 용어

| 용어 | 의미 |
| --- | --- |
| order intent | PRD 02 승인 뒤 관찰할 주문 의도. 실행 호출이 아니다. |
| broker truth | Broker가 제공했다고 선언된 주문, 체결, 수수료, 취소, 거절 snapshot의 redacted canonical record. |
| internal ledger | 내부 append-only order reconciliation artifact stream. |
| fill fragment | 한 주문에 대해 broker truth가 보고한 부분 체결 한 건. |
| reconciliation run | broker truth와 internal ledger, expected cash, expected position을 한 시점에 비교한 결과. |
| idempotent recovery | interruption 뒤 같은 key로 재개해도 기존 artifact를 찾고 중복 append를 막는 복구 규칙. |

## Strict no real order boundary

| boundary | 규칙 | 실패 예 |
| --- | --- | --- |
| Submission | 이 PRD의 fixture와 validation은 broker submit을 호출하지 않는다. | Reconciliation을 위해 새 주문을 전송한다. |
| Broker truth input | 이미 획득된 redacted snapshot만 읽는다. | Raw account response를 저장한다. |
| Identifier | Raw broker order ID는 저장하지 않고 `broker_order_ref_hash`만 저장한다. | `broker_order_id`, `live_order_id`, `account_number` key가 artifact에 있다. |
| Storage | Reconciliation artifact는 `data/paper/v8/reconciliation/**` 같은 전용 경로를 쓴다. | `data/portfolio.json`을 대사 중 직접 수정한다. |
| Unknown handling | `unknown`이면 재주문을 금지하고 broker truth refresh만 허용한다. | 상태를 모른다는 이유로 같은 주문을 다시 만든다. |

## Identity 계약

모든 ID는 canonical JSON seed를 UTF-8로 직렬화한 뒤 SHA-256을 계산하고, prefix 뒤에 앞 20 hex를 붙인다. Canonical JSON은 key를 정렬하고 공백을 제거한다. Array 순서는 broker truth가 보장한 관찰 순서를 유지한다.

| ID | 형식 | seed |
| --- | --- | --- |
| `execution_order_id` | `eord_v8_` + first 20 hex | dry-run response ID, proposed order ID, side, quantity, order type, price, idempotency key |
| `broker_truth_id` | `btru_v8_` + first 20 hex | broker adapter, redacted order ref hash, observed at, broker truth payload hash |
| `fill_fragment_id` | `ffill_v8_` + first 20 hex | execution order ID, broker truth ID, fill sequence, quantity, price, filled at |
| `order_reconciliation_id` | `orecon_v8_` + first 20 hex | execution order ID, broker truth ID, as-of, prior reconciliation hash |
| `portfolio_delta_id` | `pdelta_v8_` + first 20 hex | execution order ID, fill fragment IDs, cash delta, position delta, fee, tax |
| `record_hash` | `sha256:` + 64 hex | artifact without `record_hash` |

## Order status definitions

Artifacts use the field name `order_status`. They never use `state` or `stage` as field names.

| order_status | Meaning | Broker truth requirement | Internal effect |
| --- | --- | --- | --- |
| `submitted` | The system has a durable intent and idempotency record for a broker submission attempt, but broker acceptance is not yet observed. | Submission attempt hash and request timestamp, no acceptance timestamp yet. | Freeze idempotency key. Do not mutate cash or position. |
| `accepted` | Broker truth says the order is accepted and open with zero filled quantity. | Accepted timestamp, remaining quantity equals original quantity, filled quantity is zero. | Reserve expected exposure only. Do not book a fill. |
| `partial` | Broker truth reports one or more fill fragments and remaining quantity is positive. | Filled quantity greater than zero and less than original quantity. | Append fill fragments, update expected cash and position delta for filled quantity only. |
| `filled` | Broker truth reports cumulative filled quantity equal to original quantity. | Remaining quantity is zero and terminal fill timestamp exists. | Book all fill fragments and close order lifecycle. |
| `cancelled` | Broker truth says no further fills will occur and unfilled quantity was cancelled. | Cancel timestamp and final cumulative filled quantity. | Keep filled fragments, release unfilled quantity, close lifecycle. |
| `rejected` | Broker truth says the order was rejected before any fill. | Reject code and reject timestamp. | No cash or position delta. Store reject reason. |
| `unknown` | Broker truth is missing, contradictory, malformed, or stale after a submission attempt. | No trusted terminal truth. | Fail closed. No reorder. No cash or position mutation. Require operator review. |

Terminal statuses are `filled`, `cancelled`, `rejected`, and `unknown`. `unknown` may be resolved only by a later broker truth refresh that proves one of `accepted`, `partial`, `filled`, `cancelled`, or `rejected` for the same redacted order ref hash. It must not create a new execution order.

## Status transition rules

| from `order_status` | observation | guard | to `order_status` | mutation |
| --- | --- | --- | --- | --- |
| none | durable submission intent recorded | dry-run passed, idempotency key unused for a different seed | `submitted` | Append execution order artifact. |
| `submitted` | broker accepted | broker truth hash valid, no fill quantity | `accepted` | Append broker truth artifact. |
| `submitted` or `accepted` | broker reports partial fill | cumulative filled greater than zero and less than original quantity | `partial` | Append fill fragments and portfolio delta. |
| `submitted`, `accepted`, or `partial` | broker reports full fill | cumulative filled equals original quantity | `filled` | Append final fill fragment and reconciliation. |
| `submitted`, `accepted`, or `partial` | broker reports cancellation | cancellation has broker truth and no later fill | `cancelled` | Append cancellation and release remainder. |
| `submitted` or `accepted` | broker rejects | reject code present and cumulative filled is zero | `rejected` | Append reject artifact. |
| any non-terminal | broker truth missing or contradictory past timeout | truth freshness expired or malformed | `unknown` | Append unknown artifact, block reorder. |
| `unknown` | later trusted truth arrives for same redacted order ref hash | idempotency key and order seed match | proven status | Append recovery reconciliation only. |

No terminal status can transition to another terminal status except `unknown` recovery with matching broker truth. A mismatch in order seed, redacted order ref hash, quantity, ticker, side, or currency remains `unknown` and opens a mismatch record.

## Broker truth contract

Broker truth is the source of observed order and fill facts. It is not a permission to submit another order.

| field | required | rule |
| --- | --- | --- |
| `schema_version` | yes | `v8.order_reconciliation.broker_truth.1` |
| `broker_truth_id` | yes | Deterministic `btru_v8_` ID. |
| `broker_adapter` | yes | Name, version, and read mode. |
| `observed_at` | yes | ISO 8601 with timezone. |
| `truth_fresh_until` | yes | After this time, truth cannot resolve current status. |
| `broker_order_ref_hash` | yes | Full `sha256:<64 hex>` of redacted broker order reference. |
| `order_status` | yes | One of the seven statuses. |
| `ticker` | yes | Must match the execution order. |
| `side` | yes | `BUY` or `SELL`. |
| `currency` | yes | `KRW` or `USD`. |
| `original_quantity` | yes | Positive decimal string. |
| `cumulative_filled_quantity` | yes | Decimal string from broker truth. |
| `remaining_quantity` | yes | `original_quantity - cumulative_filled_quantity`. |
| `fill_fragments` | yes | Empty for zero fill, otherwise ordered fill array. |
| `fee_total` | yes | Decimal string or explicit unavailable reason. |
| `tax_total` | yes | Decimal string or explicit unavailable reason. |
| `reject_code` | conditional | Required for `rejected`. |
| `cancelled_at` | conditional | Required for `cancelled`. |
| `forbidden_fields_absent` | yes | Must prove raw credential and raw broker ID fields are absent. |

If broker truth says `filled` while remaining quantity is positive, or says `partial` with zero fill quantity, reconciliation returns `broker_truth_contradiction` and maps the internal status to `unknown`.

## Retry semantics

| case | required behavior |
| --- | --- |
| Same idempotency key and same execution seed before broker truth arrives | Return existing `execution_order_id`. Do not submit, append, or mutate. |
| Same idempotency key and different execution seed | Return `idempotency_conflict`. Do not create a new order artifact. |
| Network interruption after durable submit intent, before broker truth | Mark `submitted`, then poll or read broker truth by the same redacted order ref hash. Do not reorder. |
| Broker truth read timeout | Mark `unknown` after timeout. Do not book cash or position delta. |
| Retry after `partial` | Reconcile cumulative fill against already booked fragments. Append only new fill fragments. |
| Retry after terminal status | Return existing terminal reconciliation artifact. Do not append duplicates. |

Retry never means reusing the same intent to send another order while the previous broker outcome is unknown. Recovery always starts by finding existing artifacts and reading broker truth for the same redacted order ref hash.

## Partial fill accounting

Partial fills are accounted by fragments. The cumulative totals must match broker truth and internal ledger replay.

| object | required fields | arithmetic rule |
| --- | --- | --- |
| fill fragment | fill fragment ID, sequence, filled at, quantity, price, gross notional, fee, tax | Quantity and money use decimal string arithmetic. |
| BUY cash delta | gross notional, fee, tax | `cash_delta = -(gross_notional + fee + tax)` |
| SELL cash delta | gross notional, fee, tax | `cash_delta = gross_notional - fee - tax` |
| BUY position delta | quantity, average price, cost basis | Increase quantity by filled quantity and cost basis by gross notional. |
| SELL position delta | quantity, realized PnL | Reduce quantity by filled quantity and calculate realized PnL against known cost basis. |
| remaining quantity | original quantity, cumulative filled quantity | `remaining_quantity = original_quantity - cumulative_filled_quantity` |

For partial BUY of 4 shares at `10000.00` with fee `40.00` and tax `0.00`, gross notional is `40000.00` and cash delta is `-40040.00`. If original quantity is `10`, remaining quantity is `6`.

## Cash and position reconciliation

Reconciliation compares three views: broker truth, internal artifact replay, and expected portfolio snapshot hash. It does not write the live portfolio file.

| check | pass condition | failure result |
| --- | --- | --- |
| Broker truth freshness | `observed_at <= truth_fresh_until` and truth is not older than reconciliation cutoff. | `stale_broker_truth`, map to `unknown`. |
| Hash chain | Each record hash recomputes and each previous hash matches the prior record. | `broken_hash_chain`, block reconciliation. |
| Fill cumulative | Sum of internal fill fragment quantities equals broker truth cumulative filled quantity. | `fill_quantity_mismatch`, block portfolio delta. |
| Cash delta | Sum of gross, fee, and tax equals expected cash delta per currency. | `cash_mismatch`, block portfolio delta. |
| Position delta | Filled quantity and side reproduce expected position quantity and cost basis delta. | `position_mismatch`, block portfolio delta. |
| Terminal consistency | Terminal status has no remaining open quantity except `cancelled` with cancelled remainder. | `terminal_mismatch`, block status close. |
| Forbidden fields | No raw credential, account, or raw order ID key exists. | `live_state_contamination`, block artifact write. |

Mismatch handling is fail closed. A mismatch may append a reconciliation record, but it must not append a portfolio delta, must not claim order success, and must not trigger reorder.

## Idempotent recovery

Recovery reads artifacts in this order:

1. Idempotency index by key and execution seed hash.
2. Existing execution order artifact.
3. Latest order reconciliation artifact.
4. Broker truth snapshot for the same `broker_order_ref_hash`.
5. Fill fragment hashes already booked.

Recovery can append only the missing next artifact. It cannot edit a prior artifact. If recovery cannot prove whether broker accepted, filled, cancelled, or rejected the order, it appends `unknown` and stops.

## JSON artifact and mutation contracts

| artifact | append path | forbidden mutation |
| --- | --- | --- |
| Execution order | `data/paper/v8/reconciliation/orders.jsonl` | Changing ticker, side, quantity, price, currency, idempotency key, or dry-run ref. |
| Broker truth | `data/paper/v8/reconciliation/broker_truth.jsonl` | Replacing observed status, fill fragments, fee, tax, reject code, or redacted ref hash. |
| Fill fragments | `data/paper/v8/reconciliation/fills.jsonl` | Changing quantity, price, sequence, timestamp, fee, tax, or fragment ID. |
| Portfolio delta | `data/paper/v8/reconciliation/portfolio_deltas.jsonl` | Changing cash delta, position delta, or snapshot hash. |
| Reconciliation | `data/paper/v8/reconciliation/reconciliations.jsonl` | Changing mismatch count, final status, or quality result. |
| Idempotency index | `data/paper/v8/reconciliation/idempotency_index.json` | Pointing one key to a different execution seed. |

Every append record includes `record_hash`, `prev_record_hash`, `source_hashes`, `schema_version`, and `order_status` when it represents an order lifecycle fact. JSON parser failure, duplicate artifact ID, duplicate record hash, missing schema version, invalid decimal string, forbidden key, or full hash mismatch blocks the write before any artifact is appended.

Field names `state` and `stage` are forbidden in artifacts. The valid lifecycle field is `order_status`.

## Mismatch handling

| mismatch | detection rule | required result |
| --- | --- | --- |
| `broker_truth_contradiction` | Broker truth status and fill quantities conflict. | Append `unknown` reconciliation and require fresh truth. |
| `cash_mismatch` | Expected cash after fragments differs from replayed cash. | Do not append portfolio delta. Keep order status, flag mismatch. |
| `position_mismatch` | Expected quantity or cost basis differs from replay. | Do not append portfolio delta. Require operator review. |
| `duplicate_fill_fragment` | Same fill fragment seed appears twice with different hash or values. | Reject second fragment. Keep prior artifact. |
| `idempotency_conflict` | Same key points to a different execution seed. | Return conflict and block new execution order. |
| `stale_broker_truth` | Truth is older than cutoff or lacks `truth_fresh_until`. | Map to `unknown`. No reorder. |
| `live_state_contamination` | Credential, raw account, or raw order ID field appears. | Reject before append. |
| `misleading_success_output` | Report marks success while mismatch count is greater than zero or status is `unknown`. | Fail report validation. |

## Happy partial fill fixture

This fixture is a contract sample. It does not send an order. It shows a 10 share BUY where broker truth reports a 4 share partial fill.

```json
{
  "schema_version": "v8.order_reconciliation.prd03.fixture.1",
  "fixture_name": "happy_partial_fill_reconciliation",
  "strict_no_real_order": true,
  "forbidden_fields": [
    "access_token",
    "account_number",
    "broker_order_id",
    "client_secret",
    "live_order_id"
  ],
  "execution_order": {
    "schema_version": "v8.order_reconciliation.execution_order.1",
    "execution_order_id": "eord_v8_6e48b5a50d7fc2ed4b1c",
    "proposed_order_id": "aprop_v8_f5e78bd2e22f115b7e08",
    "dry_run_response_id": "adry_v8_7e7c2b4d21c7a6e5e38f",
    "ticker": "005930",
    "side": "BUY",
    "order_type": "limit",
    "quantity": "10",
    "limit_price": "10000.00",
    "currency": "KRW",
    "idempotency_key": "idem_order_recon_v8_fixture_1",
    "order_status": "submitted",
    "broker_order_ref_hash": "sha256:8e5c7d81227df03b1fe21bb604a8b64c24d9f0ab1f428809218cc09388ce9f11",
    "record_hash": "sha256:2c1ebc1a7e7a5c7f1690a761b7f0c143e845785c3c25f1d34f7a76c7bd7c2a10"
  },
  "broker_truth": {
    "schema_version": "v8.order_reconciliation.broker_truth.1",
    "broker_truth_id": "btru_v8_99a715ce8a1d998f22de",
    "broker_adapter": {
      "name": "fixture_broker_reader",
      "version": "read_only_1",
      "mode": "redacted_truth_snapshot"
    },
    "observed_at": "2026-08-06T09:08:10+09:00",
    "truth_fresh_until": "2026-08-06T09:08:40+09:00",
    "broker_order_ref_hash": "sha256:8e5c7d81227df03b1fe21bb604a8b64c24d9f0ab1f428809218cc09388ce9f11",
    "order_status": "partial",
    "ticker": "005930",
    "side": "BUY",
    "currency": "KRW",
    "original_quantity": "10",
    "cumulative_filled_quantity": "4",
    "remaining_quantity": "6",
    "fill_fragments": [
      {
        "fill_fragment_id": "ffill_v8_9c55b18a93af0cba542e",
        "sequence": 1,
        "filled_at": "2026-08-06T09:08:05+09:00",
        "quantity": "4",
        "price": "10000.00",
        "gross_notional": "40000.00",
        "fee": "40.00",
        "tax": "0.00"
      }
    ],
    "fee_total": "40.00",
    "tax_total": "0.00",
    "forbidden_fields_absent": true,
    "record_hash": "sha256:5f6c71f8298a9b584f81e3c90d52266a00d63ef18c3c8fb9e2c0ac31c59cf582"
  },
  "portfolio_delta": {
    "portfolio_delta_id": "pdelta_v8_89e813b7e25bde95582c",
    "order_status": "partial",
    "cash_before": {
      "KRW": "1000000.00"
    },
    "cash_delta": {
      "KRW": "-40040.00"
    },
    "cash_after": {
      "KRW": "959960.00"
    },
    "position_delta": {
      "ticker": "005930",
      "quantity_delta": "4",
      "cost_basis_delta": "40000.00",
      "avg_price_after": "10000.00"
    },
    "portfolio_state_before_hash": "sha256:39765e5de752d6c15f6e7928500f268c958ec52a385305bac559e15e4126d905",
    "portfolio_state_after_hash": "sha256:ac898d028799010be491145ff428b7c90315226584550ecce5b42f4e6af02f88",
    "record_hash": "sha256:66cfd83ed3e1c7d5835cf6b82d776419dd1827c2296b5dd2e0dff276db9fa38d"
  },
  "reconciliation": {
    "order_reconciliation_id": "orecon_v8_1a010db279330d8f9682",
    "as_of": "2026-08-06T09:08:12+09:00",
    "order_status": "partial",
    "matched_checks": [
      "broker_truth_fresh",
      "fill_cumulative",
      "cash_delta",
      "position_delta",
      "forbidden_fields_absent"
    ],
    "mismatch_count": 0,
    "reorder_allowed": false,
    "expected_arithmetic": {
      "gross_notional": "40000.00",
      "fee": "40.00",
      "tax": "0.00",
      "cash_delta": "-40040.00",
      "cash_after": "959960.00",
      "remaining_quantity": "6"
    },
    "prev_record_hash": "sha256:66cfd83ed3e1c7d5835cf6b82d776419dd1827c2296b5dd2e0dff276db9fa38d",
    "record_hash": "sha256:b14961ddcc2f7a54e13c34f32e9a35bd8ac3c258a908030a61a570d22b77c0af"
  }
}
```

## Unknown failure fixture

This fixture proves fail closed behavior after broker truth cannot be trusted. It does not send a replacement order.

```json
{
  "schema_version": "v8.order_reconciliation.prd03.failure_fixture.1",
  "fixture_name": "unknown_broker_truth_blocks_reorder",
  "execution_order_id": "eord_v8_6e48b5a50d7fc2ed4b1c",
  "idempotency_key": "idem_order_recon_v8_fixture_1",
  "submitted_at": "2026-08-06T09:08:00+09:00",
  "truth_failure": {
    "observed_at": "2026-08-06T09:10:20+09:00",
    "truth_fresh_until": "2026-08-06T09:08:40+09:00",
    "broker_order_ref_hash": "sha256:8e5c7d81227df03b1fe21bb604a8b64c24d9f0ab1f428809218cc09388ce9f11",
    "reported_order_status": "accepted",
    "reported_cumulative_filled_quantity": "4",
    "reported_remaining_quantity": "10",
    "contradiction": "filled_plus_remaining_exceeds_original"
  },
  "expected_result": {
    "order_status": "unknown",
    "mismatch": "broker_truth_contradiction",
    "cash_delta_appended": false,
    "position_delta_appended": false,
    "reorder_allowed": false,
    "operator_review_required": true,
    "allowed_next_action": "refresh_broker_truth_for_same_ref_hash"
  },
  "record_hash": "sha256:bd955057c91a1ff0c3d8ff38dca371b287e80a2bca9d7b17bb3e0b140668259d"
}
```

## Failure probes

| probe | mutation | expected result |
| --- | --- | --- |
| `json_malformed` | Remove `schema_version` or make `fill_fragments` a string. | Reject before append. |
| `status_mismatch` | Set `order_status` to `filled` while `remaining_quantity` is `6`. | `broker_truth_contradiction`, map to `unknown`. |
| `hash_mismatch` | Change fill quantity without changing `record_hash`. | `broken_hash_chain` or `record_hash_mismatch`. |
| `arithmetic_mismatch` | Change cash after to `959970.00`. | `cash_mismatch`, no portfolio delta. |
| `interruption_duplicate_fill` | Replay after interruption and append the same fill fragment with a new ID. | `duplicate_fill_fragment`, keep original fragment. |
| `unknown_reorder` | Submit the same execution seed again after `unknown`. | `reorder_blocked_under_unknown`. |
| `forbidden_field` | Add `broker_order_id` or `account_number`. | `live_state_contamination`, reject before append. |
| `misleading_success` | Set `mismatch_count` to `1` while report says success. | `misleading_success_output`. |

## Acceptance criteria

1. Line 1 title and line 2 draft marker are exact, and no done marker exists.
2. The document defines `submitted`, `accepted`, `partial`, `filled`, `cancelled`, `rejected`, and `unknown` with broker truth requirements.
3. Retry semantics and idempotent recovery block duplicate orders and duplicate fill fragments.
4. Partial fill accounting defines decimal arithmetic for fill, fee, tax, cash delta, remaining quantity, and position delta.
5. Cash and position reconciliation mismatch handling is fail closed.
6. `unknown` blocks reorder and allows only same-reference broker truth refresh or operator review.
7. Happy partial fill fixture parses and proves `1000000.00 - 40000.00 - 40.00 = 959960.00` with remaining quantity `6`.
8. Unknown failure fixture parses and proves no cash delta, no position delta, and no reorder under unknown.
9. Failure probes cover JSON shape, status, hash, arithmetic, interruption, unknown reorder, forbidden field, and misleading success mutations.
10. Artifacts forbid field names `state` and `stage`, raw credentials, raw account IDs, raw broker order IDs, real broker submission, and `data/portfolio.json` mutation.
