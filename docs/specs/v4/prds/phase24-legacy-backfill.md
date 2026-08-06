# PRD: Phase 24 legacy backfill
> **상태**: ✅ 완료
> **SPEC 참조**: [../SPEC.md](../SPEC.md)

## 문제

기존 `data/snapshots/`에는 2026-03-28부터 2026-08-05까지 82개 일별 snapshot 파일이 있다. 이 파일들은 추천 당시의 날짜, 일부 시장 요약, 추천 가격, 합의 결과, 관점별 판단을 담지만 Phase 22, Phase 23, Phase 25가 요구하는 entry session, data cutoff, per-recommendation market context, candidate audit, raw prompt, raw provider output, portfolio state를 담지 않는다.

Phase 24는 이 82개 파일을 v4 native snapshot으로 바꾸지 않는다. 원본은 불변 source로 보존하고, 별도 derived artifact에 감사 가능한 값과 복원 불가능한 값을 분리한다. 결과는 audit-only이며 canonical v4 metric, calibration, adaptive weight, production decision score에 포함하지 않는다.

## 목표

1. 기존 82개 source snapshot을 변경하지 않는 정책을 고정한다.
2. 별도 derived artifact 경로와 source linkage를 정의한다.
3. 필드별 provenance를 `direct`, `derived`, `external_backfill`, `unknown`, `not_applicable`로 표준화한다.
4. backfill 가능한 outcome과 benchmark field, 복원 불가능한 raw prompt, data cutoff, candidate audit, portfolio state를 분리한다.
5. migration tier, eligibility matrix, coverage report schema, deterministic hash, idempotence를 정의한다.
6. rollback이 필요 없는 비파괴 동작과 실패 상태를 명시한다.

## Source immutability

Legacy source set은 `data/snapshots/*.json`이다. 현재 디렉터리 listing 기준 파일 수는 82개다. 이 문서는 대표 파일인 `2026-03-28.json`과 `2026-08-05.json`, snapshot 저장 및 평가 코드, 선행 PRD를 읽고 정책을 작성한다. 모든 82개 파일 본문을 검사했거나 migration했다고 주장하지 않는다.

Source snapshot은 다음 규칙을 따른다.

| 항목 | 정책 |
| --- | --- |
| source path | `data/snapshots/<YYYY-MM-DD>.json` |
| write policy | 절대 수정하지 않는다. 재포맷, 키 추가, migration in place 금지 |
| identity | source path와 source file SHA-256으로 식별한다 |
| retention | 원본은 legacy audit source로 남긴다 |
| canonical v4 eligibility | 불가. Phase 24 derived 결과도 canonical metric에서 제외한다 |

`src/performance/tracker.py`의 기존 `load_snapshot()`은 source JSON을 그대로 읽고, `evaluate_snapshot()`은 현재 조회 시점 가격으로 평가한다. Phase 24 derived artifact는 이 동작을 고치거나 실행하지 않는다. 후속 구현은 기존 평가 결과와 Phase 24 audit backfill을 분리해서 표시해야 한다.

## Artifact paths

Derived output은 source와 다른 경로에만 쓴다.

| artifact | path pattern | 설명 |
| --- | --- | --- |
| per-snapshot derived audit | `data/derived/v4/legacy-backfill/snapshots/<YYYY-MM-DD>.derived.json` | 한 source snapshot에서 생성한 audit-only record |
| coverage report | `data/derived/v4/legacy-backfill/reports/coverage.json` | 82개 source path별 coverage, eligibility, failure state 요약 |
| run manifest | `data/derived/v4/legacy-backfill/manifests/<run_id>.json` | migration policy version, input source hashes, output hashes |
| quarantine report | `data/derived/v4/legacy-backfill/reports/quarantine.json` | malformed source 또는 schema mismatch 목록 |

이 경로들은 계약이다. 이 PRD는 파일을 생성하지 않는다. 구현 때도 `data/snapshots/**`는 읽기 전용이며, 기존 source에 rollback이 필요할 수 있는 변경을 만들면 실패다.

## Provenance vocabulary

모든 derived field는 provenance를 가진다.

| provenance | 의미 | 예 |
| --- | --- | --- |
| `direct` | legacy source에 값이 그대로 존재한다 | `date`, `recommendations.105560.price`, `consensus_verdict` |
| `derived` | legacy source 값만으로 결정적으로 계산된다 | legacy record id, vote total, source section hash |
| `external_backfill` | source 밖의 versioned 시장 데이터로 사후 보강했다 | entry close, exit close, benchmark close, corporate action check |
| `unknown` | 필요하지만 source와 허용된 외부 backfill로 복원할 수 없다 | raw prompt, exact data cutoff, candidate universe |
| `not_applicable` | legacy source에서 의미가 없는 field다 | code-based quant raw provider payload |

