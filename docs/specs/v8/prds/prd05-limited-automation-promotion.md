# PRD: v8 PRD 05 limited automation promotion
> **상태**: ✅ 구현 완료
> 상위 SPEC: [v8 SPEC](../SPEC.md)

## 문제

v8 PRD 01은 paper ledger를 정의하고, PRD 02는 operator approval dry-run을 고정한다. PRD 03은 주문 관찰과 대사를 fail closed로 처리하고, PRD 04는 risk gate와 kill switch를 정의한다. 아직 없는 계약은 이 흐름을 어느 조건에서 제한 자동화로 승격하고, 사고가 나면 어느 속도로 되돌리는지다.

## 사용법

```bash
uv run python -m src.v8.cli prd05-build
uv run python -m src.v8.cli prd05-verify
uv run python -m src.v8.cli prd05-verify --fixture docs/specs/v8/fixtures/prd05-limited-automation-promotion-incident.json
uv run python -m src.v8.cli prd05-acceptance
```

Canonical fixture는 `docs/specs/v8/fixtures/prd05-limited-automation-promotion-happy.json`과 `docs/specs/v8/fixtures/prd05-limited-automation-promotion-incident.json`이다. Fixture의 결과는 `expected_result`를 읽지 않고 typed evidence에서 계산한다.

Traffic sampling의 canonical seed는 `{"promotion_decision_id": string, "proposal_id": string, "trading_session": string}`이다. Canonical JSON SHA-256의 첫 8 hex를 unsigned integer로 읽어 `mod 10000` bucket을 만들고, `5.00%`는 bucket `< 500`만 선택한다. 동일 proposal replay는 항상 같은 결과를 내며 artifact에 없는 proposal은 먼저 deny-by-default scope gate에서 차단한다.

이 PRD의 limited automation은 실제 주문 자동화가 아니다. 시스템이 할 수 있는 일은 적격한 paper order를 자동으로 risk gate와 dry-run 후보로 올리고, 승인 필요 구간을 줄이며, 제한된 dry-run 요청을 자동으로 실행하는 것뿐이다. Live broker submit, live order 생성, live portfolio mutation, unlimited automation은 언제나 금지된다.

## 목표

1. `paper -> dry_run -> approval_required -> limited_automation` 승격 사다리를 정의한다.
2. Eligible symbol, order type, notional, traffic share, 동시 실행 수를 캡으로 고정한다.
3. Observation window와 승격 threshold를 정해 충분한 paper, dry-run, approval_required 증거가 없으면 승격하지 않는다.
4. Incident가 발생하면 자동 rollback과 kill switch 연동을 SLA 안에 끝낸다.
5. 재승격은 root cause, clean observation, 독립 승인, 축소 cap으로만 허용한다.
6. Happy limited promotion fixture와 incident auto rollback fixture를 제공한다.

## 범위 밖

1. 실제 broker 주문을 만들거나 전송하지 않는다.
2. Live account balance, account number, access token, client secret, raw live order ID를 읽거나 저장하지 않는다.
3. `data/portfolio.json`, `config.yaml`, `src/**`, `scripts/**`를 변경하지 않는다.
4. Unlimited automation, live submit, market order auto routing, margin, short selling, derivatives, after-hours order를 허용하지 않는다.
5. Dashboard, notification UI, market data 수집, broker adapter 구현을 요구하지 않는다.

## 현재 계약에서 소비하는 사실

