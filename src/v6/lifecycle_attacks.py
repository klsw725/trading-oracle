from collections.abc import Callable

from pydantic import ValidationError

from src.v4.models import JsonValue, canonical_hash

from .lifecycle_artifact import ConsensusLifecycleArtifact, LifecycleArtifactBody, build_lifecycle_artifact
from .lifecycle_evidence import hash_body
from .lifecycle_events import LifecycleEvent, LifecycleEventBody, OperationPayload, PolicyEmittedPayload, event_hash_json
from .lifecycle_fixture import LifecycleFixture
from .lifecycle_history import LifecycleHistory, LifecycleHistoryBody
from .lifecycle_models import LifecycleResultCode, LifecycleState, OperatorApproval, OperatorApprovalBody
from .lifecycle_operations import IncidentOperation, PromotionOperation, RenewalOperation, ReopenAuthorization, ReopenAuthorizationBody, ReopenOperation, RetirementAssessmentOperation, RollbackOperation
from .models import ContractInvariantError
from .lifecycle_policy import ConsensusPolicyArtifact


def rejected[T](action: Callable[[], T]) -> bool:
    try:
        _ = action()
    except (ValidationError, ContractInvariantError):
        return True
    return False


def rebound_approval(approval: OperatorApproval, **updates: JsonValue) -> OperatorApproval:
    body = OperatorApprovalBody.model_validate({**approval.model_dump(mode="json", exclude={"approval_hash"}), **updates})
    return OperatorApproval.model_validate({**body.model_dump(mode="json"), "approval_hash": hash_body(body)})


def wrong_approval_identity_rejected(fixture: LifecycleFixture) -> bool:
    operation = fixture.operations[3]
    if not isinstance(operation, RenewalOperation): return False
    forged = rebound_approval(operation.approval, candidate_id=fixture.unrelated_candidate_id)
    return rejected(lambda: build_lifecycle_artifact(operation.model_copy(update={"approval": forged}), fixture.artifacts[3].compiler_context))


def wrong_approval_state_rejected(fixture: LifecycleFixture) -> bool:
    operation = fixture.operations[5]
    if not isinstance(operation, RollbackOperation): return False
    forged = rebound_approval(operation.approval, from_state=LifecycleState.RENEWAL_REVIEW)
    return rejected(lambda: build_lifecycle_artifact(operation.model_copy(update={"approval": forged}), fixture.artifacts[5].compiler_context))


def reset_to_genesis_rejected(fixture: LifecycleFixture) -> bool:
    operation, genesis = fixture.operations[3], fixture.artifacts[1].history
    if not isinstance(operation, RenewalOperation): return False
    forged = rebound_approval(operation.approval, prior_history_hash=genesis.history_hash)
    request = operation.model_copy(update={"prior_history": genesis, "expected_prior_history_hash": genesis.history_hash, "approval": forged})
    return rejected(lambda: build_lifecycle_artifact(request, fixture.artifacts[3].compiler_context))


def branch_splice_rejected(fixture: LifecycleFixture) -> bool:
    operation, wrong = fixture.operations[8], fixture.artifacts[1].history
    if not isinstance(operation, IncidentOperation): return False
    request = operation.model_copy(update={"prior_history": wrong, "expected_prior_history_hash": wrong.history_hash})
    return rejected(lambda: build_lifecycle_artifact(request, fixture.artifacts[8].compiler_context))


def cross_history_duplicate_rejected(fixture: LifecycleFixture) -> bool:
    operation, prior = fixture.operations[4], fixture.operations[1]
    if not isinstance(operation, IncidentOperation) or not isinstance(prior, PromotionOperation): return False
    value = operation.lifecycle_input.model_copy(update={"idempotency_key": prior.lifecycle_input.idempotency_key})
    return rejected(lambda: build_lifecycle_artifact(operation.model_copy(update={"lifecycle_input": value}), fixture.artifacts[4].compiler_context))


def arbitrary_reopen_history_rejected(fixture: LifecycleFixture) -> bool:
    operation, wrong = fixture.operations[6], fixture.artifacts[9].history
    request = operation.model_copy(update={"prior_history": wrong, "expected_prior_history_hash": wrong.history_hash})
    return rejected(lambda: build_lifecycle_artifact(request, fixture.artifacts[6].compiler_context))


