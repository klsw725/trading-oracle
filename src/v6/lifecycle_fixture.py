from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from .lifecycle_artifact import ConsensusLifecycleArtifact, build_lifecycle_artifact
from .lifecycle_compiler import build_assessment
from .lifecycle_evidence import ErrorOutcome, ErrorOutcomeBody, PromotionErrorWindow, PromotionErrorWindowBody, hash_body
from .lifecycle_incidents import DeliberationIncident, DeliberationManifest, DeliberationManifestBody
from .lifecycle_models import ApprovalAction, LifecycleInput, LifecycleState, OperatorApproval, OperatorApprovalBody
from .lifecycle_operations import ExpiryOperation, IncidentOperation, LifecycleOperation, PromotionOperation, RenewalOperation, ReopenAuthorization, ReopenAuthorizationBody, ReopenOperation, RetirementAssessmentOperation, RetirementOperation, RollbackOperation
from .lifecycle_retirement import RetirementRequired, RetirementRequiredBody
from .lifecycle_policy import ActiveCandidatePolicy, CandidateDeliberationPolicy, ConsensusPolicyArtifact, CurrentConsensusPolicy, CurrentConsensusPolicyBody, IncidentThresholdPolicy, PerspectiveWeight, weight_share
from .models import BoundaryModel, CandidateId, CandidateVersion, ContractInvariantError, HypothesisId, JsonBoundary
from .paper_artifact import PaperCohortArtifact, build_paper_artifact
from .paper_fixture import build_ledger, load_paper_fixture
from .paper_models import PaperCohortInput
from .paper_observations import HorizonObservation, HorizonObservationBody, ObservationBatch, ObservationBatchBody
from .lifecycle_registry import PolicyVersionEntry, PolicyVersionRegistry, PolicyVersionRegistryBody
from .lifecycle_context import CompilerContext


GOLDEN_WEIGHT = "0.250000"
GOLDEN_SHARE = "0.047619"
type Policy = CurrentConsensusPolicy | ConsensusPolicyArtifact


class ScenarioBranch(BoundaryModel):
    name: Literal["promotion_rejection", "expiry_renewal", "rollback_reopen", "retirement_after_two_rollbacks"]
    artifact_hashes: tuple[str, ...]


class LifecycleFixture(BoundaryModel):
    schema_version: Literal["v6.consensus-lifecycle-fixture.5"]
    fixture_name: Literal["consensus_lifecycle_complete"]
    operations: tuple[LifecycleOperation, ...]
    artifacts: tuple[ConsensusLifecycleArtifact, ...]
    branches: tuple[ScenarioBranch, ...]
    unrelated_candidate_id: str


@dataclass(frozen=True, slots=True)
class ApprovalSpec:
    lifecycle_input: LifecycleInput
    action: ApprovalAction
    current: Policy
    output_version: str
    state: LifecycleState
    prior_history_hash: str | None = None


def bound_policy(body: CurrentConsensusPolicyBody) -> CurrentConsensusPolicy:
    return CurrentConsensusPolicy.model_validate({**body.model_dump(mode="json"), "policy_hash": hash_body(body)})


def unrelated_candidate(weights: tuple[PerspectiveWeight, ...]) -> ActiveCandidatePolicy:
    return ActiveCandidatePolicy(candidate_id=CandidateId("pcand_v6_unrelated_quality"), candidate_version=CandidateVersion("unrelated_quality.1.0"), hypothesis_id=HypothesisId("hyp_v6_unrelated_quality_001"), lifecycle_state=LifecycleState.LIMITED_PRODUCTION, source_paper_artifact_hash=f"sha256:{'1' * 64}", operator_approval_id="approval_unrelated", operator_approval_hash=f"sha256:{'2' * 64}", initial_weight="0.100000", total_valid_weight_share=weight_share(weights, "0.100000"), approval_start_session_ordinal=10, approval_end_session_ordinal=69, rollback_policy_version="consensus_policy_genesis", rollback_policy_hash=f"sha256:{'3' * 64}", deliberation=CandidateDeliberationPolicy(), incident_thresholds=IncidentThresholdPolicy(), source_ttl_policies=())


