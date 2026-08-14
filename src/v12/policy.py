from __future__ import annotations

from src.v11.costs import freeze_policy
from src.v11.models import CostPolicy


def fixture_policy() -> CostPolicy:
    return freeze_policy(CostPolicy(version="v12.fixture.cost.1", policy_hash="sha256:pending",
        effective_session="2026-01-01", prior_hash="sha256:genesis", reviewer="fixture-reviewer",
        approved=True, commission_rate="0.0001", kr_sell_tax_rate="0.0018",
        spread_rate="0.0002", slippage_rate="0.0003", participation_rate="0.0001",
        borrow_rate="0.0004", locate_rate="0.0001"), "2026-01-02")
