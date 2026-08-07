# PRD 02: Offline Evaluation
> **상태**: ✅ 구현 완료 (2026-08-07)
> **SPEC 참조**: [v6 SPEC](../SPEC.md)

## 문서 범위

이 문서는 PRD 01에서 평가 대상으로 접수된 새 투자 관점 후보를 오프라인에서 판정하는 계약을 정의한다. 입력은 고정 데이터셋, 후보 산출물, 기존 다섯 관점 산출물, outcome fixture다. 출력은 후보를 paper cohort로 보낼 수 있는지, 거절해야 하는지, 표본이나 증거가 부족한지에 대한 근거다.

이 문서는 v6 내부 PRD 02다. v4 측정 산출물이 있으면 outcome adapter로 쓸 수 있지만, 그 산출 여부에 의존하지 않는다. v4 산출물이 없으면 이 문서의 fixture와 계산식만으로 parser, mutation, 산술 검증을 만들 수 있어야 한다.

## 문제

새 관점 후보는 기존 관점과 다른 말을 한다고 해서 가치가 생기지 않는다. 같은 데이터와 같은 오류를 다시 설명하는 후보는 합의 표를 늘리지만 정보량은 늘리지 않는다. 반대로 독립 가설이 있어도 오프라인 평가가 느슨하면 미래 가격, 기존 결과, 수작업으로 고른 표본이 섞여 성능이 과장된다.

오프라인 평가는 다음 질문에 답해야 한다.

1. 후보가 기존 baseline보다 추가 정보를 주는가.
2. 그 추가 정보가 특정 오류군에서 재현되는가.
3. 후보 오류가 기존 관점 오류와 높은 상관 clone은 아닌가.
4. confidence, N/A, 비용, latency가 품질 향상을 잠식하지 않는가.
5. 표본이 부족하거나 결과가 흔들릴 때 정책 변경 없이 보류되는가.

## 목표

1. 고정 데이터셋 split과 leakage 금지 규칙을 정의한다.
2. baseline, 후보 단독, baseline plus candidate의 비교 방식을 고정한다.
3. incremental lift, error correlation, calibration, N/A rate, cost, latency, ablation을 같은 report에서 판정한다.
4. 최소 표본, threshold, inconclusive 규칙을 명시한다.
5. high-correlation clone을 후보 성능과 무관하게 거절한다.
6. stale, dirty, misleading, flaky probe와 mutation fixture를 요구한다.
7. DoneClaim이 증거를 대체하지 못하게 한다.

## 비목표

1. 후보를 production 합의에 넣지 않는다.
2. paper cohort, rollout, rollback, weight 변경은 정의하지 않는다.
3. 기존 다섯 관점 prompt나 scorer를 고치지 않는다.
4. live market fetch, LLM 호출, broker 주문을 요구하지 않는다.
5. 기존 legacy snapshot을 canonical 성과로 승격하지 않는다.

## 입력 계약

오프라인 평가 입력은 네 묶음이다.

| input | required | rule |
| --- | --- | --- |
| `candidate_proposal` | yes | PRD 01을 통과한 후보 제안서다. `candidate_id`, `candidate_version`, `hypothesis_id`, `overlap_matrix`, budget이 있어야 한다. |
| `frozen_dataset_manifest` | yes | split, sample id, feature cutoff, outcome cutoff, hash를 가진다. 평가 시작 뒤 변경할 수 없다. |
| `baseline_outputs` | yes | 기존 다섯 관점과 기존 합의기의 산출물이다. 후보 산출 뒤에 다시 계산하지 않는다. |
| `candidate_outputs` | yes | 후보가 같은 decision input cutoff만 보고 만든 verdict, confidence, N/A, cost, latency다. |
| `outcome_adapter` | optional | v4 measurement artifact 또는 이 문서 fixture의 outcome fields다. 없으면 outcome metric은 inconclusive다. |

필수 필드 예시는 다음과 같다.

