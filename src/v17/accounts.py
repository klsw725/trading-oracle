from __future__ import annotations

from src.v16.models import RuntimeIdentity

from .errors import V17Error
from .models import AccountNamespace


def verify_identity_membership(namespace: AccountNamespace, identity: RuntimeIdentity) -> None:
    if namespace.selector() not in identity.namespaces:
        raise V17Error("STALE_RUNTIME_IDENTITY", namespace.selector())
    if identity.account_selector != namespace.account_id or identity.arm_selector != namespace.arm_id:
        raise V17Error("STALE_RUNTIME_IDENTITY", namespace.selector())
