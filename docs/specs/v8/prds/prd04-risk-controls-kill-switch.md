# PRD: v8 PRD 04 risk controls kill switch
> **상태**: 📝 초안
> 상위 SPEC: [v8 SPEC](../SPEC.md)

## 문제

v8 PRD 01은 paper ledger를 정의하고, PRD 02는 운영자 승인 뒤 dry-run만 허용하며, PRD 03은 redacted broker truth와 내부 artifact를 대사한다. 하지만 주문 의도가 dry-run으로 넘어가기 전에 현금, 보유 수량, 집중도, 시장 시간, quote freshness, 일일 손실, 위험 확인, kill switch를 같은 기준으로 막는 계약은 아직 없다.

현재 `src/portfolio/sizer.py`는 cash floor, 최대 보유 종목 수, 종목 집중도, 포트폴리오 손실, 상관 리스크를 계산한다. 이 값들이 사전 차단 규칙으로 고정되지 않으면 운영자가 dry-run 승인 화면에서 안전하지 않은 주문을 통과시키거나, stale quote와 장외 시간이 정상 주문처럼 보일 수 있다.

이 PRD는 실행 위험 통제와 kill switch 계약만 정의한다. 실제 주문, broker submit, portfolio mutation, market data 수집, dashboard 구현은 다루지 않는다.

## 목표

1. Pre-trade cash, position, concentration, correlation, market-hours, stale quote rule을 하나의 risk decision으로 합친다.
2. Daily loss limit과 forced reduction 우선 규칙을 fail closed로 고정한다.
3. Risk acknowledgement가 경고를 읽었다는 증거일 뿐 차단을 우회하지 못하게 한다.
4. Kill switch 권한, 자동 발동 조건, reset 절차, fail-closed 동작을 정의한다.
5. Risk artifact, fixture, hash, idempotency, interruption 복구 규칙을 append-only로 둔다.
6. Happy safe order와 cash 부족, stale quote failure fixture를 제공한다.

## 범위 밖

1. 실제 broker 주문을 만들거나 전송하지 않는다.
2. Live account balance, account number, access token, client secret, raw live order ID를 읽거나 저장하지 않는다.
3. `data/portfolio.json`, `config.yaml`, `src/**`, `scripts/**`를 변경하지 않는다.
4. PRD 05의 제한 자동화 승격, traffic share, rollback 정책을 확정하지 않는다.
5. Dashboard 화면, 알림 UI, source refetch, market calendar 구현을 요구하지 않는다.

## 현재 계약에서 소비하는 사실

| 출처 | 확인한 사실 | PRD에서 쓰는 방식 |
| --- | --- | --- |
| `src/portfolio/sizer.py` | `check_portfolio_health()`는 cash floor, available cash, max positions, overweight, forced sell, total PnL, can buy, buy block reason을 계산한다. | Risk gate는 이 값을 입력 예시로 삼지만 파일을 직접 호출하거나 갱신하지 않는다. |
| `src/portfolio/sizer.py` | 상관 리스크와 섹터 집중도는 포트폴리오 보유 종목 기준으로 `correlation_risk`, `sector_concentration`, `diversification_score`에 들어간다. | Concentration과 correlation 차단 규칙의 source field로 둔다. |
| `src/portfolio/correlation.py` | pair correlation, sector concentration, diversification score가 별도 계산된다. | High correlation pair와 sector concentration을 pre-trade blocker로 표현한다. |
| `docs/specs/v8/prds/prd01-paper-portfolio-ledger.md` | Paper ledger는 paper namespace와 hash chain을 쓴다. | Risk artifact도 paper 전용 경로와 hash를 쓴다. |
| `docs/specs/v8/prds/prd02-operator-approval-dry-run.md` | Approval dry-run은 quote freshness와 no real order boundary를 요구한다. | Risk gate는 approval 전과 dry-run 전 양쪽에서 quote freshness를 재검사한다. |
| `docs/specs/v8/prds/prd03-order-state-reconciliation.md` | Unknown, mismatch, stale truth는 fail closed이며 reorder를 막는다. | Risk gate도 unknown이나 stale safety input을 allow로 바꾸지 않는다. |

