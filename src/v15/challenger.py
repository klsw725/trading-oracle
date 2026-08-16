from __future__ import annotations

from .contract import V15Failure, V15FailureCode
from .states import LifecycleState
from .retirement import RetirementRegistry, require_active
from .winner import WinnerArtifact, WinnerVerdict


def promote_winner(
    artifact: WinnerArtifact, registry: RetirementRegistry, version: str
) -> LifecycleState:
    require_active(registry, artifact.market, version)
    if artifact.verdict is not WinnerVerdict.ROUTER:
        raise V15Failure(V15FailureCode.PROMOTION_BLOCKED, artifact.verdict.value)
    return LifecycleState.ROUTER_PRIMARY
