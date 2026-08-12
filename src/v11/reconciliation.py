from __future__ import annotations

from src.v4.models import JsonValue

from .canonical import canonical_hash, model_json
from .models import ReplayState, StrictModel


class ReconciliationResult(StrictModel):
    state: str
    input_hash: str
    execution_halt: bool
    pending_cancelled: bool


def reconcile(replayed: ReplayState, source: ReplayState) -> ReconciliationResult:
    matches = (replayed.cash == source.cash and replayed.positions == source.positions
        and replayed.open_intents == source.open_intents and replayed.fill_quantity == source.fill_quantity
        and replayed.accrued_cost == source.accrued_cost and replayed.halted == source.halted)
    body: JsonValue = {"replayed": model_json(replayed), "source": model_json(source)}
    return ReconciliationResult(state="pass" if matches else "mismatch",
        input_hash=canonical_hash(body), execution_halt=not matches, pending_cancelled=not matches)
