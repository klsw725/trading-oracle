from __future__ import annotations

from src.v4.models import sha256_bytes
from src.v13.circuit_breaker import observe_attempt, prepare_session
from src.v13.codex import execute_recorded
from src.v13.models import StrictModel
from src.v13.prd02_models import BatchRequest, BatchScoringArtifact, RecordedResponse
from src.v13.prd03_models import (
    CircuitKey,
    CircuitObservation,
    CircuitState,
)
from src.v13.validation import market_fallback


class RoutedBatch(StrictModel):
    artifact: BatchScoringArtifact
    circuit_before: CircuitState
    circuit_after: CircuitState
    observed: bool


class RouteInput(StrictModel):
    request: BatchRequest
    recorded: RecordedResponse
    state: CircuitState
    key: CircuitKey


def route_recorded(inputs: RouteInput) -> RoutedBatch:
    request = inputs.request
    before = prepare_session(inputs.state, inputs.key)
    raw_hash = sha256_bytes(inputs.recorded.raw_response)
    if before.is_open:
        artifact = market_fallback(request, raw_hash, "CIRCUIT_OPEN", 0)
        return RoutedBatch(artifact=artifact, circuit_before=before,
            circuit_after=before, observed=False)
    if len(request.candidates) > request.invocation.max_candidates:
        artifact = market_fallback(request, raw_hash, "INPUT_OVERFLOW", 0)
        return RoutedBatch(artifact=artifact, circuit_before=before,
            circuit_after=before, observed=False)
    artifact = execute_recorded(request, inputs.recorded)
    succeeded = artifact.state != "market_quant_only"
    reason = artifact.fallbacks[0].reason_code if artifact.fallbacks else "PROVIDER_SUCCESS"
    after = observe_attempt(before, CircuitObservation(succeeded=succeeded,
        reason_code=reason))
    return RoutedBatch(artifact=artifact, circuit_before=before,
        circuit_after=after, observed=True)


def integrity_fallback(inputs: RouteInput, reason_code: str) -> RoutedBatch:
    before = prepare_session(inputs.state, inputs.key)
    artifact = market_fallback(inputs.request,
        sha256_bytes(inputs.recorded.raw_response), reason_code, 1)
    after = observe_attempt(before, CircuitObservation(succeeded=False,
        reason_code=reason_code))
    return RoutedBatch(artifact=artifact, circuit_before=before,
        circuit_after=after, observed=True)
