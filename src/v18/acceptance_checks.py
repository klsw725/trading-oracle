from collections.abc import Callable

from .acceptance_models import ProbeResult, passed
from .acceptance_support import (
    Scenario,
    cohort_specification,
    evaluated_predictions,
    prediction,
    prepared_candidate,
    row_count,
)
from .cohorts import build_manifest, freeze_cohort
from .errors import FaultInjected, V18Error
from .migrations import SCHEMA_HASH
from .models import CandidateStatus, CandidateTransition
from .outcomes import store_evaluation
from .policies import ELIGIBILITY_POLICY, EVALUATOR_POLICY
from .policy_repository import transition_candidate
from .repository import MeasurementRepository
from .acceptance_faults import fault_checkpoint_matrix
from .acceptance_security import SECURITY_CHECKS


def schema_head() -> ProbeResult:
    with Scenario.open() as scenario:
        match scenario.repository.connection.execute("PRAGMA user_version").fetchone():  # noqa: MATCH_OK - SQLite boundary.
            case (2,):
                pass
            case value:
                raise V18Error("MIGRATION_VERSION_MISMATCH", str(value))
        if not SCHEMA_HASH.startswith("sha256:"):
            raise AssertionError("schema hash is not canonical")
    return passed("schema_head", "global head 002")


def end_to_end_candidate() -> ProbeResult:
    with Scenario.open() as scenario:
        candidate = prepared_candidate(scenario)
        if candidate.status is not CandidateStatus.PROPOSED:
            raise AssertionError("candidate was activated")
        total = sum(int(value.replace(".", "")) for value in candidate.weights.values())
        if total != 1_000_000:
            raise AssertionError("candidate weights do not sum to one")
    return passed("end_to_end_candidate", "inactive bounded candidate")


def candidate_lifecycle() -> ProbeResult:
    with Scenario.open() as scenario:
        candidate = prepared_candidate(scenario)
        approved = transition_candidate(
            scenario.repository, candidate.candidate_id,
            CandidateTransition.APPROVE, "2026-01-05T08:00:00Z",
        )
        scheduled = transition_candidate(
            scenario.repository, approved.candidate_id,
            CandidateTransition.SCHEDULE, "2026-01-05T09:00:00Z",
        )
        rolled_back = transition_candidate(
            scenario.repository, scheduled.candidate_id,
            CandidateTransition.ROLLBACK, "2026-01-05T10:00:00Z",
        )
        if rolled_back.status is not CandidateStatus.ROLLED_BACK:
            raise AssertionError("candidate rollback did not persist")
    return passed("candidate_lifecycle", "append-only rollback")


def _assert_fault_rollback(
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


def registration_fault_rollback() -> ProbeResult:
    with Scenario.open() as scenario:
        record = prediction(0)
        _assert_fault_rollback(
            scenario,
            lambda: (
                scenario.repository.register_prediction(
                    record, fault="after_immutable_row_insert"
                ),
                None,
            )[1],
            "after_immutable_row_insert",
        )
    return passed("registration_fault_rollback", "pre-state restored")


def evaluation_fault_rollback() -> ProbeResult:
    with Scenario.open() as scenario:
        record = prediction(0)
        _ = scenario.repository.register_prediction(record)
        prices = scenario.fixture.prices
        _assert_fault_rollback(
            scenario,
            lambda: (
                store_evaluation(
                    scenario.repository, record.prediction_id, scenario.fixture.sessions,
                    prices, "2026-01-05T06:30:00Z", EVALUATOR_POLICY,
                    fault="after_immutable_row_insert",
                ),
                None,
            )[1],
            "after_immutable_row_insert",
        )
    return passed("evaluation_fault_rollback", "pre-state restored")


def cohort_fault_rollback() -> ProbeResult:
    with Scenario.open() as scenario:
        records = evaluated_predictions(scenario)
        manifest = build_manifest(
            scenario.repository,
            cohort_specification(records),
            ELIGIBILITY_POLICY,
        )
        _assert_fault_rollback(
            scenario,
            lambda: (
                freeze_cohort(
                    scenario.repository, manifest, fault="after_immutable_row_insert"
                ),
                None,
            )[1],
            "after_immutable_row_insert",
        )
    return passed("cohort_fault_rollback", "pre-state restored")


def candidate_fault_rollback() -> ProbeResult:
    with Scenario.open() as scenario:
        candidate = prepared_candidate(scenario)
        _assert_fault_rollback(
            scenario,
            lambda: (
                transition_candidate(
                    scenario.repository, candidate.candidate_id,
                    CandidateTransition.APPROVE, "2026-01-05T08:00:00Z",
                    fault="after_projection_update",
                ),
                None,
            )[1],
            "after_projection_update",
        )
    return passed("candidate_fault_rollback", "pre-state restored")


def account_write_set() -> ProbeResult:
    with Scenario.open() as scenario:
        _ = prepared_candidate(scenario)
        for table in ("account_balances", "account_positions", "account_reservations"):
            if row_count(scenario.repository, table) != 0:
                raise V18Error("ACCOUNT_WRITE_SET_VIOLATION", table)
    return passed("account_write_set", "account tables unchanged")


CHECKS = (
    schema_head,
    end_to_end_candidate,
    candidate_lifecycle,
    fault_checkpoint_matrix,
    account_write_set,
    *SECURITY_CHECKS,
)


def run_checks() -> tuple[ProbeResult, ...]:
    return tuple(sorted((check() for check in CHECKS), key=lambda item: item.id))
