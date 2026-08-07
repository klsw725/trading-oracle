# PRD 04: Promotion Retirement
> **상태**: ✅ 구현 완료 (offline source lifecycle policy compiler, 71/71 acceptance)

Parent SPEC: [v7 Information Source Expansion SPEC](../SPEC.md)

## 문서 범위

이 문서는 PRD 01 provenance, PRD 02 quality, PRD 03 incremental value report를 통과한 source bundle이 운영 정책으로 승격되고, 장애나 계약 만료 때 비활성화되며, 더는 쓰지 않는 source가 폐기되는 lifecycle 계약을 정의한다.

현재 `src/data/web_search.py`는 `web_search.enabled`, `cache_ttl_hours`, `searched_at`, `gate_stats`, `title`, `snippet`, `date`, `url`을 사용한다. 하지만 어떤 source가 기본 경로가 되는지, traffic을 얼마나 받을 수 있는지, fallback이 어떤 순서로 일어나는지, 장애 때 즉시 끄는지, 계약 만료와 cache 무효화가 어떻게 연결되는지는 별도 계약으로 남아 있지 않다.

이 문서는 source를 더 많이 붙이는 문서가 아니다. 검증된 source만 작게 열고, 나쁜 source는 지체 없이 닫고, 닫힌 source의 cache가 fresh처럼 보이지 않게 하는 정책 문서다.

## 목표

1. Source promotion에 필요한 입력 hash, owner 승인, traffic share, 관찰 창을 고정한다.
2. Fallback order를 vendor 선호가 아니라 lifecycle state, quality, value, freshness, contract 상태로 계산하게 한다.
3. 장애, severe harm, prompt injection, secret leakage, contract expiry가 생기면 즉시 disable되게 한다.
4. Retirement와 cache invalidation을 감사 가능한 정책 변경으로 남긴다.
5. State, hash, stale cache, interruption mutation만으로 parser와 fixture 검증을 할 수 있게 한다.

## 비목표

1. PRD 01 provenance, PRD 02 quality, PRD 03 value metric을 다시 정의하지 않는다.
2. 특정 vendor, 검색 엔진, broker API, finance library, 유료 source를 기본값으로 정하지 않는다.
3. Production config, prompt, scorer, cache 파일, data 파일을 수정하지 않는다.
4. 작은 표본의 value pass, stale quality result, 수동 선호만으로 source를 승격하지 않는다.
5. 장애가 난 source를 fallback 성공으로 숨기지 않는다.

## 입력 계약

Promotion policy는 아래 입력만 소비한다.

| input | required | rule |
| --- | --- | --- |
| `promotion_request` | yes | source bundle ID, requested state, requested traffic share, owner, reason을 가진다. |
| `source_bundle_manifest` | yes | PRD 01 provenance hash 목록, PRD 02 quality hash 목록, source capabilities, market coverage, contract metadata hash를 가진다. |
| `incremental_value_report` | yes | PRD 03 report hash와 `PASS_INCREMENTAL_VALUE_EVALUATION` code를 가진다. |
| `current_policy_snapshot` | yes | 현재 lifecycle state, traffic share, fallback order, cache generation, state hash를 가진다. |
| `incident_report` | optional | 장애, severe harm, secret leakage, prompt injection, outage, contract breach를 기록한다. |
| `owner_approval` | yes for promotion | accountable owner, reviewer, approval timestamp, expiry review date를 가진다. |
| `source_trust_document` | yes | fixture와 별도 저장하며 PRD03 trust document hash, source bundle, 초기 policy/registry, contract, owner approval, fallback 후보, incident authorization을 고정한다. |
| `prd03_fixture_and_trust` | yes | 별도 경로에서 로드하며 PRD01/02 lineage와 PRD03 value artifact를 독립적으로 다시 계산한다. |

PRD 03 pass가 없으면 source policy는 no-op이다. PRD 03 pass가 있더라도 PRD 01 또는 PRD 02 hash가 바뀌었거나 stale이면 no-op이다.

