# PRD 01: Source Adapter Provenance
> **상태**: ✅ 구현 완료 (2026-08-07)

Parent SPEC: [v7 Information Source Expansion SPEC](../SPEC.md)

## 문서 범위

이 문서는 외부 데이터 소스를 Trading Oracle 내부 기록으로 들여올 때 필요한 어댑터 계약을 정의한다. 가격, 지수, 종목 목록, 펀더멘털, 환율, 매크로 시계열, 뉴스, 웹 컨텍스트를 같은 provenance 형식으로 기록한다.

현재 코드에는 웹 검색 캐시의 `searched_at`, 펀더멘털 캐시의 `cached_at`, README의 데이터 소스 표처럼 출처 단서가 이미 있다. 하지만 추천 기록이 나중에 재검토될 때, 어떤 어댑터가 어떤 권한으로 어느 시점의 데이터를 읽었는지, 원문과 정규화 값이 어떻게 연결되는지 독립적으로 증명하기에는 부족하다.

이 PRD는 특정 vendor를 기본값으로 정하지 않는다. 같은 기능을 제공하는 여러 소스가 있으면 각 소스는 동일한 계약을 만족해야 하며, 선택 순서는 이 문서 밖의 실행 정책이 정한다.

## 목표

1. 모든 source adapter가 공통 identity, auth boundary, market coverage, timestamp, as-of, license, retention, version, hash를 남기게 한다.
2. 정규화 record와 raw payload hash를 분리해 값 변환과 원문 증거를 함께 추적한다.
3. secret, token, cookie, 계좌 정보, 사용자 입력 원문이 hash 전에 redaction 되는 규칙을 고정한다.
4. 데이터 결손, stale source, malformed payload, untrusted external text, auth boundary 위반을 성공처럼 보이지 않게 한다.
5. downstream 문서나 구현 없이도 이 계약만으로 fixture와 parser를 작성할 수 있게 한다.

## 비목표

1. 특정 vendor, API, 스크래퍼, 라이브러리, 유료 플랜을 표준으로 지정하지 않는다.
2. config 파일, secret 파일, auth 파일, 로컬 토큰을 읽거나 문서에 적지 않는다.
3. quality scoring, dedup, source ON/OFF 성과 비교, promotion policy를 정의하지 않는다.
4. 기존 cache 파일을 migration 하거나 data 파일을 쓰지 않는다.
5. 외부 웹 텍스트를 신뢰된 지시문으로 취급하지 않는다.

## Adapter Contract

모든 adapter fetch는 아래 envelope를 반환하거나 같은 필드를 가진 artifact를 남긴다. 필드가 비어 있으면 성공 record가 아니다.

| field | required rule |
| --- | --- |
| `adapter_id` | 논리 ID. 예: `market_price_kr`, `fundamental_equity`, `web_context`. Vendor 이름만으로 만들지 않는다. |
| `adapter_version` | 코드 버전, schema 버전, 변환 규칙 버전을 함께 식별한다. 예: `source-adapter-provenance.1+sha256:<64hex>`. |
| `source_identity.source_id` | Vendor 중립 source ID. 같은 adapter가 fallback을 쓰면 실제 읽은 source를 기록한다. |
| `source_identity.source_kind` | `broker_api`, `exchange_dataset`, `finance_library`, `web_page`, `search_result`, `manual_fixture`, `local_cache` 중 하나. |
| `source_identity.endpoint_label` | URL, table, method, symbol namespace를 secret 없이 식별하는 label. Query token은 금지한다. |
| `auth_boundary.mode` | `none`, `api_key`, `oauth`, `session_cookie`, `local_cache`, `manual_fixture` 중 하나. |
| `auth_boundary.secret_material_present` | 실제 credential 사용 여부를 boolean으로만 기록한다. 값 자체, key 이름 일부, token prefix는 금지한다. |
| `auth_boundary.redaction_policy` | 적용한 redaction policy ID. |
| `market_coverage` | market, exchange, asset type, symbol namespace, currency, timezone 목록. |
| `fetch_started_at` | fetch 시도 시작 timestamp. ISO 8601 timezone 포함. |
| `fetched_at` | 응답 수신 timestamp. ISO 8601 timezone 포함. |
| `as_of` | record 값이 나타내는 기준 시각 또는 기준 session. 없으면 success가 아니다. |
| `freshness_status` | `fresh`, `stale`, `missing`, `degraded`, `not_applicable` 중 하나. |
| `license` | source license, ToS class, redistribution boundary, attribution 필요 여부. 모르면 `unknown`으로 적고 downstream 재배포를 막는다. |
| `retention` | raw retention 방식, TTL, hash-only 여부, deletion rule. |
| `normalized_record` | 내부 schema에 맞춘 값. secret과 raw HTML 또는 raw JSON 전체를 담지 않는다. |
| `raw_payload_hash` | redacted raw payload의 `sha256:<64 lowercase hex>`. Raw를 보관하지 않아도 hash는 필요하다. |
| `normalized_record_hash` | canonical JSON으로 직렬화한 normalized record hash. |
| `provenance_hash` | envelope 전체에서 hash 필드를 제외하고 redaction 후 계산한 hash. |
| `capabilities` | adapter가 제공할 수 있는 feature 목록과 한계. |
| `error_envelope` | 성공이면 null. 실패나 degraded이면 표준 오류 객체. |

