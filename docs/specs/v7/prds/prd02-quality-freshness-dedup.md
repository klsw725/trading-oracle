# PRD 02: Quality Freshness Dedup
> **상태**: ✅ 구현 완료 (2026-08-08)

Parent SPEC: [v7 Information Source Expansion SPEC](../SPEC.md)

## 문서 범위

이 문서는 v7 source artifact가 추천, 리포트, 프롬프트 컨텍스트에 들어가기 전에 통과해야 하는 품질, freshness, dedup 계약을 정의한다. [PRD 01](prd01-source-adapter-provenance.md)의 provenance envelope가 이미 만들어졌다는 전제에서 동작한다.

현재 `src/data/web_search.py`는 DuckDuckGo 결과를 `searched_at`, `gate_stats`, `title`, `snippet`, `date`, `url`로 캐시한다. `data/web_cache.json`에는 검색별 건수와 통과 건수가 있지만, 중복 기사, publish date 결측, 상충 문장, 오래된 기사, 신뢰도 낮은 도메인, prompt injection 문구를 품질 점수와 분리해서 표현하는 계약은 없다.

검색 결과 개수는 품질이 아니다. `gate_stats.passed=28`이어도 같은 원문을 재배포한 중복 묶음이면 독립 근거는 1개일 수 있다. 반대로 2개 결과만 있어도 서로 독립된 공시와 거래소 자료면 품질이 높을 수 있다.

## 목표

1. Source artifact별 freshness SLA와 TTL 판정 규칙을 고정한다.
2. URL, canonical title, source family, subject, event date를 이용해 duplicate cluster와 dedup key를 만든다.
3. factuality, reliability, contradiction, prompt safety, cache hygiene를 count와 독립된 quality signal로 기록한다.
4. stale, degraded, expired, fallback 결과가 fresh 또는 high quality처럼 보이지 않게 한다.
5. JSON parser와 mutation fixture만으로 happy path와 failure path를 검증할 수 있게 한다.

## 비목표

1. 특정 검색 vendor, 뉴스 vendor, LLM provider, broker API를 기본값으로 정하지 않는다.
2. 기존 `data/web_cache.json` 파일을 migration 하거나 수정하지 않는다.
3. PRD 01의 provenance 필드, redaction, auth boundary를 다시 정의하지 않는다.
4. 검색 결과 수, snippet 길이, query 수를 품질 점수로 승격하지 않는다.
5. Source ON/OFF 성과 비교, promotion, retirement 정책을 정의하지 않는다.

## Input Contract

구현 계약 `v7.quality_freshness_dedup.prd02.2`는 caller가 평가 fixture 안에 함께 넣은 expected root를 증거로 인정하지 않는다. 각 source는 완전한 PRD 01 `PersistedProvenanceBundle`을 내장하고, compiler 호출자는 평가 fixture와 별도 경로에서 읽은 `v7.quality_freshness_dedup.trust.1` 문서로 registry root와 bundle root를 제공해야 한다.

| field | rule |
| --- | --- |
| `source.bundle` | PRD 01 artifact와 trusted payload manifest를 함께 가진 persisted verification bundle. hash-only ref는 금지한다. |
| `source.upstream_bundle` | local cache일 때 필수인 별도 upstream PRD 01 persisted bundle. cache와 upstream 모두 각자의 root와 raw preimage로 검증한다. |
| `QualityTrustDocument` | 평가 fixture와 독립적으로 persisted된 primary/fallback registry root 및 bundle root inventory다. body와 claimed root를 함께 바꿔도 이 문서를 바꾸지 않으면 발급이 실패한다. |
| `QualityTrustContext` | 독립 trust document의 root와 평가 fixture의 raw preimage 및 source metadata registry를 함께 검증한 뒤 내부 issuer가 발급한다. artifact에 raw preimage를 저장하지 않는다. |
| `SourceMetadataRegistry` | trusted root가 source ID, provenance/quality kind, reliability, family, capabilities, coverage, canonical host, cache upstream source ID를 고정한다. |
| `subject` | ticker, market, company name, query label을 포함한다. |
| `normalized_record` | typed `quality_claim`에서 subject, event date, canonical URL/title, predicate, object, polarity, numeric consistency, claim text, untrusted text를 결정적으로 파생한다. caller override는 없다. |

`fetched_at`은 freshness의 보조 값일 뿐이다. 웹 검색처럼 publish date가 없으면 `as_of.kind="unknown"`, `freshness_label="degraded"`, `quality_label="degraded"`를 써야 한다.

