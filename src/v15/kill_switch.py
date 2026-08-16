from __future__ import annotations

from enum import StrEnum, unique

from .states import KillOverlay


@unique
class TriggerKind(StrEnum):
    SYMBOL_DATA = "symbol_data"
    SYMBOL_ACTION = "symbol_action"
    SYMBOL_BORROW = "symbol_borrow"
    ARM_RECONCILIATION = "arm_reconciliation"
    MARKET_CALENDAR = "market_calendar"
    MARKET_SOURCE = "market_source"
    MARKET_REGULATION = "market_regulation"
    GLOBAL_MANIFEST = "global_manifest"
    GLOBAL_POLICY = "global_policy"
    GLOBAL_HASH_CHAIN = "global_hash_chain"
    ARM_DAILY_LOSS = "arm_daily_loss"
    UNKNOWN_SYMBOL = "unknown_symbol"
    LLM_FALLBACK = "llm_fallback"


def classify_trigger(trigger: TriggerKind) -> KillOverlay:
    match trigger:  # noqa: MATCH_OK - TriggerKind is exhaustively covered
        case TriggerKind.SYMBOL_DATA | TriggerKind.SYMBOL_ACTION | TriggerKind.SYMBOL_BORROW:
            return KillOverlay.SYMBOL_BLOCKED
        case TriggerKind.ARM_DAILY_LOSS:
            return KillOverlay.ARM_LOSS_KILLED
        case TriggerKind.ARM_RECONCILIATION:
            return KillOverlay.ARM_OPERATION_KILLED
        case TriggerKind.UNKNOWN_SYMBOL | TriggerKind.MARKET_CALENDAR \
                | TriggerKind.MARKET_SOURCE | TriggerKind.MARKET_REGULATION:
            return KillOverlay.MARKET_OPERATION_KILLED
        case TriggerKind.GLOBAL_MANIFEST | TriggerKind.GLOBAL_POLICY \
                | TriggerKind.GLOBAL_HASH_CHAIN:
            return KillOverlay.GLOBAL_OPERATION_KILLED
        case TriggerKind.LLM_FALLBACK:
            return KillOverlay.CLEAR


def dominant_overlay(overlays: tuple[KillOverlay, ...]) -> KillOverlay:
    rank = {KillOverlay.CLEAR: 0, KillOverlay.SYMBOL_BLOCKED: 1,
        KillOverlay.ARM_LOSS_KILLED: 2,
        KillOverlay.ARM_OPERATION_KILLED: 3,
        KillOverlay.MARKET_OPERATION_KILLED: 4,
        KillOverlay.GLOBAL_OPERATION_KILLED: 5}
    return max(overlays, key=rank.__getitem__, default=KillOverlay.CLEAR)
