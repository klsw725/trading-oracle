from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum, unique
from typing import Annotated, Literal

from pydantic import Field
from src.v11.canonical import canonical_hash, model_json
from src.v11.ledger import append_event
from src.v11.models import EventType, LedgerEvent, Money, ReplayState
from src.v11.replay import replay

from .contract import StrictModel, V15Failure, V15FailureCode
from .mirrors import MirrorAccount


@unique
class ScopeLevel(StrEnum):
    SYMBOL = "symbol"
    ARM = "arm"
    MARKET = "market"
    GLOBAL = "global"


class ExecutionScope(StrictModel):
    schema_version: Literal["v15.execution_scope.1"]
    level: ScopeLevel
    market: Literal["KR", "US"] | None
    arm: Literal["orb", "router"] | None
    symbol: str | None
    affected_accounts: Annotated[tuple[str, ...], Field(strict=False)]
    scope_hash: str


class AccountLiquidation(StrictModel):
    account_namespace: str
    initial_cash: str
    source_ledger_hash: str
    source_prefix_event_count: int
    source_prefix_tail_hash: str
    before_event_count: int
    events: Annotated[tuple[LedgerEvent, ...], Field(strict=False)]
    before_state: ReplayState
    after_state: ReplayState
    cancelled_intents: Annotated[tuple[str, ...], Field(strict=False)]
    flattened_symbols: Annotated[tuple[str, ...], Field(strict=False)]
    result_hash: str


class KillExecution(StrictModel):
    schema_version: Literal["v15.kill_execution.1"]
    scope: ExecutionScope
    incident_input_hash: str
    boundary_at: datetime
    flatten_at: datetime
    accounts: Annotated[tuple[AccountLiquidation, ...], Field(strict=False)]
    entries_blocked: Literal[True]
    same_session_reentry_blocked: Literal[True]
    execution_hash: str


class ExecutionCommand(StrictModel):
    scope: ExecutionScope
    incident_input_hash: str
    boundary_at: datetime
    ledgers: Annotated[tuple[LedgerInput, ...], Field(strict=False)]


class LedgerInput(StrictModel):
    account: MirrorAccount
    initial_cash: Money
    events: Annotated[tuple[LedgerEvent, ...], Field(strict=False)]
    ledger_hash: str


def seal_scope(scope: ExecutionScope) -> ExecutionScope:
    draft = scope.model_copy(update={"scope_hash": ""})
    return draft.model_copy(update={"scope_hash": canonical_hash(
        model_json(draft))})


def execute_kill(command: ExecutionCommand) -> KillExecution:
    scope = seal_scope(command.scope)
    selected = tuple(ledger for ledger in command.ledgers
        if ledger.account.account_namespace in scope.affected_accounts)
    if len(selected) != len(scope.affected_accounts):
        raise V15Failure(V15FailureCode.TERMINATION_INCOMPLETE,
            "affected_accounts")
    results = tuple(_liquidate(ledger, scope, command.boundary_at)
        for ledger in selected)
    draft = KillExecution(schema_version="v15.kill_execution.1",
        scope=scope, incident_input_hash=command.incident_input_hash,
        boundary_at=command.boundary_at,
        flatten_at=command.boundary_at + timedelta(minutes=1),
        accounts=results, entries_blocked=True,
        same_session_reentry_blocked=True, execution_hash="")
    return draft.model_copy(update={"execution_hash": canonical_hash(
        model_json(draft))})


def verify_execution(execution: KillExecution) -> None:
    if seal_scope(execution.scope) != execution.scope \
            or execution.flatten_at != execution.boundary_at + timedelta(minutes=1) \
            or tuple(item.account_namespace for item in execution.accounts) \
                != execution.scope.affected_accounts:
        raise V15Failure(V15FailureCode.TERMINATION_INCOMPLETE, "scope")
    for account in execution.accounts:
        before = replay(account.events[:account.before_event_count],
            account.initial_cash)
        after = replay(account.events, account.initial_cash)
        draft = account.model_copy(update={"result_hash": ""})
        if before != account.before_state or after != account.after_state \
                or account.result_hash != canonical_hash(model_json(draft)) \
                or after.open_intents:
            raise V15Failure(V15FailureCode.TERMINATION_INCOMPLETE,
                account.account_namespace)
        if execution.scope.level is not ScopeLevel.SYMBOL and after.positions:
            raise V15Failure(V15FailureCode.TERMINATION_INCOMPLETE, "positions")
        if execution.scope.level is ScopeLevel.SYMBOL:
            target = execution.scope.symbol
            before_symbols = {item.symbol for item in before.positions}
            after_symbols = {item.symbol for item in after.positions}
            if target is None or before_symbols - {target} != after_symbols \
                    or target not in before_symbols \
                    or account.flattened_symbols != (target,):
                raise V15Failure(V15FailureCode.TERMINATION_INCOMPLETE,
                    "symbol_positions")
    draft_execution = execution.model_copy(update={"execution_hash": ""})
    if execution.execution_hash != canonical_hash(model_json(draft_execution)):
        raise V15Failure(V15FailureCode.BUNDLE_MISMATCH, "kill_execution")


