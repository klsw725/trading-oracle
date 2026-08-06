# PRD 03: Incremental Value Evaluation
> **상태**: 📝 초안

Parent SPEC: [v7 Information Source Expansion SPEC](../SPEC.md)

## 문서 범위

이 문서는 PRD 01 source provenance와 PRD 02 quality result를 통과한 source가 실제 추천 판단에 추가 가치를 주는지 평가하는 계약을 정의한다. 평가 대상은 가격, 펀더멘털, 공시, 뉴스, 웹 컨텍스트, 매크로 source를 모두 포함한다.

Source를 붙였다는 사실은 성공이 아니다. 더 많은 검색 결과, 더 긴 프롬프트, 더 많은 fetch가 있어도 factual correction, verdict quality, calibration, coverage, cost, latency, harm 기준을 함께 통과하지 못하면 source는 채택 근거가 없다.

기존 웹 검색 설계는 source ON/OFF 30일 비교와 5 percent point 합의 적중률 개선 목표를 남겼다. 이 문서는 그 목표를 같은 입력 cutoff, 같은 평가 cohort, 같은 threshold, 같은 cost ledger 위에서 검증 가능한 A/B 계약으로 좁힌다.

## 목표

1. Source ON/OFF cohort를 같은 decision input과 outcome cutoff로 고정한다.
2. Baseline A/B protocol로 OFF, ON, ON without source facts를 비교한다.
3. Factual correction, verdict change, calibration lift, latency, cost, coverage, harm을 하나의 report에서 판정한다.
4. Minimum sample, threshold, no-op policy를 정의해 작은 표본이나 흔들리는 결과가 정책 변경으로 이어지지 않게 한다.
5. Deterministic fixture와 mutation만으로 leakage, flaky result, misleading lift, latency-only win을 검증할 수 있게 한다.

## 비목표

1. Source promotion, fallback order, cache invalidation, retirement를 정의하지 않는다.
2. Adapter provenance나 quality scoring을 다시 정의하지 않는다.
3. Production scorer, prompt, config, cache, data 파일을 수정하지 않는다.
4. 특정 vendor, 검색 도구, broker API, 유료 source를 기본값으로 고르지 않는다.
5. Source 추가 자체, 검색 건수 증가, latency 개선만으로 성공 판정을 내리지 않는다.

## 입력 계약

Incremental value report는 아래 입력만 소비한다.

| input | required | rule |
| --- | --- | --- |
| `cohort_manifest` | yes | sample id, market, ticker, action universe, split, decision cutoff, outcome cutoff, content hash를 가진다. |
| `source_off_outputs` | yes | source 후보를 끈 baseline 산출물이다. 같은 prompt bundle과 scorer를 쓴다. |
| `source_on_outputs` | yes | source 후보를 켠 산출물이다. PRD 01 provenance와 PRD 02 quality hash를 연결한다. |
| `source_masked_outputs` | yes | source는 fetch하지만 candidate facts를 prompt나 scorer에서 제거한 산출물이다. Latency와 routing 영향만 분리한다. |
| `fact_audit_set` | yes | 사람이 고른 예제가 아니라 frozen manifest의 fact claim과 expected correction label이다. |
| `outcome_adapter` | optional | v4 measurement 또는 같은 의미의 deterministic outcome fixture다. 없으면 verdict lift와 calibration은 no-op이다. |

Source ON과 OFF는 같은 ticker, 같은 emitted_at, 같은 market calendar, 같은 prompt bundle, 같은 scorer version, 같은 portfolio input, 같은 decision cutoff를 써야 한다. ON output이 OFF보다 늦게 만들어졌더라도 decision cutoff 이후 article, filing, price, benchmark, outcome은 feature로 들어갈 수 없다.

## Source ON/OFF Cohorts

