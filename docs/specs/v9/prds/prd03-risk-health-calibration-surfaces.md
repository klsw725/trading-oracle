# PRD: v9 PRD 03 risk health calibration surfaces
> **상태**: 📝 초안
> **SPEC 참조**: [v9 SPEC](../SPEC.md)

## 문제

v9 PRD 01은 dashboard 입력 envelope를 정의했고, v9 PRD 02는 replay 탐색 구조를 정의했다. 하지만 운영자가 오늘 봐야 할 위험, 오래된 source, 신뢰도 보정 문제, paper와 live 차이를 한곳에서 읽는 표면은 아직 없다.

현재 추천 JSON은 `portfolio_sizing`, `action_plan`, `binding_constraints`를 담고, 성과 JSON은 `by_confidence`, `current_weights`, `details`를 담는다. 포트폴리오 health 계산은 cash floor, concentration, correlation, forced sell 후보를 만든다. 이 값들이 dashboard에 그대로 흩어지면 open risk가 숨거나 stale source가 정상처럼 보일 수 있다.

이 PRD는 risk inbox, source health, confidence reliability, paper/live divergence, alert, severity, acknowledgement 표면 계약을 정의한다. 화면 구현, backend API, portfolio 변경, broker 주문, source 수집, calibration 실행은 새로 정의하지 않는다.

## 목표

1. 운영자가 먼저 봐야 할 open risk를 inbox 항목으로 고정한다.
2. source health와 stale behavior를 정상 상태와 분리한다.
3. confidence reliability를 성과 적중률, reliability gap, Brier, ECE로 읽는 표면을 정의한다.
4. paper/live divergence를 account나 credential 없이 읽는 계약을 정의한다.
5. alert severity와 acknowledgement 표면을 정의하되 risk 사실 자체를 바꾸지 않는다.
6. JSON, view-state, mutation QA로 happy open risk와 stale health falsely normal 오류를 검증할 수 있게 한다.

## 범위 밖

1. 화면 component, layout, route, color, animation 구현은 다루지 않는다.
2. backend 조회 API, database schema, queue, cache, broker 연동을 재정의하지 않는다.
3. LLM 호출, replay 실행, recalibration 실행, paper fill 생성, live order 전송을 요구하지 않는다.
4. `scripts/**`, `src/**`, `data/**`, `config.yaml` 변경은 다루지 않는다.
5. Rich 터미널 출력, localized prose, account identifier, credential, raw config를 business data로 파싱하지 않는다.

## 선행 입력

| 입력 | 이 PRD에서 쓰는 부분 | 경계 |
| --- | --- | --- |
| v9 PRD 01 dashboard input contract | `dashboard.event_envelope`, `dashboard.query_result`, freshness, quality, risk state, links, adapter boundary | 필수 입력 계약 |
| v9 PRD 02 replay information architecture | navigation node, selected recommendation, timeline, drilldown, view model condition | 탐색 구조만 소비 |
| recommendation summary output | `portfolio_sizing`, `selection_constraints`, `recommendations[].action_plan`, consensus confidence | adapter를 거친 typed payload만 소비 |
| performance report output | `consensus`, `by_perspective`, `by_confidence`, `current_weights`, `details` | reliability 표면의 입력 예시 |
| portfolio health output | cash floor, available cash, buy block reason, overweight, forced sell, correlation, sector concentration, diversification | risk reason으로만 표시 |
| paper/live artifacts | paper event, live reference, reconciliation summary examples | account secret이나 live mutation은 금지 |

## 용어

| 용어 | 의미 |
| --- | --- |
| risk inbox | open, acknowledged, stale, blocked risk를 한 queue로 읽는 표면 |
| risk item | 하나의 subject에 연결된 위험 항목 |
| source health | source freshness, quality, affected field, lag를 합친 읽기 상태 |
| confidence reliability | confidence가 실제 correctness event와 얼마나 맞는지 보여주는 성과 표면 |
| divergence | paper와 live 또는 expected와 observed 값의 차이 |
| acknowledgement | 운영자가 위험을 봤다는 audit intent. 위험 사실을 수정하지 않는다 |
| view-state | renderer가 보여줄 condition, selected item, visible panel, disabled action 묶음 |

