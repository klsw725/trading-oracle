from __future__ import annotations

from typing import Literal

from src.v11.canonical import canonical_hash, model_json
from src.v4.models import JsonValue, canonical_json
from src.v13.fallback import RouteInput, RoutedBatch, route_recorded
from src.v13.models import RouterRunManifest, RouterSelection, StrictModel
from src.v13.prd02_models import BatchRequest, RecordedResponse
from src.v13.prd03_models import CircuitKey, CircuitState
from src.v13.selection import run_router


class NoCallProvider(StrictModel):
    call_count: Literal[0] = 0

    def call(self) -> None:
        raise AssertionError("replay provider call is forbidden")


class ReplayRecord(StrictModel):
    request: BatchRequest
    recorded_response: RecordedResponse
    routed: RoutedBatch
    router_manifest: RouterRunManifest
    decision_bytes: bytes
    artifact_hash: str
    circuit_key: CircuitKey


class ReplayResult(StrictModel):
    provider_call_count: Literal[0]
    decision_bytes: bytes
    byte_identical: bool
    artifact_identical: bool
    circuit_identical: bool
    replay_hash: str


class RecordInput(StrictModel):
    request: BatchRequest
    recorded_response: RecordedResponse
    circuit_state: CircuitState
    circuit_key: CircuitKey
    router_manifest: RouterRunManifest


def record_decision(inputs: RecordInput) -> ReplayRecord:
    routed = route_recorded(RouteInput(request=inputs.request,
        recorded=inputs.recorded_response, state=inputs.circuit_state,
        key=inputs.circuit_key))
    selection = _selection(inputs.router_manifest, routed)
    decision_bytes = canonical_json(model_json(selection))
    return ReplayRecord(request=inputs.request,
        recorded_response=inputs.recorded_response, routed=routed,
        router_manifest=inputs.router_manifest, decision_bytes=decision_bytes,
        artifact_hash=canonical_hash(model_json(routed.artifact)),
        circuit_key=inputs.circuit_key)


def replay_decision(record: ReplayRecord, provider: NoCallProvider) -> ReplayResult:
    routed = route_recorded(RouteInput(request=record.request,
        recorded=record.recorded_response, state=record.routed.circuit_before,
        key=record.circuit_key))
    selection = _selection(record.router_manifest, routed)
    decision_bytes = canonical_json(model_json(selection))
    artifact_identical = canonical_hash(model_json(routed.artifact)) == record.artifact_hash
    circuit_identical = routed.circuit_after == record.routed.circuit_after
    body: JsonValue = {"decision_hash": canonical_hash(model_json(selection)),
        "artifact_identical": artifact_identical,
        "circuit_identical": circuit_identical,
        "provider_call_count": provider.call_count}
    return ReplayResult(provider_call_count=provider.call_count,
        decision_bytes=decision_bytes,
        byte_identical=decision_bytes == record.decision_bytes,
        artifact_identical=artifact_identical,
        circuit_identical=circuit_identical,
        replay_hash=canonical_hash(body))


def _selection(manifest: RouterRunManifest, routed: RoutedBatch) -> RouterSelection:
    replay_manifest = manifest.model_copy(update={"candidates": routed.artifact.candidates})
    return run_router(replay_manifest)
