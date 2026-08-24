from .acceptance_models import ProbeResult, passed
from .acceptance_support import (
    Scenario,
    cohort_specification,
    evaluated_predictions,
    expect_code,
    prediction,
    prepared_candidate,
    prepared_manifest,
    row_count,
)
from .boundaries import snapshot
from .candidates import build_candidate, validate_weights
from .cohorts import build_manifest
from .fixtures import ROOT
from .models import CandidateTransition, Market
from .objective import perspective_contributions
from .policies import ELIGIBILITY_POLICY, WEIGHT_POLICY
from .policy_repository import (
    transition_candidate,
)
from .outcomes import store_evaluation
from .policies import EVALUATOR_POLICY


def immature_cohort_member() -> ProbeResult:
    with Scenario.open() as scenario:
        records = evaluated_predictions(scenario)
        immature = prediction(5)
        _ = scenario.repository.register_prediction(immature)
        specification = cohort_specification(records + (immature,))
        expect_code(
            lambda: build_manifest(scenario.repository, specification, ELIGIBILITY_POLICY),
            "COHORT_MEMBER_INELIGIBLE",
        )
    return passed("immature_cohort_member", "COHORT_MEMBER_INELIGIBLE")


def duplicate_cohort_member() -> ProbeResult:
    with Scenario.open() as scenario:
        records = evaluated_predictions(scenario)
        specification = cohort_specification(records)
        duplicate = specification.model_copy(
            update={"prediction_ids": specification.prediction_ids + (records[0].prediction_id,)}
        )
        expect_code(
            lambda: build_manifest(scenario.repository, duplicate, ELIGIBILITY_POLICY),
            "COHORT_DUPLICATE_MEMBER",
        )
    return passed("duplicate_cohort_member", "COHORT_DUPLICATE_MEMBER")


def leakage_future_input() -> ProbeResult:
    with Scenario.open() as scenario:
        records = tuple(
            prediction(
                index,
                perspective_scores_as_of="2026-01-06T06:30:00Z",
                recorded_as_of="2026-01-06T06:30:00Z",
            )
            for index in range(5)
        )
        for record in records:
            _ = scenario.repository.register_prediction(record)
            _ = store_evaluation(
                scenario.repository,
                record.prediction_id,
                scenario.fixture.sessions,
                scenario.fixture.prices,
                "2026-01-06T06:30:00Z",
                EVALUATOR_POLICY,
            )
        specification = cohort_specification(records, cutoff="2026-01-05T06:29:59Z")
        expect_code(
            lambda: build_manifest(scenario.repository, specification, ELIGIBILITY_POLICY),
            "MEASUREMENT_LEAKAGE",
        )
    return passed("leakage_future_input", "MEASUREMENT_LEAKAGE")


def candidate_bound_escape() -> ProbeResult:
    invalid = (
        (400_000, 150_000, 150_000, 150_000, 150_000),
        (250_000, 250_000, 250_000, 250_000),
        (250_000, 200_000, 200_000, 200_000, 200_000),
        (250_000, 250_000, 200_000, 150_000, 150_000),
    )
    for weights in invalid:
        expect_code(
            lambda weights=weights: validate_weights(weights, WEIGHT_POLICY),
            "CANDIDATE_WEIGHT_BOUNDS",
        )
    return passed("candidate_bound_escape", "CANDIDATE_WEIGHT_BOUNDS")


def candidate_effective_past() -> ProbeResult:
    with Scenario.open() as scenario:
        manifest = prepared_manifest(scenario)
        contributions = perspective_contributions(
            scenario.repository, manifest, WEIGHT_POLICY
        )
        sessions = tuple(
            item for item in scenario.fixture.sessions if item.market is Market.KR
        )
        expect_code(
            lambda: build_candidate(
                manifest, manifest.specification.namespace, contributions,
                sessions, "2026-01-09T00:00:00Z", WEIGHT_POLICY,
            ),
            "CANDIDATE_EFFECTIVE_SESSION_INVALID",
        )
    return passed("candidate_effective_past", "CANDIDATE_EFFECTIVE_SESSION_INVALID")


def active_weight_overwrite() -> ProbeResult:
    with Scenario.open() as scenario:
        candidate = prepared_candidate(scenario)
        try:
            _ = scenario.repository.connection.execute(
                "UPDATE policy_candidates SET current_status='ACTIVE' WHERE candidate_id=?",
                (candidate.candidate_id,),
            )
        except sqlite3.IntegrityError:
            scenario.repository.connection.rollback()
        else:
            raise AssertionError("candidate reached ACTIVE")
    return passed("active_weight_overwrite", "ACTIVE_POLICY_MUTATION_FORBIDDEN")


def rollback_deletes_history() -> ProbeResult:
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
        _ = transition_candidate(
            scenario.repository, scheduled.candidate_id,
            CandidateTransition.ROLLBACK, "2026-01-05T10:00:00Z",
        )
        try:
            _ = scenario.repository.connection.execute(
                "DELETE FROM candidate_events WHERE candidate_id=?",
                (candidate.candidate_id,),
            )
        except sqlite3.IntegrityError:
            scenario.repository.connection.rollback()
        else:
            raise AssertionError("candidate history delete succeeded")
        if row_count(scenario.repository, "candidate_events") != 4:
            raise AssertionError("rollback history was not preserved")
    return passed("rollback_deletes_history", "CANDIDATE_HISTORY_IMMUTABLE")


def portfolio_mutation() -> ProbeResult:
    path = ROOT / "data/portfolio.json"
    before = snapshot(path)
    after = snapshot(path)
    if before != after:
        raise AssertionError("portfolio changed during acceptance")
    return passed("portfolio_mutation", "mutation 0")


CANDIDATE_MUTATIONS = (
    immature_cohort_member,
    duplicate_cohort_member,
    leakage_future_input,
    candidate_bound_escape,
    candidate_effective_past,
    active_weight_overwrite,
    rollback_deletes_history,
    portfolio_mutation,
)
import sqlite3
