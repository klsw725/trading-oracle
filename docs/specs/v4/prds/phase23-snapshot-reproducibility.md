# PRD: Phase 23 snapshot 재현성
> **상태**: 📝 초안
> **SPEC 참조**: [../SPEC.md](../SPEC.md)

## 문제

기존 snapshot은 날짜, KOSPI와 KOSDAQ 요약, 추천 결과, 관점별 판단을 저장한다. 그러나 추천 당시 어떤 후보가 탈락했는지, 어떤 market context와 data cutoff가 쓰였는지, 어떤 provider와 prompt, parser, config가 raw LLM 결과를 parsed recommendation으로 바꿨는지 재현할 수 없다.

Phase 23은 v4 native snapshot의 저장 계약을 정의한다. 목표는 과거 의사결정을 그대로 감사하고, Phase 22의 N-session 측정과 Phase 25의 시장 context를 같은 입력으로 다시 추적하게 만드는 것이다. 모든 필드를 무조건 필수로 두지 않는다. 결측은 숫자나 성공 상태로 위장하지 않고 `unknown`, `degraded`, `not_applicable`로 남긴다.

## 목표

1. snapshot identity, schema version, recommendation timestamp, created timestamp, decision timestamp, data cutoff timestamp를 분리한다.
2. Phase 25 market context를 recommendation마다 포함해 KR과 US의 calendar, timezone, benchmark, currency, FX 경계를 보존한다.
3. source freshness, provenance, candidate universe, selection, rejection, features, signals, LLM raw 결과, parsed 결과, consensus, deliberation, portfolio, risk state를 추적한다.
4. provider, model, prompt bundle, config, parser version을 저장해 replay와 attribution이 같은 입력 계약을 읽게 한다.
5. content hash와 deterministic ID 알고리즘을 문서화해 같은 입력이 같은 ID와 hash를 만들게 한다.
6. raw payload 저장, secret redaction, retention 규칙을 정의한다.

## 상태 어휘

| 상태 | 의미 | 사용 예 |
| --- | --- | --- |
| `available` | 값과 provenance가 모두 있다. | fresh OHLCV, parsed LLM verdict |
| `unknown` | 값이 필요하지만 수집 또는 복원이 불가능하다. | legacy raw prompt, missing provider response |
| `degraded` | 핵심 판단은 가능하지만 일부 보조 값이 stale 또는 결측이다. | missing FX로 portfolio KRW 비중 차단 |
| `blocked` | 오염된 입력 때문에 해당 feature와 파생값을 쓰면 안 된다. | US market cap이 KRW_100M 단위로 들어온 경우 |
| `not_applicable` | action, market, provider 경로상 해당 필드가 의미 없다. | HOLD의 order fill, quant 관점의 LLM raw payload |

`unknown`과 `degraded`는 서로 다르다. `unknown`은 값을 모른다는 뜻이고, `degraded`는 무엇이 부족한지 알고 영향 범위를 닫았다는 뜻이다. `not_applicable`은 결측이 아니라 설계상 해당 없음이다.

## Snapshot v4 envelope

v4 snapshot은 하나의 decision run을 저장한다. 추천 요청 범위가 `ALL`이어도 각 recommendation은 독립적인 market context를 가진다.

```json
{
  "schema_version": "v4.snapshot.phase23.1",
  "snapshot_id": "snap_v4_0a2f8e16c90db7a3e2d1",
  "created_at": "2026-06-02T10:32:18+09:00",
  "decision_at": "2026-06-02T10:31:54+09:00",
  "recommendation_emitted_at": "2026-06-02T10:32:10+09:00",
  "decision_data_cutoff_at": "2026-06-02T10:00:00+09:00",
  "request_scope": {
    "market_scope": "KR",
    "tickers_requested": [],
    "top_n": 2,
    "operator_request_id": "req_v4_demo_kr_20260602"
  },
  "contract_refs": {
    "measurement_contract": "v4.phase22.1",
    "market_context_contract": "v4.market_context.phase25.1"
  },
  "retention_policy": {
    "policy_version": "v4.retention.phase23.1",
    "raw_llm_text_days": 180,
    "market_payload_retention": "hash_only"
  },
  "redaction": {
    "redaction_version": "v4.redaction.phase23.1",
    "redaction_events": []
  },
  "recommendations": [],
  "content_hashes": {
    "snapshot_identity_hash": "sha256:identity-fixture",
    "snapshot_content_hash": "sha256:content-fixture"
  }
}
```

## Field contract

| 필드 | 필수 | nullable | provenance | redaction |
| --- | --- | --- | --- | --- |
| `schema_version` | yes | no | Phase 23 contract version | none |
| `snapshot_id` | yes | no | deterministic identity algorithm | none |
| `created_at` | yes | no | snapshot writer clock, timezone 포함 | none |
| `decision_at` | yes | no | decision pipeline start or final consensus timestamp | none |
| `recommendation_emitted_at` | yes | no | user-visible output timestamp | none |
| `decision_data_cutoff_at` | yes | no | latest allowed source as-of, must be `<= recommendation_emitted_at` | none |
| `request_scope.market_scope` | yes | no | CLI or service request | none |
| `request_scope.tickers_requested` | yes | yes | user request, empty list means screener decides universe | redact secret-like free text before storage |
| `request_scope.top_n` | yes | yes | config and CLI args | none |
| `operator_request_id` | no | yes | caller generated ID | redact account or user secret fragments |
| `contract_refs.measurement_contract` | yes | no | Phase 22 version | none |
| `contract_refs.market_context_contract` | yes | no | Phase 25 version | none |
| `recommendations[]` | yes | no | parsed recommendation outputs | nested rules apply |
| `content_hashes.snapshot_identity_hash` | yes | no | canonical identity seed | none |
| `content_hashes.snapshot_content_hash` | yes | no | canonical redacted snapshot body | none |
| `retention_policy` | yes | no | storage policy version | none |

## Recommendation record

Each record ties a ticker-level decision to all replayable inputs and outputs.