| 출처 | 확인한 사실 | PRD에서 쓰는 방식 |
| --- | --- | --- |
| `docs/specs/v8/prds/prd01-paper-portfolio-ledger.md` | Paper order와 fill은 paper namespace, deterministic ID, hash chain을 쓴다. | Promotion evidence는 paper ledger replay와 hash를 입력으로 쓴다. |
| `docs/specs/v8/prds/prd02-operator-approval-dry-run.md` | Approval dry-run은 live submission이 아니며 quote freshness와 permission을 요구한다. | `dry_run`과 `approval_required` 승격 조건은 이 artifact를 참조한다. |
| `docs/specs/v8/prds/prd03-order-state-reconciliation.md` | Unknown, stale broker truth, mismatch는 reorder와 portfolio mutation을 막는다. | Promotion은 unknown이나 mismatch가 있으면 막히고 rollback한다. |
| `docs/specs/v8/prds/prd04-risk-controls-kill-switch.md` | Risk gate와 kill switch는 fail closed이며 dry-run 전 stale quote를 다시 검사한다. | Limited automation은 risk allow와 inactive kill switch가 없으면 동작하지 않는다. |

## Strict no real order boundary

| boundary | 규칙 | 실패 예 |
| --- | --- | --- |
| Automation output | Limited automation은 proposed order, risk decision, approval artifact, dry-run request, dry-run response만 만들 수 있다. | Broker submit, live order, live fill을 만든다. |
| Destination | 자동 목적지는 `internal_dry_run` 또는 `broker_dry_run`뿐이다. | `broker_live`, `toss_live`, `real_account`를 destination으로 쓴다. |
| Storage | Promotion artifact는 `data/paper/v8/promotion/**` 같은 전용 경로만 쓴다. | `data/portfolio.json`이나 credential 파일을 읽거나 갱신한다. |
| Identifier | Raw account ID, raw broker order ID, credential key는 artifact에 없어야 한다. | 값이 null이어도 forbidden key가 존재한다. |
| Authority | Cap, eligible universe, rollback SLA, prohibited actions는 artifact에 고정된다. | Cap 없이 all symbol, all notional, all order type을 허용한다. |

## Promotion ladder

Artifacts use `promotion_status` as the lifecycle field. Field names `state` and `stage` are forbidden.

| promotion_status | 의미 | 자동 허용 | 다음 조건 |
| --- | --- | --- | --- |
| `paper` | PRD 01 paper ledger만 실행한다. | Paper recommendation, paper order, paper fill replay. | Paper observation window 통과. |
| `dry_run` | PRD 02 dry-run 후보를 만들 수 있다. | Risk check와 operator approval 뒤 dry-run request. | Dry-run pass rate와 stale block 증거 통과. |
| `approval_required` | 시스템이 proposal과 checklist를 만들지만 매 건 운영자 승인이 필요하다. | Proposal, checklist, risk decision 생성. | Clean approval window와 no incident threshold 통과. |
| `limited_automation` | 적격 주문만 자동 risk check와 dry-run request까지 진행한다. | Eligible scope 안의 dry-run request, artifact append, auto rollback. | 재승격 또는 cap 변경은 별도 승인 필요. |
| `rolled_back` | 사고 뒤 제한 자동화를 끄고 이전 보수 status로 되돌린다. | Incident artifact, kill switch activation, read-only audit. | 재승격 조건을 새로 충족해야 한다. |

No promotion may skip a prior status. Terminal incident handling can move `limited_automation` to `approval_required`, `dry_run`, or `paper` based on severity. It never moves to an unlimited status.

## Promotion artifact schema

| field | required | rule |
| --- | --- | --- |
| `schema_version` | yes | `v8.limited_automation_promotion.decision.1` |
| `promotion_decision_id` | yes | `prom_v8_` plus canonical JSON seed hash first 20 hex |
| `promotion_status_before` | yes | Current `promotion_status` |
| `promotion_status_after` | yes | Requested next `promotion_status` |
| `requested_by` | yes | Redacted operator or `system.promotion_guard` |
| `approved_by` | conditional | Required for promotion and re-promotion, independent from requester |
| `effective_at` | yes | ISO 8601 with timezone |
| `expires_at` | yes | Limited automation expires without renewal |
| `eligible_scope` | yes | Symbol, order type, notional, market, and time scope |
| `blast_radius_caps` | yes | Per order, per symbol, per day, concurrent, and traffic caps |
| `observation_window` | yes | Evidence counts, duration, and threshold values |
| `incident_policy` | yes | Rollback SLA, severity mapping, re-promotion requirements |
| `source_hashes` | yes | PRD 01 to PRD 04 artifacts, policy, evidence, and kill switch hashes |
| `idempotency_key` | yes | Promotion request key |
| `record_hash` | yes | Full hash of artifact without `record_hash` |

