# pyright: reportUnnecessaryComparison=false

from dataclasses import dataclass
from enum import StrEnum, unique
from typing import Final, NewType, assert_never, override

from src.v4.models import ContentHash, JsonValue, ReplayMode, canonical_hash
from src.v4.replay import FailureProbe, ReplayContractError, ReplayRecord, replay_mode
from src.v4.replay_runtime import ReplayArtifact, record_seed, replay_artifact


ReplayRunId = NewType("ReplayRunId", str)
CheckpointId = NewType("CheckpointId", str)


@unique
class WorkflowState(StrEnum):
    RUN_CREATED = "RUN_CREATED"
    UNIVERSE_BUILT = "UNIVERSE_BUILT"
    CANDIDATE_SELECTED = "CANDIDATE_SELECTED"
    SIGNAL_EVALUATED = "SIGNAL_EVALUATED"
    PERSPECTIVES_REPLAYED = "PERSPECTIVES_REPLAYED"
    CONSENSUS_REPLAYED = "CONSENSUS_REPLAYED"
    RISK_REPLAYED = "RISK_REPLAYED"
    TRADE_REPLAYED = "TRADE_REPLAYED"
    OUTCOME_REPLAYED = "OUTCOME_REPLAYED"
    REPORT_WRITTEN = "REPORT_WRITTEN"
    REPORT_FAILED = "REPORT_FAILED"


WORKFLOW_ORDER: Final = (
    WorkflowState.RUN_CREATED,
    WorkflowState.UNIVERSE_BUILT,
    WorkflowState.CANDIDATE_SELECTED,
    WorkflowState.SIGNAL_EVALUATED,
    WorkflowState.PERSPECTIVES_REPLAYED,
    WorkflowState.CONSENSUS_REPLAYED,
    WorkflowState.RISK_REPLAYED,
    WorkflowState.TRADE_REPLAYED,
    WorkflowState.OUTCOME_REPLAYED,
    WorkflowState.REPORT_WRITTEN,
)


@dataclass(frozen=True, slots=True)
class WorkflowTransition:
    from_state: WorkflowState
    to_state: WorkflowState
    transition_hash: ContentHash


@dataclass(frozen=True, slots=True)
class WorkflowTransitionError(Exception):
    from_state: WorkflowState
    to_state: WorkflowState

    @override
    def __str__(self) -> str:
        return f"invalid workflow transition: {self.from_state} -> {self.to_state}"


def transition(from_state: WorkflowState, to_state: WorkflowState) -> WorkflowTransition:
    try:
        index = WORKFLOW_ORDER.index(from_state)
    except ValueError:
        raise WorkflowTransitionError(from_state, to_state) from None
    failure_edge = from_state is WorkflowState.OUTCOME_REPLAYED and to_state is WorkflowState.REPORT_FAILED
    success_edge = index + 1 < len(WORKFLOW_ORDER) and WORKFLOW_ORDER[index + 1] is to_state
    if not failure_edge and not success_edge:
        raise WorkflowTransitionError(from_state, to_state)
    seed: JsonValue = {"from": from_state, "to": to_state}
    return WorkflowTransition(from_state, to_state, canonical_hash(seed))


def transitions_through(count: int, failed: bool = False) -> tuple[WorkflowTransition, ...]:
    transitions = tuple(
        transition(WORKFLOW_ORDER[index], WORKFLOW_ORDER[index + 1])
        for index in range(count)
    )
    if failed and count == len(WORKFLOW_ORDER) - 1:
        failed_report = transition(WorkflowState.OUTCOME_REPLAYED, WorkflowState.REPORT_FAILED)
        return (*transitions[:-1], failed_report)
    return transitions


def state_after(transitions: tuple[WorkflowTransition, ...]) -> WorkflowState:
    if not transitions:
        return WorkflowState.RUN_CREATED
    return transitions[-1].to_state


@dataclass(frozen=True, slots=True)
class ReplayRequest:
    mode: ReplayMode
    idempotency_key: str
    records: tuple[ReplayRecord, ...]
    ledger_tail_hash: ContentHash | None = None


@dataclass(frozen=True, slots=True)
class ReplayCheckpoint:
    checkpoint_id: CheckpointId
    input_hash: ContentHash
    mode: ReplayMode
    idempotency_key: str
    transition_count: int
    workflow_state: WorkflowState
    cancelled: bool
    failed: bool
    last_ledger_hash: ContentHash | None
    last_artifact_hash: ContentHash | None
    artifact_hashes: tuple[ContentHash, ...]
    failure_probes: tuple[FailureProbe, ...]
    transitions: tuple[WorkflowTransition, ...]
    checkpoint_hash: ContentHash


@dataclass(frozen=True, slots=True)
class ReplayExecution:
    replay_run_id: ReplayRunId
    input_hash: ContentHash
    complete: bool
    failed: bool
    workflow_state: WorkflowState
    artifacts: tuple[ReplayArtifact, ...]
    transitions: tuple[WorkflowTransition, ...]
    checkpoint: ReplayCheckpoint
    failure_probes: tuple[FailureProbe, ...]
    output_hash: ContentHash | None


