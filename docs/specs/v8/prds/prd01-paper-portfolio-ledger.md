# PRD: v8 PRD 01 paper portfolio ledger
> **상태**: 📝 초안
> 상위 SPEC: [v8 SPEC](../SPEC.md)

## 문제

현재 포트폴리오 코드는 `data/portfolio.json`의 `cash_krw`, `cash_usd`, `positions`, `history`를 직접 갱신한다. `src/portfolio/sizer.py`는 BUY와 SELL 계획을 만들지만, 그 계획이 가상 계좌에서 어떤 주문, 체결, 수수료, 잔고 변화로 이어졌는지 남기는 별도 원장은 없다.

이 PRD는 추천을 실제 주문으로 보내지 않고도 성과와 운영 위험을 검증할 수 있는 paper portfolio ledger를 정의한다. paper 계좌는 기존 live 포트폴리오와 같은 숫자를 흉내 낼 수 있지만, 파일 경로, ID, credential, 주문 목적지, reconciliation 결과가 live와 섞이면 실패다.

## 목표

1. recommendation identity를 paper 전용으로 만들고, 기존 추천 ID를 seed로 요구하지 않는다.
2. virtual cash, position, order, fill, fee, corporate action, reconciliation을 append-only ledger event로 남긴다.
3. deterministic fill 규칙을 고정해 같은 입력과 같은 idempotency key가 같은 fill과 잔고를 만든다.
4. ledger event마다 `prev_event_hash`와 `event_hash`를 저장해 hash chain을 검증한다.
5. paper와 live namespace, credential boundary를 분리한다.
6. replay fixture가 happy paper fill과 live state contamination failure를 모두 검증한다.

## 비목표

1. 실제 broker 주문을 전송하지 않는다.
2. live 계좌 잔고, live order ID, access token, client secret, account number를 읽거나 저장하지 않는다.
3. 기존 `data/portfolio.json`을 paper 원장으로 승격하지 않는다.
4. 다른 문서 묶음의 완료 여부를 요구하지 않는다.
5. 자동매매 승인, broker dry-run, 주문 reconciliation, kill switch는 여기서 구현하지 않는다.

## 현재 코드에서 소비하는 사실

| 파일 | 확인한 사실 | PRD에서 쓰는 방식 |
| --- | --- | --- |
| `src/portfolio/tracker.py` | mutable portfolio는 `cash_krw`, `cash_usd`, `positions`, `history`를 저장하고, buy와 sell helper가 즉시 저장한다. | paper ledger는 이 파일을 직접 바꾸지 않고, replay 결과만 같은 형태로 비교할 수 있다. |
| `src/portfolio/tracker.py` | partial sell history와 numpy JSON encoder가 있다. | paper fixture는 JSON 숫자를 string decimal로 저장해 numpy 타입과 부동소수 오차를 피한다. |
| `src/portfolio/sizer.py` | BUY plan은 entry, stop, shares, investment, cash after를 계산한다. SELL plan은 shares, proceeds, expected PnL을 계산한다. | paper order intent는 sizing output을 참조할 수 있지만, 실제 주문 목적지는 항상 `paper_engine`이다. |

## Namespace와 credential boundary

| boundary | 규칙 | 실패 예 |
| --- | --- | --- |
| paper namespace | 모든 paper ID는 `prec_v8_`, `pord_v8_`, `pfill_v8_`, `ppos_v8_`, `pevt_v8_`, `precon_v8_` prefix를 가진다. | live ID나 broker order ID가 paper event의 primary ID가 된다. |
| storage namespace | paper ledger는 `data/paper/v8/**` 같은 paper 전용 경로만 쓴다. | `data/portfolio.json`을 paper replay 중에 쓰거나 갱신한다. |
| order destination | paper order의 destination은 `paper_engine`뿐이다. | destination이 broker, toss, live, real account 값이다. |
| credential boundary | paper event와 fixture에는 `access_token`, `client_secret`, `account_number`, `live_order_id` field가 없어야 한다. | credential field가 null이어도 key가 존재한다. |
| source boundary | quote, corporate action, fee model은 redacted source hash와 as-of만 참조한다. | secret이나 raw account response를 provenance로 저장한다. |

## Identity 계약

