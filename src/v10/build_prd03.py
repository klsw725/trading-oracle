from __future__ import annotations

from decimal import Decimal

from pydantic import ValidationError

from src.v4.models import JsonValue

from .bundle import seal_bundle
from .canonical import model_json, seal_meta
from .corporate_actions import CorporateActionSnapshot
from .eligibility import block_eligibility
from .fixture_models import Prd03Fixture
from .models import V10ContractError
from .price_layers import build_price_layers, verify_execution_price
from .probe_runner import error_probe, outcome_probe
from .universe import assert_membership_frozen, build_universe


def build(value: JsonValue) -> JsonValue:
    try:
        fixture = Prd03Fixture.model_validate(value)
    except ValidationError as error:
        raise V10ContractError("V10_FIXTURE_ERROR", str(error)) from error
    candidates = _candidates(fixture)
    universe = build_universe(candidates, fixture.ranking_date, fixture.effective_date, fixture.market)
    us_candidates = _candidates(fixture, fixture.secondary_symbol_prefix)
    us_universe = build_universe(us_candidates, fixture.ranking_date, fixture.effective_date,
                                 fixture.secondary_market)
    blocked_symbol = universe.members[fixture.eligibility.blocked_index].symbol
    eligibility = block_eligibility(fixture.market, blocked_symbol,
                                    fixture.eligibility.effective_at, fixture.eligibility.reason)
    action = _action(fixture)
    price = build_price_layers(action.symbol, fixture.price.cutoff, fixture.price.raw_price, (action,))
    proposed = tuple(item.symbol for item in universe.members[1:])
    probes = (
        error_probe("future_universe", "V10_UNIVERSE_LOOKAHEAD",
                    lambda: build_universe(candidates, fixture.ranking_date, fixture.ranking_date, fixture.market)),
        error_probe("replacement_member", "V10_UNIVERSE_NOT_FROZEN",
                    lambda: assert_membership_frozen(universe, proposed)),
        outcome_probe("excluded_instrument", "excluded_instrument",
                      next(item.reason for item in universe.exclusions if item.reason == "excluded_instrument")),
        outcome_probe("insufficient_history", "insufficient_history",
                      next(item.reason for item in universe.exclusions if item.reason == "insufficient_history")),
        outcome_probe("independent_markets", fixture.secondary_market.value, us_universe.market.value),
        error_probe("adjusted_execution", "V10_PRICE_LAYER_MISMATCH",
                    lambda: verify_execution_price(price, price.adjusted_indicator_price)),
        error_probe("corporate_action_unknown", "V10_CORPORATE_ACTION_UNKNOWN", _unknown_action),
    )
    artifacts = tuple(model_json(item) for item in (universe, us_universe, eligibility, action, price))
    return seal_bundle(3, value, artifacts, probes)


def _candidates(fixture: Prd03Fixture, prefix: str | None = None) -> JsonValue:
    seed = fixture.candidate_seed
    overrides = {item.index: item for item in seed.overrides}
    result: list[JsonValue] = []
    for index in range(seed.count):
        override = overrides.get(index)
        turnover = seed.first_turnover - seed.turnover_step * Decimal(index)
        turnovers: list[JsonValue] = [str(turnover)] * seed.sessions
        candidate: dict[str, JsonValue] = {"symbol": f"{prefix or seed.symbol_prefix}{index + 1:06d}",
            "instrument_type": "COMMON" if override is None or override.instrument_type is None else override.instrument_type,
            "classification_verified": True,
            "listed_sessions": 20 if override is None or override.listed_sessions is None else override.listed_sessions,
            "halted": False, "turnovers": turnovers}
        result.append(candidate)
    return result


def _action(fixture: Prd03Fixture) -> CorporateActionSnapshot:
    item = fixture.corporate_action
    body: JsonValue = {**item.model_dump(mode="json"), "market": fixture.market.value,
                       "verified": True, "source_refs": []}
    return CorporateActionSnapshot(meta=seal_meta("corporate_action_snapshot", body), market=fixture.market,
        symbol=item.symbol, action_type=item.action_type, effective_at=item.effective_at,
        observed_at=item.observed_at, adjustment_factor=item.adjustment_factor, verified=True, source_refs=())


def _unknown_action() -> None:
    from .corporate_actions import build_action
    _ = build_action({"verified": False})
