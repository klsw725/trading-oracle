from collections.abc import Callable

from .acceptance_models import ProbeResult, passed
from .acceptance_support import (
    Scenario,
    candidate_value,
    cohort_specification,
    evaluated_predictions,
    prediction,
    prepared_candidate,
)
from .cohorts import build_manifest, freeze_cohort
from .errors import FaultInjected, V18Error
from .models import CandidateTransition
from .outcomes import store_evaluation
from .policies import ELIGIBILITY_POLICY, EVALUATOR_POLICY
from .policy_repository import propose_candidate, transition_candidate
from .repository import MeasurementRepository


def _assert_rollback(
    scenario: Scenario, operation: Callable[[], None], checkpoint: str
) -> None:
    before = scenario.repository.table_hashes()
    try:
        operation()
    except FaultInjected as error:
        if error.checkpoint != checkpoint:
            raise V18Error("FAULT_CHECKPOINT_MISMATCH", error.checkpoint) from error
    else:
        raise V18Error("FAULT_NOT_INJECTED", checkpoint)
    if scenario.repository.table_hashes() != before:
        raise V18Error("FAULT_ROLLBACK_FAILED", checkpoint)
    path = scenario.repository.path
    scenario.repository.close()
    scenario.repository = MeasurementRepository.open(path)
    if scenario.repository.table_hashes() != before:
        raise V18Error("FAULT_REOPEN_MISMATCH", checkpoint)


def _registration(checkpoint: str) -> None:
    with Scenario.open() as scenario:
        record = prediction(0)
        _assert_rollback(
            scenario,
            lambda: (
                scenario.repository.register_prediction(record, fault=checkpoint),
                None,
            )[1],
            checkpoint,
        )


def _evaluation(checkpoint: str) -> None:
    with Scenario.open() as scenario:
        record = prediction(0)
        _ = scenario.repository.register_prediction(record)
        _assert_rollback(
            scenario,
            lambda: (
                store_evaluation(
                    scenario.repository,
                    record.prediction_id,
                    scenario.fixture.sessions,
                    scenario.fixture.prices,
                    "2026-01-05T06:30:00Z",
                    EVALUATOR_POLICY,
                    fault=checkpoint,
                ),
                None,
            )[1],
            checkpoint,
        )


def _cohort(checkpoint: str) -> None:
    with Scenario.open() as scenario:
        records = evaluated_predictions(scenario)
        manifest = build_manifest(
            scenario.repository, cohort_specification(records), ELIGIBILITY_POLICY
        )
        _assert_rollback(
            scenario,
            lambda: (
                freeze_cohort(scenario.repository, manifest, fault=checkpoint),
                None,
            )[1],
            checkpoint,
        )


def _proposal(checkpoint: str) -> None:
    with Scenario.open() as scenario:
        candidate = candidate_value(scenario)
        _assert_rollback(
            scenario,
            lambda: (
                propose_candidate(scenario.repository, candidate, fault=checkpoint),
                None,
            )[1],
            checkpoint,
        )


def _transition(checkpoint: str) -> None:
    with Scenario.open() as scenario:
        candidate = prepared_candidate(scenario)
        _assert_rollback(
            scenario,
            lambda: (
                transition_candidate(
                    scenario.repository,
                    candidate.candidate_id,
                    CandidateTransition.APPROVE,
                    "2026-01-05T08:00:00Z",
                    fault=checkpoint,
                ),
                None,
            )[1],
            checkpoint,
        )


def fault_checkpoint_matrix() -> ProbeResult:
    operations: tuple[tuple[Callable[[str], None], tuple[str, ...]], ...] = (
        (
            _registration,
            (
                "after_event_append",
                "after_immutable_row_insert",
                "after_idempotency_insert",
                "after_final_invariant",
            ),
        ),
        (
            _evaluation,
            (
                "after_projection_update",
                "after_event_append",
                "after_immutable_row_insert",
                "after_idempotency_insert",
                "after_final_invariant",
            ),
        ),
        (
            _cohort,
            (
                "after_event_append",
                "after_immutable_row_insert",
                "after_idempotency_insert",
                "after_final_invariant",
            ),
        ),
        (
            _proposal,
            (
                "after_event_append",
                "after_immutable_row_insert",
                "after_idempotency_insert",
                "after_final_invariant",
            ),
        ),
        (
            _transition,
            ("after_event_append", "after_projection_update", "after_final_invariant"),
        ),
    )
    for operation, checkpoints in operations:
        for checkpoint in checkpoints:
            operation(checkpoint)
    return passed("fault_checkpoint_matrix", "all named checkpoints restore pre-state")
