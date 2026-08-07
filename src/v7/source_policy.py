from typing import Annotated, Literal

from pydantic import Field

from src.v4.models import canonical_hash
from src.v6.models import BoundaryModel, JsonBoundary

from .models import HashText
from .source_models import LifecycleState, SourcePolicyError


class CacheProjection(BoundaryModel):
    generation: Annotated[int, Field(strict=True, ge=0)]
    current: bool
    audit_only_generations: tuple[int, ...]
    purge_required: bool
    policy_hash: HashText | None
    source_bundle_hash: HashText
    quality_result_hash: HashText


class FallbackCandidate(BoundaryModel):
    source_bundle_id: str
    state: LifecycleState
    capability_match: bool
    freshness_label: Literal["fresh", "stale", "expired", "missing"]
    quality_label: Literal["high", "usable", "degraded", "blocked"]
    value_rank: Annotated[int, Field(strict=True, ge=0)]
    cost_latency_rank: Annotated[int, Field(strict=True, ge=0)]


class SourcePolicyBody(BoundaryModel):
    schema_version: Literal["v7.source-policy.snapshot.1"]
    policy_version: Annotated[int, Field(strict=True, ge=0)]
    source_bundle_id: str
    source_bundle_hash: HashText
    contract_ref_hash: HashText
    state: LifecycleState
    traffic_share: str
    cache: CacheProjection
    fallback_order: tuple[str, ...]
    production_isolation: Literal["offline_only_no_production_imports"]


class SourcePolicySnapshot(SourcePolicyBody):
    policy_hash: HashText


def policy_hash(body: SourcePolicyBody) -> str:
    projected = body.model_copy(update={"cache": body.cache.model_copy(update={"policy_hash": None})})
    value = JsonBoundary.model_validate(projected.model_dump(mode="json")).root
    return str(canonical_hash(value))


def bind_policy(body: SourcePolicyBody) -> SourcePolicySnapshot:
    digest = policy_hash(body)
    bound = body.model_copy(update={"cache": body.cache.model_copy(update={"policy_hash": digest})})
    return SourcePolicySnapshot.model_validate({**bound.model_dump(mode="json"), "policy_hash": digest})


def ordered_fallback(candidates: tuple[FallbackCandidate, ...], current_source_bundle_id: str | None = None) -> tuple[str, ...]:
    state_rank = {LifecycleState.PRIMARY: 0, LifecycleState.LIMITED: 1, LifecycleState.CANARY: 2}
    eligible = tuple(item for item in candidates if item.source_bundle_id != current_source_bundle_id and item.state in state_rank and item.capability_match and item.freshness_label == "fresh" and item.quality_label in ("high", "usable"))
    return tuple(item.source_bundle_id for item in sorted(eligible, key=lambda item: (state_rank[item.state], 0 if item.quality_label == "high" else 1, item.value_rank, item.cost_latency_rank, item.source_bundle_id)))


def verify_policy_projection(policy: SourcePolicySnapshot, candidates: tuple[FallbackCandidate, ...]) -> None:
    closed = policy.state in (LifecycleState.DISABLED, LifecycleState.RETIRING, LifecycleState.RETIRED, LifecycleState.EXPIRED)
    if closed and policy.traffic_share not in ("0", "0.00"):
        raise SourcePolicyError("DISABLE_TRAFFIC_NOT_ZERO", policy.source_bundle_id)
    if policy.cache.current and policy.cache.policy_hash is None:
        raise SourcePolicyError("CACHE_POLICY_HASH_MISSING", policy.source_bundle_id)
    if closed and policy.cache.current:
        raise SourcePolicyError("STALE_CACHE_POLICY_MISMATCH", policy.source_bundle_id)
    expected = () if closed else ordered_fallback(candidates, policy.source_bundle_id)
    eligible = set(ordered_fallback(candidates, policy.source_bundle_id))
    if any(item not in eligible for item in policy.fallback_order):
        raise SourcePolicyError("FALLBACK_USES_INELIGIBLE_SOURCE", policy.source_bundle_id)
    if policy.fallback_order != expected:
        by_id = {item.source_bundle_id: item for item in candidates}
        if len(policy.fallback_order) != len(expected):
            raise SourcePolicyError("FALLBACK_ORDER_MISMATCH", policy.source_bundle_id)
        first = next(index for index, item in enumerate(policy.fallback_order) if item != expected[index])
        if policy.fallback_order[first] not in by_id or expected[first] not in by_id:
            raise SourcePolicyError("FALLBACK_USES_INELIGIBLE_SOURCE", policy.source_bundle_id)
        declared = by_id[policy.fallback_order[first]]
        canonical = by_id[expected[first]]
        declared_key = (declared.state, declared.quality_label, declared.value_rank, declared.cost_latency_rank)
        canonical_key = (canonical.state, canonical.quality_label, canonical.value_rank, canonical.cost_latency_rank)
        if declared_key == canonical_key:
            raise SourcePolicyError("FALLBACK_TIE_BREAK_MISMATCH", policy.source_bundle_id)
        raise SourcePolicyError("FALLBACK_ORDER_MISMATCH", policy.source_bundle_id)