| cohort | source access | expected use |
| --- | --- | --- |
| `source_off` | 후보 source disabled | 사용자가 받았을 baseline이다. |
| `source_on` | 후보 source enabled and quality-gated | factual correction, verdict, confidence, latency, cost, coverage, harm을 평가한다. |
| `source_masked` | fetch and quality check happen, source facts hidden | latency, timeout, routing side effect를 분리한다. |
| `source_oracle_fixture` | deterministic fixture only | parser와 mutation 산술 검증에만 쓴다. |

ON/OFF sample은 pair 단위로 묶는다. 한쪽 output이 없으면 그 pair는 verdict lift sample이 아니며 coverage denominator에는 남는다. Missing ON을 HOLD나 neutral verdict로 바꿀 수 없다.

## Baseline A/B Protocol

A/B는 read-only simulation이다. Production scorer, weights, prompt, cache, config를 바꾸지 않는다.

1. `cohort_manifest`를 outcome 확인 전에 고정한다.
2. `source_off_outputs`를 먼저 materialize 하고 hash를 남긴다.
3. `source_on_outputs`는 PRD 01 provenance와 PRD 02 quality result가 pass 또는 usable인 source만 prompt eligible로 둔다.
4. `source_masked_outputs`는 fetch, dedup, quality cost는 유지하되 source facts를 숨긴다.
5. Outcome adapter는 all outputs materialized 뒤에만 결합한다.
6. Report는 pair hash, output hash, source quality hash, outcome hash를 모두 기록한다.

OFF baseline보다 ON이 좋아 보여도 source_masked가 같은 lift를 보이면 source fact의 증분 가치가 아니다. Routing, delay, random model variance, sample selection 때문이면 no-op이다.

## Factual Correction Metric

Factual correction은 source가 baseline의 사실 오류를 고쳤는지 claim 단위로 본다. Verdict가 바뀌지 않아도 correction은 따로 기록한다.

| metric | formula | threshold |
| --- | --- | --- |
| `correction_precision` | true corrections / claimed corrections | `0.80` 이상 |
| `correction_recall` | corrected baseline factual errors / known baseline factual errors | `0.25` 이상 |
| `unsupported_correction_rate` | corrections without PRD 01 and PRD 02 evidence / claimed corrections | `0.05` 이하 |
| `new_false_fact_rate` | new false facts introduced by source ON / source ON samples | `0.03` 이하 |

Factual correction은 source hash와 quality hash가 없으면 인정하지 않는다. Search snippet count, domain fame, 또는 LLM reasoning tone은 correction evidence가 아니다.

## Verdict and Calibration Lift

Verdict lift는 source ON이 OFF보다 action-specific outcome을 더 잘 맞혔는지 본다. Calibration lift는 confidence probability가 correctness event 확률에 더 가까워졌는지 본다.

```text
source_gain_N = source_on_edge_N - source_off_edge_N
verdict_lift_N = mean(source_gain_N over eligible paired samples)
off_hit_N = 1 if source_off_edge_N >= success_threshold_N else 0
on_hit_N = 1 if source_on_edge_N >= success_threshold_N else 0
factual_recovery_rate = count(off factual error fixed and on hit) / count(off factual error samples)
calibration_brier_delta = source_on_brier - source_off_brier
calibration_ece_delta = source_on_ece - source_off_ece
```

| metric | required direction | default threshold |
| --- | --- | --- |
| `verdict_lift_5` | positive | lower 90 percent bootstrap bound >= `0.003` |
| `factual_recovery_rate` | positive | `0.10` 이상 |
| `calibration_brier_delta` | lower is better | `<= -0.010` 또는 regression `<= 0.005` with verdict lift pass |
| `calibration_ece_delta` | lower is better | `<= -0.010` 또는 source ON ECE `<= 0.10` |
| `verdict_flip_precision` | beneficial flips / all source-caused flips | `0.60` 이상 |

BUY, SELL, HOLD는 섞지 않는다. Market, action, horizon, prompt bundle, scorer, source bundle, quality contract version이 다르면 별도 cohort다.

