from __future__ import annotations

from .observability import LlmOutcomeKind, LlmOutcomeLedger, reduce_llm
from .operation_models import MarketOperation


def build_llm_outcomes(
    markets: tuple[MarketOperation, MarketOperation],
) -> tuple[LlmOutcomeLedger, LlmOutcomeLedger]:
    ledgers: list[LlmOutcomeLedger] = []
    for market in markets:
        sessions = market.schedule.performance_sessions \
            or market.schedule.comparison_sessions[-20:]
        call_sessions = (sessions[0], sessions[1], sessions[1], sessions[1],
            sessions[1], sessions[1], *sessions[2:])
        requested = (LlmOutcomeKind.SUCCESS, LlmOutcomeKind.TIMEOUT,
            LlmOutcomeKind.ABSTAIN, LlmOutcomeKind.SCHEMA_FAILURE,
            LlmOutcomeKind.SUCCESS, LlmOutcomeKind.SUCCESS,
            *(LlmOutcomeKind.SUCCESS for _ in sessions[2:]))
        ledgers.append(reduce_llm(market.market, call_sessions, requested))
    return ledgers[0], ledgers[1]
