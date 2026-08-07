from dataclasses import replace

from .source_artifact import compile_source_artifact
from .source_compiler import CompilationState, compile_operation
from .source_context import SourceTrustInputs, TrustedCompilerContext
from .source_history import empty_history
from .source_models import LifecycleState, RetirementReason, SourcePolicyError
from .source_operations import PromotionOperation, RetirementOperation
from .source_policy import verify_policy_projection
from .source_fixture import SourceLifecycleFixture
from .source_trust import issue_source_context


def _state(fixture: SourceLifecycleFixture, context: TrustedCompilerContext, count: int) -> CompilationState:
    state = CompilationState(fixture.initial_policy, context.trusted_registry, empty_history(), ())
    for operation in fixture.operations[:count]:
        state = compile_operation(operation, state, fixture.manifest, context, fixture.evaluated_at)
    return state


def _joint_substitution_rejected(fixture: SourceLifecycleFixture, inputs: SourceTrustInputs) -> bool:
    root = "sha256:" + "f" * 64
    value_fixture = inputs.value_fixture.model_copy(update={"cohort_manifest": inputs.value_fixture.cohort_manifest.model_copy(update={"manifest_root": root})})
    value_trust = inputs.value_trust.model_copy(update={"expected_cohort_root": root})
    try:
        _ = issue_source_context(fixture, SourceTrustInputs(inputs.source, value_fixture, value_trust))
    except SourcePolicyError as error:
        return error.code == "SOURCE_TRUST_MISMATCH"
    return False


def _conflicting_duplicate_rejected(fixture: SourceLifecycleFixture, context: TrustedCompilerContext) -> bool:
    first = fixture.operations[0]
    if not isinstance(first, PromotionOperation):
        return False
    conflict = first.model_copy(update={"to_state": LifecycleState.PRIMARY, "traffic_share": "1.00"})
    try:
        _ = compile_operation(conflict, _state(fixture, context, 1), fixture.manifest, context, fixture.evaluated_at)
    except SourcePolicyError as error:
        return error.code == "DUPLICATE_OPERATION_CONFLICT"
    return False


def _terminal_matches_primary(fixture: SourceLifecycleFixture, context: TrustedCompilerContext) -> bool:
    primary = fixture.model_copy(update={"operations": fixture.operations[:5]})
    artifact = compile_source_artifact(primary, context)
    return artifact.final_policy.state is LifecycleState.PRIMARY and artifact.terminal_code == "PROMOTION_ACCEPTED_GRADUAL"


def _primary_retirement_supported(fixture: SourceLifecycleFixture, context: TrustedCompilerContext) -> bool:
    primary = _state(fixture, context, 5)
    first = RetirementOperation(kind="retirement", operation_id="primary_retire", idempotency_key="primary-retire-1", expected_prior_policy_hash=primary.policy.policy_hash, expected_registry_hash=primary.registry.registry_hash, reason=RetirementReason.OWNER_REQUEST)
    try:
        retiring = compile_operation(first, primary, fixture.manifest, context, fixture.evaluated_at)
        second = first.model_copy(update={"operation_id": "primary_retire_close", "idempotency_key": "primary-retire-2", "expected_prior_policy_hash": retiring.policy.policy_hash, "expected_registry_hash": retiring.registry.registry_hash})
        retired = compile_operation(second, retiring, fixture.manifest, context, fixture.evaluated_at)
    except SourcePolicyError:
        return False
    return retiring.policy.state is LifecycleState.RETIRING and retired.policy.state is LifecycleState.RETIRED


def _expired_retirement_supported(fixture: SourceLifecycleFixture, context: TrustedCompilerContext) -> bool:
    expiry = fixture.manifest.contract.valid_until
    if expiry is None:
        return False
    primary = _state(fixture, context, 5)
    first = RetirementOperation(kind="retirement", operation_id="expiry_retire", idempotency_key="expiry-retire-1", expected_prior_policy_hash=primary.policy.policy_hash, expected_registry_hash=primary.registry.registry_hash, reason=RetirementReason.OWNER_REQUEST)
    try:
        expired = compile_operation(first, primary, fixture.manifest, context, expiry)
        second = first.model_copy(update={"operation_id": "expiry_retire_close", "idempotency_key": "expiry-retire-2", "expected_prior_policy_hash": expired.policy.policy_hash, "expected_registry_hash": expired.registry.registry_hash})
        retired = compile_operation(second, expired, fixture.manifest, context, expiry)
    except SourcePolicyError:
        return False
    return expired.policy.state is LifecycleState.EXPIRED and retired.policy.state is LifecycleState.RETIRED


def _hash_only_license_rejected(fixture: SourceLifecycleFixture, context: TrustedCompilerContext) -> bool:
    first = fixture.operations[0]
    if not isinstance(first, PromotionOperation):
        return False
    contract = fixture.manifest.contract.model_copy(update={"license_scope": "hash_only"})
    manifest = fixture.manifest.model_copy(update={"contract": contract})
    changed_context = replace(context, contract=contract)
    try:
        _ = compile_operation(first, CompilationState(fixture.initial_policy, context.trusted_registry, empty_history(), ()), manifest, changed_context, fixture.evaluated_at)
    except SourcePolicyError as error:
        return error.code == "LICENSE_CURRENT_USE_FORBIDDEN"
    return False


def _fallback_prefix_typed(fixture: SourceLifecycleFixture, context: TrustedCompilerContext) -> bool:
    primary = _state(fixture, context, 5).policy
    shortened = primary.model_copy(update={"fallback_order": primary.fallback_order[:-1]})
    try:
        verify_policy_projection(shortened, context.fallback_candidates)
    except SourcePolicyError as error:
        return error.code == "FALLBACK_ORDER_MISMATCH"
    except StopIteration:
        return False
    return False


def oracle_blocker_checks(fixture: SourceLifecycleFixture, inputs: SourceTrustInputs, context: TrustedCompilerContext) -> dict[str, bool]:
    shadow = _state(fixture, context, 1).policy
    return {
        "independent_context_joint_substitution": _joint_substitution_rejected(fixture, inputs),
        "conflicting_duplicate_payload": _conflicting_duplicate_rejected(fixture, context),
        "shadow_self_fallback_excluded": fixture.manifest.source_bundle_id not in shadow.fallback_order,
        "terminal_code_from_final_state": _terminal_matches_primary(fixture, context),
        "primary_voluntary_retirement": _primary_retirement_supported(fixture, context),
        "expired_source_retirement": _expired_retirement_supported(fixture, context),
        "hash_only_license_blocks_traffic": _hash_only_license_rejected(fixture, context),
        "fallback_prefix_shape_typed": _fallback_prefix_typed(fixture, context),
    }
