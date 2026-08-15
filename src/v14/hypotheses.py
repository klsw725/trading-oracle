from __future__ import annotations

from typing import Final

from src.v11.canonical import canonical_hash, model_json
from src.v12.registry import REGISTRY

from .contract import V14ContractError
from .hypothesis_models import (
    FrozenHypothesisRegistry,
    FrozenHypothesisRegistryBody,
    HypothesisRole,
    HypothesisSpec,
)
from .manifest_models import ExperimentPlanManifest


PRIMARY_ID: Final = "long_orb_15m"
STRATEGY_NULL: Final = "daily_net_excess_return<=0"
ROUTER_NULL: Final = "paired_mixed_minus_deterministic<=0"


def build_hypothesis_registry(
    plan: ExperimentPlanManifest,
) -> FrozenHypothesisRegistry:
    strategy_ids = tuple(item.strategy_id for item in REGISTRY)
    holm_ids = tuple(item for item in strategy_ids if item != PRIMARY_ID)
    if plan.hypotheses.primary_id != PRIMARY_ID \
            or plan.hypotheses.holm_family_ids != holm_ids \
            or plan.hypotheses.router_candidate_registry != strategy_ids:
        raise V14ContractError("V14_HYPOTHESIS_REGISTRY", plan.manifest_hash)
    primary = HypothesisSpec(hypothesis_id=PRIMARY_ID,
        role=HypothesisRole.PRIMARY, null=STRATEGY_NULL,
        comparator="no_trade", confirmatory=True)
    holm = tuple(HypothesisSpec(hypothesis_id=item,
        role=HypothesisRole.HOLM, null=STRATEGY_NULL,
        comparator="no_trade", confirmatory=True) for item in holm_ids)
    exploratory = tuple(HypothesisSpec(hypothesis_id=item,
        role=HypothesisRole.EXPLORATORY, null="exploratory_association<=0",
        comparator="descriptive_baseline", confirmatory=False)
        for item in plan.hypotheses.exploratory_ids)
    router = HypothesisSpec(
        hypothesis_id=plan.hypotheses.router_hypothesis_id,
        role=HypothesisRole.ROUTER, null=ROUTER_NULL,
        comparator="deterministic_only_router", confirmatory=True)
    body = FrozenHypothesisRegistryBody(
        schema_version="v14.hypothesis_registry.1",
        plan_manifest_hash=plan.manifest_hash, primary=primary,
        holm_family=holm, exploratory=exploratory, router=router)
    return FrozenHypothesisRegistry(schema_version=body.schema_version,
        plan_manifest_hash=body.plan_manifest_hash, primary=body.primary,
        holm_family=body.holm_family, exploratory=body.exploratory,
        router=body.router, registry_hash=canonical_hash(model_json(body)))
