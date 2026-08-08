from __future__ import annotations

from decimal import Decimal
from typing import Final

from src.v8.risk_json import JsonValue, canonical_hash, deterministic_id, model_json
from src.v8.risk_models import RiskDecision, RiskRequest

_GENESIS: Final = "sha256:genesis"


def source_hashes(request: RiskRequest) -> dict[str, str]:
    inputs = request.inputs
    proposal: JsonValue = {
        "proposed_order_id": request.proposed_order_id,
        "paper_order_id": request.paper_order_id,
        "ticker": request.ticker,
        "side": request.side,
        "quantity": str(request.quantity),
        "currency": request.currency,
        "idempotency_key": request.idempotency_key,
    }
    policy: JsonValue = {
        "max_positions": inputs.position.max_positions,
        "max_weight_pct": str(inputs.position.max_weight_pct),
        "max_sector_weight_pct": str(inputs.concentration.max_sector_weight_pct),
        "pair_threshold": str(inputs.concentration.pair_threshold),
        "halt_threshold_pct": str(inputs.daily_loss.halt_threshold_pct),
    }
    return {
        "proposal": canonical_hash(proposal),
        "portfolio": canonical_hash(
            [model_json(inputs.cash), model_json(inputs.position), model_json(inputs.concentration)]
        ),
        "quote": canonical_hash(model_json(inputs.quote)),
        "calendar": canonical_hash(model_json(inputs.market_hours)),
        "policy": canonical_hash(policy),
        "kill_switch": canonical_hash(model_json(inputs.kill_switch)),
    }


def _blocking_reasons(request: RiskRequest) -> tuple[str, ...]:
    inputs = request.inputs
    switch = inputs.kill_switch
    reasons: list[str] = []
    if not switch.readable or not switch.hash_chain_verified or not switch.coverage_determined:
        return ("kill_switch_unreadable",)
    if switch.switch_status == "active" and request.side in switch.covered_actions:
        return ("kill_switch_active",)
    quote = inputs.quote
    checked_at = inputs.market_hours.checked_at
    if quote.freshness_result == "fresh" and checked_at > quote.quote_expires_at:
        return ("stale_quote_falsely_fresh",)
    market = inputs.market_hours
    if market.is_open and market.holiday:
        return ("market_hours_contradiction",)
    if not market.is_open:
        reasons.append("market_closed")
    if not market.source_hash.startswith("sha256:") or len(market.source_hash) != 71:
        reasons.append("market_calendar_missing")
    if quote.freshness_result == "stale" or checked_at > quote.quote_expires_at:
        reasons.append("stale_quote")
    if (quote.ticker is not None and quote.ticker != request.ticker) or (
        quote.currency is not None and quote.currency != request.currency
    ):
        reasons.append("stale_quote")
    if request.side == "BUY":
        if not request.fee_tax_known:
            reasons.append("fee_tax_unknown")
        if inputs.cash.required_cash > inputs.cash.available_cash_after_floor:
            reasons.append("cash_insufficient")
        if inputs.cash.cash_floor_after_order_pct < inputs.cash.minimum_cash_floor_pct:
            reasons.append("cash_floor_breach")
        if (
            not inputs.position.ticker_already_held
            and inputs.position.current_distinct_positions >= inputs.position.max_positions
        ):
            reasons.append("max_positions_reached")
        if inputs.concentration.sector_weight_after_pct > inputs.concentration.max_sector_weight_pct:
            reasons.append("sector_concentration")
        if inputs.concentration.max_pair_correlation > inputs.concentration.pair_threshold:
            reasons.append("pair_correlation_high")
        if not inputs.concentration.source_complete:
            reasons.append("concentration_source_untrusted")
    if (
        request.risk_increasing_action
        and inputs.position.post_order_weight_pct > inputs.position.max_weight_pct
    ):
        reasons.append("single_name_concentration")
    if request.side == "SELL":
        if not inputs.position.source_trusted:
            reasons.append("position_source_untrusted")
        elif request.quantity > inputs.position.current_quantity:
            reasons.append("position_insufficient")
    calculated_pnl = (
        (inputs.daily_loss.current_equity - inputs.daily_loss.day_start_equity)
        / inputs.daily_loss.day_start_equity
        * Decimal(100)
    )
    if request.risk_increasing_action and (
        calculated_pnl <= inputs.daily_loss.halt_threshold_pct
        or inputs.daily_loss.daily_pnl_pct <= inputs.daily_loss.halt_threshold_pct
    ):
        reasons.append("daily_loss_limit_hit")
    return tuple(dict.fromkeys(reasons))


def evaluate_risk(request: RiskRequest) -> RiskDecision:
    hashes = source_hashes(request)
    blockers = _blocking_reasons(request)
    switch_failure = bool(
        {"kill_switch_active", "kill_switch_unreadable", "stale_quote_falsely_fresh", "market_hours_contradiction"}
        .intersection(blockers)
    )
    risk_status = (
        "kill_switch_active"
        if switch_failure
        else "blocked"
        if blockers
        else "requires_ack"
        if request.ack_required_reasons
        else "allowed"
    )
    hash_values: dict[str, JsonValue] = {key: value for key, value in hashes.items()}
    reason_values: list[JsonValue] = list(blockers)
    seed: dict[str, JsonValue] = {
        "proposed_order_id": request.proposed_order_id,
        "paper_order_id": request.paper_order_id,
        "source_hashes": hash_values,
        "idempotency_key": request.idempotency_key,
        "risk_status": risk_status,
        "blocking_reasons": reason_values,
    }
    decision_id = deterministic_id("risk_v8_", seed)
    allowed = risk_status == "allowed"
    decision = RiskDecision(
        schema_version="v8.risk_controls.decision.1",
        risk_decision_id=decision_id,
        proposed_order_id=request.proposed_order_id,
        paper_order_id=request.paper_order_id,
        ticker=request.ticker,
        side=request.side,
        quantity=request.quantity,
        currency=request.currency,
        estimated_notional=request.estimated_notional,
        estimated_fee=request.estimated_fee,
        estimated_tax=request.estimated_tax,
        risk_status=risk_status,
        blocking_reasons=blockers,
        ack_required_reasons=request.ack_required_reasons,
        source_hashes=hashes,
        idempotency_key=request.idempotency_key,
        prev_record_hash=_GENESIS,
        fail_closed=not allowed,
        next_allowed_destination="broker_dry_run" if allowed else None,
        dry_run_request_allowed=allowed,
        real_order_created=False,
        portfolio_mutated=False,
        record_hash="sha256:pending",
    )
    return decision.model_copy(
        update={"record_hash": canonical_hash(model_json(decision, exclude={"record_hash"}))}
    )
