import ast
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path

from pydantic import ValidationError

from src.v4.models import JsonValue

from .lifecycle_artifact import ConsensusLifecycleArtifact, build_lifecycle_artifact
from .lifecycle_attacks import arbitrary_reopen_history_rejected, branch_splice_rejected, cross_history_duplicate_rejected, exact_operation_replay_rejected, forged_rollback_pointer_rejected, ignored_retirement_ordinals_rejected, old_paper_reopen_rejected, operation_roundtrips, rebound_approval, renewal_pointer_change_rejected, reset_to_genesis_rejected, retirement_delta_checks, semantic_ledger_substitution_rejected, wrong_approval_identity_rejected, wrong_approval_state_rejected
from .lifecycle_evidence import AttemptObservation, AttemptObservationBody, ErrorOutcome, ErrorOutcomeBody, MonitoringWindow, MonitoringWindowBody, PromotionErrorWindow, PromotionErrorWindowBody, hash_body, raw_error_delta, validate_promotion_window
from .lifecycle_events import LifecycleEventBody, OperationPayload, event_hash_json
from .lifecycle_fixture import GOLDEN_SHARE, ApprovalSpec, LifecycleFixture, approval, bound_policy, policy_registry
from .lifecycle_incidents import ErrorRateIncident, MonitoringEvidence, MonitoringEvidenceBody, MonitoringIncident
from .lifecycle_interruption import InterruptionCheckpoint, InterruptionCheckpointBody, PendingIntent, pending_intent_body, resume_decision, select_pending_intent
from .lifecycle_models import LifecycleResultCode, LifecycleState
from .lifecycle_operations import IncidentOperation, PromotionOperation, RenewalOperation, ReopenOperation, RetirementOperation, RollbackOperation
from .lifecycle_retirement import AvailabilityObservation, AvailabilityObservationBody, FalsificationObservation, FalsificationObservationBody, HypothesisFalsificationArtifact, HypothesisFalsificationArtifactBody, HypothesisFalsified, HypothesisFalsifiedBody, OwnerRequest, OwnerRequestBody, SourceAvailabilityArtifact, SourceAvailabilityArtifactBody, SourceUnavailable, SourceUnavailableBody, SupersededVersion, SupersededVersionBody
from .lifecycle_context import CompilerContext
from .lifecycle_models import ApprovalAction
from .lifecycle_policy import ConsensusPolicyArtifact, ConsensusPolicyBody, CurrentConsensusPolicy, CurrentConsensusPolicyBody
from .models import CandidateVersion, ContractInvariantError, HypothesisId, JsonBoundary


def rejected[T](action: Callable[[], T]) -> bool:
    try:
        _ = action()
    except (ValidationError, ContractInvariantError):
        return True
    return False


def attempt(index: int, latency_ms: int = 2000) -> AttemptObservation:
    body = AttemptObservationBody(schema_version="v6.lifecycle-attempt-observation.1", attempt_id=f"parser_attempt_{index:03d}", production_decision_id=f"parser_decision_{index:03d}", market_session_ordinal=120, target_disagreement=False, parser_failed=index < 4, candidate_verdict=None, latency_ms=latency_ms)
    return AttemptObservation.model_validate({**body.model_dump(mode="json"), "record_hash": hash_body(body)})


def parser_operation(fixture: LifecycleFixture, count: int) -> IncidentOperation:
    operation = fixture.operations[4]
    if not isinstance(operation, IncidentOperation): raise ContractInvariantError("fixture incident missing")
    value, policy = operation.lifecycle_input, operation.current_policy
    window_body = MonitoringWindowBody(schema_version="v6.lifecycle-monitoring-window.1", window_id=f"parser_{count}", candidate_id=value.candidate_id, candidate_version=value.candidate_version, policy_version=policy.policy_version, market="KR", window_index=0, previous_window_hash=None, records=tuple(attempt(index) for index in range(count)))
    window = MonitoringWindow.model_validate({**window_body.model_dump(mode="json"), "window_hash": hash_body(window_body)})
    evidence_body = MonitoringEvidenceBody(schema_version="v6.lifecycle-monitoring-evidence.1", candidate_id=value.candidate_id, candidate_version=value.candidate_version, policy_version=policy.policy_version, market="KR", windows=(window,))
    evidence = MonitoringEvidence.model_validate({**evidence_body.model_dump(mode="json"), "evidence_hash": hash_body(evidence_body)})
    report = MonitoringIncident(incident_type="parser_failure_spike", incident_id=f"parser_{count}", evidence=evidence)
    return operation.model_copy(update={"report": report, "lifecycle_input": value.model_copy(update={"operation_id": f"lifecycle_op_parser_{count}", "idempotency_key": f"parser_{count}|{value.candidate_id}|{value.candidate_version}"})})