| 영역 | 필드 | 필수 | nullable | provenance | redaction |
| --- | --- | --- | --- | --- | --- |
| identity | `recommendation_id` | yes | no | deterministic recommendation algorithm | none |
| identity | `ticker`, `name`, `market`, `exchange` | yes | no | ticker resolver and Phase 25 context | none |
| time | `decision_at`, `emitted_at`, `data_cutoff_at` | yes | no | pipeline clock and source cutoff | none |
| market context | `market_context` | yes | no | Phase 25 schema | nested rules apply |
| sources | `sources[]` | yes | no | adapter id, source id, as-of, freshness | raw credentials forbidden |
| candidate audit | `candidate_universe`, `selection`, `rejections[]` | yes | no | screener, ranking, filters | redact request free text |
| features | `features` | yes | no | normalized market, fundamental, macro inputs | raw payload hash only if vendor terms allow |
| signals | `signals` | yes | yes | technical signal engine and version | none |
| provider | `llm.provider`, `llm.model`, `llm.provider_request_id` | yes | yes | provider adapter | provider request id redacted if it embeds account data |
| prompt | `llm.prompt_bundle_version`, `llm.prompt_hash`, `llm.prompt_messages_redacted` | yes | yes | prompt builder and hash | secret-like strings redacted |
| config | `config_version`, `config_hash`, `parser_version` | yes | no | runtime config and parser artifact | store hash, not local secrets |
| raw LLM | `llm.raw_results[]` | yes | yes | provider response, code-based N/A reason | redact before retention |
| parsed LLM | `llm.parsed_results[]` | yes | no | parser output per perspective | none except rationale text redaction |
| consensus | `consensus` | yes | no | scorer version, weights | none |
| deliberation | `deliberation` | yes | yes | deliberator version, rounds | none |
| portfolio | `portfolio_state` | yes | yes | portfolio snapshot hash and risk adapter | account ids and broker ids redacted |
| risk | `risk_state` | yes | yes | sizing, correlation, stale checks | account ids and secrets redacted |
| hashes | `content_hashes` | yes | no | canonical section hashes | none |
| degradation | `quality_states[]` | yes | no | classifier version | none |

`llm.raw_results[]` can contain `not_applicable` for code-based quant results. A provider timeout or parser failure does not delete the perspective. It becomes `verdict="N/A"` with `quality_state="degraded"` or `quality_state="unknown"`, depending on whether the failure cause is known.

## Market context from Phase 25

`market_context` must embed or reference the Phase 25 fields below.

| 필드 | required behavior |
| --- | --- |
| `schema_version` | Must equal the active Phase 25 market context contract. |
| `market`, `exchange`, `calendar_id`, `timezone` | Required for every recommendation. Unknown market means `context_state="insufficient_context"`. |
| `quote_currency`, `base_reporting_currency` | Required. Missing quote currency blocks price-derived features. |
| `benchmark_id`, `benchmark_source`, `benchmark_as_of` | Required when benchmark excess can be measured. Missing benchmark keeps absolute return separate. |
| `decision_data_cutoff_at`, `target_session_close_at` | Required for Phase 22 entry and exit tracing. |
| `decision_regime`, `decision_regime_source`, `analysis_regime` | Required when regime is consumed. US direct regime source must be `IXIC` or `US500`. |
| `fx_pair`, `fx_rate`, `fx_as_of`, `fx_freshness_state` | Required for mixed portfolio normalization. Missing FX degrades KRW portfolio fields, not quote return. |
| `blocked_fields`, `degraded_fields` | Required lists. Empty list means no blocked or degraded field. |

## Candidate universe and audit

Candidate audit prevents selection bias. A rejected ticker is still evidence.

| 필드 | 의미 | 상태 규칙 |
| --- | --- | --- |
| `candidate_universe.universe_id` | deterministic ID for the screened universe | required |
| `candidate_universe.market_scope` | `KR`, `US`, or `ALL` request scope | required |
| `candidate_universe.source` | ranking or listing source and adapter version | required |
| `candidate_universe.total_seen` | input universe count before filters | required if known, else `unknown` |
| `candidate_universe.members_hash` | canonical hash of normalized candidate IDs | required |
| `selection.selected_by` | rank, diversification, signal, operator pin | required |
| `selection.rank_before_filter` | numeric rank before final selection | nullable when not ranked |
| `rejections[]` | ticker, reason, stage, provenance | required list, can be empty |

Rejected candidates use `action="CANDIDATE_REJECTED"` in Phase 26 attribution, but in Phase 23 they live under `rejections[]` unless the pipeline emits a recommendation-level rejected record.

## Source, freshness, and provenance

Each source entry follows this shape.

```json
{
  "source_id": "toss.market.ohlcv",
  "adapter_version": "market-adapter-v2026.08",
  "record_type": "ohlcv",
  "as_of": "2026-06-02T10:00:00+09:00",
  "fetched_at": "2026-06-02T10:01:05+09:00",
  "freshness_state": "fresh",
  "provenance_hash": "sha256:ohlcv-redacted-payload",
  "raw_retention": "hash_only"
}
```

Freshness state is `fresh`, `stale`, `missing`, or `not_applicable`. A stale cache can be used only if the consuming field allows `degraded` and lists the affected fields. A missing primary source can fall back only when the fallback source has its own provenance and freshness.

## Provider, prompt, config, and parser versions

| 필드 | required behavior |
| --- | --- |
| `provider_adapter_version` | Version of Anthropic, Codex, or local code adapter wrapper. |
| `provider` | Provider name. Code-based quant uses `not_applicable`. |
| `model` | Model name for LLM perspectives. Code-based quant uses `not_applicable`. |
| `prompt_bundle_version` | Human-readable prompt bundle release. |
| `prompt_hash` | SHA-256 over canonical redacted prompt messages. |
| `config_version` | Runtime config schema version. |
| `config_hash` | SHA-256 over redacted config values that affect behavior. Secret values are replaced before hashing. |
| `parser_version` | Parser code or schema version that converts raw provider output to typed result. |
| `parser_input_hash` | SHA-256 over redacted provider output consumed by parser. |

