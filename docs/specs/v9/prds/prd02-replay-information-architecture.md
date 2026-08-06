# PRD: v9 PRD 02 replay information architecture
> **상태**: 📝 초안
> **SPEC 참조**: [v9 SPEC](../SPEC.md)

## 문제

v9 PRD 01은 대시보드가 읽을 envelope와 query result 계약을 정의했다. 하지만 사용자가 과거 추천을 다시 볼 때 필요한 정보 구조는 아직 분리되어 있지 않다. 추천 목록에서 어떤 항목을 고르고, 어떤 source가 결정에 쓰였고, 이후 outcome이 어떻게 붙었는지 한 흐름으로 읽을 수 있어야 한다.

이 PRD는 replay 정보를 탐색하는 정보 구조를 정의한다. 화면 구성, 시각 스타일, client cache, 서버 조회 API, replay 실행 계약은 새로 정의하지 않는다. v4 replay payload는 adapter example로만 언급하며, 그 payload가 준비됐는지 여부는 이 PRD의 선행 조건이 아니다.

## 목표

1. replay 탐색을 위한 navigation과 sitemap을 고정한다.
2. recommendation list와 detail에서 사용자가 볼 정보 묶음을 정의한다.
3. source -> decision -> outcome timeline을 한 recommendation 기준으로 연결한다.
4. filters, comparison, drilldown 규칙을 정의한다.
5. v9 PRD 01 envelope를 읽는 view model을 정의한다.
6. loading, empty, partial, error 조건을 성공처럼 보이지 않게 한다.
7. happy drilldown fixture와 missing outcome explicit fixture를 제공한다.

## 범위 밖

1. backend 계약을 재정의하지 않는다.
2. replay 실행, LLM 호출, broker 주문, portfolio mutation, source/data/config 변경을 요구하지 않는다.
3. visual component, layout pixel, animation, color token, client cache 구현은 다루지 않는다.
4. v4 문서나 future artifact의 완료 여부를 요구하지 않는다.
5. Rich 터미널 출력이나 localized prose를 business data로 파싱하지 않는다.

## 선행 입력

| 입력 | 이 PRD에서 쓰는 부분 | 경계 |
| --- | --- | --- |
| [v9 PRD 01 dashboard input contract](prd01-dashboard-input-contract.md) | `dashboard.event_envelope`, `dashboard.query_result`, freshness, quality, risk state, links, adapter boundary | 필수 입력 계약 |
| `recommendation.summary.v1` | 추천 목록 seed, ticker, market, consensus, action plan, freshness와 quality 표시 | PRD 01 payload를 재해석하지 않음 |
| `performance.detail.v1` | outcome summary가 있으면 detail 보조 정보로 표시 | 없으면 missing outcome으로 표시 |
| `replay.trace.v1` | future adapter example | 필수 선행 산출물이 아님 |
| v4 full workflow replay | adapter example | v9 정보 구조가 v4 실행 계약을 재정의하지 않음 |

## 용어

| 용어 | 의미 |
| --- | --- |
| replay IA | 과거 추천과 관련 evidence를 찾고 읽는 정보 구조 |
| navigation node | 사용자가 이동할 수 있는 정보 목적지 |
| view model | envelope와 links를 사람이 읽을 묶음으로 정렬한 read model |
| drilldown | 목록 항목에서 source, decision, outcome, evidence 세부 묶음으로 들어가는 탐색 |
| comparison | 둘 이상의 recommendation, run, horizon, market, ticker를 나란히 보는 구조 |
| explicit missing | 값이 없음을 빈 문자열, 0, 성공 상태로 숨기지 않는 표시 |

## Navigation sitemap

경로 이름은 정보 목적지 식별자다. routing 구현을 요구하지 않는다.

| Node | Purpose | Primary payloads | Required links |
| --- | --- | --- | --- |
| `/dashboard` | 전체 현황 진입 | `recommendation.summary.v1`, `performance.report.v1` | latest recommendation, replay home |
| `/dashboard/replay` | replay 탐색 홈 | query summaries | recommendations, comparisons, filters |
| `/dashboard/replay/recommendations` | 추천 replay 목록 | `recommendation.summary.v1` envelopes | detail, compare, source summary |
| `/dashboard/replay/recommendations/{subject_id}` | 추천 replay 상세 | selected recommendation envelope plus linked detail payloads | list, source, decision, outcome, evidence |
| `/dashboard/replay/comparison` | 추천 비교 | selected recommendation view models | each detail, filter return |
| `/dashboard/replay/sources` | source freshness와 provenance 탐색 | source references from envelopes | affected recommendation list |
| `/dashboard/replay/outcomes` | outcome 유무와 maturity 탐색 | performance or measurement adapter examples | affected recommendation list |