def _input_hash(request: ReplayRequest) -> ContentHash:
    seed: JsonValue = {
        "mode": request.mode,
        "idempotency_key": request.idempotency_key,
        "ledger_tail_hash": request.ledger_tail_hash,
        "records": [record_seed(record) for record in request.records],
    }
    return canonical_hash(seed)


def _artifact_state(mode: ReplayMode) -> WorkflowState:
    match mode:
        case ReplayMode.VERBATIM | ReplayMode.RECOMPUTE:
            return WorkflowState.PERSPECTIVES_REPLAYED
        case ReplayMode.OUTCOME:
            return WorkflowState.OUTCOME_REPLAYED
        case unreachable:
            assert_never(unreachable)


def _artifacts(request: ReplayRequest, state: WorkflowState) -> tuple[ReplayArtifact, ...]:
    try:
        state_index = WORKFLOW_ORDER.index(state)
    except ValueError:
        state_index = len(WORKFLOW_ORDER)
    if state_index < WORKFLOW_ORDER.index(_artifact_state(request.mode)):
        return ()
    return tuple(replay_artifact(record) for record in request.records)


def _checkpoint(
    request: ReplayRequest,
    input_hash: ContentHash,
    transitions: tuple[WorkflowTransition, ...],
    cancelled: bool,
) -> ReplayCheckpoint:
    state = state_after(transitions)
    artifacts = _artifacts(request, state)
    hashes = tuple(artifact.artifact_hash for artifact in artifacts)
    probes = tuple(probe for artifact in artifacts for probe in artifact.failure_probes)
    last_artifact = hashes[-1] if hashes else None
    seed: JsonValue = {
        "input_hash": input_hash,
        "mode": request.mode,
        "idempotency_key": request.idempotency_key,
        "transition_count": len(transitions),
        "workflow_state": state,
        "cancelled": cancelled,
        "failed": state is WorkflowState.REPORT_FAILED,
        "last_ledger_hash": request.ledger_tail_hash,
        "last_artifact_hash": last_artifact,
        "artifact_hashes": list(hashes),
        "failure_probes": [probe.value for probe in probes],
        "transition_hashes": [item.transition_hash for item in transitions],
    }
    checkpoint_hash = canonical_hash(seed)
    return ReplayCheckpoint(
        CheckpointId(f"chk_v4_{checkpoint_hash.removeprefix('sha256:')[:20]}"),
        input_hash,
        request.mode,
        request.idempotency_key,
        len(transitions),
        state,
        cancelled,
        state is WorkflowState.REPORT_FAILED,
        request.ledger_tail_hash,
        last_artifact,
        hashes,
        probes,
        transitions,
        checkpoint_hash,
    )


def _validate_request(request: ReplayRequest, max_transitions: int | None) -> None:
    if max_transitions is not None and max_transitions <= 0:
        raise ReplayContractError("max_transitions must be positive")
    if any(replay_mode(record) is not request.mode for record in request.records):
        raise ReplayContractError("request contains a record from another replay mode")


def execute_replay(
    request: ReplayRequest,
    checkpoint: ReplayCheckpoint | None = None,
    max_transitions: int | None = None,
) -> ReplayExecution:
    _validate_request(request, max_transitions)
    input_hash = _input_hash(request)
    will_fail = any(not artifact.eligible for artifact in (replay_artifact(record) for record in request.records))
    completed = 0
    if checkpoint is not None:
        completed = checkpoint.transition_count
        if completed > len(WORKFLOW_ORDER) - 1:
            raise ReplayContractError("resume_input_mismatch")
        expected_transitions = transitions_through(completed, will_fail)
        expected = _checkpoint(request, input_hash, expected_transitions, completed < len(WORKFLOW_ORDER) - 1)
        if checkpoint != expected:
            raise ReplayContractError("resume_input_mismatch")
    remaining = len(WORKFLOW_ORDER) - 1 - completed
    advance = remaining if max_transitions is None else min(remaining, max_transitions)
    transitions = transitions_through(completed + advance, will_fail)
    terminal = len(transitions) == len(WORKFLOW_ORDER) - 1
    complete = terminal and state_after(transitions) is WorkflowState.REPORT_WRITTEN
    current = _checkpoint(request, input_hash, transitions, not terminal)
    artifacts = _artifacts(request, current.workflow_state)
    output_hash = canonical_hash([artifact.artifact_hash for artifact in artifacts]) if complete else None
    run_id = ReplayRunId(f"replay_v4_{input_hash.removeprefix('sha256:')[:20]}")
    return ReplayExecution(run_id, input_hash, complete, current.failed, current.workflow_state, artifacts, transitions, current, current.failure_probes, output_hash)
