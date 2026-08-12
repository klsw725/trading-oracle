from __future__ import annotations

from decimal import Decimal
from math import sqrt

from src.v4.models import JsonValue

from .canonical import canonical_hash, decimal_value, money
from .identity import intent_id
from .models import Account, Decision, GateInputs, GateResult, Reservation, RiskIncident, RiskResult, Side


def correlation(left: tuple[str, ...], right: tuple[str, ...]) -> Decimal | None:
    if len(left) != 20 or len(right) != 20:
        return None
    x = tuple(decimal_value(item) for item in left)
    y = tuple(decimal_value(item) for item in right)
    mean_x = sum(x) / Decimal(20)
    mean_y = sum(y) / Decimal(20)
    covariance = sum((a - mean_x) * (b - mean_y) for a, b in zip(x, y, strict=True))
    variance_x = sum((a - mean_x) ** 2 for a in x)
    variance_y = sum((b - mean_y) ** 2 for b in y)
    if variance_x == 0 or variance_y == 0:
        return None
    return covariance / Decimal(str(sqrt(float(variance_x * variance_y))))


def check_risk(account: Account, decision: Decision, quantity: int, reference_price: str,
               candidate_returns: tuple[str, ...] | None,
               existing_returns: dict[str, tuple[str, ...]] | None = None,
               gates: GateInputs | None = None, expected_cost: str = "0") -> RiskResult:
    inputs = gates or GateInputs(eligible=True, session_open=True, data_fresh=True,
        borrow_allowed=True, liquidity_allowed=True, daily_loss_halted=account.halted,
        execution_halted=False)
    notional = Decimal(quantity) * decimal_value(reference_price)
    gate_results, reason = _evaluate_gates(account, decision, quantity, notional,
                                           decimal_value(expected_cost), candidate_returns,
                                           existing_returns or {}, inputs)
    payload: JsonValue = {"decision_id": decision.decision_id, "quantity": quantity,
        "reference_price": reference_price, "expected_cost": expected_cost,
        "account": account.model_dump(mode="json"), "gates": inputs.model_dump(mode="json")}
    if reason != "RISK_ACCEPTED":
        return RiskResult(decision_id=decision.decision_id, state="blocked", reason_code=reason,
            input_hash=canonical_hash(payload), quantity=quantity, reference_price=reference_price,
            target_notional=money(notional), reservation=None, gates=gate_results)
    cost = decimal_value(expected_cost)
    reserved = notional + cost
    signed = notional if decision.side is Side.LONG else -notional
    reservation = Reservation(intent_id=intent_id(decision),
        cash=money(reserved) if decision.side is Side.LONG else "0",
        collateral=money(reserved) if decision.side is Side.SHORT else "0",
        gross=money(notional), net=money(signed), sector=decision.sector,
        expected_cost=expected_cost)
    return RiskResult(decision_id=decision.decision_id, state="accepted",
        reason_code="RISK_ACCEPTED", input_hash=canonical_hash(payload), quantity=quantity,
        reference_price=reference_price, target_notional=money(notional),
        reservation=reservation, gates=gate_results)