def base_policy(production_hash: str) -> CurrentConsensusPolicy:
    weights = tuple(PerspectiveWeight(perspective=name, weight="1.000000") for name in ("kwangsoo", "ouroboros", "quant", "macro", "value"))
    body = CurrentConsensusPolicyBody(schema_version="v6.consensus-policy-snapshot.2", policy_version="consensus_policy_v6_previous", scorer_version="consensus-scorer-current", deliberator_version="deliberator-current", base_perspectives=("kwangsoo", "ouroboros", "quant", "macro", "value"), incumbent_weights=weights, active_candidates=(unrelated_candidate(weights),), incumbent_deliberation_policy_hash=f"sha256:{'a' * 64}", observed_production_snapshot_hash=production_hash)
    return bound_policy(body)


def policy_registry(policy: Policy) -> PolicyVersionRegistry:
    versions = {policy.policy_version: policy.policy_hash}
    if isinstance(policy, ConsensusPolicyArtifact): versions[policy.source_policy_version] = policy.source_policy_hash
    entries = tuple(PolicyVersionEntry(policy_version=version, policy_hash=versions[version]) for version in sorted(versions))
    body = PolicyVersionRegistryBody(schema_version="v6.consensus_lifecycle.policy-registry.1", persistence_scope="trading-oracle-v6-consensus-policy", revision=1, previous_registry_hash=None, entries=entries)
    return PolicyVersionRegistry.model_validate({**body.model_dump(mode="json"), "registry_hash": hash_body(body)})


def lifecycle_input(paper: PaperCohortArtifact, operation: str, ordinal: int, policy: Policy, registry: PolicyVersionRegistry | None = None) -> LifecycleInput:
    occurred_at = datetime.fromisoformat("2026-08-06T10:00:00+09:00") + timedelta(minutes=ordinal)
    return LifecycleInput(schema_version="v6.consensus_lifecycle.input.1", operation_id=f"lifecycle_op_{operation}", idempotency_key=f"{operation}|{paper.paper_input.candidate_id}|{paper.paper_input.candidate_version}", candidate_id=paper.paper_input.candidate_id, candidate_version=paper.paper_input.candidate_version, hypothesis_id=paper.paper_input.hypothesis_id, current_session_ordinal=ordinal, occurred_at=occurred_at, policy_registry=registry or policy_registry(policy))


def target_candidate(policy: Policy) -> ActiveCandidatePolicy:
    candidate = next((item for item in policy.active_candidates if item.candidate_id == "pcand_v6_working_capital_quality"), None)
    if candidate is None: raise ContractInvariantError("fixture target candidate missing")
    return candidate


def approval(spec: ApprovalSpec) -> OperatorApproval:
    value, action, current = spec.lifecycle_input, spec.action, spec.current
    target = LifecycleState.LIMITED_PRODUCTION if action in (ApprovalAction.PROMOTE, ApprovalAction.RENEW) else LifecycleState.ROLLED_BACK if action is ApprovalAction.ROLLBACK else LifecycleState.RETIRED
    rollback_version = current.policy_version if action is ApprovalAction.PROMOTE else target_candidate(current).rollback_policy_version if action in (ApprovalAction.RENEW, ApprovalAction.ROLLBACK) else None
    rollback_hash = current.policy_hash if action is ApprovalAction.PROMOTE else target_candidate(current).rollback_policy_hash if action in (ApprovalAction.RENEW, ApprovalAction.ROLLBACK) else None
    body = OperatorApprovalBody(schema_version="v6.consensus_lifecycle.approval.1", approval_id=f"approval_{value.operation_id}", operator_id="operator_fixture", approved_at=value.occurred_at, action=action, candidate_id=value.candidate_id, candidate_version=value.candidate_version, from_state=spec.state, to_state=target, policy_version=spec.output_version, initial_weight=GOLDEN_WEIGHT if action in (ApprovalAction.PROMOTE, ApprovalAction.RENEW) else None, approval_start_session_ordinal=value.current_session_ordinal if action in (ApprovalAction.PROMOTE, ApprovalAction.RENEW) else None, approval_duration_market_sessions=60 if action in (ApprovalAction.PROMOTE, ApprovalAction.RENEW) else None, rollback_policy_version=rollback_version, rollback_policy_hash=rollback_hash, prior_history_hash=spec.prior_history_hash, reason=f"explicit {action.value}")
    return OperatorApproval.model_validate({**body.model_dump(mode="json"), "approval_hash": hash_body(body)})