```json
{
  "evaluation_input": {
    "schema_version": "v6.offline_evaluation.1",
    "candidate_id": "pcand_v6_working_capital_quality",
    "candidate_version": "working_capital_quality.0.1",
    "hypothesis_id": "hyp_v6_working_capital_quality_001",
    "dataset_manifest_id": "fds_v6_perspective_eval_20260806",
    "baseline_bundle_id": "baseline_existing_five_20260806",
    "candidate_output_id": "cand_out_working_capital_quality_20260806",
    "outcome_adapter": "fixture_or_v4_measurement_optional"
  }
}
```

## 고정 데이터셋과 split

평가 데이터셋은 outcome을 보기 전에 고정한다. manifest는 sample id, ticker, market, emitted_at, decision input cutoff, feature cutoff, outcome horizon, split name, content hash를 가진다.

| split | purpose | default share | mutation allowed? |
| --- | --- | --- | --- |
| `train_window` | 후보 parser와 산술 검증 개발 | 50 percent | no |
| `validation_window` | threshold 조정과 ablation 확인 | 25 percent | no |
| `holdout_window` | 최종 오프라인 판정 | 25 percent | no |
| `drift_probe_window` | 최신 구간 민감도 관찰 | optional | no |

Split 규칙은 다음과 같다.

1. 시간 순서를 지킨다. 같은 ticker의 미래 sample이 과거 split에 영향을 주면 안 된다.
2. 같은 emitted_at, 같은 ticker, 같은 source hash를 가진 중복은 한 split에만 들어간다.
3. Train과 holdout 사이에는 기본 20 동일 시장 session embargo를 둔다.
4. Outcome cutoff 이후 만들어진 feature, price, benchmark, article, analyst note는 decision input으로 쓰지 않는다.
5. 후보 confidence와 N/A 판정은 outcome을 보기 전에 materialized output으로 고정한다.
6. 수작업 제외는 manifest에 exclusion code와 입력 기준을 남긴다. Outcome을 본 뒤 제외할 수 없다.

## Baseline 비교

Baseline은 세 겹으로 비교한다.

| baseline | definition | reason |
| --- | --- | --- |
| `existing_consensus` | 현재 다섯 관점의 기존 합의 결과 | 사용자가 받았을 결과다. |
| `closest_existing_perspective` | PRD 01 overlap matrix에서 overlap score가 가장 높은 기존 관점 | clone 여부를 본다. |
| `equal_weight_existing_five` | 기존 다섯 관점만 같은 weight로 합성한 결과 | adaptive legacy metric 영향을 줄인다. |

Candidate 비교는 read-only simulation으로만 한다. `baseline_plus_candidate`는 사전에 선언한 합성 규칙으로 계산하며, production scorer나 설정을 바꾸지 않는다.

## Outcome과 metric

Primary outcome은 horizon N의 action specific edge다. v4 측정 artifact가 있으면 같은 entry, exit, benchmark excess 개념을 adapter로 쓴다. 없으면 fixture가 제공한 `baseline_edge`와 `candidate_edge`를 쓴다.

```text
sample_gain_N = candidate_edge_N - baseline_edge_N
incremental_lift_N = mean(sample_gain_N over eligible holdout samples)
baseline_hit_N = 1 if baseline_edge_N >= success_threshold_N else 0
candidate_hit_N = 1 if candidate_edge_N >= success_threshold_N else 0
error_baseline_N = 1 - baseline_hit_N
error_candidate_N = 1 - candidate_hit_N
```

기본 success threshold는 `0.01`이다. Threshold version은 manifest에 저장한다. Threshold를 바꾸면 기존 report를 덮어쓰지 않고 새 report를 만든다.

## Incremental lift

후보는 전체 holdout과 독립 가설이 겨냥한 오류군에서 모두 비교한다.

