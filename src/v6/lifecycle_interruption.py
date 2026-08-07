from typing import Literal, Self

from pydantic import model_validator

from .lifecycle_evidence import hash_body
from .lifecycle_history import LifecycleHistory
from .lifecycle_models import LifecycleResultCode
from .models import BoundaryModel, ContractInvariantError
from .offline_models import ContentHash
from .lifecycle_operations import LifecycleOperation
from .lifecycle_compiler import compile_operation
from .lifecycle_context import CompilerContext
from .lifecycle_ledger import LedgerCompilation, approval_hash_for, semantic_ledger


OperationType = Literal["promotion", "renewal", "rollback", "retirement"]
ResumeAction = Literal["write_all", "write_policy_and_commit", "write_transition_and_commit", "write_commit", "noop", "rollback_required"]


class PendingIntentBody(BoundaryModel):
    schema_version: Literal["v6.consensus_lifecycle.pending-intent.1"]
    operation_id: str
    idempotency_key: str
    operation_type: OperationType
    request: LifecycleOperation
    compiler_context: CompilerContext
    expected_history_hash: ContentHash
    expected_prev_event_hash: ContentHash
    expected_first_event_index: int
    transition_hash: ContentHash
    policy_hash: ContentHash
    commit_hash: ContentHash
    approval_hash: ContentHash


class PendingIntent(PendingIntentBody):
    intent_hash: ContentHash

    @model_validator(mode="after")
    def hash_bound(self) -> Self:
        body = PendingIntentBody.model_validate(self.model_dump(mode="json", exclude={"intent_hash"}))
        derived = pending_intent_body(self.request, self.compiler_context)
        if body != derived or self.intent_hash != hash_body(body): raise ContractInvariantError("pending lifecycle intent derivation mismatch")
        return self


class InterruptionCheckpointBody(BoundaryModel):
    schema_version: Literal["v6.consensus_lifecycle.checkpoint.3"]
    pending: PendingIntent
    head_state: Literal["genesis", "history"]
    observed_history_hash: ContentHash
    observed_ledger_head_hash: ContentHash
    observed_next_event_index: int
    persisted_transition_hash: ContentHash | None
    persisted_policy_hash: ContentHash | None
    persisted_commit_hash: ContentHash | None


class InterruptionCheckpoint(InterruptionCheckpointBody):
    checkpoint_hash: ContentHash

    @model_validator(mode="after")
    def hash_bound(self) -> Self:
        body = InterruptionCheckpointBody.model_validate(self.model_dump(mode="json", exclude={"checkpoint_hash"}))
        if self.checkpoint_hash != hash_body(body): raise ContractInvariantError("interruption checkpoint hash mismatch")
        return self


class ResumeDecision(BoundaryModel):
    action: ResumeAction
    result_code: LifecycleResultCode


def resume_decision(checkpoint: InterruptionCheckpoint, history: LifecycleHistory | None) -> ResumeDecision:
    pending = checkpoint.pending
    head = (history.history_hash, history.head_event_hash, history.next_event_index) if history else (f"sha256:{'0' * 64}", f"sha256:{'0' * 64}", 0)
    observed = (checkpoint.observed_history_hash, checkpoint.observed_ledger_head_hash, checkpoint.observed_next_event_index)
    expected_head = (pending.expected_history_hash, pending.expected_prev_event_hash, pending.expected_first_event_index)
    persisted = (checkpoint.persisted_transition_hash, checkpoint.persisted_policy_hash, checkpoint.persisted_commit_hash)
    expected = (pending.transition_hash, pending.policy_hash, pending.commit_hash)
    expected_state = "history" if history else "genesis"
    if checkpoint.head_state != expected_state or observed != head or expected_head != head or any(value is not None and value != target for value, target in zip(persisted, expected, strict=True)):
        return ResumeDecision(action="rollback_required", result_code=LifecycleResultCode.ROLLBACK_REQUIRED)
    match tuple(value is not None for value in persisted):  # noqa: MATCH_OK - all persistence shapes handled
        case (False, False, False): action = "write_all"
        case (True, False, False): action = "write_policy_and_commit"
        case (False, True, False): action = "write_transition_and_commit"
        case (True, True, False): action = "write_commit"
        case (True, True, True): action = "noop"
        case _: return ResumeDecision(action="rollback_required", result_code=LifecycleResultCode.ROLLBACK_REQUIRED)
    code = LifecycleResultCode.NOOP_ALREADY_COMMITTED if action == "noop" else LifecycleResultCode.RESUME_READY
    return ResumeDecision(action=action, result_code=code)


def select_pending_intent(intents: tuple[PendingIntent, ...]) -> PendingIntent:
    rollbacks = tuple(intent for intent in intents if intent.operation_type == "rollback")
    return rollbacks[0] if rollbacks else intents[0]


def pending_intent_body(request: LifecycleOperation, context: CompilerContext) -> PendingIntentBody:
    if request.operation_type not in ("promotion", "renewal", "rollback", "retirement"): raise ContractInvariantError("operation does not support interruption")
    compiled = compile_operation(request, context); generated = request.lifecycle_input.occurred_at.isoformat(); ledger = semantic_ledger(LedgerCompilation(request, compiled.decision, compiled.policy, compiled.evidence_hash, generated)); prior = request.prior_history
    prior_count = len(prior.events) if prior else 0
    transition_index = prior_count + (1 if not prior and ledger[0].event_type == "lifecycle_created" else 0)
    transition = ledger[transition_index]; policy_hash = compiled.policy.policy_hash if compiled.policy else f"sha256:{'0' * 64}"; approval = approval_hash_for(request)
    if approval is None: raise ContractInvariantError("interrupted operation requires approval")
    commit_hash = hash_body(CommitRecord(operation_id=request.lifecycle_input.operation_id, transition_hash=transition.event_hash, policy_hash=policy_hash))
    return PendingIntentBody(schema_version="v6.consensus_lifecycle.pending-intent.1", operation_id=request.lifecycle_input.operation_id, idempotency_key=request.lifecycle_input.idempotency_key, operation_type=request.operation_type, request=request, compiler_context=context, expected_history_hash=prior.history_hash if prior else f"sha256:{'0' * 64}", expected_prev_event_hash=prior.head_event_hash if prior else f"sha256:{'0' * 64}", expected_first_event_index=prior.next_event_index if prior else 0, transition_hash=transition.event_hash, policy_hash=policy_hash, commit_hash=commit_hash, approval_hash=approval)


class CommitRecord(BoundaryModel):
    operation_id: str
    transition_hash: ContentHash
    policy_hash: ContentHash