Navigation rules:

1. Every detail node must keep a return link to the list query that selected it.
2. A comparison node must show the selected subject IDs and the filter snapshot used to pick them.
3. Source and outcome nodes can be reached from detail, but they must not create new source or outcome contracts.
4. Missing linked data must show an explicit missing condition, not an empty section with a success label.
5. A blocked risk state can be browsed for audit, but it must not be promoted to actionable guidance.

## Recommendation list

The list is a scan surface for past recommendations. It should answer: what was recommended, when, how fresh the source was, what quality caveat exists, and whether more detail is available.

Required list columns:

| Group | Fields | Rule |
| --- | --- | --- |
| Identity | `subject_id`, `ticker`, `market`, optional `name`, `portfolio_scope` | Use envelope identity first, payload fields second. |
| Decision | action, consensus label, confidence, selected_by, risk level | Do not infer action from color or prose. |
| Time | produced_at, observed_at, data_cutoff_at, expires_at | Keep PRD 01 timestamp separation. |
| Freshness | freshness status, age, max age, source lag | Stale or expired rows stay visible with clear caveat. |
| Quality | quality status, score, failed checks | Degraded is not counted as ok. |
| Outcome | outcome status, horizon summary if present | Missing outcome is `missing`, not `0%`. |
| Links | detail, compare, source summary, outcome summary | Broken links are error conditions. |

List sorting and grouping:

1. Default sort is `timestamps.data_cutoff_at desc`, then `identity.subject_id asc`.
2. Group by `market`, `action`, `freshness.status`, `quality.status`, or `outcome.status`.
3. Pagination follows PRD 01 query result rules. Cursor values remain opaque.
4. A row may show multiple caveats. Freshness, quality, and risk caveats are separate.

## Recommendation detail

The detail node shows one recommendation as a trace. It does not recompute the decision.

Detail sections:

| Section | Content | Required behavior |
| --- | --- | --- |
| Header | ticker, market, subject ID, action, consensus, risk level | Show blocked, stale, and degraded caveats near the title. |
| Decision summary | signals, consensus, perspective votes if present, action plan | Missing optional fields use explicit missing labels. |
| Source summary | each source reference, adapter name, source ID, as-of, freshness, raw hash if allowed | Do not show secrets or raw account identifiers. |
| Timeline | source -> decision -> outcome events | Preserve timestamp labels and order. |
| Outcome summary | horizon, status, benchmark excess, absolute return, net execution when present | Pending or missing cannot look like loss or win. |
| Drilldown links | source evidence, perspective detail, risk reason, outcome detail, compare | Links must be typed and validated. |
| Quality notes | failed checks, degraded reason, malformed source error if present | Quality failure must remain visible after filtering. |

## Source -> decision -> outcome timeline

Timeline is an ordered reading model, not a replay executor. It uses known timestamps from envelopes and linked payloads.

| Timeline item | Required fields | Display rule |
| --- | --- | --- |
| `source_observed` | source ID, adapter, observed_at, as_of, freshness | If source is stale, the line remains visible with stale label. |
| `decision_input_cutoff` | data_cutoff_at, max source as-of if available | Later source data cannot be mixed into the decision block. |
| `decision_emitted` | produced_at, action, consensus, confidence, risk level | Action is copied from typed payload, not inferred. |
| `operator_or_execution` | operator decision or paper/live reference if linked | Missing link is explicit and neutral. |
| `outcome_matured` | horizon, outcome status, metrics, measurement source | Missing or pending outcome is not a failure unless the payload says so. |
| `evidence_checked` | quality checks, raw hash, link validation result | Malformed or broken evidence blocks the affected drilldown only. |

Ordering rules:

1. `decision_input_cutoff` must be at or before `decision_emitted`.
2. `source_observed` can appear after as-of if the adapter observed a cached value. The as-of field must still be shown.
3. Outcome items can appear after decision. They must not overwrite decision inputs.
4. If an item lacks a timestamp, it appears in an explicit missing timestamp group.

