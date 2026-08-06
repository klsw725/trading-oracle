# PRD 03: Paper Cohort
> **상태**: 📝 초안
> **SPEC 참조**: [v6 SPEC](../SPEC.md)

## 문서 범위

이 문서는 PRD 02에서 `PASS_OFFLINE_EVALUATION`을 받은 새 투자 관점 후보를 paper cohort에서 shadow로 관찰하는 계약을 정의한다. 입력은 후보 제안서, 오프라인 평가 summary, 생산 합의 산출물, paper 실행 설정, 선택적 outcome adapter다. 출력은 후보가 생산 합의에 들어갈 수 있는지가 아니라, 다음 PRD의 lifecycle 검토로 보낼 수 있는지에 대한 shadow evidence다.

이 문서는 v6 내부 PRD 03이다. v4 attribution artifact가 있으면 outcome과 denominator adapter로 쓸 수 있지만 필수는 아니다. adapter가 없으면 outcome 관련 verdict는 `INCONCLUSIVE_PENDING_ADAPTER`나 `PENDING_OUTCOME`으로 남긴다. adapter 부재를 근거로 후보를 생산 vote에 넣을 수 없다.

## 문제

오프라인 평가는 고정 fixture에서 후보가 추가 정보를 주는지 확인한다. 그러나 실제 추천 흐름에서는 데이터 freshness, latency, N/A 비율, 관점 간 disagreement, 시장 구간 drift가 달라질 수 있다. 후보를 바로 생산 합의에 넣으면 기존 `src/consensus/voter.py`의 다섯 관점 고정 vote가 바뀌고, 기존 사용자 행동과 성과 attribution을 오염시킨다.

paper cohort는 이 간극을 메우되, 더 엄격한 경계가 필요하다. 후보는 실제 입력을 보고 shadow verdict를 만들 수 있지만, 그 verdict는 사용자에게 노출되는 생산 vote, scorer input, deliberation input, portfolio sizing, order intent, prompt tuning, adaptive weight에 영향을 주면 안 된다.

## 목표

1. Shadow verdict와 생산 verdict를 분리한다.
2. 후보가 생산 vote, scorer, deliberation, portfolio output을 바꾸지 못하게 한다.
3. Deterministic cohort assignment로 같은 입력이 항상 같은 paper 처리 결과를 갖게 한다.
4. Append-only cohort ledger와 hash chain으로 관찰 결과를 추적한다.
5. Sample horizon, minimum duration, minimum sample을 명시한다.
6. Drift monitoring과 stop condition을 정의한다.
7. Contamination prevention을 fixture와 mutation으로 검증한다.
8. Cancel과 resume이 중복 shadow verdict나 ledger mutation을 만들지 못하게 한다.

## 비목표

1. 후보를 production 관점으로 채택하지 않는다.
2. `ALL_PERSPECTIVES`, `compute_consensus`, deliberation, portfolio sizing을 바꾸지 않는다.
3. Paper 결과로 adaptive weight, prompt tuning, scorer threshold를 바꾸지 않는다.
4. Broker 주문, paper portfolio fill, live portfolio mutation을 만들지 않는다.
5. v4나 v8 산출물을 필수 선행 조건으로 삼지 않는다.
6. 특정 후보를 영구 관점으로 예약하지 않는다.

## 입력 계약

| input | required | rule |
| --- | --- | --- |
| `candidate_proposal` | yes | PRD 01을 통과한 후보다. `candidate_id`, `candidate_version`, `hypothesis_id`, owner, budget이 있어야 한다. |
| `offline_evaluation_summary` | yes | PRD 02의 `PASS_OFFLINE_EVALUATION`이어야 한다. 다른 code면 paper run을 만들 수 없다. |
| `production_decision_snapshot` | yes | 기존 다섯 관점 생산 결과다. 후보 실행 전에 고정하며 후보 결과로 다시 계산하지 않는다. |
| `paper_assignment_policy` | yes | cohort salt, sample rate, eligibility, horizon, duration이 있다. |
| `shadow_candidate_output` | yes | 같은 decision cutoff만 보고 만든 후보 verdict, confidence, N/A, cost, latency다. |
| `outcome_adapter` | optional | v4 attribution 또는 별도 fixture adapter다. 없으면 outcome metric은 pending이다. |

