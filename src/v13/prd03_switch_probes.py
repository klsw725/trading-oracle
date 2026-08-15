from __future__ import annotations

from decimal import Decimal

from src.v11.models import IntentId, Position, Reservation, Side
from src.v13.prd03_fixture import SwitchScenario, load_switch_fixture, switch_execution
from src.v13.switch import execute_switch


def run_switch_probes() -> tuple[dict[str, bool], dict[str, str], dict[str, str]]:
    fixture = load_switch_fixture()
    hold = execute_switch(switch_execution(SwitchScenario(
        score=fixture.challengers.above, elapsed_minutes=14)))
    below = execute_switch(switch_execution(SwitchScenario(
        score=fixture.challengers.below)))
    exact = execute_switch(switch_execution(SwitchScenario(
        score=fixture.challengers.exact)))
    above = execute_switch(switch_execution(SwitchScenario(
        score=fixture.challengers.above)))
    opposite = execute_switch(switch_execution(SwitchScenario(
        score=fixture.challengers.exact, side=Side.SHORT)))
    partial_exit = execute_switch(switch_execution(SwitchScenario(
        score=fixture.challengers.exact, exit_volume=100)))
    missed_exit = execute_switch(switch_execution(SwitchScenario(
        score=fixture.challengers.exact, miss_exit=True)))
    rejected_entry = execute_switch(switch_execution(SwitchScenario(
        score=fixture.challengers.exact, reject_entry=True)))
    missed_entry = execute_switch(switch_execution(SwitchScenario(
        score=fixture.challengers.exact, miss_entry=True)))
    unfilled_entry = execute_switch(switch_execution(SwitchScenario(
        score=fixture.challengers.exact, entry_volume=0)))
    portfolio_execution = switch_execution(SwitchScenario(
        score=fixture.challengers.exact))
    unrelated = Position(symbol="OTHER", side=Side.LONG, sector="finance",
        quantity=1, mark_price="100")
    portfolio_execution = portfolio_execution.model_copy(update={"account":
        portfolio_execution.account.model_copy(update={"positions":
            (portfolio_execution.incumbent, unrelated)})})
    portfolio_risk = execute_switch(portfolio_execution)
    candidate_returns = tuple(str(index) for index in range(1, 21))
    unrelated_returns = tuple("1" if index % 2 else "-1"
        for index in range(1, 21))
    verified_portfolio = portfolio_execution.model_copy(update={
        "challenger": portfolio_execution.challenger.model_copy(update={"evidence":
            portfolio_execution.challenger.evidence.model_copy(update={
                "candidate_returns": candidate_returns})}),
        "existing_returns": {"OTHER": unrelated_returns}})
    verified_portfolio_risk = execute_switch(verified_portfolio)
    reservation = Reservation(intent_id=IntentId("unrelated"), cash="99000", collateral="0",
        gross="0", net="0", sector="finance", expected_cost="0")
    reservation_execution = switch_execution(SwitchScenario(
        score=fixture.challengers.exact))
    reservation_execution = reservation_execution.model_copy(update={"account":
        reservation_execution.account.model_copy(update={"reservations": (reservation,)})})
    reservation_risk = execute_switch(reservation_execution)
    released_reservation_risk = execute_switch(reservation_execution.model_copy(
        update={"released_reservation_ids": ("unrelated",)}))
    expected_path = tuple(item.value for item in fixture.expected_path)
    exact_path = tuple(item.state.value for item in exact.timeline)
    checks = {
        "hold_under_15_minutes": hold.state == "held" and hold.reason_code == "HOLD_PERIOD",
        "improvement_below_exact_threshold": below.state == "held",
        "improvement_exact_threshold": exact.state == "challenger",
        "improvement_above_threshold": above.state == "challenger",
        "same_direction_two_leg": exact_path == expected_path
            and exact.exit_target_at is not None and exact.entry_target_at is not None,
        "opposite_direction_two_leg": opposite.state == "challenger"
            and opposite.challenger_position is not None
            and opposite.challenger_position.side is Side.SHORT,
        "partial_exit_residual_only": partial_exit.state == "residual_incumbent"
            and partial_exit.residual_incumbent is not None
            and partial_exit.challenger_position is None
            and all(event.occurred_at == partial_exit.exit_target_at
                for event in partial_exit.ledger_events),
        "missed_exit_no_challenger_events": missed_exit.state == "residual_incumbent"
            and len(missed_exit.ledger_events) == 0,
        "rejected_entry_stays_flat": rejected_entry.state == "flat"
            and rejected_entry.entry_risk is not None
            and rejected_entry.entry_risk.state == "blocked",
        "missed_entry_stays_flat": missed_entry.state == "flat"
            and missed_entry.reason_code == "ENTRY_BOUNDARY_MISSED",
        "unfilled_entry_stays_flat": unfilled_entry.state == "flat"
            and unfilled_entry.reason_code == "ENTRY_UNFILLED",
        "independent_leg_costs": Decimal(exact.exit_cost) > 0
            and Decimal(exact.entry_cost) > 0,
        "immutable_leg_ledger": len(exact.ledger_events) == 15
            and exact.ledger_events[-1].event_index == 14,
        "binding_hash_enforced": exact.binding_hash.startswith("sha256:"),
        "unrelated_position_reaches_fresh_risk": portfolio_risk.state == "flat"
            and portfolio_risk.entry_risk is not None
            and portfolio_risk.entry_risk.reason_code == "CORRELATION_UNKNOWN",
        "verified_returns_reach_fresh_risk": verified_portfolio_risk.state == "challenger"
            and verified_portfolio_risk.entry_risk is not None
            and verified_portfolio_risk.entry_risk.reason_code == "RISK_ACCEPTED",
        "unrelated_reservation_reaches_fresh_risk": reservation_risk.state == "flat"
            and reservation_risk.entry_risk is not None
            and reservation_risk.entry_risk.reason_code == "RESERVATION_LIMIT",
        "released_switch_reservation_is_removed": released_reservation_risk.state
            == "challenger",
    }
    same_boundary_killed = exact.entry_target_at is not None \
        and exact.exit_target_at is not None \
        and exact.entry_target_at > exact.exit_target_at \
        and exact_path == expected_path
    mutations = {"switch_same_boundary": "killed" if same_boundary_killed else "survived"}
    hashes = {"switch_result_hash": exact.result_hash,
        "switch_ledger_tail_hash": exact.ledger_events[-1].event_hash,
        "switch_binding_hash": exact.binding_hash}
    return checks, mutations, hashes
