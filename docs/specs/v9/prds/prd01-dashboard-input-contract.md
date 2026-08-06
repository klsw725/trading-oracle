# PRD: v9 PRD 01 dashboard input contract
> **상태**: 📝 초안
> **SPEC 참조**: [v9 SPEC](../SPEC.md)

## 문제

Trading Oracle의 추천, 성과, 리스크, 품질 정보는 지금 명령별 JSON과 Rich 터미널 출력에 흩어져 있다. `scripts/recommend.py --json`은 추천 결과를 반환하고, `scripts/performance.py report --json`은 성과 요약을 반환하며, `src/output/formatter.py`는 사람이 보는 터미널 카드를 만든다. 대시보드 입력은 이 세 표면을 그대로 소비하면 안 된다. 출력 모양, 최신성, 품질, 리스크 의미가 서로 다르기 때문이다.

이 PRD는 대시보드가 읽는 독립 입력 계약을 정의한다. 다른 SPEC payload는 adapter 예시로만 등장하며, 영문 검증 문구로는 adapter examples다. 그 payload가 준비됐는지 여부는 이 계약의 선행 게이트가 아니다.

## 목표

1. 모든 입력을 typed event envelope와 typed query result로 감싼다.
2. identity, timestamp, freshness, quality, risk state를 값으로 고정한다.
3. cursor 기반 pagination과 version negotiation을 정의한다.
4. adapter boundary를 두어 기존 script JSON과 터미널 formatter가 직접 대시보드 입력이 되지 않게 한다.
5. happy valid payload와 unsupported version error를 손으로 읽고 deterministic parser로 검증할 수 있게 한다.

## 범위 밖

1. 화면 구성, visual component, layout, routing, client cache 구현은 다루지 않는다.
2. 주문, broker 연동, 자동매매, portfolio mutation은 다루지 않는다.
3. `scripts/**`, `src/**`, `data/**`, `config.yaml` 변경은 다루지 않는다.
4. 다른 SPEC payload를 이 PRD의 필수 선행 산출물로 두지 않는다.

## 용어

| 용어 | 의미 |
| --- | --- |
| envelope | payload의 identity, timestamp, freshness, quality, risk state를 포함한 외피 |
| query result | envelope 목록을 pagination과 negotiation 결과와 함께 반환하는 조회 응답 |
| adapter | 기존 command output이나 향후 artifact를 대시보드 입력 계약으로 변환하는 경계 |
| producer | envelope를 만든 adapter 또는 service 식별자 |
| payload type | `recommendation.summary.v1`, `performance.report.v1` 같은 typed payload 이름 |
| risk state | 입력 소비자가 위험도를 오해하지 않도록 붙는 `normal`, `watch`, `blocked` 분류 |

## Envelope 계약

모든 event는 아래 필드를 가진다. `payload`만 payload type별 schema를 따른다.

```json
{
  "schema_name": "dashboard.event_envelope",
  "schema_version": "1.0.0",
  "min_reader_version": "1.0.0",
  "event_id": "evt_20260806_recommend_005930_01",
  "correlation_id": "corr_20260806_operator_dashboard_01",
  "request_id": "req_20260806_recommend_all_01",
  "producer": {
    "name": "recommendation_json_adapter",
    "version": "1.0.0",
    "source_command": "scripts/recommend.py --json"
  },
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
    "valid_after_at": "2026-08-06T09:10:11+09:00",
    "expires_at": "2026-08-06T09:40:11+09:00"
  },
  "freshness": {
    "status": "fresh",
    "age_seconds": 311,
    "max_age_seconds": 1800,
    "stale_after_seconds": 1800,
    "source_lag_seconds": 300
  },
  "quality": {
    "status": "ok",
    "score": 0.98,
    "checks": [
      {"name": "schema", "status": "pass"},
      {"name": "required_fields", "status": "pass"},
      {"name": "source_freshness", "status": "pass"}
    ]
  },
  "risk_state": {
    "level": "watch",
    "reasons": ["sector_concentration_near_limit"],
    "blocking": false,
    "risk_version": "risk-input-v1"
  },
  "payload_type": "recommendation.summary.v1",
  "payload": {},
  "links": [],
  "meta": {
    "redaction": "none_required",
    "raw_hash": "sha256:8a4c0e2d0b2df4b6f5a15c4f7b3a9f1d3b2c1a0e9f8d7c6b5a4e3d2c1b0a9988"
  }
}
```