| metric | required direction | default threshold |
| --- | --- | --- |
| `holdout_incremental_lift_5` | positive | lower 90 percent bootstrap bound >= `0.003` |
| `target_error_lift_5` | positive | lower 90 percent bootstrap bound >= `0.007` |
| `harm_rate` | bounded | candidate가 baseline보다 `0.02` 이상 나쁜 sample 비율 <= `0.20` |
| `baseline_miss_recovery_rate` | positive | baseline miss 중 candidate hit 비율 >= `0.10` |
| `non_target_harm_rate` | bounded | non target cohort에서 harm rate <= `0.25` |

20 session horizon이 있으면 같은 기준을 별도 report로 계산한다. 5와 20을 평균내서 하나의 수치로 만들지 않는다.

## Error correlation과 clone 거절

후보 오류는 기존 관점 오류와 낮은 상관이어야 한다. 상관은 holdout에서 action과 horizon별로 계산한다.

```text
error_correlation(candidate, perspective) = pearson(error_candidate_vector, error_perspective_vector)
verdict_correlation(candidate, perspective) = pearson(candidate_verdict_direction, perspective_verdict_direction)
max_error_correlation = max over existing perspectives
max_verdict_correlation = max over existing perspectives
```

거절 규칙은 hard rule이다.

| rejection code | condition |
| --- | --- |
| `REJECT_HIGH_CORRELATION_CLONE` | `max_error_correlation >= 0.80` 또는 `max_verdict_correlation >= 0.90` |
| `REJECT_QUANT_REWEIGHT_CLONE` | quant와 high correlation이고 주요 입력이 `signals`, RSI, MACD, EMA, BB, momentum 투표에 몰려 있다. |
| `REJECT_NO_INCREMENTAL_LIFT` | high correlation은 아니지만 holdout과 target 오류군 lift가 모두 threshold 아래다. |
| `REJECT_HARMFUL_CANDIDATE` | 전체 harm rate 또는 non target harm rate가 threshold를 넘는다. |

High-correlation clone은 lift가 좋아 보여도 거절한다. 같은 오류를 같은 방식으로 맞히는 후보는 독립 관점이 아니다.

## Calibration

Candidate confidence는 후보 correctness event가 참일 확률이다. Display label이나 reasoning tone이 아니다.

```text
p_i = candidate confidence for sample i
y_i = candidate_hit_N for sample i
Brier = mean((p_i - y_i)^2)
ECE = sum(bucket_weight * abs(bucket_accuracy - bucket_confidence))
```

Bucket은 `[0.0,0.2)`, `[0.2,0.4)`, `[0.4,0.6)`, `[0.6,0.8)`, `[0.8,1.0]`이다. Empty bucket은 metric에 더하지 않는다.

Calibration 기준은 다음과 같다.

| metric | threshold |
| --- | --- |
| `candidate_brier` | baseline confidence Brier보다 `0.02` 이상 나빠지면 inconclusive 또는 reject |
| `candidate_ece` | `0.10` 이하 또는 baseline ECE보다 `0.02` 이상 개선 |
| `overconfident_error_bucket` | sample 20개 이상 bucket에서 confidence와 accuracy gap이 `0.20` 초과면 reject |

## N/A와 coverage

`N/A`는 낮은 confidence의 HOLD가 아니다. 필수 입력 부재, parser 실패, budget 초과, timeout, 독립 가설 적용 불가, outcome adapter 부재는 `N/A`로 남긴다.

| metric | threshold |
| --- | --- |
| `overall_na_rate` | `0.15` 이하 |
| `target_error_na_rate` | `0.20` 이하 |
| `missing_required_input_as_hold_count` | `0` |
| `timeout_as_verdict_count` | `0` |

Coverage가 낮아도 특정 niche 후보를 무조건 거절하지는 않는다. 다만 N/A가 많은 후보는 전체 관점이 아니라 제한된 오류군 후보로만 다음 문서에서 다룰 수 있다.

## Cost와 latency

Cost와 latency는 품질 metric과 함께 판정한다.

