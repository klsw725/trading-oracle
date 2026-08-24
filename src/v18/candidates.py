from itertools import product
from typing import Never

from .canonical import JsonValue, canonical_hash, model_json
from .errors import V18Error
from .models import (
    CalendarSession,
    CandidateStatus,
    CohortManifest,
    MeasurementNamespace,
    PolicyCandidate,
)
from .policies import WeightPolicy
from .sessions import next_effective_session
from .validation import canonical_decimal, canonical_utc


def weight_string(value: int) -> str:
    return f"{value // 1_000_000}.{value % 1_000_000:06d}"


def validate_weights(weights: tuple[int, ...], policy: WeightPolicy) -> None:
    if len(weights) != len(policy.perspectives) or sum(weights) != 1_000_000:
        raise V18Error("CANDIDATE_WEIGHT_BOUNDS", "set or sum")
    if any(
        value < policy.minimum_weight_millionths
        or value > policy.maximum_weight_millionths
        or abs(value - policy.base_weight_millionths)
        > policy.maximum_per_weight_delta_millionths
        for value in weights
    ):
        raise V18Error("CANDIDATE_WEIGHT_BOUNDS", "individual or delta")
    if sum(abs(value - policy.base_weight_millionths) for value in weights) > policy.maximum_l1_delta_millionths:
        raise V18Error("CANDIDATE_WEIGHT_BOUNDS", "l1")


def reject_active_policy_mutation() -> Never:
    raise V18Error("ACTIVE_POLICY_MUTATION_FORBIDDEN", "v18 candidates are inactive")


def validate_candidate(candidate: PolicyCandidate, policy: WeightPolicy) -> None:
    _ = canonical_utc(candidate.created_as_of)
    if candidate.status is not CandidateStatus.PROPOSED:
        raise V18Error("CANDIDATE_TRANSITION_INVALID", candidate.status.value)
    if (
        candidate.base_policy_version != policy.base_version
        or candidate.objective_version != policy.objective_version
        or tuple(sorted(candidate.weights)) != tuple(sorted(policy.perspectives))
    ):
        raise V18Error("CANDIDATE_WEIGHT_BOUNDS", "policy identity")
    weights: list[int] = []
    for perspective in policy.perspectives:
        value = candidate.weights[perspective]
        _ = canonical_decimal(value)
        weights.append(int(value.replace(".", "")))
    validate_weights(tuple(weights), policy)
    expected_version = canonical_hash(
        {
            "base_policy_version": policy.base_version,
            "cohort_hash": candidate.cohort_id,
            "objective_version": policy.objective_version,
        }
    )
    if candidate.candidate_version != expected_version:
        raise V18Error("CANDIDATE_VERSION_CONFLICT", candidate.candidate_version)
    identity = model_json(candidate, exclude={"candidate_id"})
    if canonical_hash(identity) != candidate.candidate_id:
        raise V18Error("CANDIDATE_IDENTITY_CONFLICT", candidate.candidate_id)


def select_weights(
    contributions: dict[str, int], policy: WeightPolicy
) -> tuple[int, ...]:
    values = range(
        policy.base_weight_millionths - policy.maximum_per_weight_delta_millionths,
        policy.base_weight_millionths + policy.maximum_per_weight_delta_millionths + 1,
        policy.quantum_millionths,
    )
    base = tuple(policy.base_weight_millionths for _ in policy.perspectives)
    base_score = sum(contributions[key] * value for key, value in zip(policy.perspectives, base, strict=True))
    eligible: list[tuple[int, tuple[int, ...]]] = []
    for candidate in product(values, repeat=len(policy.perspectives)):
        if sum(candidate) != 1_000_000:
            continue
        if sum(abs(value - policy.base_weight_millionths) for value in candidate) > policy.maximum_l1_delta_millionths:
            continue
        score = sum(
            contributions[key] * value
            for key, value in zip(policy.perspectives, candidate, strict=True)
        )
        if score > base_score:
            eligible.append((score, candidate))
    if not eligible:
        raise V18Error("NO_ELIGIBLE_CANDIDATE", "objective has no improvement")
    best_score = max(item[0] for item in eligible)
    selected = min(item[1] for item in eligible if item[0] == best_score)
    validate_weights(selected, policy)
    return selected


def build_candidate(
    manifest: CohortManifest,
    namespace: MeasurementNamespace,
    contributions: dict[str, int],
    sessions: tuple[CalendarSession, ...],
    created_as_of: str,
    policy: WeightPolicy,
) -> PolicyCandidate:
    if namespace != manifest.specification.namespace:
        raise V18Error("NAMESPACE_MISMATCH", manifest.cohort_id)
    weights = select_weights(contributions, policy)
    effective = next_effective_session(sessions, created_as_of)
    if effective.market is not namespace.market:
        raise V18Error("CANDIDATE_EFFECTIVE_SESSION_INVALID", effective.session)
    candidate_version = canonical_hash(
        {
            "base_policy_version": policy.base_version,
            "cohort_hash": manifest.manifest_hash,
            "objective_version": policy.objective_version,
        }
    )
    weight_map = {
        key: weight_string(value)
        for key, value in zip(policy.perspectives, weights, strict=True)
    }
    contribution_json: dict[str, JsonValue] = {
        key: value for key, value in contributions.items()
    }
    weight_json: dict[str, JsonValue] = {key: value for key, value in weight_map.items()}
    evidence: JsonValue = {
        "cohort_hash": manifest.manifest_hash,
        "contributions": contribution_json,
        "weights": weight_json,
    }
    body: JsonValue = {
        "base_policy_version": policy.base_version,
        "candidate_version": candidate_version,
        "cohort_id": manifest.cohort_id,
        "created_as_of": created_as_of,
        "effective_session": effective.session,
        "evidence_hash": canonical_hash(evidence),
        "namespace": {
            "account_id": namespace.account_id,
            "arm_id": namespace.arm_id,
            "currency": namespace.currency.value,
            "market": namespace.market.value,
        },
        "objective_version": policy.objective_version,
        "schema_version": "v18.policy-candidate.1",
        "status": CandidateStatus.PROPOSED.value,
        "weights": weight_json,
    }
    return PolicyCandidate(
        candidate_id=canonical_hash(body),
        candidate_version=candidate_version,
        base_policy_version=policy.base_version,
        namespace=namespace,
        cohort_id=manifest.cohort_id,
        objective_version=policy.objective_version,
        weights=weight_map,
        effective_session=effective.session,
        created_as_of=created_as_of,
        evidence_hash=canonical_hash(evidence),
        status=CandidateStatus.PROPOSED,
    )
