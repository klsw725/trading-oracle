from __future__ import annotations

from pathlib import Path

from src.v11.canonical import canonical_hash, model_json

from .compatibility import build_compatibility
from .holdout import approve_holdout, consume_lease, freeze_holdout_plan, issue_lease
from .manifest import build_result_manifest
from .pipeline import Prd01Artifacts, build_prd01
from .prd04_run_models import ValidationRunArtifact
from .prd04_models import (
    HoldoutHistory,
    V14ResultBundle,
    V14ResultBundleBody,
)
from .prd04_runs import build_holdout_run, build_validation_run
from .prd04_source_models import LoadedSources, Prd04Source
from .prd04_sources import load_sources
from .verdict_models import HoldoutVerdict


ROOT = Path(__file__).parents[2]


def build_prd04(
    source: Prd04Source,
    prior_history: HoldoutHistory,
    root: Path = ROOT,
) -> V14ResultBundle:
    return build_prd04_from_loaded(
        source, prior_history, load_sources(source, root))


def build_prd04_from_loaded(
    source: Prd04Source,
    prior_history: HoldoutHistory,
    sources: LoadedSources,
) -> V14ResultBundle:
    prd01 = build_prd01(sources.prd01)
    validation = build_validation_run(prd01.plan, prd01.selection, sources)
    return build_prd04_after_validation(
        source, prior_history, sources, prd01, validation)


def build_prd04_after_validation(
    source: Prd04Source,
    prior_history: HoldoutHistory,
    sources: LoadedSources,
    prd01: Prd01Artifacts,
    validation: ValidationRunArtifact,
) -> V14ResultBundle:
    plan = freeze_holdout_plan(prd01.plan, sources, validation)
    approval = approve_holdout(plan, source.approval)
    lease = issue_lease(plan, approval, source.lease, prior_history)
    holdout = build_holdout_run(prd01.plan, prd01.selection, sources,
        plan, approval, lease, validation)
    history = consume_lease(prior_history, lease, holdout.holdout_run_hash)
    result = build_result_manifest(prd01.plan, sources.evidence, plan,
        approval, lease, validation, holdout, history)
    body = V14ResultBundleBody(schema_version="v14.result_bundle.2",
        source=source, source_evidence=sources.evidence, plan=prd01.plan,
        validation_run=validation, holdout_plan=plan, approval=approval,
        lease=lease, prior_history=prior_history, holdout_run=holdout,
        history=history, result_manifest=result,
        compatibility=build_compatibility(sources.v13),
        verdict_inventory=tuple(item.value for item in HoldoutVerdict),
        promotion_eligible=False, paper_side_effect_count=0,
        live_side_effect_count=0)
    return V14ResultBundle(schema_version=body.schema_version,
        source=body.source, source_evidence=body.source_evidence,
        plan=body.plan, validation_run=body.validation_run,
        holdout_plan=body.holdout_plan, approval=body.approval,
        lease=body.lease, prior_history=body.prior_history,
        holdout_run=body.holdout_run, history=body.history,
        result_manifest=body.result_manifest, compatibility=body.compatibility,
        verdict_inventory=body.verdict_inventory,
        promotion_eligible=body.promotion_eligible,
        paper_side_effect_count=body.paper_side_effect_count,
        live_side_effect_count=body.live_side_effect_count,
        bundle_hash=canonical_hash(model_json(body)))
