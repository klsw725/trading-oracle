from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from src.v4.models import JsonValue

from .canonical import artifact_ref, seal_meta
from .corporate_actions import CorporateActionSnapshot
from .models import ArtifactMeta, ArtifactRef, StrictModel, Symbol, V10ContractError


class PriceAdjustmentSnapshot(StrictModel):
    meta: ArtifactMeta
    symbol: Symbol
    cutoff: datetime
    raw_price: Decimal
    adjusted_indicator_price: Decimal
    execution_price: Decimal
    action_refs: tuple[ArtifactRef, ...]
    execution_layer: Literal["raw"]


def build_price_layers(symbol: Symbol, cutoff: datetime, raw_price: Decimal,
                       actions: tuple[CorporateActionSnapshot, ...]) -> PriceAdjustmentSnapshot:
    available = tuple(action for action in actions if action.observed_at <= cutoff)
    factor = Decimal(1)
    for action in available:
        factor *= action.adjustment_factor
    adjusted = raw_price * factor
    body: JsonValue = {"symbol": symbol, "cutoff": cutoff.isoformat(), "raw_price": str(raw_price),
                       "adjusted_indicator_price": str(adjusted), "execution_price": str(raw_price),
                       "action_refs": [artifact_ref("action", action).model_dump(mode="json") for action in available],
                       "execution_layer": "raw"}
    return PriceAdjustmentSnapshot(meta=seal_meta("price_adjustment_snapshot", body), symbol=symbol,
        cutoff=cutoff, raw_price=raw_price, adjusted_indicator_price=adjusted,
        execution_price=raw_price, action_refs=tuple(artifact_ref("action", action) for action in available),
        execution_layer="raw")


def verify_execution_price(snapshot: PriceAdjustmentSnapshot, fill_price: Decimal) -> None:
    if fill_price != snapshot.raw_price:
        raise V10ContractError("V10_PRICE_LAYER_MISMATCH", str(fill_price))