필수 envelope 예시는 다음과 같다.

```json
{
  "paper_input": {
    "schema_version": "v6.paper_cohort.1",
    "candidate_id": "pcand_v6_working_capital_quality",
    "candidate_version": "working_capital_quality.0.1",
    "hypothesis_id": "hyp_v6_working_capital_quality_001",
    "offline_evaluation_report_id": "eval_v6_working_capital_quality_20260806",
    "production_decision_id": "prod_decision_20260806_005930",
    "assignment_policy_id": "paper_policy_v6_20260806",
    "outcome_adapter": "optional_v4_attribution_adapter"
  }
}
```

## Shadow verdict

Shadow verdict는 후보가 생산 입력과 같은 cutoff 안에서 낸 paper 전용 판단이다.

| field | required | rule |
| --- | --- | --- |
| `shadow_verdict` | yes | `BUY`, `SELL`, `HOLD`, `N/A` 중 하나다. |
| `shadow_confidence` | yes | 0.0에서 1.0 사이 숫자다. `N/A`면 0.0이다. |
| `shadow_reason` | yes | 후보의 독립 가설과 관측값을 연결한다. |
| `shadow_action` | yes | `buy`, `sell`, `hold`, `none` 중 하나다. `N/A`면 `none`이다. |
| `production_verdict_before` | yes | 후보 실행 전에 이미 고정된 생산 합의 verdict다. |
| `production_verdict_after` | yes | 반드시 before와 같아야 한다. 다르면 contamination이다. |
| `vote_effect` | yes | 항상 `none`이어야 한다. |

Paper 결과는 vote에 영향을 주지 않는다. 이 규칙은 품질이 좋아도, 비용이 낮아도, drift가 안정적이어도 예외가 없다. 생산 합의는 기존 다섯 관점 output만 사용한다.

## Production isolation

Isolation boundary는 다음을 금지한다.

| boundary | forbidden mutation |
| --- | --- |
| `src/consensus/voter.py` | `ALL_PERSPECTIVES`에 후보 추가, 반환 순서 변경, max workers 변경 |
| `src/consensus/scorer.py` | 후보 verdict를 vote count, weighted vote, majority reasoning에 포함 |
| deliberation | 후보 shadow reason을 다수 또는 소수 근거로 주입 |
| portfolio sizing | shadow verdict로 매수, 매도, hold plan 생성 |
| performance tuning | paper outcome으로 weight, prompt, threshold 자동 변경 |
| output surface | 사용자용 추천 verdict를 shadow verdict로 덮어쓰기 |

검증기는 `production_verdict_before == production_verdict_after`, `vote_effect == "none"`, `shadow_visible_to_user == false`를 동시에 확인해야 한다.

## Deterministic cohort assignment

Assignment는 난수를 쓰지 않는다. 같은 후보, 같은 생산 결정, 같은 policy면 항상 같은 assignment가 나온다.

```text
assignment_seed = candidate_id + "|" + candidate_version + "|" + production_decision_id + "|" + emitted_at + "|" + ticker + "|" + market + "|" + policy_salt
assignment_hash = sha256(assignment_seed)
assignment_bucket = int(first_8_hex(assignment_hash), 16) mod 10000
assigned_to_paper = assignment_bucket < sample_rate_bps
```

