from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import AwareDatetime, ValidationError

from src.v4.models import canonical_hash
from src.v6.models import BoundaryModel, JsonBoundary

from .fixture import parse_json_bytes
from .models import ProvenanceContractError
from .quality_models import QualityFixture
from .quality_fixture_factory import canonical_quality_trust_document
from .source_bundle import SourceBundleManifest
from .source_bundle import SourceBundleBody, bundle_hash
from .source_compiler import CompilationState, compile_operation
from .source_context import IncidentAuthorization, SourceTrustDocument, SourceTrustInputs, genesis_registry
from .source_history import empty_history
from .source_models import ContractMetadata, IncidentCode, LifecycleState, OwnerApproval, PromotionObservation, RetirementReason, SourcePolicyError
from .source_operations import IncidentOperation, PromotionOperation, RetirementOperation, SourceOperation
from .source_policy import CacheProjection, FallbackCandidate, SourcePolicyBody, SourcePolicySnapshot, bind_policy
from .value_trust import trust_value_fixture


class SourceLifecycleFixture(BoundaryModel):
    schema_version: Literal["v7.promotion_retirement.prd04.1"]
    contract_id: Literal["promotion_retirement_prd04"]
    evaluated_at: AwareDatetime
    manifest: SourceBundleManifest
    initial_policy: SourcePolicySnapshot
    operations: tuple[SourceOperation, ...]


def parse_source_fixture_bytes(payload: bytes) -> SourceLifecycleFixture:
    try:
        value = parse_json_bytes(payload)
    except ProvenanceContractError as error:
        raise SourcePolicyError("MALFORMED_SOURCE_POLICY", error.detail) from error
    try:
        return SourceLifecycleFixture.model_validate(value)
    except ValidationError as error:
        raise SourcePolicyError("MALFORMED_SOURCE_POLICY", str(error)) from error


def load_source_fixture(path: Path) -> SourceLifecycleFixture:
    return parse_source_fixture_bytes(path.read_bytes())


def parse_source_trust_bytes(payload: bytes) -> SourceTrustDocument:
    try:
        value = parse_json_bytes(payload)
    except ProvenanceContractError as error:
        raise SourcePolicyError("MALFORMED_SOURCE_POLICY", error.detail) from error
    try:
        return SourceTrustDocument.model_validate(value)
    except ValidationError as error:
        raise SourcePolicyError("MALFORMED_SOURCE_POLICY", str(error)) from error


def load_source_trust(path: Path) -> SourceTrustDocument:
    return parse_source_trust_bytes(path.read_bytes())


def fixture_time() -> datetime:
    return datetime.fromisoformat("2026-08-06T12:00:00+09:00")