## Surface map

| Surface | Purpose | Primary payloads | Required behavior |
| --- | --- | --- | --- |
| `/dashboard/risk` | risk inbox 홈 | `risk.health.v1`, `recommendation.summary.v1` | open risk를 숨기지 않는다. |
| `/dashboard/risk/sources` | source health 탐색 | source references from envelopes | stale, expired, missing을 normal로 세지 않는다. |
| `/dashboard/risk/confidence` | confidence reliability 탐색 | `performance.report.v1`, calibration report examples | small sample과 legacy-only를 calibrated로 표시하지 않는다. |
| `/dashboard/risk/divergence` | paper/live 차이 탐색 | paper and live reference examples | paper와 live namespace를 섞지 않는다. |
| `/dashboard/risk/alerts` | severity별 alert list | risk alerts | severity, owner, due time, acknowledgement 상태를 보인다. |
| `/dashboard/risk/acknowledgements` | acknowledgement audit | acknowledgement view events | ack는 risk fact를 닫지 않는다. |

Surface rules:

1. Every risk surface consumes PRD 01 envelopes or PRD 02 view model links. It does not read source files directly.
2. Risk item identity uses `risk_item_id` and linked `subject_id`. Row index is never an identity.
3. A blocked, stale, degraded, or unknown condition remains visible after filters unless the operator explicitly filters it out.
4. Alerts and acknowledgements are view contracts. They are not broker commands and not portfolio mutations.
5. Missing source, missing paper link, or missing calibration sample is explicit. Empty string, zero, green label, or success count is invalid.

## Risk inbox contract

The inbox answers: what risk is open, why it matters, what subject it affects, what source supports it, and what safe action the operator can take next.

Required fields:

| Field | Required | Rule |
| --- | --- | --- |
| `risk_item_id` | yes | Stable ID for the logical risk item. |
| `subject` | yes | `subject_type`, `subject_id`, market, ticker when known. |
| `category` | yes | `portfolio_constraint`, `source_health`, `confidence_reliability`, `paper_live_divergence`, `system_health`, or `operator_attention`. |
| `severity` | yes | One of the severity values in this PRD. |
| `status` | yes | `open`, `acknowledged`, `snoozed`, `resolved_by_source`, `blocked`, or `stale`. |
| `opened_at` | yes | ISO 8601 timestamp with timezone. |
| `updated_at` | yes | Last visible risk update. |
| `evidence_links` | yes | Typed links to envelope, source health, performance, paper, or replay nodes. |
| `affected_fields` | yes | Fields the risk can change or block. Empty only when the risk is global. |
| `actionability` | yes | `informational`, `needs_review`, `blocks_action`, or `blocks_current_use`. |
| `available_actions` | yes | View actions allowed for this item. |

Inbox status rules:

1. `open` means the operator has not acknowledged the latest risk version.
2. `acknowledged` means the latest risk version was seen. It can still block actionability.
3. `snoozed` hides the item from default alert noise until `snooze_until`, but source health and blocked counts still include it.
4. `resolved_by_source` is allowed only when linked source or performance evidence shows the condition is no longer true.
5. `stale` means the risk item itself has not refreshed within its SLA. Stale risk cannot become normal by timeout.

Available action rules:

| Action | Allowed when | Required effect |
| --- | --- | --- |
| `open_detail` | Always | Opens typed drilldown. No data change. |
| `acknowledge` | `status` is `open` or `stale` | Creates acknowledgement view event. Does not alter severity or source health. |
| `snooze` | Severity is `info`, `watch`, or `action_required` | Requires reason and expiry. Blocked and critical cannot be snoozed. |
| `open_source` | Source evidence link exists | Opens source health detail. |
| `open_replay` | Recommendation subject link exists | Opens replay detail. |
| `open_divergence` | Paper or live reference exists | Opens divergence detail. |

## Severity taxonomy

