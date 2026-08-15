from __future__ import annotations

from unittest.mock import patch

from src.v11.canonical import canonical_hash, model_json

from .failure import V14Failure, V14FailureCode
from .hypothesis_models import RouterGateBody, RouterGateResult, RouterGateState
from .observed_models import (
    ObservedRouterVerdictArtifact,
    ObservedRouterVerdictBody,
    ObservedStrategyVerdictArtifact,
    ObservedStrategyVerdictBody,
)
from .pipeline import build_prd01
from .prd03_pipeline import SegmentPrd03Artifacts, SegmentPrd03ArtifactsBody
from .prd04_bundle import build_prd04_after_validation
from .prd04_models import HoldoutHistory, V14ResultBundle
from .prd04_run_models import ValidationRunArtifact, ValidationRunBody
from .prd04_runs import validation_scopes
from .prd04_source_models import LoadedSources, Prd04Source
from .verdict_models import ValidationVerdict


def _strategy(value: ObservedStrategyVerdictArtifact) -> ObservedStrategyVerdictArtifact:
    changed = value.model_copy(update={"verdict": ValidationVerdict.REJECT})
    body = ObservedStrategyVerdictBody.model_validate(
        changed.model_dump(exclude={"verdict_hash"}))
    return changed.model_copy(update={"verdict_hash": canonical_hash(model_json(body))})


def _router(value: ObservedRouterVerdictArtifact) -> ObservedRouterVerdictArtifact:
    changed = value.model_copy(update={"verdict": ValidationVerdict.REJECT})
    body = ObservedRouterVerdictBody.model_validate(
        changed.model_dump(exclude={"verdict_hash"}))
    return changed.model_copy(update={"verdict_hash": canonical_hash(model_json(body))})


def _gate(value: RouterGateResult) -> RouterGateResult:
    changed = value.model_copy(update={"state": RouterGateState.METRIC_BLOCKED,
        "confirmatory_passed": False})
    body = RouterGateBody.model_validate(changed.model_dump(exclude={"gate_hash"}))
    return changed.model_copy(update={"gate_hash": canonical_hash(model_json(body))})


def _prd03(value: SegmentPrd03Artifacts) -> SegmentPrd03Artifacts:
    body = SegmentPrd03ArtifactsBody.model_validate(
        value.model_dump(exclude={"artifact_hash"}))
    return value.model_copy(update={"artifact_hash": canonical_hash(model_json(body))})


def _validation(value: ValidationRunArtifact) -> ValidationRunArtifact:
    body = ValidationRunBody.model_validate(
        value.model_dump(exclude={"validation_run_hash"}))
    return value.model_copy(update={
        "validation_run_hash": canonical_hash(model_json(body))})


def sealed_validation_reject(
    validation: ValidationRunArtifact,
) -> ValidationRunArtifact:
    strategy = (_strategy(validation.prd03.observed_strategy_verdicts[0]),
        *validation.prd03.observed_strategy_verdicts[1:])
    routers = (_router(validation.prd03.observed_router_verdicts[0]),
        validation.prd03.observed_router_verdicts[1])
    gates = (_gate(validation.prd03.router_gates[0]),
        validation.prd03.router_gates[1])
    prd03 = _prd03(validation.prd03.model_copy(update={
        "observed_strategy_verdicts": strategy,
        "observed_router_verdicts": routers,
        "observed_verdicts": (*strategy, *routers), "router_gates": gates}))
    provisional = _validation(validation.model_copy(update={"prd03": prd03}))
    return _validation(provisional.model_copy(
        update={"market_scopes": validation_scopes(provisional)}))


def reject_validation_before_holdout(
    source: Prd04Source,
    prior: HoldoutHistory,
    sources: LoadedSources,
    bundle: V14ResultBundle,
) -> None:
    rejected = sealed_validation_reject(bundle.validation_run)
    with patch("src.v14.prd04_bundle.build_holdout_run") as holdout:
        try:
            _ = build_prd04_after_validation(source, prior, sources,
                build_prd01(sources.prd01), rejected)
        except V14Failure as error:
            if error.code is V14FailureCode.VALIDATION_GATE and not holdout.called:
                raise
            raise AssertionError("validation reject reached holdout") from error
    raise AssertionError("validation reject opened holdout")