## Strict no real order boundary

| boundary | 규칙 | 실패 예 |
| --- | --- | --- |
| Decision output | Risk gate는 `allowed`, `blocked`, `requires_ack`, `kill_switch_active`만 반환한다. | Broker submit, live order creation, fill booking을 수행한다. |
| Destination | Risk gate가 통과해도 다음 목적지는 PRD 02의 `broker_dry_run` 또는 `internal_dry_run`뿐이다. | `broker_live`, `toss_live`, `real_account`를 destination으로 만든다. |
| Storage | Risk artifact는 `data/paper/v8/risk/**` 같은 전용 경로만 쓴다. | `data/portfolio.json`이나 live credential 파일을 읽거나 갱신한다. |
| Identifier | Artifact에는 raw account ID, raw broker order ID, credential key가 없어야 한다. | 값이 null이어도 `account_number`, `broker_order_id`, `live_order_id`, `access_token`, `client_secret` key가 있다. |
| Side effect | Risk acknowledgement와 kill switch reset은 artifact append만 허용한다. | Acknowledgement나 reset이 cash, position, order, fill을 바꾼다. |

## Risk decision envelope

Risk decision은 proposed order와 quote, portfolio snapshot hash, market calendar evidence, daily loss evidence, kill switch evidence를 읽어 하나의 결과를 만든다.

| field | required | rule |
| --- | --- | --- |
| `schema_version` | yes | `v8.risk_controls.decision.1` |
| `risk_decision_id` | yes | `risk_v8_` + canonical JSON seed hash first 20 hex |
| `proposed_order_id` | yes | PRD 02 proposed order ID |
| `paper_order_id` | yes | PRD 01 paper order ID |
| `ticker` | yes | Proposal, quote, position, correlation subject와 같아야 한다. |
| `side` | yes | `BUY` 또는 `SELL` |
| `quantity` | yes | Positive decimal string |
| `currency` | yes | `KRW` 또는 `USD` |
| `risk_status` | yes | `allowed`, `blocked`, `requires_ack`, or `kill_switch_active` |
| `blocking_reasons` | yes | Empty only when `risk_status="allowed"` or only ack warnings exist. |
| `ack_required_reasons` | yes | 경고 확인이 필요한 reason code list |
| `source_hashes` | yes | Portfolio, quote, market calendar, policy, kill switch input hash |
| `idempotency_key` | yes | Proposal과 risk check를 묶는 caller supplied key |
| `record_hash` | yes | Full hash of artifact without `record_hash` |

Artifacts must not use `state` as a lifecycle field name. The lifecycle field is `risk_status`.

## Pre-trade risk matrix

| Control | Applies to | Allow condition | Block code | Ack can override |
| --- | --- | --- | --- | --- |
| Cash available | BUY | `available_cash_after_cash_floor >= estimated_cash_effect_abs + fee + tax` | `cash_insufficient` | no |
| Cash floor | BUY | Cash ratio after order stays at or above regime floor. | `cash_floor_breach` | no |
| Position exists | SELL | Holding quantity for ticker is at least sell quantity. | `position_insufficient` | no |
| Max positions | BUY new ticker | Current distinct positions after order stay at or below max positions. | `max_positions_reached` | no |
| Single-name concentration | BUY or SELL that increases weight | Post-order ticker weight is at or below max weight. | `single_name_concentration` | no |
| Sector concentration | BUY | Sector weight after order is at or below policy threshold, or risk reducing SELL. | `sector_concentration` | no |
| Pair correlation | BUY | Candidate max absolute correlation with holdings is below policy threshold. | `pair_correlation_high` | no |
| Market hours | all | Target exchange is open for the order side and type at decision time. | `market_closed` | no |
| Stale quote | all | Quote is present, ticker matched, and `checked_at <= quote_expires_at`. | `stale_quote` | no |
| Daily loss | all risk-increasing actions | Day loss is above halt threshold and no forced halt is active. | `daily_loss_limit_hit` | no |
| Risk acknowledgement | warning only | Required ack exists for the same risk version and operator. | `risk_ack_missing` | yes, for warnings only |
| Kill switch | all | No active switch covers this market, account scope, ticker, or all order flow. | `kill_switch_active` | no |

