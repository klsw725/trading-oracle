from __future__ import annotations

from typing import Final

from src.v16.canonical import JsonValue, canonical_hash
from src.v16.models import RuntimeIdentity

from .errors import V17Error

SUPPORTED_POLICIES: Final = frozenset({"v16.policy.1"})


def identity_hash(identity: RuntimeIdentity) -> str:
    seed: JsonValue = {
        "identity_schema_version": identity.identity_schema_version,
        "config_hash": identity.config_hash,
        "policy_version": identity.policy_version,
        "calendar_versions": {
            market.value: version for market, version in identity.calendar_versions.items()
        },
        "input_manifest_hash": identity.input_manifest_hash,
        "python_version": identity.python_version,
        "lock_hash": identity.lock_hash,
        "account_selector": identity.account_selector,
        "arm_selector": identity.arm_selector,
        "namespaces": list(identity.namespaces),
    }
    return canonical_hash(seed)


def verify_runtime_identity(identity: RuntimeIdentity) -> None:
    if identity.policy_version not in SUPPORTED_POLICIES:
        raise V17Error("UNKNOWN_EVENT_POLICY", identity.policy_version)
    computed = identity_hash(identity)
    if identity.runtime_identity != computed:
        raise V17Error("RUNTIME_IDENTITY_HASH_MISMATCH", identity.runtime_identity)
