from typing import Literal, Self

from pydantic import model_validator

from .lifecycle_evidence import MonitoringWindow, PromotionErrorWindow, hash_body
from .lifecycle_policy import CurrentConsensusPolicy
from .models import BoundaryModel, CandidateId, CandidateVersion, ContractInvariantError
from .offline_models import ContentHash, Decimal6


class MonitoringEvidenceBody(BoundaryModel):
    schema_version: Literal["v6.lifecycle-monitoring-evidence.1"]
    candidate_id: CandidateId
    candidate_version: CandidateVersion
    policy_version: str
    market: Literal["KR", "US"]
    windows: tuple[MonitoringWindow, ...]

    @model_validator(mode="after")
    def identity_and_inventory(self) -> Self:
        if not self.windows:
            raise ContractInvariantError("monitoring evidence requires windows")
        expected = (self.candidate_id, self.candidate_version, self.policy_version, self.market)
        if any((item.candidate_id, item.candidate_version, item.policy_version, item.market) != expected for item in self.windows):
            raise ContractInvariantError("monitoring window identity mismatch")
        if tuple(item.window_index for item in self.windows) != tuple(range(self.windows[0].window_index, self.windows[0].window_index + len(self.windows))):
            raise ContractInvariantError("monitoring windows must be ordered and consecutive")
        for prior, current in zip(self.windows, self.windows[1:]):
            if current.previous_window_hash != prior.window_hash:
                raise ContractInvariantError("monitoring window link mismatch")
        attempts = tuple(record.attempt_id for window in self.windows for record in window.records)
        decisions = tuple(record.production_decision_id for window in self.windows for record in window.records)
        if len(set(attempts)) != len(attempts) or len(set(decisions)) != len(decisions):
            raise ContractInvariantError("monitoring records must be globally unique")
        return self


class MonitoringEvidence(MonitoringEvidenceBody):
    evidence_hash: ContentHash

    @model_validator(mode="after")
    def hash_bound(self) -> Self:
        body = MonitoringEvidenceBody.model_validate(self.model_dump(mode="json", exclude={"evidence_hash"}))
        if self.evidence_hash != hash_body(body):
            raise ContractInvariantError("monitoring evidence hash mismatch")
        return self


class DeliberationManifestBody(BoundaryModel):
    schema_version: Literal["v6.lifecycle-deliberation-manifest.1"]
    candidate_id: CandidateId
    candidate_version: CandidateVersion
    policy_version: str
    candidate_reasoning_hash: ContentHash
    incumbent_prompt_input_hashes: tuple[ContentHash, ...]
    candidate_reasoning_as_prompt_input: Literal[False]


class DeliberationManifest(DeliberationManifestBody):
    evidence_hash: ContentHash

    @model_validator(mode="after")
    def hash_bound(self) -> Self:
        body = DeliberationManifestBody.model_validate(self.model_dump(mode="json", exclude={"evidence_hash"}))
        if self.evidence_hash != hash_body(body):
            raise ContractInvariantError("deliberation evidence hash mismatch")
        return self


class ObservedCapEvidenceBody(BoundaryModel):
    schema_version: Literal["v6.lifecycle-observed-cap.1"]
    candidate_id: CandidateId
    candidate_version: CandidateVersion
    policy_version: str
    observed_policy_hash: ContentHash
    emitted_weight: Decimal6
    emitted_share: Decimal6


class ObservedCapEvidence(ObservedCapEvidenceBody):
    evidence_hash: ContentHash

    @model_validator(mode="after")
    def hash_bound(self) -> Self:
        body = ObservedCapEvidenceBody.model_validate(self.model_dump(mode="json", exclude={"evidence_hash"}))
        if self.evidence_hash != hash_body(body):
            raise ContractInvariantError("cap evidence hash mismatch")
        return self


class DirtyPolicyPairBody(BoundaryModel):
    schema_version: Literal["v6.lifecycle-dirty-policy-pair.1"]
    recorded_policy: CurrentConsensusPolicy
    observed_policy: CurrentConsensusPolicy

    @model_validator(mode="after")
    def same_version_mutation(self) -> Self:
        if self.recorded_policy.policy_version != self.observed_policy.policy_version or self.recorded_policy.policy_hash == self.observed_policy.policy_hash:
            raise ContractInvariantError("dirty policy evidence requires same-version distinct hashes")
        return self


class DirtyPolicyPair(DirtyPolicyPairBody):
    evidence_hash: ContentHash

    @model_validator(mode="after")
    def hash_bound(self) -> Self:
        body = DirtyPolicyPairBody.model_validate(self.model_dump(mode="json", exclude={"evidence_hash"}))
        if self.evidence_hash != hash_body(body):
            raise ContractInvariantError("dirty policy evidence hash mismatch")
        return self


class ErrorRateIncident(BoundaryModel):
    incident_type: Literal["error_rate_spike"]
    incident_id: str
    candidate_id: CandidateId
    candidate_version: CandidateVersion
    policy_version: str
    error_window: PromotionErrorWindow


class MonitoringIncident(BoundaryModel):
    incident_type: Literal["parser_failure_spike", "na_rate_spike", "latency_spike"]
    incident_id: str
    evidence: MonitoringEvidence


class DeliberationIncident(BoundaryModel):
    incident_type: Literal["deliberation_contamination"]
    incident_id: str
    evidence: DeliberationManifest


class CapIncident(BoundaryModel):
    incident_type: Literal["weight_cap_breach"]
    incident_id: str
    evidence: ObservedCapEvidence


class DirtyPolicyIncident(BoundaryModel):
    incident_type: Literal["dirty_policy_mutation"]
    incident_id: str
    evidence: DirtyPolicyPair


type IncidentReport = ErrorRateIncident | MonitoringIncident | DeliberationIncident | CapIncident | DirtyPolicyIncident