Promotion and rollback records are append-only. Same idempotency key and same seed returns the existing record. Same key with a different seed returns `idempotency_conflict` and appends nothing.

## Eligible scope

| dimension | allowed in fixture policy | required guard | prohibited |
| --- | --- | --- | --- |
| Symbol | Explicit allow list, fixture uses `005930` and `000660` only. | Quote fresh, market open, no active kill switch, no unresolved incident. | Wildcard symbol, delisted symbol, halted symbol, synthetic symbol. |
| Market | `KR` regular session only. | Calendar evidence and quote source hash match PRD 04. | After-hours, pre-open, cross-market routing. |
| Side | BUY and risk-reducing SELL only. | PRD 04 says risk allowed, SELL quantity exists. | Short sell, exposure-increasing SELL, forced liquidation without approval. |
| Order type | Limit order only. | Limit price no worse than fresh quote guard and PRD 02 proposed order. | Market, stop, stop-limit, conditional, bracket, options, margin. |
| Notional | Per order `100000.00` KRW max in fixture policy. | Estimated notional plus fee and tax is under all caps. | Missing notional, negative notional, unlimited cap. |

Eligibility is deny by default. A symbol or order type not listed in the promotion artifact is blocked even if other risk checks pass.

## Blast radius caps

| cap | fixture value | enforcement |
| --- | --- | --- |
| Per order notional | `100000.00` KRW | Block before dry-run request if estimated notional plus fee and tax exceeds cap. |
| Per symbol daily notional | `200000.00` KRW | Sum accepted limited automation dry-run requests by symbol and trading day. |
| Total daily notional | `300000.00` KRW | Sum all eligible dry-run requests in the promotion namespace. |
| Concurrent requests | `1` | New request waits or blocks while one request lacks terminal dry-run response. |
| Traffic share | `5.00` percent of eligible proposals | Route only the deterministic sample slice under the cap. |
| Max eligible symbols | `2` | Promotion artifact names each symbol. No wildcard. |
| Max duration | `5` trading sessions | Expire back to `approval_required` unless renewed with fresh evidence. |

Cap checks use decimal string arithmetic. If cap evidence is missing, malformed, stale, or says `unlimited`, promotion and limited automation both block.

## Observation window and thresholds

| window | minimum evidence | threshold to pass |
| --- | --- | --- |
| Paper | 20 trading sessions and at least 30 paper orders. | 0 live contamination, 0 broken hash chain, reconciliation mismatch rate `0.00`. |
| Dry-run | At least 10 approved dry-run attempts. | Dry-run malformed response count `0`, duplicate idempotency count `0`, stale quote blocked count equals expected stale probes. |
| Approval required | 5 trading sessions and at least 10 approved proposals under the planned scope. | Operator override of blockers `0`, risk gate false allow `0`, incident count `0`. |
| Limited automation renewal | Most recent 5 trading sessions. | Incident count `0`, cap breach count `0`, rollback drill evidence fresh. |

Thresholds are minimums, not suggestions. Changing a threshold requires a new promotion artifact, an independent reviewer, and a new observation window hash. A threshold cannot be relaxed in place.

## Incident rollback policy

