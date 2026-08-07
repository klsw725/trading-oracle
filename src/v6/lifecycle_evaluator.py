from datetime import datetime
from decimal import Decimal

from .lifecycle_evidence import PromotionErrorWindow, raw_promotion_error_delta, validate_promotion_window
from .lifecycle_events import OperationPayload
from .lifecycle_history import LifecycleHistory, rollback_ordinals
from .lifecycle_incidents import CapIncident, DeliberationIncident, DirtyPolicyIncident, ErrorRateIncident, MonitoringIncident
from .lifecycle_models import ApprovalAction, LifecycleDecision, LifecycleResultCode, LifecycleState, OperatorApproval
from .lifecycle_operations import ExpiryOperation, IncidentOperation, LifecycleOperation, PromotionOperation, RenewalOperation, ReopenOperation, RetirementAssessmentOperation, RetirementOperation, RollbackOperation
from .lifecycle_policy import ActiveCandidatePolicy, ConsensusPolicyArtifact, CurrentConsensusPolicy
from .models import ContractInvariantError
from .paper_models import PaperStopCode
from .lifecycle_retirement import HypothesisFalsified, OwnerRequest, RetirementRequired, SourceUnavailable, SupersededVersion
from .lifecycle_context import CompilerContext


def bind_history(operation: LifecycleOperation, policy: ConsensusPolicyArtifact | CurrentConsensusPolicy, allowed: tuple[LifecycleState, ...]) -> LifecycleHistory:
    history = operation.prior_history
    value = operation.lifecycle_input
    if history is None or (history.candidate_id, history.candidate_version, history.hypothesis_id) != (value.candidate_id, value.candidate_version, value.hypothesis_id):
        raise ContractInvariantError("operation identity is not bound to prior history")
    if operation.expected_prior_history_hash != history.history_hash:
        raise ContractInvariantError("operation expected prior history hash mismatch")
    if history.current_state not in allowed or (history.current_policy_version, history.current_policy_hash) != (policy.policy_version, policy.policy_hash):
        raise ContractInvariantError("operation policy or state is stale against prior history")
    if any(event.payload.operation_id == value.operation_id or event.payload.idempotency_key == value.idempotency_key for event in history.events):
        raise ContractInvariantError("operation identity already exists in prior history")
    return history


def active_candidate(operation: IncidentOperation | ExpiryOperation | RenewalOperation | RollbackOperation) -> ActiveCandidatePolicy:
    value = operation.lifecycle_input
    candidate = next((item for item in operation.current_policy.active_candidates if (item.candidate_id, item.candidate_version) == (value.candidate_id, value.candidate_version)), None)
    if candidate is None:
        raise ContractInvariantError("operation candidate is not active in current policy")
    return candidate


def exact_approval(approval: OperatorApproval, operation: LifecycleOperation, action: ApprovalAction, before: LifecycleState, after: LifecycleState) -> None:
    value = operation.lifecycle_input
    if (approval.candidate_id, approval.candidate_version, approval.action, approval.from_state, approval.to_state) != (value.candidate_id, value.candidate_version, action, before, after):
        raise ContractInvariantError("approval identity or state transition mismatch")
    expected_history = operation.prior_history.history_hash if operation.prior_history is not None else None
    if approval.prior_history_hash != expected_history:
        raise ContractInvariantError("approval is not bound to exact prior history")