## Auth Boundary

Auth boundary는 credential 자체를 기록하지 않는다. boundary는 누가 어떤 권한 범위로 읽었는지만 말한다.

| field | allowed content | forbidden content |
| --- | --- | --- |
| `mode` | credential 방식 이름 | token, cookie, secret value |
| `scope_label` | `read_market_data`, `read_public_web`, `read_local_cache` 같은 범위 | 계좌번호, client secret, bearer token |
| `credential_ref_hash` | redacted credential reference의 hash | credential 원문, prefix, suffix |
| `loaded_from` | `env`, `oauth_store`, `config`, `none` 같은 위치 class | 실제 파일 경로가 secret 위치를 드러내는 값 |
| `secret_material_present` | boolean | secret 문자열 |

Auth가 필요한 source에서 auth boundary가 없으면 adapter는 `AUTH_BOUNDARY_MISSING` 오류를 반환한다. Auth가 필요 없는 공개 웹 또는 local fixture도 `mode="none"` 또는 `mode="manual_fixture"`를 명시한다.

## Market Coverage

Coverage는 source가 읽을 수 있다고 주장하는 범위와 이번 fetch가 실제로 읽은 범위를 분리한다.

| field | meaning |
| --- | --- |
| `declared_markets[]` | adapter 문서상 가능한 market. 예: `KR`, `US`. |
| `declared_exchanges[]` | 가능한 exchange 또는 index namespace. |
| `actual_market` | 이번 record의 market. |
| `actual_exchange` | 이번 record의 exchange. 모르면 `unknown`이며 benchmark나 market feature에 쓰지 않는다. |
| `symbol_namespace` | `KRX_CODE`, `US_TICKER`, `INDEX_CODE`, `FX_PAIR`, `WEB_QUERY` 등. |
| `currency` | quote currency. 모르면 valuation 또는 portfolio normalization에 쓰지 않는다. |
| `timezone` | source timestamp 해석에 쓰는 timezone. |

Coverage mismatch는 silent fallback이 아니다. 예를 들어 US ticker가 KR market adapter에서 읽힌 것처럼 보이면 `COVERAGE_MISMATCH`로 닫는다.

## Timestamp and As-of Rules

`fetch_started_at`, `fetched_at`, `as_of`는 서로 다른 값이다.

| timestamp | required meaning |
| --- | --- |
| `fetch_started_at` | 네트워크 요청, cache read, fixture read를 시작한 시각. |
| `fetched_at` | 응답 또는 cache entry를 받은 시각. |
| `as_of` | 데이터 값의 기준 시각, 기준 거래 session, 발표 시각, 또는 검색 결과 publish 시각. |

`fetched_at`은 `as_of`를 대신할 수 없다. 웹 검색 결과처럼 publish date가 불확실한 자료는 `as_of.kind="unknown"`과 `freshness_status="degraded"`로 남기며, 사실 근거로 승격하지 않는다.