| metric | ceiling |
| --- | --- |
| `p95_wall_ms_per_ticker` | PRD 01 budget 이하, 최대 `6000` |
| `mean_wall_ms_per_ticker` | PRD 01 budget의 `0.60` 이하 권장 |
| `llm_calls_per_ticker` | PRD 01 budget 이하 |
| `prompt_tokens_per_ticker` | PRD 01 budget 이하 |
| `extra_fetches_per_ticker` | PRD 01 budget 이하 |
| `timeout_rate` | `0.02` 이하 |

Budget 초과 sample은 성공으로 바꾸지 않는다. Candidate가 budget을 넘기면 해당 sample은 `N/A`와 `budget_exceeded`로 기록한다.

## Ablation

Ablation은 후보가 새 관측값으로 성능을 얻었는지 확인한다.

| ablation | expected result |
| --- | --- |
| `remove_novel_observations` | lift가 최소 `0.007` 낮아진다. |
| `existing_signal_only` | candidate가 PRD 01 overlap ceiling을 넘으면 reject. |
| `shuffle_candidate_outputs_within_split` | lift가 0 근처로 무너진다. |
| `leak_future_outcome_feature` | parser가 leakage로 실패시킨다. |
| `na_to_hold_mutation` | malformed N/A handling으로 실패시킨다. |

Ablation이 후보 lift를 설명하지 못하면 결과는 inconclusive다. 기존 신호만 남겨도 같은 lift가 나오면 clone 거절이다.

## 최소 표본

정책 변경 없이 report는 작은 표본에서도 만들 수 있다. 다만 다음 문서로 넘기는 판정에는 최소 표본이 필요하다.

| cohort | minimum eligible samples |
| --- | --- |
| 전체 holdout | `300` |
| target error cohort | `100` |
| market별 holdout | `100` for KR, `100` for US when both are in scope |
| action별 BUY, SELL, HOLD | each `50` when candidate emits that action |
| non-empty calibration bucket | `20` |
| high-correlation check | candidate와 각 기존 관점이 같이 verdict를 낸 sample `100` |

표본이 부족하면 `INCONCLUSIVE_INSUFFICIENT_SAMPLE`이다. 표본 부족을 pass로 바꿀 수 없다.

## 판정 코드

오프라인 평가 report는 다음 코드 중 하나를 낸다.

| code | meaning |
| --- | --- |
| `PASS_OFFLINE_EVALUATION` | 최소 표본을 충족하고 lift, clone, calibration, N/A, cost, ablation 기준을 모두 만족한다. |
| `REJECT_HIGH_CORRELATION_CLONE` | 기존 관점과 오류 또는 verdict 상관이 너무 높다. |
| `REJECT_NO_INCREMENTAL_LIFT` | 독립 후보지만 baseline 대비 lift가 부족하다. |
| `REJECT_HARMFUL_CANDIDATE` | 전체 또는 non target harm이 크다. |
| `REJECT_MALFORMED_EVALUATION_INPUT` | split, cutoff, confidence, N/A, cost, hash 중 하나가 잘못됐다. |
| `INCONCLUSIVE_INSUFFICIENT_SAMPLE` | 표본이 minimum 아래다. |
| `INCONCLUSIVE_FLAKY_RESULT` | 같은 입력 반복 계산에서 threshold 판정이 바뀐다. |
| `INCONCLUSIVE_MISSING_OUTCOME_ADAPTER` | outcome fields가 없어 lift를 계산할 수 없다. |

`PASS_OFFLINE_EVALUATION`은 production 채택이 아니다. 다음 PRD의 paper cohort 검토로 넘어갈 수 있다는 뜻만 가진다.

## Fixture A: hand calculation

이 fixture는 산술 검증용이다. 표본 수가 작아서 threshold 판정에는 쓰지 않는다.

