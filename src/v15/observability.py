from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum, unique
from typing import Annotated, Literal

from pydantic import Field
from src.v11.canonical import canonical_hash
from src.v4.models import JsonValue

from .contract import StrictModel, V15Failure, V15FailureCode
from .reporting import LlmOperations, SessionReport


@unique
class LlmOutcomeKind(StrEnum):
    SUCCESS = "success"
    TIMEOUT = "timeout"
    ABSTAIN = "abstain"
    SCHEMA_FAILURE = "schema_failure"


@unique
class ExecutionMode(StrEnum):
    MIXED = "mixed"
    QUANT_ONLY = "quant_only"


class LlmOutcome(StrictModel):
    market: Literal["KR", "US"]
    session: date
    session_call_index: int
    requested_kind: LlmOutcomeKind
    observed_kind: LlmOutcomeKind | None
    execution_mode: ExecutionMode
    provider_called: bool
    quant_fallback: bool
    mixed_success: bool
    breaker_open: bool
    fallback_reason: str | None
    evidence_hash: str


class LlmOutcomeLedger(StrictModel):
    market: Literal["KR", "US"]
    outcomes: Annotated[tuple[LlmOutcome, ...], Field(strict=False)]


@dataclass(frozen=True, slots=True)
class OutcomeSpec:
    market: Literal["KR", "US"]
    session: date
    session_call_index: int
    requested: LlmOutcomeKind
    observed: LlmOutcomeKind | None
    mode: ExecutionMode
    provider_called: bool
    fallback: bool
    mixed_success: bool
    breaker_open: bool
    reason: str | None


def reduce_llm(
    market: Literal["KR", "US"], sessions: tuple[date, ...],
    requested: tuple[LlmOutcomeKind, ...],
) -> LlmOutcomeLedger:
    if len(sessions) != len(requested):
        raise V15Failure(V15FailureCode.COMPARISON_INVALID, "llm_sessions")
    outcomes: list[LlmOutcome] = []
    open_breaker = False
    consecutive = 0
    provider_history: list[bool] = []
    current_session: date | None = None
    session_call_index = 0
    for session, kind in zip(sessions, requested, strict=True):
        if current_session is not None and session < current_session:
            raise V15Failure(V15FailureCode.COMPARISON_INVALID,
                "llm_session_order")
        if session != current_session:
            current_session = session
            open_breaker = False
            consecutive = 0
            provider_history = []
            session_call_index = 0
        if open_breaker:
            outcomes.append(_outcome(OutcomeSpec(market=market,
                session=session, session_call_index=session_call_index,
                requested=kind, observed=None, mode=ExecutionMode.QUANT_ONLY,
                provider_called=False, fallback=True, mixed_success=False,
                breaker_open=True, reason="sticky_circuit_breaker")))
            session_call_index += 1
            continue
        failed = kind is not LlmOutcomeKind.SUCCESS
        consecutive = consecutive + 1 if failed else 0
        provider_history.append(failed)
        recent = provider_history[-20:]
        open_breaker = consecutive >= 3 or (len(recent) == 20
            and sum(recent) >= 4)
        outcomes.append(_outcome(OutcomeSpec(market=market, session=session,
            session_call_index=session_call_index, requested=kind,
            observed=kind, mode=ExecutionMode.MIXED, provider_called=True,
            fallback=failed, mixed_success=not failed,
            breaker_open=open_breaker,
            reason=kind.value if failed else None)))
        session_call_index += 1
    return LlmOutcomeLedger(market=market, outcomes=tuple(outcomes))


def summarize_llm(ledger: LlmOutcomeLedger) -> LlmOperations:
    observed = tuple(item.observed_kind for item in ledger.outcomes
        if item.observed_kind is not None)
    return LlmOperations(
        timeout_count=sum(item is LlmOutcomeKind.TIMEOUT for item in observed),
        abstain_count=sum(item is LlmOutcomeKind.ABSTAIN for item in observed),
        schema_failure_count=sum(item is LlmOutcomeKind.SCHEMA_FAILURE
            for item in observed),
        circuit_open=any(item.breaker_open for item in ledger.outcomes),
        quant_fallback_count=sum(item.quant_fallback for item in ledger.outcomes),
        mixed_success_count=sum(item.mixed_success for item in ledger.outcomes))


def verify_llm_ledger(ledger: LlmOutcomeLedger) -> None:
    rebuilt = reduce_llm(ledger.market,
        tuple(item.session for item in ledger.outcomes),
        tuple(item.requested_kind for item in ledger.outcomes))
    if rebuilt != ledger:
        raise V15Failure(V15FailureCode.BUNDLE_MISMATCH, "llm_sticky")


def verify_llm_report(report: SessionReport, ledger: LlmOutcomeLedger) -> None:
    verify_llm_ledger(ledger)
    if report.market != ledger.market or report.llm != summarize_llm(ledger):
        raise V15Failure(V15FailureCode.BUNDLE_MISMATCH, "llm_report")


def _outcome(spec: OutcomeSpec) -> LlmOutcome:
    body: dict[str, JsonValue] = {"market": spec.market,
        "session": spec.session.isoformat(),
        "session_call_index": spec.session_call_index,
        "requested": spec.requested.value,
        "observed": spec.observed.value if spec.observed is not None else None,
        "mode": spec.mode.value, "provider_called": spec.provider_called,
        "fallback": spec.fallback, "mixed_success": spec.mixed_success,
        "breaker_open": spec.breaker_open, "reason": spec.reason}
    return LlmOutcome(market=spec.market, session=spec.session,
        session_call_index=spec.session_call_index,
        requested_kind=spec.requested, observed_kind=spec.observed,
        execution_mode=spec.mode, provider_called=spec.provider_called,
        quant_fallback=spec.fallback, mixed_success=spec.mixed_success,
        breaker_open=spec.breaker_open, fallback_reason=spec.reason,
        evidence_hash=canonical_hash(body))
