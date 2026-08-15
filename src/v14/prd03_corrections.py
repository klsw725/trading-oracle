from __future__ import annotations

from typing import Annotated

from pydantic import Field
from src.v12.models import Market

from .contract import StrictModel, V14ContractError
from .hypothesis_models import (
    CorrectionArtifact,
    CorrectionScope,
    FrozenHypothesisRegistry,
    PValueInput,
)
from .metric_models import MetricsArtifact
from .multiple_testing import bh_fdr, holm_step_down
from .series_models import ResearchSegment
from .verdict_models import ExploratoryInput


class ScopedCorrections(StrictModel):
    holm: Annotated[tuple[CorrectionArtifact, ...], Field(strict=False)]
    bh_fdr: Annotated[tuple[CorrectionArtifact, ...], Field(strict=False)]


def _scope(
    registry: FrozenHypothesisRegistry,
    metrics: tuple[MetricsArtifact, ...],
) -> CorrectionScope:
    first = metrics[0]
    return CorrectionScope(plan_manifest_hash=first.plan_manifest_hash,
        registry_hash=registry.registry_hash, market=first.market,
        segment=first.segment,
        source_metrics_hashes=tuple(item.metrics_hash for item in metrics),
        source_bootstrap_hashes=tuple(
            item.baseline.bootstrap.bootstrap_hash for item in metrics))


def _metrics_for(
    metrics: tuple[MetricsArtifact, ...],
    market: Market,
    segment: ResearchSegment,
) -> tuple[MetricsArtifact, ...]:
    scoped = tuple(item for item in metrics
        if item.market is market and item.segment is segment)
    if len(scoped) != 15 or len({item.hypothesis_id for item in scoped}) != 15:
        raise V14ContractError("V14_METRIC_SCOPE", f"{market.value}:{segment.value}")
    return scoped


def build_scoped_corrections(
    registry: FrozenHypothesisRegistry,
    metrics: tuple[MetricsArtifact, ...],
    exploratory: tuple[ExploratoryInput, ...],
) -> ScopedCorrections:
    holm_artifacts: list[CorrectionArtifact] = []
    bh_artifacts: list[CorrectionArtifact] = []
    holm_ids = {item.hypothesis_id for item in registry.holm_family}
    for market in Market:
        for segment in ResearchSegment:
            scoped = _metrics_for(metrics, market, segment)
            holm_metrics = tuple(item for item in scoped
                if item.hypothesis_id in holm_ids)
            holm_inputs = tuple(PValueInput(hypothesis_id=item.hypothesis_id,
                p_value=item.baseline.bootstrap.one_sided_p_value, tested=True)
                for item in holm_metrics)
            holm_artifacts.append(holm_step_down(registry, holm_inputs,
                _scope(registry, holm_metrics)))
            bh_inputs = tuple(PValueInput(hypothesis_id=item.hypothesis_id,
                p_value=item.p_value, tested=True) for item in exploratory)
            bh_artifacts.append(bh_fdr(registry, bh_inputs,
                _scope(registry, scoped)))
    return ScopedCorrections(holm=tuple(holm_artifacts),
        bh_fdr=tuple(bh_artifacts))


def build_segment_corrections(
    registry: FrozenHypothesisRegistry,
    metrics: tuple[MetricsArtifact, ...],
    exploratory: tuple[ExploratoryInput, ...],
    segment: ResearchSegment,
) -> ScopedCorrections:
    holm_artifacts: list[CorrectionArtifact] = []
    bh_artifacts: list[CorrectionArtifact] = []
    holm_ids = {item.hypothesis_id for item in registry.holm_family}
    for market in Market:
        scoped = _metrics_for(metrics, market, segment)
        holm_metrics = tuple(item for item in scoped
            if item.hypothesis_id in holm_ids)
        holm_inputs = tuple(PValueInput(hypothesis_id=item.hypothesis_id,
            p_value=item.baseline.bootstrap.one_sided_p_value, tested=True)
            for item in holm_metrics)
        holm_artifacts.append(holm_step_down(registry, holm_inputs,
            _scope(registry, holm_metrics)))
        bh_inputs = tuple(PValueInput(hypothesis_id=item.hypothesis_id,
            p_value=item.p_value, tested=True) for item in exploratory)
        bh_artifacts.append(bh_fdr(registry, bh_inputs,
            _scope(registry, scoped)))
    return ScopedCorrections(holm=tuple(holm_artifacts),
        bh_fdr=tuple(bh_artifacts))


def correction_for(
    corrections: tuple[CorrectionArtifact, ...], metrics: MetricsArtifact
) -> CorrectionArtifact:
    matches = tuple(item for item in corrections
        if item.market is metrics.market and item.segment is metrics.segment)
    if len(matches) != 1:
        raise V14ContractError("V14_CORRECTION_SCOPE", metrics.metrics_hash)
    return matches[0]
