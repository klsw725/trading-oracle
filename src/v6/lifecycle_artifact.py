from typing import Literal, Self

from datetime import datetime
from pydantic import field_validator, model_validator

from src.v4.models import JsonValue

from .lifecycle_compiler import compile_operation
from .lifecycle_context import CompilerContext
from .lifecycle_evidence import hash_body
from .lifecycle_events import LifecycleEvent
from .lifecycle_history import LifecycleHistory, LifecycleHistoryBody
from .lifecycle_ledger import LedgerCompilation, semantic_ledger
from .lifecycle_models import LifecycleDecision
from .lifecycle_operations import LifecycleOperation
from .lifecycle_policy import ConsensusPolicyArtifact, CurrentConsensusPolicy
from .models import BoundaryModel, ContractInvariantError, JsonBoundary
from .offline_models import ContentHash
from .lifecycle_registry import PolicyVersionEntry, PolicyVersionRegistry, extend_policy_registry


class LifecycleArtifactBody(BoundaryModel):
    schema_version: Literal["v6.consensus-lifecycle-artifact.3"]
    generated_at: str
    request: LifecycleOperation
    compiler_context: CompilerContext
    decision: LifecycleDecision
    ledger: tuple[LifecycleEvent, ...]
    ledger_head_hash: ContentHash
    history: LifecycleHistory
    policy: ConsensusPolicyArtifact | CurrentConsensusPolicy | None
    runtime_adoption: Literal["not_automatically_wired"]

    @field_validator("generated_at")
    @classmethod
    def valid_time(cls, value: str) -> str:
        if datetime.fromisoformat(value).tzinfo is None:
            raise ContractInvariantError("lifecycle artifact timestamp requires timezone")
        return value


class ConsensusLifecycleArtifact(LifecycleArtifactBody):
    artifact_hash: ContentHash

    @model_validator(mode="after")
    def verified_integrity(self) -> Self:
        compiled = compile_operation(self.request, self.compiler_context)
        expected = semantic_ledger(LedgerCompilation(self.request, compiled.decision, compiled.policy, compiled.evidence_hash, self.generated_at))
        expected_history = build_history(self.request, self.compiler_context, compiled.decision, compiled.policy, expected)
        generated = self.request.lifecycle_input.occurred_at.isoformat()
        prior_count = len(self.request.prior_history.events) if self.request.prior_history else 0
        if self.generated_at != generated or any(event.occurred_at != generated for event in self.ledger[prior_count:]) or self.decision != compiled.decision or self.policy != compiled.policy or self.ledger != expected or self.history != expected_history:
            raise ContractInvariantError("lifecycle semantic reconstruction mismatch")
        if not self.ledger or self.ledger_head_hash != self.ledger[-1].event_hash or self.history.events != self.ledger:
            raise ContractInvariantError("lifecycle ledger head mismatch")
        body = LifecycleArtifactBody.model_validate(self.model_dump(mode="json", exclude={"artifact_hash"}))
        if self.artifact_hash != hash_body(body):
            raise ContractInvariantError("lifecycle artifact hash mismatch")
        return self


def build_lifecycle_artifact(request: LifecycleOperation, context: CompilerContext) -> ConsensusLifecycleArtifact:
    if request.lifecycle_input.policy_registry.registry_hash != context.policy_registry.registry_hash: raise ContractInvariantError("request registry differs from trusted persistence head")
    compiled = compile_operation(request, context)
    generated_at = request.lifecycle_input.occurred_at.isoformat()
    ledger = semantic_ledger(LedgerCompilation(request, compiled.decision, compiled.policy, compiled.evidence_hash, generated_at))
    history = build_history(request, context, compiled.decision, compiled.policy, ledger)
    body = LifecycleArtifactBody(schema_version="v6.consensus-lifecycle-artifact.3", generated_at=generated_at, request=request, compiler_context=context, decision=compiled.decision, ledger=ledger, ledger_head_hash=ledger[-1].event_hash, history=history, policy=compiled.policy, runtime_adoption="not_automatically_wired")
    return ConsensusLifecycleArtifact.model_validate({**body.model_dump(mode="json"), "artifact_hash": hash_body(body)})


def build_history(request: LifecycleOperation, context: CompilerContext, decision: LifecycleDecision, policy: ConsensusPolicyArtifact | CurrentConsensusPolicy | None, ledger: tuple[LifecycleEvent, ...]) -> LifecycleHistory:
    effective_policy = policy or request.current_policy
    genesis_policy_version = request.prior_history.genesis_policy_version if request.prior_history else request.current_policy.policy_version
    genesis_policy_hash = request.prior_history.genesis_policy_hash if request.prior_history else request.current_policy.policy_hash
    if request.lifecycle_input.policy_registry.registry_hash != context.policy_registry.registry_hash: raise ContractInvariantError("operation policy registry is stale against trusted head")
    registry = extend_registry(context.policy_registry, policy)
    history_body = LifecycleHistoryBody(schema_version="v6.consensus_lifecycle.history.1", candidate_id=request.lifecycle_input.candidate_id, candidate_version=request.lifecycle_input.candidate_version, hypothesis_id=request.lifecycle_input.hypothesis_id, policy_registry=registry, genesis_policy_version=genesis_policy_version, genesis_policy_hash=genesis_policy_hash, events=ledger, current_state=decision.next_state, current_policy_version=effective_policy.policy_version, current_policy_hash=effective_policy.policy_hash, head_event_hash=ledger[-1].event_hash, next_event_index=len(ledger))
    return LifecycleHistory.model_validate({**history_body.model_dump(mode="json"), "history_hash": hash_body(history_body)})


def extend_registry(registry: PolicyVersionRegistry, policy: ConsensusPolicyArtifact | CurrentConsensusPolicy | None) -> PolicyVersionRegistry:
    if not isinstance(policy, ConsensusPolicyArtifact): return registry
    return extend_policy_registry(registry, PolicyVersionEntry(policy_version=policy.policy_version, policy_hash=policy.policy_hash))


def lifecycle_artifact_json(artifact: ConsensusLifecycleArtifact) -> JsonValue:
    return JsonBoundary.model_validate(artifact.model_dump(mode="json")).root