동일 `provenance_hash`는 alias나 record ID가 달라도 한 번만 입력할 수 있다. source family, reliability class, source kind를 바꿔 독립 cluster를 늘리는 입력은 각각 `PROVENANCE_REUSED`, `SOURCE_REGISTRY_INVALID`, `SOURCE_METADATA_MISMATCH`로 fail closed한다. Session `as_of`는 PRD 01의 IANA timezone을 `ZoneInfo`로 해석한다.

## Freshness SLA and TTL

Freshness는 source kind와 사용 목적별 SLA로 판정한다. SLA 안에 있어도 품질이 자동으로 높아지지는 않는다.

| source kind | current use SLA | audit TTL | expired after | required fallback rule |
| --- | ---: | ---: | ---: | --- |
| `market_price` | 30 minutes during market hours | 24 hours | 48 hours | stale이면 가격 판단에 쓰지 않고 최신 가격 source를 다시 요청한다. |
| `fundamental_equity` | 168 hours | 720 hours | 2160 hours | stale이면 valuation 설명은 가능하지만 신규 확신 근거로 쓰지 않는다. |
| `news_search` | 168 hours | 720 hours | 2160 hours | stale이면 fallback query를 허용하되 fallback도 같은 계약을 통과해야 한다. |
| `web_context` | 168 hours | 720 hours | 2160 hours | publish date 결측이면 degraded로 남기고 사실 근거 승격을 막는다. |
| `macro_timeseries` | 24 hours for daily release, 720 hours for monthly release | 2160 hours | 4320 hours | release calendar가 없으면 degraded다. |
| `local_cache` | upstream SLA를 상속 | upstream TTL을 상속 | upstream expiry를 상속 | upstream provenance가 없으면 fallback 금지다. |

Freshness label:

| label | required meaning | consumer rule |
| --- | --- | --- |
| `fresh` | `as_of`가 current use SLA 안에 있고 timestamp order가 유효하다. | Current decision context에 들어갈 수 있다. |
| `stale` | Current use SLA를 넘었지만 audit TTL 안에 있다. | 사용자에게 stale로 표시한다. Fresh count에 넣지 않는다. |
| `expired` | Audit TTL 또는 expired after를 넘었다. | Current decision context에 넣지 않는다. |
| `degraded` | Publish date, upstream provenance, release calendar, 또는 source timestamp가 불충분하다. | 설명에는 남길 수 있지만 사실 근거로 승격하지 않는다. |
| `missing` | 필수 timestamp 또는 source ref가 없다. | Quality result를 만들지 않는다. |

## Dedup Clustering

Dedup은 같은 사실을 여러 결과가 반복하는 문제를 줄인다. 중복 제거 뒤 남는 것은 대표 record와 독립 근거 수다.

Dedup key는 canonical JSON으로 만든 뒤 `sha256:<64hex>`로 저장한다.

```json
{
  "dedup_key_input": {
    "subject_id": "KR:005930",
    "event_date": "2026-08-04",
    "source_family": "msn_representation",
    "canonical_url_host": "msn.com",
    "canonical_title": "samsung electronics sk hynix hbm price target condition",
    "claim_fingerprint": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  },
  "dedup_key": "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
}
```

Clustering rules:

| component | rule |
| --- | --- |
| `subject_id` | market namespace와 ticker를 함께 쓴다. 회사명만 쓰지 않는다. |
| `event_date` | publish date 또는 claim 기준일. 없으면 `unknown`이며 cluster confidence를 낮춘다. |
| `source_family` | 같은 원문 syndication, repost, mirror, social repost를 묶는 family. |
| `canonical_url_host` | tracking query 제거 후 host를 정규화한다. |
| `canonical_title` | lowercase, whitespace collapse, punctuation strip, common ticker suffix 제거. |
| `claim_fingerprint` | 핵심 claim text를 redaction 후 hash한다. Raw snippet을 key에 직접 넣지 않는다. |

Duplicate cluster label:

| label | meaning |
| --- | --- |
| `unique` | 같은 claim cluster가 없다. |
| `representative` | cluster 대표 record다. |
| `duplicate` | 대표 record와 같은 claim이다. Independent evidence count에 넣지 않는다. |
| `near_duplicate` | 제목이나 claim이 거의 같지만 source family가 다르다. Reliability 계산에서 낮은 가중치를 쓴다. |