def ignored_retirement_ordinals_rejected(fixture: LifecycleFixture) -> bool:
    operation, one_rollback = fixture.operations[10], fixture.artifacts[5].history
    if not isinstance(operation, RetirementAssessmentOperation): return False
    request = operation.model_copy(update={"prior_history": one_rollback, "expected_prior_history_hash": one_rollback.history_hash})
    return rejected(lambda: build_lifecycle_artifact(request, fixture.artifacts[10].compiler_context))


def forged_rollback_pointer_rejected(fixture: LifecycleFixture) -> bool:
    operation = fixture.operations[1]
    if not isinstance(operation, PromotionOperation): return False
    forged = rebound_approval(operation.approval, rollback_policy_version="forged_previous", rollback_policy_hash=f"sha256:{'f' * 64}")
    return rejected(lambda: build_lifecycle_artifact(operation.model_copy(update={"approval": forged}), fixture.artifacts[1].compiler_context))


def renewal_pointer_change_rejected(fixture: LifecycleFixture) -> bool:
    operation = fixture.operations[3]
    if not isinstance(operation, RenewalOperation): return False
    forged = rebound_approval(operation.approval, rollback_policy_hash=f"sha256:{'e' * 64}")
    return rejected(lambda: build_lifecycle_artifact(operation.model_copy(update={"approval": forged}), fixture.artifacts[3].compiler_context))


def rehash_chain(events: tuple[LifecycleEvent, ...], result_code: str) -> tuple[LifecycleEvent, ...]:
    rebuilt: list[LifecycleEvent] = []
    for index, original in enumerate(events):
        payload = original.payload
        if index == 0 and isinstance(payload, OperationPayload):
            payload = payload.model_copy(update={"result_code": result_code})
        if isinstance(payload, PolicyEmittedPayload):
            payload = payload.model_copy(update={"transition_event_hash": rebuilt[-1].event_hash})
        body = LifecycleEventBody.model_validate({**original.model_dump(mode="json", exclude={"event_id", "event_hash"}), "prev_event_hash": rebuilt[-1].event_hash if rebuilt else f"sha256:{'0' * 64}", "payload_hash": hash_body(payload), "payload": payload})
        rebuilt.append(LifecycleEvent.model_validate({**body.model_dump(mode="json"), "event_id": f"lifecycle_v6_{index:04d}", "event_hash": canonical_hash(event_hash_json(body))}))
    return tuple(rebuilt)


def semantic_ledger_substitution_rejected(fixture: LifecycleFixture) -> bool:
    artifact = fixture.artifacts[1]
    events = rehash_chain(artifact.ledger, "ROLLBACK_COMPLETED")
    old = artifact.history
    history_body = LifecycleHistoryBody.model_validate({**old.model_dump(mode="json", exclude={"history_hash"}), "events": events, "head_event_hash": events[-1].event_hash})
    if not rejected(lambda: LifecycleHistory.model_validate({**history_body.model_dump(mode="json"), "history_hash": hash_body(history_body)})):
        return False
    raw = {**artifact.model_dump(mode="json", exclude={"artifact_hash"}), "ledger": events, "ledger_head_hash": events[-1].event_hash}
    return rejected(lambda: ConsensusLifecycleArtifact.model_validate({**raw, "artifact_hash": hash_body(LifecycleArtifactBody.model_validate(raw))}))


def operation_roundtrips(fixture: LifecycleFixture) -> bool:
    return all(ConsensusLifecycleArtifact.model_validate(item.model_dump(mode="json")) == item for item in fixture.artifacts)


def exact_operation_replay_rejected(fixture: LifecycleFixture) -> bool:
    history, promotion = fixture.artifacts[6].history, fixture.artifacts[1]
    if not isinstance(promotion.policy, ConsensusPolicyArtifact): return False
    events = list(history.events)
    for source in promotion.ledger[1:]:
        payload = source.payload
        if isinstance(payload, PolicyEmittedPayload): payload = payload.model_copy(update={"transition_event_hash": events[-1].event_hash})
        body = LifecycleEventBody.model_validate({**source.model_dump(mode="json", exclude={"event_id", "event_hash"}), "event_index": len(events), "prev_event_hash": events[-1].event_hash, "payload_hash": hash_body(payload), "payload": payload})
        events.append(LifecycleEvent.model_validate({**body.model_dump(mode="json"), "event_id": f"lifecycle_v6_{len(events):04d}", "event_hash": canonical_hash(event_hash_json(body))}))
    body = LifecycleHistoryBody.model_validate({**history.model_dump(mode="json", exclude={"history_hash"}), "events": tuple(events), "current_state": LifecycleState.LIMITED_PRODUCTION, "current_policy_version": promotion.policy.policy_version, "current_policy_hash": promotion.policy.policy_hash, "head_event_hash": events[-1].event_hash, "next_event_index": len(events)})
    return rejected(lambda: LifecycleHistory.model_validate({**body.model_dump(mode="json"), "history_hash": hash_body(body)}))


