from __future__ import annotations

from decimal import Decimal
from typing import Annotated

from pydantic import Field
from src.v11.canonical import canonical_hash, model_json
from src.v12.models import Market

from .contract import StrictModel, V14ContractError
from .hypothesis_models import (
    ConstituentGate,
    FrozenHypothesisRegistry,
    RouterGateInput,
    RouterGateBody,
    RouterGateResult,
    RouterGateState,
)
from .observed_models import (
    ObservedRouterVerdictArtifact,
    ObservedRouterVerdictBody,
    ObservedStrategyVerdictArtifact,
)
from .router_gate import evaluate_router_gate
from .router_metric_models import RouterComparisonArtifact
from .router_verdicts import (
    build_router_raw_verdicts,
    holdout_router_verdict,
    validation_router_verdict,
)
from .series_models import ResearchSegment
from .verdict_models import HoldoutVerdict, ValidationVerdict


class RouterObservedArtifacts(StrictModel):
    gates: Annotated[tuple[RouterGateResult, ...], Field(strict=False)]
    verdicts: Annotated[
        tuple[ObservedRouterVerdictArtifact, ...], Field(strict=False)
    ]


def _strategy_verdict(
    verdicts: tuple[ObservedStrategyVerdictArtifact, ...],
    comparison: RouterComparisonArtifact,
    hypothesis_id: str,
) -> ObservedStrategyVerdictArtifact:
    matches = tuple(item for item in verdicts if item.market is comparison.market
        and item.segment is comparison.segment and item.hypothesis_id == hypothesis_id)
    if len(matches) != 1:
        raise V14ContractError("V14_ROUTER_PREREQUISITE", hypothesis_id)
    return matches[0]


def _build_one(
    registry: FrozenHypothesisRegistry,
    comparison: RouterComparisonArtifact,
    strategy_verdicts: tuple[ObservedStrategyVerdictArtifact, ...],
) -> tuple[RouterGateResult, ObservedRouterVerdictArtifact]:
    orb = _strategy_verdict(strategy_verdicts, comparison,
        registry.primary.hypothesis_id)
    constituents = tuple(_strategy_verdict(strategy_verdicts, comparison,
        item.hypothesis_id) for item in registry.holm_family)
    gates = tuple(ConstituentGate(strategy_id=item.hypothesis_id,
        passed=item.verdict in {ValidationVerdict.PASS, HoldoutVerdict.PASS},
        verdict_hash=item.verdict_hash)
        for item in constituents)
    paired = comparison.paired_metrics
    raw = build_router_raw_verdicts(comparison)
    raw_passed = raw.mixed.verdict in {ValidationVerdict.PASS, HoldoutVerdict.PASS} \
        and raw.paired.verdict in {ValidationVerdict.PASS, HoldoutVerdict.PASS}
    gate = evaluate_router_gate(registry, RouterGateInput(
        plan_manifest_hash=comparison.plan_manifest_hash,
        registry_hash=registry.registry_hash, orb_passed=orb.correction_passed,
        orb_verdict_hash=orb.verdict_hash,
        frozen_enabled_strategy_ids=tuple(item.strategy_id for item in gates),
        enabled_constituents=gates,
        router_metric_passed=raw_passed,
        paired_p_value=paired.baseline.bootstrap.one_sided_p_value,
        mixed_metrics_hash=comparison.mixed_metrics.metrics_hash,
        deterministic_metrics_hash=comparison.deterministic_metrics.metrics_hash,
        paired_metrics_hash=paired.metrics_hash))
    verdict = validation_router_verdict(raw, gate.confirmatory_passed) \
        if comparison.segment is ResearchSegment.VALIDATION \
        else holdout_router_verdict(raw, gate.confirmatory_passed)
    body = ObservedRouterVerdictBody(schema_version="v14.observed_router_verdict.1",
        plan_manifest_hash=comparison.plan_manifest_hash,
        registry_hash=registry.registry_hash, market=comparison.market,
        segment=comparison.segment, selected_policy_id=comparison.selected_policy_id,
        comparison_hash=comparison.comparison_hash,
        mixed_metrics_hash=comparison.mixed_metrics.metrics_hash,
        deterministic_metrics_hash=comparison.deterministic_metrics.metrics_hash,
        paired_metrics_hash=paired.metrics_hash,
        mixed_raw_verdict_hash=raw.mixed.verdict_hash,
        paired_raw_verdict_hash=raw.paired.verdict_hash,
        orb_verdict_hash=orb.verdict_hash,
        constituent_verdict_hashes=tuple(item.verdict_hash for item in constituents),
        gate_hash=gate.gate_hash, verdict=verdict)
    artifact = ObservedRouterVerdictArtifact(schema_version=body.schema_version,
        plan_manifest_hash=body.plan_manifest_hash,
        registry_hash=body.registry_hash, market=body.market,
        segment=body.segment, selected_policy_id=body.selected_policy_id,
        comparison_hash=body.comparison_hash,
        mixed_metrics_hash=body.mixed_metrics_hash,
        deterministic_metrics_hash=body.deterministic_metrics_hash,
        paired_metrics_hash=body.paired_metrics_hash,
        mixed_raw_verdict_hash=body.mixed_raw_verdict_hash,
        paired_raw_verdict_hash=body.paired_raw_verdict_hash,
        orb_verdict_hash=body.orb_verdict_hash,
        constituent_verdict_hashes=body.constituent_verdict_hashes,
        gate_hash=body.gate_hash, verdict=body.verdict,
        verdict_hash=canonical_hash(model_json(body)))
    return gate, artifact