## Quality Score Components

Quality score는 0부터 100까지의 설명 가능한 값이다. Count 기반 보너스는 없다.

| component | max points | required evidence |
| --- | ---: | --- |
| `freshness_fit` | 20 | SLA 판정, `as_of`, `fetched_at`, TTL. |
| `source_reliability` | 20 | source kind, source family, primary 원문 여부, redistribution boundary. |
| `factuality_support` | 25 | 독립 cluster의 같은 claim 지지, 숫자와 날짜 일치, 원문 hash 연결. |
| `contradiction_risk` | 20 | 같은 subject와 event date에서 반대 claim 탐지. 낮을수록 점수가 높다. |
| `dedup_integrity` | 10 | 대표 record, duplicate 수, independent evidence count 재계산. |
| `prompt_safety` | 5 | untrusted text flag, injection phrase 차단, redaction report 연결. |

Quality label:

| label | score range | rule |
| --- | --- | --- |
| `high` | 80 to 100 | Fresh 또는 SLA에 맞고, 독립 cluster가 있고, contradiction이 없다. |
| `usable` | 60 to 79 | 일부 약점이 있지만 current context에 제한적으로 쓸 수 있다. |
| `degraded` | 30 to 59 | stale, missing publish date, 낮은 reliability, 또는 near duplicate 의존이 있다. |
| `blocked` | 0 to 29 | malformed, contradiction unresolved, prompt injection, secret leakage, provenance missing 중 하나다. |

`quality_score`는 사람이 쓴 숫자를 믿지 않는다. Parser가 component evidence에서 다시 계산한다.

## Factuality and Reliability

Factuality는 claim 단위로 기록한다.

| field | rule |
| --- | --- |
| `claim_id` | subject, predicate, object, event date, source ref hash로 만든 deterministic ID. |
| `claim_text_hash` | redacted claim text hash. Raw external text는 저장하지 않는다. |
| `supporting_cluster_ids[]` | 같은 claim을 지지하는 대표 cluster ID 목록. |
| `opposing_cluster_ids[]` | 같은 subject와 event date에서 반대 claim을 담은 cluster ID 목록. |
| `numeric_consistency` | 숫자, 단위, 통화, 날짜가 일치하는지 `match`, `range_match`, `mismatch`, `not_applicable` 중 하나. |
| `source_reliability_class` | `primary_disclosure`, `exchange_or_regulator`, `wire_or_major_media`, `broker_research`, `syndicated_media`, `social_or_video`, `unknown`. |

Reliability class는 품질 점수의 입력일 뿐이다. 유명 domain도 stale이거나 contradictory이면 high quality가 될 수 없다.

## Contradiction Handling

Contradiction은 같은 subject와 event date에서 동시에 참일 수 없는 claim이 있을 때 생긴다.

| contradiction type | example | required result |
| --- | --- | --- |
| `numeric_conflict` | 같은 날 목표주가가 `391200`과 `570000`으로 원문 없이 섞임. | `quality_label="blocked"` 또는 사람이 확인할 때까지 `degraded`. |
| `direction_conflict` | 같은 기간 기관 순매수를 순매도라고도 말함. | Opposing clusters를 남기고 factual claim 승격 금지. |
| `date_conflict` | 오래된 실적 전망을 최신 발표처럼 표시함. | Stale 또는 degraded로 낮춘다. |
| `subject_conflict` | 삼성전자 검색에서 한국전력 목표주가를 근거로 씀. | Dirty input으로 fail. |

Contradiction이 있으면 fallback source를 읽을 수 있다. Fallback은 기존 result를 덮어쓰지 않는다. 새 source ref, freshness label, quality label, contradiction link를 가진 별도 artifact로 남긴다.

## Stale, Degraded, and Fallback

| condition | result label | fallback allowed | consumer rule |
| --- | --- | --- | --- |
| SLA 안이고 contradiction 없음 | `fresh` plus `high` or `usable` | optional | Current context에 쓸 수 있다. |
| SLA 초과, audit TTL 안 | `stale` plus `degraded` | yes | Fresh summary에 넣지 않는다. |
| Publish date 결측 | `degraded` plus `degraded` | yes | Date-bound claim으로 쓰지 않는다. |
| Expired | `expired` plus `blocked` | yes | Current context에서 제외한다. |
| Fallback success | fallback의 자체 label 사용 | no chained fallback without reason | 원본과 fallback을 둘 다 표시한다. |
| Fallback fail | 원본 label 유지 | no | 실패를 성공처럼 덮지 않는다. |