모든 ID는 canonical JSON seed를 UTF-8로 직렬화한 뒤 SHA-256을 계산하고, prefix 뒤에 앞 20 hex를 붙인다. Canonical JSON은 key를 정렬하고, array 순서는 의미 있는 순서를 유지하며, 공백을 제거한다.

| ID | 형식 | seed |
| --- | --- | --- |
| `paper_recommendation_id` | `prec_v8_` + first 20 hex | schema version, paper namespace, decision time, ticker, side, quantity, limit price, source recommendation fingerprint |
| `paper_order_id` | `pord_v8_` + first 20 hex | paper recommendation ID, side, quantity, limit price, idempotency key, created time |
| `paper_fill_id` | `pfill_v8_` + first 20 hex | paper order ID, price source ID, quantity, fill price, filled time |
| `paper_position_id` | `ppos_v8_` + first 20 hex | paper namespace, ticker, currency |
| `paper_event_id` | `pevt_v8_` + first 20 hex | paper namespace, event type, occurred time, entity ref, previous event hash |
| `paper_reconciliation_id` | `precon_v8_` + first 20 hex | paper namespace, as-of, last fill ID or last event hash |

`paper_recommendation_id` is independent. A previous recommendation ID may appear as `external_recommendation_ref`, but it must not be required for seed generation.

## Ledger event schema

| field | required | rule |
| --- | --- | --- |
| `ledger_id` | yes | One stream per paper account or replay fixture. |
| `paper_namespace` | yes | Must begin with `paper:`. |
| `event_id` | yes | Deterministic `pevt_v8_` ID. |
| `event_type` | yes | One of the allowed event types below. |
| `event_version` | yes | Versioned schema string. |
| `occurred_at` | yes | Domain time, ISO 8601 with timezone. |
| `recorded_at` | yes | Writer time, never earlier than `occurred_at`. |
| `entity_ref` | yes | Entity type and entity ID. |
| `prev_event_hash` | yes | `sha256:genesis` for the first event, else prior event hash. |
| `payload` | yes | Typed payload for the event. |
| `quality_state` | yes | `available`, `degraded`, `blocked`, `unknown`, or `not_applicable`. |
| `event_hash` | yes | Full hash of the event with `event_hash` removed. |

Allowed event types are `PAPER_ACCOUNT_OPENED`, `PAPER_RECOMMENDATION_ACCEPTED`, `PAPER_ORDER_CREATED`, `PAPER_FILL_RECORDED`, `PAPER_POSITION_UPDATED`, `PAPER_CORPORATE_ACTION_APPLIED`, `PAPER_FEE_MODEL_CHANGED`, `PAPER_RECONCILED`, and `PAPER_CORRECTION_RECORDED`.

Ledger events are immutable. If a fill, fee, or corporate action is wrong, the writer appends `PAPER_CORRECTION_RECORDED` and then appends corrected downstream events. It never edits the old line.

## Virtual cash, positions, and fills

| object | required fields | arithmetic rule |
| --- | --- | --- |
| virtual cash | currency, opening balance, delta, closing balance | Decimal string arithmetic, two places for KRW fixture values unless source demands smaller unit. |
| virtual position | ticker, market, currency, quantity, average price, cost basis, realized PnL | BUY increases quantity and weighted average cost. SELL reduces quantity and realizes PnL. |
| virtual fill | order ID, fill ID, side, quantity, fill price, gross notional, fee, tax, net cash delta | BUY cash delta is negative gross notional minus fee. SELL cash delta is positive gross notional minus fee minus tax. |
| fee model | currency, fee bps, tax bps, rounding, effective interval | Fee and tax are part of replay input, not hidden constants. |

Arithmetic must use decimal values from the ledger payload. Float math that changes a cent or won after replay is a mismatch.

## Deterministic fill rule

Paper fills are deterministic simulations, not market claims.

| order type | fill rule | failure |
| --- | --- | --- |
| market buy | fill at the first accepted paper quote price at or after paper order time. | Quote has no as-of or is after replay cutoff when cutoff is enforced. |
| market sell | same quote rule, side is SELL. | Quote side creates negative position unless shorting is explicitly allowed. |
| limit buy | fill if source low or accepted quote is less than or equal to limit, price is min(limit, accepted quote). | Fill price is worse than limit. |
| limit sell | fill if source high or accepted quote is greater than or equal to limit, price is max(limit, accepted quote). | Fill price is worse than limit. |

