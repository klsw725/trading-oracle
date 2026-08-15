from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from src.v11.costs import freeze_policy
from src.v11.models import Account, CostPolicy, Market, Position, Side
from src.v13.models import ScoredCandidate
from src.v13.models import StrictModel
from src.v13.prd01_fixture import load_fixture
from src.v13.prd03_models import IncumbentSeed, SwitchExecution, SwitchFixture
from src.v13.switch import bind_incumbent, following_minute


FIXTURE_PATH = Path(__file__).parents[2] / "docs/specs/v13/fixtures/prd03-switch-recorded.json"


def load_switch_fixture() -> SwitchFixture:
    return SwitchFixture.model_validate_json(FIXTURE_PATH.read_bytes())


def cost_policy() -> CostPolicy:
    pending = CostPolicy(version="v11.cost.1", policy_hash="sha256:pending",
        effective_session="2026-01-05", prior_hash="sha256:genesis",
        reviewer="risk", approved=True, commission_rate="0.001",
        kr_sell_tax_rate="0.002", spread_rate="0.001",
        slippage_rate="0.001", participation_rate="0.001",
        borrow_rate="0.001", locate_rate="0.001")
    return freeze_policy(pending, "2026-01-05")


class SwitchScenario(StrictModel):
    score: Decimal
    side: Side = Side.LONG
    elapsed_minutes: int = 15
    exit_volume: int = 200
    entry_volume: int = 200
    miss_exit: bool = False
    miss_entry: bool = False
    reject_entry: bool = False


def switch_execution(
    scenario: SwitchScenario, fixture: SwitchFixture | None = None
) -> SwitchExecution:
    fixture = fixture or load_switch_fixture()
    incumbent = Position(symbol=fixture.incumbent.symbol, side=Side.LONG,
        sector="technology", quantity=10, mark_price="100")
    account = Account(market=Market.US, currency="USD", prior_close_nav="100000",
        cash="99000", positions=(incumbent,))
    binding = bind_incumbent(IncumbentSeed(position=incumbent,
        regular_session_id=fixture.session_id,
        candidate_id=fixture.incumbent.candidate_id,
        strategy_id=fixture.incumbent.strategy_id,
        entry_at=fixture.incumbent.entry_at,
        composite_score=fixture.incumbent.composite_score))
    evidence = load_fixture().candidates[0].model_copy(update={"market": Market.US,
        "symbol": incumbent.symbol, "side": scenario.side,
        "candidate_id": f"challenger:{scenario.side.value}",
        "strategy_id": f"challenger-{scenario.side.value}",
        "gates": load_fixture().candidates[0].gates.model_copy(
            update={"eligible": not scenario.reject_entry})})
    challenger = ScoredCandidate(evidence=evidence,
        deterministic_percentile=scenario.score, llm_percentile=scenario.score,
        composite_score=scenario.score, expected_turnover=Decimal("0.01"), quant_only=False)
    evaluated = binding.entry_at + timedelta(minutes=scenario.elapsed_minutes)
    exit_at = following_minute(evaluated)
    entry_at = following_minute(exit_at)
    return SwitchExecution(account=account, incumbent=incumbent, binding=binding,
        challenger=challenger, regular_session_id=fixture.session_id,
        evaluated_at=evaluated, exit_execution_at=None if scenario.miss_exit else exit_at,
        entry_execution_at=None if scenario.miss_entry else entry_at,
        exit_target_volume=scenario.exit_volume, entry_target_volume=scenario.entry_volume,
        cost_policy=cost_policy(), manifest_hash="sha256:v13-prd03")
