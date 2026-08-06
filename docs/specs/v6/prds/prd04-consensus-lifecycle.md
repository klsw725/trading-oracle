# PRD 04: Consensus Lifecycle
> **상태**: 📝 초안
> **SPEC 참조**: [v6 SPEC](../SPEC.md)

## 문서 범위

이 문서는 PRD 03에서 `STOP_READY_FOR_LIFECYCLE_REVIEW`를 받은 새 투자 관점 후보가 제한된 생산 합의에 들어가고, 관찰되고, 되돌려지고, 은퇴되는 계약을 정의한다. 입력은 후보 제안서, 오프라인 평가 summary, paper cohort summary, 현재 생산 합의 설정, 운영 승인 기록이다. 출력은 특정 후보 version이 어떤 lifecycle state에 있고 어떤 weight와 deliberation 권한을 갖는지에 대한 감사 가능한 정책 artifact다.

이 문서는 v6 내부 PRD 04다. 후보가 좋은 paper 결과를 냈더라도 자동으로 영구 관점이 되지 않는다. 모든 생산 영향은 version, weight cap, 기간, rollback pointer, incident threshold, audit record를 가져야 한다.

## 문제

PRD 01부터 PRD 03까지는 후보를 제안하고, 오프라인에서 검증하고, paper cohort에서 shadow로 관찰한다. 그러나 이 증거만으로 후보를 기존 다섯 관점과 같은 힘으로 합의기에 넣으면 세 가지 문제가 생긴다.

1. 기존 `compute_consensus()`는 weight dict를 받을 수 있으므로 후보 weight가 잘못 주입되면 합의 threshold가 즉시 바뀐다.
2. `deliberate()`는 분기 또는 약한 합의에서 관점 reasoning을 재판정 prompt에 넣으므로 후보 reasoning이 기존 관점의 판단을 과하게 끌 수 있다.
3. 후보 version이 바뀌거나 오류율이 급등해도 rollback과 retirement가 없으면 이전 추천과 새 추천의 attribution이 섞인다.

Lifecycle 계약은 후보를 생산 합의에 넣을 수 있는 길을 열되, blast radius를 작게 잡고 되돌릴 수 있게 한다.

## 목표

1. 후보 version별 lifecycle states와 허용 전이를 정의한다.
2. 제한 승격 조건과 initial weight cap을 고정한다.
3. Deliberation 참여 권한을 scorer 참여와 분리한다.
4. Rollback, retirement, version coexistence를 감사 가능한 artifact로 남긴다.
5. Incident threshold와 중단, 재개, 취소 규칙을 정의한다.
6. 후보가 자동 영구 관점이 되지 못하게 한다.
7. JSON, state, threshold, interruption mutation으로 parser 실패를 검증한다.

## 비목표

1. 새 후보를 기본 다섯 관점으로 편입하지 않는다.
2. 기존 `kwangsoo`, `ouroboros`, `quant`, `macro`, `value` prompt를 고치지 않는다.
3. 자동 weight 학습, prompt tuning, portfolio sizing 정책을 바꾸지 않는다.
4. Paper 결과만으로 생산 추천을 소급 변경하지 않는다.
5. Broker 주문, paper fill, live portfolio mutation을 만들지 않는다.

## 입력 계약

| input | required | rule |
| --- | --- | --- |
| `candidate_proposal` | yes | PRD 01을 통과한 같은 `candidate_id`, `candidate_version`, `hypothesis_id`다. |
| `offline_evaluation_summary` | yes | PRD 02의 `PASS_OFFLINE_EVALUATION`이어야 한다. |
| `paper_cohort_summary` | yes | PRD 03의 `STOP_READY_FOR_LIFECYCLE_REVIEW`이어야 한다. |
| `current_consensus_policy` | yes | 현재 생산 관점 목록, scorer version, weight map, deliberation policy를 담는다. |
| `operator_approval` | yes | 사람이 제한 승격, rollback, retirement 중 하나를 승인한 기록이다. |
| `incident_report` | optional | 오류율 급등, contamination, latency, parser failure 같은 중단 근거다. |

필수 envelope 예시는 다음과 같다.

```json
{
  "lifecycle_input": {
    "schema_version": "v6.consensus_lifecycle.1",
    "candidate_id": "pcand_v6_working_capital_quality",
    "candidate_version": "working_capital_quality.0.1",
    "hypothesis_id": "hyp_v6_working_capital_quality_001",
    "offline_evaluation_report_id": "eval_v6_working_capital_quality_20260806",
    "paper_run_id": "paper_run_v6_working_capital_quality_20260806",
    "current_policy_id": "consensus_policy_v6_20260806",
    "operator_approval_id": "approval_v6_limited_promotion_20260806"
  }
}
```