Repeated submission with the same `idempotency_key` and identical order seed returns the same `paper_order_id` and `paper_fill_id`. If the payload differs under the same key, the result is `idempotency_conflict` and no new fill is appended.

## Corporate actions

Corporate action handling is part of replay, not an external adjustment hidden outside the ledger.

| action | required payload | replay effect |
| --- | --- | --- |
| split | ticker, ratio numerator, ratio denominator, effective session, source hash | Quantity and average price are adjusted inversely. Cost basis is unchanged except rounding remainder. |
| reverse split | same as split | Fractional quantity policy must be explicit. Cash-in-lieu is a cash event. |
| cash dividend | ticker, amount per share, currency, ex date, pay date, withholding rule, source hash | Cash increases on pay date. Position quantity is unchanged. |
| symbol change | old ticker, new ticker, effective session, source hash | Position identity keeps lineage and moves to new ticker. |

If corporate action provenance is missing and it affects position quantity, average price, or cash, reconciliation returns `blocked` for the affected interval.

## Reconciliation

Reconciliation replays the ledger from genesis and compares derived cash, positions, fills, and hash chain with the stored summary.

| check | pass condition | failure |
| --- | --- | --- |
| hash chain | Every `prev_event_hash` equals the prior `event_hash`, and every `event_hash` recomputes. | `broken_hash_chain`. |
| cash | Opening cash plus all decimal deltas equals replayed closing cash per currency. | `cash_mismatch`. |
| positions | Fills and corporate actions reproduce quantity, average price, and cost basis. | `position_mismatch`. |
| fees | Fee model and source values reproduce every fee and tax. | `fee_mismatch`. |
| namespace | Every event uses `paper:` namespace and no forbidden credential field exists. | `live_state_contamination`. |
| idempotence | Duplicate request with same key returns the existing order and fill. | `duplicate_fill`. |

## Failure probes

| probe | detection rule | expected result |
| --- | --- | --- |
| `stale_state` | Fill uses quote or corporate action source newer than the allowed replay cutoff, or stale derived summary replaces ledger replay. | Block replay for affected event. |
| `dirty_worktree` | Evidence claims deterministic replay while source, docs, data, or config inputs differ from declared hashes. | Do not trust the replay result. |
| `misleading_success_output` | Report says success while any hash, cash, position, fee, namespace, or idempotence check failed. | Fail report validation. |
| `malformed_input` | Invalid JSON, missing schema version, bad hash format, negative quantity, duplicate event ID, missing paper namespace, or forbidden credential key. | Fail before replay. |
| `repeated_interruption` | Resume after multiple interruptions appends duplicate fills, skips hash checks, or changes output for same idempotency key. | Fail idempotence and reconciliation. |
| `live_state_contamination` | Any event touches live storage, live account ID, live order ID, broker destination, or credential field. | Block paper ledger write. |

## Replay fixture

The fixture below is a contract sample. It does not send an order. It models one paper BUY fill with a 10 bps fee and proves the live boundary by listing forbidden fields.