## Latency, Cost, Coverage, and Harm

Source value는 품질 lift에서 운영 부담과 해를 뺀 뒤 판정한다.

| metric | rule |
| --- | --- |
| `coverage_rate` | eligible ON samples / cohort samples. 기본 `0.75` 이상이다. |
| `target_coverage_rate` | source가 목표로 한 error cohort에서 `0.80` 이상이다. |
| `p95_added_wall_ms` | OFF 대비 ON 추가 p95 wall time. 기본 `2500` 이하다. |
| `mean_added_wall_ms` | OFF 대비 ON 추가 평균 wall time. 기본 `900` 이하다. |
| `added_prompt_tokens_per_ticker` | 기본 `1500` 이하다. |
| `added_fetches_per_ticker` | declared budget 이하다. |
| `timeout_rate` | `0.02` 이하다. Timeout을 verdict로 숨기면 malformed다. |
| `harm_rate` | ON edge가 OFF보다 `0.02` 이상 나쁜 pair 비율. 기본 `0.20` 이하다. |
| `severe_harm_rate` | ON edge가 OFF보다 `0.05` 이상 나쁜 pair 비율. 기본 `0.05` 이하다. |
| `coverage_gap_harm_rate` | source가 없는 sample을 잘못된 fallback fact로 채워 발생한 harm. 기본 `0`이다. |

Latency만 낮아진 source는 거절한다. 빠른 source가 factual correction이나 verdict lift 없이 baseline보다 빨라졌다면 evaluation outcome은 `REJECT_LATENCY_ONLY`다.

## Minimum Sample and No-op Policy

| cohort | minimum eligible paired samples |
| --- | --- |
| 전체 holdout | `300` |
| source target error cohort | `100` |
| market별 KR 또는 US | scope에 있으면 각 `100` |
| action별 BUY, SELL, HOLD | action을 내면 각 `50` |
| factual audit known-error set | `80` |
| non-empty calibration bucket | `20` |

표본이 부족하면 report는 만들 수 있지만 source policy는 no-op이다. No-op은 source order, traffic share, prompt injection, cache TTL, scorer weight, 사용자 출력 우선순위를 바꾸지 않는다는 뜻이다.

## Verdict Codes

| code | meaning |
| --- | --- |
| `PASS_INCREMENTAL_VALUE_EVALUATION` | sample, factual correction, verdict lift, calibration, coverage, latency, cost, harm, leakage, flaky checks를 모두 통과했다. |
| `REJECT_NO_INCREMENTAL_VALUE` | source ON이 baseline보다 충분히 낫지 않다. |
| `REJECT_HARMFUL_SOURCE` | harm 또는 severe harm threshold를 넘는다. |
| `REJECT_LATENCY_ONLY` | latency나 cost만 좋아지고 factual correction 또는 verdict lift가 없다. |
| `REJECT_MALFORMED_EVALUATION_INPUT` | cohort, cutoff, hash, confidence, cost, coverage, source evidence 중 하나가 잘못됐다. |
| `INCONCLUSIVE_INSUFFICIENT_SAMPLE` | minimum sample 아래다. |
| `INCONCLUSIVE_FLAKY_RESULT` | 같은 입력 반복 계산에서 threshold 판정이 바뀐다. |
| `INCONCLUSIVE_MISSING_OUTCOME_ADAPTER` | outcome fields가 없어 verdict lift나 calibration을 계산할 수 없다. |

Pass는 source promotion이 아니다. 다음 PRD가 promotion, retirement, rollback을 별도로 판단한다.

## Machine-readable Fixture