## Filters

Filters narrow the current query. They do not change payload meaning.

| Filter | Values | Notes |
| --- | --- | --- |
| Market | `KR`, `US`, `ALL`, exact exchange if present | `ALL` means a combined view, not a market value stored on one row. |
| Action | `BUY`, `SELL`, `HOLD`, `BLOCKED`, `CANDIDATE_REJECTED`, unknown | Unknown remains selectable for audit. |
| Freshness | fresh, stale, expired | Stale rows are not hidden by default when browsing replay. |
| Quality | ok, degraded, blocked | Degraded stays visible with reasons. |
| Risk | normal, watch, blocked | Blocked is browsable but not actionable. |
| Outcome | matured, pending, missing, insufficient_data, insufficient_context | Missing and pending are different. |
| Time | produced_at range, data_cutoff_at range | The filter label must name which timestamp it uses. |
| Source | adapter name, source ID, source freshness | Source filters use typed source refs only. |
| Comparison set | selected subject IDs | Selection is limited by query result identity, not row index. |

Filter rules:

1. Active filters must be serializable as JSON.
2. Active filters must be included in the list view model and comparison view model.
3. Clearing filters returns to the same default sort and pagination rule.
4. A filter that removes every row produces the empty condition, not an error condition.
5. A malformed filter produces a typed error condition.

## Comparison

Comparison lets a user inspect differences without merging meanings.

Comparison modes:

| Mode | Compares | Required columns |
| --- | --- | --- |
| `same_ticker_over_time` | one ticker across decision dates | action, consensus, cutoff, source freshness, outcome status |
| `same_run_cross_ticker` | recommendations from one request or correlation ID | ticker, market, action, risk level, quality, selected_by |
| `same_ticker_cross_horizon` | one recommendation across outcome horizons | horizon, maturity, benchmark excess, absolute return, data sufficiency |
| `source_impact` | rows sharing a source or adapter | source as-of, freshness, affected fields, quality checks |

Comparison rules:

1. Values are compared as typed fields. Formatted display strings are secondary.
2. Missing outcome values are shown as missing cells with reason codes.
3. Stale inputs remain stale in comparison, even if another row is fresh.
4. A comparison view must keep links back to each detail node.

## Drilldown

Drilldown links are typed. A link target can be unavailable, but the unavailable reason must be explicit.

Allowed drilldown targets:

| Target | Purpose | Required link fields |
| --- | --- | --- |
| `recommendation_detail` | selected recommendation trace | subject ID, payload type, query return link |
| `source_evidence` | source identity, as-of, freshness, quality | source ID, adapter name, link health |
| `decision_evidence` | signals, consensus, risk reasons, action plan | recommendation subject ID, decision timestamp |
| `outcome_evidence` | horizon and outcome metrics | recommendation subject ID, horizon, outcome status |
| `comparison_add` | add selected recommendation to comparison set | subject ID, current filters |

Drilldown rules:

1. A detail page reached from a list must preserve list context as `return_context`.
2. Drilldown never mutates a recommendation, source, outcome, portfolio, or config value.
3. Broken links produce a local link error and keep the rest of the detail readable.
4. Missing outcome drilldown opens an explicit missing outcome panel, not a blank chart.

## View model

The view model is the information structure consumed by a dashboard renderer. It is built from PRD 01 query results and links. It is not a server API contract.