Fallback은 안전한 대체가 아니라 새 입력이다. 원본보다 품질이 높아도 원본의 stale, dirty, contradiction 흔적은 audit trail에 남아야 한다.

## Machine-readable Fixture

아래 JSON은 원문 authoring 예시다. 실행 가능한 canonical v2 평가 fixture는 [`prd02-quality-freshness-dedup.json`](../fixtures/prd02-quality-freshness-dedup.json), 독립 root 경계는 [`prd02-quality-freshness-dedup-trust.json`](../fixtures/prd02-quality-freshness-dedup-trust.json)이다. `verify-fixture`, `build`, persisted `verify`는 두 파일을 별도 경로에서 읽는다.

```json
{
  "schema_version": "v7.quality_freshness_dedup.prd02.1",
  "contract_id": "quality_freshness_dedup_prd02",
  "score_components": {
    "freshness_fit": 20,
    "source_reliability": 20,
    "factuality_support": 25,
    "contradiction_risk": 20,
    "dedup_integrity": 10,
    "prompt_safety": 5
  },
  "freshness_sla_hours": {
    "market_price": 0.5,
    "fundamental_equity": 168,
    "news_search": 168,
    "web_context": 168,
    "macro_timeseries_daily": 24,
    "macro_timeseries_monthly": 720
  },
  "audit_ttl_hours": {
    "market_price": 24,
    "fundamental_equity": 720,
    "news_search": 720,
    "web_context": 720,
    "macro_timeseries": 2160
  },
  "happy_duplicate_cluster_fixture": {
    "quality_result_id": "qfd_v7_005930_cluster_001",
    "subject": {"market": "KR", "ticker": "005930", "name_hash": "sha256:1111111111111111111111111111111111111111111111111111111111111111"},
    "generated_at": "2026-08-06T09:30:00+09:00",
    "source_refs": [
      {
        "provenance_hash": "sha256:2222222222222222222222222222222222222222222222222222222222222222",
        "adapter_id": "web_context",
        "source_kind": "news_search",
        "as_of": {"kind": "published_at", "value": "2026-08-04T08:27:34+00:00"},
        "fetched_at": "2026-08-05T17:27:33+09:00",
        "untrusted_text_hash": "sha256:3333333333333333333333333333333333333333333333333333333333333333"
      },
      {
        "provenance_hash": "sha256:4444444444444444444444444444444444444444444444444444444444444444",
        "adapter_id": "web_context",
        "source_kind": "news_search",
        "as_of": {"kind": "published_at", "value": "2026-08-04T08:27:34+00:00"},
        "fetched_at": "2026-08-05T17:27:33+09:00",
        "untrusted_text_hash": "sha256:5555555555555555555555555555555555555555555555555555555555555555"
      }
    ],
    "clusters": [
      {
        "cluster_id": "cluster_kr_005930_hbm_20260804",
        "dedup_key": "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        "representative_ref": "sha256:2222222222222222222222222222222222222222222222222222222222222222",
        "duplicate_refs": ["sha256:4444444444444444444444444444444444444444444444444444444444444444"],
        "independent_evidence_count": 1,
        "duplicate_count": 1,
        "cluster_label": "representative"
      }
    ],
    "claims": [
      {
        "claim_id": "claim_kr_005930_hbm_condition_20260804",
        "claim_text_hash": "sha256:6666666666666666666666666666666666666666666666666666666666666666",
        "supporting_cluster_ids": ["cluster_kr_005930_hbm_20260804"],
        "opposing_cluster_ids": [],
        "numeric_consistency": "not_applicable",
        "source_reliability_class": "syndicated_media"
      }
    ],
    "freshness_label": "fresh",
    "quality_label": "usable",
    "quality_score": 72,
    "score_breakdown": {
      "freshness_fit": 20,
      "source_reliability": 10,
      "factuality_support": 17,
      "contradiction_risk": 20,
      "dedup_integrity": 5,
      "prompt_safety": 0
    },
    "summary": {
      "raw_result_count": 2,
      "cluster_count": 1,
      "independent_evidence_count": 1,
      "fresh_count": 1,
      "quality_count": 1
    },
    "fallback": null,
    "result_label": "pass"
  },
  "failure_fixtures": [
    {
      "fixture": "stale_article_mislabeled_fresh",
      "mutation": "set as_of older than news_search SLA while freshness_label remains fresh",
      "expected_result_label": "fail",
      "expected_error_code": "STALE_MISLABELED_FRESH"
    },
    {
      "fixture": "contradictory_price_target",
      "mutation": "add opposing claim with same subject and event date while quality_label remains high",
      "expected_result_label": "fail",
      "expected_error_code": "CONTRADICTION_UNRESOLVED"
    }
  ],
  "required_mutations": [
    "json_field_removal",
    "dedup_key_hash_mismatch",
    "raw_count_used_as_quality",
    "stale_mislabeled_fresh",
    "dirty_subject_mismatch",
    "misleading_fresh_count",
    "malformed_json",
    "prompt_injection_trusted_text"
  ]
}
```

