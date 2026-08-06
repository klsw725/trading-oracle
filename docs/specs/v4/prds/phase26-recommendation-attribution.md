# PRD: Phase 26 recommendation attribution
> **상태**: ✅ 완료
> **SPEC 참조**: [../SPEC.md](../SPEC.md)

## 문제

현재 추천 흐름은 넓은 후보군을 고른 뒤 시그널 필터, 다관점 분석, BUY 합의 필터를 지나 사용자에게 BUY 목록만 반환한다. `compute_action_plan()`도 BUY와 SELL에만 계획을 만들고, HOLD, 차단된 BUY, 후보 탈락, 사용자의 미실행 결정은 같은 귀속 단위로 남지 않는다. 이 상태에서 체결된 BUY만 성과 평가에 넣으면 선택 편향이 생긴다.

Phase 26은 Phase 22의 측정 계약, Phase 23의 snapshot 재현성, Phase 25의 시장 컨텍스트를 이어받아 후보부터 추천, 운영자 결정, 부분 체결, 청산, 보정까지 같은 identity로 추적한다.

## 목표

1. `snapshot_id`, `recommendation_id`, `candidate_id`, `attribution_event_id`, `portfolio_trade_id`, `order_id`를 결정적으로 만든다.
2. action taxonomy를 `BUY`, `SELL`, `HOLD`, `BLOCKED`, `CANDIDATE_REJECTED`로 고정한다.
3. confidence를 보정 가능한 확률로 저장하고, horizon은 Phase 22의 양의 정수 session 목록을 따른다.
4. 후보 선택과 탈락, 차단된 BUY, HOLD, SELL, 실제 운영자 결정을 모두 append-only ledger에 남긴다.
5. evaluation denominator가 체결된 BUY만 보지 않도록 rejected candidate와 blocked recommendation을 보존한다.

## 선행 계약

| 계약 | Phase 26에서 소비하는 부분 |
| --- | --- |
| [Phase 22 측정 계약](phase22-measurement-contract.md) | entry는 추천 이후 다음 동일 시장 정규 session 종가, exit는 entry 이후 N번째 session 종가, HOLD와 BLOCKED는 trading PnL을 만들지 않음 |
| [Phase 23 snapshot 재현성](phase23-snapshot-reproducibility.md) | snapshot envelope, candidate audit, deterministic hash, redaction, source freshness, portfolio state |
| [Phase 25 시장 컨텍스트 분리](phase25-market-context-separation.md) | market, exchange, calendar, timezone, benchmark, currency, FX degradation, blocked fields |
| [Recommendation Pipeline SPEC](../../recommend/SPEC.md) | 넓은 universe, diversified selection, Bull 4 of 6 시그널 필터, BUY 합의, action plan |

## Identity 계약

모든 ID는 Phase 23 canonical JSON 규칙을 따른다. Hash input은 redaction 이후 값만 쓴다. ID 생성을 위해 `sha256:` 접두사가 붙은 전체 hash를 저장하고, 표시용 ID는 앞 20 hex를 쓴다.

| ID | 형식 | seed |
| --- | --- | --- |
| `candidate_id` | `cand_v4_` + first 20 hex | `schema_version`, `snapshot_identity_hash`, `universe_id`, `market`, `exchange`, `ticker`, `selection_stage`, `rank_seed_hash` |
| `recommendation_id` | `rec_v4_` + first 20 hex | Phase 23의 `recommendation_identity_seed`, action 포함 |
| `attribution_event_id` | `att_v4_` + first 20 hex | `ledger_id`, `event_type`, `event_version`, `occurred_at`, `entity_ref`, `prev_event_hash` |
| `portfolio_trade_id` | `ptrade_v4_` + first 20 hex | `recommendation_id`, `operator_decision_id`, `ticker`, `side`, `first_fill_at` |
| `order_id` | `order_v4_` + first 20 hex | `portfolio_trade_id`, `order_intent`, `idempotency_key`, `submitted_at` |
| `correction_id` | `corr_v4_` + first 20 hex | `target_event_id`, `correction_reason`, `correction_event_hash` |

`snapshot_id`는 Phase 23의 decision run 단위다. `recommendation_id`는 snapshot 안의 ticker action 단위다. `candidate_id`는 추천으로 승격되지 않은 후보도 추적하기 위한 단위다.

## Action taxonomy

| action | 의미 | action plan | 새 거래 | Phase 22 측정 | denominator 포함 |
| --- | --- | --- | --- | --- | --- |
| `BUY` | 신규 또는 추가 매수 의사결정 | 필요 | 가능 | directional return과 benchmark excess 가능 | 예 |
| `SELL` | 보유 포지션 축소 또는 청산 의사결정 | 필요 | 기존 포지션 변경 | 방향은 SELL, 실제 체결은 execution metric으로 분리 | 예 |
| `HOLD` | 새 거래 없음 | 없음 | 없음 | price path와 opportunity cost만 저장 | 예 |
| `BLOCKED` | 의사결정은 있었지만 risk, context, freshness, portfolio 제약으로 실행 금지 | 차단 이유 필요 | 없음 | blocked opportunity와 avoided loss 평가 | 예 |
| `CANDIDATE_REJECTED` | universe에는 있었지만 selection, signal, diversification, 보유 종목 제외 등에서 추천 전 탈락 | 없음 | 없음 | 선택 편향 분석용 outcome만 저장 | 예 |

HOLD는 신규 거래가 아니다. HOLD의 `execution_intent`는 항상 `none`이고, portfolio trade나 order가 생기면 schema 오류다.

## Confidence, horizon, rationale, risk, source component

| component | 필드 | 규칙 |
| --- | --- | --- |
| confidence | `confidence_probability` | 0.0 이상 1.0 이하 숫자. Phase 28에서 보정 가능한 확률이다. `high`, `moderate` 같은 label만 저장하면 불충분하다. |
| confidence | `confidence_label` | 표시용 label. 측정과 calibration의 기준값이 아니다. |
| horizon | `horizons` | Phase 22와 같은 양의 정수 session 목록. 기본은 `[5, 20]`이다. |
| rationale | `rationale.summary` | 사람이 읽는 요약. redaction 뒤 저장한다. |
| rationale | `rationale.component_refs[]` | 관점, 시그널, 후보 선택, 시장 context, portfolio risk 중 어떤 근거가 action에 기여했는지 참조한다. |
| risk | `risk_component` | cash floor, concentration, correlation, stale quote, FX degradation, blocked field를 구조화한다. |
| source | `source_component` | source id, adapter version, as-of, freshness, provenance hash를 Phase 23 source와 연결한다. |