```json
{
  "schema_name": "dashboard.replay_view_model",
  "schema_version": "1.0.0",
  "source_contract": "dashboard.query_result.1.0.0",
  "view_id": "replay_recommendation_detail_005930_20260806",
  "navigation": {
    "current_node": "/dashboard/replay/recommendations/{subject_id}",
    "breadcrumbs": [
      {"label": "Dashboard", "node": "/dashboard"},
      {"label": "Replay", "node": "/dashboard/replay"},
      {"label": "Recommendations", "node": "/dashboard/replay/recommendations"}
    ],
    "return_context": {
      "query_id": "qry_recommendation_happy_001",
      "cursor": null,
      "filters": {"market": "KR", "outcome_status": "matured"}
    }
  },
  "selected_recommendation": {
    "subject_id": "rec_20260806_005930_buy",
    "ticker": "005930",
    "market": "KR",
    "action": "BUY",
    "consensus_label": "강한 합의",
    "confidence": "high",
    "freshness_status": "fresh",
    "quality_status": "ok",
    "risk_level": "watch"
  },
  "timeline": [
    {
      "kind": "source_observed",
      "label": "market price source",
      "timestamp": "2026-08-06T09:05:00+09:00",
      "status": "fresh",
      "refs": ["src_market_kr_005930_20260806"]
    },
    {
      "kind": "decision_input_cutoff",
      "label": "decision data cutoff",
      "timestamp": "2026-08-06T09:05:00+09:00",
      "status": "locked",
      "refs": ["evt_recommend_20260806_005930_001"]
    },
    {
      "kind": "decision_emitted",
      "label": "BUY recommendation emitted",
      "timestamp": "2026-08-06T09:10:11+09:00",
      "status": "available",
      "refs": ["rec_20260806_005930_buy"]
    },
    {
      "kind": "outcome_matured",
      "label": "20 session outcome matured",
      "timestamp": "2026-09-03T15:30:00+09:00",
      "status": "matured",
      "refs": ["outcome_20260806_005930_20"]
    }
  ],
  "sections": {
    "source_summary": {
      "condition": "ready",
      "items": [
        {
          "source_id": "src_market_kr_005930_20260806",
          "adapter": "recommendation_json_adapter",
          "as_of": "2026-08-06T09:05:00+09:00",
          "freshness_status": "fresh",
          "quality_status": "ok"
        }
      ]
    },
    "decision_summary": {
      "condition": "ready",
      "action": "BUY",
      "signals": {"verdict": "BULLISH", "bull_votes": 5, "bear_votes": 1},
      "consensus": {"label": "강한 합의", "confidence": "high"}
    },
    "outcome_summary": {
      "condition": "ready",
      "items": [
        {
          "horizon_sessions": 20,
          "outcome_status": "matured",
          "gross_benchmark_excess_return_pct": "4.20",
          "gross_absolute_return_pct": "7.10",
          "data_sufficiency": "sufficient"
        }
      ]
    }
  },
  "drilldown_links": [
    {
      "rel": "source_evidence",
      "target_node": "/dashboard/replay/sources",
      "target_id": "src_market_kr_005930_20260806",
      "health": "ok"
    },
    {
      "rel": "outcome_evidence",
      "target_node": "/dashboard/replay/outcomes",
      "target_id": "outcome_20260806_005930_20",
      "health": "ok"
    }
  ],
  "conditions": {
    "loading": false,
    "empty": false,
    "partial": false,
    "error": false
  }
}
```

View model rules:

1. `selected_recommendation.subject_id` must match the envelope identity subject ID.
2. `timeline[].refs` must resolve to the selected recommendation, source, or linked outcome IDs.
3. `conditions.partial=true` is required when any section is degraded but the detail remains readable.
4. `conditions.error=true` is required for malformed query, unsupported version, or broken required identity.
5. `risk_level="blocked"` remains visible and does not become an actionable prompt.

## Loading, empty, partial, and error conditions

| Condition | Meaning | Required copy behavior | Must not do |
| --- | --- | --- | --- |
| `loading` | Query or linked payload has not arrived | Say which node is loading | Do not show stale previous detail as current |
| `empty` | Query is valid and returns no items | Show active filters and reset path | Do not call it an error |
| `partial` | Base recommendation is readable but linked source or outcome is missing, stale, or degraded | Show readable sections and caveats | Do not count degraded section as ok |
| `error` | Query, JSON, identity, version, or required link is invalid | Show typed error code and affected node | Do not show a success summary |

Condition precedence:

1. `error` overrides `partial`, `empty`, and `loading` for the affected node.
2. `partial` can coexist with ready sections.
3. `empty` applies only to valid list queries.
4. `loading` must include the current node and query ID when known.

## Fixture A: happy recommendation drilldown

This fixture shows a valid list to detail drilldown. It reads one PRD 01 recommendation envelope and one linked outcome summary. It does not run replay.

