from dataclasses import dataclass, field
from typing import Annotated, Literal

from pydantic import Field

from src.v4.models import canonical_hash
from src.v6.models import BoundaryModel, JsonBoundary

from .models import HashText
from .source_models import ContractMetadata, IncidentCode, OwnerApproval, SourcePolicyError
from .source_policy import FallbackCandidate, SourcePolicySnapshot
from .value_input import ValueFixture, ValueTrustDocument
from .value_trust import ValueTrustContext, require_value_context


class PolicyRegistryBody(BoundaryModel):
    schema_version: Literal["v7.source-policy.registry.1"]
    namespace: Literal["trading-oracle-v7-source-policy"]
    revision: Annotated[int, Field(strict=True, ge=0)]
    previous_registry_hash: HashText
    policies: tuple[SourcePolicySnapshot, ...]


class PolicyRegistry(PolicyRegistryBody):
    registry_hash: HashText


class IncidentAuthorization(BoundaryModel):
    incident_code: IncidentCode
    evidence_hash: HashText
    source_bundle_id: str


class SourceTrustDocument(BoundaryModel):
    schema_version: Literal["v7.promotion_retirement.trust.1"]
    contract_id: Literal["promotion_retirement_prd04"]
    expected_value_trust_hash: HashText
    expected_source_bundle_hash: HashText
    expected_initial_policy_hash: HashText
    expected_registry_hash: HashText
    contract: ContractMetadata
    promotion_approval: OwnerApproval
    fallback_candidates: tuple[FallbackCandidate, ...]
    incident_authorizations: tuple[IncidentAuthorization, ...]


@dataclass(frozen=True, slots=True)
class SourceTrustInputs:
    source: SourceTrustDocument
    value_fixture: ValueFixture
    value_trust: ValueTrustDocument


class _TrustIssuer:
    pass


_ISSUER = _TrustIssuer()


@dataclass(frozen=True, slots=True)
class TrustedCompilerContext:
    trusted_registry: PolicyRegistry
    value_context: ValueTrustContext
    contract: ContractMetadata
    promotion_approval: OwnerApproval
    fallback_candidates: tuple[FallbackCandidate, ...]
    incident_authorizations: tuple[IncidentAuthorization, ...]
    _issuer: _TrustIssuer = field(repr=False)

    def issued_by(self, issuer: _TrustIssuer) -> bool:
        return self._issuer is issuer


def _hash(body: PolicyRegistryBody) -> str:
    value = JsonBoundary.model_validate(body.model_dump(mode="json")).root
    return str(canonical_hash(value))


def bind_registry(body: PolicyRegistryBody) -> PolicyRegistry:
    return PolicyRegistry.model_validate({**body.model_dump(mode="json"), "registry_hash": _hash(body)})


def genesis_registry(policy: SourcePolicySnapshot) -> PolicyRegistry:
    body = PolicyRegistryBody(schema_version="v7.source-policy.registry.1", namespace="trading-oracle-v7-source-policy", revision=0, previous_registry_hash="sha256:" + "0" * 64, policies=(policy,))
    return bind_registry(body)


def verify_context(context: TrustedCompilerContext) -> None:
    if not context.issued_by(_ISSUER):
        raise SourcePolicyError("TRUSTED_SOURCE_CONTEXT_REQUIRED", "context was not issued by the source trust boundary")
    registry = context.trusted_registry
    body = PolicyRegistryBody.model_validate(registry.model_dump(mode="json", exclude={"registry_hash"}))
    if registry.registry_hash != _hash(body):
        raise SourcePolicyError("STALE_TRUSTED_REGISTRY", "trusted registry head differs")
    try:
        _ = require_value_context(context.value_context)
    except ValueError as error:
        raise SourcePolicyError("TRUSTED_SOURCE_CONTEXT_REQUIRED", str(error)) from error


def issue_compiler_context(registry: PolicyRegistry, value_context: ValueTrustContext, trust: SourceTrustDocument) -> TrustedCompilerContext:
    return TrustedCompilerContext(registry, value_context, trust.contract, trust.promotion_approval, trust.fallback_candidates, trust.incident_authorizations, _ISSUER)


def advance_registry(registry: PolicyRegistry, policy: SourcePolicySnapshot) -> PolicyRegistry:
    if registry.policies[-1].source_bundle_id != policy.source_bundle_id:
        raise SourcePolicyError("STALE_TRUSTED_REGISTRY", "registry source identity differs")
    body = PolicyRegistryBody(schema_version="v7.source-policy.registry.1", namespace="trading-oracle-v7-source-policy", revision=registry.revision + 1, previous_registry_hash=registry.registry_hash, policies=(*registry.policies, policy))
    return bind_registry(body)