Risk-reducing SELL can pass concentration and daily-loss warnings only when it reduces exposure, has a fresh quote, market is open, position exists, and no kill switch covers risk-reducing orders. It still cannot create a real order from this PRD.

## Cash and position rules

BUY cash checks use estimated gross notional plus fee and tax from PRD 02 dry-run estimate or internal estimate. If fee or tax is unknown, use the conservative configured upper bound. If no bound exists, block with `fee_tax_unknown`.

SELL position checks use a portfolio snapshot hash and decimal quantity. If the holding is missing, stale, malformed, or from a live account payload, block with `position_source_untrusted`. Short selling is not allowed unless a later PRD explicitly adds a separate contract.

Cash and position inputs are read snapshots. A passed risk decision never books cash, reserves shares, writes a fill, or changes `data/portfolio.json`.

## Concentration and correlation rules

| Risk | Required input | Block rule |
| --- | --- | --- |
| Single-name weight | Current market value, estimated post-order notional, total assets | Post-order weight exceeds `max_weight_pct`. |
| Sector weight | Sector lookup or declared sector source hash | Post-order sector weight exceeds `max_sector_weight_pct`. |
| Pair correlation | Correlation matrix as-of, window, threshold | Max absolute pair correlation is greater than threshold. |
| Diversification unknown | Source quality and as-of | Required concentration or correlation input is missing for a BUY. |

If correlation data is unavailable because fewer than two comparable holdings exist, the result is `not_applicable`. If holdings exist but the source is stale, malformed, or incomplete, the result is `blocked`, not `not_applicable`.

## Market-hours and stale quote rules

Market-hours input must name market, exchange calendar, session date, checked time, open interval, close interval, holiday flag, and source hash. Missing calendar evidence blocks with `market_calendar_missing`.

Quote input must include quote ID, source, ticker, currency, quote time, expiry time, side, price, source hash, and freshness result. Freshness is checked before risk decision and again immediately before PRD 02 dry-run request. A quote that becomes stale after risk approval changes the next risk decision to `blocked` with `stale_quote`.

No fallback close price may satisfy quote freshness for an order decision. A fallback close can be audit context only.

## Daily loss limit

Daily loss input compares day-start equity with current marked equity using decimal string arithmetic.

| field | rule |
| --- | --- |
| `loss_window` | One trading day in the target market timezone. |
| `day_start_equity` | Snapshot hash and timestamp required. |
| `current_equity` | Current marked value with source hashes required. |
| `daily_pnl_pct` | `(current_equity - day_start_equity) / day_start_equity * 100`. |
| `halt_threshold_pct` | Policy value, default example `-3.00` for fixture only. |
| `risk_increasing_action` | BUY or SELL that increases exposure. |

If `daily_pnl_pct <= halt_threshold_pct`, risk-increasing actions are blocked with `daily_loss_limit_hit`. Risk-reducing SELL may continue only if market is open, quote is fresh, holding exists, and kill switch policy allows reduction orders.

## Risk acknowledgement

Risk acknowledgement proves an operator saw a non-blocking warning. It is not permission to ignore a blocker.

| field | required | rule |
| --- | --- | --- |
| `risk_ack_id` | yes | `rack_v8_` + canonical JSON seed hash first 20 hex |
| `risk_decision_id` | yes | Decision being acknowledged |
| `risk_version` | yes | Hash of warnings, policy, subject, and source hashes |
| `operator_ref` | yes | Redacted operator identity |
| `permission` | yes | `risk.acknowledge` |
| `reason_code` | yes | Machine-readable acknowledgement reason |
| `acknowledged_at` | yes | ISO 8601 with timezone |
| `expires_at` | yes | Must be no later than quote expiry for order-specific warnings |
| `record_hash` | yes | Full hash of acknowledgement record |