def _not_opened(
    registry: FrozenHypothesisRegistry,
    comparison: RouterComparisonArtifact,
    validation: ObservedRouterVerdictArtifact,
) -> tuple[RouterGateResult, ObservedRouterVerdictArtifact]:
    source = f"not-opened:{comparison.comparison_hash}"
    gate_body = RouterGateBody(state=RouterGateState.NOT_OPENED,
        confirmatory_passed=False, enabled_strategy_ids=(),
        paired_p_value=Decimal(0),
        plan_manifest_hash=comparison.plan_manifest_hash,
        registry_hash=registry.registry_hash,
        orb_verdict_hash=validation.verdict_hash,
        constituent_verdict_hashes=(validation.verdict_hash,),
        mixed_metrics_hash=source, deterministic_metrics_hash=source,
        paired_metrics_hash=source)
    gate = RouterGateResult(state=gate_body.state,
        confirmatory_passed=gate_body.confirmatory_passed,
        enabled_strategy_ids=gate_body.enabled_strategy_ids,
        paired_p_value=gate_body.paired_p_value,
        plan_manifest_hash=gate_body.plan_manifest_hash,
        registry_hash=gate_body.registry_hash,
        orb_verdict_hash=gate_body.orb_verdict_hash,
        constituent_verdict_hashes=gate_body.constituent_verdict_hashes,
        mixed_metrics_hash=gate_body.mixed_metrics_hash,
        deterministic_metrics_hash=gate_body.deterministic_metrics_hash,
        paired_metrics_hash=gate_body.paired_metrics_hash,
        gate_hash=canonical_hash(model_json(gate_body)))
    body = ObservedRouterVerdictBody(schema_version="v14.observed_router_verdict.1",
        plan_manifest_hash=comparison.plan_manifest_hash,
        registry_hash=registry.registry_hash, market=comparison.market,
        segment=comparison.segment, selected_policy_id=comparison.selected_policy_id,
        comparison_hash=comparison.comparison_hash,
        mixed_metrics_hash=source, deterministic_metrics_hash=source,
        paired_metrics_hash=source, mixed_raw_verdict_hash=None,
        paired_raw_verdict_hash=None, orb_verdict_hash=validation.verdict_hash,
        constituent_verdict_hashes=(validation.verdict_hash,),
        gate_hash=gate.gate_hash, verdict="HOLDOUT_NOT_OPENED")
    artifact = ObservedRouterVerdictArtifact(schema_version=body.schema_version,
        plan_manifest_hash=body.plan_manifest_hash,
        registry_hash=body.registry_hash, market=body.market,
        segment=body.segment, selected_policy_id=body.selected_policy_id,
        comparison_hash=body.comparison_hash,
        mixed_metrics_hash=body.mixed_metrics_hash,
        deterministic_metrics_hash=body.deterministic_metrics_hash,
        paired_metrics_hash=body.paired_metrics_hash,
        mixed_raw_verdict_hash=body.mixed_raw_verdict_hash,
        paired_raw_verdict_hash=body.paired_raw_verdict_hash,
        orb_verdict_hash=body.orb_verdict_hash,
        constituent_verdict_hashes=body.constituent_verdict_hashes,
        gate_hash=body.gate_hash, verdict=body.verdict,
        verdict_hash=canonical_hash(model_json(body)))
    return gate, artifact


def build_router_observed(
    registry: FrozenHypothesisRegistry,
    comparisons: tuple[RouterComparisonArtifact, ...],
    strategy_verdicts: tuple[ObservedStrategyVerdictArtifact, ...],
) -> RouterObservedArtifacts:
    built: list[tuple[RouterGateResult, ObservedRouterVerdictArtifact]] = []
    for market in Market:
        validation_comparison = next(item for item in comparisons
            if item.market is market and item.segment is ResearchSegment.VALIDATION)
        holdout_comparison = next(item for item in comparisons
            if item.market is market and item.segment is ResearchSegment.HOLDOUT)
        validation = _build_one(registry, validation_comparison, strategy_verdicts)
        built.append(validation)
        if validation[1].verdict is ValidationVerdict.PASS:
            built.append(_build_one(registry, holdout_comparison, strategy_verdicts))
        else:
            built.append(_not_opened(registry, holdout_comparison, validation[1]))
    return RouterObservedArtifacts(gates=tuple(item[0] for item in built),
        verdicts=tuple(item[1] for item in built))


def build_router_segment(
    registry: FrozenHypothesisRegistry,
    comparisons: tuple[RouterComparisonArtifact, ...],
    strategy_verdicts: tuple[ObservedStrategyVerdictArtifact, ...],
    segment: ResearchSegment,
) -> RouterObservedArtifacts:
    built = tuple(_build_one(registry, next(item for item in comparisons
        if item.market is market and item.segment is segment), strategy_verdicts)
        for market in Market)
    return RouterObservedArtifacts(gates=tuple(item[0] for item in built),
        verdicts=tuple(item[1] for item in built))