`external_backfill`은 source의 결측을 숨기지 않는다. 어떤 adapter, as-of, query timestamp, calendar version, corporate action source를 썼는지 함께 남긴다. 외부 시장 데이터가 없으면 값을 추정하지 않고 `unknown` 또는 실패 상태로 둔다.

## Eligibility policy

Legacy derived records는 audit-only다.

| 소비자 | legacy derived 사용 가능 | 이유 |
| --- | --- | --- |
| Phase 27 outcome replay 감사 화면 | 가능 | 당시 추천과 사후 가격 결과를 분리해 표시할 수 있음 |
| Phase 29 evidence gate coverage | 가능 | legacy coverage, 결측률, blocked reason 보고 가능 |
| canonical v4 decision-quality metric | 불가 | native v4 data cutoff와 market context가 없음 |
| Phase 28 confidence calibration | 불가 | recommendation denominator와 candidate audit이 불완전함 |
| adaptive perspective weights | 불가 | 기존 metric이 최신 종가 평가였고 HOLD 의미도 v4와 다름 |
| production promotion gate | 불가 | audit-only 자료는 릴리스 성과를 증명하지 못함 |

Coverage가 높아도 canonical metric 제외 원칙은 바뀌지 않는다. Legacy backfill은 과거 판단을 이해하기 위한 보조 증거이며, v4 이후 native snapshot과 같은 표본으로 섞으면 실패다.

## Backfillable and non-backfillable fields

### Backfill may fill

아래 값은 source linkage와 외부 데이터 provenance가 충분할 때만 derived artifact에 넣을 수 있다.

| field | 허용 provenance | 조건 |
| --- | --- | --- |
| `legacy.date` | `direct` | source top-level `date` 존재 |
| `legacy.market.kospi`, `legacy.market.kosdaq` | `direct` | source market object 존재 |
| `legacy.recommendation_price` | `direct` | source `price` 존재. Phase 22 entry로 승격 금지 |
| `legacy.consensus` | `direct` | source consensus fields 존재 |
| `legacy.perspectives` | `direct` | source perspectives array 존재 |
| `entry_session_close`, `target_exit_session_close` | `external_backfill` | Phase 22 calendar, price, corporate action provenance 충분 |
| `benchmark_entry_close`, `benchmark_exit_close` | `external_backfill` | Phase 25 benchmark mapping과 close provenance 충분 |
| `gross_absolute_return_N` | `external_backfill` | entry, exit, corporate action basis 충분 |
| `gross_benchmark_excess_return_N` | `external_backfill` | absolute return과 benchmark return 모두 충분 |
| `market_context_guess.exchange` | `derived` 또는 `unknown` | ticker resolver가 결정적으로 식별할 때만 `derived` |

### Backfill must remain unknown

아래 값은 legacy source에서 복원하지 않는다.

| field | required state | 이유 |
| --- | --- | --- |
| `raw_prompt` | `unknown` | source에 저장되지 않음 |
| `prompt_hash` | `unknown` | 원문 prompt가 없으므로 hash 불가 |
| `raw_provider_response` | `unknown` | source는 parsed summary만 저장 |
| `provider_request_id` | `unknown` | source에 없음 |
| `decision_data_cutoff_at` | `unknown` | source date는 cutoff timestamp가 아님 |
| `candidate_universe` | `unknown` | 탈락 후보와 universe hash 없음 |
| `candidate_rejections` | `unknown` | source에 selection denominator 없음 |
| `portfolio_state` | `unknown` | 추천 당시 현금, 보유, sizing input 없음 |
| `risk_state` | `unknown` | 상관, concentration, 현금 하한 상태 없음 |
| `verbatim_replay_eligible` | `false` | raw prompt와 raw provider output이 없음 |

Prompt 또는 secret class는 일반 legacy snapshot에는 적용할 raw prompt field가 없으므로 `not_applicable`이다. 만약 미래에 다른 legacy source가 prompt-like text를 포함하면 Phase 23 redaction을 먼저 적용하고, 그래도 native v4 prompt hash로 승격하지 않는다.

## Migration tiers

