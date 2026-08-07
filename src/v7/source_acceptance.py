import ast
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from src.v4.models import JsonValue, canonical_hash
from src.v6.models import BoundaryModel, JsonBoundary

from .source_artifact import SourcePolicyArtifact, SourcePolicyArtifactBody, compile_source_artifact, ensure_source_paths, verify_source_artifact
from .source_attacks import rejected_source_code, remove_source, replace_source
from .source_checkpoint import TransitionCheckpoint, verify_checkpoint
from .source_compiler import CompilationState, compile_operation
from .source_context import SourceTrustInputs, TrustedCompilerContext, issue_compiler_context
from .source_history import AuditHistory, AuditHistoryBody, empty_history
from .source_events import event_hash
from .source_ledger import OperationLedger, OperationLedgerBody
from .source_bundle import SourceBundleBody, SourceBundleManifest, bundle_hash
from .source_evaluator import evaluate_verified_artifacts
from .source_fixture import SourceLifecycleFixture, parse_source_fixture_bytes
from .source_models import IncidentCode, LifecycleState, PromotionObservation, RetirementReason, SourcePolicyCode, SourcePolicyError
from .source_operations import IncidentOperation, PromotionOperation, RetirementOperation, SourceOperation
from .source_oracle_acceptance import oracle_blocker_checks
from .source_policy import FallbackCandidate, SourcePolicyBody, bind_policy, ordered_fallback, verify_policy_projection
from .source_trust import issue_source_context
from .value_trust import trust_value_fixture


def _json(model: BoundaryModel) -> JsonValue:
    return JsonBoundary.model_validate(model.model_dump(mode="json")).root


def _compile_json(fixture: SourceLifecycleFixture, context: TrustedCompilerContext) -> JsonValue:
    return _json(compile_source_artifact(fixture, context))


def _artifact(fixture: SourceLifecycleFixture, context: TrustedCompilerContext) -> SourcePolicyArtifact:
    return compile_source_artifact(fixture, context)


def _bind_artifact(body: SourcePolicyArtifactBody) -> SourcePolicyArtifact:
    return SourcePolicyArtifact.model_validate({**body.model_dump(mode="json"), "artifact_hash": str(canonical_hash(_json(body)))})


def _reject(fixture: SourceLifecycleFixture, context: TrustedCompilerContext, code: SourcePolicyCode) -> bool:
    return rejected_source_code(lambda: _compile_json(fixture, context), code)


def _state(fixture: SourceLifecycleFixture, context: TrustedCompilerContext, count: int) -> CompilationState:
    state = CompilationState(fixture.initial_policy, context.trusted_registry, empty_history(), ())
    for operation in fixture.operations[:count]:
        state = compile_operation(operation, state, fixture.manifest, context, fixture.evaluated_at)
    return state


def _operation(fixture: SourceLifecycleFixture, index: int, operation: SourceOperation) -> SourceLifecycleFixture:
    operations = list(fixture.operations)
    operations[index] = operation
    return fixture.model_copy(update={"operations": tuple(operations[: index + 1])})


def _manifest(fixture: SourceLifecycleFixture, manifest: SourceBundleManifest) -> SourceLifecycleFixture:
    body = SourceBundleBody.model_validate(manifest.model_dump(mode="json", exclude={"source_bundle_hash"}))
    return fixture.model_copy(update={"manifest": manifest.model_copy(update={"source_bundle_hash": bundle_hash(body)})})


def _run(action: Callable[[], None]) -> JsonValue:
    action()
    return {}


def _issue(fixture: SourceLifecycleFixture, inputs: SourceTrustInputs) -> JsonValue:
    _ = issue_source_context(fixture, inputs)
    return {}


def _incident_fixture(fixture: SourceLifecycleFixture, code: IncidentCode) -> SourceLifecycleFixture:
    source = fixture.operations[5]
    assert isinstance(source, IncidentOperation)
    return _operation(fixture, 5, source.model_copy(update={"incident_code": code}))


