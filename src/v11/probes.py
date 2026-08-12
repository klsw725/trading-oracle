from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from src.v4.models import canonical_json

from .accounts import create_account
from .costs import execution_costs, verify_stress
from .decisions import intent_is_timely
from .fills import simulate_fill, verify_fill
from .identity import intent_id
from .ledger import append_event, register_intent
from .liquidity import verify_causal_sizing
from .models import CostPolicy, Decision, EventType, GateInputs, Market, OrderAction, Position, Probe, Side
from .reservations import reserve
from .risk import check_risk
from .session_exit import entry_allowed, verify_flat_at_close
from .shorts import short_eligible


def normative_probes() -> tuple[Probe, ...]:
    now = datetime(2026, 1, 5, 0, 0, tzinfo=timezone.utc)
    policy = _policy()
    decision = _decision(now)
    valid_fill = simulate_fill(intent_id(decision), Market.US, Side.LONG, 10, 100, "100", now,
                               policy, OrderAction.BUY)
    events, _ = register_intent((), decision, now, "sha256:manifest")
    duplicate, receipt = register_intent(events, decision, now, "sha256:manifest")
    altered = decision.model_copy(update={"strategy_id": "other"})
    prior_identity = next(item.payload["identity_hash"] for item in events
                          if item.event_type is EventType.ORDER_INTENDED)
    collision_events = append_event((), EventType.SIGNAL_OBSERVED, intent_id(altered), now,
        {"semantic_key": "signal"}, "sha256:manifest")
    collision_events = append_event(collision_events, EventType.ORDER_INTENDED, intent_id(altered), now,
        {"identity_hash": prior_identity}, "sha256:manifest")
    account = create_account(Market.US).model_copy(update={"cash": "2100"})
    first = check_risk(account, decision, 10, "100", None, {}, _gates(), "100")
    reserved = reserve(account, first.reservation) if first.reservation else account
    second = check_risk(reserved, decision.model_copy(update={"decision_id": "d2"}),
                        10, "100", None, {}, _gates(), "100")
    zero_returns = tuple("0" for _ in range(20))
    position_account = create_account(Market.US).model_copy(update={"positions": (
        Position(symbol="MSFT", side=Side.LONG, sector="financial", quantity=1, mark_price="100"),)})
    unknown = check_risk(position_account, decision, 1, "100", zero_returns,
                         {"MSFT": zero_returns}, _gates())
    close = now + timedelta(hours=6)
    values: tuple[tuple[str, Literal[1, 2, 3, 4], bool, str], ...] = (
        ("fractional_quantity", 1, _public_fractional_error(), "QUANTITY_FAILURE"),
        ("future_volume", 2, _error(lambda: verify_causal_sizing(True), "V11_LOOKAHEAD"), "LOOKAHEAD_FAILURE"),
        ("overfill", 2, _error(lambda: verify_fill(valid_fill.model_copy(update={"filled_quantity": 6}), 100),
                               "V11_PARTICIPATION_LIMIT"), "PARTICIPATION_FAILURE"),
        ("carry_remainder", 2, _error(lambda: verify_fill(valid_fill, 100, True),
                                      "V11_STALE_EXECUTION"), "STALE_EXECUTION_FAILURE"),
        ("duplicate_intent", 3, len(duplicate) == len(events) and receipt.state == "no_op", "NO_OP"),
        ("strategy_collision", 3, _error(lambda: register_intent(collision_events, altered, now,
            "sha256:manifest"), "V11_INTENT_IDENTITY_COLLISION"), "IDENTITY_FAILURE"),
        ("unreserved_batch", 1, second.reason_code == "RESERVATION_LIMIT", "RESERVATION_FAILURE"),
        ("ledger_break", 3, _public_bundle_error(),
         "RECONCILIATION_FAILURE_EXECUTION_HALT"),
        ("missing_borrow", 2, not short_eligible(None, now), "SHORT_ELIGIBILITY_FAILURE"),
        ("late_entry", 2, not entry_allowed(close - timedelta(minutes=19), close),
         "MARKET_CLOSE_RISK_FAILURE"),
        ("overnight", 2, _error(lambda: verify_flat_at_close(1, close, None),
                                "V11_OVERNIGHT_POSITION"), "FORCED_LIQUIDATION_FAILURE"),
        ("correlation_unknown", 1, unknown.reason_code == "CORRELATION_UNKNOWN",
         "CORRELATION_GATE_FAILURE"),
    )
    return _passed(values)