| severity | detection | automatic result | SLA |
| --- | --- | --- | --- |
| critical | Forbidden credential field, live destination, real order attempt, cap set to unlimited, kill switch unreadable. | Activate global kill switch and rollback to `paper`. | Stop new automation within 30 seconds, append incident within 2 minutes. |
| high | Cap breach, stale quote falsely fresh, market closed falsely open, risk blocker marked safe. | Rollback to `dry_run` and activate scoped kill switch. | Stop scope within 60 seconds, append incident within 5 minutes. |
| medium | Duplicate promotion record, delayed dry-run response, approval evidence missing. | Rollback to `approval_required`. | Stop scope within 5 minutes, append incident within 15 minutes. |
| low | Non-blocking evidence lag with no unsafe action. | Keep status, require renewal review. | Append warning within 1 trading day. |

Rollback is automatic when severity is critical, high, or medium. It does not wait for operator acknowledgement. It never submits a live order, cancels a live order, or mutates portfolio cash or position.

## Re-promotion after rollback

Re-promotion starts from the rolled back status and cannot jump directly to `limited_automation` unless every prior rung has fresh evidence.

| requirement | rule |
| --- | --- |
| Root cause | Incident record must name cause, affected scope, source hashes, and corrective artifact. |
| Clean window | At least 5 clean trading sessions after rollback for the affected scope. |
| Cap reduction | First re-promotion uses at most 50 percent of the prior per order, daily, and traffic caps. |
| Independent review | Approver differs from requester and from the operator tied to the incident. |
| Kill switch | Scoped switch must have an inactive record with verified hash chain. |
| Replay | PRD 01 to PRD 04 evidence must replay with no stale, dirty, misleading, malformed, or interruption errors. |

If any requirement is missing, re-promotion remains blocked. A second incident in the same scope during re-promotion forces rollback to `paper` and requires a new observation window.

## Prohibited actions

| action | result |
| --- | --- |
| Send broker live order or call submit endpoint. | Critical incident and rollback to `paper`. |
| Store or read account number, access token, client secret, raw broker order ID. | Critical incident and global kill switch. |
| Change `data/portfolio.json` cash, position, or history. | Critical incident and artifact rejection. |
| Use market, stop, stop-limit, margin, short, derivatives, or after-hours order. | Block before dry-run request. |
| Raise caps in place or set any cap to `unlimited`. | Reject promotion artifact. |
| Disable risk gate, quote freshness, market-hours check, idempotency, or kill switch. | High or critical incident based on scope. |
| Retry after unknown by creating a new order intent. | Block and require operator review. |

## JSON artifact and mutation contracts

| artifact | append path | forbidden mutation |
| --- | --- | --- |
| Promotion decision | `data/paper/v8/promotion/decisions.jsonl` | Changing status, eligible scope, caps, threshold, source hash, reviewer, or expiry. |
| Automation request | `data/paper/v8/promotion/automation_requests.jsonl` | Changing symbol, side, order type, notional, quote, risk decision, or dry-run response ref. |
| Incident | `data/paper/v8/promotion/incidents.jsonl` | Editing severity, scope, detected time, rollback result, or SLA timestamps. |
| Re-promotion review | `data/paper/v8/promotion/repromotion_reviews.jsonl` | Replacing root cause, clean window, cap reduction, reviewer, or kill switch proof. |
| Idempotency index | `data/paper/v8/promotion/idempotency_index.json` | Pointing one key to a different promotion seed. |

Every append record includes `schema_version`, `record_hash`, `prev_record_hash`, `source_hashes`, and `promotion_status` when it represents a promotion lifecycle fact. JSON parser failure, duplicate artifact ID, duplicate hash, missing schema version, invalid decimal string, forbidden key, missing cap, stale source hash, or full hash mismatch blocks the write before any artifact is appended.

## Happy limited promotion fixture

The fixture proves promotion from `approval_required` to `limited_automation` under fixed caps. It does not place an order.