외부 웹 또는 provider 원문이 rationale에 들어올 수 있으면 Phase 23 redaction과 source freshness를 먼저 통과해야 한다. 이 문서 자체의 fixture는 외부 원문을 실행하지 않으므로 prompt injection 평가는 해당 없음이다.

## Candidate selection and exclusion

후보 audit은 추천된 ticker만 담으면 안 된다. 각 후보는 가장 마지막으로 도달한 stage와 탈락 이유를 가진다.

| stage | 보존 필드 | rejection reason 예 |
| --- | --- | --- |
| `universe_seen` | market scope, source, rank seed, raw member hash | 없음 |
| `portfolio_exclusion` | held position ref, quantity state | `already_held` |
| `diversified_selection` | rank before filter, selected_by, relaxed constraints | `sector_cap`, `market_balance` |
| `signal_filter` | bull votes, bear votes, threshold | `insufficient_bull_votes` |
| `perspective_analysis` | raw and parsed perspective refs | `provider_unavailable`, `parser_failed` |
| `consensus` | vote summary, consensus confidence | `non_buy_consensus`, `weak_consensus` |
| `risk_gate` | portfolio and context refs | `cash_floor`, `concentration`, `stale_quote`, `blocked_market_context` |

`CANDIDATE_REJECTED` event는 후보가 마지막 stage에서 사라지는 순간에 생성한다. 추천 목록이 비어도 rejected event는 남아야 한다.

## Action plan and operator decision

| field | BUY | SELL | HOLD | BLOCKED | CANDIDATE_REJECTED |
| --- | --- | --- | --- | --- | --- |
| `action_plan.intent` | `open_or_add` | `reduce_or_close` | `none` | `blocked` | `none` |
| `action_plan.quantity_basis` | cash, risk, stop price | shares held, confidence, cash ratio | `not_applicable` | blocked reason | rejection reason |
| `operator_decision.state` | `accepted`, `rejected`, `ignored`, `partial_execution` | same | `ignored` or `not_applicable` | `not_applicable` | `not_applicable` |
| `portfolio_trade_id` | nullable until first fill | nullable until first fill | null | null | null |
| `order_ids[]` | zero or more | zero or more | empty | empty | empty |

Operator states are:

| state | meaning |
| --- | --- |
| `accepted` | 운영자가 제안을 승인했고 주문 또는 수동 거래를 전량 실행했다. |
| `rejected` | 운영자가 명시적으로 거절했다. 이유를 남긴다. |
| `ignored` | 노출 뒤 만료 시점까지 아무 행동도 하지 않았다. |
| `partial_execution` | 일부 수량만 체결됐다. 남은 수량의 만료나 취소 상태를 함께 저장한다. |
| `not_applicable` | HOLD, BLOCKED, CANDIDATE_REJECTED처럼 운영자 실행 선택이 없는 경우다. |

운영자 결정은 추천 action을 바꾸지 않는다. 예를 들어 BUY 추천을 거절해도 recommendation action은 BUY이고, operator decision만 `rejected`다.

## Portfolio trade and order linkage

`portfolio_trade_id`는 추천에서 실제 portfolio 변화까지 잇는 audit key다. 기존 portfolio 파일의 `positions[]`, `history[]`, `cash_krw`, `cash_usd` 구조를 참조할 수 있지만, Phase 26 ledger는 별도 append-only event로 남는다.

| link | required fields | rule |
| --- | --- | --- |
| recommendation to trade | `recommendation_id`, `operator_decision_id`, `portfolio_trade_id` | 첫 fill 전에는 trade id가 null일 수 있다. |
| trade to order | `portfolio_trade_id`, `order_id`, `idempotency_key` | 한 trade가 여러 partial order를 가질 수 있다. |
| order to portfolio mutation | `order_id`, `fill_id`, `portfolio_state_before_hash`, `portfolio_state_after_hash` | state hash만 저장하고 account secret은 저장하지 않는다. |
| close to recommendation | `portfolio_trade_id`, `close_event_id`, `exit_reason`, `realized_pnl` | Phase 22 outcome과 실제 execution metric을 분리한다. |

Phase 26은 broker 주문 구현을 요구하지 않는다. 수동 거래라도 같은 link 필드를 채운다.

## Lifecycle timestamps

| timestamp | owner | required for |
| --- | --- | --- |
| `universe_built_at` | screener | 후보 denominator |
| `candidate_selected_at` | selection stage | candidate lifecycle |
| `candidate_rejected_at` | rejecting stage | rejected outcome |
| `decision_at` | recommendation pipeline | snapshot identity |
| `emitted_at` | user-visible output | Phase 22 entry |
| `operator_decided_at` | operator surface | accept, reject, ignore, partial execution |
| `order_submitted_at` | execution adapter | order lifecycle |
| `fill_recorded_at` | portfolio adapter | trade linkage |
| `position_closed_at` | portfolio adapter | close event |
| `outcome_matured_at` | measurement adapter | Phase 22 horizon outcome |
| `correction_recorded_at` | ledger writer | correction event |

Timestamps are ISO 8601 with timezone. Date-only values are `session_date`, not midnight timestamps.

## Append-only attribution ledger

Ledger events are immutable. No event is overwritten or deleted. Corrections append a new event that references the bad event and states the corrected field path.

| event_type | entity | purpose |
| --- | --- | --- |
| `CANDIDATE_SEEN` | candidate | universe denominator 생성 |
| `CANDIDATE_SELECTED` | candidate | final analysis 대상 선정 |
| `CANDIDATE_REJECTED` | candidate | 탈락 후보 보존 |
| `RECOMMENDATION_EMITTED` | recommendation | BUY, SELL, HOLD, BLOCKED 추천 기록 |
| `OPERATOR_DECISION_RECORDED` | recommendation | accept, reject, ignore, partial execution 기록 |
| `ORDER_LINKED` | order | 주문 또는 수동 거래 의도 연결 |
| `FILL_RECORDED` | fill | 실제 부분 또는 전량 체결 연결 |
| `POSITION_CLOSED` | trade | 청산 기록 |
| `OUTCOME_MATURED` | recommendation | Phase 22 horizon 결과 연결 |
| `CORRECTION_RECORDED` | prior event | append-only 보정 |

