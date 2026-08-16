from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum, unique
from typing import Annotated, Final, Literal

from pydantic import Field
from src.v11.canonical import canonical_hash, model_json

from .contract import StrictModel, V15Failure, V15FailureCode


GENESIS_HASH: Final = "sha256:" + "0" * 64


@unique
class LifecycleState(StrEnum):
    FOUNDATION_CANDIDATE = "foundation_candidate"
    FOUNDATION_READY = "foundation_ready"
    ORB_CANDIDATE = "orb_candidate"
    ORB_HOLDOUT_PASSED = "orb_holdout_passed"
    ORB_PAPER = "orb_paper"
    STRATEGIES_CANDIDATE = "strategies_candidate"
    STRATEGIES_SHADOW = "strategies_shadow"
    ROUTER_CANDIDATE = "router_candidate"
    ROUTER_SHADOW = "router_shadow"
    ROUTER_CHALLENGER = "router_challenger"
    ROUTER_PRIMARY = "router_primary"
    ROUTER_OPERATIONAL_ROLLBACK = "router_operational_rollback"
    ROUTER_PERFORMANCE_ROLLBACK = "router_performance_rollback"
    ROUTER_RETIRED = "router_retired"


@unique
class KillOverlay(StrEnum):
    CLEAR = "clear"
    SYMBOL_BLOCKED = "symbol_blocked"
    ARM_LOSS_KILLED = "arm_loss_killed"
    ARM_OPERATION_KILLED = "arm_operation_killed"
    MARKET_OPERATION_KILLED = "market_operation_killed"
    GLOBAL_OPERATION_KILLED = "global_operation_killed"


@unique
class OperationEventType(StrEnum):
    LIFECYCLE = "lifecycle"
    MIRROR_DAY = "mirror_day"
    LOSS_KILL = "loss_kill"
    OPERATION_KILL = "operation_kill"
    CANCEL = "cancel"
    FLATTEN = "flatten"
    RECOVERY = "recovery"
    OPERATIONAL_ROLLBACK = "operational_rollback"
    PERFORMANCE_ROLLBACK = "performance_rollback"
    LLM_OUTCOME = "llm_outcome"


class OperationEventBody(StrictModel):
    schema_version: Literal["v15.operation_event.2"]
    sequence: int
    event_type: OperationEventType
    market: Literal["KR", "US"] | None
    arm: str | None
    symbol: str | None
    session: date
    occurred_at: datetime
    manifest_hash: str
    evidence_refs: Annotated[tuple[str, ...], Field(strict=False)]
    detail_hash: str
    lifecycle_before: LifecycleState
    lifecycle_after: LifecycleState
    kill_before: KillOverlay
    kill_after: KillOverlay
    previous_hash: str


class OperationEvent(OperationEventBody):
    event_hash: str


_ALLOWED: Final = frozenset({
    (LifecycleState.FOUNDATION_CANDIDATE, LifecycleState.FOUNDATION_READY),
    (LifecycleState.ORB_CANDIDATE, LifecycleState.ORB_HOLDOUT_PASSED),
    (LifecycleState.ORB_HOLDOUT_PASSED, LifecycleState.ORB_PAPER),
    (LifecycleState.STRATEGIES_CANDIDATE, LifecycleState.STRATEGIES_SHADOW),
    (LifecycleState.ROUTER_CANDIDATE, LifecycleState.ROUTER_SHADOW),
    (LifecycleState.ROUTER_SHADOW, LifecycleState.ROUTER_CHALLENGER),
    (LifecycleState.ROUTER_CHALLENGER, LifecycleState.ROUTER_PRIMARY),
    (LifecycleState.ROUTER_PRIMARY,
        LifecycleState.ROUTER_OPERATIONAL_ROLLBACK),
    (LifecycleState.ROUTER_OPERATIONAL_ROLLBACK,
        LifecycleState.ROUTER_PRIMARY),
    (LifecycleState.ROUTER_PRIMARY,
        LifecycleState.ROUTER_PERFORMANCE_ROLLBACK),
    (LifecycleState.ROUTER_PERFORMANCE_ROLLBACK,
        LifecycleState.ROUTER_RETIRED),
})


def append_event(
    events: tuple[OperationEvent, ...], body: OperationEventBody
) -> tuple[OperationEvent, ...]:
    previous = events[-1].event_hash if events else GENESIS_HASH
    if body.sequence != len(events) + 1 or body.previous_hash != previous:
        raise V15Failure(V15FailureCode.CHAIN_MISMATCH, body.event_type.value)
    if events and body.occurred_at < events[-1].occurred_at:
        raise V15Failure(V15FailureCode.CHAIN_MISMATCH, "event_time")
    prior = next((item for item in reversed(events)
        if item.market == body.market and item.arm == body.arm), None)
    if prior is not None and body.lifecycle_before is not prior.lifecycle_after:
        raise V15Failure(V15FailureCode.INVALID_TRANSITION, "entity_state")
    _verify_transition(body)
    event_hash = canonical_hash(model_json(body))
    return (*events, OperationEvent(
        schema_version=body.schema_version, sequence=body.sequence,
        event_type=body.event_type, market=body.market, arm=body.arm,
        symbol=body.symbol, session=body.session, occurred_at=body.occurred_at,
        manifest_hash=body.manifest_hash, evidence_refs=body.evidence_refs,
        detail_hash=body.detail_hash, lifecycle_before=body.lifecycle_before,
        lifecycle_after=body.lifecycle_after, kill_before=body.kill_before,
        kill_after=body.kill_after, previous_hash=body.previous_hash,
        event_hash=event_hash),)


def verify_chain(events: tuple[OperationEvent, ...]) -> str:
    rebuilt: tuple[OperationEvent, ...] = ()
    for event in events:
        body = OperationEventBody.model_validate(
            event.model_dump(exclude={"event_hash"}))
        rebuilt = append_event(rebuilt, body)
        if rebuilt[-1].event_hash != event.event_hash:
            raise V15Failure(V15FailureCode.CHAIN_MISMATCH, event.event_hash)
    return rebuilt[-1].event_hash if rebuilt else GENESIS_HASH


def _verify_transition(body: OperationEventBody) -> None:
    lifecycle_changed = body.lifecycle_before is not body.lifecycle_after
    kill_changed = body.kill_before is not body.kill_after
    if lifecycle_changed and (body.lifecycle_before, body.lifecycle_after) not in _ALLOWED:
        raise V15Failure(V15FailureCode.INVALID_TRANSITION,
            f"{body.lifecycle_before.value}->{body.lifecycle_after.value}")
    if body.event_type is OperationEventType.LIFECYCLE and not lifecycle_changed:
        raise V15Failure(V15FailureCode.INVALID_TRANSITION, "lifecycle_no_change")
    if body.event_type is not OperationEventType.LIFECYCLE and lifecycle_changed \
            and body.event_type not in {OperationEventType.OPERATIONAL_ROLLBACK,
                OperationEventType.PERFORMANCE_ROLLBACK,
                OperationEventType.RECOVERY}:
        raise V15Failure(V15FailureCode.INVALID_TRANSITION, body.event_type.value)
    if body.event_type in {OperationEventType.MIRROR_DAY,
            OperationEventType.CANCEL, OperationEventType.FLATTEN,
            OperationEventType.LLM_OUTCOME} and kill_changed:
        raise V15Failure(V15FailureCode.INVALID_TRANSITION, "unexpected_kill_change")