| policy field | required | rule |
| --- | --- | --- |
| `policy_salt` | yes | Policy 생성 시 고정한다. 후보 outcome을 본 뒤 바꾸면 dirty policy다. |
| `sample_rate_bps` | yes | 1에서 10000 사이다. Default는 10000이다. |
| `eligible_markets` | yes | `KR`, `US`, `ALL` 중 명시한다. Unknown market은 제외한다. |
| `eligible_actions` | yes | 생산 verdict 기준 action 목록이다. Shadow verdict 기준으로 eligibility를 정하지 않는다. |
| `horizons` | yes | 기본 `[5, 20]` market sessions다. |
| `min_duration_market_sessions` | yes | 기본 60 동일 시장 session이다. |
| `min_eligible_samples` | yes | 기본 300이다. |
| `min_target_disagreement_samples` | yes | 기본 100이다. |

Assignment 정책은 paper run 시작 뒤 바꾸지 않는다. 바꿔야 하면 기존 run을 cancel하고 새 `policy_id`로 새 run을 만든다.

## Cohort ledger

Ledger는 append-only다. Correction은 새 event로 남기며 기존 event를 덮어쓰지 않는다.

| event type | purpose |
| --- | --- |
| `paper_run_started` | 후보, policy, offline report, production isolation seed를 고정한다. |
| `sample_assigned` | deterministic assignment 결과와 생산 verdict snapshot hash를 기록한다. |
| `shadow_verdict_recorded` | 후보의 shadow verdict, confidence, N/A, cost, latency를 기록한다. |
| `outcome_observed` | 선택적 adapter에서 mature horizon outcome을 연결한다. |
| `drift_signal_recorded` | drift metric과 threshold 초과 여부를 기록한다. |
| `paper_run_cancelled` | 중단 reason과 resume checkpoint를 기록한다. |
| `paper_run_resumed` | 같은 run에서 다음 ledger index를 이어 쓴다. |
| `paper_run_stopped` | stop condition과 다음 PRD 검토 가능 여부를 기록한다. |

Ledger event는 다음 필드를 가진다.

```json
{
  "event_id": "pledge_v6_0003",
  "schema_version": "v6.paper_cohort.ledger.1",
  "run_id": "paper_run_v6_working_capital_quality_20260806",
  "event_index": 3,
  "event_type": "shadow_verdict_recorded",
  "occurred_at": "2026-08-06T09:35:00+09:00",
  "entity_ref_id": "paper_sample_v6_005930_20260806",
  "prev_event_hash": "sha256:1111111111111111111111111111111111111111111111111111111111111111",
  "payload_hash": "sha256:2222222222222222222222222222222222222222222222222222222222222222",
  "event_hash": "sha256:3333333333333333333333333333333333333333333333333333333333333333",
  "payload": {
    "shadow_verdict": "HOLD",
    "shadow_confidence": "0.72",
    "vote_effect": "none",
    "shadow_visible_to_user": false
  }
}
```

`event_hash`는 `schema_version`, `run_id`, `event_index`, `event_type`, `entity_ref_id`, `prev_event_hash`, `payload_hash`를 canonical JSON으로 serialize한 뒤 sha256으로 계산한다.

## Sample horizon and minimum duration

Paper cohort는 최소 기간과 최소 표본을 모두 만족하기 전에는 다음 PRD 검토로 넘어가지 않는다.

| requirement | default |
| --- | --- |
| Minimum running duration | 60 동일 시장 session |
| Minimum assigned samples | 300 |
| Minimum target disagreement samples | 100 |
| Minimum mature horizon coverage | assigned samples 중 70 percent 이상이 5 session horizon mature |
| Long horizon check | 20 session horizon은 별도 report로 남긴다. 5와 평균내지 않는다. |
| Candidate N/A ceiling | 전체 0.15 이하, target disagreement 0.20 이하 |
| Latency ceiling | PRD 01 budget 이하, p95 최대 6000 ms |

Minimum을 만족하지 못한 report는 `INCONCLUSIVE_INSUFFICIENT_PAPER_SAMPLE`이다. 이 결과는 생산 vote를 바꾸지 않는다.

## Drift monitoring