```json
{
  "schema_version": "v8.limited_automation_promotion.prd05.fixture.1",
  "fixture_name": "happy_limited_automation_promotion",
  "strict_no_real_order": true,
  "promotion_decision": {
    "schema_version": "v8.limited_automation_promotion.decision.1",
    "promotion_decision_id": "prom_v8_3c7e2f8a5b9d1046aa21",
    "promotion_status_before": "approval_required",
    "promotion_status_after": "limited_automation",
    "requested_by": "operator_execution_lead_01",
    "approved_by": "operator_risk_reviewer_02",
    "effective_at": "2026-08-06T09:00:00+09:00",
    "expires_at": "2026-08-13T15:30:00+09:00",
    "idempotency_key": "idem_promotion_v8_fixture_1",
    "eligible_scope": {
      "markets": ["KR"],
      "symbols": ["005930", "000660"],
      "sides": ["BUY", "SELL"],
      "order_types": ["limit"],
      "risk_reducing_sell_only": true,
      "regular_session_only": true
    },
    "blast_radius_caps": {
      "per_order_notional_krw": "100000.00",
      "per_symbol_daily_notional_krw": "200000.00",
      "total_daily_notional_krw": "300000.00",
      "concurrent_requests": 1,
      "traffic_share_pct": "5.00",
      "max_eligible_symbols": 2,
      "max_duration_trading_sessions": 5,
      "unlimited_allowed": false
    },
    "observation_window": {
      "paper_sessions": 20,
      "paper_order_count": 35,
      "dry_run_attempts": 12,
      "approval_required_sessions": 6,
      "approval_required_count": 11,
      "live_contamination_count": 0,
      "hash_chain_break_count": 0,
      "risk_false_allow_count": 0,
      "incident_count": 0
    },
    "source_hashes": {
      "paper_ledger": "sha256:8c51c2fcfbaf51f5c5df75510a65d3db32d2d361d6ab8e0b7f222a66c9d7f215",
      "approval_dry_run": "sha256:ea8a87ec3adf92d25d5701d34f18ca5d181f5a7d5cce946a4521de170ac17ed4",
      "order_reconciliation": "sha256:97f04d9551fbe8915239df9df417f510c212743931e81231d3d7f5f3aab9439d",
      "risk_controls": "sha256:b7687edac7806257c0b732ab9b64b3020147561497d41e530baacbf6173df3ca",
      "promotion_policy": "sha256:1a94d798851b50142c0341b0a6d6c02f627182f0ad3d330a91a6422c1d75b8e2"
    },
    "record_hash": "sha256:3c7e2f8a5b9d1046aa21524b1b5d66c1a5cdbf20432ab54ad7773000d8f9023f"
  },
  "automation_request_sample": {
    "automation_request_id": "auto_v8_ea6b7e9c56f1130c4e40",
    "promotion_decision_id": "prom_v8_3c7e2f8a5b9d1046aa21",
    "ticker": "005930",
    "side": "BUY",
    "order_type": "limit",
    "estimated_notional": "100000.00",
    "estimated_fee": "100.00",
    "destination": "broker_dry_run",
    "live_submission": false,
    "risk_status": "allowed",
    "dry_run_request_allowed": true,
    "real_order_created": false,
    "portfolio_mutated": false
  },
  "expected_result": {
    "promotion_status": "limited_automation",
    "next_allowed_destination": "broker_dry_run",
    "limited_by_caps": true,
    "unlimited_allowed": false,
    "real_order_created": false,
    "portfolio_mutated": false
  }
}
```

## Incident auto rollback fixture

This fixture proves a stale quote false allow incident rolls back limited automation automatically. It does not send or cancel a real order.

