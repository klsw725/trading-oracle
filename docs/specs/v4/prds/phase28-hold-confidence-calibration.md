# PRD: Phase 28 HOLD confidence calibration
> **상태**: 📝 초안
> **SPEC 참조**: [../SPEC.md](../SPEC.md)

## 문제

현재 성과 추적은 BUY, SELL, HOLD를 같은 방식의 적중률로 다룬다. 특히 HOLD는 `abs(return) < threshold` 같은 deadband로만 판단되어, 새 거래를 만들지 않는 의사결정이라는 의미가 흐려진다. 또한 confidence label은 `high`, `moderate` 같은 표시값에 머물러 실제로 맞을 확률인지 검증할 수 없다.

Phase 28은 Phase 22, 23, 25, 26, 27의 계약을 소비해 action별 correctness event를 먼저 고정한다. 그 뒤 confidence를 그 event가 참일 calibrated probability로 평가한다. 이 문서는 calibration 계약과 실패 검증만 정의하며, 실제 가중치 변경, 프롬프트 변경, source, data, config 변경은 하지 않는다.

## 목표

1. HOLD를 `new trade none`으로 고정하고, HOLD 결과를 opportunity cost와 avoided loss로 평가한다.
2. BUY, SELL, HOLD마다 서로 다른 correctness label과 outcome을 정의한다.
3. confidence를 action, market, horizon, version별로 정의된 correctness event의 확률로 해석한다.
4. confidence bucket, reliability curve, Brier score, Expected Calibration Error를 표준 수식으로 고정한다.
5. sample eligibility와 sample weight를 명시하고 legacy, malformed, insufficient context를 calibration에서 제외한다.
6. version, market, action, horizon cohort를 섞지 않는다.
7. recalibration, promotion, rollback gate를 정의하고, 기존 adaptive weights와 prompt tuning은 gate 전까지 동결한다.

## 비목표

1. HOLD를 가상 매수나 가상 매도 PnL로 바꾸지 않는다.
2. BLOCKED와 CANDIDATE_REJECTED를 confidence calibration sample로 쓰지 않는다. Phase 26 denominator report에는 계속 보존한다.
3. legacy snapshot을 native v4 calibration sample로 승격하지 않는다.
4. 적응형 관점 가중치나 prompt tuner를 이 문서만으로 재활성화하지 않는다.

## 선행 계약

| 계약 | Phase 28에서 소비하는 부분 |
| --- | --- |
| [Phase 22 측정 계약](phase22-measurement-contract.md) | entry, exit, gross absolute return, gross benchmark excess return, HOLD는 trading PnL 없음. |
| [Phase 23 snapshot 재현성](phase23-snapshot-reproducibility.md) | numeric confidence, data cutoff, source freshness, parser, model, prompt, legacy audit-only 경계. |
| [Phase 25 시장 컨텍스트 분리](phase25-market-context-separation.md) | market, exchange, benchmark, decision regime, analysis regime 분리. |
| [Phase 26 recommendation attribution](phase26-recommendation-attribution.md) | five action taxonomy, HOLD action plan `none`, denominator 보존, numeric `confidence_probability`. |
| [Phase 27 full workflow replay](phase27-full-workflow-replay.md) | outcome replay, denominator report, stale state, dirty worktree, malformed input probes. |

## Action semantics

| action | execution intent | correctness event | primary stored outcome |
| --- | --- | --- | --- |
| `BUY` | `open_or_add` | horizon N에서 매수 방향 excess edge가 threshold 이상이다. | `buy_edge_N`, `gross_benchmark_excess_return_N`, `Y_BUY_N`. |
| `SELL` | `reduce_or_close` | horizon N에서 보유 축소가 피한 underperformance edge가 threshold 이상이다. | `sell_edge_N`, `avoided_underperformance_N`, `Y_SELL_N`. |
| `HOLD` | `none` | 새 거래를 하지 않은 결정이 alternative BUY 또는 SELL edge를 놓치지 않았다. | `hold_opportunity_cost_N`, `hold_avoided_loss_N`, `Y_HOLD_N`. |

HOLD는 신규 거래 없음이다. `portfolio_trade_id`, `order_ids`, `fill_ids`가 있으면 schema failure다. HOLD의 결과는 price path에서 계산한 counterfactual opportunity와 avoided loss이며, 실제 trade PnL이 아니다.

