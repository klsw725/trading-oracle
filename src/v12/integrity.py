from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from src.v4.models import JsonValue, canonical_json
from src.v11.canonical import canonical_hash, model_json
from src.v11.identity import intent_id
from src.v11.ledger import verify_chain
from src.v11.replay import replay
from src.v11.shorts import borrow_cost
from src.v11.models import EventType
from src.v11.models import Account
from src.v11.sizing import causal_quantity

from .artifacts import Candidate, TradeAttribution
from .models import V12ContractError


def verify_candidate(candidate: Candidate) -> None:
    score = candidate.deterministic_score
    if not Decimal(0) <= score <= Decimal(1) or not score.is_finite():
        raise V12ContractError("V12_SCORE_RANGE", str(score))
    identity: dict[str, JsonValue] = {"market": candidate.market.value,
        "symbol": candidate.symbol, "strategy_id": candidate.strategy_id,
        "strategy_version": candidate.strategy_version,
        "parameter_set_id": candidate.parameter_set_id,
        "cutoff": candidate.signal_cutoff.isoformat()}
    expected = f"v12:candidate:{canonical_hash(identity)[7:]}"
    if candidate.candidate_id != expected:
        raise V12ContractError("V12_IDENTITY_COLLISION", candidate.candidate_id)


def verify_attribution(trade: TradeAttribution, account: Account) -> None:
    verify_candidate(trade.candidate)
    manifest = trade.manifest
    expected_owner = f"shadow/{trade.candidate.market.value}/{trade.candidate.strategy_id}/{trade.candidate.parameter_set_id}"
    expected_arm = f"v12:arm:{trade.candidate.strategy_id}:{trade.candidate.parameter_set_id}"
    if (manifest.owner_namespace != expected_owner or manifest.arm_id != expected_arm
            or manifest.strategy_id != trade.candidate.strategy_id
            or manifest.strategy_version != trade.candidate.strategy_version
            or manifest.active_parameter_set_id != trade.candidate.parameter_set_id):
        raise V12ContractError("V12_ATTRIBUTION_OWNER", manifest.arm_id)
    body: dict[str, JsonValue] = {"arm_id": manifest.arm_id,
        "account_arm_id": manifest.account_arm_id, "owner_namespace": manifest.owner_namespace,
        "strategy_id": manifest.strategy_id, "strategy_version": manifest.strategy_version,
        "active_parameter_set_id": manifest.active_parameter_set_id,
        "source_fixture_hash": manifest.source_fixture_hash,
        "registry_hash": manifest.registry_hash, "cost_policy_hash": manifest.cost_policy_hash}
    if manifest.manifest_hash != canonical_hash(body):
        raise V12ContractError("V12_MANIFEST_HASH", manifest.arm_id)
    decision = trade.decision
    if (decision.candidate_id != trade.candidate.candidate_id
            or decision.strategy_id != trade.candidate.strategy_id
            or decision.strategy_version != trade.candidate.strategy_version
            or decision.market.value != trade.candidate.market.value
            or decision.symbol != trade.candidate.symbol
            or decision.side.value != trade.candidate.side.value):
        raise V12ContractError("V12_ATTRIBUTION_DECISION", manifest.arm_id)
    if trade.v11_intent_id != intent_id(decision) or trade.fill.intent_id != trade.v11_intent_id:
        raise V12ContractError("V12_ATTRIBUTION_INTENT", manifest.arm_id)
    expected_arm_intent = f"v12:intent:{canonical_hash({'arm': manifest.account_arm_id, 'v11': trade.v11_intent_id})[7:]}"
    if trade.arm_intent_id != expected_arm_intent:
        raise V12ContractError("V12_ARM_INTENT", manifest.arm_id)
    if any(event.experiment_manifest_hash != manifest.manifest_hash for event in trade.events):
        raise V12ContractError("V12_EVENT_OWNER", manifest.arm_id)
    verify_chain(trade.events)
    state = replay(trade.events, account.cash)
    if state.positions or state.open_intents:
        raise V12ContractError("V12_REPLAY_NOT_FLAT", manifest.arm_id)
    event_hash = canonical_hash(canonical_json([model_json(item) for item in trade.events]).decode())
    if trade.event_bytes_hash != event_hash:
        raise V12ContractError("V12_EVENT_BYTES", manifest.arm_id)
    if trade.entry_costs != trade.fill.costs:
        raise V12ContractError("V12_ATTRIBUTION_COST", manifest.arm_id)
    _verify_risk_fill(trade, account)
    _verify_entry_events(trade)
    recalled_at = trade.borrow.recalled_at
    risk_kill_at = trade.risk_kill_at
    expected_reason = ("risk_kill" if risk_kill_at is not None else "short_recall"
        if recalled_at is not None else "session_close")
    if (trade.exit_reason != expected_reason
            or recalled_at is not None and (trade.candidate.side.value != "short"
                or not trade.fill.target_at < recalled_at < trade.regular_close)
            or risk_kill_at is not None
                and not trade.fill.target_at < risk_kill_at < trade.regular_close):
        raise V12ContractError("V12_ATTRIBUTION_FORCED_EXIT", manifest.arm_id)
    _verify_exit_events(trade)
    semantic = f"{trade.exit_reason}_signal"
    if not any(event.payload.get("semantic_key") == semantic for event in trade.events):
        raise V12ContractError("V12_ATTRIBUTION_EXIT", manifest.arm_id)
    trade_body: dict[str, JsonValue] = trade.model_dump(mode="json", exclude={"ledger_hash"})
    if trade.ledger_hash != canonical_hash(trade_body):
        raise V12ContractError("V12_LEDGER_HASH", manifest.arm_id)