### Required envelope rules

| Rule | Required behavior |
| --- | --- |
| Identity is stable | `event_id` changes for each emitted event. `subject_id` stays stable for the same logical recommendation, report, or risk record. |
| Timestamp separation | `produced_at`, `observed_at`, `data_cutoff_at`, `valid_after_at`, and `expires_at` must not be collapsed into one field. |
| Freshness is explicit | Stale or expired data must use `freshness.status`, not a hidden null or success-like number. |
| Quality is explicit | Partial adapter success must use `quality.status="degraded"` with failed checks. |
| Risk is explicit | `risk_state.level="blocked"` means the payload can be shown as blocked input but cannot be treated as actionable fresh data. |
| Payload is typed | `payload_type` selects one schema. Mixed payloads in one envelope are invalid. |
| Secrets are excluded | API keys, OAuth tokens, broker credentials, raw config, and account identifiers must not appear. |

## Query result 계약

List and search reads return typed query results. A query result never returns bare payload arrays.

```json
{
  "schema_name": "dashboard.query_result",
  "schema_version": "1.0.0",
  "query_id": "qry_20260806_recommendations_page_1",
  "requested_payload_type": "recommendation.summary.v1",
  "accepted_versions": ["1.0.0"],
  "returned_version": "1.0.0",
  "generated_at": "2026-08-06T09:10:12+09:00",
  "pagination": {
    "cursor": null,
    "next_cursor": "cur_eyJzb3J0IjoiZGF0YV9jdXRvZmZfYXQiLCJrZXkiOiIwMDU5MzAifQ",
    "limit": 2,
    "has_more": true,
    "sort": [
      {"field": "timestamps.data_cutoff_at", "direction": "desc"},
      {"field": "identity.subject_id", "direction": "asc"}
    ]
  },
  "items": [],
  "summary": {
    "returned_count": 0,
    "fresh_count": 0,
    "degraded_count": 0,
    "blocked_count": 0
  },
  "warnings": []
}
```

Pagination rules:

1. Cursor is opaque to consumers.
2. Cursor must encode sort position and schema version, not raw credentials or config.
3. `limit` must be a positive integer from 1 to 100.
4. `next_cursor=null` and `has_more=false` end pagination.
5. Changing `sort` while reusing a cursor is a malformed query.
6. Page boundaries must not duplicate or skip items when new envelopes are produced during a read. The adapter uses `generated_at` as the read watermark.

## Version negotiation

Consumers send a list of accepted envelope versions and payload versions. The producer returns the highest mutually supported version.

Request shape:

```json
{
  "accept": {
    "envelope_versions": ["1.0.0"],
    "payload_versions": {
      "recommendation.summary": ["1.0.0"],
      "performance.report": ["1.0.0"]
    }
  },
  "query": {
    "payload_type": "recommendation.summary.v1",
    "limit": 2
  }
}
```

Negotiation rules:

| Scenario | Result |
| --- | --- |
| Exact match exists | Return that version. |
| Multiple matches exist | Return the highest supported compatible version and record it in `returned_version`. |
| No envelope match | Return `dashboard.error` with `code="unsupported_envelope_version"`. |
| No payload match | Return `dashboard.error` with `code="unsupported_payload_version"`. |
| Consumer omits accepted versions | Return `dashboard.error` with `code="missing_version_accept"`. |
| Producer can only return older incompatible payload | Do not silently downgrade. Return unsupported payload error. |

## Adapter boundary

Adapters are the only path from current command output or future artifacts into this contract.

