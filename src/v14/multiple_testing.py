from __future__ import annotations

from decimal import Decimal
from typing import Final

from src.v11.canonical import canonical_hash, model_json

from .contract import V14ContractError
from .hypothesis_models import (
    CorrectionArtifact,
    CorrectionArtifactBody,
    CorrectionResult,
    CorrectionScope,
    FrozenHypothesisRegistry,
    PValueInput,
)


ALPHA: Final = Decimal("0.05")
HOLM_FAMILY_SIZE: Final = 14


def one_sided_alpha(p_value: Decimal) -> bool:
    return p_value <= ALPHA


def holm_step_down(
    registry: FrozenHypothesisRegistry,
    inputs: tuple[PValueInput, ...],
    scope: CorrectionScope,
) -> CorrectionArtifact:
    expected = tuple(item.hypothesis_id for item in registry.holm_family)
    observed = tuple(item.hypothesis_id for item in inputs)
    if len(inputs) != HOLM_FAMILY_SIZE or set(observed) != set(expected):
        raise V14ContractError("V14_HOLM_FAMILY", str(sorted(set(expected) ^ set(observed))))
    ordered = tuple(sorted(inputs, key=lambda item: (item.p_value,
        item.hypothesis_id)))
    active = True
    results: list[CorrectionResult] = []
    for rank, item in enumerate(ordered, start=1):
        threshold = ALPHA / Decimal(HOLM_FAMILY_SIZE - rank + 1)
        passed = active and item.tested and item.p_value <= threshold
        active = passed
        results.append(CorrectionResult(hypothesis_id=item.hypothesis_id,
            raw_p_value=item.p_value, rank=rank, threshold=threshold,
            correction_passed=passed, tested=item.tested, confirmatory=True))
    body = CorrectionArtifactBody(schema_version="v14.correction.1",
        method="holm", alpha=ALPHA, family_size=HOLM_FAMILY_SIZE,
        plan_manifest_hash=scope.plan_manifest_hash,
        registry_hash=scope.registry_hash, market=scope.market,
        segment=scope.segment, source_metrics_hashes=scope.source_metrics_hashes,
        source_bootstrap_hashes=scope.source_bootstrap_hashes,
        results=tuple(results))
    return CorrectionArtifact(schema_version=body.schema_version,
        method=body.method, alpha=body.alpha, family_size=body.family_size,
        plan_manifest_hash=body.plan_manifest_hash,
        registry_hash=body.registry_hash, market=body.market,
        segment=body.segment, source_metrics_hashes=body.source_metrics_hashes,
        source_bootstrap_hashes=body.source_bootstrap_hashes,
        results=body.results, correction_hash=canonical_hash(model_json(body)))


def bh_fdr(
    registry: FrozenHypothesisRegistry,
    inputs: tuple[PValueInput, ...],
    scope: CorrectionScope,
) -> CorrectionArtifact:
    expected = tuple(item.hypothesis_id for item in registry.exploratory)
    observed = tuple(item.hypothesis_id for item in inputs)
    if len(inputs) != len(expected) or set(observed) != set(expected):
        raise V14ContractError("V14_BH_FAMILY", str(sorted(set(expected) ^ set(observed))))
    ordered = tuple(sorted(inputs, key=lambda item: (item.p_value,
        item.hypothesis_id)))
    family_size = len(ordered)
    discovery_rank = max((rank for rank, item in enumerate(ordered, start=1)
        if item.tested and item.p_value <= ALPHA * rank / family_size), default=0)
    results = tuple(CorrectionResult(hypothesis_id=item.hypothesis_id,
        raw_p_value=item.p_value, rank=rank,
        threshold=ALPHA * rank / family_size,
        correction_passed=rank <= discovery_rank and item.tested,
        tested=item.tested, confirmatory=False)
        for rank, item in enumerate(ordered, start=1))
    body = CorrectionArtifactBody(schema_version="v14.correction.1",
        method="bh_fdr", alpha=ALPHA, family_size=family_size,
        plan_manifest_hash=scope.plan_manifest_hash,
        registry_hash=scope.registry_hash, market=scope.market,
        segment=scope.segment, source_metrics_hashes=scope.source_metrics_hashes,
        source_bootstrap_hashes=scope.source_bootstrap_hashes, results=results)
    return CorrectionArtifact(schema_version=body.schema_version,
        method=body.method, alpha=body.alpha, family_size=body.family_size,
        plan_manifest_hash=body.plan_manifest_hash,
        registry_hash=body.registry_hash, market=body.market,
        segment=body.segment, source_metrics_hashes=body.source_metrics_hashes,
        source_bootstrap_hashes=body.source_bootstrap_hashes,
        results=body.results, correction_hash=canonical_hash(model_json(body)))