## Outcome definitions

모든 return은 Phase 22처럼 소수로 저장한다. threshold는 cohort config에 version과 함께 저장한다.

```text
instrument_return_N = instrument_total_return_close(exit_N) / instrument_total_return_close(entry) - 1
benchmark_return_N = benchmark_total_return_close(exit_N) / benchmark_total_return_close(entry) - 1
excess_return_N = instrument_return_N - benchmark_return_N

buy_edge_N = excess_return_N
sell_edge_N = -excess_return_N

Y_BUY_N = 1 if buy_edge_N >= buy_success_threshold_N else 0
Y_SELL_N = 1 if sell_edge_N >= sell_success_threshold_N else 0

hold_buy_opportunity_cost_N = max(0, buy_edge_N - buy_success_threshold_N)
hold_sell_opportunity_cost_N = max(0, sell_edge_N - sell_success_threshold_N) when a held position was sell-eligible, else 0
hold_opportunity_cost_N = hold_buy_opportunity_cost_N + hold_sell_opportunity_cost_N
hold_avoided_loss_N = max(0, sell_edge_N)
Y_HOLD_N = 1 if hold_opportunity_cost_N == 0 else 0
```

Default thresholds are `buy_success_threshold_N=0.01` and `sell_success_threshold_N=0.01` for v4 calibration fixtures. A later implementation may version thresholds, but it must not change old cohort labels in place.

## Confidence meaning

`confidence_probability` is the model's predicted probability that the action-specific correctness event is true for a given horizon.

```text
p_i = confidence_probability for sample i
y_i = Y_ACTION_N for sample i, where y_i is 0 or 1
```

`confidence_label` is display-only. A record with only `high`, `moderate`, or `low` is not calibration eligible. A record with `p_i < 0`, `p_i > 1`, non-numeric probability, missing action label, or non-binary outcome fails malformed input validation.

## Calibration cohorts

Calibration never pools across these keys:

| cohort key | rule |
| --- | --- |
| `calibration_contract_version` | Must match the formulas and threshold version. |
| `snapshot_schema_version` | Native v4 only for primary calibration. |
| `attribution_schema_version` | Phase 26 or later with numeric confidence. |
| `market` | `KR` and `US` are separate. |
| `exchange` | Report separately when sample size allows, else remain market-level with exchange mix shown. |
| `action` | `BUY`, `SELL`, `HOLD` never pool. |
| `horizon` | `5`, `20`, and custom N-session horizons never pool. |
| `prompt_bundle_version`, `scorer_version`, `weights_version` | Report separately. Recalibration promotion cannot hide version drift. |
| `decision_regime` and `analysis_regime` | Report separately. If too small, no-op rather than mixing. |

## Sample eligibility

| condition | eligible? | reason |
| --- | --- | --- |
| Native v4 `BUY`, `SELL`, or `HOLD` with numeric `confidence_probability` and Phase 22 `matured` outcome | yes | Calibration target is defined. |
| `BLOCKED` or `CANDIDATE_REJECTED` | no | Preserved in denominator, but no action confidence target here. |
| Legacy snapshot without raw cutoff, action taxonomy, numeric probability, or Phase 22 outcome | no | Audit-only. |
| `pending`, `insufficient_data`, `insufficient_context` | no | Target label is not defined. |
| Duplicate superseded by correction | no | Use the latest valid correction chain only. |
| HOLD with order, malformed horizon, bad hash chain, probability outside `[0, 1]` | no | Structural failure, not a calibration miss. |

## Sample weights

Default sample weight is `1.0`. A later version may add predeclared weights, but the weight must be known before outcomes are read.

```text
w_i = 1.0 by default
weighted_count = sum_i w_i
```

Allowed weight adjustments are versioned and limited to ex-ante sampling design, such as downweighting duplicate same-day ticker recommendations in the same cohort. Outcome-dependent weights are forbidden because they hide calibration error.

## Bucket and reliability formulas

Buckets are half-open intervals except the final bucket, which includes `1.0`.

```text
B1 = [0.0, 0.2)
B2 = [0.2, 0.4)
B3 = [0.4, 0.6)
B4 = [0.6, 0.8)
B5 = [0.8, 1.0]
```