Provider metadata must not copy API keys, OAuth tokens, broker credentials, local auth paths, or config secrets. If a prompt includes user text that looks like a token, that substring is replaced by a redaction token before retention.

## Raw and parsed LLM results

Raw result retention is controlled per perspective.

| raw field | rule |
| --- | --- |
| `raw_text_redacted` | Store only after redaction. Nullable when retention is `hash_only` or provider failed before text arrived. |
| `raw_payload_hash` | Hash over redacted raw payload. If raw contains secret-like input, hash the redacted payload, not the original secret. |
| `provider_latency_ms` | Nullable for code-based or unavailable paths. |
| `provider_error_type` | `not_applicable`, `timeout`, `rate_limited`, `auth_failed`, `parse_failed`, `empty_response`, `unknown`. |
| `quality_state` | `available`, `degraded`, `unknown`, or `not_applicable`. |

Parsed results use the current perspective output contract.

| parsed field | required behavior |
| --- | --- |
| `perspective` | fixed name such as `kwangsoo`, `ouroboros`, `quant`, `macro`, `value`. |
| `verdict` | `BUY`, `SELL`, `HOLD`, `N/A`, `DIVIDED`, or later Phase 26 action vocabulary where applicable. |
| `confidence` | nullable only when verdict is `N/A` or parser cannot recover it. |
| `reason` | redacted natural-language summary. |
| `reasoning` | nullable. Redacted before storage. |
| `action` | nullable typed action object. |
| `signals` | required for quant when available, `not_applicable` for non-quant unless emitted. |

## Consensus and deliberation

The consensus section preserves both before and after deliberation where applicable.

| 필드 | 필수 | nullable | 의미 |
| --- | --- | --- | --- |
| `consensus.scorer_version` | yes | no | scoring contract version |
| `consensus.weights_used` | yes | yes | perspective weights, `unknown` if not reconstructable |
| `consensus.vote_summary` | yes | no | final vote counts including `N/A` |
| `consensus.consensus_verdict` | yes | no | final parsed consensus |
| `consensus.consensus_confidence` | yes | no | label or calibrated probability per later phases |
| `consensus.consensus_label` | yes | no | display label |
| `initial_consensus` | yes | yes | required when deliberation ran, else `not_applicable` |
| `deliberation.triggered` | yes | no | boolean |
| `deliberation.rounds` | yes | yes | list when triggered, `not_applicable` when not triggered |
| `deliberation.errors` | yes | no | empty list allowed |

`src/consensus/voter.py` allows partial failure. The snapshot must retain N/A perspective results instead of dropping them, preserving the fixed order `kwangsoo`, `ouroboros`, `quant`, `macro`, `value`.

## Portfolio and risk state

Portfolio and risk state explain why an actionable recommendation may become blocked or resized.

| 필드 | required behavior |
| --- | --- |
| `portfolio_state.state_hash` | Hash of redacted holdings, cash, and valuation inputs used by sizing. |
| `portfolio_state.cash_available_base` | Nullable when portfolio is unavailable. Unknown cash blocks execution sizing but not decision recording. |
| `portfolio_state.positions[]` | Redacted positions with ticker, quantity, average price, market, and valuation state. |
| `risk_state.cash_floor` | Nullable if sizing not run. |
| `risk_state.concentration_state` | `available`, `degraded`, `blocked`, or `not_applicable`. |
| `risk_state.correlation_state` | `available`, `degraded`, `blocked`, or `not_applicable`. |
| `risk_state.blocked_fields` | Required list. Empty list allowed. |

Broker account IDs, OAuth tokens, client secrets, and local credential paths are never stored. Portfolio state can be `unknown` for legacy snapshots and `degraded` when missing FX prevents KRW exposure calculation.

## Deterministic ID and hash algorithms

All algorithms are implementable with standard JSON and SHA-256.

### Canonicalization

1. Build JSON objects using UTF-8 strings.
2. Sort object keys lexicographically by Unicode code point.
3. Preserve array order when the order is semantic. This includes perspective order and deliberation rounds.
4. Sort sets before serialization. Candidate members sort by `market`, `exchange`, `ticker`.
5. Serialize with no insignificant whitespace, equivalent to Python `json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))` after arrays have been explicitly ordered.
6. Timestamps must be ISO 8601 strings with timezone. Do not convert to local system timezone. If the source has timezone, preserve it. If the source is date-only, store the date-only value in a separate `session_date` field, not as midnight.
7. Numeric prices and returns are serialized as JSON numbers using the normalized decimal value produced by the writer. Do not add formatted percent strings to hashed fields.
8. Redaction happens before hashing for prompt, raw provider, config, portfolio, and request free-text fields.
9. Hash fields themselves are excluded from the hash section they describe.

### snapshot_id

`snapshot_id = "snap_v4_" + first_20_hex(sha256(canonical_json(identity_seed)))`

`identity_seed` contains:

```json
{
  "schema_version": "v4.snapshot.phase23.1",
  "market_scope": "KR",
  "decision_at": "2026-06-02T10:31:54+09:00",
  "recommendation_emitted_at": "2026-06-02T10:32:10+09:00",
  "decision_data_cutoff_at": "2026-06-02T10:00:00+09:00",
  "candidate_universe_hash": "sha256:universe-fixture",
  "prompt_bundle_hash": "sha256:prompt-fixture",
  "config_hash": "sha256:config-fixture",
  "recommendation_ids": [
    "rec_v4_7f3c2a99d1f04e18a43b",
    "rec_v4_b10b0fb069dd814c4b6d"
  ]
}
```

### recommendation_id

`recommendation_id = "rec_v4_" + first_20_hex(sha256(canonical_json(recommendation_identity_seed)))`

`recommendation_identity_seed` contains `schema_version`, `snapshot_id`, `market`, `exchange`, `ticker`, `action`, `emitted_at`, `data_cutoff_at`, `candidate_universe_hash`, and `parsed_result_hash`. If `snapshot_id` is being computed at the same time, use `snapshot_identity_hash` instead of `snapshot_id` to avoid a cycle.