def error_window(paper_hash: str, records: tuple[tuple[str, str], ...], error_counts: tuple[int, int] = (93, 87)) -> PromotionErrorWindow:
    outcomes: list[ErrorOutcome] = []
    for index, (sample_id, record_hash) in enumerate(records):
        body = ErrorOutcomeBody(schema_version="v6.lifecycle-error-outcome.1", sample_id=sample_id, paper_horizon_record_hash=record_hash, candidate_error=index < error_counts[0], baseline_error=index < error_counts[1])
        outcomes.append(ErrorOutcome.model_validate({**body.model_dump(mode="json"), "record_hash": hash_body(body)}))
    body = PromotionErrorWindowBody(schema_version="v6.lifecycle-promotion-window.1", paper_artifact_hash=paper_hash, market="KR", window_end_session_id="KRX_072", records=tuple(outcomes))
    return PromotionErrorWindow.model_validate({**body.model_dump(mode="json"), "window_hash": hash_body(body)})


def incident(paper: PaperCohortArtifact, active: ConsensusPolicyArtifact, prior: ConsensusLifecycleArtifact, suffix: str, ordinal: int, context: CompilerContext) -> IncidentOperation:
    value = lifecycle_input(paper, f"incident_{suffix}", ordinal, active, context.policy_registry)
    body = DeliberationManifestBody(schema_version="v6.lifecycle-deliberation-manifest.1", candidate_id=value.candidate_id, candidate_version=value.candidate_version, policy_version=active.policy_version, candidate_reasoning_hash=f"sha256:{'4' * 64}", incumbent_prompt_input_hashes=(f"sha256:{'4' * 64}",), candidate_reasoning_as_prompt_input=False)
    manifest = DeliberationManifest.model_validate({**body.model_dump(mode="json"), "evidence_hash": hash_body(body)})
    return IncidentOperation(operation_type="incident", lifecycle_input=value, current_policy=active, prior_history=prior.history, expected_prior_history_hash=prior.history.history_hash, output_policy_version=f"consensus_policy_incident_review_{suffix}", source_paper_artifact=paper, report=DeliberationIncident(incident_type="deliberation_contamination", incident_id=f"incident_{suffix}", evidence=manifest))


def promote(paper: PaperCohortArtifact, current: CurrentConsensusPolicy, window: PromotionErrorWindow, suffix: str, ordinal: int, context: CompilerContext, prior: ConsensusLifecycleArtifact | None = None) -> PromotionOperation:
    prior_history = prior.history if prior else None
    value = lifecycle_input(paper, f"promotion_{suffix}", ordinal, current, context.policy_registry)
    return PromotionOperation(operation_type="promotion", lifecycle_input=value, paper_artifact=paper, current_policy=current, approval=approval(ApprovalSpec(value, ApprovalAction.PROMOTE, current, f"consensus_policy_limited_{suffix}", LifecycleState.PAPER_READY, prior_history.history_hash if prior_history else None)), error_window=window, prior_history=prior_history, expected_prior_history_hash=prior_history.history_hash if prior_history else None)


def rollback(paper: PaperCohortArtifact, active: ConsensusPolicyArtifact, base: CurrentConsensusPolicy, incident_operation: IncidentOperation, prior: ConsensusLifecycleArtifact, suffix: str, ordinal: int, context: CompilerContext) -> RollbackOperation:
    value = lifecycle_input(paper, f"rollback_{suffix}", ordinal, active, context.policy_registry)
    return RollbackOperation(operation_type="rollback", lifecycle_input=value, current_policy=active, prior_history=prior.history, expected_prior_history_hash=prior.history.history_hash, rollback_policy=base, approval=approval(ApprovalSpec(value, ApprovalAction.ROLLBACK, active, "unused", prior.history.current_state, prior.history.history_hash)), assessment=build_assessment(incident_operation, prior.compiler_context))


def fresh_paper_artifact(paper: PaperCohortArtifact, generated_at: str) -> PaperCohortArtifact:
    run_id = f"{paper.paper_input.run_id}_reopen_001"
    source_batch = paper.paper_input.observation_batches[0]
    batch_id = f"{source_batch.batch_id}_reopen_001"
    batch_body = ObservationBatchBody.model_validate({**source_batch.model_dump(mode="json", exclude={"batch_hash"}), "batch_id": batch_id, "run_id": run_id})
    batch = ObservationBatch.model_validate({**batch_body.model_dump(mode="json"), "batch_hash": hash_body(batch_body)})
    horizons: list[HorizonObservation] = []
    for source in paper.paper_input.horizon_observations:
        body = HorizonObservationBody.model_validate({**source.model_dump(mode="json", exclude={"observation_hash"}), "batch_id": batch_id, "run_id": run_id})
        horizons.append(HorizonObservation.model_validate({**body.model_dump(mode="json"), "observation_hash": hash_body(body)}))
    value = PaperCohortInput.model_validate({**paper.paper_input.model_dump(mode="json"), "generated_at": generated_at, "run_id": run_id, "observation_batches": (batch,), "horizon_observations": tuple(horizons)})
    return build_paper_artifact(value, build_ledger(value))