An acknowledgement is invalid if the quote expired, risk version changed, operator lacks permission, or the decision has any blocking reason. Acknowledgement cannot change `risk_status`, source health, cash, position, order, fill, or kill switch coverage.

Machine-readable acknowledgement authority:

```json
{
  "schema_version": "v8.risk_controls.ack_authority.1",
  "authority_type": "risk_acknowledgement",
  "required_permission": "risk.acknowledge",
  "may_acknowledge_statuses": ["requires_ack"],
  "may_acknowledge_reason_classes": ["warning_only"],
  "must_match_fields": ["risk_decision_id", "risk_version", "operator_ref", "expires_at"],
  "forbidden_overrides": [
    "cash_insufficient",
    "cash_floor_breach",
    "position_insufficient",
    "max_positions_reached",
    "single_name_concentration",
    "sector_concentration",
    "pair_correlation_high",
    "market_closed",
    "stale_quote",
    "daily_loss_limit_hit",
    "kill_switch_active",
    "kill_switch_unreadable"
  ],
  "side_effects_allowed": ["append_acknowledgement_artifact"],
  "side_effects_forbidden": ["change_risk_status", "submit_order", "request_dry_run", "mutate_portfolio", "reset_kill_switch"]
}
```

## Kill switch authority

Kill switch can be manual or automatic. Manual actions require permission and append-only evidence. Automatic actions fire when critical safety input is missing or contradictory.

| Action | Actor | Permission | Required reason | Result |
| --- | --- | --- | --- | --- |
| Activate global switch | Operator | `risk.kill_switch.activate_global` | Required | Blocks all risk decisions in covered namespace. |
| Activate scoped switch | Operator | `risk.kill_switch.activate_scoped` | Required | Blocks market, ticker, side, or strategy scope. |
| Auto activate | System | `system.risk_guard` | Generated reason | Blocks covered scope when critical condition appears. |
| Reset scoped switch | Operator pair | `risk.kill_switch.reset` plus second reviewer | Required | Allows new risk decisions after reset checks pass. |
| Audit switch | Operator | `risk.kill_switch.audit` | Optional | Read-only, no mutation. |

Automatic activation conditions include forbidden credential field, live destination in paper artifact, broken risk hash chain, stale quote falsely marked fresh, market closed falsely marked open, daily loss input missing after order flow starts, or repeated interruption that cannot prove idempotence.

## Kill switch artifact

| field | required | rule |
| --- | --- | --- |
| `schema_version` | yes | `v8.risk_controls.kill_switch.1` |
| `kill_switch_id` | yes | `ksw_v8_` + canonical JSON seed hash first 20 hex |
| `switch_status` | yes | `active`, `reset_requested`, `reset_approved`, or `inactive` |
| `scope` | yes | `global`, `market`, `ticker`, `side`, `strategy`, or `operator` |
| `activated_by` | yes | Redacted operator ref or `system.risk_guard` |
| `activated_at` | yes | ISO 8601 with timezone |
| `reason_codes` | yes | Non-empty list |
| `covered_actions` | yes | Actions blocked by switch |
| `reset_requirements` | yes | Evidence and approvals required before inactive |
| `prev_record_hash` | yes | Prior switch stream hash or `sha256:genesis` |
| `record_hash` | yes | Full hash of artifact without `record_hash` |

If the kill switch artifact cannot be read, hash chain cannot be verified, or current coverage cannot be determined, the risk gate behaves as if a global switch is active. This is fail closed.

## Reset procedure

Reset never deletes the active switch. It appends reset request, review, and inactive records.

1. Operator with reset permission creates a reset request with root cause, affected scope, and source hashes.
2. A different reviewer confirms that forbidden field, stale source, broken hash, or daily loss condition is cleared.
3. System recomputes hash chain from genesis through the reset request.
4. Cooldown passes for the covered scope. Fixture default is 15 minutes.
5. New risk decision reads the inactive switch record and fresh source hashes before returning `allowed`.

If any reset input is missing, stale, self-approved, or hash mismatched, reset remains blocked and the prior active switch continues to cover the scope.

Machine-readable reset authority:

```json
{
  "schema_version": "v8.risk_controls.reset_authority.1",
  "authority_type": "kill_switch_reset",
  "required_permissions": ["risk.kill_switch.reset"],
  "required_independent_reviewers": 2,
  "self_approval_allowed": false,
  "required_evidence": [
    "root_cause_recorded",
    "fresh_quote_evidence",
    "market_calendar_evidence",
    "daily_loss_evidence_when_applicable",
    "hash_chain_recomputed",
    "forbidden_fields_absent"
  ],
  "cooldown_seconds": 900,
  "reset_result_if_missing_evidence": "blocked",
  "side_effects_allowed": ["append_reset_request", "append_reset_review", "append_inactive_switch_record"],
  "side_effects_forbidden": ["delete_active_switch", "submit_order", "request_dry_run", "mutate_portfolio"]
}
```

## JSON artifact and mutation contracts

| artifact | append path | forbidden mutation |
| --- | --- | --- |
| Risk decision | `data/paper/v8/risk/decisions.jsonl` | Changing status, reason, source hash, quantity, quote, policy, or idempotency key. |
| Risk acknowledgement | `data/paper/v8/risk/acknowledgements.jsonl` | Replacing operator, reason, risk version, or expiry. |
| Kill switch | `data/paper/v8/risk/kill_switches.jsonl` | Editing active coverage, reset approval, reason, or hash. |
| Risk idempotency index | `data/paper/v8/risk/idempotency_index.json` | Pointing one key to a different risk decision seed. |

Every append record includes `schema_version`, `record_hash`, `prev_record_hash`, `source_hashes`, and a lifecycle field specific to that artifact. JSON parser failure, duplicate artifact ID, duplicate record hash, missing schema version, invalid decimal string, forbidden key, missing source hash, or full hash mismatch blocks the write before any artifact is appended.

## Happy safe order fixture

The fixture proves a safe BUY can pass the risk gate and proceed only to dry-run. It does not place an order.

```json
{
  "schema_version": "v8.risk_controls.prd04.fixture.1",
  "fixture_name": "happy_safe_order_allowed",
  "strict_no_real_order": true,
  "proposed_order_id": "aprop_v8_f5e78bd2e22f115b7e08",
  "paper_order_id": "pord_v8_401fb2527af3008c3980",
  "risk_decision": {
    "schema_version": "v8.risk_controls.decision.1",
    "risk_decision_id": "risk_v8_7f9672a29d6e5bff6fd1",
    "ticker": "005930",
    "side": "BUY",
    "quantity": "10",
    "currency": "KRW",
    "estimated_notional": "100000.00",
    "estimated_fee": "100.00",
    "estimated_tax": "0.00",
    "risk_status": "allowed",
    "blocking_reasons": [],
    "ack_required_reasons": [],
    "idempotency_key": "idem_risk_v8_fixture_1",
    "source_hashes": {
      "proposal": "sha256:2a9b1775ee1d9ef7b391c94df26095a3ce1e89cd080936523052f050144dba87",
      "portfolio": "sha256:39765e5de752d6c15f6e7928500f268c958ec52a385305bac559e15e4126d905",
      "quote": "sha256:2f0bf376dcfd0e69f391a01cbbe6a9f4d393c96a58e626e1f29de6290904588b",
      "calendar": "sha256:40a8d14797d9c5b9975a9d36c5e79628e5edc43120c63663745307ba5e8c8e3f",
      "policy": "sha256:67c306789781b0249b71b1a2ef54899c4ed7ecdbcfbc2b9398f6af2ca3af633b",
      "kill_switch": "sha256:6bf7e9e4f1a6cd7f4b02315217c43f7818b71c6af02f88d5a93e6df9f60c6ea1"
    },
    "record_hash": "sha256:7f9672a29d6e5bff6fd1ddfbac946257a18f8a8147fdcd96c0fc90ba46831d88"
  },
  "inputs": {
    "cash": {
      "currency": "KRW",
      "available_cash_after_floor": "500000.00",
      "required_cash": "100100.00",
      "cash_floor_after_order_pct": "25.00"
    },
    "position": {
      "current_quantity": "0",
      "post_order_quantity": "10",
      "post_order_weight_pct": "10.00",
      "max_weight_pct": "33.00"
    },
    "concentration": {
      "sector_weight_after_pct": "40.00",
      "max_sector_weight_pct": "50.00",
      "max_pair_correlation": "0.42",
      "pair_threshold": "0.70"
    },
    "market_hours": {
      "market": "KR",
      "checked_at": "2026-08-06T09:07:15+09:00",
      "is_open": true,
      "source_hash": "sha256:40a8d14797d9c5b9975a9d36c5e79628e5edc43120c63663745307ba5e8c8e3f"
    },
    "quote": {
      "quote_id": "quote_v8_fixture_005930_20260806_090700",
      "quote_as_of": "2026-08-06T09:07:00+09:00",
      "quote_expires_at": "2026-08-06T09:07:30+09:00",
      "freshness_result": "fresh"
    },
    "daily_loss": {
      "day_start_equity": "1000000.00",
      "current_equity": "999000.00",
      "daily_pnl_pct": "-0.10",
      "halt_threshold_pct": "-3.00"
    },
    "kill_switch": {
      "switch_status": "inactive",
      "covered_actions": []
    }
  },
  "expected_result": {
    "risk_status": "allowed",
    "next_allowed_destination": "broker_dry_run",
    "real_order_created": false,
    "portfolio_mutated": false
  }
}
```

