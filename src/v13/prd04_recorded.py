from __future__ import annotations

from src.v11.canonical import money
from src.v4.models import JsonValue, canonical_json
from src.v13.models import CandidateEvidence
from src.v13.policy import build_policy
from src.v13.prd02_models import BatchBuildInput, BatchRequest, ContextSnapshot, RecordedResponse
from src.v13.prompts import build_batch_request


def request_for(
    candidates: tuple[CandidateEvidence, ...], context: ContextSnapshot
) -> BatchRequest:
    return build_batch_request(BatchBuildInput(candidates=candidates, context=context,
        policy=build_policy(), max_candidates=100))


def response_for(request: BatchRequest) -> RecordedResponse:
    items: list[JsonValue] = [{"candidate_id": candidate.candidate_id,
        "score": money(candidate.deterministic_score), "veto_code": None,
        "abstain": False, "confidence": "0.50",
        "source_artifact_ids": [], "reason": "recorded deterministic fixture"}
        for candidate in sorted(request.candidates, key=lambda item: item.candidate_id)]
    envelope: JsonValue = {"schema_version": request.identity.schema_version,
        "batch_id": request.identity.batch_id, "market": request.identity.market.value,
        "cutoff": request.identity.cutoff.isoformat(),
        "prompt_hash": request.prompt.prompt_hash, "items": items}
    return RecordedResponse(outcome="response", model_id=request.identity.model_id,
        raw_response=canonical_json(envelope))