```json
{
  "fixture_name": "offline_eval_hand_calculation",
  "schema_version": "v6.offline_evaluation.fixture.1",
  "success_threshold": "0.01",
  "samples": [
    {"sample_id": "eval_s1", "split": "holdout_window", "baseline_edge": "-0.02", "candidate_edge": "0.03", "candidate_confidence": "0.70", "candidate_verdict": "HOLD", "nearest_existing_verdict": "BUY"},
    {"sample_id": "eval_s2", "split": "holdout_window", "baseline_edge": "0.01", "candidate_edge": "0.04", "candidate_confidence": "0.80", "candidate_verdict": "BUY", "nearest_existing_verdict": "HOLD"},
    {"sample_id": "eval_s3", "split": "holdout_window", "baseline_edge": "0.02", "candidate_edge": "0.00", "candidate_confidence": "0.60", "candidate_verdict": "HOLD", "nearest_existing_verdict": "BUY"},
    {"sample_id": "eval_s4", "split": "holdout_window", "baseline_edge": "-0.01", "candidate_edge": "0.02", "candidate_confidence": "0.70", "candidate_verdict": "HOLD", "nearest_existing_verdict": "SELL"}
  ],
  "expected_metrics": {
    "mean_baseline_edge": "0.000000",
    "mean_candidate_edge": "0.022500",
    "incremental_lift": "0.022500",
    "candidate_hits": 3,
    "candidate_errors": 1,
    "brier": "0.145000",
    "ece": "0.050000",
    "sample_policy": "arithmetic_only"
  }
}
```

계산:

```text
sample_gain = [0.05, 0.03, -0.02, 0.03]
incremental_lift = (0.05 + 0.03 - 0.02 + 0.03) / 4 = 0.0225
candidate_hit = [1, 1, 0, 1]
Brier = (0.09 + 0.04 + 0.36 + 0.09) / 4 = 0.1450
ECE = 0.0500
```

## Fixture B: threshold pass summary

```json
{
  "fixture_name": "offline_eval_threshold_pass_summary",
  "schema_version": "v6.offline_evaluation.summary_fixture.1",
  "candidate_id": "pcand_v6_working_capital_quality",
  "holdout_eligible_samples": 360,
  "target_error_samples": 140,
  "holdout_incremental_lift_5": "0.014000",
  "holdout_lift_bootstrap_lower_90": "0.005000",
  "target_error_lift_5": "0.021000",
  "target_error_lift_bootstrap_lower_90": "0.010000",
  "harm_rate": "0.140000",
  "non_target_harm_rate": "0.180000",
  "baseline_miss_recovery_rate": "0.230000",
  "max_error_correlation": "0.420000",
  "max_verdict_correlation": "0.480000",
  "candidate_brier_delta_vs_baseline": "-0.025000",
  "candidate_ece": "0.080000",
  "overall_na_rate": "0.090000",
  "p95_wall_ms_per_ticker": 2400,
  "timeout_rate": "0.004000",
  "ablation_remove_novel_observations_lift_drop": "0.012000",
  "expected_code": "PASS_OFFLINE_EVALUATION"
}
```

## Fixture C: rejected high-correlation clone

```json
{
  "fixture_name": "offline_eval_rejected_high_correlation_clone",
  "schema_version": "v6.offline_evaluation.summary_fixture.1",
  "candidate_id": "pcand_v6_quant_plus",
  "nearest_existing_perspective": "quant",
  "holdout_eligible_samples": 420,
  "target_error_samples": 160,
  "holdout_incremental_lift_5": "0.018000",
  "holdout_lift_bootstrap_lower_90": "0.006000",
  "max_error_correlation": "0.860000",
  "max_verdict_correlation": "0.930000",
  "primary_observations": ["signals.rsi.value", "signals.macd.histogram", "signals.bull_votes"],
  "expected_code": "REJECT_HIGH_CORRELATION_CLONE",
  "must_not_override_with_lift": true
}
```

## Fixture D: N/A and budget failure