## Cash failure fixture

```json
{
  "schema_version": "v8.risk_controls.prd04.failure_fixture.1",
  "fixture_name": "cash_insufficient_blocks_order",
  "strict_no_real_order": true,
  "mutation": {
    "available_cash_after_floor": "50000.00",
    "required_cash": "100100.00"
  },
  "expected_result": {
    "risk_status": "blocked",
    "blocking_reasons": ["cash_insufficient"],
    "fail_closed": true,
    "ack_can_override": false,
    "dry_run_request_allowed": false,
    "reset_required": false,
    "reset_authority": "not_applicable",
    "real_order_created": false,
    "portfolio_mutated": false
  },
  "record_hash": "sha256:318ef5ab7290bd9f4d0870dc3777d7c9038e4f5dd73f1c80e5b216c409c4caa2"
}
```

## Stale quote failure fixture

```json
{
  "schema_version": "v8.risk_controls.prd04.failure_fixture.1",
  "fixture_name": "stale_quote_blocks_order",
  "strict_no_real_order": true,
  "mutation": {
    "checked_at": "2026-08-06T09:07:45+09:00",
    "quote_expires_at": "2026-08-06T09:07:30+09:00",
    "freshness_result": "stale"
  },
  "expected_result": {
    "risk_status": "blocked",
    "blocking_reasons": ["stale_quote"],
    "fail_closed": true,
    "ack_can_override": false,
    "dry_run_request_allowed": false,
    "reset_required": false,
    "reset_authority": "not_applicable",
    "real_order_created": false,
    "portfolio_mutated": false
  },
  "record_hash": "sha256:61b870bb6915d671019a33ccdc65f0801c996c5c77ff79f7698dab6f349d9de2"
}
```

## Market closed failure fixture

```json
{
  "schema_version": "v8.risk_controls.prd04.failure_fixture.1",
  "fixture_name": "market_closed_blocks_order",
  "strict_no_real_order": true,
  "mutation": {
    "market": "KR",
    "checked_at": "2026-08-06T08:45:00+09:00",
    "is_open": false,
    "calendar_session": "pre_open",
    "calendar_source_hash": "sha256:9ee4f7bbf8641ce843ea8a0284d98e5db1b26daaa7a590cc585588a73f9c2f7b"
  },
  "expected_result": {
    "risk_status": "blocked",
    "blocking_reasons": ["market_closed"],
    "fail_closed": true,
    "ack_can_override": false,
    "dry_run_request_allowed": false,
    "reset_required": false,
    "reset_authority": "not_applicable",
    "real_order_created": false,
    "portfolio_mutated": false
  },
  "record_hash": "sha256:313634e25e9bd29fdbf89e1cfb2d1bf3d45314452f2fd89bb7c39b7783c7c6a9"
}
```