| Adapter | Reads | Emits | Boundary rule |
| --- | --- | --- | --- |
| `recommendation_json_adapter` | `scripts/recommend.py --json` result | `recommendation.summary.v1` envelopes | Keep `market`, `universe_size`, `portfolio_sizing`, `selection_constraints`, `recommendations`, and `no_recommendation_reason` as typed fields. |
| `performance_report_adapter` | `scripts/performance.py report --json` result | `performance.report.v1` envelopes | Preserve `snapshots_count`, `period`, `consensus`, perspective stats, confidence stats, and current weights. |
| `performance_detail_adapter` | `scripts/performance.py detail <date> --json` result | `performance.detail.v1` envelopes | Preserve per-ticker evaluation windows and perspective hits. |
| `terminal_formatter_adapter` | structured records before `src/output/formatter.py` renders Rich output | `display.card_input.v1` envelopes | Terminal markup is not parsed as data. Structured records are adapted before rendering. |
| `measurement_result_adapter` | future measurement artifact example | `measurement.result.v1` envelopes | Example only. This PRD does not wait for that artifact. |
| `paper_order_adapter` | future dry-run order artifact example | `paper.order.v1` envelopes | Example only. It cannot mutate portfolio or broker data from this contract. |

Adapter requirements:

1. Convert source-specific names to payload schema names at the boundary.
2. Preserve unknown, stale, degraded, and blocked meanings as first-class values.
3. Add `raw_hash` and source command metadata without storing raw secret-bearing content.
4. Reject malformed source JSON with an error envelope.
5. Never parse Rich markup, emoji, or localized prose to recover business data.

## Typed payload examples

### Recommendation summary happy payload

This is a valid page containing one recommendation summary envelope.

```json
{
  "schema_name": "dashboard.query_result",
  "schema_version": "1.0.0",
  "query_id": "qry_recommendation_happy_001",
  "requested_payload_type": "recommendation.summary.v1",
  "accepted_versions": ["1.0.0"],
  "returned_version": "1.0.0",
  "generated_at": "2026-08-06T09:10:12+09:00",
  "pagination": {
    "cursor": null,
    "next_cursor": null,
    "limit": 10,
    "has_more": false,
    "sort": [
      {"field": "timestamps.data_cutoff_at", "direction": "desc"},
      {"field": "identity.subject_id", "direction": "asc"}
    ]
  },
  "items": [
    {
      "schema_name": "dashboard.event_envelope",
      "schema_version": "1.0.0",
      "min_reader_version": "1.0.0",
      "event_id": "evt_recommend_20260806_005930_001",
      "correlation_id": "corr_operator_dashboard_20260806_001",
      "request_id": "req_recommend_kr_20260806_001",
      "producer": {
        "name": "recommendation_json_adapter",
        "version": "1.0.0",
        "source_command": "scripts/recommend.py --json"
      },
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
        "valid_after_at": "2026-08-06T09:10:11+09:00",
        "expires_at": "2026-08-06T09:40:11+09:00"
      },
      "freshness": {
        "status": "fresh",
        "age_seconds": 311,
        "max_age_seconds": 1800,
        "stale_after_seconds": 1800,
        "source_lag_seconds": 300
      },
      "quality": {
        "status": "ok",
        "score": 0.98,
        "checks": [
          {"name": "schema", "status": "pass"},
          {"name": "required_fields", "status": "pass"},
          {"name": "source_freshness", "status": "pass"}
        ]
      },
      "risk_state": {
        "level": "watch",
        "reasons": ["sector_concentration_near_limit"],
        "blocking": false,
        "risk_version": "risk-input-v1"
      },
      "payload_type": "recommendation.summary.v1",
      "payload": {
        "date": "2026-08-06",
        "market": "KR",
        "regime": {"regime": "sideways", "label": "횡보"},
        "universe_size": 2741,
        "universe_breakdown": {"KOSPI": 943, "KOSDAQ": 1798},
        "screened": 40,
        "signal_filtered": 6,
        "analyzed": 6,
        "portfolio_sizing": {
          "cash": 5000000,
          "cash_ratio": 20.0,
          "cash_floor": 10,
          "available_cash": 2500000,
          "can_buy": true
        },
        "selection_constraints": {
          "sector_cap": 2,
          "prefer_market_balance": true,
          "relaxed": false
        },
        "recommendations": [
          {
            "ticker": "005930",
            "name": "삼성전자",
            "market": "KR",
            "sector": "반도체",
            "price": 79000,
            "price_display": "79,000원",
            "selected_by": ["score", "diversification"],
            "signals": {
              "verdict": "BULLISH",
              "bull_votes": 5,
              "bear_votes": 1
            },
            "consensus": {
              "consensus_verdict": "BUY",
              "consensus_label": "강한 합의",
              "confidence": "high"
            },
            "action_plan": {
              "type": "buy",
              "target_shares": 20,
              "first_tranche_shares": 10,
              "first_tranche_pct": 50,
              "stop_loss": 71100,
              "binding_constraints": []
            }
          }
        ],
        "no_recommendation_reason": null
      },
      "links": [],
      "meta": {
        "redaction": "none_required",
        "raw_hash": "sha256:8a4c0e2d0b2df4b6f5a15c4f7b3a9f1d3b2c1a0e9f8d7c6b5a4e3d2c1b0a9988"
      }
    }
  ],
  "summary": {
    "returned_count": 1,
    "fresh_count": 1,
    "degraded_count": 0,
    "blocked_count": 0
  },
  "warnings": []
}
```