def _verify_risk_fill(trade: TradeAttribution, account: Account) -> None:
    risk, fill = trade.risk, trade.fill
    reference = str(trade.causal_sizing.close)
    notional = Decimal(risk.quantity) * Decimal(reference)
    reservation = risk.reservation
    quantity, _ = causal_quantity(account, reference,
        tuple(str(value) for value in trade.causal_sizing.prior_turnovers))
    if (risk.decision_id != trade.decision.decision_id or risk.quantity != quantity
            or risk.quantity != fill.requested_quantity
            or Decimal(risk.reference_price) != Decimal(reference)
            or Decimal(risk.target_notional) != notional
            or reservation is None or reservation.intent_id != fill.intent_id
            or Decimal(reservation.gross) != notional
            or Decimal(fill.price) != trade.execution_snapshot.open
            or fill.target_at != trade.execution_snapshot.target_at):
        raise V12ContractError("V12_ATTRIBUTION_RISK_FILL", trade.manifest.arm_id)


def _verify_entry_events(trade: TradeAttribution) -> None:
    entity = trade.fill.intent_id
    events = tuple(item for item in trade.events if item.entity_id == entity)
    semantic = {str(item.payload.get("semantic_key")): item for item in events}
    fill_event = semantic.get("fill")
    position = semantic.get("position")
    cost = semantic.get("cost")
    accepted = semantic.get("accepted")
    if (fill_event is None or position is None or cost is None or accepted is None
            or accepted.payload.get("quantity") != trade.fill.requested_quantity
            or fill_event.payload.get("quantity") != trade.fill.filled_quantity
            or position.payload.get("quantity") != trade.fill.filled_quantity
            or position.payload.get("mark_price") != trade.fill.price
            or cost.payload.get("total") != trade.fill.costs.total):
        raise V12ContractError("V12_ATTRIBUTION_ENTRY_EVENTS", trade.manifest.arm_id)


def _verify_exit_events(trade: TradeAttribution) -> None:
    entity = f"{trade.fill.intent_id}:exit"
    events = tuple(item for item in trade.events if item.entity_id == entity)
    semantic = {str(item.payload.get("semantic_key")): item for item in events}
    prefix = trade.exit_reason
    keys = tuple(f"{prefix}_{name}" for name in
                 ("signal", "intent", "risk", "accepted", "fill", "position", "cost", "reconciled"))
    if any(key not in semantic for key in keys):
        raise V12ContractError("V12_ATTRIBUTION_EXIT", trade.manifest.arm_id)
    signal, intent, risk, accepted, fill, position, cost, reconciled = tuple(
        semantic[key] for key in keys)
    forced_at = trade.risk_kill_at if trade.risk_kill_at is not None else trade.borrow.recalled_at
    signal_at = (trade.regular_close - timedelta(minutes=5)
        if forced_at is None else forced_at)
    fill_at = (trade.regular_close - timedelta(minutes=4)
        if forced_at is None else forced_at.replace(second=0, microsecond=0) + timedelta(minutes=1))
    if (signal.occurred_at != signal_at or intent.occurred_at != signal_at
            or any(item.occurred_at != fill_at for item in (risk, accepted, fill, position))
            or cost.occurred_at <= fill_at or reconciled.occurred_at <= cost.occurred_at
            or fill.payload.get("quantity") != trade.fill.filled_quantity
            or fill.payload.get("price") != trade.fill.price
            or position.payload.get("quantity") != 0
            or cost.event_type is not EventType.COST_ACCRUED):
        raise V12ContractError("V12_ATTRIBUTION_EXIT_TIMELINE", trade.manifest.arm_id)
    holding_days = max(1, (fill_at.date() - trade.fill.target_at.date()).days)
    notional = Decimal(trade.fill.filled_quantity) * Decimal(trade.fill.price)
    expected_borrow = (borrow_cost(str(notional), str(trade.borrow.annual_fee), holding_days)
        if trade.candidate.side.value == "short" else "0")
    if cost.payload.get("borrow_fee") != expected_borrow:
        raise V12ContractError("V12_ATTRIBUTION_BORROW_COST", trade.manifest.arm_id)