## Lifecycle states

State는 후보 version 단위로 기록한다. 같은 후보 이름이라도 version이 다르면 별도 lifecycle record다.

| lifecycle_state | meaning | production vote | next allowed states |
| --- | --- | --- | --- |
| `proposal_received` | PRD 01 후보가 접수됐다. | no | `offline_passed`, `rejected` |
| `offline_passed` | PRD 02 평가를 통과했다. | no | `paper_ready`, `rejected` |
| `paper_ready` | PRD 03 shadow 관찰이 lifecycle 검토 가능 상태로 닫혔다. | no | `limited_production`, `rejected` |
| `limited_production` | capped weight로 생산 scorer에 참여한다. | yes, capped | `renewal_review`, `rolled_back`, `retired` |
| `renewal_review` | 제한 기간이 끝났거나 threshold 재검토가 필요하다. | yes only if current approval has not expired | `limited_production`, `rolled_back`, `retired` |
| `rolled_back` | 이전 승인 policy로 되돌렸다. | no for this version | `paper_ready`, `retired` |
| `retired` | 후보 version 사용을 닫았다. | no | none |
| `rejected` | lifecycle 진입 또는 승격을 거절했다. | no | none |

허용되지 않은 전이는 parser failure다. 특히 `paper_ready` 없이 `limited_production`으로 갈 수 없고, `rolled_back` 또는 `retired` version이 새 approval 없이 다시 vote에 들어갈 수 없다.

## Promotion gate

제한 승격은 다음 조건을 모두 만족해야 한다.

1. PRD 01 `candidate_id`, PRD 02 report, PRD 03 paper run의 `candidate_version`과 `hypothesis_id`가 모두 같다.
2. PRD 02 code가 `PASS_OFFLINE_EVALUATION`이다.
3. PRD 03 stop code가 `STOP_READY_FOR_LIFECYCLE_REVIEW`다.
4. Paper run에서 contamination event가 없다.
5. 최근 paper outcome에서 `candidate_error_rate_5 - baseline_error_rate_5 <= 0.03`이다.
6. `candidate_na_rate <= 0.15`, `target_na_rate <= 0.20`이다. `target_na_rate` is the N/A rate inside the target disagreement cohort.
7. `latency_p95_ms`가 PRD 01 budget 이하이고 최대 `6000` 이하다.
8. 운영자가 `limited_production`과 rollback pointer를 명시적으로 승인했다.
9. 새 policy artifact가 기존 policy를 덮어쓰지 않고 새 `policy_version`을 만든다.

통과 결과는 제한 승격이다. 영구 관점, 무기한 approval, 기본 다섯 관점 편입은 모두 금지한다.

## Initial weight cap

`limited_production`의 후보 initial weight는 다음 cap을 모두 만족해야 한다.

| cap | value | reason |
| --- | --- | --- |
| Absolute candidate weight | `<= 0.25` | 기존 관점 기본 weight `1.0`의 4분의 1을 넘지 않는다. |
| Total valid weight share | `<= 0.05` | 생산 합의에서 후보 한 표가 단독으로 threshold를 끌지 못하게 한다. |
| Per candidate version count | `1` active version per candidate id | 같은 후보의 두 version이 같은 결정을 동시에 밀지 못하게 한다. |
| Approval duration | `<= 60` market sessions | 제한 기간 뒤 renewal review가 필요하다. |

`compute_consensus()`에 전달하는 weight map은 기존 관점 weight와 후보 capped weight를 함께 담을 수 있다. Weight가 cap을 넘거나 candidate key가 누락된 채 후보 verdict가 vote summary에 들어가면 parser failure다.

## Deliberation participation

Scorer 참여와 deliberation 참여는 별도 권한이다.

| lifecycle_state | scorer participation | deliberation participation |
| --- | --- | --- |
| `paper_ready` | no | no |
| `limited_production` | yes, capped | candidate can be asked to reconsider as minority, but its reasoning cannot be injected into incumbent prompts as majority pressure. |
| `renewal_review` | yes only if approval is still valid | same as `limited_production` until renewal decision. |
| `rolled_back` | no | no |
| `retired` | no | no |

Deliberation rules are:

1. Candidate verdict can trigger weak or divided consensus through capped scorer weight only.
2. During initial limited production, incumbent perspectives can appear in the candidate's reconsideration prompt.
3. Candidate reasoning cannot be inserted into incumbent reconsideration prompts until a future approval explicitly enables `candidate_reasoning_as_prompt_input=true`.
4. `quant` remains code based and is not forced to rejudge because of candidate reasoning.
5. Any deliberation result must keep `initial_consensus`, final consensus, accepted changes, rejected changes, errors, and candidate lifecycle refs separate.

## Version coexistence

Version coexistence prevents hidden replacement.

| case | rule |
| --- | --- |
| New candidate version proposed | Starts at `proposal_received`; it does not inherit production approval. |
| Old version active, new version in paper | Old version may stay in `limited_production`; new version is shadow only. |
| New version promoted | Old version must move to `renewal_review`, `rolled_back`, or `retired` before the new version enters production. |
| Same decision timestamp | Only one version per `candidate_id` can affect the scorer. |
| Audit replay | Historical decisions reference the exact candidate version and policy version used at that time. |

The system never rewrites old recommendation records when a newer candidate version is approved.

## Rollback

Rollback restores the previous approved consensus policy and disables the candidate version for new production decisions.

Rollback is mandatory when any incident threshold fires.

| incident | threshold | rollback action |
| --- | --- | --- |
| `error_rate_spike` | `candidate_error_rate_5 - baseline_error_rate_5 > 0.08` over at least 50 mature samples | move to `rolled_back`, restore previous policy, freeze renewal. |
| `parser_failure_spike` | parser failure rate `> 0.03` over 100 attempts | move to `rolled_back`, require new version. |
| `na_rate_spike` | `candidate_na_rate > 0.20` or `target_na_rate > 0.25` | move to `rolled_back`, restore previous policy, require coverage review before any new version. |
| `latency_spike` | p95 exceeds PRD 01 budget or `6000` ms | move to `rolled_back` if two consecutive windows fail. |
| `deliberation_contamination` | candidate reasoning enters incumbent prompt without approval | immediate `rolled_back`. |
| `weight_cap_breach` | weight exceeds cap in any emitted policy | immediate `rolled_back`. |
| `dirty_policy_mutation` | existing policy edited in place | immediate `rolled_back` and policy audit. |

Rollback does not delete audit records. It appends a `lifecycle_rolled_back` event with previous policy hash, new policy hash, incident id, and affected decision range.

## Retirement

Retirement closes a candidate version.

Retirement is required when:

1. Owner requests closure.
2. Candidate version is superseded and no longer needed for replay except audit.
3. Two rollback events happen within 120 market sessions.
4. Required input source is unavailable beyond its audit TTL.
5. The hypothesis is falsified by offline or production evidence.

Retired versions remain readable for replay and attribution. They cannot appear in new scorer weights, deliberation prompts, adaptive weights, prompt tuning, portfolio sizing, or user output as active guidance.

## Audit trail

Lifecycle records are append-only. Correction is a new event, not an edit.

| event_type | purpose |
| --- | --- |
| `lifecycle_created` | Creates version state from PRD 01, PRD 02, PRD 03 refs. |
| `limited_promotion_approved` | Records approval, initial weight, duration, scorer and deliberation permissions. |
| `policy_emitted` | Writes new consensus policy version and rollback pointer. |
| `incident_recorded` | Records threshold breach or contamination. |
| `lifecycle_rolled_back` | Restores previous policy for new decisions. |
| `renewal_review_started` | Opens review at expiry or threshold warning. |
| `lifecycle_retired` | Closes the candidate version. |

Event fields:

```json
{
  "event_id": "lifecycle_v6_0003",
  "schema_version": "v6.consensus_lifecycle.event.1",
  "candidate_id": "pcand_v6_working_capital_quality",
  "candidate_version": "working_capital_quality.0.1",
  "policy_version": "consensus_policy_v6_20260806_limited_1",
  "event_index": 3,
  "event_type": "limited_promotion_approved",
  "lifecycle_state_before": "paper_ready",
  "lifecycle_state_after": "limited_production",
  "occurred_at": "2026-08-06T10:00:00+09:00",
  "prev_event_hash": "sha256:1111111111111111111111111111111111111111111111111111111111111111",
  "payload_hash": "sha256:2222222222222222222222222222222222222222222222222222222222222222",
  "event_hash": "sha256:3333333333333333333333333333333333333333333333333333333333333333",
  "payload": {
    "initial_weight": "0.25",
    "total_weight_share": "0.0476",
    "approval_duration_market_sessions": 60,
    "candidate_reasoning_as_prompt_input": false,
    "rollback_policy_version": "consensus_policy_v6_20260806_previous"
  }
}
```