```json
{
  "schema_version": "v7.incremental_value_evaluation.prd03.1",
  "contract_id": "incremental_value_evaluation_prd03",
  "thresholds": {
    "success_threshold_5": "0.01",
    "verdict_lift_lower_90_min": "0.003",
    "correction_precision_min": "0.80",
    "correction_recall_min": "0.25",
    "coverage_rate_min": "0.75",
    "p95_added_wall_ms_max": 2500,
    "harm_rate_max": "0.20",
    "severe_harm_rate_max": "0.05"
  },
  "happy_filing_lift_fixture": {
    "report_id": "ive_v7_filing_source_001",
    "source_bundle_id": "filing_source_bundle_v1",
    "cohort_key": {
      "market": "KR",
      "action": "BUY",
      "horizon": 5,
      "prompt_bundle": "mp_prompt_20260806",
      "scorer_version": "consensus_scorer_v1",
      "quality_contract": "v7.quality_freshness_dedup.prd02.1"
    },
    "samples": {
      "holdout_pairs": 360,
      "target_error_pairs": 130,
      "factual_audit_known_errors": 96,
      "non_empty_calibration_bucket_min": 24
    },
    "source_refs": [
      {
        "adapter_id": "filing_context",
        "provenance_hash": "sha256:1111111111111111111111111111111111111111111111111111111111111111",
        "quality_result_hash": "sha256:2222222222222222222222222222222222222222222222222222222222222222",
        "freshness_label": "fresh",
        "quality_label": "high"
      }
    ],
    "metrics": {
      "verdict_lift_5": "0.012",
      "verdict_lift_lower_90": "0.004",
      "factual_recovery_rate": "0.18",
      "correction_precision": "0.86",
      "correction_recall": "0.31",
      "unsupported_correction_rate": "0.02",
      "new_false_fact_rate": "0.01",
      "verdict_flip_precision": "0.67",
      "calibration_brier_delta": "-0.014",
      "calibration_ece_delta": "-0.012",
      "coverage_rate": "0.82",
      "target_coverage_rate": "0.86",
      "p95_added_wall_ms": 1800,
      "mean_added_wall_ms": 640,
      "added_prompt_tokens_per_ticker": 780,
      "timeout_rate": "0.004",
      "harm_rate": "0.13",
      "severe_harm_rate": "0.02"
    },
    "masked_control": {
      "source_masked_lift_5": "0.001",
      "source_masked_lift_lower_90": "-0.002",
      "conclusion": "lift_requires_source_facts"
    },
    "expected_code": "PASS_INCREMENTAL_VALUE_EVALUATION"
  },
  "failure_fixtures": [
    {
      "fixture": "latency_only_rejection",
      "mutation": "set p95_added_wall_ms lower than baseline but factual and verdict lift to zero",
      "expected_code": "REJECT_LATENCY_ONLY"
    },
    {
      "fixture": "source_addition_not_success",
      "mutation": "increase source result count and keep all lift metrics below threshold",
      "expected_code": "REJECT_NO_INCREMENTAL_VALUE"
    },
    {
      "fixture": "future_filing_leakage",
      "mutation": "insert filing published after decision cutoff into source_on_outputs",
      "expected_code": "REJECT_MALFORMED_EVALUATION_INPUT"
    },
    {
      "fixture": "flaky_bootstrap_lift",
      "mutation": "same input crosses verdict_lift_lower_90 threshold across repeated deterministic seeds",
      "expected_code": "INCONCLUSIVE_FLAKY_RESULT"
    }
  ],
  "required_mutations": [
    "json_field_removal",
    "source_hash_mismatch",
    "quality_hash_missing",
    "source_on_off_cutoff_mismatch",
    "future_fact_leakage",
    "masked_control_same_lift",
    "latency_only_win",
    "harm_threshold_breach",
    "insufficient_sample_noop",
    "flaky_threshold"
  ]
}
```

## Happy Trace: Filing Source Lift

