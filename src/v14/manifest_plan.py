from __future__ import annotations

from typing import Final

from src.v11.canonical import canonical_hash, model_json
from src.v12.registry import REGISTRY

from .cohort_models import FrozenCohort
from .contract import V14ContractError
from .manifest_models import (
    ExperimentPlanBody,
    ExperimentPlanManifest,
    HypothesisRegistry,
    MarketPeriod,
    PlanInputs,
)
from .selection_models import DevelopmentSelection


PRIMARY_ID: Final = "long_orb_15m"


def build_experiment_plan(
    inputs: PlanInputs,
    cohort: FrozenCohort,
    selection: DevelopmentSelection,
) -> ExperimentPlanManifest:
    if selection.cohort_hash != cohort.cohort_hash:
        raise V14ContractError("V14_PLAN_LINEAGE", selection.cohort_hash)
    strategy_ids = tuple(spec.strategy_id for spec in REGISTRY)
    holm_ids = tuple(item for item in strategy_ids if item != PRIMARY_ID)
    periods = tuple(MarketPeriod(market=item.market,
        development_start=item.development.start,
        validation_start=item.validation.start,
        holdout_start=item.holdout.start,
        holdout_end=item.holdout.end) for item in cohort.markets)
    hypotheses = HypothesisRegistry(primary_id="long_orb_15m",
        holm_family_ids=holm_ids,
        router_hypothesis_id="mixed_router_vs_deterministic",
        router_candidate_registry=strategy_ids,
        router_enabled_set_freeze_stage="after_validation",
        exploratory_ids=inputs.exploratory_ids)
    body = ExperimentPlanBody(schema_version="v14.experiment_plan.1",
        cohort_hash=cohort.cohort_hash, selection_hash=selection.selection_hash,
        code=inputs.code, runtime_lock=inputs.runtime_lock, config=inputs.config,
        components=inputs.components, universes=inputs.universes,
        references=inputs.references, data=inputs.data, sources=inputs.sources,
        costs=inputs.costs, prompt=inputs.prompt, bootstrap=inputs.bootstrap,
        periods=periods, hypotheses=hypotheses)
    digest = canonical_hash(model_json(body))
    return ExperimentPlanManifest(schema_version=body.schema_version,
        cohort_hash=body.cohort_hash, selection_hash=body.selection_hash,
        code=body.code, runtime_lock=body.runtime_lock, config=body.config,
        components=body.components, universes=body.universes,
        references=body.references, data=body.data, sources=body.sources,
        costs=body.costs, prompt=body.prompt, bootstrap=body.bootstrap,
        periods=body.periods, hypotheses=body.hypotheses,
        experiment_version=f"v14:{digest.removeprefix('sha256:')[:20]}",
        manifest_hash=digest)


def result_free_plan(manifest: ExperimentPlanManifest) -> ExperimentPlanBody:
    return ExperimentPlanBody(schema_version=manifest.schema_version,
        cohort_hash=manifest.cohort_hash, selection_hash=manifest.selection_hash,
        code=manifest.code, runtime_lock=manifest.runtime_lock,
        config=manifest.config, components=manifest.components,
        universes=manifest.universes, references=manifest.references,
        data=manifest.data, sources=manifest.sources, costs=manifest.costs,
        prompt=manifest.prompt, bootstrap=manifest.bootstrap,
        periods=manifest.periods, hypotheses=manifest.hypotheses)


def result_free_plan_hash(manifest: ExperimentPlanManifest) -> str:
    return canonical_hash(model_json(result_free_plan(manifest)))