def old_paper_reopen_rejected(fixture: LifecycleFixture) -> bool:
    operation = fixture.operations[6]
    if not isinstance(operation, ReopenOperation): return False
    old_paper = fixture.operations[1]
    if not isinstance(old_paper, PromotionOperation): return False
    rollback = operation.prior_history.events[-1]
    body = ReopenAuthorizationBody(schema_version="v6.consensus_lifecycle.reopen-authorization.1", candidate_id=operation.lifecycle_input.candidate_id, candidate_version=operation.lifecycle_input.candidate_version, prior_history_hash=operation.prior_history.history_hash, rollback_event_hash=rollback.event_hash, prior_source_paper_artifact_hash=old_paper.paper_artifact.artifact_hash, paper_artifact_hash=old_paper.paper_artifact.artifact_hash)
    authorization = ReopenAuthorization.model_validate({**body.model_dump(mode="json"), "authorization_hash": hash_body(body)})
    request = operation.model_copy(update={"paper_artifact": old_paper.paper_artifact, "authorization": authorization})
    return rejected(lambda: build_lifecycle_artifact(request, fixture.artifacts[6].compiler_context))


def history_with_rollback_delta(fixture: LifecycleFixture, delta: int) -> LifecycleHistory:
    history = fixture.artifacts[9].history
    rollback_indices = tuple(index for index, event in enumerate(history.events) if event.event_type == "lifecycle_rolled_back")
    first_payload = history.events[rollback_indices[0]].payload
    if not isinstance(first_payload, OperationPayload): raise ContractInvariantError("first rollback payload missing")
    target = rollback_indices[-1]
    events: list[LifecycleEvent] = []
    for index, source in enumerate(history.events):
        payload = source.payload
        if index == target and isinstance(payload, OperationPayload): payload = payload.model_copy(update={"session_ordinal": first_payload.session_ordinal + delta})
        if isinstance(payload, PolicyEmittedPayload): payload = payload.model_copy(update={"transition_event_hash": events[-1].event_hash})
        body = LifecycleEventBody.model_validate({**source.model_dump(mode="json", exclude={"event_id", "event_hash"}), "prev_event_hash": events[-1].event_hash if events else f"sha256:{'0' * 64}", "payload_hash": hash_body(payload), "payload": payload})
        events.append(LifecycleEvent.model_validate({**body.model_dump(mode="json"), "event_id": source.event_id, "event_hash": canonical_hash(event_hash_json(body))}))
    history_body = LifecycleHistoryBody.model_validate({**history.model_dump(mode="json", exclude={"history_hash"}), "events": tuple(events), "head_event_hash": events[-1].event_hash})
    return LifecycleHistory.model_validate({**history_body.model_dump(mode="json"), "history_hash": hash_body(history_body)})


def retirement_delta_checks(fixture: LifecycleFixture) -> tuple[bool, bool, bool]:
    operation = fixture.operations[10]
    if not isinstance(operation, RetirementAssessmentOperation): return False, False, False
    def build(delta: int) -> ConsensusLifecycleArtifact:
        history = history_with_rollback_delta(fixture, delta)
        value = operation.lifecycle_input.model_copy(update={"current_session_ordinal": 122 + delta})
        return build_lifecycle_artifact(operation.model_copy(update={"prior_history": history, "expected_prior_history_hash": history.history_hash, "lifecycle_input": value}), fixture.artifacts[10].compiler_context)
    accepted = build(120)
    return rejected(lambda: build(0)), accepted.decision.result_code is LifecycleResultCode.RETIREMENT_REQUIRED, rejected(lambda: build(121))