| tier | 이름 | 필수 조건 | 허용 산출 | canonical 사용 |
| --- | --- | --- | --- | --- |
| T0 | source inventory | source JSON parse 성공, source hash 계산 | source index와 direct field coverage | 불가 |
| T1 | structural audit | top-level `date`, `market`, `recommendations` 구조 확인 | direct consensus와 perspective audit | 불가 |
| T2 | outcome-only backfill | ticker, price, calendar, adjusted price provenance 충분 | gross absolute return, state | 불가 |
| T3 | benchmark audit backfill | T2와 Phase 25 benchmark close provenance 충분 | gross benchmark excess return, benchmark state | 불가 |
| T4 | blocked native promotion | raw prompt, data cutoff, candidate audit, portfolio state 결측 확인 | native promotion blocked reason | 불가 |

T4는 성공 등급이 아니다. native promotion을 막는 증거를 명시하는 tier다. 어떤 legacy snapshot도 T4를 통과해 canonical v4 snapshot이 되지 않는다.

## Coverage report schema

Coverage report는 82개 source path를 대상으로 하나의 record를 가진다. 구현은 source count를 listing에서 확인하되, parse 실패 source도 record로 남긴다.

```json
{
  "schema_version": "v4.legacy_backfill.coverage.phase24.1",
  "policy_version": "v4.phase24.1",
  "source_root": "data/snapshots",
  "expected_source_count": 82,
  "generated_at": "2026-08-06T00:00:00+09:00",
  "canonical_metric_eligible_count": 0,
  "records": [
    {
      "source_path": "data/snapshots/2026-03-28.json",
      "source_sha256": "sha256:<source-file-hash>",
      "parse_state": "parsed",
      "migration_tier": "T3",
      "audit_only": true,
      "canonical_metric_eligible": false,
      "recommendation_count": 6,
      "covered_fields": {
        "direct": ["date", "market", "recommendations", "consensus", "perspectives"],
        "derived": ["legacy_snapshot_id", "legacy_recommendation_id"],
        "external_backfill": ["entry_close", "exit_close", "benchmark_close"],
        "unknown": ["raw_prompt", "decision_data_cutoff_at", "candidate_universe", "portfolio_state"],
        "not_applicable": []
      },
      "failure_states": [],
      "derived_artifact_path": "data/derived/v4/legacy-backfill/snapshots/2026-03-28.derived.json",
      "derived_artifact_sha256": "sha256:<derived-file-hash>"
    }
  ],
  "summary": {
    "parsed_sources": 1,
    "malformed_sources": 0,
    "audit_only_sources": 1,
    "canonical_metric_eligible_sources": 0
  }
}
```

`expected_source_count`는 source inventory의 기준값이다. 실제 coverage report는 모든 source path를 record로 남겨야 하며, malformed file도 `parse_state="malformed"`로 남긴다. 이 PRD는 coverage report 형식만 정의한다.

## Deterministic linkage and hash

Canonicalization은 Phase 23과 같은 JSON 규칙을 쓴다. UTF-8, sorted object keys, insignificant whitespace 제거, semantic array order 보존, redaction before hash를 따른다.

```text
legacy_snapshot_id = "legacy_snap_" + first_20_hex(sha256(canonical_json({source_path, source_sha256, policy_version})))
legacy_recommendation_id = "legacy_rec_" + first_20_hex(sha256(canonical_json({legacy_snapshot_id, ticker, source_record_index, consensus_verdict, recommendation_price})))
derived_artifact_hash = "sha256:" + sha256(canonical_json(derived_artifact_without_hash_fields))
source_link_hash = "sha256:" + sha256(canonical_json({source_path, source_sha256, derived_artifact_hash, policy_version}))
```

같은 source hash와 같은 policy version으로 다시 실행하면 같은 derived content와 hash가 나와야 한다. 외부 backfill data version이 바뀌면 `external_data_version`과 output hash가 바뀌며, 이전 artifact는 덮어쓰지 않거나 같은 content임을 확인한 뒤 같은 파일에 동일 바이트를 쓴다.

## Idempotence

Phase 24 implementation은 다음 동작을 보장해야 한다.

1. Source hash가 같고 policy version이 같으면 output이 byte-for-byte 동일하다.
2. 이미 같은 derived artifact가 있으면 재실행은 no-op이다.
3. 같은 path에 다른 content를 쓰려면 먼저 manifest에 conflict를 남기고 실패한다.
4. Partial run 이후 재실행하면 완료된 artifact는 hash로 건너뛰고 누락 artifact만 만든다.
5. Coverage summary는 records에서 다시 계산한다. 수동 입력 count를 믿지 않는다.

## Non-destructive behavior

Rollback은 필요하지 않다. 원본을 바꾸지 않기 때문이다.