```json
{
  "schema_version": "v8.paper_portfolio_ledger.prd01.fixture.1",
  "fixture_name": "happy_paper_fill_and_live_contamination_guard",
  "paper_namespace": "paper:v8:fixture",
  "live_namespace_forbidden": true,
  "credential_fields_forbidden": [
    "access_token",
    "account_number",
    "client_secret",
    "live_order_id"
  ],
  "fee_model": {
    "currency": "KRW",
    "fee_bps": "10",
    "sell_tax_bps": "0",
    "rounding": "decimal_half_up_2dp"
  },
  "starting_balances": [
    {
      "currency": "KRW",
      "cash": "1000000.00"
    }
  ],
  "recommendation": {
    "paper_recommendation_id": "prec_v8_1df70a8e23b72f301477",
    "schema_version": "v8.paper_portfolio_ledger.prd01.fixture.1",
    "paper_namespace": "paper:v8:fixture",
    "decision_at": "2026-08-06T09:05:00+09:00",
    "ticker": "005930",
    "side": "BUY",
    "quantity": "10",
    "limit_price": "10000.00",
    "source_recommendation_fingerprint": "sha256:4bdfec8f2cd850d455488f16d714b7d83b8647d576cf0a1322ec46606f5a1293"
  },
  "expected_after_replay": {
    "cash": {
      "KRW": "899900.00"
    },
    "positions": [
      {
        "paper_position_id": "ppos_v8_89a99d247fe4c907bd44",
        "ticker": "005930",
        "quantity": "10",
        "avg_price": "10000.00",
        "cost_basis": "100000.00"
      }
    ],
    "fills": [
      {
        "paper_fill_id": "pfill_v8_64097cfdd3848c8306cb",
        "gross_notional": "100000.00",
        "fee": "100.00",
        "net_cash_delta": "-100100.00"
      }
    ],
    "last_reconciliation_id": "precon_v8_67d3b897a660adea338e",
    "idempotency_key": "idem_paper_v8_fixture_1"
  },
  "events": [
    {
      "ledger_id": "pledger_v8_fixture",
      "paper_namespace": "paper:v8:fixture",
      "event_id": "pevt_v8_fd205f454010c3b3b3f6",
      "event_type": "PAPER_ACCOUNT_OPENED",
      "event_version": "v8.paper_portfolio_ledger.event.1",
      "occurred_at": "2026-08-06T09:00:00+09:00",
      "recorded_at": "2026-08-06T09:00:00+09:00",
      "entity_ref": {
        "entity_type": "paper_account",
        "entity_id": "pacct_v8_fixture"
      },
      "prev_event_hash": "sha256:genesis",
      "payload": {
        "cash": {
          "KRW": "1000000.00"
        },
        "positions": []
      },
      "quality_state": "available",
      "event_hash": "sha256:fc9acff20691522c08afd2c7490d6be00d8f6a2bbbacbb1e792f736d8d349fa1"
    },
    {
      "ledger_id": "pledger_v8_fixture",
      "paper_namespace": "paper:v8:fixture",
      "event_id": "pevt_v8_da6188e8b1649399ccad",
      "event_type": "PAPER_RECOMMENDATION_ACCEPTED",
      "event_version": "v8.paper_portfolio_ledger.event.1",
      "occurred_at": "2026-08-06T09:05:00+09:00",
      "recorded_at": "2026-08-06T09:05:00+09:00",
      "entity_ref": {
        "entity_type": "paper_recommendation",
        "entity_id": "prec_v8_1df70a8e23b72f301477"
      },
      "prev_event_hash": "sha256:fc9acff20691522c08afd2c7490d6be00d8f6a2bbbacbb1e792f736d8d349fa1",
      "payload": {
        "paper_recommendation_id": "prec_v8_1df70a8e23b72f301477",
        "ticker": "005930",
        "side": "BUY",
        "quantity": "10",
        "limit_price": "10000.00",
        "order_intent": "paper_only"
      },
      "quality_state": "available",
      "event_hash": "sha256:2e2191c3009ba9f3dde3dbadc19486a4daa2bf0a526a7f9179c3c3c9e4985807"
    },
    {
      "ledger_id": "pledger_v8_fixture",
      "paper_namespace": "paper:v8:fixture",
      "event_id": "pevt_v8_03e15f5b35560b39ae49",
      "event_type": "PAPER_ORDER_CREATED",
      "event_version": "v8.paper_portfolio_ledger.event.1",
      "occurred_at": "2026-08-06T09:06:00+09:00",
      "recorded_at": "2026-08-06T09:06:00+09:00",
      "entity_ref": {
        "entity_type": "paper_order",
        "entity_id": "pord_v8_401fb2527af3008c3980"
      },
      "prev_event_hash": "sha256:2e2191c3009ba9f3dde3dbadc19486a4daa2bf0a526a7f9179c3c3c9e4985807",
      "payload": {
        "paper_order_id": "pord_v8_401fb2527af3008c3980",
        "paper_recommendation_id": "prec_v8_1df70a8e23b72f301477",
        "side": "BUY",
        "quantity": "10",
        "limit_price": "10000.00",
        "idempotency_key": "idem_paper_v8_fixture_1",
        "destination": "paper_engine"
      },
      "quality_state": "available",
      "event_hash": "sha256:7ca9ed98cc0e6f0e523619364b6284260eba89e19386ef6decf9c017c1d39892"
    },
    {
      "ledger_id": "pledger_v8_fixture",
      "paper_namespace": "paper:v8:fixture",
      "event_id": "pevt_v8_f3b5ac17ed8afef31216",
      "event_type": "PAPER_FILL_RECORDED",
      "event_version": "v8.paper_portfolio_ledger.event.1",
      "occurred_at": "2026-08-06T09:07:00+09:00",
      "recorded_at": "2026-08-06T09:07:00+09:00",
      "entity_ref": {
        "entity_type": "paper_fill",
        "entity_id": "pfill_v8_64097cfdd3848c8306cb"
      },
      "prev_event_hash": "sha256:7ca9ed98cc0e6f0e523619364b6284260eba89e19386ef6decf9c017c1d39892",
      "payload": {
        "paper_fill_id": "pfill_v8_64097cfdd3848c8306cb",
        "paper_order_id": "pord_v8_401fb2527af3008c3980",
        "ticker": "005930",
        "side": "BUY",
        "quantity": "10",
        "fill_price": "10000.00",
        "gross_notional": "100000.00",
        "fee": "100.00",
        "net_cash_delta": "-100100.00",
        "price_source_id": "quote_v8_fixture_005930_20260806_090700",
        "fill_rule": "limit_cross_or_better"
      },
      "quality_state": "available",
      "event_hash": "sha256:cd01d2ee516fc9d60ccc8e12762eeb172d5be7564624e3851e3b201661a48ee6"
    },
    {
      "ledger_id": "pledger_v8_fixture",
      "paper_namespace": "paper:v8:fixture",
      "event_id": "pevt_v8_24de441175145f8c1907",
      "event_type": "PAPER_POSITION_UPDATED",
      "event_version": "v8.paper_portfolio_ledger.event.1",
      "occurred_at": "2026-08-06T09:07:00+09:00",
      "recorded_at": "2026-08-06T09:07:00+09:00",
      "entity_ref": {
        "entity_type": "paper_position",
        "entity_id": "ppos_v8_89a99d247fe4c907bd44"
      },
      "prev_event_hash": "sha256:cd01d2ee516fc9d60ccc8e12762eeb172d5be7564624e3851e3b201661a48ee6",
      "payload": {
        "paper_position_id": "ppos_v8_89a99d247fe4c907bd44",
        "ticker": "005930",
        "quantity": "10",
        "avg_price": "10000.00",
        "cost_basis": "100000.00",
        "cash_after": {
          "KRW": "899900.00"
        }
      },
      "quality_state": "available",
      "event_hash": "sha256:3b3be5bd0c6566aba06e1e3edef24bc2bf8dcba85f1a3d3ee85d3250e0a2fcc3"
    },
    {
      "ledger_id": "pledger_v8_fixture",
      "paper_namespace": "paper:v8:fixture",
      "event_id": "pevt_v8_df165d9903a6d2d4bc2d",
      "event_type": "PAPER_RECONCILED",
      "event_version": "v8.paper_portfolio_ledger.event.1",
      "occurred_at": "2026-08-06T09:08:00+09:00",
      "recorded_at": "2026-08-06T09:08:00+09:00",
      "entity_ref": {
        "entity_type": "paper_reconciliation",
        "entity_id": "precon_v8_67d3b897a660adea338e"
      },
      "prev_event_hash": "sha256:3b3be5bd0c6566aba06e1e3edef24bc2bf8dcba85f1a3d3ee85d3250e0a2fcc3",
      "payload": {
        "paper_reconciliation_id": "precon_v8_67d3b897a660adea338e",
        "replayed_cash": {
          "KRW": "899900.00"
        },
        "replayed_positions_hash": "sha256:de318972923f0458b0873bf6000afc07f9a65a8863ae166f3b8fba390e441161",
        "source": "ledger_replay",
        "mismatch_count": 0
      },
      "quality_state": "available",
      "event_hash": "sha256:447da8b769790d0cc17b3caeda4f11353b05158184e26d66a2101e271becddac"
    }
  ]
}
```

## Acceptance criteria

1. The PRD line 1 title and line 2 draft marker are exact and no completion marker exists.
2. The schema includes paper recommendation, virtual cash, virtual position, virtual fill, fee, corporate action, reconciliation, and hash-chain ledger contracts.
3. The fixture validates happy paper fill arithmetic: `1000000.00 - 100000.00 - 100.00 = 899900.00`.
4. The fixture validates hash chain recomputation and full `sha256:<64 hex>` event hashes.
5. In-memory mutations detect stale source, dirty declared input, misleading success, malformed JSON shape, repeated interruption duplicate fill, and live state contamination.
6. No real order, broker destination, credential field, or live portfolio mutation is required or allowed.