1. Evaluator reads 360 paired KR BUY samples where source OFF and source ON share the same decision cutoff.
2. Filing source records point to PRD 01 provenance hash and PRD 02 high quality hash.
3. ON fixes known baseline filing errors with correction precision `0.86` and recall `0.31`.
4. ON improves 5-session verdict lift with lower 90 percent bound `0.004`.
5. Calibration improves because Brier and ECE deltas are negative.
6. Source masked control has near-zero lift, so the gain is tied to source facts rather than fetch side effects.
7. Coverage, p95 latency, token cost, timeout, harm, and severe harm all stay inside thresholds.
8. Evaluator returns `PASS_INCREMENTAL_VALUE_EVALUATION`, which is only an evaluation pass and not source promotion.

## Failure Fixtures

### Latency-only rejection

If ON is faster or cheaper but factual correction and verdict lift are both zero, evaluator returns `REJECT_LATENCY_ONLY`. Speed does not justify a source that adds no decision value.

### Source addition not success

If ON has more source records, more snippets, or more prompt tokens but lift metrics remain below threshold, evaluator returns `REJECT_NO_INCREMENTAL_VALUE`. Addition itself is not success evidence.

### Future filing leakage

If ON uses a filing, article, price, benchmark, or outcome published after decision cutoff, parser returns `REJECT_MALFORMED_EVALUATION_INPUT`. The sample cannot be repaired by dropping only the leaked field after outcome is known.

### Flaky bootstrap lift

If the same frozen inputs produce pass and fail decisions across repeated deterministic runs, evaluator returns `INCONCLUSIVE_FLAKY_RESULT`. A flaky threshold cannot alter source policy.

## Parser and Mutation Requirements

Parser must read every fenced JSON block in this PRD and run these in-memory mutations.

| probe | mutation | expected result |
| --- | --- | --- |
| `json_field_removal` | Remove `cohort_key`, `samples`, `source_refs`, `metrics`, or `expected_code`. | fail with missing field. |
| `source_hash_mismatch` | Change `provenance_hash` after report hash calculation. | fail with hash mismatch. |
| `quality_hash_missing` | Remove `quality_result_hash` from a source ref. | `REJECT_MALFORMED_EVALUATION_INPUT`. |
| `source_on_off_cutoff_mismatch` | Give ON a later decision cutoff than OFF. | `REJECT_MALFORMED_EVALUATION_INPUT`. |
| `future_fact_leakage` | Add post-cutoff filing text to ON facts. | `REJECT_MALFORMED_EVALUATION_INPUT`. |
| `masked_control_same_lift` | Set masked control lift equal to source ON lift. | `REJECT_NO_INCREMENTAL_VALUE`. |
| `latency_only_win` | Improve latency while setting factual and verdict lift to zero. | `REJECT_LATENCY_ONLY`. |
| `harm_threshold_breach` | Set harm rate above `0.20` or severe harm above `0.05`. | `REJECT_HARMFUL_SOURCE`. |
| `insufficient_sample_noop` | Lower holdout pairs below `300`. | `INCONCLUSIVE_INSUFFICIENT_SAMPLE` and no-op. |
| `flaky_threshold` | Same inputs cross the lower-bound threshold across repeated deterministic runs. | `INCONCLUSIVE_FLAKY_RESULT`. |

## Acceptance Criteria

1. The document has draft metadata directly under the title and no done marker.
2. It defines source ON/OFF cohorts, factual correction, verdict lift, calibration lift, latency, cost, coverage, harm, baseline A/B, sample thresholds, and no-op policy.
3. It says source addition itself is not success evidence.
4. It includes a parseable JSON fixture with a filing-source lift happy path and latency-only rejection failure.
5. It requires deterministic parser and mutation checks for leakage, flaky threshold, harm breach, hash mismatch, missing quality hash, field removal, masked control, and insufficient sample no-op.
6. It does not read or expose config, secret, token, cookie, account, or credential material.

## Evidence Requirement

The exact evidence artifact for this authoring task is `.omo/evidence/trading-oracle-v4-v9-specs-20260806/task-22-trading-oracle-v4-measurement-attribution.md`. The evidence must record failing-first target absence, manual Read of this PRD, deterministic parser checks, fixture mutations, and the no secret-read boundary.
