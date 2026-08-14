from __future__ import annotations

from datetime import timedelta

from src.v11.models import Account

from .artifacts import TradeAttribution
from .integrity import verify_attribution
from .models import V12ContractError


def fake_risk_kill(trade: TradeAttribution, account: Account) -> None:
    verify_attribution(trade.model_copy(update={"exit_reason": "risk_kill"}), account)


def ignored_risk_kill(trade: TradeAttribution, account: Account) -> None:
    verify_attribution(trade.model_copy(update={"exit_reason": "session_close"}), account)


def missing_risk_kill(trade: TradeAttribution, account: Account) -> None:
    verify_attribution(trade.model_copy(update={"risk_kill_at": None}), account)


def wrong_risk_kill_time(trade: TradeAttribution, account: Account) -> None:
    risk_kill_at = trade.risk_kill_at
    if risk_kill_at is None:
        raise V12ContractError("V12_PROBE_FAILED", "risk kill missing")
    verify_attribution(trade.model_copy(update={
        "risk_kill_at": risk_kill_at + timedelta(minutes=1)}), account)