Lifecycle compiler와 standalone artifact verifier는 fixture 내부 authority를 신뢰하지 않는다. 별도로 로드한 PRD04 trust document가 PRD03 trust document의 canonical hash와 source bundle, 초기 policy/registry를 고정하고, PRD03 fixture와 trust에서 PRD01 provenance, PRD02 source metadata/capability/quality, PRD03 outcome/value/risk를 다시 계산한다. Fixture와 하위 trust 입력을 함께 바꾸더라도 PRD04 trust hash가 일치하지 않으면 `SOURCE_TRUST_MISMATCH`다. Incident operation은 issued context에 고정된 `(incident_code, evidence_hash, source_bundle_id)` authorization과 정확히 일치해야 한다.

## Lifecycle State

| state | meaning | traffic rule | fallback rule |
| --- | --- | --- | --- |
| `candidate` | Source bundle이 식별됐지만 운영 traffic을 받지 않는다. | `0.00` | fallback 대상이 아니다. |
| `shadow` | Fetch와 quality check만 실행하고 사용자 판단에는 넣지 않는다. | `0.00` | fallback 대상이 아니다. |
| `canary` | 작은 traffic에서 prompt eligible이 될 수 있다. | 정확히 `0.05` | 같은 capability의 primary 실패 때만 후보가 된다. |
| `limited` | 검증된 시장, action, horizon에서만 쓴다. | `0.05` to `0.50` | primary 다음 후보가 될 수 있다. |
| `primary` | 해당 capability의 기본 source 후보가 된다. | `0.50` to `1.00` | fallback chain의 첫 유효 후보가 된다. |
| `disabled` | 장애나 정책 위반으로 즉시 닫힌 상태다. | `0.00` | fallback 대상이 아니다. |
| `retiring` | 새 decision에는 쓰지 않고 audit TTL만 유지한다. | `0.00` | fallback 대상이 아니다. |
| `retired` | 운영과 audit current context에서 제거됐다. | `0.00` | fallback 대상이 아니다. |
| `expired` | 계약, license, auth boundary, data permission이 만료됐다. | `0.00` | fallback 대상이 아니다. |

State transition은 단방향이 기본이다. `disabled`, `retired`, `expired`에서 다시 traffic을 받으려면 새 source bundle ID, 새 PRD 01 hash, 새 PRD 02 hash, 새 PRD 03 report hash, 새 owner approval이 필요하다.

## Source Promotion

Promotion은 아래 gate를 모두 통과해야 한다.

| gate | required rule |
| --- | --- |
| `value_gate` | PRD 03 report code가 `PASS_INCREMENTAL_VALUE_EVALUATION`이다. |
| `quality_gate` | 모든 prompt eligible source ref가 PRD 02 `fresh` plus `usable` 이상이다. |
| `provenance_gate` | 모든 source ref가 PRD 01 hash, as-of, retention, license, auth boundary를 가진다. |
| `sample_gate` | PRD 03 minimum sample no-op이 아니다. |
| `harm_gate` | Severe harm, prompt injection, secret leakage, stale freshness mislabel이 없다. |
| `owner_gate` | accountable owner와 reviewer가 있고 expiry review date가 있다. |
| `state_hash_gate` | 현재 policy snapshot hash가 request의 `previous_policy_hash`와 일치한다. |

Traffic share는 점진적으로만 늘린다.

| step | allowed state | max share | required observation |
| --- | --- | ---: | --- |
| `shadow_check` | `shadow` | `0.00` | quality, cost, latency, cache generation이 기록된다. |
| `canary_5` | `canary` | `0.05` | 장애, severe harm, timeout spike가 없다. |
| `limited_25` | `limited` | `0.25` | PRD 03 harm threshold를 계속 만족한다. |
| `limited_50` | `limited` | `0.50` | coverage와 stale cache rate가 threshold 안에 있다. |
| `primary_100` | `primary` | `1.00` | owner review와 audit log가 닫힌다. |

단계를 건너뛰면 parser는 `ILLEGAL_PROMOTION_JUMP`를 반환한다. Emergency disable은 예외다. 장애와 정책 위반은 언제든 `disabled`로 즉시 이동한다.

각 promotion step의 required observation은 최소 100 attempts를 포함해야 한다. 그보다 작으면 traffic을 늘리지 않고 현재 안전 상태를 유지한다.

## Traffic and Fallback