Drift는 후보가 실제 흐름에서 안정적인지 보기 위한 signal이다. Drift signal은 ledger에 기록하지만 생산 동작을 바꾸지 않는다.

| drift metric | threshold | result |
| --- | --- | --- |
| `input_schema_drift_rate` | 0.02 초과 | `STOP_SCHEMA_DRIFT` |
| `candidate_na_rate` | policy ceiling 초과 | `STOP_COVERAGE_DRIFT` |
| `shadow_vote_distribution_shift` | offline holdout 대비 PSI 0.20 초과 | `STOP_VERDICT_DRIFT` |
| `latency_p95_ms` | PRD 01 budget 초과 | `STOP_LATENCY_DRIFT` |
| `production_shadow_disagreement_rate` | 0.80 초과 또는 0.02 미만 | review flag. 단독 stop은 아님. |
| `outcome_adapter_staleness_rate` | 0.10 초과 | outcome report pending |

Drift threshold를 outcome을 본 뒤 조정하면 dirty policy다. Dirty policy는 run을 `STOP_CONTAMINATION_DETECTED`로 닫는다.

## Stop conditions

Paper run은 다음 code 중 하나로 닫힌다.

| stop code | meaning | next step |
| --- | --- | --- |
| `STOP_READY_FOR_LIFECYCLE_REVIEW` | minimum duration, sample, drift, isolation, outcome evidence가 모두 통과했다. | 다음 PRD에서만 검토한다. |
| `STOP_REJECT_HARMFUL_SHADOW` | shadow outcome이 baseline보다 큰 harm을 보인다. | 후보 폐기 또는 새 후보 version 요구. |
| `STOP_INCONCLUSIVE_INSUFFICIENT_SAMPLE` | 기간이나 표본이 부족하다. | 생산 영향 없이 관찰 연장 또는 새 policy. |
| `STOP_INCONCLUSIVE_PENDING_ADAPTER` | outcome adapter가 없어 outcome metric을 닫을 수 없다. | adapter 제공 전까지 보류. |
| `STOP_SCHEMA_DRIFT` | 입력 schema가 후보 계약과 맞지 않는다. | 후보 parser 수정 후 새 version. |
| `STOP_CONTAMINATION_DETECTED` | 생산 vote, scorer, portfolio, tuning이 shadow를 읽었다. | run 폐기. 생산 산출물 감사. |
| `STOP_CANCELLED_BY_OPERATOR` | 운영자가 paper run을 중단했다. | resume 가능 checkpoint가 있으면 이어 쓸 수 있다. |

`STOP_READY_FOR_LIFECYCLE_REVIEW`도 production 채택이 아니다. Paper는 증거를 만들 뿐이며 vote를 바꾸지 않는다.

## Contamination prevention

Contamination은 paper 산출물이 생산 경로에 영향을 주는 모든 경우다.

| contamination type | parser rule |
| --- | --- |
| `vote_mutation` | 생산 vote summary에 후보 perspective 이름이 있으면 fail. |
| `reasoning_injection` | majority 또는 minority reasoning에 shadow reason이 있으면 fail. |
| `portfolio_mutation` | order intent, position sizing, live portfolio에 shadow action이 있으면 fail. |
| `training_feedback` | paper outcome으로 prompt, weight, threshold를 자동 변경하면 fail. |
| `eligibility_leakage` | shadow verdict나 future outcome으로 assignment eligibility를 바꾸면 fail. |
| `adapter_dependency_claim` | optional adapter가 없는데 success로 표시하면 fail. |

Contamination이 한 번이라도 발견되면 해당 run은 lifecycle 검토로 보낼 수 없다.

## Cancel and resume

Cancel은 ledger에 `paper_run_cancelled` event를 추가한다. Resume은 같은 `run_id`, 같은 `policy_id`, 같은 `candidate_version`, 같은 last event hash에서만 가능하다.

Resume 규칙은 다음과 같다.