For bucket `b`:

```text
W_b = sum_{i in b} w_i
avg_confidence_b = sum_{i in b} w_i * p_i / W_b
empirical_accuracy_b = sum_{i in b} w_i * y_i / W_b
reliability_gap_b = empirical_accuracy_b - avg_confidence_b
```

Empty buckets are shown with `sample_count=0` and no accuracy. They do not contribute to ECE.

## Brier score and ECE

```text
Brier = sum_i w_i * (p_i - y_i)^2 / sum_i w_i
ECE = sum_{b with W_b > 0} (W_b / sum_i w_i) * abs(empirical_accuracy_b - avg_confidence_b)
```

Lower Brier and lower ECE are better. Brier measures probability quality per sample. ECE measures bucket reliability. A cohort can improve one and worsen the other, so promotion checks both.

## Minimum sample and no-op policy

Calibration report can be printed for small cohorts, but policy changes need enough data.

| gate | default |
| --- | --- |
| Minimum total eligible samples per cohort | `100` |
| Minimum eligible samples per non-empty promotion bucket | `20` |
| Minimum horizons | Evaluate `5` and `20` separately. |
| Minimum markets | `KR` and `US` separately. |
| Small cohort behavior | Write report as `insufficient_sample`, do not recalibrate, promote, alter weights, or alter prompts. |

If any required cohort is below the minimum, the system performs no-op for that cohort. No-op means current equal or previously approved weights remain in place, prompt tuner stays frozen, and confidence display remains uncalibrated or uses the last approved calibration artifact for the exact same cohort key.

## Recalibration, promotion, and rollback

Recalibration creates a shadow calibration artifact keyed by cohort. It does not mutate historical recommendations.

Promotion requires all of the following:

1. Cohort passes minimum sample gates.
2. Holdout Brier improves by at least `0.02` over raw confidence or the current calibration artifact.
3. Holdout ECE improves by at least `0.02` and no action bucket with at least 20 samples worsens by more than `0.03`.
4. `BUY`, `SELL`, and `HOLD` reports keep their own action semantics and do not use HOLD trading PnL.
5. Phase 27 replay input hash and Phase 26 denominator counts match the promotion manifest.
6. Promotion artifact records version, cohort keys, train window, holdout window, sample counts, Brier, ECE, and rollback pointer.

Rollback is required when a promoted artifact later shows ECE regression greater than `0.05`, malformed input acceptance, cohort key mixing, stale state, or hidden legacy inclusion. Rollback restores the prior artifact and freezes adaptive weights and prompt tuning again.

## Adaptive weights and prompt tuning freeze

`compute_perspective_weights()`, `compute_regime_weights()`, `identify_underperformers()`, and `generate_tuning_suggestion()` currently depend on legacy-style hit data. Phase 28 freezes their automatic use for production decisions until the gate below passes.

| component | frozen behavior | reactivation gate |
| --- | --- | --- |
| Perspective adaptive weights | Use equal weights or last manually approved weights. | Phase 22 outcomes, Phase 23 native snapshots, Phase 26 denominator, and Phase 28 calibration all pass for the exact market/action/horizon cohort. |
| Regime weights | Do not auto-switch on legacy regime hit rate. | Native v4 decision regime and analysis regime cohorts pass minimum sample. |
| Prompt tuning | May generate audit-only suggestions, but cannot auto-apply. | Shadow paper cohort shows calibrated lift without Brier/ECE regression. |

## Five-action denominator preservation

Calibration eligibility is narrower than denominator preservation. Reports must show all five Phase 26 cohorts, then explain why only emitted `BUY`, `SELL`, and `HOLD` are calibration samples.

| cohort | denominator report | confidence calibration |
| --- | --- | --- |
| emitted `BUY` | included | eligible when outcome matured and probability valid. |
| emitted `SELL` | included | eligible when outcome matured and probability valid. |
| emitted `HOLD` | included | eligible when outcome matured and probability valid, with no trade PnL. |
| emitted `BLOCKED` | included | excluded from this calibration target. |
| `CANDIDATE_REJECTED` | included | excluded from this calibration target. |

## Concrete JSON fixture

This fixture is intentionally small so Brier and ECE are hand-computable. It is not large enough for promotion.