| 동작 | 정책 |
| --- | --- |
| source mutation | 금지 |
| in-place migration | 금지 |
| destructive cleanup | 금지 |
| derived artifact overwrite | 같은 canonical content일 때만 허용 |
| quarantine | source를 이동하지 않고 report에만 기록 |
| rollback | source에는 불필요. 잘못된 derived artifact는 새 run manifest로 대체하고 이전 것을 감사 trail로 남김 |

Implementation이 source write permission을 요구하거나 `data/snapshots/**` 파일 hash를 바꾸면 실패다.

## Compatibility

| 소비자 | 계약 |
| --- | --- |
| Phase 22 | derived outcome은 Phase 22 formula를 쓸 수 있지만 native outcome이 아니다 |
| Phase 23 | legacy source와 native snapshot schema를 섞지 않는다. missing native fields는 `unknown`으로 남긴다 |
| Phase 25 | market과 benchmark는 Phase 25 mapping을 쓰며, unknown market은 `insufficient_context`다 |
| Phase 26 | recommendation identity는 legacy prefix를 쓰고 native attribution denominator에 섞지 않는다 |
| Phase 27 | outcome replay에서는 audit overlay로 볼 수 있지만 verbatim replay는 불가 |
| Phase 28 | calibration sample에서 제외한다 |
| Phase 29 | coverage와 exclusion evidence로만 사용한다 |

Downstream Task 6, Task 8, Task 9는 이 문서의 audit-only와 canonical exclusion을 release gate에 반영해야 한다.

## Failure states

| state | 조건 | 처리 |
| --- | --- | --- |
| `malformed_source_json` | JSON parse 실패 | quarantine report에 source path와 hash만 남김 |
| `missing_required_legacy_field` | `date` 또는 `recommendations` 없음 | T0 또는 T1에서 멈추고 covered field를 비움 |
| `malformed_recommendation_record` | ticker record가 object가 아니거나 `price`가 숫자가 아님 | 해당 recommendation만 `blocked`로 남김 |
| `unknown_market_context` | ticker로 market 또는 exchange를 결정할 수 없음 | benchmark excess는 `insufficient_context` |
| `external_price_missing` | entry 또는 exit close가 없음 | outcome field는 `unknown` 또는 `insufficient_data` |
| `benchmark_missing` | benchmark entry 또는 exit close가 없음 | gross absolute만 가능, excess는 `insufficient_context` |
| `corporate_action_unverified` | split, dividend, delisting 여부 확인 불가 | return 계산 금지 |
| `source_hash_changed_during_run` | 읽기 시작과 쓰기 직전 source hash가 다름 | dirty source로 보고 실패. source 수정 금지 |
| `derived_conflict` | 같은 derived path에 다른 hash 존재 | overwrite 금지, manifest conflict 기록 |
| `misleading_success_output` | record 일부 실패를 전체 성공으로 출력 | summary에 partial, failed count를 반드시 표시 |

Malformed input은 legacy malformed JSON, missing `date`, missing `recommendations`, malformed recommendation record, missing `price`, missing perspectives를 포함한다. 구현 검증은 이 사례를 synthetic source로 probe해야 한다.

## Legacy source to derived fixture

이 fixture는 `data/snapshots/2026-03-28.json`의 `105560` record 형태를 source로 삼는 예시다. 실제 migration 실행 결과가 아니다.

### Source excerpt

```json
{
  "date": "2026-03-28",
  "market": {
    "kospi": {"name": "코스피", "close": 5438.87, "change_5d": 0.6126809415899717, "change_20d": -12.896272178830362},
    "kosdaq": {"name": "코스닥", "close": 1141.51, "change_5d": 4.067864599002624, "change_20d": -4.2983618102248515}
  },
  "recommendations": {
    "105560": {
      "name": "KB금융",
      "price": 152200.0,
      "consensus_verdict": "HOLD",
      "consensus_confidence": "moderate",
      "consensus_label": "약한 합의",
      "vote_summary": {"BUY": 1, "SELL": 1, "HOLD": 3, "N/A": 0},
      "perspectives": [
        {"perspective": "kwangsoo", "verdict": "HOLD", "confidence": 0.84, "reason": "하락장 속 반등 구간이지만 중기 추세와 주도주 조건이 부족해 신규 매수보다 관망이 우선이다."},
        {"perspective": "quant", "verdict": "SELL", "confidence": 0.67, "reason": "Bear 3/6 vs 4/6"}
      ]
    }
  }
}
```

### Derived audit artifact