def build_canonical_source_fixture(quality_fixture: QualityFixture) -> tuple[SourceLifecycleFixture, SourceTrustDocument]:
    from .value_artifact import compile_value_artifact
    from .value_fixture import build_canonical_value_fixture
    from .source_trust import issue_source_context

    evaluated_at = fixture_time()
    value_fixture, value_trust = build_canonical_value_fixture(quality_fixture, canonical_quality_trust_document(quality_fixture))
    value_context = trust_value_fixture(value_fixture, value_trust)
    value = compile_value_artifact(value_fixture, value_context)
    quality = value.source_binding.quality_artifact
    provenance_hashes = tuple(dict.fromkeys(source.bundle.artifact.provenance_hash for source in quality.build_input.sources))
    provenance_bodies = tuple(next(source.bundle.artifact for source in quality.build_input.sources if source.bundle.artifact.provenance_hash == digest) for digest in provenance_hashes)
    source_id = value.source_binding.provenance_bundle.artifact.source_identity.source_id
    metadata = next(item for item in value_context.quality_context.registry.entries if item.source_id == source_id)
    contract = ContractMetadata(contract_ref_hash="sha256:" + "7" * 64, license_scope="internal_prompt_eligible_hash_only", valid_from=datetime.fromisoformat("2026-08-01T00:00:00+09:00"), valid_until=datetime.fromisoformat("2026-11-06T00:00:00+09:00"), expiry_review_at=datetime.fromisoformat("2026-10-06T00:00:00+09:00"))
    bundle_body = SourceBundleBody(schema_version="v7.source-policy.bundle.1", source_bundle_id=value.source_bundle_id, provenance=provenance_bodies, quality=(quality,), value=value, capabilities=metadata.capabilities, market=metadata.coverage.market, exchange=metadata.coverage.exchange, symbol_namespace=metadata.coverage.symbol_namespace, contract=contract)
    manifest = SourceBundleManifest.model_validate({**bundle_body.model_dump(mode="json"), "source_bundle_hash": bundle_hash(bundle_body)})
    cache = CacheProjection(generation=0, current=False, audit_only_generations=(), purge_required=False, policy_hash=None, source_bundle_hash=manifest.source_bundle_hash, quality_result_hash=quality.artifact_hash)
    initial = bind_policy(SourcePolicyBody(schema_version="v7.source-policy.snapshot.1", policy_version=0, source_bundle_id=manifest.source_bundle_id, source_bundle_hash=manifest.source_bundle_hash, contract_ref_hash=contract.contract_ref_hash, state=LifecycleState.CANDIDATE, traffic_share="0.00", cache=cache, fallback_order=(), production_isolation="offline_only_no_production_imports"))
    registry = genesis_registry(initial)
    candidates = (
        FallbackCandidate(source_bundle_id="backup_primary", state=LifecycleState.PRIMARY, capability_match=True, freshness_label="fresh", quality_label="high", value_rank=0, cost_latency_rank=0),
        FallbackCandidate(source_bundle_id="backup_bundle_z", state=LifecycleState.LIMITED, capability_match=True, freshness_label="fresh", quality_label="usable", value_rank=1, cost_latency_rank=1),
        FallbackCandidate(source_bundle_id="backup_bundle_a", state=LifecycleState.LIMITED, capability_match=True, freshness_label="fresh", quality_label="usable", value_rank=1, cost_latency_rank=1),
    )
    approval = OwnerApproval(accountable_owner="data_source_owner", reviewer="risk_reviewer", approved_at=evaluated_at, expiry_review_at=contract.expiry_review_at)
    authorizations = tuple(IncidentAuthorization(incident_code=code, evidence_hash="sha256:" + "9" * 64, source_bundle_id=manifest.source_bundle_id) for code in IncidentCode) + (IncidentAuthorization(incident_code=IncidentCode.CONTRACT_EXPIRED, evidence_hash="sha256:" + "8" * 64, source_bundle_id=manifest.source_bundle_id),)
    value_trust_json = JsonBoundary.model_validate(value_trust.model_dump(mode="json")).root
    source_trust = SourceTrustDocument(schema_version="v7.promotion_retirement.trust.1", contract_id="promotion_retirement_prd04", expected_value_trust_hash=str(canonical_hash(value_trust_json)), expected_source_bundle_hash=manifest.source_bundle_hash, expected_initial_policy_hash=initial.policy_hash, expected_registry_hash=registry.registry_hash, contract=contract, promotion_approval=approval, fallback_candidates=candidates, incident_authorizations=authorizations)
    provisional = SourceLifecycleFixture(schema_version="v7.promotion_retirement.prd04.1", contract_id="promotion_retirement_prd04", evaluated_at=evaluated_at, manifest=manifest, initial_policy=initial, operations=())
    context = issue_source_context(provisional, SourceTrustInputs(source_trust, value_fixture, value_trust))
    state = CompilationState(initial, registry, empty_history(), ())
    operations: list[SourceOperation] = []
    steps = ((LifecycleState.SHADOW, "0.00"), (LifecycleState.CANARY, "0.05"), (LifecycleState.LIMITED, "0.25"), (LifecycleState.LIMITED, "0.50"), (LifecycleState.PRIMARY, "1.00"))
    for index, (target, share) in enumerate(steps, start=1):
        metrics = value.metrics
        observation = PromotionObservation(attempts=metrics.eligible_pairs, harm_events=int(metrics.harm_rate * metrics.eligible_pairs), timeout_spikes=int(metrics.timeout_rate * metrics.eligible_pairs), stale_cache_events=0)
        operation = PromotionOperation(kind="promotion", operation_id=f"promote_{index}", idempotency_key=f"source-policy-promote-{index}", expected_prior_policy_hash=state.policy.policy_hash, expected_registry_hash=state.registry.registry_hash, expected_source_bundle_hash=manifest.source_bundle_hash, expected_contract_hash=contract.contract_ref_hash, to_state=target, traffic_share=share, owner_approval=approval, observation=observation)
        operations.append(operation)
        state = compile_operation(operation, state, manifest, context, evaluated_at)
    incident = IncidentOperation(kind="incident", operation_id="disable_prompt_injection", idempotency_key="source-policy-disable-1", expected_prior_policy_hash=state.policy.policy_hash, expected_registry_hash=state.registry.registry_hash, incident_code=IncidentCode.PROMPT_INJECTION, evidence_hash="sha256:" + "9" * 64, traffic_share="0.00")
    operations.append(incident)
    state = compile_operation(incident, state, manifest, context, evaluated_at)
    for index, reason in enumerate((RetirementReason.HARMFUL, RetirementReason.HARMFUL), start=1):
        retirement = RetirementOperation(kind="retirement", operation_id=f"retire_{index}", idempotency_key=f"source-policy-retire-{index}", expected_prior_policy_hash=state.policy.policy_hash, expected_registry_hash=state.registry.registry_hash, reason=reason)
        operations.append(retirement)
        state = compile_operation(retirement, state, manifest, context, evaluated_at)
    fixture = provisional.model_copy(update={"operations": tuple(operations)})
    return fixture, source_trust
