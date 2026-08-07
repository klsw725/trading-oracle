from src.v4.models import JsonValue, canonical_hash, sha256_bytes

from .models import JsonBoundary
from .paper_assignment_types import AssignmentInput, AssignmentResult
from .paper_models import AssignmentPolicy, AssignmentPolicyBody


def policy_body_json(policy: AssignmentPolicyBody) -> JsonValue:
    return JsonBoundary.model_validate(policy.model_dump(mode="json")).root


def build_policy(body: AssignmentPolicyBody) -> AssignmentPolicy:
    return AssignmentPolicy.model_validate({**body.model_dump(mode="json"), "policy_hash": canonical_hash(policy_body_json(body))})


def verify_policy(policy: AssignmentPolicy) -> bool:
    body = AssignmentPolicyBody.model_validate(policy.model_dump(mode="json", exclude={"policy_hash"}))
    return policy.policy_hash == canonical_hash(policy_body_json(body))


def assign(candidate_id: str, candidate_version: str, value: AssignmentInput, policy: AssignmentPolicy) -> AssignmentResult:
    seed = "|".join((candidate_id, candidate_version, value.production_decision_id, value.emitted_at, value.ticker, value.market, policy.policy_salt))
    assignment_hash = sha256_bytes(seed.encode("utf-8"))
    bucket = int(assignment_hash.removeprefix("sha256:")[:8], 16) % 10_000
    market_eligible = "ALL" in policy.eligible_markets or value.market in policy.eligible_markets
    action_eligible = value.production_action in policy.eligible_actions
    return AssignmentResult(assignment_hash=assignment_hash, assignment_bucket=bucket, assigned_to_paper=market_eligible and action_eligible and bucket < policy.sample_rate_bps)