```json
{
  "schema_version": "v4.legacy_backfill.snapshot.phase24.1",
  "policy_version": "v4.phase24.1",
  "audit_only": true,
  "canonical_metric_eligible": false,
  "source": {
    "source_path": "data/snapshots/2026-03-28.json",
    "source_sha256": "sha256:<source-file-hash>",
    "source_snapshot_date": {"value": "2026-03-28", "provenance": "direct"}
  },
  "legacy_snapshot_id": "legacy_snap_<first20hex>",
  "records": [
    {
      "legacy_recommendation_id": "legacy_rec_<first20hex>",
      "ticker": {"value": "105560", "provenance": "direct"},
      "name": {"value": "KB금융", "provenance": "direct"},
      "source_record_index": 0,
      "legacy_recommendation_price": {"value": 152200.0, "provenance": "direct", "phase22_entry_price": false},
      "consensus": {
        "verdict": {"value": "HOLD", "provenance": "direct"},
        "confidence_label": {"value": "moderate", "provenance": "direct"},
        "vote_summary": {"value": {"BUY": 1, "SELL": 1, "HOLD": 3, "N/A": 0}, "provenance": "direct"}
      },
      "market_context": {
        "market": {"value": "KR", "provenance": "derived"},
        "exchange": {"value": "KOSPI", "provenance": "derived"},
        "benchmark_id": {"value": "KS11", "provenance": "derived"},
        "decision_data_cutoff_at": {"value": null, "state": "unknown", "provenance": "unknown"}
      },
      "outcomes": {
        "N5": {
          "state": "matured_audit_only",
          "entry_session": {"value": "2026-03-30", "provenance": "external_backfill"},
          "target_exit_session": {"value": "2026-04-06", "provenance": "external_backfill"},
          "entry_close": {"value": 153000.0, "provenance": "external_backfill", "source": "price-fixture-v1"},
          "exit_close": {"value": 156060.0, "provenance": "external_backfill", "source": "price-fixture-v1"},
          "benchmark_entry_close": {"value": 5400.0, "provenance": "external_backfill", "source": "benchmark-fixture-v1"},
          "benchmark_exit_close": {"value": 5346.0, "provenance": "external_backfill", "source": "benchmark-fixture-v1"},
          "gross_absolute_return": {"value": 0.02, "provenance": "external_backfill"},
          "gross_benchmark_excess_return": {"value": 0.03, "provenance": "external_backfill"},
          "canonical_metric_eligible": false
        }
      },
      "unknown_native_fields": [
        "raw_prompt",
        "prompt_hash",
        "raw_provider_response",
        "decision_data_cutoff_at",
        "candidate_universe",
        "candidate_rejections",
        "portfolio_state",
        "risk_state"
      ],
      "replay_eligibility": {
        "outcome_replay": "audit_only",
        "verbatim_replay": "ineligible",
        "recompute_replay": "ineligible"
      }
    }
  ],
  "content_hashes": {
    "derived_artifact_hash": "sha256:<derived-hash>",
    "source_link_hash": "sha256:<source-link-hash>"
  }
}
```

Fixture trace: source `price`는 direct legacy recommendation price이며 Phase 22 entry price가 아니다. Outcome과 benchmark는 `external_backfill`로만 들어간다. Raw prompt, data cutoff, candidate audit, portfolio state는 `unknown`으로 남는다. Derived record는 audit-only이고 canonical metric에 들어가지 않는다.

## Acceptance criteria

1. Source snapshot 82개는 immutable source로 남고 `data/snapshots/**`를 수정하지 않는다.
2. Derived output은 `data/derived/v4/legacy-backfill/**`에만 쓴다.
3. 모든 field는 `direct`, `derived`, `external_backfill`, `unknown`, `not_applicable` 중 하나의 provenance를 가진다.
4. Legacy derived record는 audit-only이며 canonical v4 metric, calibration, adaptive weights에서 제외된다.
5. Outcome과 benchmark field만 충분한 external provenance가 있을 때 backfill할 수 있다.
6. Raw prompt, exact data cutoff, candidate audit, portfolio state, risk state는 추정하지 않고 `unknown`으로 남긴다.
7. Coverage report는 source path별 parse state, tier, field coverage, failure state, derived hash를 포함한다.
8. Deterministic linkage와 hash는 같은 input에서 같은 output을 만든다.
9. 재실행은 idempotent이며 source mutation과 destructive rollback이 없다.
10. Malformed legacy input은 성공으로 숨기지 않고 failure state 또는 quarantine report에 남긴다.