### Ledger event schema

| field | required | rule |
| --- | --- | --- |
| `ledger_id` | yes | snapshot 또는 portfolio ledger stream id |
| `event_id` | yes | deterministic `att_v4_` id |
| `event_type` | yes | 위 event type 중 하나 |
| `event_version` | yes | schema version |
| `occurred_at` | yes | domain event time |
| `recorded_at` | yes | writer time |
| `entity_ref` | yes | candidate, recommendation, order, fill, trade 중 하나 |
| `prev_event_hash` | yes | stream 첫 event면 `sha256:genesis` |
| `event_hash` | yes | hash fields를 뺀 canonical event hash |
| `payload` | yes | event type별 typed payload |
| `quality_state` | yes | `available`, `degraded`, `blocked`, `unknown`, `not_applicable` |

### Correction semantics

| correction case | required behavior |
| --- | --- |
| 잘못된 field value | `CORRECTION_RECORDED`가 `target_event_id`, `field_path`, `old_value_hash`, `new_value`, `reason`, `corrected_by`, `correction_recorded_at`을 가진다. |
| 누락된 event | 누락됐던 event를 현재 시점에 append하고 `payload.original_occurred_at`을 남긴다. |
| 잘못된 event type | 원 event는 그대로 두고 `supersedes_event_id`가 있는 새 event를 append한다. |
| downstream outcome 변경 | 기존 outcome을 지우지 않고 새 `OUTCOME_MATURED` 또는 correction event가 이전 outcome을 참조한다. |

## Evaluation denominator

평가 cohort는 다음을 모두 포함한다.

| cohort member | denominator role | primary question |
| --- | --- | --- |
| emitted BUY | decision quality와 execution linkage | 살 만한 종목을 골랐는가 |
| emitted SELL | decision quality와 realized exit linkage | 줄이거나 닫을 타이밍이 맞았는가 |
| emitted HOLD | opportunity cost와 avoided loss | 새 거래를 피한 판단이 맞았는가 |
| emitted BLOCKED | risk gate quality | 실행 차단이 손실 회피 또는 과잉 차단이었는가 |
| CANDIDATE_REJECTED | selection quality | 탈락시킨 후보가 더 나은 성과를 냈는가 |

Denominator에는 `candidate_id`, `recommendation_id` 또는 둘 다 있어야 한다. BUY만 체결됐다는 이유로 denominator를 `portfolio_trade_id is not null`로 제한하면 실패다.

## Schema tables

### Recommendation attribution record

| field | type | required | notes |
| --- | --- | --- | --- |
| `schema_version` | string | yes | `v4.recommendation_attribution.phase26.1` |
| `snapshot_id` | string | yes | Phase 23 snapshot |
| `recommendation_id` | string | yes for emitted recommendation | rejected-only candidate는 null 가능 |
| `candidate_id` | string | yes | 모든 action에 필요 |
| `ticker` | string | yes | normalized ticker |
| `market` | string | yes | Phase 25 market |
| `exchange` | string | yes | Phase 25 exchange |
| `action` | enum | yes | five action taxonomy |
| `confidence_probability` | number | yes except rejected when unavailable | calibration input |
| `confidence_label` | string | nullable | display only |
| `horizons` | array number | yes | positive sessions |
| `rationale` | object | yes | redacted summary and component refs |
| `risk_component` | object | yes | gate status and reasons |
| `source_component` | object | yes | source refs and freshness |
| `candidate_audit` | object | yes | selection and exclusion trace |
| `action_plan` | object | yes | `intent` decides execution path |
| `operator_decision` | object | yes | state and timestamp |
| `portfolio_linkage` | object | yes | trade, order, fill refs |
| `lifecycle_timestamps` | object | yes | all known lifecycle times |
| `denominator_eligibility` | object | yes | cohort membership and exclusions |

### Denominator eligibility

| field | type | rule |
| --- | --- | --- |
| `decision_quality_denominator` | boolean | true for all five actions unless schema is malformed |
| `execution_quality_denominator` | boolean | true only when an execution intent exists |
| `selection_quality_denominator` | boolean | true for selected and rejected candidates |
| `excluded_from_primary_reason` | string or null | only structural invalidity, duplicate correction superseded, or insufficient measurement context |
| `blocked_or_rejected_preserved` | boolean | must be true for `BLOCKED` and `CANDIDATE_REJECTED` |

## Concrete JSON fixture

This fixture covers all five actions and one happy chain from candidate to recommendation, partial execution, and close.

Fixture deterministic algorithm:

1. `canonical_json(value)` is `json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))` after redaction.
2. `full_hash(value)` is `"sha256:" + sha256(canonical_json(value).encode()).hexdigest()` and always stores all 64 lowercase hex characters.
3. `short_id(prefix, seed)` is `prefix + sha256(canonical_json(seed).encode()).hexdigest()[:20]`.
4. `snapshot_identity_hash` is `full_hash(snapshot_seed)` where `snapshot_seed` is `schema_version`, `ledger_id`, `decision_at`, `emitted_at`, and `universe_id`.
5. Candidate IDs use `candidate_audit.selection_stage` and `candidate_audit.rank_seed_hash`; recommendation IDs use the Phase 23 visible seed fields `schema_version`, `snapshot_id`, `market`, `exchange`, `ticker`, `action`, `emitted_at`, `data_cutoff_at`, `candidate_universe_hash`, and `parsed_result_hash`.
6. Portfolio trade, order, fill, and attribution event IDs use the seed fields from the Identity table above; `order_id` specifically uses the visible structured `order_intent` object in `ORDER_LINKED.payload`.
7. For every ledger event, compute `event_id` first, set `prev_event_hash` to `sha256:genesis` or the previous event's `event_hash`, then compute `event_hash = full_hash(event_without_event_hash)`.
8. The JSON below is the actual output of that algorithm; a validator must be able to recompute every `prev_event_hash`, `event_hash`, and prefix ID from the documented visible seeds.

