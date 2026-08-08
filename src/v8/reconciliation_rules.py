from __future__ import annotations

from decimal import Decimal

from src.v8.reconciliation_models import (
    BrokerTruth,
    ExecutionOrder,
    HappyFixture,
    ReconciliationErrorCode,
)


def status_error(truth: BrokerTruth) -> ReconciliationErrorCode | None:
    original = truth.original_quantity
    filled = truth.cumulative_filled_quantity
    remaining = truth.remaining_quantity
    if filled + remaining != original:
        return ReconciliationErrorCode.BROKER_TRUTH_CONTRADICTION
    match truth.order_status:  # noqa: MATCH_OK - OrderStatus is exhaustively handled
        case "submitted":
            valid = filled == 0 and remaining == original
        case "accepted":
            valid = (
                filled == 0
                and remaining == original
                and truth.accepted_at is not None
            )
        case "partial":
            valid = Decimal(0) < filled < original and remaining > 0
        case "filled":
            valid = (
                filled == original
                and remaining == 0
                and truth.terminal_fill_at is not None
            )
        case "cancelled":
            valid = truth.cancelled_at is not None and filled <= original
        case "rejected":
            valid = (
                filled == 0
                and truth.reject_code is not None
                and truth.rejected_at is not None
            )
        case "unknown":
            valid = False
    return None if valid else ReconciliationErrorCode.BROKER_TRUTH_CONTRADICTION


def truth_error(
    order: ExecutionOrder, truth: BrokerTruth, as_of_is_fresh: bool
) -> ReconciliationErrorCode | None:
    if (
        truth.broker_order_ref_hash != order.broker_order_ref_hash
        or truth.ticker != order.ticker
        or truth.side != order.side
        or truth.currency != order.currency
        or truth.original_quantity != order.quantity
    ):
        return ReconciliationErrorCode.BROKER_TRUTH_CONTRADICTION
    contradiction = status_error(truth)
    if contradiction is not None:
        return contradiction
    if (
        truth.observed_at.tzinfo is None
        or truth.truth_fresh_until.tzinfo is None
        or truth.observed_at > truth.truth_fresh_until
        or not as_of_is_fresh
    ):
        return ReconciliationErrorCode.STALE_BROKER_TRUTH
    return None


def accounting_error(
    fixture: HappyFixture, truth: BrokerTruth
) -> ReconciliationErrorCode | None:
    fills = truth.fill_fragments
    if len({fill.sequence for fill in fills}) != len(fills):
        return ReconciliationErrorCode.DUPLICATE_FILL_FRAGMENT
    if sum((fill.quantity for fill in fills), Decimal(0)) != truth.cumulative_filled_quantity:
        return ReconciliationErrorCode.FILL_QUANTITY_MISMATCH
    for fill in fills:
        if fill.gross_notional != fill.quantity * fill.price:
            return ReconciliationErrorCode.CASH_MISMATCH
    gross = sum((fill.gross_notional for fill in fills), Decimal(0))
    fee = sum((fill.fee for fill in fills), Decimal(0))
    tax = sum((fill.tax for fill in fills), Decimal(0))
    if fee != truth.fee_total or tax != truth.tax_total:
        return ReconciliationErrorCode.CASH_MISMATCH
    is_buy = truth.side == "BUY"
    delta = -(gross + fee + tax) if is_buy else gross - fee - tax
    claimed = fixture.portfolio_delta
    currency = truth.currency
    if (
        claimed.cash_delta.get(currency) != delta
        or claimed.cash_before.get(currency, Decimal(0)) + delta
        != claimed.cash_after.get(currency)
    ):
        return ReconciliationErrorCode.CASH_MISMATCH
    expected_quantity = truth.cumulative_filled_quantity if is_buy else -truth.cumulative_filled_quantity
    expected_cost = gross if is_buy else -gross
    if (
        claimed.position_delta.ticker != truth.ticker
        or claimed.position_delta.quantity_delta != expected_quantity
        or claimed.position_delta.cost_basis_delta != expected_cost
    ):
        return ReconciliationErrorCode.POSITION_MISMATCH
    return None