Traffic share는 source가 prompt eligible이 되는 비율이다. Fetch traffic과 prompt traffic을 같은 값으로 보지 않는다. Shadow state는 fetch는 할 수 있지만 prompt에는 들어가지 않는다.

Fallback order는 아래 정렬 key로 계산한다.

1. `state_rank`: `primary`, `limited`, `canary` 순서다.
2. `capability_match`: 요청한 capability, market, exchange, symbol namespace가 일치해야 한다.
3. `freshness_rank`: fresh가 stale보다 앞선다. Expired와 missing은 제외한다.
4. `quality_rank`: high, usable 순서다. Degraded는 current decision fallback이 아니다.
5. `value_rank`: PRD 03 cohort가 같은 market, action, horizon에 가까울수록 앞선다.
6. `cost_latency_rank`: threshold 안에서 낮은 운영 비용이 앞선다.

모든 정렬 key가 같으면 `source_bundle_id` 오름차순으로 결정한다. 이 tie-break는 fixture 입력 순서와 무관하다.

현재 평가 중인 `source_bundle_id`는 자신의 fallback order에서 제외한다. Persisted fallback projection은 eligible 후보의 canonical order와 정확히 같아야 하며, 길이가 짧거나 길면 `FALLBACK_ORDER_MISMATCH`, 동일 key 후보의 순서만 바뀌면 `FALLBACK_TIE_BREAK_MISMATCH`다.

Fallback은 원본 실패를 덮어쓰지 않는다. Current decision에 fallback source를 쓰면 audit log에 원본 source state, 실패 code, fallback source bundle ID, fallback reason, cache generation을 같이 남긴다.

## Incident Disable

아래 조건은 즉시 disable이다.

| incident | required action |
| --- | --- |
| `secret_leakage` | source state를 `disabled`로 바꾸고 prompt eligibility를 `0.00`으로 만든다. |
| `prompt_injection_trusted` | source state를 `disabled`로 바꾸고 affected cache generation을 invalid로 표시한다. |
| `severe_harm_breach` | source state를 `disabled`로 바꾸고 fallback order에서 제거한다. |
| `contract_expired` | source state를 `expired`로 바꾸고 current cache를 invalid로 표시한다. |
| `auth_boundary_breach` | source state를 `disabled`로 바꾸고 credential material은 audit log에 쓰지 않는다. |
| `stale_cache_served_as_fresh` | source state를 `disabled`로 바꾸고 stale cache purge를 요구한다. |
| `source_outage_masked_as_success` | source state를 `disabled`로 바꾸고 misleading success를 fail로 기록한다. |

Immediate disable은 owner approval을 기다리지 않는다. Owner와 reviewer는 사후 audit에 서명한다. Disable 후 traffic share가 `0.00`이 아니면 parser는 `DISABLE_TRAFFIC_NOT_ZERO`를 반환한다.

## Contract Expiry and Retirement

Contract metadata는 raw 계약서나 secret을 담지 않고 hash와 날짜만 기록한다.

| field | rule |
| --- | --- |
| `contract_ref_hash` | redacted contract metadata hash다. |
| `license_scope` | redistribution, internal use, hash-only, prompt eligibility boundary를 적는다. |
| `valid_from` | source permission 시작 시각이다. |
| `valid_until` | source permission 종료 시각이다. Null이면 expiry review date가 필수다. |
| `expiry_review_at` | owner가 재검토해야 하는 시각이다. |
| `retirement_reason` | `contract_expired`, `replaced_by_better_source`, `harmful`, `no_incremental_value`, `coverage_lost`, `owner_request` 중 하나다. |

`valid_until`이 지났거나 license scope가 current prompt use를 명시적으로 허용하지 않으면 source는 `expired`다. `hash_only`와 같이 hash 보존만 허용하는 scope는 promotion traffic을 열 수 없다. Expired source는 audit hash chain에는 남지만 current prompt, fallback, fresh count, quality count에 들어갈 수 없다.

Contract expiry와 voluntary retirement 조건이 동시에 성립하면 `expired` 전이를 먼저 적용한 뒤 `expired -> retired` 순서로 닫는다.

