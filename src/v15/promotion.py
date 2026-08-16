from __future__ import annotations

from typing import Literal

from .contract import StrictModel, V15Failure, V15FailureCode
from .upstream import MarketGateEvidence, UpstreamEvidence
from .retirement import RetirementRegistry, require_active


class OperationalSample(StrictModel):
    official_sessions: int
    completed_trades: int
    critical_incidents: int


def market_gate(
    evidence: UpstreamEvidence, market: Literal["KR", "US"]
) -> MarketGateEvidence:
    matched = tuple(item for item in evidence.markets if item.market == market)
    if len(matched) != 1:
        raise V15Failure(V15FailureCode.UPSTREAM_EVIDENCE, market)
    return matched[0]


def require_orb_paper(
    evidence: UpstreamEvidence, market: Literal["KR", "US"]
) -> MarketGateEvidence:
    gate = market_gate(evidence, market)
    if gate.orb_validation_verdict != "VALIDATION_PASS" \
            or gate.orb_holdout_verdict != "PASS":
        raise V15Failure(V15FailureCode.PROMOTION_BLOCKED, f"orb:{market}")
    return gate


def require_strategies_shadow(
    evidence: UpstreamEvidence,
    market: Literal["KR", "US"],
    sample: OperationalSample,
) -> tuple[str, ...]:
    gate = require_orb_paper(evidence, market)
    if len(gate.enabled_strategy_ids) != 14 \
            or "long_orb_15m" in gate.enabled_strategy_ids:
        raise V15Failure(V15FailureCode.PROMOTION_BLOCKED, "strategy_inventory")
    if sample.official_sessions < 20 or sample.completed_trades < 30 \
            or sample.critical_incidents != 0:
        raise V15Failure(V15FailureCode.PROMOTION_BLOCKED, "shadow_sample")
    return gate.enabled_strategy_ids


def require_router_challenger(
    evidence: UpstreamEvidence,
    market: Literal["KR", "US"],
    orb_paper_event_hash: str,
    registry: RetirementRegistry,
    router_version: str,
) -> MarketGateEvidence:
    gate = require_orb_paper(evidence, market)
    require_active(registry, market, router_version)
    if not orb_paper_event_hash.startswith("sha256:") \
            or gate.router_validation_state != "pass" \
            or gate.router_holdout_state != "pass":
        raise V15Failure(V15FailureCode.PROMOTION_BLOCKED, f"router:{market}")
    if gate.router_validation_gate_hash in {gate.orb_validation_hash,
            gate.orb_holdout_hash} or gate.router_holdout_gate_hash in {
                gate.orb_validation_hash, gate.orb_holdout_hash}:
        raise V15Failure(V15FailureCode.UPSTREAM_EVIDENCE, "router_gate_alias")
    return gate