`event_hash` is computed from canonical JSON over `schema_version`, `candidate_id`, `candidate_version`, `policy_version`, `event_index`, `event_type`, `lifecycle_state_before`, `lifecycle_state_after`, `prev_event_hash`, and `payload_hash`.

## Policy artifact

The emitted policy is separate from the lifecycle event.

```json
{
  "schema_version": "v6.consensus_policy.1",
  "policy_version": "consensus_policy_v6_20260806_limited_1",
  "scorer_version": "consensus-scorer-current",
  "deliberator_version": "deliberator-current",
  "base_perspectives": ["kwangsoo", "ouroboros", "quant", "macro", "value"],
  "limited_candidates": [
    {
      "candidate_id": "pcand_v6_working_capital_quality",
      "candidate_version": "working_capital_quality.0.1",
      "lifecycle_state": "limited_production",
      "initial_weight": "0.25",
      "total_weight_share": "0.0476",
      "approval_expires_after_market_sessions": 60,
      "deliberation": {
        "candidate_can_reconsider": true,
        "candidate_reasoning_as_prompt_input": false,
        "incumbents_can_be_forced_by_candidate": false
      }
    }
  ],
  "rollback_policy_version": "consensus_policy_v6_20260806_previous",
  "automatic_permanent_perspective": false
}
```

If `automatic_permanent_perspective` is absent or true, parser fails.

## Interruption and resume

Promotion, rollback, and retirement writes can be interrupted. Resume is allowed only when the last persisted event hash and idempotency key match the pending operation.

Rules:

1. If lifecycle event is written but policy artifact is missing, resume writes the policy only if event payload hash matches the pending policy payload hash.
2. If policy artifact is written but lifecycle event is missing, parser treats the policy as orphaned and blocks use until an event is appended with matching payload hash.
3. If both exist but hashes disagree, rollback to previous policy is mandatory before any new candidate decision.
4. Repeated resume with the same idempotency key must not create a second promotion or rollback event.
5. Interrupted rollback is higher priority than interrupted promotion.

## Fixture A: happy limited promotion

```json
{
  "fixture_name": "consensus_lifecycle_happy_limited_promotion",
  "schema_version": "v6.consensus_lifecycle.fixture.1",
  "candidate_id": "pcand_v6_working_capital_quality",
  "candidate_version": "working_capital_quality.0.1",
  "prior_lifecycle_state": "paper_ready",
  "offline_code": "PASS_OFFLINE_EVALUATION",
  "paper_stop_code": "STOP_READY_FOR_LIFECYCLE_REVIEW",
  "paper_contamination_events": 0,
  "paper_metrics": {
    "candidate_error_rate_5": "0.31",
    "baseline_error_rate_5": "0.29",
    "candidate_na_rate": "0.08",
    "target_na_rate": "0.12",
    "latency_p95_ms": 2300
  },
  "approval": {
    "operator_approval_id": "approval_v6_limited_promotion_20260806",
    "approved_lifecycle_state": "limited_production",
    "initial_weight": "0.25",
    "approval_duration_market_sessions": 60,
    "rollback_policy_version": "consensus_policy_v6_20260806_previous"
  },
  "policy": {
    "policy_version": "consensus_policy_v6_20260806_limited_1",
    "base_perspectives": ["kwangsoo", "ouroboros", "quant", "macro", "value"],
    "candidate_weight": "0.25",
    "total_weight_share": "0.0476",
    "candidate_reasoning_as_prompt_input": false,
    "automatic_permanent_perspective": false
  },
  "expected_next_lifecycle_state": "limited_production",
  "expected_vote_effect": "capped_weight_only"
}
```

## Fixture B: error spike rollback

```json
{
  "fixture_name": "consensus_lifecycle_error_spike_rollback",
  "schema_version": "v6.consensus_lifecycle.failure_fixture.1",
  "candidate_id": "pcand_v6_working_capital_quality",
  "candidate_version": "working_capital_quality.0.1",
  "prior_lifecycle_state": "limited_production",
  "active_policy_version": "consensus_policy_v6_20260806_limited_1",
  "rollback_policy_version": "consensus_policy_v6_20260806_previous",
  "incident": {
    "incident_id": "incident_v6_error_spike_20260820",
    "incident_type": "error_rate_spike",
    "mature_samples_5": 64,
    "candidate_error_rate_5": "0.46",
    "baseline_error_rate_5": "0.34",
    "threshold_delta": "0.08"
  },
  "expected_lifecycle_state_after": "rolled_back",
  "expected_policy_after": "consensus_policy_v6_20260806_previous",
  "candidate_allowed_in_new_votes": false,
  "audit_event_required": "lifecycle_rolled_back"
}
```