Retirement는 새 decision traffic을 먼저 `0.00`으로 만든 뒤 cache invalidation을 수행한다. Audit TTL 안의 과거 artifact는 삭제하지 않는다. 삭제 대신 current eligibility를 닫고 retention rule에 맞는 hash만 남긴다.

Voluntary retirement는 `canary`, `limited`, `primary`에서 `retiring`으로 이동한 뒤 두 번째 retirement operation으로 `retired`가 된다. Artifact terminal code는 operation 종류가 아니라 최종 state와 contract-expiry history에서 계산한다.

## Cache Invalidation

Cache invalidation은 source lifecycle event와 연결된다.

| trigger | invalidation rule |
| --- | --- |
| promotion state change | 새 `cache_generation`을 만들고 이전 generation은 audit-only로 둔다. |
| traffic share increase | prompt eligible cache는 새 policy hash와 source bundle hash를 포함해야 한다. |
| incident disable | affected source bundle cache를 current decision에서 즉시 제외한다. |
| contract expiry | expiry 이후 fetched cache를 invalid로 표시한다. |
| retirement | current cache index에서 제거하고 retention hash만 남긴다. |
| stale cache served as fresh | source를 disable하고 stale generation을 purge required로 표시한다. |

Cache entry는 `policy_hash`, `source_bundle_hash`, `quality_result_hash`, `cache_generation`, `as_of`, `fetched_at`, `freshness_label`을 가져야 current context에 들어갈 수 있다. 하나라도 없으면 `CACHE_POLICY_HASH_MISSING` 또는 `STALE_CACHE_POLICY_MISMATCH`다.

## Owner and Audit Log

각 policy change는 owner와 audit log를 가진다.

| field | required rule |
| --- | --- |
| `accountable_owner` | 개인명 대신 role label을 쓴다. 예: `data_source_owner`. |
| `reviewer` | owner와 다른 role label이다. |
| `decision_reason` | promotion, disable, expiry, retirement 이유를 짧게 적는다. |
| `previous_policy_hash` | 변경 전 policy snapshot hash다. |
| `new_policy_hash` | 변경 후 policy snapshot hash다. |
| `audit_event_hash` | audit event에서 자기 hash를 제외하고 계산한다. |
| `interrupted_transition` | 전환 중단 여부다. 중단이면 traffic share는 이전 안전 상태나 `0.00`이어야 한다. |

Audit log는 raw external text, secret, token, cookie, 계좌 정보, 사용자 prompt 원문을 담지 않는다. Incident audit도 credential 원문을 기록하지 않는다.

Interrupted operation은 checkpoint만 남기고 policy, registry, history, ledger, cache, fallback projection을 변경하지 않는다. Persisted artifact verification은 trusted context에서 전체 operation을 처음부터 replay하고 history, ledger, checkpoint, cache, fallback, final policy가 모두 같은지 비교한다.

Idempotent retry는 `operation_id`, `idempotency_key`, canonical `operation_hash`가 모두 기존 audit event와 같을 때만 no-op이다. 같은 ID나 key로 payload를 바꾸면 `DUPLICATE_OPERATION_CONFLICT`다.

## Machine-readable Fixture