```json
{
  "schema_version": "v4.hold_confidence_calibration.phase28.1",
  "cohort_key": {
    "calibration_contract_version": "phase28.1",
    "snapshot_schema_version": "v4.snapshot.phase23.1",
    "attribution_schema_version": "v4.recommendation_attribution.phase26.1",
    "market": "KR_US_fixture_mixed_for_arithmetic_only",
    "action_scope": "BUY_SELL_HOLD_fixture",
    "horizon": 5,
    "prompt_bundle_version": "perspectives-v4.2026.08",
    "scorer_version": "consensus-scorer-v2026.08",
    "weights_version": "equal-v1"
  },
  "thresholds": {
    "buy_success_threshold": "0.01",
    "sell_success_threshold": "0.01"
  },
  "bucket_edges": ["0.0", "0.2", "0.4", "0.6", "0.8", "1.0"],
  "samples": [
    {
      "sample_id": "cal_v4_buy_hit",
      "recommendation_id": "rec_v4_buy_hit",
      "action": "BUY",
      "position_state_at_decision": "flat",
      "confidence_probability": "0.70",
      "sample_weight": "1.0",
      "instrument_return": "0.06",
      "benchmark_return": "0.03",
      "buy_edge": "0.03",
      "sell_edge": "-0.03",
      "correctness_label": "Y_BUY_5",
      "correctness_outcome": 1,
      "brier_component": "0.09"
    },
    {
      "sample_id": "cal_v4_sell_miss",
      "recommendation_id": "rec_v4_sell_miss",
      "action": "SELL",
      "position_state_at_decision": "held_long",
      "confidence_probability": "0.70",
      "sample_weight": "1.0",
      "instrument_return": "0.05",
      "benchmark_return": "0.01",
      "buy_edge": "0.04",
      "sell_edge": "-0.04",
      "correctness_label": "Y_SELL_5",
      "correctness_outcome": 0,
      "brier_component": "0.49"
    },
    {
      "sample_id": "cal_v4_hold_avoided_loss",
      "recommendation_id": "rec_v4_hold_avoided_loss",
      "action": "HOLD",
      "position_state_at_decision": "flat",
      "confidence_probability": "0.90",
      "sample_weight": "1.0",
      "instrument_return": "-0.05",
      "benchmark_return": "0.01",
      "buy_edge": "-0.06",
      "sell_edge": "0.06",
      "hold_opportunity_cost": "0.00",
      "hold_avoided_loss": "0.06",
      "correctness_label": "Y_HOLD_5",
      "correctness_outcome": 1,
      "brier_component": "0.01"
    },
    {
      "sample_id": "cal_v4_hold_missed_upside",
      "recommendation_id": "rec_v4_hold_missed_upside",
      "action": "HOLD",
      "position_state_at_decision": "flat",
      "confidence_probability": "0.90",
      "sample_weight": "1.0",
      "instrument_return": "0.08",
      "benchmark_return": "0.01",
      "buy_edge": "0.07",
      "sell_edge": "-0.07",
      "hold_opportunity_cost": "0.06",
      "hold_avoided_loss": "0.00",
      "correctness_label": "Y_HOLD_5",
      "correctness_outcome": 0,
      "brier_component": "0.81"
    }
  ],
  "expected_bucket_report": [
    {
      "bucket": "[0.6,0.8)",
      "weighted_count": "2.0",
      "avg_confidence": "0.70",
      "empirical_accuracy": "0.50",
      "absolute_gap": "0.20",
      "ece_component": "0.10"
    },
    {
      "bucket": "[0.8,1.0]",
      "weighted_count": "2.0",
      "avg_confidence": "0.90",
      "empirical_accuracy": "0.50",
      "absolute_gap": "0.40",
      "ece_component": "0.20"
    }
  ],
  "expected_metrics": {
    "weighted_count": "4.0",
    "brier_score": "0.35",
    "ece": "0.30",
    "promotion_state": "insufficient_sample_no_op"
  }
}
```

Hand calculation:

```text
Brier = (0.09 + 0.49 + 0.01 + 0.81) / 4 = 1.40 / 4 = 0.35
Bucket [0.6,0.8): avg confidence 0.70, accuracy (1 + 0) / 2 = 0.50, ECE part (2 / 4) * 0.20 = 0.10
Bucket [0.8,1.0]: avg confidence 0.90, accuracy (1 + 0) / 2 = 0.50, ECE part (2 / 4) * 0.40 = 0.20
ECE = 0.10 + 0.20 = 0.30
```

