from typing import Literal, Self

from pydantic import model_validator

from src.v4.models import canonical_hash
from .models import BoundaryModel, ContractInvariantError, JsonBoundary
from .offline_models import ContentHash


class PolicyVersionEntry(BoundaryModel):
    policy_version: str
    policy_hash: ContentHash


class PolicyVersionRegistryBody(BoundaryModel):
    schema_version: Literal["v6.consensus_lifecycle.policy-registry.1"]
    persistence_scope: Literal["trading-oracle-v6-consensus-policy"]
    revision: int
    previous_registry_hash: ContentHash | None
    entries: tuple[PolicyVersionEntry, ...]


class PolicyVersionRegistry(PolicyVersionRegistryBody):
    registry_hash: ContentHash

    @model_validator(mode="after")
    def hash_bound(self) -> Self:
        body = PolicyVersionRegistryBody.model_validate(self.model_dump(mode="json", exclude={"registry_hash"}))
        versions = tuple(item.policy_version for item in self.entries)
        expected = canonical_hash(JsonBoundary.model_validate(body.model_dump(mode="json")).root)
        chain_shape = (self.revision == 1 and self.previous_registry_hash is None) or (self.revision > 1 and self.previous_registry_hash is not None)
        if not chain_shape or not self.entries or len(set(versions)) != len(versions) or self.registry_hash != expected:
            raise ContractInvariantError("policy version registry integrity mismatch")
        return self


def extend_policy_registry(registry: PolicyVersionRegistry, entry: PolicyVersionEntry) -> PolicyVersionRegistry:
    entries = {item.policy_version: item.policy_hash for item in registry.entries}
    if entry.policy_version in entries:
        raise ContractInvariantError("policy version registry collision")
    entries[entry.policy_version] = entry.policy_hash
    ordered = tuple(PolicyVersionEntry(policy_version=version, policy_hash=entries[version]) for version in sorted(entries))
    body = PolicyVersionRegistryBody(schema_version=registry.schema_version, persistence_scope=registry.persistence_scope, revision=registry.revision + 1, previous_registry_hash=registry.registry_hash, entries=ordered)
    return PolicyVersionRegistry.model_validate({**body.model_dump(mode="json"), "registry_hash": canonical_hash(JsonBoundary.model_validate(body.model_dump(mode="json")).root)})
