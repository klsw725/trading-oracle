from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal, ROUND_HALF_UP

from src.v8.event_models import (
    AccountOpenedEvent,
    CorporateActionEvent,
    CorrectionEvent,
    FeeModelEvent,
    FillEvent,
    FillSummary,
    LedgerEvent,
    OrderEvent,
    PositionEvent,
    PositionSummary,
    RecommendationEvent,
    ReconciledEvent,
)
from src.v8.identity import deterministic_id
from src.v8.models import FailureCode, FeeModel

CENT = Decimal("0.01")


@dataclass(frozen=True, slots=True)
class PositionState:
    position_id: str
    ticker: str
    currency: str
    quantity: Decimal
    avg_price: Decimal
    cost_basis: Decimal
    realized_pnl: Decimal


@dataclass(frozen=True, slots=True)
class ReplaySnapshot:
    cash: dict[str, Decimal]
    positions: tuple[PositionState, ...]
    fills: tuple[FillSummary, ...]
    errors: tuple[FailureCode, ...]


def _money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _fill_position(
    event: FillEvent,
    currency: str,
    current: PositionState | None,
) -> PositionState | None:
    payload = event.payload
    position_id = deterministic_id(
        "ppos_v8_",
        {
            "paper_namespace": event.paper_namespace,
            "ticker": payload.ticker,
            "currency": currency,
        },
    )
    prior = current or PositionState(
        position_id, payload.ticker, currency, Decimal(0), Decimal(0), Decimal(0), Decimal(0)
    )
    match payload.side:  # noqa: MATCH_OK - Side literals are exhaustively handled
        case "BUY":
            quantity = prior.quantity + payload.quantity
            cost_basis = prior.cost_basis + payload.gross_notional
            return replace(
                prior,
                quantity=quantity,
                avg_price=cost_basis / quantity,
                cost_basis=cost_basis,
            )
        case "SELL":
            if payload.quantity > prior.quantity:
                return None
            quantity = prior.quantity - payload.quantity
            removed_cost = prior.avg_price * payload.quantity
            return replace(
                prior,
                quantity=quantity,
                avg_price=prior.avg_price if quantity else Decimal(0),
                cost_basis=prior.cost_basis - removed_cost,
                realized_pnl=prior.realized_pnl
                + payload.gross_notional
                - removed_cost
                - payload.fee
                - (payload.tax or Decimal(0)),
            )


def _corporate_action(
    event: CorporateActionEvent,
    positions: dict[str, PositionState],
    cash: dict[str, Decimal],
) -> bool:
    payload = event.payload
    current = positions.get(payload.ticker)
    if current is None or not payload.source_hash.startswith("sha256:"):
        return False
    match payload.action:  # noqa: MATCH_OK - action literals are exhaustively handled
        case "split" | "reverse_split":
            if payload.ratio_numerator is None or payload.ratio_denominator is None:
                return False
            ratio = payload.ratio_numerator / payload.ratio_denominator
            positions[payload.ticker] = replace(
                current,
                quantity=current.quantity * ratio,
                avg_price=current.avg_price / ratio,
            )
        case "cash_dividend":
            if payload.amount_per_share is None:
                return False
            cash[current.currency] = cash.get(current.currency, Decimal(0)) + _money(
                payload.amount_per_share * current.quantity
            )
        case "symbol_change":
            if payload.new_ticker is None:
                return False
            del positions[payload.ticker]
            positions[payload.new_ticker] = replace(current, ticker=payload.new_ticker)
    return True


def replay_events(
    events: tuple[LedgerEvent, ...], opening_fee_model: FeeModel
) -> ReplaySnapshot:
    cash: dict[str, Decimal] = {}
    positions: dict[str, PositionState] = {}
    fills: list[FillSummary] = []
    errors: list[FailureCode] = []
    fee_model = opening_fee_model
    for event in events:
        match event:  # noqa: MATCH_OK - LedgerEvent union is exhaustively handled
            case AccountOpenedEvent(payload=payload):
                cash = dict(payload.cash)
                positions = {
                    item.ticker: PositionState(
                        item.paper_position_id,
                        item.ticker,
                        fee_model.currency,
                        item.quantity,
                        item.avg_price,
                        item.cost_basis,
                        Decimal(0),
                    )
                    for item in payload.positions
                }
            case RecommendationEvent() | OrderEvent() | CorrectionEvent():
                continue
            case FillEvent(payload=payload):
                gross = _money(payload.quantity * payload.fill_price)
                fee = _money(gross * fee_model.fee_bps / Decimal(10_000))
                expected_tax = (
                    _money(gross * fee_model.sell_tax_bps / Decimal(10_000))
                    if payload.side == "SELL"
                    else Decimal("0.00")
                )
                actual_tax = payload.tax or Decimal("0.00")
                net = (
                    -(gross + fee)
                    if payload.side == "BUY"
                    else gross - fee - expected_tax
                )
                if (payload.gross_notional, payload.fee, actual_tax, payload.net_cash_delta) != (
                    gross,
                    fee,
                    expected_tax,
                    net,
                ):
                    errors.append(FailureCode.FEE_MISMATCH)
                currency = fee_model.currency
                cash[currency] = cash.get(currency, Decimal(0)) + payload.net_cash_delta
                updated = _fill_position(
                    event, currency, positions.get(payload.ticker)
                )
                if updated is None:
                    errors.append(FailureCode.POSITION_MISMATCH)
                else:
                    positions[payload.ticker] = updated
                fills.append(
                    FillSummary(
                        paper_fill_id=payload.paper_fill_id,
                        gross_notional=payload.gross_notional,
                        fee=payload.fee,
                        net_cash_delta=payload.net_cash_delta,
                    )
                )
            case PositionEvent(payload=payload):
                current = positions.get(payload.ticker)
                if current is None or (
                    current.position_id,
                    current.quantity,
                    current.avg_price,
                    current.cost_basis,
                ) != (
                    payload.paper_position_id,
                    payload.quantity,
                    payload.avg_price,
                    payload.cost_basis,
                ):
                    errors.append(FailureCode.POSITION_MISMATCH)
                if payload.cash_after != cash:
                    errors.append(FailureCode.CASH_MISMATCH)
            case CorporateActionEvent():
                if not _corporate_action(event, positions, cash):
                    errors.append(FailureCode.STALE_STATE)
            case FeeModelEvent(payload=payload):
                fee_model = FeeModel(
                    currency=payload.currency,
                    fee_bps=payload.fee_bps,
                    sell_tax_bps=payload.sell_tax_bps,
                    rounding=payload.rounding,
                )
            case ReconciledEvent(payload=payload):
                if payload.replayed_cash != cash or payload.mismatch_count != 0:
                    errors.append(FailureCode.CASH_MISMATCH)
    return ReplaySnapshot(
        cash,
        tuple(sorted(positions.values(), key=lambda item: item.position_id)),
        tuple(fills),
        tuple(dict.fromkeys(errors)),
    )


def position_summaries(snapshot: ReplaySnapshot) -> tuple[PositionSummary, ...]:
    return tuple(
        PositionSummary(
            paper_position_id=position.position_id,
            ticker=position.ticker,
            quantity=position.quantity,
            avg_price=_money(position.avg_price),
            cost_basis=_money(position.cost_basis),
        )
        for position in snapshot.positions
    )