| Severity | Meaning | Actionability | SLA for attention | Must not do |
| --- | --- | --- | --- | --- |
| `info` | Useful context that does not change decision quality. | `informational` | 7 days | Count as open blocker. |
| `watch` | Risk is near a limit or data quality is degraded. | `needs_review` | 1 trading day | Hide by default when open. |
| `action_required` | Operator should review before using current recommendation. | `needs_review` | same session | Mark actionable without review. |
| `blocking` | Current use is blocked for affected subject or field. | `blocks_current_use` | immediate | Count as healthy or fresh. |
| `critical` | Cross-surface safety issue, credential leak sign, namespace mix, or stale health falsely normal. | `blocks_action` | immediate | Snooze, auto-resolve, or downgrade without new evidence. |

Severity escalation rules:

1. A source with `freshness.status="stale"`, `expired`, `missing`, or `quality.status="blocked"` cannot produce `severity="info"` for affected current-use fields.
2. Any stale source summarized as healthy is `critical` with code `stale_health_falsely_normal`.
3. Paper/live namespace mix, broker credential field, or live order reference in a paper surface is `critical`.
4. Confidence reliability can be `watch` for low sample count and `action_required` when calibrated display is claimed without eligible samples.
5. Portfolio buy block, forced sell, cash floor breach, high correlation pair, or sector concentration creates at least `watch` risk.

## Source health surface

Source health is a read model over envelope freshness, quality, and source links. It does not refetch data.

Health labels:

| Label | Required meaning | Consumer rule |
| --- | --- | --- |
| `healthy` | Fresh, ok quality, timestamp order valid, no blocked affected field. | May be summarized as current. |
| `degraded` | Partial quality, unknown publish date, missing optional field, or low reliability. | Show caveat and affected fields. |
| `stale` | Source exceeds current-use SLA but remains useful for audit. | Do not count as healthy or current. |
| `expired` | Source exceeds audit TTL or explicit expiry. | Block current use for affected fields. |
| `blocked` | Malformed, contradiction, forbidden field, credential risk, or quality blocked. | Block affected surface and alert. |
| `missing` | Required source link or timestamp is absent. | Show missing condition, not zero. |

Required source health fields:

| Field | Rule |
| --- | --- |
| `source_health_id` | Stable ID for source health record. |
| `source_ref` | Adapter, source ID, payload type, raw hash if allowed. |
| `freshness_status` | Copied or derived from PRD 01 envelope. |
| `quality_status` | Copied or derived from PRD 01 envelope. |
| `health_label` | Must follow the label table. |
| `age_seconds` | Numeric when known. Null only with explicit missing reason. |
| `max_age_seconds` | Numeric policy for current-use source. |
| `affected_fields` | Examples: price, fundamentals, news context, confidence, paper fill, actionability. |
| `last_good_at` | Last known healthy time if known. |
| `stale_action` | `refetch_required`, `audit_only`, `block_current_use`, or `operator_review`. |

Stale behavior:

1. `age_seconds > max_age_seconds` with `health_label="healthy"` is invalid.
2. A stale source can remain visible for audit, but its affected current-use fields are `degraded` or `blocked`.
3. A fallback source never erases stale history. The source list shows original and fallback health separately.
4. Source health summary counts `healthy`, `degraded`, `stale`, `expired`, `blocked`, and `missing` separately.

## Confidence reliability surface

Confidence reliability reads performance and calibration examples. It does not compute new weights or apply tuning.

Metric definitions:

| Metric | Formula or rule | Display rule |
| --- | --- | --- |
| `eligible_sample_count` | Count of samples with numeric probability, action, horizon, and matured correctness outcome. | Show count and minimum side by side. |
| `hit_rate` | `hits / total` from existing performance report when target is legacy hit. | Label as hit rate, not calibrated probability. |
| `avg_confidence` | Weighted average of predicted probability in bucket. | Null when only display label exists. |
| `empirical_accuracy` | Weighted average of correctness outcome in bucket. | Null when target is undefined. |
| `reliability_gap` | `empirical_accuracy - avg_confidence`. | Positive and negative gaps keep signs. |
| `brier_score` | Mean weighted squared probability error. | Lower is better, no green label without cohort pass. |
| `ece` | Weighted absolute bucket gap. | Lower is better, no promotion meaning here. |
| `sample_state` | `eligible`, `insufficient_sample`, `legacy_only`, `pending`, or `malformed`. | Non-eligible states cannot show calibrated. |