### content hashes

| hash | input |
| --- | --- |
| `candidate_universe_hash` | normalized candidate members and rejection metadata |
| `source_hash` | source entries after redaction |
| `feature_hash` | normalized feature values consumed by perspectives |
| `prompt_hash` | redacted prompt messages and prompt bundle version |
| `raw_result_hash` | redacted raw provider output or `not_applicable` token |
| `parsed_result_hash` | parsed perspective result after redaction |
| `consensus_hash` | initial consensus, final consensus, weights, deliberation |
| `portfolio_state_hash` | redacted portfolio and risk inputs |
| `snapshot_content_hash` | whole snapshot with `content_hashes` values removed |

Hash strings use `sha256:<lowercase hex>`. Implementations may store full 64 hex characters for hashes and use the first 20 hex characters only for IDs.

## Redaction and retention

### Redaction classes

| class | examples | stored value |
| --- | --- | --- |
| `api_key` | provider key prefixes, bot token prefixes, or explicit API key labels | `REDACTED_SECRET(api_key)` |
| `oauth_token` | bearer tokens, refresh tokens, access tokens | `REDACTED_SECRET(oauth_token)` |
| `broker_secret` | client secret, account auth, cert password | `REDACTED_SECRET(broker_secret)` |
| `account_id` | broker account number or user account handle | `REDACTED_ACCOUNT_ID` |
| `local_secret_path` | paths under auth directories | `REDACTED_LOCAL_SECRET_PATH` |
| `secret_like_free_text` | prompt text that contains token-like material | `REDACTED_SECRET(free_text)` |

Redaction must run before prompt, raw payload, config, portfolio, and request text are written. The writer stores `redaction_version` and `redaction_events[]` with class, field path, and replacement token. It does not store original secret values.

### Retention policy

| payload | default retention | reason |
| --- | --- | --- |
| redacted snapshot body | keep | required for replay and audit |
| redacted prompt messages | keep | needed for verbatim replay eligibility |
| redacted raw LLM text | keep for 180 days, then hash-only is allowed | high audit value, moderate storage cost |
| vendor raw payload with headers | hash_only | headers can contain secrets and account metadata |
| raw market payload | hash_only unless license allows retention | vendor terms and storage cost |
| portfolio details | keep redacted values | replay needs position and cash context |
| secrets and credentials | never | security boundary |

If raw text is not retained, `raw_text_redacted` is null and `raw_retention="hash_only"`. The hash must still be over the redacted representation that the parser consumed.

## Native v4 happy fixture

This fixture traces input to parsed output for one KR recommendation. It uses Phase 22 entry and exit language and Phase 25 market context fields.