```json
{
  "fixture_name": "happy_recommendation_drilldown",
  "schema_name": "dashboard.replay_ia.fixture",
  "schema_version": "1.0.0",
  "input_query": {
    "schema_name": "dashboard.query_result",
    "schema_version": "1.0.0",
    "query_id": "qry_replay_list_kr_buy_001",
    "requested_payload_type": "recommendation.summary.v1",
    "returned_version": "1.0.0",
    "generated_at": "2026-08-06T09:10:12+09:00",
    "items": [
      {
        "schema_name": "dashboard.event_envelope",
        "schema_version": "1.0.0",
        "event_id": "evt_recommend_20260806_005930_001",
        "identity": {
          "subject_type": "recommendation",
          "subject_id": "rec_20260806_005930_buy",
          "market": "KR",
          "ticker": "005930",
          "portfolio_scope": "default"
        },
        "timestamps": {
          "produced_at": "2026-08-06T09:10:11+09:00",
          "observed_at": "2026-08-06T09:10:10+09:00",
          "data_cutoff_at": "2026-08-06T09:05:00+09:00",
          "expires_at": "2026-08-06T09:40:11+09:00"
        },
        "freshness": {"status": "fresh", "age_seconds": 311, "max_age_seconds": 1800},
        "quality": {"status": "ok", "checks": [{"name": "schema", "status": "pass"}]},
        "risk_state": {"level": "watch", "blocking": false, "reasons": ["sector_concentration_near_limit"]},
        "payload_type": "recommendation.summary.v1",
        "payload": {
          "recommendations": [
            {
              "ticker": "005930",
              "name": "삼성전자",
              "market": "KR",
              "sector": "반도체",
              "selected_by": ["score", "diversification"],
              "signals": {"verdict": "BULLISH", "bull_votes": 5, "bear_votes": 1},
              "consensus": {"consensus_verdict": "BUY", "consensus_label": "강한 합의", "confidence": "high"},
              "action_plan": {"type": "buy", "target_shares": 20, "first_tranche_shares": 10}
            }
          ]
        },
        "links": [
          {"rel": "outcome_evidence", "target_id": "outcome_20260806_005930_20", "payload_type": "performance.detail.v1"},
          {"rel": "source_evidence", "target_id": "src_market_kr_005930_20260806", "payload_type": "source.reference.v1"}
        ]
      }
    ],
    "summary": {"returned_count": 1, "fresh_count": 1, "degraded_count": 0, "blocked_count": 0},
    "warnings": []
  },
  "selected_subject_id": "rec_20260806_005930_buy",
  "expected_view_model": {
    "current_node": "/dashboard/replay/recommendations/{subject_id}",
    "selected_subject_id": "rec_20260806_005930_buy",
    "timeline_order": ["source_observed", "decision_input_cutoff", "decision_emitted", "outcome_matured"],
    "detail_condition": "ready",
    "drilldown_targets": ["source_evidence", "outcome_evidence"],
    "missing_outcome_visible": false
  }
}
```

## Fixture B: missing outcome explicit

This fixture proves that a recommendation can be readable while outcome evidence is absent. The absence is visible and neutral.

