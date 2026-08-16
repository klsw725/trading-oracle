from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field
from src.v14.prd04_models import V14ResultBundle
from src.v14.verdict_models import HoldoutVerdict, ValidationVerdict

from .contract import StrictModel, V15Failure, V15FailureCode


class MarketGateEvidence(StrictModel):
    market: Literal["KR", "US"]
    orb_validation_verdict: Literal["VALIDATION_PASS"]
    orb_validation_hash: str
    orb_holdout_verdict: Literal["PASS"]
    orb_holdout_hash: str
    router_validation_state: Literal["pass"]
    router_validation_verdict_hash: str
    router_validation_gate_hash: str
    router_holdout_state: Literal["pass"]
    router_holdout_verdict_hash: str
    router_holdout_gate_hash: str
    enabled_strategy_ids: Annotated[tuple[str, ...], Field(strict=False)]


class PolicyIdentity(StrictModel):
    manifest_hash: str
    experiment_version: str
    code_commit: str
    config_hash: str
    prompt_hash: str
    model_version: str
    schema_hash: str
    cost_model: str
    strategy_version: str
    risk_version: str
    router_version: str


class BootstrapIdentity(StrictModel):
    plan_manifest_hash: str
    experiment_version: str
    seed: int
    block_trading_days: Literal[5]
    resamples: Literal[10000]
    hypothesis_id: Literal["mixed_router_vs_deterministic"]


class UpstreamEvidence(StrictModel):
    schema_version: Literal["v15.upstream_evidence.1"]
    v14_bundle_hash: str
    v14_result_manifest_hash: str
    v14_approval_hash: str
    gate_available_at: datetime
    gate_reviewer: str
    policy: PolicyIdentity
    bootstrap: BootstrapIdentity
    markets: Annotated[tuple[MarketGateEvidence, MarketGateEvidence],
        Field(strict=False)]
    v11_prd_count: Literal[4]


def extract_upstream(bundle: V14ResultBundle) -> UpstreamEvidence:
    primary = bundle.plan.hypotheses.primary_id
    enabled = bundle.plan.hypotheses.holm_family_ids
    if len(enabled) != 14 or primary in enabled:
        raise V15Failure(V15FailureCode.UPSTREAM_EVIDENCE, "strategy_inventory")
    markets = tuple(_market_evidence(bundle, market, enabled)
        for market in ("KR", "US"))
    policy = PolicyIdentity(manifest_hash=bundle.plan.manifest_hash,
        experiment_version=bundle.plan.experiment_version,
        code_commit=bundle.plan.code.commit,
        config_hash=bundle.plan.config.config_hash,
        prompt_hash=bundle.plan.prompt.canonical_bytes_hex,
        model_version=bundle.plan.prompt.codex_model,
        schema_hash=bundle.plan.prompt.output_schema_hash,
        cost_model=bundle.plan.costs.stress_2x_variable,
        strategy_version=bundle.plan.components.strategy,
        risk_version=bundle.plan.components.risk,
        router_version=bundle.plan.components.router)
    bootstrap = BootstrapIdentity(plan_manifest_hash=bundle.plan.manifest_hash,
        experiment_version=bundle.plan.experiment_version,
        seed=bundle.plan.bootstrap.seed,
        block_trading_days=bundle.plan.bootstrap.block_trading_days,
        resamples=bundle.plan.bootstrap.resamples,
        hypothesis_id=bundle.plan.hypotheses.router_hypothesis_id)
    return UpstreamEvidence(schema_version="v15.upstream_evidence.1",
        v14_bundle_hash=bundle.bundle_hash,
        v14_result_manifest_hash=bundle.result_manifest.result_manifest_hash,
        v14_approval_hash=bundle.approval.approval_hash,
        gate_available_at=bundle.approval.approved_at,
        gate_reviewer=bundle.approval.operator_id,
        policy=policy, bootstrap=bootstrap,
        markets=(markets[0], markets[1]),
        v11_prd_count=bundle.compatibility.v11_prd_count)


def _market_evidence(
    bundle: V14ResultBundle,
    market: Literal["KR", "US"],
    expected_enabled: tuple[str, ...],
) -> MarketGateEvidence:
    validation_orb = tuple(item for item in
        bundle.validation_run.prd03.observed_strategy_verdicts
        if item.market.value == market and item.hypothesis_id == "long_orb_15m")
    holdout_orb = tuple(item for item in
        bundle.holdout_run.prd03.observed_strategy_verdicts
        if item.market.value == market and item.hypothesis_id == "long_orb_15m")
    validation_router = tuple(item for item in
        bundle.validation_run.prd03.observed_router_verdicts
        if item.market.value == market)
    holdout_router = tuple(item for item in
        bundle.holdout_run.prd03.observed_router_verdicts
        if item.market.value == market)
    market_index = 0 if market == "KR" else 1
    validation_gate = bundle.validation_run.prd03.router_gates[market_index]
    holdout_gate = bundle.holdout_run.prd03.router_gates[market_index]
    if len(validation_orb) != 1 or len(holdout_orb) != 1 \
            or len(validation_router) != 1 or len(holdout_router) != 1:
        raise V15Failure(V15FailureCode.UPSTREAM_EVIDENCE, market)
    if validation_orb[0].verdict is not ValidationVerdict.PASS \
            or holdout_orb[0].verdict is not HoldoutVerdict.PASS \
            or validation_router[0].verdict is not ValidationVerdict.PASS \
            or holdout_router[0].verdict is not HoldoutVerdict.PASS:
        raise V15Failure(V15FailureCode.PROMOTION_BLOCKED, market)
    if validation_gate.state != "pass" or holdout_gate.state != "pass" \
            or validation_gate.enabled_strategy_ids != expected_enabled \
            or holdout_gate.enabled_strategy_ids != expected_enabled \
            or validation_gate.plan_manifest_hash != bundle.plan.manifest_hash \
            or holdout_gate.plan_manifest_hash != bundle.plan.manifest_hash \
            or validation_gate.orb_verdict_hash != validation_orb[0].verdict_hash \
            or holdout_gate.orb_verdict_hash != holdout_orb[0].verdict_hash:
        raise V15Failure(V15FailureCode.UPSTREAM_EVIDENCE, f"router:{market}")
    return MarketGateEvidence(market=market,
        orb_validation_verdict="VALIDATION_PASS",
        orb_validation_hash=validation_orb[0].verdict_hash,
        orb_holdout_verdict="PASS", orb_holdout_hash=holdout_orb[0].verdict_hash,
        router_validation_state="pass",
        router_validation_verdict_hash=validation_router[0].verdict_hash,
        router_validation_gate_hash=validation_gate.gate_hash,
        router_holdout_state="pass",
        router_holdout_verdict_hash=holdout_router[0].verdict_hash,
        router_holdout_gate_hash=holdout_gate.gate_hash,
        enabled_strategy_ids=expected_enabled)