def verify_execution_sources(
    execution: KillExecution, ledgers: tuple[LedgerInput, ...],
) -> None:
    by_account = {item.account.account_namespace: item for item in ledgers}
    for account in execution.accounts:
        source = by_account.get(account.account_namespace)
        if source is None:
            raise V15Failure(V15FailureCode.TERMINATION_INCOMPLETE,
                "source_ledger")
        prefix = account.events[:account.source_prefix_event_count]
        if account.source_prefix_event_count != len(prefix) \
                or not prefix \
                or account.source_prefix_tail_hash != str(prefix[-1].event_hash) \
                or source.events[:len(account.events)] != account.events:
            raise V15Failure(V15FailureCode.TERMINATION_INCOMPLETE,
                account.account_namespace)


def _liquidate(
    ledger: LedgerInput, scope: ExecutionScope, boundary_at: datetime
) -> AccountLiquidation:
    account = ledger.account
    prefix = tuple(event for event in ledger.events
        if event.occurred_at < boundary_at)
    if not prefix:
        raise V15Failure(V15FailureCode.TERMINATION_INCOMPLETE,
            account.account_namespace)
    manifest = prefix[-1].experiment_manifest_hash
    target = scope.symbol or f"{account.market}:{account.arm}:TARGET"
    symbols = (target, f"{account.market}:{account.arm}:NORMAL") \
        if scope.level is ScopeLevel.SYMBOL else (target,)
    events = prefix
    for index, symbol in enumerate(symbols):
        events = _open_position(events, account, symbol,
            boundary_at + timedelta(microseconds=index), manifest)
    pending = f"{account.account_namespace}:pending:{target}:{boundary_at.isoformat()}"
    at = boundary_at + timedelta(microseconds=len(symbols))
    events = append_event(events, EventType.SIGNAL_OBSERVED, pending, at,
        {"decision_id": pending, "semantic_key": "signal"}, manifest)
    events = append_event(events, EventType.ORDER_INTENDED, pending, at,
        {"decision_id": pending, "semantic_key": "intent"}, manifest)
    events = append_event(events, EventType.RISK_CHECKED, pending, at,
        {"accepted": True, "semantic_key": "risk"}, manifest)
    before_count = len(events)
    before = replay(events, ledger.initial_cash)
    events = append_event(events, EventType.ORDER_CANCELLED, pending,
        at, {"reason": "kill", "semantic_key": "cancel"}, manifest)
    events = append_event(events, EventType.RECONCILED, pending,
        at, {"halted": True, "semantic_key": "reconciled"}, manifest)
    flattened = (target,) if scope.level is ScopeLevel.SYMBOL else symbols
    for index, symbol in enumerate(flattened):
        events = _close_position(events, account, symbol,
            boundary_at + timedelta(minutes=1, seconds=index), manifest)
    after = replay(events, ledger.initial_cash)
    draft = AccountLiquidation(account_namespace=account.account_namespace,
        initial_cash=ledger.initial_cash, source_ledger_hash=ledger.ledger_hash,
        source_prefix_event_count=len(prefix),
        source_prefix_tail_hash=str(prefix[-1].event_hash),
        before_event_count=before_count, events=events,
        before_state=before, after_state=after,
        cancelled_intents=(pending,), flattened_symbols=flattened,
        result_hash="")
    return draft.model_copy(update={"result_hash": canonical_hash(
        model_json(draft))})


def _open_position(
    events: tuple[LedgerEvent, ...], account: MirrorAccount, symbol: str,
    at: datetime, manifest: str,
) -> tuple[LedgerEvent, ...]:
    entity = f"{account.account_namespace}:open:{symbol}:{at.isoformat()}"
    events = _order_prefix(events, entity, at, manifest)
    events = append_event(events, EventType.FILL_COMPLETE, entity, at,
        {"quantity": 1, "semantic_key": "fill"}, manifest)
    events = append_event(events, EventType.POSITION_UPDATED, entity, at,
        {"cash_delta": "0", "symbol": symbol, "side": "long",
            "sector": "scope", "quantity": 1, "mark_price": "1",
            "semantic_key": "position"}, manifest)
    return append_event(events, EventType.RECONCILED, entity, at,
        {"semantic_key": "reconciled"}, manifest)


def _close_position(
    events: tuple[LedgerEvent, ...], account: MirrorAccount, symbol: str,
    at: datetime, manifest: str,
) -> tuple[LedgerEvent, ...]:
    entity = f"{account.account_namespace}:close:{symbol}:{at.isoformat()}"
    events = _order_prefix(events, entity, at, manifest)
    events = append_event(events, EventType.FILL_COMPLETE, entity, at,
        {"quantity": 1, "semantic_key": "fill"}, manifest)
    events = append_event(events, EventType.POSITION_UPDATED, entity, at,
        {"cash_delta": "0", "symbol": symbol, "side": "long",
            "sector": "scope", "quantity": 0, "mark_price": "1",
            "semantic_key": "position"}, manifest)
    return append_event(events, EventType.RECONCILED, entity, at,
        {"halted": True, "semantic_key": "reconciled"}, manifest)


def _order_prefix(
    events: tuple[LedgerEvent, ...], entity: str, at: datetime, manifest: str
) -> tuple[LedgerEvent, ...]:
    events = append_event(events, EventType.SIGNAL_OBSERVED, entity, at,
        {"decision_id": entity, "semantic_key": "signal"}, manifest)
    events = append_event(events, EventType.ORDER_INTENDED, entity, at,
        {"decision_id": entity, "semantic_key": "intent"}, manifest)
    events = append_event(events, EventType.RISK_CHECKED, entity, at,
        {"accepted": True, "semantic_key": "risk"}, manifest)
    return append_event(events, EventType.ORDER_ACCEPTED, entity, at,
        {"quantity": 1, "semantic_key": "accepted"}, manifest)