def local_probes() -> tuple[Probe, ...]:
    now = datetime(2026, 1, 5, tzinfo=timezone.utc)
    target = now + timedelta(minutes=1)
    missed = not intent_is_timely(target + timedelta(seconds=1), target)
    policy = _policy()
    baseline = execution_costs(policy, Market.US, OrderAction.BUY, "1000")
    stressed = execution_costs(policy, Market.US, OrderAction.BUY, "1000", True)
    mutated = stressed.model_copy(update={"commission": str(float(stressed.commission) * 2)})
    fixed = _error(lambda: verify_stress(baseline, mutated), "V11_FIXED_COST_STRESSED")
    values: tuple[tuple[str, Literal[1, 2, 3, 4], bool, str], ...] = (
        ("missed_boundary", 2, missed, "ORDER_CANCELLED"),
        ("fixed_cost_doubled", 2, fixed, "COST_CONTRACT_FAILURE"))
    return _passed(values)


def _decision(now: datetime) -> Decision:
    return Decision(decision_id="d", candidate_id="c", router_decision_id="r",
        strategy_id="s", strategy_version="1", market=Market.US, symbol="AAPL",
        sector="technology", side=Side.LONG, action="open", cutoff=now,
        watermark_at=now, decision_ready_at=now, deterministic_score="1")


def _gates() -> GateInputs:
    return GateInputs(eligible=True, session_open=True, data_fresh=True, borrow_allowed=True,
        liquidity_allowed=True, daily_loss_halted=False, execution_halted=False)


def _policy() -> CostPolicy:
    return CostPolicy(version="test", policy_hash="sha256:pending", effective_session="2026-01-05",
        prior_hash="sha256:genesis", reviewer="test", approved=True, commission_rate="0.0002",
        kr_sell_tax_rate="0.0018", spread_rate="0.0005", slippage_rate="0.0004",
        participation_rate="0.0003", borrow_rate="0.0001", locate_rate="0.00005")


def _passed(values: tuple[tuple[str, Literal[1, 2, 3, 4], bool, str], ...]) -> tuple[Probe, ...]:
    return tuple(Probe(probe_id=name, owner_prd=owner, state="pass", result_code=code)
                 for name, owner, passed, code in values if passed)


def _public_fractional_error() -> bool:
    from .build import build_fixture
    from .canonical import parse_json
    from .models import V11ContractError
    root = Path(__file__).resolve().parents[2]
    value = parse_json((root / "docs/specs/v11/fixtures/prd02.json").read_bytes())
    if not isinstance(value, dict) or not isinstance(executions := value.get("executions"), list):
        return False
    first = executions[0]
    if not isinstance(first, dict):
        return False
    first["requested_quantity"] = 1.5
    try:
        _ = build_fixture(value)
    except V11ContractError as error:
        return error.code == "V11_FIXTURE_ERROR"
    return False


def _public_bundle_error() -> bool:
    from .build import build_fixture
    from .canonical import parse_json
    from .verifier import verify_bundle
    from .models import V11ContractError
    root = Path(__file__).resolve().parents[2]
    value = build_fixture(parse_json((root / "docs/specs/v11/fixtures/prd03.json").read_bytes()))
    if not isinstance(value, dict) or not isinstance(artifacts := value.get("artifacts"), list):
        return False
    ledger = artifacts[0]
    if not isinstance(ledger, dict) or not isinstance(events := ledger.get("events"), list):
        return False
    event = events[0]
    if not isinstance(event, dict):
        return False
    event["previous_event_hash"] = "sha256:broken"
    try:
        _ = verify_bundle(canonical_json(value))
    except V11ContractError as error:
        return error.code in {"V11_DERIVED_FIELD_MISMATCH", "V11_HASH_MISMATCH"}
    return False


def _error[T](action: Callable[[], T], code: str) -> bool:
    from .models import V11ContractError
    try:
        _ = action()
    except V11ContractError as error:
        return error.code == code
    return False