def evaluate_promotion(operation: PromotionOperation) -> LifecycleDecision:
    value, paper, approval, policy = operation.lifecycle_input, operation.paper_artifact, operation.approval, operation.current_policy
    if operation.prior_history is not None:
        _ = bind_history(operation, policy, (LifecycleState.PAPER_READY,))
    if (value.candidate_id, value.candidate_version, value.hypothesis_id) != (paper.paper_input.candidate_id, paper.paper_input.candidate_version, paper.paper_input.hypothesis_id):
        raise ContractInvariantError("lifecycle and paper lineage mismatch")
    exact_approval(approval, operation, ApprovalAction.PROMOTE, LifecycleState.PAPER_READY, LifecycleState.LIMITED_PRODUCTION)
    if (approval.rollback_policy_version, approval.rollback_policy_hash) != (policy.policy_version, policy.policy_hash):
        raise ContractInvariantError("promotion rollback pointer must equal current immutable policy")
    if paper.decision.stop_code is not PaperStopCode.READY or paper.prd04_handoff != "evidence_only_not_production_adoption":
        raise ContractInvariantError("paper artifact is not a READY lifecycle handoff")
    vote_summary = paper.paper_input.isolation.production_before.vote_summary
    if not isinstance(vote_summary, dict) or vote_summary.get("N/A") != 0 or policy.observed_production_snapshot_hash != paper.production_before_hash:
        raise ContractInvariantError("production snapshot binding mismatch")
    existing = tuple(item for item in policy.active_candidates if item.candidate_id == value.candidate_id)
    if existing and not (len(existing) == 1 and existing[0].candidate_version != value.candidate_version and existing[0].lifecycle_state is LifecycleState.RENEWAL_REVIEW and value.current_session_ordinal > existing[0].approval_end_session_ordinal):
        raise ContractInvariantError("candidate already has a non-replaceable active version")
    _ = validate_promotion_window(paper, operation.error_window); paper_metrics = paper.decision.metrics
    budget = paper.paper_input.offline_artifact.candidate_artifact.candidate_proposal.budget.max_wall_ms_per_ticker
    failures = tuple(reason for failed, reason in ((raw_promotion_error_delta(operation.error_window) > Decimal("0.03"), "promotion_error_delta"), (Decimal(paper_metrics.candidate_na_rate) > Decimal("0.150000"), "candidate_na_rate"), (Decimal(paper_metrics.target_na_rate) > Decimal("0.200000"), "target_na_rate"), (paper_metrics.latency_p95_ms > min(budget, 6000), "latency_p95")) if failed)
    if failures:
        return LifecycleDecision(result_code=LifecycleResultCode.PROMOTION_REJECTED_GATE, prior_state=LifecycleState.PAPER_READY, next_state=LifecycleState.REJECTED, reasons=failures)
    return LifecycleDecision(result_code=LifecycleResultCode.PROMOTION_APPROVED_LIMITED, prior_state=LifecycleState.PAPER_READY, next_state=LifecycleState.LIMITED_PRODUCTION, reasons=("all_promotion_gates_passed",))


