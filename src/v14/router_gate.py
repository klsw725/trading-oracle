from __future__ import annotations

from src.v11.canonical import canonical_hash, model_json

from .contract import V14ContractError
from .hypothesis_models import (
    FrozenHypothesisRegistry,
    RouterGateBody,
    RouterGateInput,
    RouterGateResult,
    RouterGateState,
)
from .multiple_testing import one_sided_alpha


def evaluate_router_gate(
    registry: FrozenHypothesisRegistry, gate: RouterGateInput
) -> RouterGateResult:
    enabled = tuple(item.strategy_id for item in gate.enabled_constituents)
    verdict_hashes = tuple(item.verdict_hash for item in gate.enabled_constituents)
    allowed = {item.hypothesis_id for item in registry.holm_family}
    if enabled != gate.frozen_enabled_strategy_ids \
            or not enabled or len(enabled) != len(set(enabled)) \
            or not set(enabled).issubset(allowed) \
            or len(verdict_hashes) != len(set(verdict_hashes)):
        raise V14ContractError("V14_ROUTER_ENABLED_SET", str(enabled))
    if not gate.orb_passed:
        state = RouterGateState.ORB_BLOCKED
    elif not all(item.passed for item in gate.enabled_constituents):
        state = RouterGateState.CONSTITUENT_BLOCKED
    elif not gate.router_metric_passed:
        state = RouterGateState.METRIC_BLOCKED
    elif not one_sided_alpha(gate.paired_p_value):
        state = RouterGateState.ALPHA_BLOCKED
    else:
        state = RouterGateState.PASS
    body = RouterGateBody(state=state,
        confirmatory_passed=state is RouterGateState.PASS,
        enabled_strategy_ids=enabled, paired_p_value=gate.paired_p_value,
        plan_manifest_hash=gate.plan_manifest_hash,
        registry_hash=gate.registry_hash, orb_verdict_hash=gate.orb_verdict_hash,
        constituent_verdict_hashes=verdict_hashes,
        mixed_metrics_hash=gate.mixed_metrics_hash,
        deterministic_metrics_hash=gate.deterministic_metrics_hash,
        paired_metrics_hash=gate.paired_metrics_hash)
    return RouterGateResult(state=body.state,
        confirmatory_passed=body.confirmatory_passed,
        enabled_strategy_ids=body.enabled_strategy_ids,
        paired_p_value=body.paired_p_value,
        plan_manifest_hash=body.plan_manifest_hash,
        registry_hash=body.registry_hash, orb_verdict_hash=body.orb_verdict_hash,
        constituent_verdict_hashes=body.constituent_verdict_hashes,
        mixed_metrics_hash=body.mixed_metrics_hash,
        deterministic_metrics_hash=body.deterministic_metrics_hash,
        paired_metrics_hash=body.paired_metrics_hash,
        gate_hash=canonical_hash(model_json(body)))