## Failure fixtures

### Insufficient sample no-op

```json
{
  "fixture": "insufficient_sample_no_op",
  "cohort": {"market": "KR", "action": "HOLD", "horizon": 5},
  "eligible_sample_count": 4,
  "minimum_required": 100,
  "expected_report_state": "insufficient_sample",
  "expected_policy_change": "no_op",
  "must_not_change": ["adaptive_weights", "regime_weights", "prompt_tuning", "consensus_threshold"]
}
```

### Legacy excluded

```json
{
  "fixture": "legacy_excluded_from_calibration",
  "legacy_snapshot_path": "data/snapshots/2026-08-05.json",
  "consensus_confidence": "high",
  "confidence_probability": null,
  "decision_data_cutoff_at": "unknown",
  "phase22_outcome_state": "audit_overlay_only",
  "calibration_eligible": false,
  "exclusion_reason": "legacy_missing_numeric_probability_cutoff_and_native_outcome",
  "must_preserve_denominator_audit": true
}
```

### Malformed probability and outcome

```json
{
  "fixture": "malformed_probability_outcome",
  "samples": [
    {"sample_id": "bad_probability", "action": "BUY", "confidence_probability": "1.20", "correctness_outcome": 1},
    {"sample_id": "bad_outcome", "action": "HOLD", "confidence_probability": "0.60", "correctness_outcome": "maybe"},
    {"sample_id": "hold_with_trade", "action": "HOLD", "confidence_probability": "0.60", "correctness_outcome": 1, "portfolio_trade_id": "ptrade_v4_bad"}
  ],
  "expected_result": "fail_malformed_input_before_metric_calculation"
}
```

## Required probes

| probe | detection rule | expected result |
| --- | --- | --- |
| `stale_state` | latest close or source `as_of` after decision cutoff is used as an N-session outcome | fail calibration QA |
| `dirty_worktree` | recalibration or promotion starts while source, data, or config state differs from the declared replay input hash | block promotion before artifact write |
| `misleading_output` | report says calibrated, promoted, or passed while cohort is insufficient, stale, malformed, or legacy-only | fail report validation |
| `malformed_probability_outcome` | probability outside `[0, 1]`, non-numeric probability, non-binary outcome, HOLD with trade linkage | fail before Brier or ECE calculation |
| `flaky_statistical_threshold` | promotion result changes across repeated runs over the same fixed input, or bootstrap interval crosses the required lift threshold | no-op and mark `statistically_inconclusive` |

Other classes are N/A for this PRD unless a later implementation adds browser, broker, network, or live provider calls.

## Deterministic uv assertions

Downstream implementation must add a deterministic `uv run` assertion surface before enabling recalibration.

Required assertions:

1. Every JSON fixture parses.
2. BUY, SELL, and HOLD labels are computed from action-specific formulas.
3. HOLD with `portfolio_trade_id`, `order_ids`, or `fill_ids` fails.
4. Brier score and ECE match the fixture values using decimal arithmetic.
5. Insufficient sample produces no-op.
6. Legacy fixture is excluded from calibration but remains visible in denominator audit.
7. Cohort keys do not mix version, market, action, or horizon.
8. Adaptive weights and prompt tuning remain frozen until promotion gate passes.

## Acceptance criteria

1. HOLD is defined as `new trade none`, with opportunity cost and avoided loss but no trade PnL.
2. BUY, SELL, and HOLD each have explicit correctness labels and outcomes.
3. Confidence is a calibrated probability of the defined correctness event, not a display label.
4. Bucket, reliability curve, Brier score, and ECE formulas are specified.
5. Eligibility, sample weights, minimum samples, and no-op behavior are explicit.
6. Cohorts are separated by version, market, action, and horizon.
7. Recalibration, promotion, and rollback rules freeze adaptive weights and prompt tuning until the gate passes.
8. Fixtures cover hand-computable Brier/ECE, BUY/SELL/HOLD outcomes, insufficient sample, legacy exclusion, malformed probability/outcome, and HOLD trade failure.