```json
{
  "fixture_name": "offline_eval_na_budget_failure",
  "schema_version": "v6.offline_evaluation.failure_fixture.1",
  "candidate_id": "pcand_v6_working_capital_quality",
  "samples": [
    {"sample_id": "missing_required_input", "required_input": "working_capital_series", "candidate_verdict": "HOLD", "expected_error": "missing_required_input_must_be_na"},
    {"sample_id": "timeout_as_buy", "wall_ms": 7200, "candidate_verdict": "BUY", "expected_error": "timeout_must_be_na"},
    {"sample_id": "bad_confidence", "candidate_confidence": "1.20", "expected_error": "malformed_confidence"}
  ],
  "expected_code": "REJECT_MALFORMED_EVALUATION_INPUT"
}
```

## Required probes와 mutations

| probe | mutation | expected result |
| --- | --- | --- |
| `stale_dataset` | feature cutoff 이후 생성된 outcome price를 decision input에 넣는다. | `REJECT_MALFORMED_EVALUATION_INPUT` |
| `dirty_manifest` | frozen manifest hash와 실제 sample hash를 다르게 만든다. | `REJECT_MALFORMED_EVALUATION_INPUT` |
| `misleading_report` | threshold 미달인데 summary에 pass wording을 넣는다. | parser failure |
| `flaky_threshold` | 같은 입력을 20번 계산했을 때 bootstrap lower bound가 기준 위아래로 바뀐다. | `INCONCLUSIVE_FLAKY_RESULT` |
| `high_correlation_clone` | max error correlation을 `0.86`으로 바꾸고 lift를 positive로 둔다. | `REJECT_HIGH_CORRELATION_CLONE` |
| `leakage_feature` | `exit_close`, `future_return`, post cutoff article을 feature list에 넣는다. | parser failure |
| `ablation_no_drop` | novel observations 제거 뒤 lift drop을 `0.000`으로 둔다. | inconclusive |

## 검증 기준

PRD 02 parser는 다음을 확인해야 한다.

1. 문서 제목은 `# PRD 02: Offline Evaluation`이다.
2. 구현 완료 metadata가 정확히 한 번 있다.
3. Production 채택을 뜻하는 표식은 없다.
4. Fixture A부터 D까지 JSON이 parse된다.
5. Fixture A의 incremental lift, Brier, ECE가 hand calculation과 일치한다.
6. Fixture B는 threshold와 minimum sample을 만족해 `PASS_OFFLINE_EVALUATION`을 낸다.
7. Fixture C는 positive lift가 있어도 high-correlation clone으로 거절된다.
8. Fixture D는 N/A와 budget 위반을 verdict로 숨기지 못한다.
9. Split rule에 no leakage, embargo, duplicate isolation이 있다.
10. Baseline comparison, error correlation, calibration, N/A, cost, latency, ablation, minimum sample, inconclusive policy가 모두 있다.
11. Stale, dirty, misleading, flaky probe가 모두 있다.

## 구현 계약

- 경계 모델: `src/v6/offline_models.py`
- Frozen input/manifest/sample record: `src/v6/offline_evidence.py`
- Hash, duplicate, cutoff, leakage, N/A/resource 검증: `src/v6/offline_validation.py`
- Hand calculation: `src/v6/offline_metrics.py`
- Record-to-summary derivation과 deterministic bootstrap: `src/v6/offline_derive.py`
- 판정과 precedence: `src/v6/offline_evaluator.py`
- PRD 01 lineage 및 canonical hash self-verification: `src/v6/offline_artifact.py`
- Acceptance와 Oracle bypass probe: `src/v6/offline_acceptance.py`
- Evidence-level mutation corpus: `src/v6/offline_mutations.py`
- Fixture: `docs/specs/v6/fixtures/prd02-offline-evaluation.json`
- CLI: `uv run scripts/evaluate_perspective_candidate.py verify-fixture`
- Immutable build: `uv run scripts/evaluate_perspective_candidate.py build --input docs/specs/v6/fixtures/prd02-offline-evaluation.json`