Reliability rules:

1. `consensus_confidence` labels such as `high` or `moderate` are display labels unless a numeric probability and correctness outcome exist.
2. `by_confidence` hit rate can inform the surface, but it is not calibrated reliability by itself.
3. Legacy snapshots, pending outcomes, insufficient context, and malformed probability are visible but excluded from calibration metrics.
4. `current_weights` can be displayed as existing output, but this PRD does not approve changing them.
5. Small cohort result is `insufficient_sample`, not pass, not calibrated, and not a reason to change thresholds.

## Paper/live divergence surface

Paper/live divergence is a read-only comparison surface. It compares typed paper references and typed live references when they exist. Missing links are neutral and explicit.

Required divergence groups:

| Group | Fields | Required behavior |
| --- | --- | --- |
| Identity | paper namespace, live reference label, recommendation subject ID | Never use live account ID as display identity. |
| Cash | expected paper cash, observed live cash if linked, delta | Missing live cash is `missing_live_reference`, not zero. |
| Position | ticker, quantity, average price, market value, delta | Paper and live namespaces stay separate. |
| Order or fill | paper order/fill ID, live order reference if linked, status | No live order ID in paper primary ID. |
| Reconciliation | last check time, check status, failed checks | Any failed check keeps divergence open. |

Divergence severity rules:

1. Paper-only surface with no live link is `info` or `watch`, never a live failure.
2. Live reference missing while comparison is requested is `watch` with `missing_live_reference`.
3. Namespace contamination, credential field, or broker destination in paper payload is `critical`.
4. Non-zero cash, quantity, fill price, or reconciliation delta creates at least `action_required` until acknowledged and explained.
5. Divergence cannot be resolved by acknowledgement alone. It needs updated comparison evidence.

## Alerts and acknowledgement surface

Alerts are priority views over risk inbox items. Acknowledgement is a view event that proves the operator saw a risk version.

Alert fields:

| Field | Rule |
| --- | --- |
| `alert_id` | Stable per risk item version and severity. |
| `risk_item_id` | Links to inbox item. |
| `severity` | Same taxonomy as risk item. |
| `title` | Short human-readable summary. |
| `reason_codes` | Machine-readable causes. |
| `opened_at` | Time alert became visible. |
| `due_at` | Attention SLA deadline. |
| `ack_status` | `unseen`, `acknowledged`, `snoozed`, or `not_allowed`. |
| `default_visibility` | `visible`, `collapsed`, or `blocked_banner`. |

Acknowledgement request shape:

```json
{
  "schema_name": "dashboard.risk_acknowledgement_request",
  "schema_version": "1.0.0",
  "ack_request_id": "ackreq_20260806_risk_cash_floor_001",
  "risk_item_id": "risk_20260806_cash_floor_005930",
  "risk_version": "rv_20260806_001",
  "operator_ref": "operator_local_redacted",
  "requested_action": "acknowledge",
  "reason_code": "reviewed_before_decision",
  "comment": "Cash floor breach reviewed before acting.",
  "snooze_until": null,
  "requested_at": "2026-08-06T10:00:00+09:00",
  "client_context": {
    "view_id": "risk_inbox_20260806",
    "selected_risk_item_id": "risk_20260806_cash_floor_005930"
  }
}
```

Acknowledgement rules:

1. `acknowledge` requires current `risk_version`, operator reference, reason code, and timestamp.
2. `snooze` requires `snooze_until` and cannot apply to `blocking` or `critical` severity.
3. Acknowledgement does not change `severity`, `source_health`, `freshness`, `quality`, `divergence`, or `actionability`.
4. A new risk version resets `ack_status` to `unseen`.
5. Critical stale-health and namespace-contamination alerts have `ack_status="not_allowed"` for snooze.