def evaluate_incident(operation: IncidentOperation) -> LifecycleDecision:
    history = bind_history(operation, operation.current_policy, (LifecycleState.LIMITED_PRODUCTION, LifecycleState.RENEWAL_REVIEW))
    candidate, report = active_candidate(operation), operation.report
    source_paper = operation.source_paper_artifact
    if candidate.source_paper_artifact_hash != source_paper.artifact_hash or (source_paper.paper_input.candidate_id, source_paper.paper_input.candidate_version, source_paper.paper_input.hypothesis_id) != (operation.lifecycle_input.candidate_id, operation.lifecycle_input.candidate_version, operation.lifecycle_input.hypothesis_id): raise ContractInvariantError("incident source paper artifact mismatch")
    identity = (candidate.candidate_id, candidate.candidate_version, operation.current_policy.policy_version)
    required: str | None = None
    review: str | None = None
    match report:  # noqa: MATCH_OK - IncidentReport is a closed discriminated union
        case ErrorRateIncident(candidate_id=candidate_id, candidate_version=version, policy_version=policy_version, error_window=window):
            if (candidate_id, version, policy_version) != identity: raise ContractInvariantError("error incident identity mismatch")
            if window.paper_artifact_hash != source_paper.artifact_hash or window.market != source_paper.paper_input.assignment_input.market: raise ContractInvariantError("error incident window source mismatch")
            delta, count = validate_window(window)
            if delta > Decimal("0.08"):
                if count >= 50: required = "error_rate_spike"
                else: review = "insufficient_error_evidence"
        case MonitoringIncident(incident_type=incident_type, evidence=evidence):
            if (evidence.candidate_id, evidence.candidate_version, evidence.policy_version) != identity: raise ContractInvariantError("monitoring incident identity mismatch")
            records = tuple(record for window in evidence.windows for record in window.records)
            if incident_type == "parser_failure_spike":
                if len(records) != 100 or len({item.attempt_id for item in records}) != 100: raise ContractInvariantError("parser failure incident requires exactly 100 unique attempts")
                if sum(item.parser_failed for item in records) > 3: required = incident_type
            elif incident_type == "na_rate_spike":
                target = tuple(item for item in records if item.target_disagreement)
                overall_failed = Decimal(sum(item.candidate_verdict == "N/A" for item in records)) / Decimal(len(records)) > Decimal("0.20")
                target_failed = bool(target) and Decimal(sum(item.candidate_verdict == "N/A" for item in target)) / Decimal(len(target)) > Decimal("0.25")
                if overall_failed or target_failed: required = incident_type
            elif incident_type == "latency_spike":
                if any(not window.records for window in evidence.windows): raise ContractInvariantError("latency windows require records")
                budget = source_paper.paper_input.offline_artifact.candidate_artifact.candidate_proposal.budget.max_wall_ms_per_ticker
                failed = tuple(p95(tuple(item.latency_ms for item in window.records)) > min(budget, 6000) for window in evidence.windows)
                if len(failed) >= 2 and all(failed[-2:]): required = incident_type
                elif any(failed): review = "single_latency_failure"
        case DeliberationIncident(evidence=evidence):
            if (evidence.candidate_id, evidence.candidate_version, evidence.policy_version) != identity: raise ContractInvariantError("deliberation incident identity mismatch")
            if evidence.candidate_reasoning_hash in evidence.incumbent_prompt_input_hashes: required = "deliberation_contamination"
        case CapIncident(evidence=evidence):
            if (evidence.candidate_id, evidence.candidate_version, evidence.policy_version, evidence.observed_policy_hash) != (*identity, operation.current_policy.policy_hash): raise ContractInvariantError("cap incident identity mismatch")
            if Decimal(evidence.emitted_weight) > Decimal("0.250000") or Decimal(evidence.emitted_share) > Decimal("0.050000"): required = "weight_cap_breach"
        case DirtyPolicyIncident(evidence=evidence):
            if (evidence.recorded_policy.policy_version, evidence.recorded_policy.policy_hash) != (operation.current_policy.policy_version, operation.current_policy.policy_hash): raise ContractInvariantError("dirty policy incident source mismatch")
            required = "dirty_policy_mutation"
    if required:
        return LifecycleDecision(result_code=LifecycleResultCode.ROLLBACK_REQUIRED, prior_state=history.current_state, next_state=history.current_state, reasons=(required,), audit_failure=required == "dirty_policy_mutation")
    if review and history.current_state is LifecycleState.LIMITED_PRODUCTION:
        return LifecycleDecision(result_code=LifecycleResultCode.RENEWAL_REVIEW_OPENED, prior_state=history.current_state, next_state=LifecycleState.RENEWAL_REVIEW, reasons=(review,))
    return LifecycleDecision(result_code=LifecycleResultCode.INCIDENT_NO_ACTION, prior_state=history.current_state, next_state=history.current_state, reasons=("below_threshold",))