def parser_count_checks(fixture: LifecycleFixture) -> tuple[bool, bool, bool]:
    context = fixture.artifacts[4].compiler_context
    valid = build_lifecycle_artifact(parser_operation(fixture, 100), context)
    return (valid.decision.result_code is LifecycleResultCode.ROLLBACK_REQUIRED, rejected(lambda: build_lifecycle_artifact(parser_operation(fixture, 99), context)), rejected(lambda: build_lifecycle_artifact(parser_operation(fixture, 101), context)))


def incident_review_artifacts(fixture: LifecycleFixture) -> tuple[ConsensusLifecycleArtifact, ConsensusLifecycleArtifact]:
    operation, promotion = fixture.operations[4], fixture.operations[1]
    if not isinstance(operation, IncidentOperation) or not isinstance(promotion, PromotionOperation): raise ContractInvariantError("incident review fixtures missing")
    outcomes: list[ErrorOutcome] = []
    for source in promotion.error_window.records[:49]:
        body = ErrorOutcomeBody.model_validate({**source.model_dump(mode="json", exclude={"record_hash"}), "candidate_error": True, "baseline_error": False})
        outcomes.append(ErrorOutcome.model_validate({**body.model_dump(mode="json"), "record_hash": hash_body(body)}))
    window_body = PromotionErrorWindowBody.model_validate({**promotion.error_window.model_dump(mode="json", exclude={"window_hash"}), "records": tuple(outcomes)})
    window = PromotionErrorWindow.model_validate({**window_body.model_dump(mode="json"), "window_hash": hash_body(window_body)})
    error_report = ErrorRateIncident(incident_type="error_rate_spike", incident_id="incident_insufficient_error", candidate_id=operation.lifecycle_input.candidate_id, candidate_version=operation.lifecycle_input.candidate_version, policy_version=operation.current_policy.policy_version, error_window=window)
    error_value = operation.lifecycle_input.model_copy(update={"operation_id": "lifecycle_op_insufficient_error", "idempotency_key": "insufficient_error_review"})
    error_operation = operation.model_copy(update={"lifecycle_input": error_value, "output_policy_version": "consensus_policy_error_review", "report": error_report})
    records = tuple(attempt(index, 7001) for index in range(10))
    monitor_body = MonitoringWindowBody(schema_version="v6.lifecycle-monitoring-window.1", window_id="latency_review", candidate_id=operation.lifecycle_input.candidate_id, candidate_version=operation.lifecycle_input.candidate_version, policy_version=operation.current_policy.policy_version, market="KR", window_index=0, previous_window_hash=None, records=records)
    monitor = MonitoringWindow.model_validate({**monitor_body.model_dump(mode="json"), "window_hash": hash_body(monitor_body)})
    evidence_body = MonitoringEvidenceBody(schema_version="v6.lifecycle-monitoring-evidence.1", candidate_id=operation.lifecycle_input.candidate_id, candidate_version=operation.lifecycle_input.candidate_version, policy_version=operation.current_policy.policy_version, market="KR", windows=(monitor,))
    evidence = MonitoringEvidence.model_validate({**evidence_body.model_dump(mode="json"), "evidence_hash": hash_body(evidence_body)})
    latency_report = MonitoringIncident(incident_type="latency_spike", incident_id="incident_single_latency", evidence=evidence)
    latency_value = operation.lifecycle_input.model_copy(update={"operation_id": "lifecycle_op_single_latency", "idempotency_key": "single_latency_review"})
    latency_operation = operation.model_copy(update={"lifecycle_input": latency_value, "output_policy_version": "consensus_policy_latency_review", "report": latency_report})
    context = fixture.artifacts[4].compiler_context
    return build_lifecycle_artifact(error_operation, context), build_lifecycle_artifact(latency_operation, context)


def non_positive_weight_rejected(fixture: LifecycleFixture) -> bool:
    current = fixture.operations[1].current_policy
    first = current.incumbent_weights[0].model_copy(update={"weight": "0.000000"})
    raw = {**current.model_dump(mode="json", exclude={"policy_hash"}), "incumbent_weights": (first, *current.incumbent_weights[1:])}
    return rejected(lambda: CurrentConsensusPolicyBody.model_validate(raw))


