from __future__ import annotations

from src.v4.models import canonical_json

from .artifacts import TradeAttribution
from .bundle import ArtifactBundle
from .integrity import verify_attribution
from .models import CohortFixture, V12ContractError
from .verifier import verify_bundle


def replay(payload: bytes, strategy_id: str, parameter_set_id: str) -> TradeAttribution:
    first = verify_bundle(payload)
    second = verify_bundle(canonical_json(first.model_dump(mode="json")))
    if first != second:
        raise V12ContractError("V12_REPLAY_NONDETERMINISTIC", strategy_id)
    trade = _trade(first, strategy_id, parameter_set_id)
    fixture = CohortFixture.model_validate(first.source_fixture)
    verify_attribution(trade, fixture.execution.account)
    first_bytes = canonical_json(trade.model_dump(mode="json"))
    second_bytes = canonical_json(_trade(second, strategy_id, parameter_set_id).model_dump(mode="json"))
    if first_bytes != second_bytes:
        raise V12ContractError("V12_REPLAY_NONDETERMINISTIC", strategy_id)
    return trade


def _trade(bundle: ArtifactBundle, strategy_id: str,
           parameter_set_id: str) -> TradeAttribution:
    matches = tuple(item for item in bundle.run.trades
                    if item.manifest.strategy_id == strategy_id
                    and item.manifest.active_parameter_set_id == parameter_set_id)
    match matches:
        case (trade,):
            return trade
        case _:
            raise V12ContractError("V12_ARM_NOT_FOUND", f"{strategy_id}:{parameter_set_id}")