## Position and max-position failure fixture

```json
{
  "schema_version": "v8.risk_controls.prd04.failure_fixture.1",
  "fixture_name": "position_and_max_position_breaches_block_order",
  "strict_no_real_order": true,
  "failure_cases": [
    {
      "case_name": "sell_quantity_exceeds_holding",
      "mutation": {
        "side": "SELL",
        "ticker": "005930",
        "current_quantity": "4",
        "requested_quantity": "10"
      },
      "expected_result": {
        "risk_status": "blocked",
        "blocking_reasons": ["position_insufficient"],
        "fail_closed": true,
        "ack_can_override": false,
        "dry_run_request_allowed": false,
        "reset_required": false,
        "reset_authority": "not_applicable",
        "real_order_created": false,
        "portfolio_mutated": false
      }
    },
    {
      "case_name": "new_buy_exceeds_max_positions",
      "mutation": {
        "side": "BUY",
        "ticker": "035420",
        "current_distinct_positions": 3,
        "max_positions": 3,
        "ticker_already_held": false
      },
      "expected_result": {
        "risk_status": "blocked",
        "blocking_reasons": ["max_positions_reached"],
        "fail_closed": true,
        "ack_can_override": false,
        "dry_run_request_allowed": false,
        "reset_required": false,
        "reset_authority": "not_applicable",
        "real_order_created": false,
        "portfolio_mutated": false
      }
    }
  ],
  "record_hash": "sha256:0eec2c40b814ef65417685a9f24dbf613b9797fb34bcbbfd7ca8a830f6a65b44"
}
```

## Daily loss failure fixture

```json
{
  "schema_version": "v8.risk_controls.prd04.failure_fixture.1",
  "fixture_name": "daily_loss_limit_blocks_risk_increasing_order",
  "strict_no_real_order": true,
  "mutation": {
    "side": "BUY",
    "day_start_equity": "1000000.00",
    "current_equity": "970000.00",
    "daily_pnl_pct": "-3.00",
    "halt_threshold_pct": "-3.00",
    "risk_increasing_action": true
  },
  "expected_result": {
    "risk_status": "blocked",
    "blocking_reasons": ["daily_loss_limit_hit"],
    "fail_closed": true,
    "ack_can_override": false,
    "dry_run_request_allowed": false,
    "reset_required": false,
    "reset_authority": "not_applicable",
    "real_order_created": false,
    "portfolio_mutated": false
  },
  "record_hash": "sha256:bd31bbaea49170fe928540f3d8919ecf9c269843be6cd12198defdbed1bc8805"
}
```

## Kill switch failure fixture

```json
{
  "schema_version": "v8.risk_controls.prd04.failure_fixture.1",
  "fixture_name": "active_kill_switch_blocks_scope",
  "strict_no_real_order": true,
  "kill_switch": {
    "schema_version": "v8.risk_controls.kill_switch.1",
    "kill_switch_id": "ksw_v8_63b3c10a7875a035117d",
    "switch_status": "active",
    "scope": "market",
    "scope_value": "KR",
    "activated_by": "operator_risk_admin_01",
    "activated_at": "2026-08-06T09:06:00+09:00",
    "reason_codes": ["stale_quote_falsely_fresh"],
    "covered_actions": ["BUY", "SELL"],
    "reset_requirements": ["fresh_quote_evidence", "hash_chain_recomputed", "second_reviewer"],
    "prev_record_hash": "sha256:genesis",
    "record_hash": "sha256:63b3c10a7875a035117d6760ddf5ca8ad1b9533f09073c1ddedb4d2712162ddf"
  },
  "expected_result": {
    "risk_status": "kill_switch_active",
    "blocking_reasons": ["kill_switch_active"],
    "fail_closed": true,
    "ack_can_override": false,
    "dry_run_request_allowed": false,
    "reset_required": true,
    "reset_authority": {
      "required_permissions": ["risk.kill_switch.reset"],
      "required_independent_reviewers": 2,
      "self_approval_allowed": false
    },
    "real_order_created": false,
    "portfolio_mutated": false
  }
}
```