def _evaluate_gates(account: Account, decision: Decision, quantity: int, notional: Decimal,
                    expected_cost: Decimal,
                    candidate_returns: tuple[str, ...] | None,
                    existing_returns: dict[str, tuple[str, ...]],
                    inputs: GateInputs) -> tuple[tuple[GateResult, ...], str]:
    nav = decimal_value(account.prior_close_nav)
    gross = sum((decimal_value(item.mark_price) * item.quantity for item in account.positions), Decimal(0))
    gross += sum((decimal_value(item.gross) for item in account.reservations), Decimal(0))
    net = sum(((decimal_value(item.mark_price) * item.quantity) *
               (1 if item.side is Side.LONG else -1) for item in account.positions), Decimal(0))
    net += sum((decimal_value(item.net) for item in account.reservations), Decimal(0))
    sector = sum((decimal_value(item.mark_price) * item.quantity for item in account.positions
                  if item.sector == decision.sector), Decimal(0))
    sector += sum((decimal_value(item.gross) for item in account.reservations
                  if item.sector == decision.sector), Decimal(0))
    signed = notional if decision.side is Side.LONG else -notional
    available = decimal_value(account.cash) - sum((decimal_value(item.cash) +
        decimal_value(item.collateral) for item in account.reservations), Decimal(0))
    correlations = tuple(correlation(candidate_returns, existing_returns[position.symbol])
        if candidate_returns is not None and position.symbol in existing_returns else None
        for position in account.positions)
    correlation_ok = not account.positions or all(item is not None and abs(item) <= Decimal("0.7")
                                                   for item in correlations)
    correlation_code = ("CORRELATION_UNKNOWN" if any(item is None for item in correlations)
                        else "CORRELATION_HIGH")
    exposure_drift = gross > nav * Decimal("0.20") or not -nav * Decimal("0.10") <= net <= nav * Decimal("0.10")
    checks = (("eligibility", inputs.eligible, "ELIGIBILITY_BLOCKED"),
        ("market_session", inputs.session_open, "MARKET_SESSION_BLOCKED"),
        ("data_freshness", inputs.data_fresh, "DATA_STALE"),
        ("borrow_regulation", inputs.borrow_allowed or decision.side is Side.LONG, "SHORT_BLOCKED"),
        ("position_count", len(account.positions) + len(account.reservations) < 10, "POSITION_LIMIT"),
        ("single_name", quantity > 0 and notional <= nav * Decimal("0.02"), "SINGLE_NAME_LIMIT"),
        ("sector", sector + notional <= nav * Decimal("0.06"), "SECTOR_LIMIT"),
        ("correlation", correlation_ok, correlation_code),
        ("gross_net", gross + notional <= nav * Decimal("0.20") and
         -nav * Decimal("0.10") <= net + signed <= nav * Decimal("0.10"), "EXPOSURE_LIMIT"),
        ("liquidity", inputs.liquidity_allowed and quantity > 0, "NO_ORDER_LIQUIDITY"),
        ("daily_loss_halt", not inputs.daily_loss_halted, "DAILY_LOSS_HALT"),
        ("execution_halt", not inputs.execution_halted, "EXECUTION_HALT"),
        ("accounting", inputs.accounting_consistent, "ACCOUNTING_MISMATCH"),
        ("exposure_drift", not exposure_drift, "EXPOSURE_DRIFT"),
        ("reservation", notional + expected_cost <= available, "RESERVATION_LIMIT"))
    results: list[GateResult] = []
    blocked = False
    reason = "RISK_ACCEPTED"
    for name, passed, code in checks:
        if blocked:
            results.append(GateResult(gate=name, state="not_evaluated", reason_code="PRIOR_GATE_BLOCKED"))
        elif passed:
            results.append(GateResult(gate=name, state="pass", reason_code="PASS"))
        else:
            results.append(GateResult(gate=name, state="blocked", reason_code=code))
            blocked = True
            reason = code
    return tuple(results), reason


def risk_incidents(account: Account, accounting_consistent: bool) -> tuple[RiskIncident, ...]:
    nav = decimal_value(account.prior_close_nav)
    gross = sum((decimal_value(item.mark_price) * item.quantity for item in account.positions), Decimal(0))
    net = sum(((decimal_value(item.mark_price) * item.quantity) *
        (1 if item.side is Side.LONG else -1) for item in account.positions), Decimal(0))
    body: JsonValue = {"market": account.market.value, "gross": money(gross), "net": money(net),
                       "accounting_consistent": accounting_consistent}
    incidents: list[RiskIncident] = []
    if gross > nav * Decimal("0.20") or not -nav * Decimal("0.10") <= net <= nav * Decimal("0.10"):
        incidents.append(RiskIncident(kind="exposure_drift", market=account.market,
            input_hash=canonical_hash(body), halt_requested=False))
    if not accounting_consistent:
        incidents.append(RiskIncident(kind="accounting_mismatch", market=account.market,
            input_hash=canonical_hash(body), halt_requested=True))
    return tuple(incidents)