def evaluate_operation(operation: LifecycleOperation, context: CompilerContext) -> LifecycleDecision:
    match operation:  # noqa: MATCH_OK - LifecycleOperation is a closed discriminated union
        case PromotionOperation(): return evaluate_promotion(operation)
        case IncidentOperation(): return evaluate_incident(operation)
        case ExpiryOperation():
            history, candidate = bind_history(operation, operation.current_policy, (LifecycleState.LIMITED_PRODUCTION,)), active_candidate(operation)
            if operation.lifecycle_input.current_session_ordinal <= candidate.approval_end_session_ordinal: raise ContractInvariantError("candidate approval has not expired")
            return LifecycleDecision(result_code=LifecycleResultCode.RENEWAL_REVIEW_OPENED, prior_state=history.current_state, next_state=LifecycleState.RENEWAL_REVIEW, reasons=("approval_window_expired",))
        case RenewalOperation():
            _ = bind_history(operation, operation.current_policy, (LifecycleState.RENEWAL_REVIEW,)); candidate = active_candidate(operation)
            exact_approval(operation.approval, operation, ApprovalAction.RENEW, LifecycleState.RENEWAL_REVIEW, LifecycleState.LIMITED_PRODUCTION)
            if operation.approval.initial_weight != candidate.initial_weight or (operation.approval.rollback_policy_version, operation.approval.rollback_policy_hash) != (candidate.rollback_policy_version, candidate.rollback_policy_hash): raise ContractInvariantError("renewal must preserve weight and rollback pointer")
            return LifecycleDecision(result_code=LifecycleResultCode.RENEWAL_APPROVED_LIMITED, prior_state=LifecycleState.RENEWAL_REVIEW, next_state=LifecycleState.LIMITED_PRODUCTION, reasons=("explicit_renewal_approved",))
        case RollbackOperation():
            history, candidate = bind_history(operation, operation.current_policy, (LifecycleState.LIMITED_PRODUCTION, LifecycleState.RENEWAL_REVIEW)), active_candidate(operation)
            exact_approval(operation.approval, operation, ApprovalAction.ROLLBACK, history.current_state, LifecycleState.ROLLED_BACK)
            if (operation.approval.rollback_policy_version, operation.approval.rollback_policy_hash) != (candidate.rollback_policy_version, candidate.rollback_policy_hash) or (operation.rollback_policy.policy_version, operation.rollback_policy.policy_hash) != (candidate.rollback_policy_version, candidate.rollback_policy_hash): raise ContractInvariantError("rollback must restore exact immutable pointer")
            if (operation.assessment.candidate_id, operation.assessment.candidate_version, operation.assessment.policy_version, operation.assessment.source_policy_hash) != (candidate.candidate_id, candidate.candidate_version, operation.current_policy.policy_version, operation.current_policy.policy_hash): raise ContractInvariantError("rollback assessment identity mismatch")
            return LifecycleDecision(result_code=LifecycleResultCode.ROLLBACK_COMPLETED, prior_state=history.current_state, next_state=LifecycleState.ROLLED_BACK, reasons=("explicit_rollback_approved",))
        case RetirementAssessmentOperation():
            _ = bind_history(operation, operation.current_policy, (LifecycleState.ROLLED_BACK,)); ordinals = rollback_ordinals(operation.prior_history)
            if len(ordinals) < 2 or not 1 <= ordinals[-1] - ordinals[-2] <= 120: raise ContractInvariantError("retirement assessment requires two rollbacks within 1 to 120 sessions")
            return LifecycleDecision(result_code=LifecycleResultCode.RETIREMENT_REQUIRED, prior_state=LifecycleState.ROLLED_BACK, next_state=LifecycleState.ROLLED_BACK, reasons=("two_rollbacks_within_120_sessions",))
        case RetirementOperation():
            history = bind_history(operation, operation.current_policy, (LifecycleState.ROLLED_BACK, LifecycleState.LIMITED_PRODUCTION, LifecycleState.RENEWAL_REVIEW))
            exact_approval(operation.approval, operation, ApprovalAction.RETIRE, history.current_state, LifecycleState.RETIRED)
            paper = operation.source_paper_artifact
            if (paper.paper_input.candidate_id, paper.paper_input.candidate_version, paper.paper_input.hypothesis_id) != (operation.lifecycle_input.candidate_id, operation.lifecycle_input.candidate_version, operation.lifecycle_input.hypothesis_id): raise ContractInvariantError("retirement source paper identity mismatch")
            trigger = operation.trigger
            match trigger:  # noqa: MATCH_OK - RetirementTrigger is closed
                case RetirementRequired():
                    if trigger.history_hash != history.history_hash or trigger.assessment_event_hash != history.head_event_hash or history.events[-1].event_type != "retirement_required": raise ContractInvariantError("retirement assessment trigger is not the prior history head")
                case OwnerRequest():
                    candidate = paper.paper_input.offline_artifact.candidate_artifact
                    if trigger.owner_id != candidate.candidate_proposal.candidate_identity.owner or trigger.candidate_artifact_hash != candidate.artifact_hash: raise ContractInvariantError("owner retirement trigger mismatch")
                case SupersededVersion():
                    if (trigger.candidate_id, trigger.retired_version) != (operation.lifecycle_input.candidate_id, operation.lifecycle_input.candidate_version): raise ContractInvariantError("superseded retirement trigger mismatch")
                case SourceUnavailable():
                    evidence = trigger.evidence; observation = evidence.observation
                    candidate = next((item for item in operation.current_policy.active_candidates if (item.candidate_id, item.candidate_version) == (operation.lifecycle_input.candidate_id, operation.lifecycle_input.candidate_version)), None)
                    if candidate is None: raise ContractInvariantError("source retirement candidate is not active")
                    ttl = next((item for item in candidate.source_ttl_policies if (item.source_id, item.source_contract) == (observation.source_id, observation.source_contract)), None)
                    if evidence not in context.retirement_evidence or evidence.candidate_artifact.artifact_hash != paper.paper_input.offline_artifact.candidate_artifact.artifact_hash or observation.observed_session_ordinal != operation.lifecycle_input.current_session_ordinal or ttl is None or observation.observed_session_ordinal <= observation.last_available_session_ordinal + ttl.ttl_market_sessions: raise ContractInvariantError("source unavailable retirement trigger mismatch")
                case HypothesisFalsified():
                    evidence = trigger.evidence; candidate = evidence.candidate_artifact
                    if evidence not in context.retirement_evidence or candidate.artifact_hash != paper.paper_input.offline_artifact.candidate_artifact.artifact_hash or (candidate.candidate_id, candidate.candidate_version, candidate.hypothesis_id) != (operation.lifecycle_input.candidate_id, operation.lifecycle_input.candidate_version, operation.lifecycle_input.hypothesis_id) or evidence.source_paper_artifact_hash != paper.artifact_hash: raise ContractInvariantError("hypothesis retirement trigger mismatch")
            return LifecycleDecision(result_code=LifecycleResultCode.RETIREMENT_COMPLETED, prior_state=history.current_state, next_state=LifecycleState.RETIRED, reasons=("typed_retirement_trigger_approved",))
        case ReopenOperation():
            history = bind_history(operation, operation.current_policy, (LifecycleState.ROLLED_BACK,))
            rollback = next((event for event in reversed(history.events) if event.event_type == "lifecycle_rolled_back"), None)
            paper = operation.paper_artifact
            authorization = operation.authorization
            if rollback is None or not isinstance(rollback.payload, OperationPayload) or rollback.payload.policy_hash != operation.current_policy.policy_hash or rollback.payload.source_paper_artifact_hash is None: raise ContractInvariantError("reopen is not rooted in matching rollback history")
            prior_paper_hash = rollback.payload.source_paper_artifact_hash
            if (authorization.candidate_id, authorization.candidate_version, authorization.prior_history_hash, authorization.rollback_event_hash, authorization.prior_source_paper_artifact_hash, authorization.paper_artifact_hash) != (operation.lifecycle_input.candidate_id, operation.lifecycle_input.candidate_version, history.history_hash, rollback.event_hash, prior_paper_hash, operation.paper_artifact.artifact_hash): raise ContractInvariantError("reopen authorization is not bound to rollback history")
            if paper.artifact_hash == prior_paper_hash or datetime.fromisoformat(paper.generated_at) <= datetime.fromisoformat(rollback.occurred_at): raise ContractInvariantError("reopen requires fresh paper evidence after rollback")
            if paper.decision.stop_code is not PaperStopCode.READY or (paper.paper_input.candidate_id, paper.paper_input.candidate_version, paper.paper_input.hypothesis_id) != (operation.lifecycle_input.candidate_id, operation.lifecycle_input.candidate_version, operation.lifecycle_input.hypothesis_id): raise ContractInvariantError("reopen requires READY paper lineage")
            return LifecycleDecision(result_code=LifecycleResultCode.REOPENED_PAPER_READY, prior_state=history.current_state, next_state=LifecycleState.PAPER_READY, reasons=("rollback_rooted_ready_paper",))


def validate_window(window: PromotionErrorWindow) -> tuple[Decimal, int]:
    count = len(window.records)
    if count == 0: raise ContractInvariantError("error incident window requires records")
    candidate = Decimal(sum(item.candidate_error for item in window.records)) / Decimal(count); baseline = Decimal(sum(item.baseline_error for item in window.records)) / Decimal(count)
    return candidate - baseline, count


def p95(values: tuple[int, ...]) -> int:
    ordered = sorted(values); return ordered[max(0, (len(ordered) * 95 + 99) // 100 - 1)]
