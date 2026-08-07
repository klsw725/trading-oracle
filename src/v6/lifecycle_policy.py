from decimal import Decimal, ROUND_HALF_EVEN
from typing import Literal, Self

from pydantic import model_validator

from .lifecycle_evidence import hash_body
from .lifecycle_models import BASE_PERSPECTIVES, BasePerspective, LifecycleState, Probability6
from .models import BoundaryModel, CandidateId, CandidateVersion, ContractInvariantError, HypothesisId
from .offline_models import ContentHash, Decimal6


class PerspectiveWeight(BoundaryModel):
    perspective: BasePerspective
    weight: Decimal6


class CandidateDeliberationPolicy(BoundaryModel):
    candidate_can_reconsider: Literal[True] = True
    candidate_reasoning_as_prompt_input: Literal[False] = False
    incumbents_can_be_forced_by_candidate: Literal[False] = False


class IncidentThresholdPolicy(BoundaryModel):
    promotion_error_delta_ceiling: Literal["0.030000"] = "0.030000"
    rollback_error_delta_threshold: Literal["0.080000"] = "0.080000"
    rollback_error_min_mature_samples: Literal[50] = 50
    parser_failure_rate_threshold: Literal["0.030000"] = "0.030000"
    parser_failure_attempt_window: Literal[100] = 100
    candidate_na_threshold: Literal["0.200000"] = "0.200000"
    target_na_threshold: Literal["0.250000"] = "0.250000"
    latency_consecutive_failure_windows: Literal[2] = 2
    absolute_weight_cap: Literal["0.250000"] = "0.250000"
    total_valid_weight_share_cap: Literal["0.050000"] = "0.050000"


class SourceTtlPolicy(BoundaryModel):
    source_id: str
    source_contract: str
    ttl_market_sessions: Literal[20] = 20


class ActiveCandidatePolicy(BoundaryModel):
    candidate_id: CandidateId
    candidate_version: CandidateVersion
    hypothesis_id: HypothesisId
    lifecycle_state: Literal[LifecycleState.LIMITED_PRODUCTION, LifecycleState.RENEWAL_REVIEW]
    source_paper_artifact_hash: ContentHash
    operator_approval_id: str
    operator_approval_hash: ContentHash
    initial_weight: Decimal6
    total_valid_weight_share: Probability6
    approval_start_session_ordinal: int
    approval_end_session_ordinal: int
    rollback_policy_version: str
    rollback_policy_hash: ContentHash
    deliberation: CandidateDeliberationPolicy
    incident_thresholds: IncidentThresholdPolicy
    source_ttl_policies: tuple[SourceTtlPolicy, ...]

    @model_validator(mode="after")
    def valid_duration(self) -> Self:
        if not 1 <= self.approval_end_session_ordinal - self.approval_start_session_ordinal + 1 <= 60:
            raise ContractInvariantError("active candidate approval duration must be 1 to 60 sessions")
        return self


class CurrentConsensusPolicyBody(BoundaryModel):
    schema_version: Literal["v6.consensus-policy-snapshot.2"]
    policy_version: str
    scorer_version: str
    deliberator_version: str
    base_perspectives: tuple[BasePerspective, ...]
    incumbent_weights: tuple[PerspectiveWeight, ...]
    active_candidates: tuple[ActiveCandidatePolicy, ...]
    incumbent_deliberation_policy_hash: ContentHash
    observed_production_snapshot_hash: ContentHash

    @model_validator(mode="after")
    def exact_inventory(self) -> Self:
        if self.base_perspectives != BASE_PERSPECTIVES or tuple(item.perspective for item in self.incumbent_weights) != BASE_PERSPECTIVES:
            raise ContractInvariantError("policy requires exact ordered base perspectives")
        identities = tuple((item.candidate_id, item.candidate_version) for item in self.active_candidates)
        if len(set(identities)) != len(identities) or len({item.candidate_id for item in self.active_candidates}) != len(self.active_candidates):
            raise ContractInvariantError("policy permits one active version per candidate")
        if any(Decimal(item.weight) <= 0 for item in self.incumbent_weights):
            raise ContractInvariantError("incumbent weights must be positive")
        for candidate in self.active_candidates:
            if candidate.total_valid_weight_share != weight_share(self.incumbent_weights, candidate.initial_weight):
                raise ContractInvariantError("active candidate weight share mismatch")
        return self


class CurrentConsensusPolicy(CurrentConsensusPolicyBody):
    policy_hash: ContentHash

    @model_validator(mode="after")
    def hash_bound(self) -> Self:
        body = CurrentConsensusPolicyBody.model_validate(self.model_dump(mode="json", exclude={"policy_hash"}))
        if self.policy_hash != hash_body(body):
            raise ContractInvariantError("current policy hash mismatch")
        return self


class ConsensusPolicyBody(BoundaryModel):
    schema_version: Literal["v6.consensus_policy.2"]
    policy_version: str
    source_policy_version: str
    source_policy_hash: ContentHash
    scorer_version: str
    deliberator_version: str
    base_perspectives: tuple[BasePerspective, ...]
    incumbent_weights: tuple[PerspectiveWeight, ...]
    active_candidates: tuple[ActiveCandidatePolicy, ...]
    incumbent_deliberation_policy_hash: ContentHash
    observed_production_snapshot_hash: ContentHash
    authorizing_operation_id: str
    idempotency_key: str
    automatic_permanent_perspective: Literal[False]
    runtime_adoption: Literal["not_automatically_wired"]

    @model_validator(mode="after")
    def immutable_shape(self) -> Self:
        if self.policy_version == self.source_policy_version:
            raise ContractInvariantError("policy emission requires a new version")
        _ = CurrentConsensusPolicyBody(schema_version="v6.consensus-policy-snapshot.2", policy_version=self.policy_version, scorer_version=self.scorer_version, deliberator_version=self.deliberator_version, base_perspectives=self.base_perspectives, incumbent_weights=self.incumbent_weights, active_candidates=self.active_candidates, incumbent_deliberation_policy_hash=self.incumbent_deliberation_policy_hash, observed_production_snapshot_hash=self.observed_production_snapshot_hash)
        return self


class ConsensusPolicyArtifact(ConsensusPolicyBody):
    policy_hash: ContentHash

    @model_validator(mode="after")
    def hash_bound(self) -> Self:
        body = ConsensusPolicyBody.model_validate(self.model_dump(mode="json", exclude={"policy_hash"}))
        if self.policy_hash != hash_body(body):
            raise ContractInvariantError("consensus policy hash mismatch")
        return self


def weight_share(weights: tuple[PerspectiveWeight, ...], initial_weight: str) -> str:
    weight = Decimal(initial_weight)
    total = sum((Decimal(item.weight) for item in weights), Decimal(0))
    raw = weight / (total + weight)
    if weight <= 0 or weight > Decimal("0.250000") or raw > Decimal("0.050000"):
        raise ContractInvariantError("candidate weight exceeds lifecycle cap")
    return f"{raw.quantize(Decimal('0.000001'), rounding=ROUND_HALF_EVEN):.6f}"
