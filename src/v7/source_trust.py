from __future__ import annotations

from typing import Protocol

from src.v4.models import canonical_hash
from src.v6.models import JsonBoundary

from .source_bundle import SourceBundleManifest, verify_source_bundle
from .source_context import SourceTrustInputs, TrustedCompilerContext, genesis_registry, issue_compiler_context
from .source_models import SourcePolicyError
from .source_policy import SourcePolicySnapshot
from .value_artifact import compile_value_artifact
from .value_trust import trust_value_fixture


class SourceTrustSubject(Protocol):
    manifest: SourceBundleManifest
    initial_policy: SourcePolicySnapshot


def _hash(value: JsonBoundary) -> str:
    return str(canonical_hash(value.root))


def issue_source_context(fixture: SourceTrustSubject, inputs: SourceTrustInputs) -> TrustedCompilerContext:
    trust = inputs.source
    value_trust_value = JsonBoundary.model_validate(inputs.value_trust.model_dump(mode="json"))
    if _hash(value_trust_value) != trust.expected_value_trust_hash:
        raise SourcePolicyError("SOURCE_TRUST_MISMATCH", "PRD03 trust document hash")
    try:
        value_context = trust_value_fixture(inputs.value_fixture, inputs.value_trust)
        value_artifact = compile_value_artifact(inputs.value_fixture, value_context)
    except ValueError as error:
        raise SourcePolicyError("TRUSTED_SOURCE_CONTEXT_REQUIRED", str(error)) from error
    if fixture.manifest.value != value_artifact:
        raise SourcePolicyError("PRD03_LINEAGE_INVALID", "manifest value differs from independently trusted PRD03 artifact")
    verify_source_bundle(fixture.manifest, value_context)
    if fixture.manifest.source_bundle_hash != trust.expected_source_bundle_hash:
        raise SourcePolicyError("SOURCE_TRUST_MISMATCH", "source bundle hash")
    if fixture.manifest.contract != trust.contract:
        raise SourcePolicyError("SOURCE_CONTEXT_MISMATCH", "contract")
    if fixture.initial_policy.policy_hash != trust.expected_initial_policy_hash:
        raise SourcePolicyError("SOURCE_TRUST_MISMATCH", "initial policy hash")
    if (fixture.initial_policy.source_bundle_hash, fixture.initial_policy.contract_ref_hash) != (fixture.manifest.source_bundle_hash, fixture.manifest.contract.contract_ref_hash):
        raise SourcePolicyError("SOURCE_CONTEXT_MISMATCH", "initial policy lineage")
    registry = genesis_registry(fixture.initial_policy)
    if registry.registry_hash != trust.expected_registry_hash:
        raise SourcePolicyError("SOURCE_TRUST_MISMATCH", "registry hash")
    return issue_compiler_context(registry, value_context, trust)