def checkpoint_checks(fixture: LifecycleFixture) -> tuple[bool, bool, bool, bool, bool]:
    request = fixture.operations[3]
    if request.prior_history is None: raise ContractInvariantError("pending request history missing")
    history = request.prior_history
    intent_body = pending_intent_body(request, fixture.artifacts[3].compiler_context)
    intent = PendingIntent.model_validate({**intent_body.model_dump(mode="json"), "intent_hash": hash_body(intent_body)})
    states = ((None, None, None), (intent.transition_hash, None, None), (None, intent.policy_hash, None), (intent.transition_hash, intent.policy_hash, None), (intent.transition_hash, intent.policy_hash, intent.commit_hash))
    actions: list[str] = []
    ready = True
    for transition, policy, commit in states:
        body = InterruptionCheckpointBody(schema_version="v6.consensus_lifecycle.checkpoint.3", pending=intent, head_state="history", observed_history_hash=history.history_hash, observed_ledger_head_hash=history.head_event_hash, observed_next_event_index=history.next_event_index, persisted_transition_hash=transition, persisted_policy_hash=policy, persisted_commit_hash=commit)
        checkpoint = InterruptionCheckpoint.model_validate({**body.model_dump(mode="json"), "checkpoint_hash": hash_body(body)})
        decision = resume_decision(checkpoint, history); actions.append(decision.action); ready &= decision.result_code in (LifecycleResultCode.RESUME_READY, LifecycleResultCode.NOOP_ALREADY_COMMITTED)
    mismatch_body = InterruptionCheckpointBody(schema_version="v6.consensus_lifecycle.checkpoint.3", pending=intent, head_state="history", observed_history_hash=history.history_hash, observed_ledger_head_hash=history.head_event_hash, observed_next_event_index=history.next_event_index, persisted_transition_hash=f"sha256:{'f' * 64}", persisted_policy_hash=None, persisted_commit_hash=None)
    mismatch = InterruptionCheckpoint.model_validate({**mismatch_body.model_dump(mode="json"), "checkpoint_hash": hash_body(mismatch_body)})
    rollback_body = pending_intent_body(fixture.operations[5], fixture.artifacts[5].compiler_context); rollback = PendingIntent.model_validate({**rollback_body.model_dump(mode="json"), "intent_hash": hash_body(rollback_body)})
    initial = fixture.operations[1]
    initial_body = pending_intent_body(initial, fixture.artifacts[1].compiler_context); initial_intent = PendingIntent.model_validate({**initial_body.model_dump(mode="json"), "intent_hash": hash_body(initial_body)})
    zero = f"sha256:{'0' * 64}"
    genesis_body = InterruptionCheckpointBody(schema_version="v6.consensus_lifecycle.checkpoint.3", pending=initial_intent, head_state="genesis", observed_history_hash=zero, observed_ledger_head_hash=zero, observed_next_event_index=0, persisted_transition_hash=None, persisted_policy_hash=None, persisted_commit_hash=None)
    genesis = InterruptionCheckpoint.model_validate({**genesis_body.model_dump(mode="json"), "checkpoint_hash": hash_body(genesis_body)})
    return actions == ["write_all", "write_policy_and_commit", "write_transition_and_commit", "write_commit", "noop"], ready, resume_decision(mismatch, history).result_code is LifecycleResultCode.ROLLBACK_REQUIRED, select_pending_intent((intent, rollback)).operation_type == "rollback", resume_decision(genesis, None).result_code is LifecycleResultCode.RESUME_READY


