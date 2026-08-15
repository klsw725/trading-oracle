from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal

from src.v11.canonical import canonical_hash, model_json
from src.v4.models import JsonValue

from .contract import V14ContractError
from .fixture import load_fixture
from .hypothesis_models import (
    ConstituentGate,
    FrozenHypothesisRegistry,
    RouterGateInput,
    RouterGateState,
)
from .multiple_testing import one_sided_alpha
from .pipeline import build_prd01
from .prd02_pipeline import build_prd02
from .prd03_fixture import load_prd03_fixture
from .prd03_hierarchy_probes import hierarchy_checks
from .prd03_pipeline import build_prd03
from .prd03_router_probes import router_scenario_results
from .router_gate import evaluate_router_gate
from .verdict_models import HoldoutVerdict, Prd03Fixture, ValidationVerdict
from .verdicts import (
    evidence_from_metrics,
    evidence_from_scenario,
    holdout_outcome_id,
    holdout_verdict,
    validation_verdict,
    validation_outcome_id,
)


def _kills[T](code: str, operation: Callable[[], T]) -> bool:
    try:
        _ = operation()
    except V14ContractError as error:
        return error.code == code
    return False


def _evaluate_router(
    registry: FrozenHypothesisRegistry, gate: RouterGateInput
) -> None:
    _ = evaluate_router_gate(registry, gate)


def _secondary_override_killed(fixture: Prd03Fixture) -> bool:
    scenario = next(item for item in fixture.holdout_scenarios
        if item.scenario_id == "no_edge")
    changed = scenario.model_copy(update={"secondary_sharpe": Decimal("999")})
    original_evidence = evidence_from_scenario(scenario)
    changed_evidence = evidence_from_scenario(changed)
    original = holdout_verdict(original_evidence, True)
    modified = holdout_verdict(changed_evidence, True)
    return original.verdict is HoldoutVerdict.NO_EDGE \
        and original_evidence == changed_evidence \
        and modified.verdict is original.verdict