```json
{
  "schema_version": "v4.recommendation_attribution.phase26.1",
  "ledger_id": "ledger_v4_phase26_fixture",
  "snapshot_id": "snap_v4_feb6cd6e1745f7ef8b77",
  "snapshot_identity_hash": "sha256:feb6cd6e1745f7ef8b778600f98193b885c26adb33f3843a94207d58089bdf29",
  "default_horizons": [
    5,
    20
  ],
  "events": [
    {
      "event_id": "att_v4_65dbb3c6877bc9833c1b",
      "event_type": "CANDIDATE_SEEN",
      "event_version": "v4.phase26.event.1",
      "occurred_at": "2026-06-02T10:00:00+09:00",
      "recorded_at": "2026-06-02T10:00:01+09:00",
      "entity_ref": {
        "entity_type": "candidate",
        "candidate_id": "cand_v4_241d2519920a4d36d3da"
      },
      "prev_event_hash": "sha256:genesis",
      "event_hash": "sha256:fbf6e87bd6c687b07d8c8bc9b9f329a419192838e36d5f580a5c2d1f544a753b",
      "quality_state": "available",
      "payload": {
        "ticker": "005930",
        "market": "KR",
        "exchange": "KOSPI",
        "universe_id": "universe_v4_kr_us_20260602",
        "selection_stage": "signal_filter",
        "rank_seed_hash": "sha256:8173669cfe49b2652cfebad8e5ac1a5da779ee41c875f71571c8bc8ef173965c",
        "rank_before_filter": 3
      }
    },
    {
      "event_id": "att_v4_d342e897064ed2fdd69f",
      "event_type": "CANDIDATE_SELECTED",
      "event_version": "v4.phase26.event.1",
      "occurred_at": "2026-06-02T10:02:00+09:00",
      "recorded_at": "2026-06-02T10:02:01+09:00",
      "entity_ref": {
        "entity_type": "candidate",
        "candidate_id": "cand_v4_241d2519920a4d36d3da"
      },
      "prev_event_hash": "sha256:fbf6e87bd6c687b07d8c8bc9b9f329a419192838e36d5f580a5c2d1f544a753b",
      "event_hash": "sha256:9b9036d0025728e4bfc5a986d9c6e5dd5abe3b69942da31c04170a49075afa1b",
      "quality_state": "available",
      "payload": {
        "selected_by": [
          "rank",
          "signal_filter",
          "diversification"
        ],
        "bull_votes": 5,
        "selection_stage": "signal_filter",
        "rank_seed_hash": "sha256:8173669cfe49b2652cfebad8e5ac1a5da779ee41c875f71571c8bc8ef173965c"
      }
    },
    {
      "event_id": "att_v4_3a1e69b594123ae0b6be",
      "event_type": "RECOMMENDATION_EMITTED",
      "event_version": "v4.phase26.event.1",
      "occurred_at": "2026-06-02T10:32:10+09:00",
      "recorded_at": "2026-06-02T10:32:11+09:00",
      "entity_ref": {
        "entity_type": "recommendation",
        "recommendation_id": "rec_v4_62ec99717d763a8550d0"
      },
      "prev_event_hash": "sha256:9b9036d0025728e4bfc5a986d9c6e5dd5abe3b69942da31c04170a49075afa1b",
      "event_hash": "sha256:a57dab2dd2536ccb82ae086912de597dba564865b5271193adf457070c7865b8",
      "quality_state": "available",
      "payload": {
        "candidate_id": "cand_v4_241d2519920a4d36d3da",
        "recommendation_id": "rec_v4_62ec99717d763a8550d0",
        "candidate_universe_hash": "sha256:3b1104c7a0760c0fab2c775a97e9495fb489d164766b428bd9f07b0cd48cb521",
        "parsed_result_hash": "sha256:fd7e6ee80c40353cc73d1046c8ebea4b89ede8c80db46ba86ff1ac023a5a8b30",
        "ticker": "005930",
        "market": "KR",
        "exchange": "KOSPI",
        "action": "BUY",
        "intended_action": null,
        "confidence_probability": 0.79,
        "confidence_label": "high",
        "horizons": [
          5,
          20
        ],
        "rationale": {
          "summary": "trend, valuation, and market context support a staged entry",
          "component_refs": [
            "signals",
            "consensus",
            "market_context",
            "portfolio_risk"
          ]
        },
        "risk_component": {
          "state": "available",
          "blocked_fields": [],
          "degraded_fields": [],
          "cash_floor": 2000000,
          "risk_reasons": []
        },
        "source_component": {
          "source_id": "toss.market.ohlcv",
          "adapter_version": "market-adapter-v2026.08",
          "as_of": "2026-06-02T10:00:00+09:00",
          "decision_data_cutoff_at": "2026-06-02T10:00:00+09:00",
          "freshness_state": "fresh",
          "provenance_hash": "sha256:8d0d311318315cdc98650cbc2518b71a17048210ebf83eea9a0796821cae6216"
        },
        "candidate_audit": {
          "universe_id": "universe_v4_kr_us_20260602",
          "selection_stage": "signal_filter",
          "rank_seed_hash": "sha256:8173669cfe49b2652cfebad8e5ac1a5da779ee41c875f71571c8bc8ef173965c",
          "last_stage": "consensus",
          "rank_before_filter": 3,
          "selected_by": [
            "rank",
            "signal_filter",
            "diversification"
          ],
          "rejection_reason": null
        },
        "action_plan": {
          "intent": "open_or_add",
          "quantity_basis": "cash_risk_stop_price",
          "target_shares": 10,
          "max_notional": 1000000,
          "stop_price": 90000.0
        },
        "operator_decision": {
          "operator_decision_id": "opdec_v4_phase26_buy",
          "state": "partial_execution",
          "decided_at": "2026-06-02T10:35:00+09:00",
          "accepted_shares": 4,
          "rejected_shares": 6,
          "reason": "cash reserved for other positions"
        },
        "portfolio_linkage": {
          "portfolio_trade_id": "ptrade_v4_8c178900d7ed58ec979c",
          "order_ids": [
            "order_v4_68c1191d4ef619982bf4"
          ],
          "fill_ids": [
            "fill_v4_edff9d1a856bbbda185f"
          ]
        },
        "lifecycle_timestamps": {
          "universe_built_at": "2026-06-02T10:00:00+09:00",
          "candidate_selected_at": "2026-06-02T10:02:00+09:00",
          "candidate_rejected_at": null,
          "decision_at": "2026-06-02T10:31:54+09:00",
          "emitted_at": "2026-06-02T10:32:10+09:00",
          "operator_decided_at": "2026-06-02T10:35:00+09:00",
          "order_submitted_at": "2026-06-03T09:05:00+09:00",
          "fill_recorded_at": "2026-06-03T15:31:00+09:00",
          "position_closed_at": "2026-06-10T15:30:00+09:00",
          "outcome_matured_at": "2026-06-10T16:00:00+09:00",
          "correction_recorded_at": null
        },
        "denominator_eligibility": {
          "decision_quality_denominator": true,
          "execution_quality_denominator": true,
          "selection_quality_denominator": true,
          "excluded_from_primary_reason": null,
          "blocked_or_rejected_preserved": false
        }
      }
    },
    {
      "event_id": "att_v4_6b43196136038cbbc029",
      "event_type": "OPERATOR_DECISION_RECORDED",
      "event_version": "v4.phase26.event.1",
      "occurred_at": "2026-06-02T10:35:00+09:00",
      "recorded_at": "2026-06-02T10:35:01+09:00",
      "entity_ref": {
        "entity_type": "recommendation",
        "recommendation_id": "rec_v4_62ec99717d763a8550d0"
      },
      "prev_event_hash": "sha256:a57dab2dd2536ccb82ae086912de597dba564865b5271193adf457070c7865b8",
      "event_hash": "sha256:1a18ee0f873cfa7c922ce4670900c722ac0181ec598cb4dbcd13d91fd5fd95ff",
      "quality_state": "available",
      "payload": {
        "operator_decision_id": "opdec_v4_phase26_buy",
        "state": "partial_execution",
        "accepted_shares": 4,
        "rejected_shares": 6,
        "reason": "cash reserved for other positions"
      }
    },
    {
      "event_id": "att_v4_253c2b7b024bf545e9d7",
      "event_type": "ORDER_LINKED",
      "event_version": "v4.phase26.event.1",
      "occurred_at": "2026-06-03T09:05:00+09:00",
      "recorded_at": "2026-06-03T09:05:01+09:00",
      "entity_ref": {
        "entity_type": "order",
        "order_id": "order_v4_68c1191d4ef619982bf4"
      },
      "prev_event_hash": "sha256:1a18ee0f873cfa7c922ce4670900c722ac0181ec598cb4dbcd13d91fd5fd95ff",
      "event_hash": "sha256:7af490db737cced799d97e61204905c1348784f056ccfc8a451d5d7a9cc03cac",
      "quality_state": "available",
      "payload": {
        "portfolio_trade_id": "ptrade_v4_8c178900d7ed58ec979c",
        "recommendation_id": "rec_v4_62ec99717d763a8550d0",
        "side": "BUY",
        "quantity": 4,
        "order_intent": {
          "type": "manual_partial_buy",
          "side": "BUY",
          "quantity": 4
        },
        "idempotency_key": "idem_phase26_fixture_005930_1"
      }
    },
    {
      "event_id": "att_v4_3fce5e1076ecee7e5283",
      "event_type": "FILL_RECORDED",
      "event_version": "v4.phase26.event.1",
      "occurred_at": "2026-06-03T15:30:00+09:00",
      "recorded_at": "2026-06-03T15:31:00+09:00",
      "entity_ref": {
        "entity_type": "fill",
        "fill_id": "fill_v4_edff9d1a856bbbda185f"
      },
      "prev_event_hash": "sha256:7af490db737cced799d97e61204905c1348784f056ccfc8a451d5d7a9cc03cac",
      "event_hash": "sha256:86dba08399841772a89ac74b0dd6349f72d9c2c320014edd9741c90f90bfb1da",
      "quality_state": "available",
      "payload": {
        "portfolio_trade_id": "ptrade_v4_8c178900d7ed58ec979c",
        "order_id": "order_v4_68c1191d4ef619982bf4",
        "filled_shares": 4,
        "fill_price": 100000.0,
        "portfolio_state_before_hash": "sha256:4796def596cd2ee116b10342e1f0983d9327f746ed9735b491d5d104d754a118",
        "portfolio_state_after_hash": "sha256:452f51bf7901134c926e65240a280930c2e25976b88b2db3d0d5f940bafd3940"
      }
    },
    {
      "event_id": "att_v4_faf9ec19c5cd6eb9a84a",
      "event_type": "POSITION_CLOSED",
      "event_version": "v4.phase26.event.1",
      "occurred_at": "2026-06-10T15:30:00+09:00",
      "recorded_at": "2026-06-10T15:35:00+09:00",
      "entity_ref": {
        "entity_type": "trade",
        "portfolio_trade_id": "ptrade_v4_8c178900d7ed58ec979c"
      },
      "prev_event_hash": "sha256:86dba08399841772a89ac74b0dd6349f72d9c2c320014edd9741c90f90bfb1da",
      "event_hash": "sha256:1f3e4bd5582d470c36a4a2591b18dfaa1944c50dcb0e46d6bdc07a6c9d2a270d",
      "quality_state": "available",
      "payload": {
        "recommendation_id": "rec_v4_62ec99717d763a8550d0",
        "close_reason": "operator_close",
        "closed_shares": 4,
        "close_price": 106000.0,
        "realized_pnl": 24000.0,
        "position_closed_at": "2026-06-10T15:30:00+09:00"
      }
    },
    {
      "event_id": "att_v4_7f9756389d6bf63298fb",
      "event_type": "OUTCOME_MATURED",
      "event_version": "v4.phase26.event.1",
      "occurred_at": "2026-06-10T15:30:00+09:00",
      "recorded_at": "2026-06-10T16:00:00+09:00",
      "entity_ref": {
        "entity_type": "recommendation",
        "recommendation_id": "rec_v4_62ec99717d763a8550d0"
      },
      "prev_event_hash": "sha256:1f3e4bd5582d470c36a4a2591b18dfaa1944c50dcb0e46d6bdc07a6c9d2a270d",
      "event_hash": "sha256:ccecc21bf94db7d2093f3ec2bd5069498628e1da6ae6b72be2e452bffdc4c58a",
      "quality_state": "available",
      "payload": {
        "horizon": 5,
        "entry_session": "2026-06-03",
        "target_exit_session": "2026-06-10",
        "gross_absolute_return": 0.06,
        "gross_benchmark_excess_return": 0.03,
        "execution_fill_ratio": 0.4
      }
    },
    {
      "event_id": "att_v4_ea7cb8ae3c3632979ffd",
      "event_type": "RECOMMENDATION_EMITTED",
      "event_version": "v4.phase26.event.1",
      "occurred_at": "2026-06-02T10:32:12+09:00",
      "recorded_at": "2026-06-02T10:32:13+09:00",
      "entity_ref": {
        "entity_type": "recommendation",
        "recommendation_id": "rec_v4_0aa8d4fafe00d5c1b85f"
      },
      "prev_event_hash": "sha256:ccecc21bf94db7d2093f3ec2bd5069498628e1da6ae6b72be2e452bffdc4c58a",
      "event_hash": "sha256:61fbf9ba457cb57a43f55557d20228dc06a80412e1d4c0797b787f6b65eb296f",
      "quality_state": "available",
      "payload": {
        "candidate_id": "cand_v4_2e372eaf5a1641300074",
        "recommendation_id": "rec_v4_0aa8d4fafe00d5c1b85f",
        "candidate_universe_hash": "sha256:3b1104c7a0760c0fab2c775a97e9495fb489d164766b428bd9f07b0cd48cb521",
        "parsed_result_hash": "sha256:fce1a3db905a62cb980222d57b6a021de19977001e308b8946e628ea999a9eca",
        "ticker": "055550",
        "market": "KR",
        "exchange": "KOSPI",
        "action": "SELL",
        "intended_action": null,
        "confidence_probability": 0.68,
        "confidence_label": "moderate",
        "horizons": [
          5,
          20
        ],
        "rationale": {
          "summary": "position risk suggests reducing exposure but operator declined",
          "component_refs": [
            "consensus",
            "portfolio_risk"
          ]
        },
        "risk_component": {
          "state": "available",
          "blocked_fields": [],
          "degraded_fields": [],
          "cash_floor": 2000000,
          "risk_reasons": [
            "cash_ratio_rebalance"
          ]
        },
        "source_component": {
          "source_id": "portfolio.tracker",
          "adapter_version": "portfolio-tracker-v2026.08",
          "as_of": "2026-06-02T10:00:00+09:00",
          "decision_data_cutoff_at": "2026-06-02T10:00:00+09:00",
          "freshness_state": "fresh",
          "provenance_hash": "sha256:4e8d396a52784878ed6f5944c9d761ac55014539fd061e583dea760e7e9fe926"
        },
        "candidate_audit": {
          "universe_id": "universe_v4_kr_us_20260602",
          "selection_stage": "consensus",
          "rank_seed_hash": "sha256:8bfff9ce70c85b7bf661860229c16c77c2f7ee951ffd83c344e2eb036ac370d2",
          "last_stage": "consensus",
          "rank_before_filter": 8,
          "selected_by": [
            "held_position_review"
          ],
          "rejection_reason": null
        },
        "action_plan": {
          "intent": "reduce_or_close",
          "quantity_basis": "shares_held_confidence_cash_ratio",
          "sell_shares": 2
        },
        "operator_decision": {
          "operator_decision_id": "opdec_v4_phase26_sell",
          "state": "rejected",
          "decided_at": "2026-06-02T10:36:00+09:00",
          "reason": "operator keeps position"
        },
        "portfolio_linkage": {
          "portfolio_trade_id": null,
          "order_ids": [],
          "fill_ids": []
        },
        "lifecycle_timestamps": {
          "universe_built_at": "2026-06-02T10:00:00+09:00",
          "candidate_selected_at": "2026-06-02T10:03:00+09:00",
          "candidate_rejected_at": null,
          "decision_at": "2026-06-02T10:31:54+09:00",
          "emitted_at": "2026-06-02T10:32:12+09:00",
          "operator_decided_at": "2026-06-02T10:36:00+09:00",
          "order_submitted_at": null,
          "fill_recorded_at": null,
          "position_closed_at": null,
          "outcome_matured_at": null,
          "correction_recorded_at": null
        },
        "denominator_eligibility": {
          "decision_quality_denominator": true,
          "execution_quality_denominator": true,
          "selection_quality_denominator": true,
          "excluded_from_primary_reason": null,
          "blocked_or_rejected_preserved": false
        }
      }
    },
    {
      "event_id": "att_v4_ba9171bc71e833c6d5dc",
      "event_type": "RECOMMENDATION_EMITTED",
      "event_version": "v4.phase26.event.1",
      "occurred_at": "2026-06-02T10:32:14+09:00",
      "recorded_at": "2026-06-02T10:32:15+09:00",
      "entity_ref": {
        "entity_type": "recommendation",
        "recommendation_id": "rec_v4_c923bbcc202b6f68eb98"
      },
      "prev_event_hash": "sha256:61fbf9ba457cb57a43f55557d20228dc06a80412e1d4c0797b787f6b65eb296f",
      "event_hash": "sha256:ebac10cbe47013852bb5291519b8da4ee3efa111cd90f2b2389b4b24548559fa",
      "quality_state": "available",
      "payload": {
        "candidate_id": "cand_v4_ea4ea2f3ed8d0522a187",
        "recommendation_id": "rec_v4_c923bbcc202b6f68eb98",
        "candidate_universe_hash": "sha256:3b1104c7a0760c0fab2c775a97e9495fb489d164766b428bd9f07b0cd48cb521",
        "parsed_result_hash": "sha256:a42729ab29139680e5d8c34f4bcd8ea279b5937c751f464541a370de17c47c8f",
        "ticker": "MSFT",
        "market": "US",
        "exchange": "NASDAQ",
        "action": "HOLD",
        "intended_action": null,
        "confidence_probability": 0.61,
        "confidence_label": "moderate",
        "horizons": [
          5,
          20
        ],
        "rationale": {
          "summary": "evidence is mixed, so no new trade is proposed",
          "component_refs": [
            "consensus",
            "market_context"
          ]
        },
        "risk_component": {
          "state": "available",
          "blocked_fields": [],
          "degraded_fields": [],
          "cash_floor": null,
          "risk_reasons": []
        },
        "source_component": {
          "source_id": "fdr.market.ohlcv",
          "adapter_version": "market-adapter-v2026.08",
          "as_of": "2026-06-01T16:00:00-04:00",
          "decision_data_cutoff_at": "2026-06-02T10:00:00+09:00",
          "freshness_state": "fresh",
          "provenance_hash": "sha256:7a67ccb298300959f30f6dff8ff7ab3d87d1862b9734456d4aa475a303e358ac"
        },
        "candidate_audit": {
          "universe_id": "universe_v4_kr_us_20260602",
          "selection_stage": "consensus",
          "rank_seed_hash": "sha256:692c37d355482c011ad23343027a0d4b788edcdf3b0a27ea560c3b6dffefc25d",
          "last_stage": "consensus",
          "rank_before_filter": 2,
          "selected_by": [
            "operator_pin",
            "analysis"
          ],
          "rejection_reason": null
        },
        "action_plan": {
          "intent": "none",
          "quantity_basis": "not_applicable"
        },
        "operator_decision": {
          "operator_decision_id": null,
          "state": "ignored",
          "decided_at": null,
          "reason": "no trade proposed"
        },
        "portfolio_linkage": {
          "portfolio_trade_id": null,
          "order_ids": [],
          "fill_ids": []
        },
        "lifecycle_timestamps": {
          "universe_built_at": "2026-06-02T10:00:00+09:00",
          "candidate_selected_at": "2026-06-02T10:03:30+09:00",
          "candidate_rejected_at": null,
          "decision_at": "2026-06-02T10:31:54+09:00",
          "emitted_at": "2026-06-02T10:32:14+09:00",
          "operator_decided_at": null,
          "order_submitted_at": null,
          "fill_recorded_at": null,
          "position_closed_at": null,
          "outcome_matured_at": null,
          "correction_recorded_at": null
        },
        "denominator_eligibility": {
          "decision_quality_denominator": true,
          "execution_quality_denominator": false,
          "selection_quality_denominator": true,
          "excluded_from_primary_reason": null,
          "blocked_or_rejected_preserved": false
        }
      }
    },
    {
      "event_id": "att_v4_54b6944dbb6e2ade602b",
      "event_type": "RECOMMENDATION_EMITTED",
      "event_version": "v4.phase26.event.1",
      "occurred_at": "2026-06-02T10:32:16+09:00",
      "recorded_at": "2026-06-02T10:32:17+09:00",
      "entity_ref": {
        "entity_type": "recommendation",
        "recommendation_id": "rec_v4_642669f93e6944165ac0"
      },
      "prev_event_hash": "sha256:ebac10cbe47013852bb5291519b8da4ee3efa111cd90f2b2389b4b24548559fa",
      "event_hash": "sha256:49250a541d099baa0a21ec8528ac842962653933ad69bee998db83509fd6d38f",
      "quality_state": "blocked",
      "payload": {
        "candidate_id": "cand_v4_979f331ae2614df5a371",
        "recommendation_id": "rec_v4_642669f93e6944165ac0",
        "candidate_universe_hash": "sha256:3b1104c7a0760c0fab2c775a97e9495fb489d164766b428bd9f07b0cd48cb521",
        "parsed_result_hash": "sha256:b4a27a1e7221fb53517f9ae94040f5ed88f1c75576c61b3ea6ed721f22ba365f",
        "ticker": "AMGN",
        "market": "US",
        "exchange": "NASDAQ",
        "action": "BLOCKED",
        "intended_action": "BUY",
        "confidence_probability": 0.72,
        "confidence_label": "high",
        "horizons": [
          5,
          20
        ],
        "rationale": {
          "summary": "BUY setup exists but execution is blocked by portfolio context freshness",
          "component_refs": [
            "signals",
            "risk_gate",
            "market_context"
          ]
        },
        "risk_component": {
          "state": "blocked",
          "blocked_fields": [
            "portfolio_market_value_krw",
            "concentration_check"
          ],
          "degraded_fields": [
            "fx"
          ],
          "cash_floor": null,
          "risk_reasons": [
            "fx_missing_for_base_reporting",
            "concentration_unknown"
          ]
        },
        "source_component": {
          "source_id": "risk.gate",
          "adapter_version": "risk-gate-v2026.08",
          "as_of": "2026-06-02T10:00:00+09:00",
          "decision_data_cutoff_at": "2026-06-02T10:00:00+09:00",
          "freshness_state": "fresh",
          "provenance_hash": "sha256:0e4f702c5c335fe23cb0854de973f28384ae774985cfe69c8663b9ed435acda9"
        },
        "candidate_audit": {
          "universe_id": "universe_v4_kr_us_20260602",
          "selection_stage": "risk_gate",
          "rank_seed_hash": "sha256:04d349f4580d94d56e1d85d2f45cfb953f96e03f9d204e122fdf3d986258a360",
          "last_stage": "risk_gate",
          "rank_before_filter": 5,
          "selected_by": [
            "rank",
            "signal_filter"
          ],
          "rejection_reason": "blocked_market_context"
        },
        "action_plan": {
          "intent": "blocked",
          "quantity_basis": "blocked_reason",
          "blocked_reasons": [
            "fx_missing_for_base_reporting",
            "concentration_unknown"
          ]
        },
        "operator_decision": {
          "operator_decision_id": null,
          "state": "not_applicable",
          "decided_at": null,
          "reason": "blocked before operator action"
        },
        "portfolio_linkage": {
          "portfolio_trade_id": null,
          "order_ids": [],
          "fill_ids": []
        },
        "lifecycle_timestamps": {
          "universe_built_at": "2026-06-02T10:00:00+09:00",
          "candidate_selected_at": "2026-06-02T10:03:45+09:00",
          "candidate_rejected_at": null,
          "decision_at": "2026-06-02T10:31:54+09:00",
          "emitted_at": "2026-06-02T10:32:16+09:00",
          "operator_decided_at": null,
          "order_submitted_at": null,
          "fill_recorded_at": null,
          "position_closed_at": null,
          "outcome_matured_at": null,
          "correction_recorded_at": null
        },
        "denominator_eligibility": {
          "decision_quality_denominator": true,
          "execution_quality_denominator": false,
          "selection_quality_denominator": true,
          "excluded_from_primary_reason": null,
          "blocked_or_rejected_preserved": true
        }
      }
    },
    {
      "event_id": "att_v4_4449224e1154ce8f0235",
      "event_type": "CANDIDATE_REJECTED",
      "event_version": "v4.phase26.event.1",
      "occurred_at": "2026-06-02T10:04:00+09:00",
      "recorded_at": "2026-06-02T10:04:01+09:00",
      "entity_ref": {
        "entity_type": "candidate",
        "candidate_id": "cand_v4_afa914c9b9a7c3f28fe9"
      },
      "prev_event_hash": "sha256:49250a541d099baa0a21ec8528ac842962653933ad69bee998db83509fd6d38f",
      "event_hash": "sha256:3ab84309450676813bc97aeccce3b7ed8f952c0241c65e856f31494464039af1",
      "quality_state": "available",
      "payload": {
        "candidate_id": "cand_v4_afa914c9b9a7c3f28fe9",
        "recommendation_id": null,
        "candidate_universe_hash": "sha256:3b1104c7a0760c0fab2c775a97e9495fb489d164766b428bd9f07b0cd48cb521",
        "parsed_result_hash": "sha256:ebfcc7460bcd5469d5c172c7ba35d320894bda5da8a18ecdcb3a098d1f51e822",
        "ticker": "000660",
        "market": "KR",
        "exchange": "KOSPI",
        "action": "CANDIDATE_REJECTED",
        "intended_action": null,
        "confidence_probability": 0.0,
        "confidence_label": "not_applicable",
        "horizons": [
          5,
          20
        ],
        "rationale": {
          "summary": "candidate failed the Bull signal threshold and was preserved for selection analysis",
          "component_refs": [
            "candidate_audit",
            "signals"
          ]
        },
        "risk_component": {
          "state": "not_applicable",
          "blocked_fields": [],
          "degraded_fields": [],
          "cash_floor": null,
          "risk_reasons": []
        },
        "source_component": {
          "source_id": "screener.leading",
          "adapter_version": "screener-v2026.08",
          "as_of": "2026-06-02T10:00:00+09:00",
          "decision_data_cutoff_at": "2026-06-02T10:00:00+09:00",
          "freshness_state": "fresh",
          "provenance_hash": "sha256:b4708305f6390788af956f35bdc041a7295e1e6ee9babe47db7a882023a1b1d7"
        },
        "candidate_audit": {
          "universe_id": "universe_v4_kr_us_20260602",
          "selection_stage": "signal_filter",
          "rank_seed_hash": "sha256:7290538fdc8fe60d7fffaba1dad3444954acbfd12961a0a2bd1caa2b887fcd03",
          "last_stage": "signal_filter",
          "rank_before_filter": 4,
          "selected_by": [],
          "rejection_reason": "insufficient_bull_votes"
        },
        "action_plan": {
          "intent": "none",
          "quantity_basis": "rejection_reason"
        },
        "operator_decision": {
          "operator_decision_id": null,
          "state": "not_applicable",
          "decided_at": null,
          "reason": "not emitted as trade recommendation"
        },
        "portfolio_linkage": {
          "portfolio_trade_id": null,
          "order_ids": [],
          "fill_ids": []
        },
        "lifecycle_timestamps": {
          "universe_built_at": "2026-06-02T10:00:00+09:00",
          "candidate_selected_at": null,
          "candidate_rejected_at": "2026-06-02T10:04:00+09:00",
          "decision_at": "2026-06-02T10:31:54+09:00",
          "emitted_at": null,
          "operator_decided_at": null,
          "order_submitted_at": null,
          "fill_recorded_at": null,
          "position_closed_at": null,
          "outcome_matured_at": null,
          "correction_recorded_at": null
        },
        "denominator_eligibility": {
          "decision_quality_denominator": true,
          "execution_quality_denominator": false,
          "selection_quality_denominator": true,
          "excluded_from_primary_reason": null,
          "blocked_or_rejected_preserved": true
        }
      }
    }
  ],
  "denominator_summary": {
    "BUY": 1,
    "SELL": 1,
    "HOLD": 1,
    "BLOCKED": 1,
    "CANDIDATE_REJECTED": 1,
    "decision_quality_total": 5,
    "execution_quality_total": 2,
    "selection_quality_total": 5
  }
}
```

