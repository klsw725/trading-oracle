from __future__ import annotations

from src.v4.models import sha256_bytes
from src.v9.contract import V9ContractError
from src.v13.prd02_models import BatchRequest, BatchScoringArtifact, RecordedResponse
from src.v13.schema import parse_recorded_response
from src.v13.validation import market_fallback, validate_envelope


def execute_recorded(
    request: BatchRequest, recorded: RecordedResponse
) -> BatchScoringArtifact:
    raw_hash = sha256_bytes(recorded.raw_response)
    if (len(request.candidates) > request.invocation.max_candidates
            or len(request.prompt.canonical_bytes) > request.invocation.max_input_bytes):
        return market_fallback(request, raw_hash, "INPUT_OVERFLOW", 0)
    if recorded.model_id != request.identity.model_id:
        return market_fallback(request, raw_hash, "MODEL_MISMATCH", 1)
    if recorded.outcome != "response":
        return market_fallback(request, raw_hash, recorded.outcome.upper(), 1)
    try:
        parsed = parse_recorded_response(recorded.raw_response)
    except V9ContractError:
        return market_fallback(request, raw_hash, "STRICT_JSON_FAILURE", 1)
    return validate_envelope(request, parsed, raw_hash)