```json
{
  "schema_version": "v8.limited_automation_promotion.prd05.failure_fixture.1",
  "fixture_name": "incident_auto_rollback_after_stale_quote_false_allow",
  "strict_no_real_order": true,
  "promotion_status_before": "limited_automation",
  "incident": {
    "incident_id": "inc_v8_26e5d924b70f0a317c8d",
    "detected_at": "2026-08-06T09:07:45+09:00",
    "severity": "high",
    "reason_codes": ["stale_quote_falsely_fresh"],
    "affected_scope": {
      "market": "KR",
      "ticker": "005930",
      "side": "BUY"
    },
    "bad_evidence": {
      "checked_at": "2026-08-06T09:07:45+09:00",
      "quote_expires_at": "2026-08-06T09:07:30+09:00",
      "reported_freshness_result": "fresh"
    },
    "rollback_sla_seconds": 60,
    "new_automation_stopped_at": "2026-08-06T09:08:10+09:00",
    "incident_appended_at": "2026-08-06T09:10:00+09:00",
    "sla_met": true,
    "real_order_created": false,
    "portfolio_mutated": false
  },
  "rollback_result": {
    "promotion_status_after": "dry_run",
    "kill_switch_scope": "ticker",
    "kill_switch_status": "active",
    "dry_run_request_allowed": false,
    "re_promotion_allowed_immediately": false,
    "required_re_promotion_evidence": [
      "root_cause_recorded",
      "five_clean_sessions",
      "cap_reduction_50_pct",
      "independent_review",
      "inactive_kill_switch_hash_chain"
    ]
  },
  "record_hash": "sha256:26e5d924b70f0a317c8d42dcc0d7f75fbfcf502db75850cb16f540d65a550d52"
}
```

## Mutation probes

| probe | mutation | expected result |
| --- | --- | --- |
| `json_malformed` | Remove `schema_version`, make decimal fields numbers, or add forbidden credential key. | Reject before append. |
| `state_field_present` | Add field name `state` or `stage` to a promotion artifact. | Reject with `forbidden_lifecycle_field`. |
| `threshold_relaxed_in_place` | Reduce paper session minimum, raise traffic share, or change incident threshold without a new decision. | Reject with `threshold_tampered`. |
| `cap_unlimited` | Set any cap to `unlimited` or omit cap value. | Reject with `unlimited_automation_forbidden`. |
| `interruption_duplicate_promotion` | Resume after promotion append and write a second decision for the same idempotency key. | Return stored decision and reject duplicate append. |
| `interruption_incident_half_written` | Incident exists without rollback result after interruption. | Complete rollback before any new automation request. |
| `misleading_success` | Report says promoted while incident count is positive, cap is breached, kill switch is active, or real order exists. | Fail with `misleading_promotion_success`. |
| `real_order_mutation` | Add `live_submission=true`, live destination, or raw broker order key. | Critical incident, rollback to `paper`, reject artifact. |
| `stale_source` | Source hash or quote freshness evidence is older than the observation cutoff. | Block promotion and require fresh replay. |
| `dirty_policy` | Evidence declares a policy hash that differs from the cap artifact read at promotion time. | Return `dirty_input` and append nothing. |

## Acceptance criteria

1. Line 1 title, line 2 `✅ 구현 완료` marker, and the parent SPEC `✅ 구현 완료` marker are exact.
2. The promotion ladder defines `paper`, `dry_run`, `approval_required`, `limited_automation`, and rollback behavior without an unlimited status.
3. Eligible symbols, order types, markets, sides, notional, traffic share, concurrent requests, duration, and symbol caps are defined.
4. Observation windows and thresholds cover paper, dry-run, approval_required, and limited automation renewal.
5. Incident rollback policy defines severity mapping, automatic rollback, kill switch scope, rollback SLA, and re-promotion requirements.
6. Prohibited actions include live broker submission, live IDs, credentials, portfolio mutation, market orders, margin, shorts, derivatives, after-hours order, cap increases in place, and unlimited automation.
7. Happy fixture reaches `promotion_status="limited_automation"` with fixed caps, dry-run destination only, no real order, and no portfolio mutation.
8. Incident fixture rolls back automatically after stale quote false allow, meets SLA, blocks new dry-run, and requires re-promotion evidence.
9. Mutation probes cover JSON shape, forbidden lifecycle fields, threshold tampering, interruption, misleading success, stale source, dirty policy, unlimited cap, and real order mutation.