```json
{
  "schema_version": "v7.promotion_retirement.prd04.1",
  "contract_id": "promotion_retirement_prd04",
  "state_order": ["candidate", "shadow", "canary", "limited", "primary", "disabled", "retiring", "retired", "expired"],
  "traffic_steps": {
    "shadow_check": "0.00",
    "canary_5": "0.05",
    "limited_25": "0.25",
    "limited_50": "0.50",
    "primary_100": "1.00"
  },
  "happy_gradual_promotion_fixture": {
    "policy_event_id": "prom_v7_filing_source_001",
    "source_bundle_id": "filing_source_bundle_v1",
    "previous_policy_hash": "sha256:1111111111111111111111111111111111111111111111111111111111111111",
    "source_bundle_hash": "sha256:2222222222222222222222222222222222222222222222222222222222222222",
    "incremental_value_report_hash": "sha256:3333333333333333333333333333333333333333333333333333333333333333",
    "incremental_value_code": "PASS_INCREMENTAL_VALUE_EVALUATION",
    "quality_result_hashes": ["sha256:4444444444444444444444444444444444444444444444444444444444444444"],
    "provenance_hashes": ["sha256:5555555555555555555555555555555555555555555555555555555555555555"],
    "owner_approval": {
      "accountable_owner": "data_source_owner",
      "reviewer": "risk_reviewer",
      "approved_at": "2026-08-06T10:00:00+09:00",
      "expiry_review_at": "2026-11-06T10:00:00+09:00"
    },
    "transitions": [
      {"from": "candidate", "to": "shadow", "traffic_share": "0.00", "cache_generation": 1},
      {"from": "shadow", "to": "canary", "traffic_share": "0.05", "cache_generation": 2},
      {"from": "canary", "to": "limited", "traffic_share": "0.25", "cache_generation": 3},
      {"from": "limited", "to": "limited", "traffic_share": "0.50", "cache_generation": 4},
      {"from": "limited", "to": "primary", "traffic_share": "1.00", "cache_generation": 5}
    ],
    "fallback_order": [
      {"rank": 1, "source_bundle_id": "filing_source_bundle_v1", "state": "primary", "quality_label": "high", "freshness_label": "fresh"},
      {"rank": 2, "source_bundle_id": "exchange_backup_bundle_v1", "state": "limited", "quality_label": "usable", "freshness_label": "fresh"}
    ],
    "cache_policy": {
      "cache_generation": 5,
      "policy_hash": "sha256:6666666666666666666666666666666666666666666666666666666666666666",
      "stale_generations_invalidated": [1, 2, 3, 4],
      "current_cache_requires_policy_hash": true
    },
    "contract": {
      "contract_ref_hash": "sha256:7777777777777777777777777777777777777777777777777777777777777777",
      "license_scope": "internal_prompt_eligible_hash_only",
      "valid_from": "2026-08-06T00:00:00+09:00",
      "valid_until": "2026-11-06T00:00:00+09:00"
    },
    "audit_event_hash": "sha256:8888888888888888888888888888888888888888888888888888888888888888",
    "expected_code": "PROMOTION_ACCEPTED_GRADUAL"
  },
  "failure_immediate_disable_fixture": {
    "policy_event_id": "disable_v7_prompt_injection_001",
    "source_bundle_id": "web_context_bundle_v1",
    "previous_state": "limited",
    "previous_traffic_share": "0.25",
    "incident_report": {
      "incident_code": "prompt_injection_trusted",
      "severity": "critical",
      "detected_at": "2026-08-06T11:00:00+09:00",
      "evidence_hash": "sha256:9999999999999999999999999999999999999999999999999999999999999999"
    },
    "new_state": "disabled",
    "new_traffic_share": "0.00",
    "fallback_removed": true,
    "cache_policy": {
      "cache_generation": 8,
      "invalidated_source_bundle_hash": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "current_decision_allowed": false,
      "purge_required": true
    },
    "owner_post_audit_required": true,
    "expected_code": "SOURCE_DISABLED_IMMEDIATELY"
  },
  "failure_fixtures": [
    {
      "fixture": "illegal_state_jump",
      "mutation": "move candidate directly to primary with traffic 1.00",
      "expected_code": "ILLEGAL_PROMOTION_JUMP"
    },
    {
      "fixture": "hash_mismatch_policy",
      "mutation": "change previous_policy_hash after approval",
      "expected_code": "POLICY_HASH_MISMATCH"
    },
    {
      "fixture": "stale_cache_allowed",
      "mutation": "keep disabled source cache current with old cache_generation",
      "expected_code": "STALE_CACHE_POLICY_MISMATCH"
    },
    {
      "fixture": "interrupted_transition_open_traffic",
      "mutation": "mark transition interrupted while traffic_share remains 0.25",
      "expected_code": "INTERRUPTED_TRANSITION_UNSAFE"
    }
  ],
  "required_mutations": [
    "state_transition_illegal",
    "state_disable_traffic_nonzero",
    "hash_mismatch",
    "stale_cache_policy_mismatch",
    "interrupted_transition_unsafe",
    "contract_expired_still_primary",
    "fallback_uses_disabled_source",
    "owner_approval_missing",
    "audit_hash_missing"
  ]
}
```

