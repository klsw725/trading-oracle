from __future__ import annotations

from src.v4.models import JsonValue

from .canonical import canonical_hash
from .models import Decision, IntentId


def intent_id(decision: Decision) -> IntentId:
    identity: JsonValue = {
        "market": decision.market.value,
        "account_arm": f"paper-{decision.market.value.lower()}",
        "cutoff": decision.cutoff.isoformat(),
        "candidate_id": decision.candidate_id,
        "router_decision_id": decision.router_decision_id,
        "decision_id": decision.decision_id,
        "strategy_id": decision.strategy_id,
        "strategy_version": decision.strategy_version,
        "symbol": decision.symbol,
        "side": decision.side.value,
        "action": decision.action,
    }
    return IntentId(f"v11:intent:{canonical_hash(identity).removeprefix('sha256:')}")