### Performance report payload example

This example shows how `scripts/performance.py report --json` is adapted. It is not a prerequisite for the recommendation payload.

```json
{
  "payload_type": "performance.report.v1",
  "payload": {
    "period": "30d",
    "snapshots_count": 12,
    "consensus": {
      "5": {"hits": 7, "total": 10, "rate": 70.0},
      "20": {"hits": 4, "total": 8, "rate": 50.0}
    },
    "by_perspective": {
      "5": {
        "kwangsoo": {"hits": 6, "total": 10, "rate": 60.0}
      }
    },
    "by_confidence": {
      "5": {
        "high": {"hits": 4, "total": 5, "rate": 80.0}
      }
    },
    "current_weights": {
      "kwangsoo": 0.52,
      "ouroboros": 0.48,
      "quant": 0.61,
      "macro": 0.47,
      "value": 0.50
    }
  }
}
```

### Future artifact payload examples only

The following payload type names are reserved as examples for adapters. They do not make this PRD wait for those artifacts.

| Payload type | Example source | Required here |
| --- | --- | --- |
| `measurement.result.v1` | future measurement artifact | no |
| `replay.trace.v1` | future replay artifact | no |
| `risk.health.v1` | future risk artifact | no |
| `paper.order.v1` | future dry-run order artifact | no |

## Error envelope

Errors use a typed envelope and never return a plain string.

```json
{
  "schema_name": "dashboard.error",
  "schema_version": "1.0.0",
  "error_id": "err_unsupported_version_001",
  "request_id": "req_recommend_kr_20260806_unsupported",
  "correlation_id": "corr_operator_dashboard_20260806_unsupported",
  "occurred_at": "2026-08-06T09:10:12+09:00",
  "code": "unsupported_payload_version",
  "message": "Requested payload version is not supported.",
  "retryable": false,
  "supported": {
    "envelope_versions": ["1.0.0"],
    "payload_versions": {
      "recommendation.summary": ["1.0.0"],
      "performance.report": ["1.0.0"]
    }
  },
  "requested": {
    "payload_type": "recommendation.summary.v2",
    "payload_version": "2.0.0"
  },
  "quality": {
    "status": "blocked",
    "checks": [
      {"name": "version_negotiation", "status": "fail", "reason": "unsupported_payload_version"}
    ]
  }
}
```

Error codes:

