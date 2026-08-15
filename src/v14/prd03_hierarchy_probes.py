from __future__ import annotations

from typing import TypedDict

from src.v12.models import Market

from .hypothesis_models import RouterGateState
from .prd02_pipeline import Prd02Artifacts
from .prd03_pipeline import Prd03Artifacts
from .prd03_router import build_router_observed
from .series_models import ResearchSegment
from .verdict_models import ValidationVerdict


class HierarchyChecks(TypedDict):
    scoped_holm_exact_4: bool
    scoped_bh_exact_4: bool
    scoped_lineage_bound: bool
    holm_uses_matching_bootstraps: bool
    bh_confirmatory_isolation_scoped: bool
    observed_strategy_exact_60: bool
    observed_router_exact_4: bool
    observed_segment_inventory: bool
    strategy_correction_applied: bool
    router_comparison_lineage: bool
    router_prerequisite_hashes: bool
    router_failed_validation_not_opened: bool


def hierarchy_checks(
    artifacts: Prd03Artifacts, prd02: Prd02Artifacts
) -> HierarchyChecks:
    scopes = {(market, segment) for market in Market
        for segment in ResearchSegment}
    holm_scopes = {(item.market, item.segment)
        for item in artifacts.holm_corrections}
    bh_scopes = {(item.market, item.segment)
        for item in artifacts.bh_corrections}
    metrics_by_scope = {(market, segment): tuple(item for item in prd02.metrics
        if item.market is market and item.segment is segment)
        for market, segment in scopes}
    holm_source_matches = all(
        correction.source_metrics_hashes == tuple(item.metrics_hash
            for item in metrics_by_scope[(correction.market, correction.segment)]
            if item.hypothesis_id != artifacts.registry.primary.hypothesis_id)
        and correction.source_bootstrap_hashes == tuple(
            item.baseline.bootstrap.bootstrap_hash
            for item in metrics_by_scope[(correction.market, correction.segment)]
            if item.hypothesis_id != artifacts.registry.primary.hypothesis_id)
        and all(result.raw_p_value == next(item.baseline.bootstrap.one_sided_p_value
            for item in metrics_by_scope[(correction.market, correction.segment)]
            if item.hypothesis_id == result.hypothesis_id)
            for result in correction.results)
        for correction in artifacts.holm_corrections)
    scoped_lineage = all(item.plan_manifest_hash
        == artifacts.registry.plan_manifest_hash
        and item.registry_hash == artifacts.registry.registry_hash
        for item in (*artifacts.holm_corrections, *artifacts.bh_corrections))
    strategy = artifacts.observed_strategy_verdicts
    router = artifacts.observed_router_verdicts
    comparison_by_hash = {item.comparison_hash: item
        for item in prd02.router_comparisons}
    strategy_hashes = {item.verdict_hash for item in strategy}
    router_lineage = all(
        item.comparison_hash in comparison_by_hash
        and item.mixed_metrics_hash
            == comparison_by_hash[item.comparison_hash].mixed_metrics.metrics_hash
        and item.deterministic_metrics_hash
            == comparison_by_hash[item.comparison_hash].deterministic_metrics.metrics_hash
        and item.paired_metrics_hash
            == comparison_by_hash[item.comparison_hash].paired_metrics.metrics_hash
        and item.gate_hash in {gate.gate_hash for gate in artifacts.router_gates}
        for item in router)
    failed_strategy = tuple(item.model_copy(update={
        "correction_passed": False, "verdict": ValidationVerdict.REJECT,
        "verdict_hash": "probe:failed-validation"})
        if item.market is Market.KR
            and item.segment is ResearchSegment.VALIDATION
            and item.hypothesis_id == artifacts.registry.primary.hypothesis_id
        else item for item in strategy)
    failed_router = build_router_observed(
        artifacts.registry, prd02.router_comparisons, failed_strategy)
    kr_holdout = next(item for item in failed_router.verdicts
        if item.market is Market.KR and item.segment is ResearchSegment.HOLDOUT)
    kr_holdout_gate = next(item for item in failed_router.gates
        if item.gate_hash == kr_holdout.gate_hash)
    return HierarchyChecks(scoped_holm_exact_4=len(artifacts.holm_corrections) == 4
            and holm_scopes == scopes,
        scoped_bh_exact_4=len(artifacts.bh_corrections) == 4
            and bh_scopes == scopes,
        scoped_lineage_bound=scoped_lineage,
        holm_uses_matching_bootstraps=holm_source_matches,
        bh_confirmatory_isolation_scoped=all(not result.confirmatory
            for item in artifacts.bh_corrections for result in item.results),
        observed_strategy_exact_60=len(strategy) == 60,
        observed_router_exact_4=len(router) == 4,
        observed_segment_inventory=sum(item.segment is ResearchSegment.VALIDATION
            for item in strategy) == 30
            and sum(item.segment is ResearchSegment.HOLDOUT for item in strategy) == 30
            and sum(item.segment is ResearchSegment.VALIDATION for item in router) == 2
            and sum(item.segment is ResearchSegment.HOLDOUT for item in router) == 2,
        strategy_correction_applied=all(item.correction_passed
            for item in strategy if item.verdict in {
                ValidationVerdict.PASS, "PASS"})
            and all(item.correction_hash is not None for item in strategy
                if item.hypothesis_id != artifacts.registry.primary.hypothesis_id),
        router_comparison_lineage=router_lineage,
        router_prerequisite_hashes=all(item.orb_verdict_hash in strategy_hashes
            and set(item.constituent_verdict_hashes).issubset(strategy_hashes)
            and len(item.constituent_verdict_hashes) == 14 for item in router),
        router_failed_validation_not_opened=
            kr_holdout.verdict == "HOLDOUT_NOT_OPENED"
            and kr_holdout_gate.state is RouterGateState.NOT_OPENED)