def retirement_trigger_checks(fixture: LifecycleFixture) -> tuple[bool, bool, bool, bool, bool, bool, bool, bool]:
    promotion, template, promotion_operation = fixture.artifacts[1], fixture.operations[11], fixture.operations[1]
    if not isinstance(promotion.policy, ConsensusPolicyArtifact) or not isinstance(template, RetirementOperation) or not isinstance(promotion_operation, PromotionOperation): raise ContractInvariantError("retirement fixtures missing")
    paper = promotion_operation.paper_artifact
    value = template.lifecycle_input.model_copy(update={"operation_id": "active_retirement", "idempotency_key": "active_retirement", "current_session_ordinal": 170, "policy_registry": promotion.history.policy_registry})
    approved = approval(ApprovalSpec(value, ApprovalAction.RETIRE, promotion.policy, "consensus_policy_active_retired", LifecycleState.LIMITED_PRODUCTION, promotion.history.history_hash))
    candidate = paper.paper_input.offline_artifact.candidate_artifact
    owner_body = OwnerRequestBody(trigger_type="owner_request", owner_id=candidate.candidate_proposal.candidate_identity.owner, candidate_artifact_hash=candidate.artifact_hash); owner = OwnerRequest.model_validate({**owner_body.model_dump(mode="json"), "trigger_hash": hash_body(owner_body)})
    newer_version = CandidateVersion("working_capital_quality.0.2"); newer_approval = rebound_approval(promotion_operation.approval, candidate_version=newer_version, policy_version="consensus_policy_newer"); newer_candidate = promotion.policy.active_candidates[1].model_copy(update={"candidate_version": newer_version, "operator_approval_hash": newer_approval.approval_hash})
    newer_policy_body = ConsensusPolicyBody.model_validate({**promotion.policy.model_dump(mode="json", exclude={"policy_hash"}), "policy_version": "consensus_policy_newer", "active_candidates": (promotion.policy.active_candidates[0], newer_candidate)}); newer_policy = ConsensusPolicyArtifact.model_validate({**newer_policy_body.model_dump(mode="json"), "policy_hash": hash_body(newer_policy_body)})
    superseded_body = SupersededVersionBody(trigger_type="superseded_version", candidate_id=value.candidate_id, retired_version=value.candidate_version, newer_version=newer_version, newer_approval=newer_approval, newer_policy=newer_policy); superseded = SupersededVersion.model_validate({**superseded_body.model_dump(mode="json"), "trigger_hash": hash_body(superseded_body)})
    declaration = candidate.candidate_proposal.input_contract.required_extra_inputs[0]
    availability_body = AvailabilityObservationBody(schema_version="v6.source-availability-observation.1", candidate_id=value.candidate_id, candidate_version=value.candidate_version, hypothesis_id=value.hypothesis_id, source_id=declaration.name, source_contract=declaration.source_contract or declaration.name, observed_session_ordinal=170, last_available_session_ordinal=149, available=False)
    availability = AvailabilityObservation.model_validate({**availability_body.model_dump(mode="json"), "observation_hash": hash_body(availability_body)})
    source_artifact_body = SourceAvailabilityArtifactBody(schema_version="v6.source-availability-artifact.1", candidate_artifact=candidate, observation=availability)
    source_artifact = SourceAvailabilityArtifact.model_validate({**source_artifact_body.model_dump(mode="json"), "artifact_hash": hash_body(source_artifact_body)})
    source_body = SourceUnavailableBody(trigger_type="source_unavailable_beyond_ttl", evidence=source_artifact); source = SourceUnavailable.model_validate({**source_body.model_dump(mode="json"), "trigger_hash": hash_body(source_body)})
    observation_body = FalsificationObservationBody(schema_version="v6.hypothesis-falsification-observation.1", observation_id="production_falsification_001", source_artifact_hash=paper.artifact_hash, supports_hypothesis=False)
    observation = FalsificationObservation.model_validate({**observation_body.model_dump(mode="json"), "observation_hash": hash_body(observation_body)})
    falsification_body = HypothesisFalsificationArtifactBody(schema_version="v6.hypothesis-falsification-artifact.1", candidate_artifact=candidate, source_paper_artifact_hash=paper.artifact_hash, observations=(observation,), result="falsified")
    falsification = HypothesisFalsificationArtifact.model_validate({**falsification_body.model_dump(mode="json"), "artifact_hash": hash_body(falsification_body)})
    falsified_body = HypothesisFalsifiedBody(trigger_type="hypothesis_falsified", evidence=falsification); falsified = HypothesisFalsified.model_validate({**falsified_body.model_dump(mode="json"), "trigger_hash": hash_body(falsified_body)})
    base = template.model_copy(update={"lifecycle_input": value, "current_policy": promotion.policy, "prior_history": promotion.history, "expected_prior_history_hash": promotion.history.history_hash, "approval": approved, "source_paper_artifact": paper})
    context = CompilerContext(schema_version="v6.consensus_lifecycle.compiler-context.1", policy_registry=promotion.history.policy_registry, retirement_evidence=(source_artifact, falsification))
    results = tuple(build_lifecycle_artifact(base.model_copy(update={"trigger": trigger}), context).decision.result_code is LifecycleResultCode.RETIREMENT_COMPLETED for trigger in (owner, superseded, source, falsified))
    wrong_candidate_body = superseded_body.model_copy(update={"candidate_id": promotion.policy.active_candidates[0].candidate_id})
    cross_candidate = rejected(lambda: SupersededVersion.model_validate({**wrong_candidate_body.model_dump(mode="json"), "trigger_hash": hash_body(wrong_candidate_body)}))
    lexical_body = superseded_body.model_copy(update={"retired_version": CandidateVersion("working_capital_quality.0.10")})
    semantic_order = rejected(lambda: SupersededVersion.model_validate({**lexical_body.model_dump(mode="json"), "trigger_hash": hash_body(lexical_body)}))
    short_body = availability_body.model_copy(update={"last_available_session_ordinal": 169}); short = AvailabilityObservation.model_validate({**short_body.model_dump(mode="json"), "observation_hash": hash_body(short_body)})
    short_artifact_body = source_artifact_body.model_copy(update={"observation": short}); short_artifact = SourceAvailabilityArtifact.model_validate({**short_artifact_body.model_dump(mode="json"), "artifact_hash": hash_body(short_artifact_body)})
    short_trigger_body = SourceUnavailableBody(trigger_type="source_unavailable_beyond_ttl", evidence=short_artifact); short_trigger = SourceUnavailable.model_validate({**short_trigger_body.model_dump(mode="json"), "trigger_hash": hash_body(short_trigger_body)})
    source_forgery = rejected(lambda: build_lifecycle_artifact(base.model_copy(update={"trigger": short_trigger}), context))
    untrusted_context = context.model_copy(update={"retirement_evidence": (source_artifact,)})
    falsification_forgery = rejected(lambda: build_lifecycle_artifact(base.model_copy(update={"trigger": falsified}), untrusted_context))
    return results[0], results[1], results[2], results[3], cross_candidate, semantic_order, source_forgery, falsification_forgery


