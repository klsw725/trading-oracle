from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from .source_bundle import SourceBundleManifest
from .source_checkpoint import TransitionCheckpoint, verify_checkpoint
from .source_context import PolicyRegistry, TrustedCompilerContext, advance_registry, verify_context
from .source_events import AuditPayload
from .source_history import AuditHistory, append_event
from .source_ledger import OperationLedger, append_ledger, empty_ledger
from .source_evaluator import evaluate_operation
from .source_models import LifecycleState, SourcePolicyError
from .source_operations import IncidentOperation, PromotionOperation, RetirementOperation, SourceOperation, operation_hash
from .source_policy import CacheProjection, SourcePolicyBody, SourcePolicySnapshot, bind_policy, ordered_fallback


@dataclass(frozen=True, slots=True)
class CompilationState:
    policy: SourcePolicySnapshot
    registry: PolicyRegistry
    history: AuditHistory
    checkpoints: tuple[TransitionCheckpoint, ...]
    ledger: OperationLedger = field(default_factory=empty_ledger)


type EventType = Literal["promotion", "disable", "expiry", "retirement"]
type DecisionReason = Literal["promotion_gate_passed", "incident", "contract_expired", "voluntary_retirement"]


def _event_kind(operation: SourceOperation) -> tuple[EventType, DecisionReason]:
    match operation:  # noqa: MATCH_OK - SourceOperation union is fully enumerated
        case PromotionOperation():
            return "promotion", "promotion_gate_passed"
        case IncidentOperation() if operation.incident_code.value == "contract_expired":
            return "expiry", "contract_expired"
        case IncidentOperation():
            return "disable", "incident"
        case RetirementOperation() if operation.reason.value == "contract_expired":
            return "retirement", "contract_expired"
        case RetirementOperation():
            return "retirement", "voluntary_retirement"


def compile_operation(operation: SourceOperation, state: CompilationState, manifest: SourceBundleManifest, context: TrustedCompilerContext, evaluated_at: datetime) -> CompilationState:
    duplicates = tuple(event for event in state.history.events if event.payload.operation_id == operation.operation_id or event.payload.idempotency_key == operation.idempotency_key)
    if duplicates:
        prior = duplicates[0].payload
        if (prior.operation_id, prior.idempotency_key, prior.operation_hash) == (operation.operation_id, operation.idempotency_key, operation_hash(operation)):
            return state
        raise SourcePolicyError("DUPLICATE_OPERATION_CONFLICT", operation.operation_id)
    if operation.expected_registry_hash != state.registry.registry_hash:
        raise SourcePolicyError("STALE_TRUSTED_REGISTRY", operation.operation_id)
    target = evaluate_operation(operation, state.policy, manifest, context, evaluated_at)
    traffic_share = operation.traffic_share if isinstance(operation, (PromotionOperation, IncidentOperation)) else "0.00"
    generation = state.policy.cache.generation + 1
    closed = target in (LifecycleState.DISABLED, LifecycleState.RETIRING, LifecycleState.RETIRED, LifecycleState.EXPIRED)
    fallback = () if closed else ordered_fallback(context.fallback_candidates, manifest.source_bundle_id)
    cache = CacheProjection(generation=generation, current=not closed, audit_only_generations=(*state.policy.cache.audit_only_generations, state.policy.cache.generation), purge_required=closed, policy_hash=None, source_bundle_hash=manifest.source_bundle_hash, quality_result_hash=manifest.quality[0].artifact_hash)
    body = SourcePolicyBody(schema_version="v7.source-policy.snapshot.1", policy_version=state.policy.policy_version + 1, source_bundle_id=manifest.source_bundle_id, source_bundle_hash=manifest.source_bundle_hash, contract_ref_hash=manifest.contract.contract_ref_hash, state=target, traffic_share=traffic_share, cache=cache, fallback_order=fallback, production_isolation="offline_only_no_production_imports")
    policy = bind_policy(body)
    checkpoint = TransitionCheckpoint(schema_version="v7.source-policy.checkpoint.1", operation_id=operation.operation_id, expected_prior_policy_hash=state.policy.policy_hash, intended_policy_hash=policy.policy_hash, safe_policy_hash=state.policy.policy_hash, interrupted=operation.interrupted, observed_traffic_share="0.00" if operation.interrupted else policy.traffic_share)
    verify_checkpoint(checkpoint)
    if operation.interrupted:
        return CompilationState(state.policy, state.registry, state.history, (*state.checkpoints, checkpoint), state.ledger)
    event_type, reason = _event_kind(operation)
    payload = AuditPayload(operation_id=operation.operation_id, idempotency_key=operation.idempotency_key, operation_hash=operation_hash(operation), event_type=event_type, from_state=state.policy.state, to_state=target, traffic_share=traffic_share, decision_reason=reason, previous_policy_hash=state.policy.policy_hash, new_policy_hash=policy.policy_hash, source_bundle_hash=manifest.source_bundle_hash, cache_generation=generation, interrupted_transition=operation.interrupted)
    history = append_event(state.history, payload)
    return CompilationState(policy, advance_registry(state.registry, policy), history, (*state.checkpoints, checkpoint), append_ledger(state.ledger, history.events[-1]))


def verify_trusted_context(context: TrustedCompilerContext) -> None:
    verify_context(context)
