from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import ValidationError

from src.v4.models import JsonValue

from .canonical import seal_meta
from .models import ArtifactMeta, ArtifactRef, Market, StrictModel, Symbol, V10ContractError


class CorporateActionSnapshot(StrictModel):
    meta: ArtifactMeta
    market: Market
    symbol: Symbol
    action_type: Literal["split", "reverse_split", "dividend", "rights"]
    effective_at: datetime
    observed_at: datetime
    adjustment_factor: Decimal
    verified: Literal[True]
    source_refs: tuple[ArtifactRef, ...]


def build_action(value: JsonValue) -> CorporateActionSnapshot:
    try:
        unsealed = CorporateActionSnapshot.model_validate(value)
    except ValidationError as error:
        raise V10ContractError("V10_CORPORATE_ACTION_UNKNOWN", str(error)) from error
    if not unsealed.verified or unsealed.adjustment_factor <= 0:
        raise V10ContractError("V10_CORPORATE_ACTION_UNKNOWN", unsealed.symbol)
    body = unsealed.model_dump(mode="json", exclude={"meta"})
    return unsealed.model_copy(update={"meta": seal_meta("corporate_action_snapshot", body)})