## Unreadable kill switch failure fixture

```json
{
  "schema_version": "v8.risk_controls.prd04.failure_fixture.1",
  "fixture_name": "unreadable_kill_switch_state_fails_closed",
  "strict_no_real_order": true,
  "mutation": {
    "kill_switch_read_result": "unreadable",
    "kill_switch_hash_chain_verified": false,
    "current_coverage_determined": false,
    "read_error_code": "missing_or_corrupt_kill_switch_stream"
  },
  "expected_result": {
    "risk_status": "kill_switch_active",
    "blocking_reasons": ["kill_switch_unreadable"],
    "fail_closed": true,
    "ack_can_override": false,
    "dry_run_request_allowed": false,
    "reset_required": true,
    "reset_authority": {
      "required_permissions": ["risk.kill_switch.reset"],
      "required_independent_reviewers": 2,
      "self_approval_allowed": false,
      "required_evidence": ["hash_chain_recomputed", "kill_switch_stream_readable"]
    },
    "real_order_created": false,
    "portfolio_mutated": false
  },
  "record_hash": "sha256:e55a42dce91ac6b3371d3139ba15cae2c9e13d601a0c35d94cd25ad65bc4f292"
}
```

## Mutation probes

| Probe | Mutation | Expected result |
| --- | --- | --- |
| `json_malformed` | Remove `schema_version`, make decimal fields numbers, or add forbidden credential key. | Reject before append. |
| `status_mutation` | Change `risk_status` from `blocked` to `allowed`, or add field name `state`. | Fail with `risk_status_tampered`. |
| `hash_mutation` | Change quantity, source hash, switch coverage, or blocking reason without changing `record_hash`. | Fail with `record_hash_mismatch`. |
| `interruption_duplicate` | Resume after decision append and write a second decision for the same idempotency key. | Return stored decision and reject duplicate append. |
| `stale_quote` | Set quote freshness to fresh while `checked_at` is after expiry. | Block with `stale_quote_falsely_fresh`. |
| `market_closed` | Set `is_open=true` while calendar source says holiday. | Block with `market_hours_contradiction`. |
| `cash_failure` | Required cash exceeds available cash after floor. | Block with `cash_insufficient`. |
| `position_failure` | SELL quantity exceeds holding quantity. | Block with `position_insufficient`. |
| `daily_loss_failure` | Daily PnL is at or below halt threshold for a BUY. | Block with `daily_loss_limit_hit`. |
| `kill_switch_unreadable` | Current switch hash chain cannot be read or verified. | Treat as global active switch. |
| `ack_override_blocker` | Add acknowledgement to a decision with `cash_insufficient`. | Keep blocked decision. |
| `misleading_success` | Report says safe while any blocking reason exists. | Fail with `misleading_risk_success`. |

## Acceptance criteria

1. Line 1 title and line 2 draft marker are exact, and no green check marker exists.
2. Pre-trade cash, position, concentration, correlation, market-hours, stale quote, daily loss, risk acknowledgement, and kill switch contracts are present.
3. Risk matrix names allow conditions, block codes, and whether acknowledgement can override each control.
4. Kill switch authority, automatic activation, reset procedure, and fail-closed unreadable behavior are defined.
5. Happy safe order fixture reaches `risk_status="allowed"` and permits only dry-run destination with no real order and no portfolio mutation.
6. Cash, stale quote, market closed, position, max-position, daily loss, active kill switch, and unreadable kill switch fixtures block dry-run and prove no real order or portfolio mutation.
7. Every failure fixture has machine-readable `fail_closed`, `ack_can_override`, `dry_run_request_allowed`, `reset_required`, and `reset_authority` or explicit reset authority object.
8. Mutation probes cover JSON shape, status field tampering, hash mismatch, interruption duplicate, stale quote, market closed, cash, position, daily loss, kill switch unreadable, acknowledgement override, and misleading success.
9. Artifacts forbid raw credentials, raw account IDs, raw broker order IDs, live destination, broker submit, and `data/portfolio.json` mutation.