1. 마지막 event hash가 checkpoint와 같아야 한다.
2. 이미 기록한 `shadow_verdict_recorded` sample은 다시 쓰지 않는다.
3. Outcome만 늦게 도착한 경우 `outcome_observed` event만 추가한다.
4. Policy, sample rate, eligibility, horizon이 바뀌면 resume이 아니라 새 run이다.
5. Repeated resume이 같은 sample에 다른 shadow verdict를 쓰면 `STOP_CONTAMINATION_DETECTED`다.

## Fixture A: happy shadow run

```json
{
  "fixture_name": "paper_cohort_happy_shadow_run",
  "schema_version": "v6.paper_cohort.fixture.1",
  "run_id": "paper_run_v6_working_capital_quality_20260806",
  "candidate_id": "pcand_v6_working_capital_quality",
  "candidate_version": "working_capital_quality.0.1",
  "offline_code": "PASS_OFFLINE_EVALUATION",
  "assignment": {
    "policy_id": "paper_policy_v6_20260806",
    "policy_salt": "salt_v6_paper_20260806",
    "sample_rate_bps": 10000,
    "assignment_bucket": 2412,
    "assigned_to_paper": true,
    "horizons": [5, 20]
  },
  "production": {
    "production_decision_id": "prod_decision_20260806_005930",
    "perspectives": ["kwangsoo", "ouroboros", "quant", "macro", "value"],
    "vote_summary_before": {"BUY": 3, "SELL": 0, "HOLD": 2, "N/A": 0},
    "consensus_verdict_before": "BUY",
    "vote_summary_after": {"BUY": 3, "SELL": 0, "HOLD": 2, "N/A": 0},
    "consensus_verdict_after": "BUY"
  },
  "shadow": {
    "perspective": "working_capital_quality",
    "shadow_verdict": "HOLD",
    "shadow_confidence": "0.72",
    "shadow_action": "hold",
    "vote_effect": "none",
    "shadow_visible_to_user": false
  },
  "paper_metrics": {
    "assigned_samples": 360,
    "target_disagreement_samples": 130,
    "running_duration_market_sessions": 72,
    "candidate_na_rate": "0.08",
    "latency_p95_ms": 2300,
    "input_schema_drift_rate": "0.000",
    "shadow_vote_distribution_psi": "0.08"
  },
  "expected_stop_code": "STOP_READY_FOR_LIFECYCLE_REVIEW",
  "production_must_remain_unchanged": true
}
```

## Fixture B: production vote mutation blocked

```json
{
  "fixture_name": "paper_cohort_blocks_production_vote_mutation",
  "schema_version": "v6.paper_cohort.failure_fixture.1",
  "candidate_id": "pcand_v6_working_capital_quality",
  "production_before": {
    "perspectives": ["kwangsoo", "ouroboros", "quant", "macro", "value"],
    "vote_summary": {"BUY": 3, "SELL": 0, "HOLD": 2, "N/A": 0},
    "consensus_verdict": "BUY"
  },
  "production_after_mutation": {
    "perspectives": ["kwangsoo", "ouroboros", "quant", "macro", "value", "working_capital_quality"],
    "vote_summary": {"BUY": 3, "SELL": 0, "HOLD": 3, "N/A": 0},
    "consensus_verdict": "DIVIDED"
  },
  "shadow": {
    "shadow_verdict": "HOLD",
    "vote_effect": "mutated_production_vote"
  },
  "expected_error": "STOP_CONTAMINATION_DETECTED",
  "blocked_reason": "paper_result_changed_production_vote"
}
```

## Fixture C: cancel and resume