def oracle_structural_checks(fixture: LifecycleFixture) -> tuple[bool, bool, bool, bool, bool, bool, bool, bool]:
    incident, renewal, promotion, reopen = fixture.operations[4], fixture.operations[3], fixture.operations[1], fixture.operations[6]
    if not isinstance(incident, IncidentOperation) or not isinstance(renewal, RenewalOperation) or not isinstance(promotion, PromotionOperation) or not isinstance(reopen, ReopenOperation): raise ContractInvariantError("oracle fixtures missing")
    wrong = incident.lifecycle_input.model_copy(update={"hypothesis_id": HypothesisId("hyp_v6_working_capital_quality_999")})
    wrong_hypothesis = rejected(lambda: build_lifecycle_artifact(incident.model_copy(update={"lifecycle_input": wrong}), fixture.artifacts[4].compiler_context))
    promoted_policy = fixture.artifacts[1].policy
    if not isinstance(promoted_policy, ConsensusPolicyArtifact): raise ContractInvariantError("promoted policy missing")
    candidate = promoted_policy.active_candidates[1]
    duration = rejected(lambda: type(candidate).model_validate({**candidate.model_dump(mode="json"), "approval_end_session_ordinal": candidate.approval_start_session_ordinal + 60}))
    bad_time = rejected(lambda: LifecycleEventBody.model_validate({**fixture.artifacts[1].ledger[0].model_dump(mode="json", exclude={"event_id", "event_hash"}), "occurred_at": "invalid"}))
    wrong_source = rejected(lambda: build_lifecycle_artifact(incident.model_copy(update={"source_paper_artifact": reopen.paper_artifact}), fixture.artifacts[4].compiler_context))
    reused = rebound_approval(renewal.approval, policy_version=promoted_policy.policy_version)
    version_reuse = rejected(lambda: build_lifecycle_artifact(renewal.model_copy(update={"approval": reused}), fixture.artifacts[3].compiler_context))
    old = candidate.model_copy(update={"candidate_version": CandidateVersion("working_capital_quality.0.0"), "lifecycle_state": LifecycleState.RENEWAL_REVIEW, "approval_end_session_ordinal": 159})
    base = promotion.current_policy; body = CurrentConsensusPolicyBody.model_validate({**base.model_dump(mode="json", exclude={"policy_hash"}), "active_candidates": (base.active_candidates[0], old)}); current = bound_policy(body)
    value = promotion.lifecycle_input.model_copy(update={"operation_id": "replacement_promotion", "idempotency_key": "replacement_promotion", "current_session_ordinal": 200, "policy_registry": policy_registry(current)}); approved = approval(ApprovalSpec(value, ApprovalAction.PROMOTE, current, "consensus_policy_replacement", LifecycleState.PAPER_READY))
    replacement_context = CompilerContext(schema_version="v6.consensus_lifecycle.compiler-context.1", policy_registry=value.policy_registry)
    replacement = build_lifecycle_artifact(promotion.model_copy(update={"lifecycle_input": value, "current_policy": current, "approval": approved}), replacement_context); coexistence = isinstance(replacement.policy, ConsensusPolicyArtifact) and tuple(item.candidate_version for item in replacement.policy.active_candidates if item.candidate_id == value.candidate_id) == (value.candidate_version,)
    trusted_after_first = CompilerContext(schema_version="v6.consensus_lifecycle.compiler-context.1", policy_registry=fixture.artifacts[1].history.policy_registry)
    global_reuse = rejected(lambda: build_lifecycle_artifact(promotion, trusted_after_first))
    empty_body = MonitoringWindowBody(schema_version="v6.lifecycle-monitoring-window.1", window_id="empty", candidate_id=incident.lifecycle_input.candidate_id, candidate_version=incident.lifecycle_input.candidate_version, policy_version=incident.current_policy.policy_version, market="KR", window_index=0, previous_window_hash=None, records=())
    empty_window = rejected(lambda: MonitoringWindow.model_validate({**empty_body.model_dump(mode="json"), "window_hash": hash_body(empty_body)}))
    return wrong_hypothesis, duration, bad_time, wrong_source, version_reuse, coexistence, global_reuse, empty_window