## Fixture C: version coexistence

```json
{
  "fixture_name": "consensus_lifecycle_version_coexistence",
  "schema_version": "v6.consensus_lifecycle.fixture.1",
  "candidate_id": "pcand_v6_working_capital_quality",
  "versions": [
    {
      "candidate_version": "working_capital_quality.0.1",
      "lifecycle_state": "limited_production",
      "may_affect_scorer": true
    },
    {
      "candidate_version": "working_capital_quality.0.2",
      "lifecycle_state": "paper_ready",
      "may_affect_scorer": false
    }
  ],
  "same_decision_active_versions_allowed": 1,
  "expected_result": "only_0_1_affects_scorer_until_0_2_is_approved_and_0_1_leaves_active_use"
}
```

## Fixture D: interrupted promotion resume

```json
{
  "fixture_name": "consensus_lifecycle_interrupted_promotion_resume",
  "schema_version": "v6.consensus_lifecycle.resume_fixture.1",
  "operation_id": "lifecycle_op_promote_20260806_001",
  "idempotency_key": "promote|pcand_v6_working_capital_quality|working_capital_quality.0.1|consensus_policy_v6_20260806_limited_1",
  "checkpoint": {
    "event_written": true,
    "policy_written": false,
    "last_event_hash": "sha256:3333333333333333333333333333333333333333333333333333333333333333",
    "pending_policy_payload_hash": "sha256:2222222222222222222222222222222222222222222222222222222222222222"
  },
  "resume_request": {
    "prev_event_hash": "sha256:3333333333333333333333333333333333333333333333333333333333333333",
    "policy_payload_hash": "sha256:2222222222222222222222222222222222222222222222222222222222222222",
    "idempotency_key": "promote|pcand_v6_working_capital_quality|working_capital_quality.0.1|consensus_policy_v6_20260806_limited_1"
  },
  "expected_resume_allowed": true,
  "duplicate_lifecycle_event_allowed": false
}
```

## Required probes and mutations

| probe | mutation | expected result |
| --- | --- | --- |
| `happy_limited_promotion` | Fixture A as written. | `limited_production`, capped weight only. |
| `error_spike_rollback` | Fixture B as written. | `rolled_back`, previous policy restored. |
| `json_missing_lifecycle_state` | Remove `prior_lifecycle_state`. | parser failure. |
| `json_bad_weight` | Set `initial_weight` to `0.75`. | parser failure. |
| `json_permanent_perspective` | Set `automatic_permanent_perspective=true`. | parser failure. |
| `state_skip_paper_ready` | Move from `offline_passed` directly to `limited_production`. | parser failure. |
| `threshold_error_spike_not_rolled_back` | Error delta above `0.08` but state remains `limited_production`. | parser failure. |
| `threshold_insufficient_incident_sample` | Error delta above `0.08` with only 20 mature samples. | `renewal_review`, not rollback by error spike alone. |
| `deliberation_prompt_injection` | Candidate reasoning enters incumbent prompt while flag is false. | `rolled_back`. |
| `version_double_active` | Two versions of same candidate affect one scorer decision. | parser failure. |
| `interruption_hash_mismatch` | Resume with different policy payload hash. | resume rejected. |
| `duplicate_resume_event` | Same idempotency key writes second promotion event. | parser failure. |
| `dirty_policy_in_place_edit` | Active policy changes without new policy version. | `rolled_back` and audit failure. |

## 검증 기준

PRD 04 parser는 다음을 확인해야 한다.

1. 문서 제목은 `# PRD 04: Consensus Lifecycle`이다.
2. 바로 다음 줄에 초안 metadata가 정확히 한 번 있다.
3. 생산 영구 채택을 뜻하는 표식은 없다.
4. Fixture A부터 D까지 JSON이 parse된다.
5. Fixture A는 `limited_production`, `initial_weight=0.25`, `automatic_permanent_perspective=false`를 가진다.
6. Fixture B는 오류율 delta `0.12`가 threshold `0.08`을 넘고 `rolled_back`으로 닫힌다.
7. Fixture C는 같은 candidate id의 active scorer version이 하나뿐이다.
8. Fixture D는 같은 hash와 idempotency key에서만 resume을 허용한다.
9. Lifecycle states, promotion gate, initial weight cap, deliberation participation, rollback, retirement, version coexistence, incidents, audit trail이 모두 있다.
10. Required probes는 JSON, state, threshold, deliberation, interruption, dirty policy mutation을 포함한다.