모든 decimal metric은 소수점 여섯 자리 문자열로 직렬화한다. 판정 precedence는 malformed, clone, harm, no-lift, insufficient sample, missing adapter, flaky, pass 순서다. Novel observation 제거 시 lift drop이 `0.007000` 미만인 결과는 incremental evidence를 세우지 못했으므로 `REJECT_NO_INCREMENTAL_LIFT`로 닫는다. Offline pass는 PRD 03 입력 자격일 뿐 production 채택이 아니다.

### Evidence-derived schema v2

`v6.offline-evaluation-input.2`는 호출자가 summary나 metric을 제출하는 것을 허용하지 않는다. 입력은 PRD 01 artifact hash, hash-bound config, frozen manifest, content-addressed sample batch record, reported terminal code, 같은 input/config hash에 결속된 repeat run뿐이다. 각 sample batch body에는 deterministic sample ID 범위, split/window/cutoff timestamp, 세 baseline output, 기존 다섯 관점 output, candidate verdict/confidence/N/A/timeout, outcome edge, per-sample cost/latency, 세 ablation edge가 함께 고정된다.

Evaluator는 record body에서 세 baseline lift, holdout/target bootstrap lower bound, harm/recovery, error/verdict correlation, Brier/ECE, N/A coverage, p95/mean latency, cost ceiling, ablation, market/action/sample minimum을 다시 계산한다. Config, record, manifest, input hash 중 하나라도 canonical body와 다르거나 sample ID/source identity가 중복되거나 cutoff/leakage/N/A/resource 불변식을 어기면 malformed다. Repeat run 20개는 현재 재계산 결과와 동일한 input/config hash 및 terminal code를 가져야 한다.

Metric eligibility는 `split == holdout_window`, outcome adapter available, candidate edge present를 모두 만족한 sample만 포함한다. 따라서 N/A 또는 outcome-less sample은 N/A coverage의 분모에는 남지만 lift, correlation, calibration, market/action minimum과 `holdout_eligible_samples`에서는 제외한다. 현재 threshold fixture는 raw holdout 360개 중 eligible 328개, KR/US eligible 각 164개다.

Threshold evaluation은 config의 선언과 무관하게 repeat run을 정확히 20개 요구한다. Hand arithmetic input만 별도 역할로 repeat 0개를 허용한다. p95 wall time은 `min(PRD 01 max_wall_ms_per_ticker, 6000)` 이하여야 하고, LLM call, prompt token, extra fetch는 PRD 01 budget을 넘을 수 없으며 timeout rate는 `0.020000` 이하여야 한다. 이 resource gate는 clone/harm/lift보다 앞선 malformed 단계다. Holdout이 없으면 insufficient, 모든 holdout outcome adapter가 없으면 arithmetic 전에 missing adapter로 닫는다.

Eligible holdout은 있지만 eligible target-error cohort가 비어 있으면 target mean/bootstrap을 계산하지 않고 `INCONCLUSIVE_INSUFFICIENT_SAMPLE`로 닫는다. `missing_target_error_cohort` canonical-rehash mutation이 이 경계를 고정한다.

`v6.offline-evaluation-artifact.2`는 frozen hand input과 threshold input을 모두 포함한다. Artifact loader는 두 input의 모든 hash를 다시 검증하고 `OfflineSummary`와 `HandMetrics`를 재산출하므로, metric을 변조한 뒤 artifact를 재해시해도 유효해지지 않는다. `build` API는 candidate와 두 frozen input만 받고 caller-supplied summary/hand metrics 인자를 받지 않는다.

## DoneClaim 규칙

작업자는 DoneClaim에서 읽은 문서, 작성한 artifact, parser 결과, mutation 결과를 요약할 수 있다. DoneClaim은 증거를 대체하지 못한다. 증거 파일이 없거나 fixture mutation이 없거나 Read 없이 grep hit만 있으면 이 PRD의 검증은 통과하지 못한다.
