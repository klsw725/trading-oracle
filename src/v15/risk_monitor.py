from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from src.v11.canonical import canonical_hash, model_json

from .contract import StrictModel, V15Failure, V15FailureCode
from .liquidation import ExecutionScope


class PnlMark(StrictModel):
    schema_version: Literal["v15.pnl_mark.3"]
    scope: ExecutionScope
    account_namespace: str
    account_state_hash: str
    session: date
    boundary_at: datetime
    ledger_tail_hash: str
    prior_close_nav: Decimal
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    commission: Decimal
    tax: Decimal
    spread: Decimal
    slippage: Decimal
    participation: Decimal
    borrow: Decimal
    locate: Decimal
    other_execution_cost: Decimal
    mark_hash: str


class LossResult(StrictModel):
    schema_version: Literal["v15.loss_result.2"]
    mark_hash: str
    net_pnl: Decimal
    loss_fraction: Decimal
    threshold: Decimal
    triggered: bool
    decision_hash: str


def seal_mark(mark: PnlMark) -> PnlMark:
    draft = mark.model_copy(update={"mark_hash": ""})
    return draft.model_copy(update={"mark_hash": canonical_hash(
        model_json(draft))})


def evaluate_daily_loss(mark: PnlMark) -> LossResult:
    if seal_mark(mark) != mark or mark.prior_close_nav <= 0:
        raise V15Failure(V15FailureCode.LEDGER_EVIDENCE, "pnl_mark")
    costs = (mark.commission + mark.tax + mark.spread + mark.slippage
        + mark.participation + mark.borrow + mark.locate
        + mark.other_execution_cost)
    net_pnl = mark.realized_pnl + mark.unrealized_pnl - costs
    loss_fraction = -net_pnl / mark.prior_close_nav
    draft = LossResult(schema_version="v15.loss_result.2",
        mark_hash=mark.mark_hash, net_pnl=net_pnl,
        loss_fraction=loss_fraction, threshold=Decimal("0.02"),
        triggered=loss_fraction >= Decimal("0.02"), decision_hash="")
    return draft.model_copy(update={"decision_hash": canonical_hash(
        model_json(draft))})