```json
{
  "fixture_name": "paper_cohort_cancel_resume",
  "schema_version": "v6.paper_cohort.resume_fixture.1",
  "run_id": "paper_run_v6_working_capital_quality_20260806",
  "policy_id": "paper_policy_v6_20260806",
  "candidate_version": "working_capital_quality.0.1",
  "checkpoint": {
    "last_event_index": 4,
    "last_event_hash": "sha256:4444444444444444444444444444444444444444444444444444444444444444",
    "recorded_sample_ids": ["paper_sample_v6_005930_20260806"]
  },
  "resume_request": {
    "run_id": "paper_run_v6_working_capital_quality_20260806",
    "policy_id": "paper_policy_v6_20260806",
    "candidate_version": "working_capital_quality.0.1",
    "prev_event_hash": "sha256:4444444444444444444444444444444444444444444444444444444444444444",
    "next_event_index": 5,
    "write_sample_id": "paper_sample_v6_000660_20260806"
  },
  "expected_resume_allowed": true,
  "duplicate_shadow_verdict_allowed": false
}
```

## Fixture D: optional adapter pending

```json
{
  "fixture_name": "paper_cohort_optional_adapter_pending",
  "schema_version": "v6.paper_cohort.adapter_fixture.1",
  "run_id": "paper_run_v6_working_capital_quality_20260806",
  "outcome_adapter": null,
  "assigned_samples": 340,
  "running_duration_market_sessions": 68,
  "shadow_verdicts_recorded": 340,
  "outcome_metrics_available": false,
  "expected_stop_code": "STOP_INCONCLUSIVE_PENDING_ADAPTER",
  "must_not_mark_success": true,
  "production_vote_effect": "none"
}
```

## Required probes and mutations

| probe | mutation | expected result |
| --- | --- | --- |
| `happy_shadow` | Fixture A as written. | `STOP_READY_FOR_LIFECYCLE_REVIEW`, production unchanged. |
| `production_vote_mutation` | Add candidate to production perspectives and vote summary. | `STOP_CONTAMINATION_DETECTED`. |
| `json_missing_vote_effect` | Remove `shadow.vote_effect`. | parser failure. |
| `json_bad_confidence` | Set `shadow_confidence` to `1.20`. | parser failure. |
| `status_mutation_ready_too_early` | Set ready code with only 120 samples or 30 sessions. | `STOP_INCONCLUSIVE_INSUFFICIENT_SAMPLE`. |
| `status_mutation_adapter_missing_success` | Mark adapter missing fixture as ready. | `STOP_INCONCLUSIVE_PENDING_ADAPTER`. |
| `cancel_resume_hash_mismatch` | Resume with a different `prev_event_hash`. | resume rejected. |
| `repeated_resume_duplicate_shadow` | Write the same sample shadow verdict twice. | `STOP_CONTAMINATION_DETECTED`. |
| `dirty_policy` | Change `sample_rate_bps` after outcome observation. | `STOP_CONTAMINATION_DETECTED`. |
| `stale_adapter` | Mark stale outcome adapter as fresh. | parser failure. |
| `misleading_report` | Say paper affected vote and still passed. | parser failure. |
| `malformed_ledger` | Break event index sequence or hash chain. | parser failure. |

## 검증 기준

PRD 03 parser는 다음을 확인해야 한다.

1. 문서 제목은 `# PRD 03: Paper Cohort`이다.
2. 바로 다음 줄에 초안 metadata가 정확히 한 번 있다.
3. 생산 채택을 뜻하는 표식은 없다.
4. Fixture A부터 D까지 JSON이 parse된다.
5. Fixture A는 shadow verdict를 기록하지만 생산 perspectives, vote summary, consensus verdict가 바뀌지 않는다.
6. Fixture B는 후보가 생산 vote에 들어가면 `STOP_CONTAMINATION_DETECTED`로 실패한다.
7. Fixture C는 같은 hash와 같은 policy에서만 resume을 허용한다.
8. Fixture D는 optional adapter 부재를 success로 바꾸지 않는다.
9. Deterministic assignment formula와 ledger hash chain 규칙이 있다.
10. Sample horizon, minimum duration, drift monitoring, stop condition, contamination prevention이 모두 있다.
11. Required probes는 JSON mutation, status mutation, stale, dirty, misleading, malformed, cancel, resume을 포함한다.