## View model contract

The risk health view model is a dashboard read model. It groups PRD 01 envelopes, PRD 02 selected context, and risk links. It is not a server API contract.

```json
{
  "schema_name": "dashboard.risk_health_view_model",
  "schema_version": "1.0.0",
  "source_contract": "dashboard.query_result.1.0.0",
  "view_id": "risk_health_20260806_default",
  "navigation": {
    "current_node": "/dashboard/risk",
    "return_context": {"query_id": "qry_risk_health_20260806", "cursor": null, "filters": {"status": "open"}}
  },
  "summary": {
    "open_risk_count": 2,
    "blocking_count": 1,
    "critical_count": 0,
    "stale_source_count": 1,
    "healthy_source_count": 3,
    "acknowledged_count": 0,
    "paper_live_divergence_count": 1,
    "confidence_watch_count": 1
  },
  "selected_risk_item_id": "risk_20260806_cash_floor_005930",
  "risk_inbox": [
    {
      "risk_item_id": "risk_20260806_cash_floor_005930",
      "subject": {"subject_type": "recommendation", "subject_id": "rec_20260806_005930_buy", "market": "KR", "ticker": "005930"},
      "category": "portfolio_constraint",
      "severity": "blocking",
      "status": "open",
      "opened_at": "2026-08-06T09:10:12+09:00",
      "updated_at": "2026-08-06T09:10:12+09:00",
      "reason_codes": ["cash_floor_breach", "buy_block_reason_present"],
      "affected_fields": ["recommendation.actionability", "action_plan"],
      "actionability": "blocks_current_use",
      "evidence_links": [
        {"rel": "recommendation_detail", "target_id": "rec_20260806_005930_buy", "payload_type": "recommendation.summary.v1", "health": "ok"}
      ],
      "available_actions": ["open_detail", "acknowledge", "open_replay"]
    },
    {
      "risk_item_id": "risk_20260806_market_price_stale",
      "subject": {"subject_type": "source", "subject_id": "src_market_kr_005930_20260806", "market": "KR", "ticker": "005930"},
      "category": "source_health",
      "severity": "action_required",
      "status": "open",
      "opened_at": "2026-08-06T09:45:12+09:00",
      "updated_at": "2026-08-06T09:45:12+09:00",
      "reason_codes": ["source_stale"],
      "affected_fields": ["price", "recommendation.actionability"],
      "actionability": "blocks_current_use",
      "evidence_links": [
        {"rel": "source_evidence", "target_id": "srchealth_20260806_market_price", "payload_type": "source.health.v1", "health": "stale"}
      ],
      "available_actions": ["open_detail", "acknowledge", "open_source"]
    }
  ],
  "source_health": [
    {
      "source_health_id": "srchealth_20260806_market_price",
      "source_ref": {"adapter": "recommendation_json_adapter", "source_id": "market_price_kr_005930", "payload_type": "source.reference.v1"},
      "freshness_status": "stale",
      "quality_status": "degraded",
      "health_label": "stale",
      "age_seconds": 4200,
      "max_age_seconds": 1800,
      "affected_fields": ["price", "actionability"],
      "last_good_at": "2026-08-06T09:05:00+09:00",
      "stale_action": "block_current_use"
    }
  ],
  "confidence_reliability": {
    "condition": "partial",
    "items": [
      {
        "cohort_id": "conf_kr_buy_5d_legacy_report",
        "market": "KR",
        "action": "BUY",
        "horizon_sessions": 5,
        "eligible_sample_count": 12,
        "minimum_sample_count": 100,
        "sample_state": "insufficient_sample",
        "hit_rate": "0.58",
        "avg_confidence": null,
        "empirical_accuracy": null,
        "brier_score": null,
        "ece": null,
        "display_label": "Hit rate only, not calibrated reliability."
      }
    ]
  },
  "paper_live_divergence": {
    "condition": "partial",
    "items": [
      {
        "divergence_id": "div_20260806_paper_live_005930",
        "subject_id": "rec_20260806_005930_buy",
        "paper_namespace": "paper:v8:fixture",
        "live_reference_status": "missing_live_reference",
        "cash_delta": null,
        "position_delta": null,
        "severity": "watch",
        "open": true
      }
    ]
  },
  "alerts": [
    {
      "alert_id": "alert_20260806_cash_floor_001",
      "risk_item_id": "risk_20260806_cash_floor_005930",
      "severity": "blocking",
      "title": "Cash floor blocks current BUY actionability.",
      "reason_codes": ["cash_floor_breach"],
      "opened_at": "2026-08-06T09:10:12+09:00",
      "due_at": "2026-08-06T09:10:12+09:00",
      "ack_status": "unseen",
      "default_visibility": "blocked_banner"
    }
  ],
  "conditions": {"loading": false, "empty": false, "partial": true, "error": false}
}
```