```json
{
  "fixture_name": "missing_outcome_explicit",
  "schema_name": "dashboard.replay_ia.fixture",
  "schema_version": "1.0.0",
  "input_query": {
    "schema_name": "dashboard.query_result",
    "schema_version": "1.0.0",
    "query_id": "qry_replay_list_kr_missing_outcome_001",
    "requested_payload_type": "recommendation.summary.v1",
    "returned_version": "1.0.0",
    "generated_at": "2026-08-06T09:10:12+09:00",
    "items": [
      {
        "schema_name": "dashboard.event_envelope",
        "schema_version": "1.0.0",
        "event_id": "evt_recommend_20260806_000660_001",
        "identity": {
          "subject_type": "recommendation",
          "subject_id": "rec_20260806_000660_buy",
          "market": "KR",
          "ticker": "000660",
          "portfolio_scope": "default"
        },
        "timestamps": {
          "produced_at": "2026-08-06T09:12:11+09:00",
          "observed_at": "2026-08-06T09:12:10+09:00",
          "data_cutoff_at": "2026-08-06T09:05:00+09:00",
          "expires_at": "2026-08-06T09:42:11+09:00"
        },
        "freshness": {"status": "fresh", "age_seconds": 431, "max_age_seconds": 1800},
        "quality": {"status": "degraded", "checks": [{"name": "outcome_link", "status": "warn", "reason": "outcome_not_available"}]},
        "risk_state": {"level": "normal", "blocking": false, "reasons": []},
        "payload_type": "recommendation.summary.v1",
        "payload": {
          "recommendations": [
            {
              "ticker": "000660",
              "name": "SK하이닉스",
              "market": "KR",
              "sector": "반도체",
              "selected_by": ["score"],
              "signals": {"verdict": "BULLISH", "bull_votes": 4, "bear_votes": 2},
              "consensus": {"consensus_verdict": "BUY", "consensus_label": "약한 합의", "confidence": "moderate"},
              "action_plan": {"type": "buy", "target_shares": 5, "first_tranche_shares": 3}
            }
          ]
        },
        "links": [
          {"rel": "outcome_evidence", "target_id": null, "payload_type": "performance.detail.v1", "health": "missing", "reason": "outcome_not_available"}
        ]
      }
    ],
    "summary": {"returned_count": 1, "fresh_count": 1, "degraded_count": 1, "blocked_count": 0},
    "warnings": ["outcome_not_available"]
  },
  "selected_subject_id": "rec_20260806_000660_buy",
  "expected_view_model": {
    "current_node": "/dashboard/replay/recommendations/{subject_id}",
    "selected_subject_id": "rec_20260806_000660_buy",
    "detail_condition": "partial",
    "outcome_condition": "missing",
    "outcome_copy": "Outcome evidence is not available for this recommendation.",
    "outcome_metrics": null,
    "missing_outcome_visible": true,
    "must_not_count_as_loss": true,
    "must_not_count_as_win": true
  }
}
```

## Failure probes

| Probe | Detection rule | Expected result |
| --- | --- | --- |
| `stale` | A row with `freshness.status="fresh"` has `age_seconds > max_age_seconds`, or stale source appears as current decision input | fail with `stale_mislabeled_fresh` |
| `dirty` | View model includes data parsed from Rich markup, localized prose, config, or untyped source instead of envelope fields | fail with `adapter_boundary_violation` |
| `misleading` | Missing outcome is shown as `0`, ok, win, loss, or fresh success | fail with `misleading_outcome` |
| `malformed` | JSON block is invalid, envelope lacks identity, timeline ref is broken, link target shape is wrong, or filter is not serializable | fail with `malformed_replay_view_model` |
| `broken_link` | Drilldown link has `rel` but no resolvable target or explicit missing reason | fail with `broken_drilldown_link` |

## Validation and failing-first evidence

Task 32 evidence must prove target absence before creation, then prove this PRD through manual Read and deterministic parsing.

Required checks:

1. Read this PRD from line 1 and confirm the title and one draft status line.
2. Confirm there is no done marker and no global numbered workflow reference.
3. Parse every fenced JSON block intended as JSON.
4. Validate sitemap nodes include replay home, recommendation list, recommendation detail, comparison, sources, and outcomes.
5. Validate happy drilldown: one recommendation can move from list to detail, timeline order is source -> decision -> outcome, and source plus outcome drilldown links exist.
6. Validate missing outcome: detail remains partial, outcome condition is missing, metrics are null, and the fixture does not count missing as win or loss.
7. Run JSON mutations: remove selected subject ID, remove timeline refs, make `conditions.error` a string, change `payload_type` without payload shape, and make active filters unserializable.
8. Run link mutations: remove `rel`, remove `target_id` without a missing reason, point a source link to an outcome node, and remove return context.
9. Run condition mutations: mark missing outcome as ready, count degraded outcome as ok, keep loading true while detail content is final, and label empty query as error.
10. Probe stale, dirty, misleading, malformed, and broken link cases.

## Acceptance criteria

1. The document has the exact draft metadata directly under the title and no done marker.
2. It defines navigation and sitemap for replay browsing.
3. It defines recommendation list and recommendation detail information groups.
4. It defines source -> decision -> outcome timeline rules.
5. It defines filters, comparison, and drilldown behavior.
6. It defines a v9 view model that consumes PRD 01 envelope and query result fields without redefining backend contracts.
7. It defines loading, empty, partial, and error conditions.
8. It includes happy recommendation drilldown and missing outcome explicit fixtures.
9. It includes JSON, link, condition mutation checks and stale, dirty, misleading, malformed probes.
10. It treats v4 replay and future payloads as adapter examples only.