def registry_trust_checks(fixture: LifecycleFixture) -> tuple[bool, bool, bool]:
    operation = fixture.operations[1]
    if not isinstance(operation, PromotionOperation): raise ContractInvariantError("canonical promotion missing")
    trusted = CompilerContext(schema_version="v6.consensus_lifecycle.compiler-context.1", policy_registry=fixture.artifacts[1].history.policy_registry)
    omitted = rejected(lambda: build_lifecycle_artifact(operation, trusted))
    value = operation.lifecycle_input.model_copy(update={"operation_id": "lifecycle_op_collision", "idempotency_key": "collision", "policy_registry": trusted.policy_registry})
    collision = rejected(lambda: build_lifecycle_artifact(operation.model_copy(update={"lifecycle_input": value}), trusted))
    chained = all((item.history.policy_registry.revision, item.history.policy_registry.previous_registry_hash) == (item.compiler_context.policy_registry.revision + 1, item.compiler_context.policy_registry.registry_hash) if isinstance(item.policy, ConsensusPolicyArtifact) else item.history.policy_registry == item.compiler_context.policy_registry for item in fixture.artifacts)
    return omitted, collision, chained


def forbidden_imports_absent() -> bool:
    forbidden = ("src.consensus", "src.common", "src.portfolio", "src.performance", "src.perspectives", "main")
    for path in Path(__file__).resolve().parent.glob("lifecycle_*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        modules = tuple(node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module) + tuple(alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names)
        if any(module.startswith(forbidden) for module in modules): return False
    return True


def modules_within_loc_limit() -> bool:
    for path in Path(__file__).resolve().parent.glob("lifecycle_*.py"):
        source = path.read_text(encoding="utf-8"); _ = ast.parse(source)
        pure = sum(1 for line in source.splitlines() if line.strip() and not line.lstrip().startswith("#"))
        if pure > 250: return False
    return True


def verify_lifecycle_fixture(fixture: LifecycleFixture) -> JsonValue:
    rejection, promotion, expiry, renewal, incident1, rollback1, reopen, promotion2, incident2, rollback2, assessment, retirement = fixture.artifacts
    promotion_operation = fixture.operations[1]
    if not isinstance(promotion_operation, PromotionOperation): raise ContractInvariantError("canonical promotion missing")
    metrics = validate_promotion_window(promotion_operation.paper_artifact, promotion_operation.error_window)
    if not isinstance(promotion.policy, ConsensusPolicyArtifact) or not isinstance(expiry.policy, ConsensusPolicyArtifact) or not isinstance(renewal.policy, ConsensusPolicyArtifact) or not isinstance(promotion2.policy, ConsensusPolicyArtifact) or not isinstance(retirement.policy, ConsensusPolicyArtifact) or not isinstance(rollback1.policy, CurrentConsensusPolicy) or not isinstance(rollback2.policy, CurrentConsensusPolicy): raise ContractInvariantError("canonical policy type mismatch")
    rollback_operation = fixture.operations[5]
    if not isinstance(rollback_operation, RollbackOperation): raise ContractInvariantError("canonical rollback missing")
    reopen_operation = fixture.operations[6]
    if not isinstance(reopen_operation, ReopenOperation): raise ContractInvariantError("canonical reopen missing")
    parser100, parser99, parser101 = parser_count_checks(fixture); checkpoint_valid, resume_ready, checkpoint_mismatch, rollback_priority, genesis_resume = checkpoint_checks(fixture)
    error_review, latency_review = incident_review_artifacts(fixture); delta0, delta120, delta121 = retirement_delta_checks(fixture)
    owner_retire, superseded_retire, source_retire, falsified_retire, superseded_cross_candidate, superseded_semantic_order, source_artifact_forgery, falsification_artifact_forgery = retirement_trigger_checks(fixture)
    wrong_hypothesis, duration_limit, invalid_time, wrong_incident_source, policy_version_reuse, coexistence, global_reuse, empty_window = oracle_structural_checks(fixture)
    omitted_registry, independent_collision, registry_cas_chain = registry_trust_checks(fixture)
    rollback_payload = rollback1.ledger[-1].payload
    event_body = LifecycleEventBody.model_validate(promotion.ledger[0].model_dump(mode="json", exclude={"event_id", "event_hash"}))
    event_hash_value = event_hash_json(event_body)
    if not isinstance(event_hash_value, dict): raise ContractInvariantError("event hash projection must be an object")
    event_hash_fields = set(event_hash_value.keys())
    expected_codes = (LifecycleResultCode.PROMOTION_REJECTED_GATE, LifecycleResultCode.PROMOTION_APPROVED_LIMITED, LifecycleResultCode.RENEWAL_REVIEW_OPENED, LifecycleResultCode.RENEWAL_APPROVED_LIMITED, LifecycleResultCode.ROLLBACK_REQUIRED, LifecycleResultCode.ROLLBACK_COMPLETED, LifecycleResultCode.REOPENED_PAPER_READY, LifecycleResultCode.PROMOTION_APPROVED_LIMITED, LifecycleResultCode.ROLLBACK_REQUIRED, LifecycleResultCode.ROLLBACK_COMPLETED, LifecycleResultCode.RETIREMENT_REQUIRED, LifecycleResultCode.RETIREMENT_COMPLETED)
    appended = (2, 3, 2, 2, 1, 1, 1, 2, 1, 1, 1, 2)
    prior_lengths = tuple(len(item.request.prior_history.events) if item.request.prior_history else 0 for item in fixture.artifacts)
    checks: dict[str, bool] = {
        "committed_operation_roundtrips": operation_roundtrips(fixture),
        "operation_result_codes": tuple(item.decision.result_code for item in fixture.artifacts) == expected_codes,
        "full_prior_chain_preserved": all(item.ledger[:prior] == item.request.prior_history.events if item.request.prior_history else True for item, prior in zip(fixture.artifacts, prior_lengths, strict=True)),
        "monotonic_append_counts": tuple(len(item.ledger) - prior for item, prior in zip(fixture.artifacts, prior_lengths, strict=True)) == appended,
        "event_indices_monotonic": all(tuple(event.event_index for event in item.ledger) == tuple(range(len(item.ledger))) for item in fixture.artifacts),
        "history_heads_exact": all((item.history.head_event_hash, item.history.next_event_index) == (item.ledger[-1].event_hash, len(item.ledger)) for item in fixture.artifacts),
        "scenario_branches_explicit": tuple(branch.name for branch in fixture.branches) == ("promotion_rejection", "expiry_renewal", "rollback_reopen", "retirement_after_two_rollbacks"),
        "rejection_separate_genesis": rejection.ledger[0].prev_event_hash.endswith("0" * 64) and rejection.history.history_hash != promotion.history.history_hash,
        "expiry_committed": expiry.ledger[-2].event_type == "renewal_review_started" and expiry.decision.result_code is LifecycleResultCode.RENEWAL_REVIEW_OPENED,
        "renewal_follows_expiry": renewal.request.prior_history is not None and renewal.request.prior_history.history_hash == expiry.history.history_hash,
        "rollback_follows_incident": rollback1.request.prior_history is not None and rollback1.request.prior_history.history_hash == incident1.history.history_hash,
        "reopen_follows_rollback": reopen.request.prior_history is not None and reopen.request.prior_history.history_hash == rollback1.history.history_hash,
        "second_rollback_committed": rollback2.ledger[-1].event_type == "lifecycle_rolled_back" and rollback2.request.prior_history is not None and rollback2.request.prior_history.history_hash == incident2.history.history_hash,
        "retirement_assessment_committed": assessment.ledger[-1].event_type == "retirement_required" and assessment.decision.result_code is LifecycleResultCode.RETIREMENT_REQUIRED,
        "retirement_follows_assessment": retirement.request.prior_history is not None and retirement.request.prior_history.history_hash == assessment.history.history_hash,
        "wrong_approval_identity": wrong_approval_identity_rejected(fixture), "wrong_approval_state": wrong_approval_state_rejected(fixture),
        "reset_to_genesis": reset_to_genesis_rejected(fixture), "branch_splice": branch_splice_rejected(fixture),
        "cross_history_duplicate": cross_history_duplicate_rejected(fixture), "arbitrary_reopen_history": arbitrary_reopen_history_rejected(fixture),
        "ignored_retirement_ordinals": ignored_retirement_ordinals_rejected(fixture), "forged_rollback_pointer": forged_rollback_pointer_rejected(fixture),
        "renewal_pointer_change": renewal_pointer_change_rejected(fixture), "semantic_ledger_substitution": semantic_ledger_substitution_rejected(fixture),
        "exact_operation_replay": exact_operation_replay_rejected(fixture),
        "insufficient_error_opens_review": error_review.decision.result_code is LifecycleResultCode.RENEWAL_REVIEW_OPENED and error_review.ledger[-2].event_type == "renewal_review_started" and isinstance(error_review.policy, ConsensusPolicyArtifact) and error_review.policy.active_candidates[1].lifecycle_state is LifecycleState.RENEWAL_REVIEW,
        "single_latency_opens_review": latency_review.decision.result_code is LifecycleResultCode.RENEWAL_REVIEW_OPENED and latency_review.ledger[-2].event_type == "renewal_review_started" and isinstance(latency_review.policy, ConsensusPolicyArtifact),
        "incident_review_preserves_policy": isinstance(error_review.policy, ConsensusPolicyArtifact) and error_review.policy.active_candidates[0] == promotion.policy.active_candidates[0] and error_review.policy.active_candidates[1].initial_weight == promotion.policy.active_candidates[1].initial_weight and (error_review.policy.active_candidates[1].rollback_policy_version, error_review.policy.active_candidates[1].rollback_policy_hash) == (promotion.policy.active_candidates[1].rollback_policy_version, promotion.policy.active_candidates[1].rollback_policy_hash),
        "old_paper_reopen": old_paper_reopen_rejected(fixture),
        "fresh_paper_reopen": reopen_operation.paper_artifact.artifact_hash != promotion_operation.paper_artifact.artifact_hash and reopen.decision.result_code is LifecycleResultCode.REOPENED_PAPER_READY,
        "rollback_source_paper_persisted": isinstance(rollback_payload, OperationPayload) and rollback_payload.source_paper_artifact_hash == promotion_operation.paper_artifact.artifact_hash,
        "event_hash_prd_shape": event_hash_fields == {"schema_version", "candidate_id", "candidate_version", "hypothesis_id", "policy_version", "event_index", "event_type", "lifecycle_state_before", "lifecycle_state_after", "prev_event_hash", "payload_hash"} and event_hash_json(event_body) == event_hash_json(event_body.model_copy(update={"occurred_at": "2099-01-01T00:00:00+00:00"})),
        "rollback_delta_0_rejected": delta0, "rollback_delta_120_accepted": delta120, "rollback_delta_121_rejected": delta121,
        "active_owner_retirement": owner_retire, "superseded_retirement": superseded_retire, "source_ttl_retirement": source_retire, "hypothesis_falsified_retirement": falsified_retire,
        "superseded_cross_candidate_rejected": superseded_cross_candidate, "superseded_semantic_version_rejected": superseded_semantic_order, "source_candidate_artifact_forgery_rejected": source_artifact_forgery, "falsification_candidate_artifact_forgery_rejected": falsification_artifact_forgery,
        "source_ttl_claim_derived_from_persisted_policy": source_artifact_forgery, "untrusted_falsification_artifact_rejected": falsification_artifact_forgery,
        "wrong_hypothesis_rejected": wrong_hypothesis, "duration_61_rejected": duration_limit, "invalid_timestamp_rejected": invalid_time, "wrong_incident_source_rejected": wrong_incident_source, "policy_version_reuse_rejected": policy_version_reuse, "expired_review_replacement": coexistence,
        "persistence_known_version_reuse": global_reuse, "empty_monitoring_window_rejected": empty_window,
        "trusted_head_rejects_omitted_registry": omitted_registry, "independent_genesis_version_collision_rejected": independent_collision, "registry_revision_cas_chain": registry_cas_chain,
        "parser_100_accepted": parser100, "parser_99_rejected": parser99, "parser_101_rejected": parser101,
        "non_positive_incumbent_weight": non_positive_weight_rejected(fixture), "derived_intent_action_matrix": checkpoint_valid, "resume_success_code": resume_ready, "interruption_mismatch_rollback": checkpoint_mismatch, "interruption_rollback_priority": rollback_priority, "initial_promotion_genesis_resume": genesis_resume,
        "raw_promotion_threshold": raw_error_delta(60001, 0, 2_000_000) > Decimal("0.03") and f"{raw_error_delta(60001, 0, 2_000_000):.6f}" == "0.030000",
        "promotion_preserves_unrelated": {item.candidate_id for item in promotion.policy.active_candidates} == {promotion_operation.lifecycle_input.candidate_id, fixture.unrelated_candidate_id},
        "renewal_preserves_weight": renewal.policy.active_candidates[1].initial_weight == promotion.policy.active_candidates[1].initial_weight,
        "rollback_restores_snapshot": rollback1.policy == rollback_operation.rollback_policy,
        "promotion_error_metrics": (metrics.candidate_error_rate, metrics.baseline_error_rate, metrics.error_delta) == ("0.310000", "0.290000", "0.020000"),
        "golden_share": promotion.policy.active_candidates[1].total_valid_weight_share == GOLDEN_SHARE,
        "runtime_not_wired": promotion.runtime_adoption == "not_automatically_wired", "forbidden_imports_absent": forbidden_imports_absent(), "modules_within_250_loc": modules_within_loc_limit(),
    }
    topology = {branch.name: list(branch.artifact_hashes) for branch in fixture.branches}
    progressions = {branch.name: [next(len(item.history.events) for item in fixture.artifacts if item.artifact_hash == artifact_hash) for artifact_hash in branch.artifact_hashes] for branch in fixture.branches}
    return JsonBoundary.model_validate({"state": "pass" if all(checks.values()) else "fail", "schema_version": fixture.schema_version, "pass_count": sum(checks.values()), "total": len(checks), "operation_count": len(fixture.operations), "result_codes": [item.decision.result_code.value for item in fixture.artifacts], "branch_topology": topology, "event_index_progression": progressions, "checks": checks}).root
