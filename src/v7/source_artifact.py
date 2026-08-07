from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from src.v4.models import ArtifactWriteStatus, JsonValue, canonical_hash, write_immutable_json
from src.v6.models import BoundaryModel, JsonBoundary

from .source_compiler import CompilationState, compile_operation, verify_trusted_context
from .source_context import TrustedCompilerContext
from .source_checkpoint import TransitionCheckpoint
from .source_history import AuditHistory, empty_history, verify_history
from .source_ledger import OperationLedger, verify_ledger
from .source_fixture import SourceLifecycleFixture
from .source_models import LifecycleState, SourcePolicyCode, SourcePolicyError
from .source_policy import SourcePolicyBody, SourcePolicySnapshot, policy_hash, verify_policy_projection
from .sensitive_data import contains_sensitive


class SourcePolicyArtifactBody(BoundaryModel):
    schema_version: Literal["v7.source-policy.artifact.1"]
    fixture: SourceLifecycleFixture
    final_policy: SourcePolicySnapshot
    history: AuditHistory
    ledger: OperationLedger
    checkpoints: tuple[TransitionCheckpoint, ...]
    terminal_code: SourcePolicyCode
    production_isolation: Literal["offline_only_no_production_imports"]


class SourcePolicyArtifact(SourcePolicyArtifactBody):
    artifact_hash: str


def _json(model: BoundaryModel) -> JsonValue:
    return JsonBoundary.model_validate(model.model_dump(mode="json")).root


def _terminal(state: LifecycleState, history: AuditHistory) -> SourcePolicyCode:
    if state is LifecycleState.DISABLED:
        return "SOURCE_DISABLED_IMMEDIATELY"
    if state is LifecycleState.EXPIRED or any(event.payload.decision_reason == "contract_expired" for event in history.events):
        return "CONTRACT_EXPIRED_SOURCE_RETIRED"
    if state in (LifecycleState.RETIRING, LifecycleState.RETIRED):
        return "SOURCE_RETIRED"
    return "PROMOTION_ACCEPTED_GRADUAL"


def compile_source_artifact(fixture: SourceLifecycleFixture, context: TrustedCompilerContext | None = None) -> SourcePolicyArtifact:
    if context is None:
        raise SourcePolicyError("TRUSTED_SOURCE_CONTEXT_REQUIRED", "lifecycle fixture requires a separately issued context")
    verify_trusted_context(context)
    registry = context.trusted_registry
    if registry.policies[-1] != fixture.initial_policy:
        raise SourcePolicyError("STALE_TRUSTED_REGISTRY", "initial policy differs from registry head")
    state = CompilationState(fixture.initial_policy, registry, empty_history(), ())
    for operation in fixture.operations:
        state = compile_operation(operation, state, fixture.manifest, context, fixture.evaluated_at)
    body = SourcePolicyArtifactBody(schema_version="v7.source-policy.artifact.1", fixture=fixture, final_policy=state.policy, history=state.history, ledger=state.ledger, checkpoints=state.checkpoints, terminal_code=_terminal(state.policy.state, state.history), production_isolation="offline_only_no_production_imports")
    return SourcePolicyArtifact.model_validate({**body.model_dump(mode="json"), "artifact_hash": str(canonical_hash(_json(body)))})


def verify_source_artifact(value: JsonValue, context: TrustedCompilerContext | None = None) -> SourcePolicyArtifact:
    if contains_sensitive(value):
        raise SourcePolicyError("AUDIT_SENSITIVE_DATA", "audit contains forbidden material")
    match value:  # noqa: MATCH_OK - JSON boundary inspection rejects malformed variants below
        case dict() as record:
            if record.get("production_isolation") != "offline_only_no_production_imports":
                raise SourcePolicyError("PRODUCTION_ISOLATION_VIOLATION", "artifact isolation boundary")
            history = record.get("history")
            if isinstance(history, dict):
                events = history.get("events")
                if isinstance(events, list) and any(isinstance(event, dict) and "audit_event_hash" not in event for event in events):
                    raise SourcePolicyError("AUDIT_HASH_MISSING", "audit_event_hash")
        case _:
            pass
    try:
        artifact = SourcePolicyArtifact.model_validate(value)
    except ValidationError as error:
        raise SourcePolicyError("MALFORMED_SOURCE_POLICY", str(error)) from error
    if context is None:
        raise SourcePolicyError("TRUSTED_SOURCE_CONTEXT_REQUIRED", "artifact requires a separately issued context")
    verify_history(artifact.history)
    verify_ledger(artifact.ledger)
    verify_policy_projection(artifact.final_policy, context.fallback_candidates)
    body = SourcePolicyArtifactBody.model_validate(artifact.model_dump(mode="json", exclude={"artifact_hash"}))
    policy_body = SourcePolicyBody.model_validate(artifact.final_policy.model_dump(mode="json", exclude={"policy_hash"}))
    if artifact.final_policy.policy_hash != policy_hash(policy_body) or artifact.final_policy.cache.policy_hash != artifact.final_policy.policy_hash:
        raise SourcePolicyError("POLICY_HASH_MISMATCH", "final policy")
    if artifact.artifact_hash != str(canonical_hash(_json(body))):
        raise SourcePolicyError("AUDIT_HASH_MISMATCH", "artifact hash")
    expected = compile_source_artifact(artifact.fixture, context)
    if expected != artifact:
        raise SourcePolicyError("LIFECYCLE_REPLAY_MISMATCH", "artifact differs from full deterministic replay")
    return artifact


def ensure_source_paths(input_path: Path, output_path: Path) -> None:
    if input_path.resolve() == output_path.resolve():
        raise SourcePolicyError("OUTPUT_PATH_UNSAFE", "output must not replace input")


def write_source_artifact(path: Path, artifact: SourcePolicyArtifact, context: TrustedCompilerContext | None = None) -> ArtifactWriteStatus:
    verified = verify_source_artifact(_json(artifact), context)
    return write_immutable_json(path, _json(verified))