## Happy Trace: Gradual Promotion

1. Policy parser receives a filing source bundle with PRD 01 provenance hashes, PRD 02 quality hashes, and PRD 03 pass hash.
2. Owner approval names `data_source_owner`, reviewer `risk_reviewer`, and expiry review date.
3. The source starts in `shadow` with prompt traffic `0.00` and a new cache generation.
4. Canary traffic opens at `0.05` after the prior cache generation becomes audit-only.
5. Limited traffic moves through `0.25` and `0.50` only while harm, stale cache, timeout, contract, and quality checks stay valid.
6. Primary traffic reaches `1.00` only after the policy hash, source bundle hash, cache generation, fallback order, owner approval, and audit event hash all match.
7. The parser returns `PROMOTION_ACCEPTED_GRADUAL`.

## Failure Trace: Immediate Disable

If a trusted prompt injection incident is detected while a source has `0.25` traffic, policy changes do not wait for owner approval. The source moves to `disabled`, traffic share becomes `0.00`, fallback order removes the source, current cache is invalidated, and owner post audit is required. If any prompt traffic remains open, parser returns `DISABLE_TRAFFIC_NOT_ZERO`.

## Parser and Mutation Requirements

Parser must read every fenced JSON block in this PRD and run these in-memory mutations.

| probe | mutation | expected result |
| --- | --- | --- |
| `state_transition_illegal` | Move `candidate` directly to `primary`. | `ILLEGAL_PROMOTION_JUMP`. |
| `state_disable_traffic_nonzero` | Set immediate disable traffic to `0.05`. | `DISABLE_TRAFFIC_NOT_ZERO`. |
| `hash_mismatch` | Change `previous_policy_hash`, `source_bundle_hash`, or `quality_result_hashes` after policy hash calculation. | `POLICY_HASH_MISMATCH`. |
| `stale_cache_policy_mismatch` | Let a disabled source keep current cache eligibility. | `STALE_CACHE_POLICY_MISMATCH`. |
| `interrupted_transition_unsafe` | Mark transition interrupted while traffic remains above `0.00`. | `INTERRUPTED_TRANSITION_UNSAFE`. |
| `contract_expired_still_primary` | Put a source past `valid_until` in `primary`. | `CONTRACT_EXPIRED_SOURCE_ACTIVE`. |
| `fallback_uses_disabled_source` | Keep disabled, retired, or expired source in fallback order. | `FALLBACK_USES_INELIGIBLE_SOURCE`. |
| `owner_approval_missing` | Remove owner approval from promotion. | `OWNER_APPROVAL_MISSING`. |
| `audit_hash_missing` | Remove `audit_event_hash` from policy event. | `AUDIT_HASH_MISSING`. |

## Acceptance Criteria

1. The document has draft metadata directly under the title and no done marker.
2. It defines source promotion, traffic share, fallback order, incident disable, contract expiry, retirement, cache invalidation, owner, and audit log.
3. It states that happy path promotion is gradual and that failure path disable is immediate.
4. It includes a parseable JSON fixture with gradual promotion and immediate disable traces.
5. It requires deterministic parser and mutation checks for state, hash, stale cache, interruption, expired contract, disabled fallback, missing owner approval, and missing audit hash.
6. It does not read or expose config, secret, token, cookie, account, or credential material.

Persisted artifact는 다음 명령으로 fixture와 분리해 검증한다.

```bash
uv run scripts/run_source_lifecycle.py verify \
  --artifact /tmp/source-policy.json \
  --fixture docs/specs/v7/fixtures/prd04-promotion-retirement.json \
  --trust docs/specs/v7/fixtures/prd04-promotion-retirement-trust.json \
  --value-fixture docs/specs/v7/fixtures/prd03-incremental-value-evaluation.json \
  --value-trust docs/specs/v7/fixtures/prd03-incremental-value-evaluation-trust.json
```

## Evidence Requirement

The exact evidence artifact for this authoring task is `.omo/evidence/trading-oracle-v4-v9-specs-20260806/task-23-trading-oracle-v4-measurement-attribution.md`. The evidence must record failing-first target absence, manual Read of this PRD, deterministic parser checks, fixture mutations, and the no secret-read boundary.