| Code | Retryable | Meaning |
| --- | --- | --- |
| `missing_version_accept` | false | Request omitted accepted versions. |
| `unsupported_envelope_version` | false | No mutually supported envelope version exists. |
| `unsupported_payload_version` | false | Payload version is not supported. |
| `malformed_query` | false | Cursor, limit, sort, or payload type is invalid. |
| `malformed_source_payload` | false | Adapter could not parse source JSON into the typed payload. |
| `source_unavailable` | true | Source command or artifact could not be read. |
| `source_stale` | true | Source exists but freshness policy blocks fresh use. |
| `risk_blocked` | false | Payload is valid but risk state blocks actionable use. |

## Stale and degraded behavior

| Condition | Envelope output | Consumer rule |
| --- | --- | --- |
| Source age is within max age | `freshness.status="fresh"`, `quality.status="ok"` | May be treated as current input. |
| Source age exceeds max age but is still useful for audit | `freshness.status="stale"`, `quality.status="degraded"` | May be shown as stale input. Must not be counted as fresh. |
| Source expired | `freshness.status="expired"`, `quality.status="blocked"` | Must not be used for current decision context. |
| Adapter recovered partial fields | `quality.status="degraded"` with failed checks | Must expose missing fields as degraded, not as zero or empty success. |
| Risk rule blocks actionability | `risk_state.level="blocked"`, `risk_state.blocking=true` | Payload can explain the block. It must not be treated as actionable fresh data. |
| Source JSON has wrong shape | `dashboard.error`, `code="malformed_source_payload"` | Do not create a partial success envelope. |

Misleading output is forbidden. A payload with `freshness.status="stale"` must not have `summary.fresh_count` include it. A payload with `quality.status="blocked"` must not be counted as ok. A payload with `risk_state.blocking=true` must not be summarized as actionable.

## Validation and failing-first evidence

Task 31 evidence must prove failure before creation, then prove the written contract through Read and deterministic JSON checks.

Required checks:

1. Read this PRD from line 1 and confirm the title and one draft status line.
2. Parse every JSON block in this PRD that is intended as JSON.
3. Validate the happy recommendation query result: one item, valid envelope fields, fresh status, ok quality, watch risk state, typed payload, no next cursor when `has_more=false`.
4. Validate unsupported version error: `schema_name="dashboard.error"`, `code="unsupported_payload_version"`, `retryable=false`, supported versions present.
5. Run JSON/schema mutations: remove `event_id`, remove `timestamps.data_cutoff_at`, change `payload_type` without changing payload shape, set `quality.status="ok"` while a check has `status="fail"`.
6. Run pagination mutations: `limit=0`, `has_more=true` with `next_cursor=null`, sort changed while cursor remains present.
7. Run version mutations: omit accepted versions, request unsupported envelope version, request unsupported payload version.
8. Probe stale, dirty, misleading, and malformed cases.

Probe expectations:

| Probe | Mutation | Expected result |
| --- | --- | --- |
| `stale` | Set `age_seconds` greater than `max_age_seconds` while keeping `freshness.status="fresh"`. | fail with `stale_mislabeled_fresh`. |
| `dirty` | Add a payload field derived from terminal Rich markup instead of structured source data. | fail with `adapter_boundary_violation`. |
| `misleading` | Count a blocked or stale item in `summary.fresh_count`. | fail with `misleading_summary`. |
| `malformed` | Remove `payload_type` or make `payload` a string. | fail with `malformed_envelope`. |

## Acceptance criteria

1. The document has the exact draft metadata directly under the title and no done marker.
2. It defines event envelope, query result, identity, timestamps, freshness, quality, risk state, pagination, and version negotiation.
3. It defines adapter boundary and says current script output is adapted before dashboard consumption.
4. It includes typed payload examples for recommendation and performance report.
5. It includes an error envelope and unsupported version error.
6. It defines stale and degraded behavior without letting stale or blocked data look successful.
7. It treats other SPEC payloads as examples only.
8. It includes failing-first, Read, JSON/schema, pagination, version, stale, dirty, misleading, and malformed evidence requirements.