```json
{
  "schema_version": "v4.snapshot.phase23.1",
  "snapshot_id": "snap_v4_0a2f8e16c90db7a3e2d1",
  "created_at": "2026-06-02T10:32:18+09:00",
  "decision_at": "2026-06-02T10:31:54+09:00",
  "recommendation_emitted_at": "2026-06-02T10:32:10+09:00",
  "decision_data_cutoff_at": "2026-06-02T10:00:00+09:00",
  "request_scope": {
    "market_scope": "KR",
    "tickers_requested": [],
    "top_n": 1,
    "operator_request_id": "req_v4_demo_kr_20260602"
  },
  "contract_refs": {
    "measurement_contract": "v4.phase22.1",
    "market_context_contract": "v4.market_context.phase25.1"
  },
  "retention_policy": {
    "policy_version": "v4.retention.phase23.1",
    "raw_llm_text_days": 180,
    "market_payload_retention": "hash_only"
  },
  "redaction": {
    "redaction_version": "v4.redaction.phase23.1",
    "redaction_events": []
  },
  "recommendations": [
    {
      "recommendation_id": "rec_v4_7f3c2a99d1f04e18a43b",
      "ticker": "005930",
      "name": "삼성전자",
      "market": "KR",
      "exchange": "KOSPI",
      "action": "BUY",
      "decision_at": "2026-06-02T10:31:54+09:00",
      "emitted_at": "2026-06-02T10:32:10+09:00",
      "data_cutoff_at": "2026-06-02T10:00:00+09:00",
      "market_context": {
        "schema_version": "v4.market_context.phase25.1",
        "ticker": "005930",
        "market": "KR",
        "exchange": "KOSPI",
        "calendar_id": "KRX",
        "calendar_version": "krx-calendar-2026.08",
        "timezone": "Asia/Seoul",
        "quote_currency": "KRW",
        "base_reporting_currency": "KRW",
        "benchmark_id": "KS11",
        "benchmark_source": "FinanceDataReader",
        "benchmark_as_of": "2026-06-02T10:00:00+09:00",
        "decision_data_cutoff_at": "2026-06-02T10:00:00+09:00",
        "target_session_close_at": "2026-06-10T15:30:00+09:00",
        "decision_regime": "sideways",
        "decision_regime_source": "KS11",
        "decision_regime_as_of": "2026-06-01T15:30:00+09:00",
        "analysis_regime": "bull",
        "analysis_regime_source": "KS11",
        "fx_pair": "KRW_KRW",
        "fx_rate": 1.0,
        "fx_as_of": "2026-06-02T10:00:00+09:00",
        "fx_freshness_state": "fresh",
        "context_state": "matured",
        "blocked_fields": [],
        "degraded_fields": [],
        "provenance_hashes": {
          "benchmark": "sha256:benchmark-fixture",
          "calendar": "sha256:calendar-fixture",
          "fx": "sha256:fx-fixture"
        }
      },
      "sources": [
        {
          "source_id": "toss.market.ohlcv",
          "adapter_version": "market-adapter-v2026.08",
          "record_type": "ohlcv",
          "as_of": "2026-06-02T10:00:00+09:00",
          "fetched_at": "2026-06-02T10:01:05+09:00",
          "freshness_state": "fresh",
          "provenance_hash": "sha256:ohlcv-redacted-payload",
          "raw_retention": "hash_only"
        }
      ],
      "candidate_universe": {
        "universe_id": "universe_v4_kr_20260602",
        "market_scope": "KR",
        "source": "diversified_selection",
        "adapter_version": "screener-v2026.08",
        "total_seen": 2400,
        "members_hash": "sha256:universe-fixture"
      },
      "selection": {
        "selected_by": ["rank", "signal_filter", "diversification"],
        "rank_before_filter": 3,
        "rank_after_filter": 1,
        "selection_reason": "top ranked KOSPI candidate with Bull 5 of 6 signals"
      },
      "rejections": [
        {
          "ticker": "000660",
          "stage": "signal_filter",
          "reason": "insufficient_bull_votes",
          "provenance_hash": "sha256:rejection-fixture"
        }
      ],
      "features": {
        "current_price": 100000.0,
        "market_cap": {
          "value": 450000000000000,
          "currency": "KRW",
          "unit": "KRW",
          "state": "available"
        },
        "fundamentals": {
          "per": 14.2,
          "pbr": 1.4,
          "dividend_yield": 1.8,
          "state": "available"
        }
      },
      "signals": {
        "engine_version": "technical-v2.2026.08",
        "momentum": "bull",
        "short_momentum": "bull",
        "ema": "bull",
        "rsi": "bull",
        "macd": "bull",
        "bb": "expanded",
        "volume_ratio": 1.21,
        "state": "available"
      },
      "llm": {
        "provider_adapter_version": "anthropic-adapter-v2026.08",
        "provider": "anthropic",
        "model": "claude-fixture-model",
        "provider_request_id": "prov_req_redacted_fixture",
        "prompt_bundle_version": "perspectives-v4.2026.08",
        "prompt_hash": "sha256:prompt-fixture",
        "prompt_messages_redacted": [
          {"role": "system", "content": "redacted prompt fixture"},
          {"role": "user", "content": "Analyze 005930 with supplied market context"}
        ],
        "config_version": "config-schema-v2026.08",
        "config_hash": "sha256:redacted-config-fixture",
        "parser_version": "perspective-parser-v2026.08",
        "raw_results": [
          {
            "perspective": "kwangsoo",
            "raw_text_redacted": "{\"verdict\":\"BUY\",\"confidence\":0.82,\"reason\":\"trend and risk are aligned\"}",
            "raw_payload_hash": "sha256:kwangsoo-raw-fixture",
            "provider_latency_ms": 1200,
            "provider_error_type": "not_applicable",
            "quality_state": "available",
            "raw_retention": "keep_redacted"
          },
          {
            "perspective": "ouroboros",
            "raw_text_redacted": "{\"verdict\":\"HOLD\",\"confidence\":0.74,\"reason\":\"risk evidence is not decisive\"}",
            "raw_payload_hash": "sha256:ouroboros-raw-fixture",
            "provider_latency_ms": 1180,
            "provider_error_type": "not_applicable",
            "quality_state": "available",
            "raw_retention": "keep_redacted"
          },
          {
            "perspective": "quant",
            "raw_text_redacted": null,
            "raw_payload_hash": "sha256:quant-code-result-fixture",
            "provider_latency_ms": null,
            "provider_error_type": "not_applicable",
            "quality_state": "not_applicable",
            "raw_retention": "not_applicable"
          },
          {
            "perspective": "macro",
            "raw_text_redacted": "{\"verdict\":\"BUY\",\"confidence\":0.76,\"reason\":\"sector cycle supports the setup\"}",
            "raw_payload_hash": "sha256:macro-raw-fixture",
            "provider_latency_ms": 1250,
            "provider_error_type": "not_applicable",
            "quality_state": "available",
            "raw_retention": "keep_redacted"
          },
          {
            "perspective": "value",
            "raw_text_redacted": "{\"verdict\":\"BUY\",\"confidence\":0.79,\"reason\":\"valuation leaves enough margin\"}",
            "raw_payload_hash": "sha256:value-raw-fixture",
            "provider_latency_ms": 1195,
            "provider_error_type": "not_applicable",
            "quality_state": "available",
            "raw_retention": "keep_redacted"
          }
        ],
        "parsed_results": [
          {
            "perspective": "kwangsoo",
            "verdict": "BUY",
            "confidence": 0.82,
            "reason": "trend and risk are aligned",
            "reasoning": ["price stays above short and long moving averages"],
            "action": {"type": "buy"},
            "signals": "not_applicable",
            "quality_state": "available"
          },
          {
            "perspective": "ouroboros",
            "verdict": "HOLD",
            "confidence": 0.74,
            "reason": "risk evidence is not decisive",
            "reasoning": ["no confirmed dilution or insider selling evidence"],
            "action": {"type": "hold"},
            "signals": "not_applicable",
            "quality_state": "available"
          },
          {
            "perspective": "quant",
            "verdict": "BUY",
            "confidence": 0.83,
            "reason": "Bull 5/6 vs 0/6",
            "reasoning": ["technical engine emitted bullish signal set"],
            "action": {"type": "buy"},
            "signals": {"momentum": "bull", "ema": "bull", "rsi": "bull"},
            "quality_state": "available"
          },
          {
            "perspective": "macro",
            "verdict": "BUY",
            "confidence": 0.76,
            "reason": "sector cycle supports the setup",
            "reasoning": ["benchmark regime and sector context support a buy decision"],
            "action": {"type": "buy"},
            "signals": "not_applicable",
            "quality_state": "available"
          },
          {
            "perspective": "value",
            "verdict": "BUY",
            "confidence": 0.79,
            "reason": "valuation leaves enough margin",
            "reasoning": ["fundamental inputs pass valuation margin checks"],
            "action": {"type": "buy"},
            "signals": "not_applicable",
            "quality_state": "available"
          }
        ]
      },
      "consensus": {
        "scorer_version": "consensus-scorer-v2026.08",
        "weights_used": {"kwangsoo": 0.2, "ouroboros": 0.2, "quant": 0.2, "macro": 0.2, "value": 0.2},
        "vote_summary": {"BUY": 4, "SELL": 0, "HOLD": 1, "N/A": 0},
        "consensus_verdict": "BUY",
        "consensus_confidence": "high",
        "consensus_label": "강한 합의",
        "initial_consensus": "not_applicable"
      },
      "deliberation": {
        "triggered": false,
        "trigger_reason": "not_applicable",
        "rounds": "not_applicable",
        "errors": []
      },
      "portfolio_state": {
        "state_hash": "sha256:portfolio-redacted-fixture",
        "cash_available_base": 10000000,
        "base_reporting_currency": "KRW",
        "positions": [],
        "quality_state": "available"
      },
      "risk_state": {
        "sizer_version": "portfolio-sizer-v2026.08",
        "cash_floor": 2000000,
        "concentration_state": "available",
        "correlation_state": "available",
        "blocked_fields": [],
        "degraded_fields": []
      },
      "quality_states": [
        {"field": "recommendation", "state": "available", "reason": "all required decision inputs present"}
      ],
      "content_hashes": {
        "candidate_universe_hash": "sha256:universe-fixture",
        "source_hash": "sha256:source-fixture",
        "feature_hash": "sha256:feature-fixture",
        "prompt_hash": "sha256:prompt-fixture",
        "raw_result_hash": "sha256:raw-results-fixture",
        "parsed_result_hash": "sha256:parsed-results-fixture",
        "consensus_hash": "sha256:consensus-fixture",
        "portfolio_state_hash": "sha256:portfolio-redacted-fixture"
      }
    }
  ],
  "content_hashes": {
    "snapshot_identity_hash": "sha256:identity-fixture",
    "snapshot_content_hash": "sha256:content-fixture"
  }
}
```