def build_fixture(paper_fixture_path: Path | None = None) -> LifecycleFixture:
    source = load_paper_fixture(paper_fixture_path or Path("docs/specs/v6/fixtures/prd03-paper-cohort.json")); paper = build_paper_artifact(source.paper_input, source.ledger); base = base_policy(paper.production_before_hash)
    five = next(item for item in paper.paper_input.horizon_observations if item.horizon_market_sessions == 5); mature = tuple((item.sample_id, item.record_hash) for item in five.records if item.mature); good = error_window(paper.artifact_hash, mature)
    context0 = CompilerContext(schema_version="v6.consensus_lifecycle.compiler-context.1", policy_registry=policy_registry(base))
    rejected_op = promote(paper, base, error_window(paper.artifact_hash, mature, (120, 87)), "rejected", 100, context0); rejected = build_lifecycle_artifact(rejected_op, context0)
    promoted_op = promote(paper, base, good, "first", 100, context0); promoted = build_lifecycle_artifact(promoted_op, context0); active1 = promoted.policy
    if not isinstance(active1, ConsensusPolicyArtifact): raise ContractInvariantError("promotion policy missing")
    context1 = context0.model_copy(update={"policy_registry": promoted.history.policy_registry})
    expiry_input = lifecycle_input(paper, "expiry", 160, active1, context1.policy_registry); expiry_op = ExpiryOperation(operation_type="expiry", lifecycle_input=expiry_input, current_policy=active1, prior_history=promoted.history, expected_prior_history_hash=promoted.history.history_hash, output_policy_version="consensus_policy_review_1"); expiry = build_lifecycle_artifact(expiry_op, context1); review = expiry.policy
    if not isinstance(review, ConsensusPolicyArtifact): raise ContractInvariantError("expiry policy missing")
    context2 = context1.model_copy(update={"policy_registry": expiry.history.policy_registry})
    renew_input = lifecycle_input(paper, "renewal", 161, review, context2.policy_registry); renew_op = RenewalOperation(operation_type="renewal", lifecycle_input=renew_input, current_policy=review, prior_history=expiry.history, expected_prior_history_hash=expiry.history.history_hash, approval=approval(ApprovalSpec(renew_input, ApprovalAction.RENEW, review, "consensus_policy_renewed_1", LifecycleState.RENEWAL_REVIEW, expiry.history.history_hash))); renewed = build_lifecycle_artifact(renew_op, context2)
    context3 = context2.model_copy(update={"policy_registry": renewed.history.policy_registry})
    incident1_op = incident(paper, active1, promoted, "first", 120, context3); incident1 = build_lifecycle_artifact(incident1_op, context3)
    context4 = context3.model_copy(update={"policy_registry": incident1.history.policy_registry})
    rollback1_op = rollback(paper, active1, base, incident1_op, incident1, "first", 121, context4); rollback1 = build_lifecycle_artifact(rollback1_op, context4)
    rollback_event = rollback1.history.events[-1]; fresh_paper = fresh_paper_artifact(paper, (datetime.fromisoformat(rollback_event.occurred_at) + timedelta(seconds=30)).isoformat())
    reopen_input = lifecycle_input(fresh_paper, "reopen", 122, base, context4.policy_registry); reopen_body = ReopenAuthorizationBody(schema_version="v6.consensus_lifecycle.reopen-authorization.1", candidate_id=reopen_input.candidate_id, candidate_version=reopen_input.candidate_version, prior_history_hash=rollback1.history.history_hash, rollback_event_hash=rollback_event.event_hash, prior_source_paper_artifact_hash=paper.artifact_hash, paper_artifact_hash=fresh_paper.artifact_hash); reopen_auth = ReopenAuthorization.model_validate({**reopen_body.model_dump(mode="json"), "authorization_hash": hash_body(reopen_body)}); reopen_op = ReopenOperation(operation_type="reopen", lifecycle_input=reopen_input, current_policy=base, prior_history=rollback1.history, expected_prior_history_hash=rollback1.history.history_hash, paper_artifact=fresh_paper, authorization=reopen_auth); reopened = build_lifecycle_artifact(reopen_op, context4)
    fresh_five = next(item for item in fresh_paper.paper_input.horizon_observations if item.horizon_market_sessions == 5); fresh_mature = tuple((item.sample_id, item.record_hash) for item in fresh_five.records if item.mature); fresh_good = error_window(fresh_paper.artifact_hash, fresh_mature)
    promote2_op = promote(fresh_paper, base, fresh_good, "second", 180, context4, reopened); promoted2 = build_lifecycle_artifact(promote2_op, context4); active2 = promoted2.policy
    if not isinstance(active2, ConsensusPolicyArtifact): raise ContractInvariantError("second promotion policy missing")
    context5 = context4.model_copy(update={"policy_registry": promoted2.history.policy_registry})
    incident2_op = incident(fresh_paper, active2, promoted2, "second", 200, context5); incident2 = build_lifecycle_artifact(incident2_op, context5)
    context6 = context5.model_copy(update={"policy_registry": incident2.history.policy_registry})
    rollback2_op = rollback(fresh_paper, active2, base, incident2_op, incident2, "second", 210, context6); rollback2 = build_lifecycle_artifact(rollback2_op, context6)
    assess_input = lifecycle_input(paper, "retirement_assessment", 211, base, context6.policy_registry); assess_op = RetirementAssessmentOperation(operation_type="retirement_assessment", lifecycle_input=assess_input, current_policy=base, prior_history=rollback2.history, expected_prior_history_hash=rollback2.history.history_hash); assessed = build_lifecycle_artifact(assess_op, context6)
    retire_input = lifecycle_input(paper, "retirement", 212, base, context6.policy_registry); trigger_body = RetirementRequiredBody(trigger_type="retirement_required", assessment_event_hash=assessed.history.head_event_hash, history_hash=assessed.history.history_hash); trigger = RetirementRequired.model_validate({**trigger_body.model_dump(mode="json"), "trigger_hash": hash_body(trigger_body)}); retire_op = RetirementOperation(operation_type="retirement", lifecycle_input=retire_input, current_policy=base, prior_history=assessed.history, expected_prior_history_hash=assessed.history.history_hash, approval=approval(ApprovalSpec(retire_input, ApprovalAction.RETIRE, base, "consensus_policy_retired_1", LifecycleState.ROLLED_BACK, assessed.history.history_hash)), trigger=trigger, source_paper_artifact=fresh_paper); retired = build_lifecycle_artifact(retire_op, context6)
    operations: tuple[LifecycleOperation, ...] = (rejected_op, promoted_op, expiry_op, renew_op, incident1_op, rollback1_op, reopen_op, promote2_op, incident2_op, rollback2_op, assess_op, retire_op)
    artifacts = (rejected, promoted, expiry, renewed, incident1, rollback1, reopened, promoted2, incident2, rollback2, assessed, retired)
    branches = (ScenarioBranch(name="promotion_rejection", artifact_hashes=(rejected.artifact_hash,)), ScenarioBranch(name="expiry_renewal", artifact_hashes=(promoted.artifact_hash, expiry.artifact_hash, renewed.artifact_hash)), ScenarioBranch(name="rollback_reopen", artifact_hashes=(promoted.artifact_hash, incident1.artifact_hash, rollback1.artifact_hash, reopened.artifact_hash)), ScenarioBranch(name="retirement_after_two_rollbacks", artifact_hashes=tuple(item.artifact_hash for item in (promoted, incident1, rollback1, reopened, promoted2, incident2, rollback2, assessed, retired))))
    return LifecycleFixture(schema_version="v6.consensus-lifecycle-fixture.5", fixture_name="consensus_lifecycle_complete", operations=operations, artifacts=artifacts, branches=branches, unrelated_candidate_id="pcand_v6_unrelated_quality")


def load_lifecycle_fixture(path: Path) -> LifecycleFixture:
    try: return LifecycleFixture.model_validate_json(path.read_bytes())
    except ValidationError as error: raise ContractInvariantError(f"invalid lifecycle fixture: {error}") from error


def fixture_json(value: LifecycleFixture) -> bytes:
    return JsonBoundary.model_validate(value.model_dump(mode="json")).model_dump_json().encode("utf-8")