## Required failure detection

| failure | detection rule | expected result |
| --- | --- | --- |
| rejected candidate disappears | any candidate in `candidate_universe.members_hash` has no selected, rejected, or emitted event | fail attribution QA |
| blocked BUY disappears | `intended_action="BUY"` with risk gate blocked but no `BLOCKED` recommendation event | fail attribution QA |
| HOLD creates order | `action="HOLD"` and non-empty `order_ids` or non-null `portfolio_trade_id` | malformed ledger input |
| confidence is label-only | recommendation has `confidence_label` but no numeric `confidence_probability` | fail calibration readiness |
| horizon invalid | horizon contains 0, negative, non-integer, or empty list | fail Phase 22 linkage |
| mutable correction | event content changes without a later `CORRECTION_RECORDED` | fail ledger immutability |
| stale source looks fresh | `as_of` later than `emitted_at` or stale source lacks affected fields | fail stale_state probe |

## Acceptance criteria

1. The PRD defines deterministic recommendation and snapshot linkage identity without changing Phase 23 `snapshot_id` rules.
2. The five action taxonomy appears in schema, fixture, and denominator rules.
3. Confidence is a numeric probability suitable for Phase 28 calibration. Labels are display-only.
4. HOLD means no new trade and cannot create portfolio trade, order, or fill linkage.
5. Candidate selection and exclusion preserve full denominator evidence, including rejected and blocked candidates.
6. The append-only ledger has immutable event hashes and correction semantics.
7. The JSON fixture parses and covers candidate to recommendation to partial execution to close.
8. QA detects a rejected candidate or blocked BUY disappearing from the ledger.