View model rules:

1. `summary.open_risk_count` must equal visible and collapsed open inbox items, not only visible rows.
2. `summary.stale_source_count` must count stale source health records even when the matching inbox item is acknowledged.
3. `conditions.partial=true` is required when confidence or divergence data is incomplete but risk inbox is readable.
4. `conditions.error=true` is required for malformed JSON, broken identity, invalid severity, or stale source summarized as healthy.
5. `selected_risk_item_id` must resolve to a risk inbox item or be null with explicit reason.

## Fixture A: happy open risk visible

This fixture proves that open risk remains visible and actionable as a read surface.

```json
{
  "fixture_name": "happy_open_risk_visible",
  "schema_name": "dashboard.risk_health.fixture",
  "schema_version": "1.0.0",
  "input_view_model_ref": "risk_health_20260806_default",
  "expected": {
    "open_risk_count": 2,
    "selected_risk_item_id": "risk_20260806_cash_floor_005930",
    "selected_status": "open",
    "selected_severity": "blocking",
    "selected_available_actions": ["open_detail", "acknowledge", "open_replay"],
    "stale_source_visible": true,
    "paper_live_divergence_visible": true,
    "confidence_condition": "partial",
    "must_not_hide_open_risk": true,
    "must_not_mark_actionable": true
  }
}
```

## Fixture B: stale health falsely normal failure

This fixture is intentionally invalid. It proves the parser must reject stale health shown as normal.

```json
{
  "fixture_name": "stale_health_falsely_normal_failure",
  "schema_name": "dashboard.risk_health.failure_fixture",
  "schema_version": "1.0.0",
  "bad_source_health": {
    "source_health_id": "srchealth_bad_market_price",
    "freshness_status": "stale",
    "quality_status": "degraded",
    "health_label": "healthy",
    "age_seconds": 7200,
    "max_age_seconds": 1800,
    "affected_fields": ["price", "actionability"]
  },
  "bad_summary": {
    "healthy_source_count": 1,
    "stale_source_count": 0
  },
  "expected_result": "fail",
  "expected_error_code": "stale_health_falsely_normal",
  "expected_alert_severity": "critical"
}
```

## Stale behavior and actions

| Condition | Surface result | Allowed action | Forbidden result |
| --- | --- | --- | --- |
| Source is stale but audit-useful | `health_label="stale"`, risk item open or acknowledged | `open_source`, `acknowledge`, `refetch_required` label | `health_label="healthy"` |
| Source expired | `health_label="expired"`, affected current use blocked | `open_source`, `open_replay` | Count as current input |
| Health item itself is stale | Risk item status `stale` | `acknowledge`, `open_detail` | Auto-resolve as normal |
| Fallback exists | Show original and fallback source health | Compare both links | Delete original stale trace |
| Ack on stale risk | Ack status changes for the risk version | Keep stale counts and action block | Clear source health or severity |

## Metrics summary