Trace: `sources` and `candidate_universe` feed `features` and `signals`. Those feed redacted prompts and code-based quant results. `raw_results` feed `parsed_results`. Parsed perspective results feed `consensus`. `portfolio_state` and `risk_state` explain execution constraints without changing the Phase 22 decision timestamp or Phase 25 market context.

## Provider failure and degraded fixture

This fixture covers LLM N/A, stale cache, missing FX, and secret-like input redaction. It contains no real secret.

```json
{
  "schema_version": "v4.snapshot.phase23.1",
  "snapshot_id": "snap_v4_41b6c1f7a2d8e901c3ab",
  "created_at": "2026-06-02T23:05:12+09:00",
  "decision_at": "2026-06-02T22:58:00+09:00",
  "recommendation_emitted_at": "2026-06-02T23:05:00+09:00",
  "decision_data_cutoff_at": "2026-06-01T16:00:00-04:00",
  "request_scope": {
    "market_scope": "US",
    "tickers_requested": ["MSFT"],
    "top_n": 1,
    "operator_request_id": "REDACTED_SECRET(free_text)"
  },
  "contract_refs": {
    "measurement_contract": "v4.phase22.1",
    "market_context_contract": "v4.market_context.phase25.1"
  },
  "retention_policy": {
    "policy_version": "v4.retention.phase23.1",
    "raw_llm_text_days": 180,
    "market_payload_retention": "hash_only"
  },
  "redaction": {
    "redaction_version": "v4.redaction.phase23.1",
    "redaction_events": [
      {"field_path": "request_scope.operator_request_id", "class": "secret_like_free_text", "replacement": "REDACTED_SECRET(free_text)"},
      {"field_path": "llm.prompt_messages_redacted[1].content", "class": "api_key", "replacement": "REDACTED_SECRET(api_key)"}
    ]
  },
  "recommendations": [
    {
      "recommendation_id": "rec_v4_6538a0cfe7d4b812d2aa",
      "ticker": "MSFT",
      "name": "Microsoft Corporation",
      "market": "US",
      "exchange": "NASDAQ",
      "action": "HOLD",
      "decision_at": "2026-06-02T22:58:00+09:00",
      "emitted_at": "2026-06-02T23:05:00+09:00",
      "data_cutoff_at": "2026-06-01T16:00:00-04:00",
      "market_context": {
        "schema_version": "v4.market_context.phase25.1",
        "ticker": "MSFT",
        "market": "US",
        "exchange": "NASDAQ",
        "calendar_id": "NASDAQ",
        "calendar_version": "us-calendar-2026.08",
        "timezone": "America/New_York",
        "quote_currency": "USD",
        "base_reporting_currency": "KRW",
        "benchmark_id": "IXIC",
        "benchmark_source": "FinanceDataReader",
        "benchmark_as_of": "2026-06-01T16:00:00-04:00",
        "decision_data_cutoff_at": "2026-06-01T16:00:00-04:00",
        "target_session_close_at": "2026-06-10T16:00:00-04:00",
        "decision_regime": "bull",
        "decision_regime_source": "IXIC",
        "decision_regime_as_of": "2026-06-01T16:00:00-04:00",
        "analysis_regime": "unknown",
        "analysis_regime_source": "IXIC",
        "fx_pair": "USD_KRW",
        "fx_rate": null,
        "fx_as_of": null,
        "fx_freshness_state": "missing",
        "context_state": "degraded",
        "blocked_fields": [],
        "degraded_fields": ["portfolio_market_value_krw", "position_weight", "concentration_check"],
        "provenance_hashes": {
          "benchmark": "sha256:benchmark-us-fixture",
          "calendar": "sha256:calendar-us-fixture",
          "fx": "sha256:fx-missing-fixture"
        }
      },
      "sources": [
        {
          "source_id": "web.cache.news",
          "adapter_version": "web-search-v2026.08",
          "record_type": "news",
          "as_of": "2026-06-01T09:00:00-04:00",
          "fetched_at": "2026-06-02T22:58:20+09:00",
          "freshness_state": "stale",
          "provenance_hash": "sha256:stale-cache-fixture",
          "raw_retention": "hash_only"
        },
        {
          "source_id": "fx.usd_krw",
          "adapter_version": "fx-adapter-v2026.08",
          "record_type": "fx",
          "as_of": null,
          "fetched_at": "2026-06-02T22:58:22+09:00",
          "freshness_state": "missing",
          "provenance_hash": "sha256:missing-fx-fixture",
          "raw_retention": "hash_only"
        }
      ],
      "candidate_universe": {
        "universe_id": "universe_v4_us_20260602",
        "market_scope": "US",
        "source": "diversified_selection",
        "adapter_version": "screener-v2026.08",
        "total_seen": "unknown",
        "members_hash": "sha256:us-universe-fixture"
      },
      "selection": {
        "selected_by": ["rank", "operator_pin"],
        "rank_before_filter": null,
        "rank_after_filter": 1,
        "selection_reason": "operator requested MSFT while some freshness inputs were degraded"
      },
      "rejections": [],
      "features": {
        "current_price": 492.81,
        "market_cap": {
          "value": 36593,
          "currency": "KRW",
          "unit": "KRW_100M",
          "state": "blocked",
          "reason": "us_market_cap_currency_unit_mismatch"
        },
        "news": {
          "state": "degraded",
          "reason": "stale_cache"
        }
      },
      "signals": {
        "engine_version": "technical-v2.2026.08",
        "momentum": "bull",
        "short_momentum": "bull",
        "ema": "bull",
        "rsi": "bull",
        "macd": "bull",
        "bb": "expanded",
        "volume_ratio": 1.29,
        "state": "available"
      },
      "llm": {
        "provider_adapter_version": "anthropic-adapter-v2026.08",
        "provider": "anthropic",
        "model": "claude-fixture-model",
        "provider_request_id": "prov_req_redacted_degraded_fixture",
        "prompt_bundle_version": "perspectives-v4.2026.08",
        "prompt_hash": "sha256:redacted-prompt-degraded-fixture",
        "prompt_messages_redacted": [
          {"role": "system", "content": "redacted prompt fixture"},
          {"role": "user", "content": "Analyze MSFT. secret candidate token REDACTED_SECRET(api_key) must not be stored."}
        ],
        "config_version": "config-schema-v2026.08",
        "config_hash": "sha256:redacted-config-degraded-fixture",
        "parser_version": "perspective-parser-v2026.08",
        "raw_results": [
          {
            "perspective": "kwangsoo",
            "raw_text_redacted": null,
            "raw_payload_hash": "sha256:provider-empty-fixture",
            "provider_latency_ms": 30000,
            "provider_error_type": "timeout",
            "quality_state": "degraded",
            "raw_retention": "hash_only"
          },
          {
            "perspective": "ouroboros",
            "raw_text_redacted": "{\"verdict\":\"HOLD\",\"confidence\":0.72,\"reason\":\"stale news limits conviction\"}",
            "raw_payload_hash": "sha256:ouroboros-raw-degraded-fixture",
            "provider_latency_ms": 1320,
            "provider_error_type": "not_applicable",
            "quality_state": "available",
            "raw_retention": "keep_redacted"
          },
          {
            "perspective": "quant",
            "raw_text_redacted": null,
            "raw_payload_hash": "sha256:quant-code-result-degraded-fixture",
            "provider_latency_ms": null,
            "provider_error_type": "not_applicable",
            "quality_state": "not_applicable",
            "raw_retention": "not_applicable"
          },
          {
            "perspective": "macro",
            "raw_text_redacted": "{\"verdict\":\"HOLD\",\"confidence\":0.76,\"reason\":\"missing FX degrades portfolio context\"}",
            "raw_payload_hash": "sha256:macro-raw-degraded-fixture",
            "provider_latency_ms": 1410,
            "provider_error_type": "not_applicable",
            "quality_state": "degraded",
            "raw_retention": "keep_redacted"
          },
          {
            "perspective": "value",
            "raw_text_redacted": "{\"verdict\":\"HOLD\",\"confidence\":0.70,\"reason\":\"market cap unit is blocked\"}",
            "raw_payload_hash": "sha256:value-raw-degraded-fixture",
            "provider_latency_ms": 1285,
            "provider_error_type": "not_applicable",
            "quality_state": "degraded",
            "raw_retention": "keep_redacted"
          }
        ],
        "parsed_results": [
          {
            "perspective": "kwangsoo",
            "verdict": "N/A",
            "confidence": null,
            "reason": "provider timeout before parsed result",
            "reasoning": [],
            "action": null,
            "signals": "not_applicable",
            "quality_state": "degraded"
          },
          {
            "perspective": "ouroboros",
            "verdict": "HOLD",
            "confidence": 0.72,
            "reason": "stale news limits conviction",
            "reasoning": ["stale cache is retained as degraded context rather than omitted"],
            "action": {"type": "hold"},
            "signals": "not_applicable",
            "quality_state": "available"
          },
          {
            "perspective": "quant",
            "verdict": "BUY",
            "confidence": 0.83,
            "reason": "Bull 5/6 vs 0/6",
            "reasoning": ["code-based technical result did not require provider"],
            "action": {"type": "buy"},
            "signals": {"momentum": "bull", "ema": "bull", "rsi": "bull"},
            "quality_state": "available"
          },
          {
            "perspective": "macro",
            "verdict": "HOLD",
            "confidence": 0.76,
            "reason": "missing FX degrades portfolio context",
            "reasoning": ["quote return remains usable but KRW portfolio normalization is degraded"],
            "action": {"type": "hold"},
            "signals": "not_applicable",
            "quality_state": "degraded"
          },
          {
            "perspective": "value",
            "verdict": "HOLD",
            "confidence": 0.70,
            "reason": "market cap unit is blocked",
            "reasoning": ["US market-cap KRW unit mismatch blocks valuation-derived fields"],
            "action": {"type": "hold"},
            "signals": "not_applicable",
            "quality_state": "degraded"
          }
        ]
      },
      "consensus": {
        "scorer_version": "consensus-scorer-v2026.08",
        "weights_used": {"kwangsoo": 0.2, "ouroboros": 0.2, "quant": 0.2, "macro": 0.2, "value": 0.2},
        "vote_summary": {"BUY": 1, "SELL": 0, "HOLD": 3, "N/A": 1},
        "consensus_verdict": "HOLD",
        "consensus_confidence": "moderate",
        "consensus_label": "약한 합의",
        "initial_consensus": {
          "consensus_verdict": "HOLD",
          "vote_summary": {"BUY": 1, "SELL": 0, "HOLD": 3, "N/A": 1}
        }
      },
      "deliberation": {
        "triggered": true,
        "trigger_reason": "weak_consensus_with_provider_na",
        "rounds": [],
        "errors": ["kwangsoo provider timeout retained as N/A"],
        "quality_state": "degraded"
      },
      "portfolio_state": {
        "state_hash": "sha256:portfolio-redacted-degraded-fixture",
        "cash_available_base": "unknown",
        "base_reporting_currency": "KRW",
        "positions": [
          {"ticker": "MSFT", "quantity": 0, "average_price": null, "market": "US", "valuation_state": "degraded"}
        ],
        "quality_state": "degraded"
      },
      "risk_state": {
        "sizer_version": "portfolio-sizer-v2026.08",
        "cash_floor": null,
        "concentration_state": "degraded",
        "correlation_state": "unknown",
        "blocked_fields": ["market_cap", "valuation_by_market_cap", "size_bucket"],
        "degraded_fields": ["portfolio_market_value_krw", "position_weight", "concentration_check"]
      },
      "quality_states": [
        {"field": "llm.raw_results[kwangsoo]", "state": "degraded", "reason": "provider_timeout_retained_as_na"},
        {"field": "sources[web.cache.news]", "state": "degraded", "reason": "stale_cache"},
        {"field": "market_context.fx", "state": "degraded", "reason": "missing_fx_for_base_reporting"},
        {"field": "features.market_cap", "state": "blocked", "reason": "us_market_cap_currency_unit_mismatch"},
        {"field": "request_scope.operator_request_id", "state": "available", "reason": "secret_like_input_redacted_before_storage"}
      ],
      "content_hashes": {
        "candidate_universe_hash": "sha256:us-universe-fixture",
        "source_hash": "sha256:source-degraded-fixture",
        "feature_hash": "sha256:feature-degraded-fixture",
        "prompt_hash": "sha256:redacted-prompt-degraded-fixture",
        "raw_result_hash": "sha256:raw-results-degraded-fixture",
        "parsed_result_hash": "sha256:parsed-results-degraded-fixture",
        "consensus_hash": "sha256:consensus-degraded-fixture",
        "portfolio_state_hash": "sha256:portfolio-redacted-degraded-fixture"
      }
    }
  ],
  "content_hashes": {
    "snapshot_identity_hash": "sha256:identity-degraded-fixture",
    "snapshot_content_hash": "sha256:content-degraded-fixture"
  }
}
```

