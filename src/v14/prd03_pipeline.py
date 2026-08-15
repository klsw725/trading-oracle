from __future__ import annotations

from functools import cache
from typing import Annotated

from pydantic import Field
from src.v11.canonical import canonical_hash, model_json
from src.v12.models import Market

from .contract import StrictModel, V14ContractError
from .fixture import load_fixture
from .hypotheses import build_hypothesis_registry
from .hypothesis_models import (
    ConstituentGate,
    CorrectionArtifact,
    CorrectionScope,
    FrozenHypothesisRegistry,
    PValueInput,
    RouterGateInput,
    RouterGateResult,
)
from .multiple_testing import bh_fdr, holm_step_down
from .manifest_models import ExperimentPlanManifest
from .observed_models import (
    ObservedRouterVerdictArtifact,
    ObservedStrategyVerdictArtifact,
)
from .observed_verdicts import build_strategy_verdict
from .pipeline import build_prd01
from .prd02_pipeline import Prd02Artifacts, build_prd02
from .prd03_corrections import (
    build_scoped_corrections,
    build_segment_corrections,
    correction_for,
)
from .prd03_fixture import load_prd03_fixture
from .prd03_router import build_router_observed, build_router_segment
from .router_gate import evaluate_router_gate
from .series_models import ResearchSegment
from .verdict_models import (
    HoldoutVerdictArtifact,
    MetricScenario,
    Prd03Fixture,
    RouterScenario,
    ValidationVerdictArtifact,
)
from .verdicts import (
    confirmatory_gate,
    evidence_from_scenario,
    holdout_verdict,
    validation_verdict,
)


type ObservedVerdictArtifact = (
    ObservedStrategyVerdictArtifact | ObservedRouterVerdictArtifact
)


class Prd03ArtifactsBody(StrictModel):
    registry: FrozenHypothesisRegistry
    holm: CorrectionArtifact
    exploratory: CorrectionArtifact
    holm_corrections: Annotated[tuple[CorrectionArtifact, ...], Field(strict=False)]
    bh_corrections: Annotated[tuple[CorrectionArtifact, ...], Field(strict=False)]
    validation_scenarios: Annotated[
        tuple[ValidationVerdictArtifact, ...], Field(strict=False)]
    holdout_scenarios: Annotated[
        tuple[HoldoutVerdictArtifact, ...], Field(strict=False)]
    observed_strategy_verdicts: Annotated[
        tuple[ObservedStrategyVerdictArtifact, ...], Field(strict=False)]
    observed_router_verdicts: Annotated[
        tuple[ObservedRouterVerdictArtifact, ...], Field(strict=False)]
    observed_verdicts: Annotated[tuple[ObservedVerdictArtifact, ...], Field(strict=False)]
    router_gates: Annotated[tuple[RouterGateResult, ...], Field(strict=False)]
    router_pass: RouterGateResult
    router_blocked: RouterGateResult


class Prd03Artifacts(Prd03ArtifactsBody):
    artifact_hash: str


class SegmentPrd03ArtifactsBody(StrictModel):
    registry: FrozenHypothesisRegistry
    segment: ResearchSegment
    holm_corrections: Annotated[tuple[CorrectionArtifact, ...], Field(strict=False)]
    bh_corrections: Annotated[tuple[CorrectionArtifact, ...], Field(strict=False)]
    observed_strategy_verdicts: Annotated[
        tuple[ObservedStrategyVerdictArtifact, ...], Field(strict=False)]
    observed_router_verdicts: Annotated[
        tuple[ObservedRouterVerdictArtifact, ...], Field(strict=False)]
    observed_verdicts: Annotated[tuple[ObservedVerdictArtifact, ...], Field(strict=False)]
    router_gates: Annotated[tuple[RouterGateResult, ...], Field(strict=False)]


class SegmentPrd03Artifacts(SegmentPrd03ArtifactsBody):
    artifact_hash: str


def build_prd03_segment_from(
    plan: ExperimentPlanManifest,
    prd02: Prd02Artifacts,
    fixture: Prd03Fixture,
    segment: ResearchSegment,
) -> SegmentPrd03Artifacts:
    if any(item.segment is not segment for item in prd02.metrics) \
            or any(item.segment is not segment for item in prd02.router_comparisons):
        raise V14ContractError("V14_SEGMENT_MISMATCH", segment.value)
    registry = build_hypothesis_registry(plan)
    scoped = build_segment_corrections(
        registry, prd02.metrics, fixture.exploratory_inputs, segment)
    strategy = tuple(build_strategy_verdict(registry, item,
        correction_for(scoped.holm, item)) for item in prd02.metrics)
    router = build_router_segment(
        registry, prd02.router_comparisons, strategy, segment)
    body = SegmentPrd03ArtifactsBody(registry=registry, segment=segment,
        holm_corrections=scoped.holm, bh_corrections=scoped.bh_fdr,
        observed_strategy_verdicts=strategy,
        observed_router_verdicts=router.verdicts,
        observed_verdicts=(*strategy, *router.verdicts),
        router_gates=router.gates)
    return SegmentPrd03Artifacts(registry=body.registry, segment=body.segment,
        holm_corrections=body.holm_corrections,
        bh_corrections=body.bh_corrections,
        observed_strategy_verdicts=body.observed_strategy_verdicts,
        observed_router_verdicts=body.observed_router_verdicts,
        observed_verdicts=body.observed_verdicts,
        router_gates=body.router_gates,
        artifact_hash=canonical_hash(model_json(body)))