| Metric | Source | Contract |
| --- | --- | --- |
| `open_risk_count` | Risk inbox | Counts all `open` and `stale` items. |
| `blocking_count` | Risk inbox | Counts items whose actionability blocks current use or action. |
| `critical_count` | Alerts | Counts critical alerts, including stale health falsely normal and namespace contamination. |
| `stale_source_count` | Source health | Counts source health records with `health_label="stale"`. |
| `healthy_source_count` | Source health | Counts only records that satisfy healthy rules. |
| `confidence_watch_count` | Confidence reliability | Counts cohorts with insufficient sample, legacy-only, pending, or malformed state. |
| `paper_live_divergence_count` | Divergence | Counts open divergence items. |
| `ack_lag_seconds` | Alerts and acknowledgement | Time from alert opened to valid acknowledgement. Null when unseen. |
| `mean_reliability_gap_abs` | Confidence reliability | Average absolute reliability gap across eligible cohorts. Null when not eligible. |
| `max_paper_live_delta_abs` | Divergence | Maximum absolute delta among comparable fields. Null when live reference is missing. |

Metric rules:

1. Counts cannot mix healthy with stale, degraded, expired, blocked, or missing.
2. Null means not available. Zero means measured zero.
3. Acknowledgement metrics do not reduce risk counts unless new evidence changes the risk item status.
4. Reliability metrics must show sample state before any score.
5. Divergence metrics must name namespace and cannot expose live account identifiers.

## Validation and failing-first evidence

Task 33 evidence must prove target absence before creation, then prove this PRD through manual Read and deterministic parsing.

Required checks:

1. Read this PRD from line 1 and confirm the title and one draft status line.
2. Confirm there is no done marker and no global numbered workflow reference.
3. Parse every fenced JSON block intended as JSON.
4. Validate risk health view model: summary counts, selected risk resolution, open risk visibility, source health, confidence reliability, divergence, alert, and conditions.
5. Validate happy open risk fixture: open risk is visible, selected item is blocking, actions are read-safe, stale source remains visible, and current use is not marked actionable.
6. Validate stale health failure fixture: stale freshness with healthy label fails with `stale_health_falsely_normal` and critical severity.
7. Run JSON mutations: remove `risk_item_id`, remove `severity`, make `source_health.age_seconds` a string, set `summary.open_risk_count` below actual open items, and make `conditions.error` a string.
8. Run view-state mutations: hide open risk while count stays positive, select a missing risk item without reason, mark partial confidence as ready, and show stale source as healthy.
9. Run acknowledgement mutations: omit reason code, snooze blocking risk, acknowledge stale risk while clearing stale count, and resolve divergence by ack only.
10. Probe stale, dirty, misleading, malformed, and forbidden mutation cases.

Probe expectations:

| Probe | Mutation | Expected result |
| --- | --- | --- |
| `stale` | Set `freshness_status="stale"` and `health_label="healthy"`. | fail with `stale_health_falsely_normal`. |
| `dirty` | Add data parsed from Rich markup, localized prose, config, or account identifier. | fail with `adapter_boundary_violation`. |
| `misleading` | Count stale source as healthy or open blocker as actionable. | fail with `misleading_risk_summary`. |
| `malformed` | Invalid JSON, missing identity, bad severity, string condition, or broken selected item. | fail with `malformed_risk_health_view_model`. |
| `forbidden_mutation` | Ack, snooze, or view action changes risk fact, source health, paper/live value, portfolio, or broker state. | fail with `forbidden_surface_mutation`. |

## Acceptance criteria

1. The document has exact draft metadata directly under the title and no done marker.
2. It defines risk inbox, source health, confidence reliability, paper/live divergence, alerts, severity, and acknowledgement surface contracts.
3. It defines metrics, stale behavior, stale actions, and severity escalation.
4. It defines a risk health view model that consumes v9 input and replay contracts without redefining backend contracts.
5. It includes happy open risk and stale health falsely normal failure fixtures.
6. It includes JSON, view-state, acknowledgement mutation checks and stale, dirty, misleading, malformed, forbidden mutation probes.
7. It does not require screen implementation, broker calls, portfolio mutation, source refetch, calibration execution, or source/data/config changes.