def _expiry_fixture(fixture: SourceLifecycleFixture, context: TrustedCompilerContext) -> SourceLifecycleFixture:
    state = _state(fixture, context, 5)
    expiry = IncidentOperation(kind="incident", operation_id="contract_expiry", idempotency_key="source-policy-expiry", expected_prior_policy_hash=state.policy.policy_hash, expected_registry_hash=state.registry.registry_hash, incident_code=IncidentCode.CONTRACT_EXPIRED, evidence_hash="sha256:" + "8" * 64, traffic_share="0.00")
    state = compile_operation(expiry, state, fixture.manifest, context, fixture.evaluated_at)
    retirement = RetirementOperation(kind="retirement", operation_id="expired_retirement", idempotency_key="source-policy-expired-retire", expected_prior_policy_hash=state.policy.policy_hash, expected_registry_hash=state.registry.registry_hash, reason=RetirementReason.CONTRACT_EXPIRED)
    return fixture.model_copy(update={"operations": (*fixture.operations[:5], expiry, retirement)})


def _path_safety() -> bool:
    path = Path("source-policy.json")
    try:
        ensure_source_paths(path, path)
    except SourcePolicyError as error:
        return error.code == "OUTPUT_PATH_UNSAFE"
    return False


def _static_checks() -> tuple[bool, bool]:
    root = Path(__file__).resolve().parent
    forbidden = ("src.data", "src.consensus", "src.common", "main")
    imports_clean = True
    loc_clean = True
    for path in root.glob("source_*.py"):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        modules = tuple(node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module) + tuple(alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names)
        imports_clean &= not any(module.startswith(forbidden) for module in modules)
        loc_clean &= sum(1 for line in source.splitlines() if line.strip() and not line.lstrip().startswith("#")) <= 250
    return imports_clean, loc_clean