Degraded classification:

| case | field | expected state | affected outputs |
| --- | --- | --- | --- |
| LLM timeout | `llm.parsed_results[kwangsoo]` | `degraded` with `verdict="N/A"` | consensus includes N/A count, perspective is not dropped |
| stale cache | `sources[web.cache.news]` | `degraded` | news-derived reasoning can be marked stale, quote return unaffected |
| missing FX | `market_context.fx_freshness_state` | `degraded` | KRW portfolio value, weight, concentration blocked from use |
| secret-like input | `request_scope.operator_request_id`, prompt content | `available` after redaction | retained text contains replacement token only |
| US market cap unit mismatch | `features.market_cap` | `blocked` | market-cap valuation and size bucket blocked, Phase 22 quote return unaffected |

## Legacy snapshot compatibility

Existing snapshots such as `data/snapshots/2026-03-28.json` and `data/snapshots/2026-08-05.json` are not native v4 snapshots. They preserve useful audit evidence, but lack several v4 fields.

| legacy field present | v4 field missing | handling |
| --- | --- | --- |
| `date` | `decision_at`, `created_at`, `recommendation_emitted_at`, `decision_data_cutoff_at` | Phase 24 backfill may derive date-level audit metadata, native v4 identity remains unavailable |
| `market.kospi`, `market.kosdaq` | per-recommendation Phase 25 market context for US tickers | set `unknown` or `insufficient_context` in derived audit |
| `recommendations.*.price` | Phase 22 entry session close | do not treat as next-session entry |
| `perspectives[]` | raw provider output, prompt hash, parser version | `unknown`, not reconstructed |
| `initial_consensus`, `deliberation` sometimes present | deterministic deliberation provenance | use only what exists, no invented rounds |
| `vote_summary` | candidate universe and rejections | `unknown`, denominator cannot be reconstructed |