def run_probes() -> tuple[
    dict[str, bool], dict[str, str], dict[str, str], tuple[str, ...]
]:
    plan = build_prd01(load_fixture()).plan
    fixture = load_prd03_fixture()
    artifacts = build_prd03()
    repeated = build_prd03()
    expected_holm = tuple(plan.hypotheses.holm_family_ids)
    holm_results = artifacts.holm.results
    first_failure = next(index for index, item in enumerate(holm_results)
        if not item.correction_passed)
    discoveries = {item.hypothesis_id for item in artifacts.exploratory.results
        if item.correction_passed}
    holdout_pairs = tuple(zip(fixture.holdout_scenarios,
        artifacts.holdout_scenarios, strict=True))
    validation_pairs = tuple(zip(fixture.validation_scenarios,
        artifacts.validation_scenarios, strict=True))
    prd02 = build_prd02()
    actual_metric = prd02.metrics[0]
    original_evidence = evidence_from_metrics(actual_metric, True)
    passing_gate = RouterGateInput(
        plan_manifest_hash=plan.manifest_hash,
        registry_hash=artifacts.registry.registry_hash, orb_passed=True,
        orb_verdict_hash="probe:orb",
        frozen_enabled_strategy_ids=fixture.router_pass.enabled_ids,
        enabled_constituents=tuple(ConstituentGate(strategy_id=strategy_id,
            passed=True, verdict_hash=f"probe:{strategy_id}")
            for strategy_id in fixture.router_pass.enabled_ids),
        router_metric_passed=True, paired_p_value=Decimal("0.01"),
        mixed_metrics_hash="probe:mixed",
        deterministic_metrics_hash="probe:deterministic",
        paired_metrics_hash="probe:paired")
    orb_only = evaluate_router_gate(artifacts.registry,
        passing_gate.model_copy(update={"enabled_constituents": (
            ConstituentGate(strategy_id=expected_holm[0], passed=False,
                verdict_hash="probe:blocked"),),
            "frozen_enabled_strategy_ids": (expected_holm[0],)}))
    router_states = tuple(evaluate_router_gate(artifacts.registry, gate).state
        for gate in (passing_gate.model_copy(update={"orb_passed": False}),
            passing_gate.model_copy(update={"router_metric_passed": False}),
            passing_gate.model_copy(update={"paired_p_value": Decimal("0.051")})))
    validation_base = fixture.validation_scenarios[0]
    validation_boundaries = tuple(validation_verdict(evidence_from_scenario(
        validation_base.model_copy(update=change))).verdict for change in (
            {"signal_days": 59}, {"completed_trades": 149},
            {"integrity_valid": False}, {"baseline_return": Decimal("0")},
            {"stress_return": Decimal("0")}, {"ci_upper": Decimal("0")}))
    holdout_base = fixture.holdout_scenarios[0]
    holdout_collisions = tuple(holdout_verdict(evidence_from_scenario(
        holdout_base.model_copy(update=change)), correction).verdict
        for change, correction in (
            ({"integrity_valid": False, "signal_days": 0,
                "ci_upper": Decimal("0"), "stress_return": Decimal("0")}, False),
            ({"signal_days": 99, "ci_upper": Decimal("0"),
                "stress_return": Decimal("0")}, False),
            ({"completed_trades": 299, "ci_upper": Decimal("0")}, False),
            ({"ci_upper": Decimal("0"), "stress_return": Decimal("0")}, False),
            ({"stress_return": Decimal("0"), "ci_lower": Decimal("0")}, False),
            ({"ci_lower": Decimal("0")}, False), ({}, False), ({}, True)))
    hierarchy = hierarchy_checks(artifacts, prd02)
    router_scenarios = router_scenario_results(artifacts, prd02)
    checks: dict[str, bool] = {
        "scoped_holm_exact_4": hierarchy["scoped_holm_exact_4"],
        "scoped_bh_exact_4": hierarchy["scoped_bh_exact_4"],
        "scoped_lineage_bound": hierarchy["scoped_lineage_bound"],
        "holm_uses_matching_bootstraps":
            hierarchy["holm_uses_matching_bootstraps"],
        "bh_confirmatory_isolation_scoped":
            hierarchy["bh_confirmatory_isolation_scoped"],
        "observed_strategy_exact_60": hierarchy["observed_strategy_exact_60"],
        "observed_router_exact_4": hierarchy["observed_router_exact_4"],
        "observed_segment_inventory": hierarchy["observed_segment_inventory"],
        "strategy_correction_applied": hierarchy["strategy_correction_applied"],
        "router_comparison_lineage": hierarchy["router_comparison_lineage"],
        "router_prerequisite_hashes": hierarchy["router_prerequisite_hashes"],
        "router_failed_validation_not_opened":
            hierarchy["router_failed_validation_not_opened"],
        "observed_verdicts_exact_64": len(artifacts.observed_verdicts) == 64,
        "primary_registry_exact": artifacts.registry.primary.hypothesis_id
            == "long_orb_15m",
        "holm_registry_exact_14": len(artifacts.registry.holm_family) == 14
            and tuple(item.hypothesis_id for item in artifacts.registry.holm_family)
            == expected_holm,
        "holm_denominator_fixed": artifacts.holm.family_size == 14
            and artifacts.holm.results[0].threshold == Decimal("0.05") / 14,
        "holm_first_failure_propagates": first_failure == 2
            and all(not item.correction_passed
                for item in holm_results[first_failure:]),
        "untested_family_represented": len(holm_results) == 14
            and sum(not item.tested for item in holm_results) == 2,
        "bootstrap_p_value_consumed": original_evidence.one_sided_p_value
            == actual_metric.baseline.bootstrap.one_sided_p_value,
        "one_sided_alpha": one_sided_alpha(Decimal("0.05"))
            and not one_sided_alpha(Decimal("0.05000001")),
        "bh_step_up": discoveries == {"completed_trades", "win_rate"},
        "bh_confirmatory_isolation": all(not item.confirmatory
            for item in artifacts.exploratory.results),
        "router_pass": artifacts.router_pass.state is RouterGateState.PASS
            and artifacts.router_pass.confirmatory_passed,
        "router_prerequisite_block": artifacts.router_blocked.state
            is RouterGateState.CONSTITUENT_BLOCKED
            and orb_only.state is RouterGateState.CONSTITUENT_BLOCKED,
        "router_orb_metric_alpha_order": router_states == (
            RouterGateState.ORB_BLOCKED, RouterGateState.METRIC_BLOCKED,
            RouterGateState.ALPHA_BLOCKED),
        "router_enabled_set_frozen": _kills("V14_ROUTER_ENABLED_SET",
            lambda: _evaluate_router(artifacts.registry,
                passing_gate.model_copy(update={
                    "frozen_enabled_strategy_ids": (
                        expected_holm[0], expected_holm[1]),
                    "enabled_constituents": (ConstituentGate(
                        strategy_id=expected_holm[0], passed=True,
                        verdict_hash="probe:mismatch"),)}))),
        "validation_inventory": {item.verdict for item
            in artifacts.validation_scenarios} == set(ValidationVerdict),
        "validation_rules": all(validation_outcome_id(result.verdict)
            == scenario.scenario_id for scenario, result in validation_pairs),
        "validation_60_150_sign_stress_ci_upper": validation_boundaries == (
            ValidationVerdict.INCONCLUSIVE, ValidationVerdict.INCONCLUSIVE,
            ValidationVerdict.REJECT, ValidationVerdict.REJECT,
            ValidationVerdict.REJECT, ValidationVerdict.REJECT),
        "holdout_inventory": {item.verdict for item
            in artifacts.holdout_scenarios} == set(HoldoutVerdict),
        "holdout_precedence": all(holdout_outcome_id(result.verdict)
            == scenario.scenario_id for scenario, result in holdout_pairs),
        "holdout_100_300_precedence_collisions": holdout_collisions == (
            HoldoutVerdict.INVALID_EXPERIMENT,
            HoldoutVerdict.INSUFFICIENT_SAMPLE,
            HoldoutVerdict.INSUFFICIENT_SAMPLE, HoldoutVerdict.NO_EDGE,
            HoldoutVerdict.COST_FRAGILE, HoldoutVerdict.INCONCLUSIVE,
            HoldoutVerdict.MULTIPLE_TESTING, HoldoutVerdict.PASS),
        "multiple_testing_connected": next(result for scenario, result
            in holdout_pairs if scenario.scenario_id == "multiple_testing").verdict
            is HoldoutVerdict.MULTIPLE_TESTING,
        "router_raw_verdict_precedence": router_scenarios == {
            "no_edge": HoldoutVerdict.NO_EDGE,
            "cost_fragile": HoldoutVerdict.COST_FRAGILE,
            "insufficient": HoldoutVerdict.INSUFFICIENT_SAMPLE,
            "inconclusive": HoldoutVerdict.INCONCLUSIVE,
            "invalid": HoldoutVerdict.INVALID_EXPERIMENT,
            "multiple_testing": HoldoutVerdict.MULTIPLE_TESTING},
        "typed_prd02_observed": len(artifacts.observed_strategy_verdicts) == 60
            and len(artifacts.observed_router_verdicts) == 4,
        "deterministic_corrected_verdicts": artifacts == repeated,
        "canonical_artifacts": all(value.startswith("sha256:") for value in (
            artifacts.registry.registry_hash, artifacts.holm.correction_hash,
            artifacts.exploratory.correction_hash, artifacts.artifact_hash)),
    }
    killed = {
        "uncorrected_family": any(item.tested
            and item.raw_p_value <= Decimal("0.05")
            and not item.correction_passed for item in holm_results),
        "secondary_override": _secondary_override_killed(fixture),
    }
    mutations = {key: "killed" if value else "survived"
        for key, value in killed.items()}
    verdict_json: JsonValue = [model_json(item)
        for item in artifacts.holdout_scenarios]
    hashes = {
        "fixture_hash": canonical_hash(model_json(fixture)),
        "registry_hash": artifacts.registry.registry_hash,
        "holm_hash": artifacts.holm.correction_hash,
        "exploratory_hash": artifacts.exploratory.correction_hash,
        "verdict_set_hash": canonical_hash(verdict_json),
        "scoped_correction_set_hash": canonical_hash([
            item.correction_hash for item in (
                *artifacts.holm_corrections, *artifacts.bh_corrections)]),
        "observed_verdict_set_hash": canonical_hash([
            item.verdict_hash for item in artifacts.observed_verdicts]),
        "router_gate_set_hash": canonical_hash([
            item.gate_hash for item in artifacts.router_gates]),
        "prd03_artifact_hash": artifacts.artifact_hash,
    }
    verdict_inventory = tuple(item.value for item in HoldoutVerdict)
    return checks, mutations, hashes, verdict_inventory