## Happy Trace: Duplicate Cluster

1. Parser receives two web context source refs for `KR:005930` with the same event date and same claim fingerprint.
2. Both refs point to PRD 01 provenance hashes and keep title and snippet as untrusted text hashes.
3. Canonical dedup input produces the same `dedup_key` for both refs.
4. Parser creates one cluster, picks one representative, marks the other ref as duplicate, and sets `independent_evidence_count=1`.
5. Freshness is fresh because `as_of` is inside the `news_search` SLA.
6. Quality is usable, not high, because the source class is syndicated media and prompt safety gets no bonus from raw snippet count.
7. Summary keeps `raw_result_count=2` separate from `quality_count=1`.

## Failure Fixtures

### Stale Article Mislabel

If `as_of` is older than the `news_search` SLA but `freshness_label="fresh"`, parser returns `STALE_MISLABELED_FRESH`. The article can remain in audit TTL if allowed, but it cannot enter fresh context and cannot increase `fresh_count`.

### Contradiction Not Resolved

If the same subject and event date has opposing clusters, parser returns `CONTRADICTION_UNRESOLVED` when `quality_label="high"` or `result_label="pass"` hides the conflict. The claim must be degraded or blocked until a separate source resolves the conflict.

## Parser and Mutation Requirements

Parser must read every fenced JSON block in this PRD and run these in-memory mutations.

| probe | mutation | expected result |
| --- | --- | --- |
| `json_field_removal` | Remove `source_refs`, `clusters`, `claims`, `freshness_label`, or `quality_label`. | fail with missing field. |
| `dedup_key_hash_mismatch` | Change one dedup input while keeping the same `dedup_key`. | fail with hash mismatch. |
| `raw_count_used_as_quality` | Set `quality_score` higher only because `raw_result_count` increased. | fail with `COUNT_USED_AS_QUALITY`. |
| `stale` | Move `as_of` outside SLA while keeping `freshness_label="fresh"`. | fail with `STALE_MISLABELED_FRESH`. |
| `dirty` | Add a claim about another subject to a `KR:005930` cluster. | fail with `DIRTY_SUBJECT_MISMATCH`. |
| `misleading` | Count stale or duplicate refs in `summary.fresh_count` or `summary.quality_count`. | fail with `MISLEADING_SUMMARY`. |
| `malformed` | Use invalid JSON, NaN, Infinity, duplicate key, bad timestamp, or string where object is required. | fail with `MALFORMED_QUALITY_PAYLOAD`. |
| `prompt_injection` | Mark external title or snippet containing instruction-like text as trusted. | fail with `UNTRUSTED_TEXT_PROMPT_INJECTION`. |

## Acceptance Criteria

1. The document has draft metadata directly under the title and no done marker.
2. It defines freshness SLA, TTL, duplicate clustering, dedup key, quality score components, factuality, reliability, contradiction, stale behavior, degraded behavior, and fallback behavior.
3. It says that search result count is not quality and keeps raw result count separate from independent evidence count.
4. It includes a parseable JSON fixture with a duplicate cluster happy path and stale plus contradiction failure fixtures.
5. It requires JSON parsing and mutations for stale, dirty, misleading, malformed, prompt injection, dedup hash mismatch, field removal, and count-as-quality misuse.
6. It does not read or expose config, secret, token, cookie, account, or credential material.

## Evidence Requirement

The exact evidence artifact for this authoring task is `.omo/evidence/trading-oracle-v4-v9-specs-20260806/task-21-trading-oracle-v4-measurement-attribution.md`. The evidence must record failing-first target absence, manual Read of this PRD, JSON parser checks, fixture mutations, and the no secret-read boundary.