The 2026-08-05 snapshot shows why this matters. It contains US tickers, deliberation, and some LLM reasoning, while market context stores only `kospi` and `kosdaq`. It also includes market-cap unit concerns in reasoning text. Phase 23 requires those concerns to become structured `blocked` or `degraded` fields.

## Acceptance criteria

1. A native v4 snapshot has `schema_version`, deterministic `snapshot_id`, timestamp separation, request scope, contract references, recommendations, content hashes, retention policy, and redaction metadata.
2. Every recommendation includes Phase 25 market context, source freshness, candidate audit, features, signals, provider/model/prompt/config/parser versions, raw and parsed results, consensus, deliberation, portfolio state, risk state, quality states, and section hashes.
3. `unknown`, `degraded`, `blocked`, and `not_applicable` are preserved as first-class states and are not silently replaced with null or success values.
4. Deterministic ID and hash algorithms specify canonicalization, redaction-before-hash, hash inputs, and cycle avoidance.
5. Native happy and provider failure fixtures are valid JSON and cover recommendation-time input to parsed output tracing.
6. Provider failure keeps LLM N/A in the fixed perspective order, stale cache remains degraded, missing FX only degrades KRW portfolio normalization, and secret-like prompt/request content is redacted before storage.
7. Existing legacy snapshots remain audit-only until Phase 24 classifies what can and cannot be backfilled.