Freshness 판정의 숫자 기준은 [PRD 02 Freshness SLA and TTL](prd02-quality-freshness-dedup.md#freshness-sla-and-ttl)을 단일 원천으로 사용한다. PRD 01은 adapter가 선언한 임의 window를 신뢰하지 않는다.

## License and Retention

| field | required rule |
| --- | --- |
| `license.name` | 공개 license, vendor ToS class, 또는 `unknown`. |
| `license.redistribution` | `allowed`, `internal_only`, `hash_only`, `forbidden`, `unknown`. |
| `license.attribution_required` | boolean 또는 `unknown`. |
| `retention.raw_mode` | `store_redacted`, `hash_only`, `discard_after_hash`, `fixture_inline`. |
| `retention.ttl_hours` | cache나 raw copy를 둘 수 있는 시간. 없으면 null과 이유를 적는다. |
| `retention.user_visible_allowed` | 사용자 출력에 원문을 보여도 되는지. |

License가 `unknown`이면 raw text 재배포는 금지한다. `hash_only`나 `discard_after_hash`라도 normalized record와 hash는 남긴다.

## Normalized Record and Hash

Canonical JSON 규칙은 다음과 같다.

1. UTF-8로 직렬화한다.
2. Object key는 정렬한다.
3. Array 순서는 의미가 있으면 보존한다.
4. Redaction을 먼저 적용한다.
5. `raw_payload_hash`, `normalized_record_hash`, `provenance_hash`는 자기 자신을 계산할 때 제외한다.
6. Timestamp는 timezone 포함 ISO 8601을 쓴다.
7. NaN, Infinity, locale comma 숫자는 금지한다.

`normalized_record`는 source별 원문 모양을 숨기고 내부 의미만 담는다.

```json
{
  "record_type": "fundamental_snapshot",
  "symbol": "005930",
  "market": "KR",
  "exchange": "KOSPI",
  "as_of": {"kind": "session", "value": "2026-08-06", "timezone": "Asia/Seoul"},
  "fields": {
    "per": 18.42,
    "pbr": 1.31,
    "div_yield": 2.12
  },
  "field_units": {
    "per": "ratio",
    "pbr": "ratio",
    "div_yield": "percent"
  }
}
```

## Source Capability Matrix

Capability는 source 선택 근거가 아니라 검증 가능한 능력 선언이다.

| capability | required metadata | cannot claim when |
| --- | --- | --- |
| `ohlcv_daily` | market, exchange, adjusted 여부, as-of session, currency, split/dividend policy | close만 있고 session calendar가 없음 |
| `index_ohlcv_daily` | index namespace, timezone, as-of session, benchmark suitability | ticker price와 index price를 같은 namespace로 섞음 |
| `market_cap` | shares source, price source, currency, as-of | shares as-of와 price as-of가 없음 |
| `fundamentals` | field list, source page or dataset label, statement period, as-of | fetch time만 있고 statement 기준일이 없음 |
| `fx_rate` | pair, quote convention, fixing time, timezone | latest display quote만 있고 기준 시각이 없음 |
| `macro_timeseries` | series ID, unit, frequency, release timestamp, revision policy | source revision policy가 없음 |
| `news_search` | query label, result publish date, snippet boundary, untrusted text flag | 검색일만 있고 publish/as-of가 없음 |
| `web_context` | query label, result URL hash, title/snippet hash, prompt eligibility | external text가 trusted instruction으로 표시됨 |
| `local_cache` | upstream source ref, cache written_at, upstream as-of, TTL | upstream provenance가 없음 |

## Redaction Rules

Redaction은 hash 전에 실행한다.

| category | action |
| --- | --- |
| API key, OAuth token, bearer token, cookie | replace with `[REDACTED_SECRET]` |
| client id and client secret pair | secret은 redact, public id도 필요 없으면 hash only |
| account number, portfolio free text, user prompt free text | replace with `[REDACTED_USER_DATA]` unless explicitly allowed by a separate snapshot contract |
| URL query token, signed URL, session id | keep endpoint label only, remove query secret |
| HTML or search snippet containing prompt-like instruction | keep as untrusted content, never instruction |

Redaction이 적용됐는지 증명하려면 `redaction_report`에 pattern count와 replacement count를 남긴다. Count가 0이어도 report는 필요하다.

## Error Envelope

오류와 degraded 결과는 같은 envelope를 쓴다. `normalized_record`가 없거나 `as_of`가 없으면 `result_status="fail"` 또는 `result_status="degraded"`다.

| field | required rule |
| --- | --- |
| `error_code` | `AS_OF_MISSING`, `AUTH_BOUNDARY_MISSING`, `SECRET_LEAKAGE_DETECTED`, `COVERAGE_MISMATCH`, `LICENSE_UNKNOWN_RESTRICTED`, `RAW_HASH_MISSING`, `NORMALIZATION_FAILED`, `STALE_SOURCE`, `MALFORMED_PAYLOAD`, `UNTRUSTED_TEXT_PROMPT_INJECTION`, `SOURCE_UNAVAILABLE` 중 하나. |
| `severity` | `fail`, `degraded`, `blocked`. |
| `message` | 사용자에게 보여도 되는 짧은 설명. Secret과 raw payload 금지. |
| `retryable` | boolean. |
| `safe_fallback_allowed` | boolean. true이면 fallback source도 이 PRD를 만족해야 한다. |
| `blocked_fields[]` | 사용할 수 없는 normalized field 목록. |
| `evidence_ref` | redacted payload hash, parser result, mutation result 중 하나. |

## Machine-readable Fixture

```json
{
  "schema_version": "v7.source_adapter_provenance.prd01.1",
  "contract_id": "source_adapter_provenance_prd01",
  "required_fields": [
    "adapter_id",
    "adapter_version",
    "source_identity",
    "auth_boundary",
    "market_coverage",
    "fetch_started_at",
    "fetched_at",
    "as_of",
    "freshness_status",
    "license",
    "retention",
    "normalized_record",
    "raw_payload_hash",
    "normalized_record_hash",
    "provenance_hash",
    "capabilities",
    "redaction_report",
    "error_envelope"
  ],
  "hash_rules": {
    "algorithm": "sha256",
    "format": "sha256:<64 lowercase hex>",
    "redaction_before_hash": true,
    "exclude_hash_fields_from_self_hash": true,
    "canonical_json": "utf8_sorted_keys_semantic_arrays"
  },
  "happy_trace_fixture": {
    "adapter_id": "fundamental_equity",
    "adapter_version": "source-adapter-provenance.1+sha256:1111111111111111111111111111111111111111111111111111111111111111",
    "source_identity": {
      "source_id": "public_fundamental_snapshot_source",
      "source_kind": "web_page",
      "endpoint_label": "equity_fundamental_main_page",
      "vendor_default": false
    },
    "auth_boundary": {
      "mode": "none",
      "scope_label": "read_public_web",
      "secret_material_present": false,
      "credential_ref_hash": null,
      "loaded_from": "none",
      "redaction_policy": "adapter-redaction.1"
    },
    "market_coverage": {
      "declared_markets": ["KR"],
      "declared_exchanges": ["KOSPI", "KOSDAQ"],
      "actual_market": "KR",
      "actual_exchange": "KOSPI",
      "symbol_namespace": "KRX_CODE",
      "currency": "KRW",
      "timezone": "Asia/Seoul"
    },
    "fetch_started_at": "2026-08-06T09:00:01+09:00",
    "fetched_at": "2026-08-06T09:00:02+09:00",
    "as_of": {"kind": "session", "value": "2026-08-06", "timezone": "Asia/Seoul"},
    "freshness_status": "fresh",
    "license": {
      "name": "unknown",
      "redistribution": "hash_only",
      "attribution_required": "unknown"
    },
    "retention": {
      "raw_mode": "discard_after_hash",
      "ttl_hours": 168,
      "user_visible_allowed": false
    },
    "normalized_record": {
      "record_type": "fundamental_snapshot",
      "symbol": "005930",
      "market": "KR",
      "exchange": "KOSPI",
      "as_of": {"kind": "session", "value": "2026-08-06", "timezone": "Asia/Seoul"},
      "fields": {"per": 18.42, "pbr": 1.31, "div_yield": 2.12},
      "field_units": {"per": "ratio", "pbr": "ratio", "div_yield": "percent"}
    },
    "raw_payload_hash": "sha256:2222222222222222222222222222222222222222222222222222222222222222",
    "normalized_record_hash": "sha256:3333333333333333333333333333333333333333333333333333333333333333",
    "provenance_hash": "sha256:4444444444444444444444444444444444444444444444444444444444444444",
    "capabilities": ["fundamentals"],
    "redaction_report": {
      "policy": "adapter-redaction.1",
      "patterns_checked": ["secret", "token", "cookie", "signed_url", "user_data"],
      "replacement_count": 0
    },
    "error_envelope": null,
    "result_status": "pass"
  },
  "failure_fixtures": [
    {
      "fixture": "missing_as_of_record",
      "mutation": "remove as_of from envelope and normalized_record",
      "expected_status": "fail",
      "expected_error_code": "AS_OF_MISSING",
      "blocked_fields": ["per", "pbr", "div_yield"]
    },
    {
      "fixture": "secret_leakage_in_payload",
      "mutation": "insert bearer token text before redaction and keep it in normalized_record",
      "expected_status": "fail",
      "expected_error_code": "SECRET_LEAKAGE_DETECTED",
      "blocked_fields": ["normalized_record", "raw_payload_hash", "provenance_hash"]
    }
  ],
  "required_probes": [
    "stale_source",
    "dirty_input_hash",
    "misleading_success_output",
    "malformed_payload",
    "prompt_injection_from_untrusted_external_text",
    "json_field_removal",
    "hash_mismatch",
    "timestamp_order_violation",
    "redaction_after_hash"
  ]
}
```

## Happy Trace

1. Adapter `fundamental_equity` starts a public read for symbol `005930` at `2026-08-06T09:00:01+09:00`.
2. Auth boundary says `mode="none"`, `secret_material_present=false`, and no secret path or token is present.
3. Source identity records a logical source and endpoint label without choosing a default vendor.
4. The raw page is redacted, hashed, then discarded according to retention.
5. Normalization extracts PER, PBR, and dividend yield into a compact record with market, exchange, currency, timezone, and as-of session.
6. Parser recomputes normalized and provenance hashes from canonical JSON.
7. The record is accepted only because source identity, as-of, auth boundary, license, retention, capability, redaction report, adapter version, and hashes are all present.

## Failure Fixtures

### Missing as-of

Input has `fetched_at` but no `as_of`. The parser must return `AS_OF_MISSING`. `fetched_at` cannot fill the missing value. No valuation field can enter a recommendation snapshot from this record.

### Secret leakage

Input contains a token, cookie, signed URL, account value, or user free text after redaction. The parser must return `SECRET_LEAKAGE_DETECTED`. Hashes computed over leaked content are invalid, even if the digest format is correct.

## Required Probes

| probe | mutation | expected result |
| --- | --- | --- |
| `stale_source` | set `as_of` outside the allowed freshness window while `result_status` remains pass | fail with `STALE_SOURCE` |
| `dirty_input_hash` | change normalized value after `normalized_record_hash` is computed | fail with hash mismatch |
| `misleading_success_output` | keep `result_status="pass"` while `error_envelope` has severity fail | fail with misleading output |
| `malformed_payload` | provide invalid JSON, NaN, Infinity, duplicate key, or bad timestamp | fail with `MALFORMED_PAYLOAD` |
| `prompt_injection_from_untrusted_external_text` | put `ignore previous instructions` style text in title or snippet and mark it trusted | fail with `UNTRUSTED_TEXT_PROMPT_INJECTION` |
| `json_field_removal` | remove each required field one at a time | fail for each removal |
| `hash_mismatch` | alter raw hash, normalized hash, or provenance hash | fail with hash mismatch |
| `timestamp_order_violation` | make `fetched_at` earlier than `fetch_started_at` | fail with malformed timestamp order |
| `redaction_after_hash` | compute hash before redaction then redact output | fail because hash no longer proves retained content |

## Acceptance Criteria

1. The adapter contract names identity, auth boundary, market coverage, timestamps, as-of, license, retention, normalized record, raw hash, adapter version, capability matrix, redaction report, and error envelope.
2. The contract is vendor-neutral and does not choose a default source.
3. Machine-readable JSON fixture includes a happy trace and failures for missing as-of and secret leakage.
4. Parser requirements cover JSON field removal, hash mutation, timestamp mutation, and redaction mutation.
5. Required probes include stale, dirty, misleading, malformed, and prompt injection cases caused by untrusted external text.
6. A success record cannot be created from `fetched_at` alone, leaked secret material, missing raw hash, unknown license with raw redistribution, or fallback data without its own provenance.

## Evidence Requirement

The exact evidence artifact for this authoring task is `.omo/evidence/trading-oracle-v4-v9-specs-20260806/task-20-trading-oracle-v4-measurement-attribution.md`. The evidence must record failing-first target absence, manual Read of this PRD, deterministic parser checks, fixture mutation checks, and the no secret-read boundary.