def verify_source_fixture(fixture: SourceLifecycleFixture, inputs: SourceTrustInputs) -> JsonValue:
    context = issue_source_context(fixture, inputs)
    artifact = compile_source_artifact(fixture, context)
    value = _json(artifact)
    first = fixture.operations[0]
    canary = fixture.operations[1]
    incident = fixture.operations[5]
    assert isinstance(first, PromotionOperation) and isinstance(canary, PromotionOperation) and isinstance(incident, IncidentOperation)
    primary = _state(fixture, context, 5).policy
    disabled = _state(fixture, context, 6).policy
    interrupted = TransitionCheckpoint(schema_version="v7.source-policy.checkpoint.1", operation_id="unsafe", expected_prior_policy_hash=primary.policy_hash, intended_policy_hash=disabled.policy_hash, safe_policy_hash=primary.policy_hash, interrupted=True, observed_traffic_share="0.25")
    bad_registry = context.trusted_registry.model_copy(update={"registry_hash": "sha256:" + "f" * 64})
    bad_context = replace(context, trusted_registry=bad_registry)
    malformed = (b'{"x":', b'{"x":NaN}', b'{"x":1,"x":2}', b'[]')
    malformed_ok = all(rejected_source_code(lambda payload=payload: _json(parse_source_fixture_bytes(payload)), "MALFORMED_SOURCE_POLICY") for payload in malformed)
    imports_clean, loc_clean = _static_checks()
    fallback = context.fallback_candidates
    tied = tuple(item for item in fallback if item.value_rank == 1)
    ineligible = FallbackCandidate(source_bundle_id="disabled_bundle", state=LifecycleState.DISABLED, capability_match=True, freshness_label="fresh", quality_label="high", value_rank=0, cost_latency_rank=0)
    provenance_tamper = fixture.manifest.model_copy(update={"provenance": (fixture.manifest.provenance[0].model_copy(update={"provenance_hash": "sha256:" + "f" * 64}), *fixture.manifest.provenance[1:])})
    quality_tamper = fixture.manifest.model_copy(update={"quality": (fixture.manifest.quality[0].model_copy(update={"artifact_hash": "sha256:" + "f" * 64}),)})
    value_tamper = fixture.manifest.model_copy(update={"value": fixture.manifest.value.model_copy(update={"artifact_hash": "sha256:" + "f" * 64})})
    expired_contract = fixture.manifest.contract.model_copy(update={"valid_until": fixture.evaluated_at})
    expired_manifest = fixture.manifest.model_copy(update={"contract": expired_contract})
    stale_manifest = fixture.manifest.model_copy(update={"quality": (fixture.manifest.quality[0].model_copy(update={"freshness_label": "stale"}),)})
    degraded_manifest = fixture.manifest.model_copy(update={"quality": (fixture.manifest.quality[0].model_copy(update={"quality_label": "degraded"}),)})
    blocked_manifest = fixture.manifest.model_copy(update={"quality": (fixture.manifest.quality[0].model_copy(update={"quality_label": "blocked"}),)})
    no_value_manifest = fixture.manifest.model_copy(update={"value": fixture.manifest.value.model_copy(update={"terminal_code": "REJECT_NO_INCREMENTAL_VALUE", "promotion_eligible": False})})
    missing_value_fixture = inputs.value_fixture.model_copy(update={"outcome_registry": None})
    missing_value_trust = inputs.value_trust.model_copy(update={"expected_outcome_root": None})
    missing_value_context = trust_value_fixture(missing_value_fixture, missing_value_trust)
    missing_adapter_context = issue_compiler_context(context.trusted_registry, missing_value_context, inputs.source)
    forged_capabilities = _manifest(fixture, fixture.manifest.model_copy(update={"capabilities": ("forged_capability",)})).model_copy(update={"operations": (first,)})
    interrupted_state = _state(fixture, context, 5)
    interrupted_operation = incident.model_copy(update={"interrupted": True})
    interrupted_result = compile_operation(interrupted_operation, interrupted_state, fixture.manifest, context, fixture.evaluated_at)
    truncated_events = artifact.history.events[:-1]
    history_body = AuditHistoryBody(schema_version="v7.source-policy.audit-history.1", events=truncated_events, head_event_hash=truncated_events[-1].audit_event_hash)
    truncated_history = AuditHistory.model_validate({**history_body.model_dump(mode="json"), "history_hash": event_hash(history_body)})
    ledger_body = OperationLedgerBody(schema_version="v7.source-policy.operation-ledger.1", entries=artifact.ledger.entries[:-1])
    truncated_ledger = OperationLedger.model_validate({**ledger_body.model_dump(mode="json"), "ledger_hash": event_hash(ledger_body)})
    cache = artifact.final_policy.cache.model_copy(update={"audit_only_generations": artifact.final_policy.cache.audit_only_generations[:-1]})
    policy_body = SourcePolicyBody.model_validate({**artifact.final_policy.model_dump(mode="json", exclude={"policy_hash"}), "cache": cache})
    forged_policy = bind_policy(policy_body)
    body = SourcePolicyArtifactBody.model_validate(artifact.model_dump(mode="json", exclude={"artifact_hash"}))
    checks: dict[str, bool] = {
        "canonical_gradual_promotion_retirement": artifact.terminal_code == "SOURCE_RETIRED" and tuple(event.payload.to_state for event in artifact.history.events[:5]) == (LifecycleState.SHADOW, LifecycleState.CANARY, LifecycleState.LIMITED, LifecycleState.LIMITED, LifecycleState.PRIMARY),
        "canary_exact_005": artifact.history.events[1].payload.traffic_share == "0.05",
        "minimum_100_each_step": all(operation.observation.attempts >= 100 for operation in fixture.operations[:5] if isinstance(operation, PromotionOperation)),
        "immediate_disable_all_open_states": all(_artifact(_incident_fixture(fixture, code), context).final_policy.state in (LifecycleState.DISABLED, LifecycleState.EXPIRED) for code in IncidentCode),
        "disable_zero_fallback_cache": disabled.traffic_share == "0.00" and not disabled.fallback_order and not disabled.cache.current and disabled.cache.purge_required,
        "contract_expiry_before_retirement": tuple(event.payload.to_state for event in _artifact(_expiry_fixture(fixture, context), context).history.events[-2:]) == (LifecycleState.EXPIRED, LifecycleState.RETIRED),
        "full_prd_bodies_consumed": bool(fixture.manifest.provenance and fixture.manifest.quality and fixture.manifest.value.observations),
        "artifact_roundtrip": verify_source_artifact(value, context) == artifact,
        "deterministic_rebuild": compile_source_artifact(fixture, context) == compile_source_artifact(fixture, context),
        "cache_generation_advances": tuple(event.payload.cache_generation for event in artifact.history.events) == tuple(range(1, 9)),
        "prior_generations_audit_only": artifact.final_policy.cache.audit_only_generations == tuple(range(8)),
        "fallback_tie_ascending": ordered_fallback(tied) == ("backup_bundle_a", "backup_bundle_z"),
        "illegal_jump": _reject(_operation(fixture, 0, first.model_copy(update={"to_state": LifecycleState.PRIMARY, "traffic_share": "1.00"})), context, "ILLEGAL_PROMOTION_JUMP"),
        "illegal_share": _reject(_operation(fixture, 1, canary.model_copy(update={"traffic_share": "0.06"})), context, "ILLEGAL_TRAFFIC_SHARE"),
        "insufficient_observations": _reject(_operation(fixture, 0, first.model_copy(update={"observation": PromotionObservation(attempts=99)})), context, "INSUFFICIENT_OBSERVATIONS"),
        "owner_missing": _reject(_operation(fixture, 0, first.model_copy(update={"owner_approval": None})), context, "OWNER_APPROVAL_MISSING"),
        "owner_reviewer_distinct": _reject(_operation(fixture, 0, first.model_copy(update={"owner_approval": first.owner_approval.model_copy(update={"reviewer": first.owner_approval.accountable_owner}) if first.owner_approval else None})), context, "OWNER_REVIEWER_CONFLICT"),
        "prior_policy_hash_cas": _reject(_operation(fixture, 0, first.model_copy(update={"expected_prior_policy_hash": "sha256:" + "f" * 64})), context, "POLICY_HASH_MISMATCH"),
        "source_hash_drift": _reject(_operation(fixture, 0, first.model_copy(update={"expected_source_bundle_hash": "sha256:" + "f" * 64})), context, "SOURCE_BUNDLE_HASH_MISMATCH"),
        "contract_hash_drift": _reject(_operation(fixture, 0, first.model_copy(update={"expected_contract_hash": "sha256:" + "f" * 64})), context, "CONTRACT_HASH_MISMATCH"),
        "prd01_body_tamper": _reject(_manifest(fixture, provenance_tamper).model_copy(update={"operations": (first,)}), context, "PRD01_LINEAGE_INVALID"),
        "prd02_body_tamper": _reject(_manifest(fixture, quality_tamper).model_copy(update={"operations": (first,)}), context, "PRD02_LINEAGE_INVALID"),
        "prd03_body_tamper": _reject(_manifest(fixture, value_tamper).model_copy(update={"operations": (first,)}), context, "PRD03_LINEAGE_INVALID"),
        "forged_capabilities_rejected": _reject(forged_capabilities, context, "SOURCE_CONTEXT_MISMATCH"),
        "forged_context_rejected": rejected_source_code(lambda: _issue(fixture, SourceTrustInputs(inputs.source, inputs.value_fixture, inputs.value_trust.model_copy(update={"expected_cohort_root": "sha256:" + "f" * 64}))), "SOURCE_TRUST_MISMATCH"),
        "forged_risk_rejected": _reject(_operation(fixture, 0, first.model_copy(update={"observation": first.observation.model_copy(update={"harm_events": first.observation.harm_events + 1})})), context, "OBSERVATION_CONTEXT_MISMATCH"),
        "forged_incident_rejected": _reject(_operation(fixture, 5, incident.model_copy(update={"evidence_hash": "sha256:" + "e" * 64})), context, "INCIDENT_UNAUTHORIZED"),
        "quality_stale_blocks": rejected_source_code(lambda: _run(lambda: evaluate_verified_artifacts(first, stale_manifest, context)), "QUALITY_STALE"),
        "quality_degraded_blocks": rejected_source_code(lambda: _run(lambda: evaluate_verified_artifacts(first, degraded_manifest, context)), "QUALITY_DEGRADED"),
        "quality_contradiction_blocks": rejected_source_code(lambda: _run(lambda: evaluate_verified_artifacts(first, blocked_manifest, context)), "QUALITY_CONTRADICTORY"),
        "value_no_pass_blocks": rejected_source_code(lambda: _run(lambda: evaluate_verified_artifacts(first, no_value_manifest, context)), "VALUE_NOT_PASS"),
        "missing_outcome_inconclusive": rejected_source_code(lambda: _run(lambda: evaluate_verified_artifacts(first, fixture.manifest, missing_adapter_context)), "MISSING_OUTCOME_ADAPTER"),
        "expired_contract_cannot_promote": _reject(_manifest(fixture, expired_manifest).model_copy(update={"operations": (first.model_copy(update={"expected_source_bundle_hash": bundle_hash(SourceBundleBody.model_validate(expired_manifest.model_dump(mode="json", exclude={"source_bundle_hash"})))}),)}), context, "CONTRACT_EXPIRED_SOURCE_ACTIVE"),
        "stale_registry": rejected_source_code(lambda: _compile_json(fixture, bad_context), "STALE_TRUSTED_REGISTRY"),
        "nonzero_disable": _reject(_operation(fixture, 5, incident.model_copy(update={"traffic_share": "0.05"})), context, "DISABLE_TRAFFIC_NOT_ZERO"),
        "unsafe_interruption": rejected_source_code(lambda: _run(lambda: verify_checkpoint(interrupted)), "INTERRUPTED_TRANSITION_UNSAFE"),
        "safe_interruption_restore_zero": artifact.checkpoints[5].safe_policy_hash == primary.policy_hash and disabled.traffic_share == "0.00",
        "interruption_atomic_projection": (interrupted_result.policy, interrupted_result.registry, interrupted_result.history, interrupted_result.ledger) == (interrupted_state.policy, interrupted_state.registry, interrupted_state.history, interrupted_state.ledger) and len(interrupted_result.checkpoints) == len(interrupted_state.checkpoints) + 1,
        "ineligible_fallback_excluded": ordered_fallback((*fallback, ineligible)) == ordered_fallback(fallback),
        "ineligible_fallback_rejected": rejected_source_code(lambda: _run(lambda: verify_policy_projection(primary.model_copy(update={"fallback_order": (*primary.fallback_order, ineligible.source_bundle_id)}), (*fallback, ineligible))), "FALLBACK_USES_INELIGIBLE_SOURCE"),
        "fallback_order_rejected": rejected_source_code(lambda: _run(lambda: verify_policy_projection(primary.model_copy(update={"fallback_order": tuple(reversed(primary.fallback_order))}), fallback)), "FALLBACK_ORDER_MISMATCH"),
        "fallback_tie_attack": rejected_source_code(lambda: _run(lambda: verify_policy_projection(primary.model_copy(update={"fallback_order": (primary.fallback_order[0], primary.fallback_order[2], primary.fallback_order[1])}), fallback)), "FALLBACK_TIE_BREAK_MISMATCH"),
        "closed_cache_rejected": rejected_source_code(lambda: _run(lambda: verify_policy_projection(disabled.model_copy(update={"cache": disabled.cache.model_copy(update={"current": True})}), fallback)), "STALE_CACHE_POLICY_MISMATCH"),
        "cache_hash_required": rejected_source_code(lambda: _run(lambda: verify_policy_projection(primary.model_copy(update={"cache": primary.cache.model_copy(update={"policy_hash": None})}), fallback)), "CACHE_POLICY_HASH_MISSING"),
        "audit_secret_rejected": rejected_source_code(lambda: verify_source_artifact(replace_source(value, ("history", "events", 0, "payload", "operation_id"), "access_token=secret"), context).model_dump(mode="json"), "AUDIT_SENSITIVE_DATA"),
        "audit_bearer_rejected": rejected_source_code(lambda: verify_source_artifact(replace_source(value, ("history", "events", 0, "payload", "operation_id"), "Bearer benign-review-token"), context).model_dump(mode="json"), "AUDIT_SENSITIVE_DATA"),
        "audit_hash_missing": rejected_source_code(lambda: verify_source_artifact(remove_source(value, ("history", "events", 0, "audit_event_hash")), context).model_dump(mode="json"), "AUDIT_HASH_MISSING"),
        "audit_hash_tamper": rejected_source_code(lambda: verify_source_artifact(replace_source(value, ("history", "events", 0, "audit_event_hash"), "sha256:" + "f" * 64), context).model_dump(mode="json"), "AUDIT_HASH_MISMATCH"),
        "history_splice": rejected_source_code(lambda: verify_source_artifact(replace_source(value, ("history", "events", 1, "previous_event_hash"), "sha256:" + "f" * 64), context).model_dump(mode="json"), "EVENT_CHAIN_SPLICE"),
        "history_hash_tamper": rejected_source_code(lambda: verify_source_artifact(replace_source(value, ("history", "history_hash"), "sha256:" + "f" * 64), context).model_dump(mode="json"), "HISTORY_HASH_MISMATCH"),
        "history_truncation_full_replay": rejected_source_code(lambda: _json(verify_source_artifact(_json(_bind_artifact(body.model_copy(update={"history": truncated_history}))), context)), "LIFECYCLE_REPLAY_MISMATCH"),
        "ledger_truncation_full_replay": rejected_source_code(lambda: _json(verify_source_artifact(_json(_bind_artifact(body.model_copy(update={"ledger": truncated_ledger}))), context)), "LIFECYCLE_REPLAY_MISMATCH"),
        "checkpoint_truncation_full_replay": rejected_source_code(lambda: _json(verify_source_artifact(_json(_bind_artifact(body.model_copy(update={"checkpoints": artifact.checkpoints[:-1]}))), context)), "LIFECYCLE_REPLAY_MISMATCH"),
        "cache_projection_full_replay": rejected_source_code(lambda: _json(verify_source_artifact(_json(_bind_artifact(body.model_copy(update={"final_policy": forged_policy}))), context)), "LIFECYCLE_REPLAY_MISMATCH"),
        "idempotent_replay": compile_operation(fixture.operations[0], _state(fixture, context, 1), fixture.manifest, context, fixture.evaluated_at) == _state(fixture, context, 1),
        "duplicate_operation_conflict": rejected_source_code(lambda: _json(compile_operation(first.model_copy(update={"expected_prior_policy_hash": "sha256:" + "f" * 64}), _state(fixture, context, 1), fixture.manifest, context, fixture.evaluated_at).policy), "DUPLICATE_OPERATION_CONFLICT"),
        "closed_state_reopen": rejected_source_code(lambda: _json(compile_operation(first.model_copy(update={"operation_id": "reopen", "idempotency_key": "reopen", "expected_prior_policy_hash": artifact.final_policy.policy_hash, "expected_registry_hash": _state(fixture, context, 8).registry.registry_hash}), _state(fixture, context, 8), fixture.manifest, context, fixture.evaluated_at).policy), "CLOSED_STATE_REOPEN"),
        "retention_deletion_rejected": _reject(_operation(fixture, 6, fixture.operations[6].model_copy(update={"delete_retained_history": True})), context, "RETENTION_DELETION_FORBIDDEN"),
        "production_isolation_attack": rejected_source_code(lambda: verify_source_artifact(replace_source(value, ("production_isolation",), "production_wired"), context).model_dump(mode="json"), "PRODUCTION_ISOLATION_VIOLATION"),
        "production_isolation": imports_clean and artifact.production_isolation == "offline_only_no_production_imports",
        "input_output_path_safety": _path_safety(),
        "malformed_json_rejected": malformed_ok,
        "modules_within_250_loc": loc_clean,
    }
    checks.update(oracle_blocker_checks(fixture, inputs, context))
    codes = sorted({"ILLEGAL_PROMOTION_JUMP", "ILLEGAL_TRAFFIC_SHARE", "INSUFFICIENT_OBSERVATIONS", "OWNER_APPROVAL_MISSING", "OWNER_REVIEWER_CONFLICT", "POLICY_HASH_MISMATCH", "SOURCE_BUNDLE_HASH_MISMATCH", "PRD01_LINEAGE_INVALID", "PRD02_LINEAGE_INVALID", "PRD03_LINEAGE_INVALID", "CONTRACT_HASH_MISMATCH", "QUALITY_STALE", "QUALITY_DEGRADED", "QUALITY_CONTRADICTORY", "VALUE_NOT_PASS", "MISSING_OUTCOME_ADAPTER", "CONTRACT_EXPIRED_SOURCE_ACTIVE", "STALE_TRUSTED_REGISTRY", "DISABLE_TRAFFIC_NOT_ZERO", "FALLBACK_USES_INELIGIBLE_SOURCE", "FALLBACK_ORDER_MISMATCH", "FALLBACK_TIE_BREAK_MISMATCH", "INTERRUPTED_TRANSITION_UNSAFE", "STALE_CACHE_POLICY_MISMATCH", "CACHE_POLICY_HASH_MISSING", "AUDIT_SENSITIVE_DATA", "AUDIT_HASH_MISSING", "AUDIT_HASH_MISMATCH", "EVENT_CHAIN_SPLICE", "HISTORY_HASH_MISMATCH", "DUPLICATE_OPERATION_CONFLICT", "CLOSED_STATE_REOPEN", "RETENTION_DELETION_FORBIDDEN", "PRODUCTION_ISOLATION_VIOLATION", "MALFORMED_SOURCE_POLICY", "OUTPUT_PATH_UNSAFE", "TRUSTED_SOURCE_CONTEXT_REQUIRED", "SOURCE_CONTEXT_MISMATCH", "INCIDENT_UNAUTHORIZED", "OBSERVATION_CONTEXT_MISMATCH", "LIFECYCLE_REPLAY_MISMATCH"})
    return JsonBoundary.model_validate({"state": "pass" if all(checks.values()) else "fail", "schema_version": fixture.schema_version, "pass_count": sum(checks.values()), "total": len(checks), "error_codes": codes, "checks": checks}).root