def _scenario_scope(registry: FrozenHypothesisRegistry) -> CorrectionScope:
    return CorrectionScope(plan_manifest_hash=registry.plan_manifest_hash,
        registry_hash=registry.registry_hash, market=Market.KR,
        segment=ResearchSegment.VALIDATION,
        source_metrics_hashes=("scenario_fixture",),
        source_bootstrap_hashes=("scenario_fixture",))


def _router_input(
    scenario: RouterScenario,
    registry: FrozenHypothesisRegistry,
) -> RouterGateInput:
    if len(scenario.enabled_ids) != len(scenario.constituent_passes):
        raise V14ContractError("V14_ROUTER_FIXTURE", str(len(scenario.enabled_ids)))
    constituents = tuple(ConstituentGate(strategy_id=strategy_id, passed=passed,
        verdict_hash=f"scenario:{strategy_id}") for strategy_id, passed in zip(
            scenario.enabled_ids, scenario.constituent_passes, strict=True))
    return RouterGateInput(plan_manifest_hash=registry.plan_manifest_hash,
        registry_hash=registry.registry_hash, orb_passed=scenario.orb_passed,
        orb_verdict_hash="scenario:orb",
        frozen_enabled_strategy_ids=scenario.enabled_ids,
        enabled_constituents=constituents,
        router_metric_passed=scenario.router_metric_passed,
        paired_p_value=scenario.paired_p_value,
        mixed_metrics_hash="scenario:mixed",
        deterministic_metrics_hash="scenario:deterministic",
        paired_metrics_hash="scenario:paired")


def _scenario_holdout(
    scenario: MetricScenario,
    registry: FrozenHypothesisRegistry,
    holm: CorrectionArtifact,
) -> HoldoutVerdictArtifact:
    evidence = evidence_from_scenario(scenario)
    return holdout_verdict(evidence, confirmatory_gate(registry, evidence, holm))


@cache
def build_prd03() -> Prd03Artifacts:
    return build_prd03_from(load_prd03_fixture())


def build_prd03_from(fixture: Prd03Fixture) -> Prd03Artifacts:
    prd01 = build_prd01(load_fixture())
    registry = build_hypothesis_registry(prd01.plan)
    scope = _scenario_scope(registry)
    holm = holm_step_down(registry, fixture.holm_inputs, scope)
    exploratory_inputs = tuple(PValueInput(hypothesis_id=item.hypothesis_id,
        p_value=item.p_value, tested=True) for item in fixture.exploratory_inputs)
    exploratory = bh_fdr(registry, exploratory_inputs, scope)
    prd02 = build_prd02()
    scoped = build_scoped_corrections(
        registry, prd02.metrics, fixture.exploratory_inputs)
    strategy_verdicts = tuple(build_strategy_verdict(registry, item,
        correction_for(scoped.holm, item)) for item in prd02.metrics)
    router = build_router_observed(
        registry, prd02.router_comparisons, strategy_verdicts)
    validation = tuple(validation_verdict(evidence_from_scenario(item))
        for item in fixture.validation_scenarios)
    holdout = tuple(_scenario_holdout(item, registry, holm)
        for item in fixture.holdout_scenarios)
    router_pass = evaluate_router_gate(registry,
        _router_input(fixture.router_pass, registry))
    router_blocked = evaluate_router_gate(registry,
        _router_input(fixture.router_blocked, registry))
    body = Prd03ArtifactsBody(registry=registry, holm=holm,
        exploratory=exploratory, holm_corrections=scoped.holm,
        bh_corrections=scoped.bh_fdr, validation_scenarios=validation,
        holdout_scenarios=holdout,
        observed_strategy_verdicts=strategy_verdicts,
        observed_router_verdicts=router.verdicts,
        observed_verdicts=(*strategy_verdicts, *router.verdicts),
        router_gates=router.gates, router_pass=router_pass,
        router_blocked=router_blocked)
    return Prd03Artifacts(registry=body.registry, holm=body.holm,
        exploratory=body.exploratory,
        holm_corrections=body.holm_corrections,
        bh_corrections=body.bh_corrections,
        validation_scenarios=body.validation_scenarios,
        holdout_scenarios=body.holdout_scenarios,
        observed_strategy_verdicts=body.observed_strategy_verdicts,
        observed_router_verdicts=body.observed_router_verdicts,
        observed_verdicts=body.observed_verdicts,
        router_gates=body.router_gates, router_pass=body.router_pass,
        router_blocked=body.router_blocked,
        artifact_hash=canonical_hash(model_json(body)))
