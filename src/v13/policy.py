from __future__ import annotations

from decimal import Decimal
from typing import Final

from src.v11.canonical import canonical_hash, money
from src.v4.models import JsonValue

from src.v13.models import RouterPolicy, V13ContractError


MINIMUM_SCORES: Final = (Decimal("0.70"), Decimal("0.80"), Decimal("0.90"))
MINIMUM_GAPS: Final = (Decimal("0.05"), Decimal("0.10"))


def build_policy(
    minimum_score: Decimal | None = None,
    minimum_gap: Decimal | None = None,
) -> RouterPolicy:
    minimum_score = minimum_score or Decimal("0.80")
    minimum_gap = minimum_gap or Decimal("0.05")
    if minimum_score not in MINIMUM_SCORES or minimum_gap not in MINIMUM_GAPS:
        raise V13ContractError(
            "V13_ROUTER_POLICY", f"{minimum_score}:{minimum_gap}"
        )
    body: JsonValue = {
        "schema_version": "v13.router_policy.1",
        "minimum_score": money(minimum_score),
        "minimum_gap": money(minimum_gap),
    }
    return RouterPolicy(
        schema_version="v13.router_policy.1",
        minimum_score=minimum_score,
        minimum_gap=minimum_gap,
        policy_hash=canonical_hash(body),
    )


def policy_grid() -> tuple[RouterPolicy, ...]:
    return tuple(
        build_policy(score, gap)
        for score in MINIMUM_SCORES
        for gap in MINIMUM_GAPS
    )
