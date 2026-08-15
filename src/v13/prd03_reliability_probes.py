from __future__ import annotations

from pathlib import Path

from src.v11.canonical import canonical_hash
from src.v11.models import Account, Market
from src.v13.circuit_breaker import initial_state
from src.v13.context import build_context_snapshot, load_v10_context_fixture
from src.v13.fallback import RouteInput, RoutedBatch, integrity_fallback, route_recorded
from src.v13.models import CandidateEvidence, RouterRunManifest
from src.v13.policy import build_policy
from src.v13.prd01_fixture import load_fixture
from src.v13.prd02_models import BatchBuildInput, BatchRequest, RecordedResponse
from src.v13.prd03_models import CircuitKey
from src.v13.prompts import build_batch_request
from src.v13.replay import (
    NoCallProvider,
    RecordInput,
    record_decision,
    replay_decision,
)


RECORDED_PATH = Path(__file__).parents[2] / "docs/specs/v13/fixtures/prd02-recorded-normal.json"


def _candidates() -> tuple[CandidateEvidence, ...]:
    cutoff = load_v10_context_fixture().cutoff
    return tuple(item.model_copy(update={"market": Market.US, "symbol": "US:AAPL",
        "cutoff": cutoff, "watermark_at": cutoff, "decision_ready_at": cutoff})
        for item in load_fixture().candidates[:2])


def _request(max_candidates: int = 10) -> BatchRequest:
    candidates = _candidates()
    context = build_context_snapshot(load_v10_context_fixture(), candidates)
    return build_batch_request(BatchBuildInput(candidates=candidates, context=context,
        policy=build_policy(), max_candidates=max_candidates))


def _recorded(outcome: str = "response", payload: bytes | None = None,
              model_id: str = "gpt-5.1-codex") -> RecordedResponse:
    return RecordedResponse.model_validate({"outcome": outcome, "model_id": model_id,
        "raw_response": RECORDED_PATH.read_bytes() if payload is None else payload})


def _route(request: BatchRequest, recorded: RecordedResponse, key: CircuitKey) -> RoutedBatch:
    return route_recorded(RouteInput(request=request, recorded=recorded,
        state=initial_state(key), key=key))


def run_reliability_probes() -> tuple[dict[str, bool], dict[str, str], dict[str, str]]:
    request = _request()
    key = CircuitKey(market=Market.US, regular_session_id="US:2026-01-05:regular")
    normal_recorded = _recorded()
    normal = _route(request, normal_recorded, key)
    timeout = _route(request, _recorded("timeout", b""), key)
    auth = _route(request, _recorded("auth_error", b""), key)
    provider = _route(request, _recorded("provider_error", b""), key)
    overflow = _route(_request(1), normal_recorded, key)
    model = _route(request, _recorded(model_id="wrong-model"), key)
    strict_json = _route(request, _recorded(payload=b"{"), key)
    identity_payload = normal_recorded.raw_response.replace(
        request.identity.batch_id.encode(), b"sha256:wrong")
    identity = _route(request, _recorded(payload=identity_payload), key)
    abstain_payload = normal_recorded.raw_response.replace(
        b'"abstain":false', b'"abstain":true', 1)
    abstain = _route(request, _recorded(payload=abstain_payload), key)
    item_error_payload = normal_recorded.raw_response.replace(
        b'"score":"0.80"', b'"score":"2"', 1)
    item_error = _route(request, _recorded(payload=item_error_payload), key)
    integrity_reasons = ("ARTIFACT_CUTOFF_FAILURE", "ARTIFACT_HASH_FAILURE",
        "PROMPT_VERSION_MISMATCH", "SCHEMA_VERSION_MISMATCH")
    integrity = tuple(integrity_fallback(RouteInput(request=request,
        recorded=normal_recorded, state=initial_state(key), key=key), reason)
        for reason in integrity_reasons)
    consecutive = initial_state(key)
    for _ in range(3):
        consecutive = route_recorded(RouteInput(request=request,
            recorded=_recorded("timeout", b""), state=consecutive, key=key)).circuit_after
    skipped = route_recorded(RouteInput(request=request, recorded=normal_recorded,
        state=consecutive, key=key))
    recent = initial_state(key)
    before_twenty = recent
    for index in range(20):
        failed = index in {4, 9, 14, 19}
        observation = _recorded("timeout", b"") if failed else normal_recorded
        recent = route_recorded(RouteInput(request=request, recorded=observation,
            state=recent, key=key)).circuit_after
        if index == 18:
            before_twenty = recent
    next_key = CircuitKey(market=Market.US,
        regular_session_id="US:2026-01-06:regular")
    reset = route_recorded(RouteInput(request=request, recorded=normal_recorded,
        state=recent, key=next_key))
    manifest = RouterRunManifest(schema_version="v13.router_run.1",
        run_id="prd03:replay", market=Market.US, cutoff=request.identity.cutoff,
        policy=build_policy(), account=Account(market=Market.US, currency="USD",
            prior_close_nav="100000", cash="100000"),
        candidates=request.candidates, slot_limit=2)
    record = record_decision(RecordInput(request=request,
        recorded_response=normal_recorded, circuit_state=initial_state(key),
        circuit_key=key, router_manifest=manifest))
    replayed = replay_decision(record, NoCallProvider())
    fallback_reasons = {timeout.artifact.fallbacks[0].reason_code,
        auth.artifact.fallbacks[0].reason_code,
        provider.artifact.fallbacks[0].reason_code,
        overflow.artifact.fallbacks[0].reason_code,
        model.artifact.fallbacks[0].reason_code,
        strict_json.artifact.fallbacks[0].reason_code,
        identity.artifact.fallbacks[0].reason_code,
        skipped.artifact.fallbacks[0].reason_code,
        *(item.artifact.fallbacks[0].reason_code for item in integrity)}
    expected_reasons = {"TIMEOUT", "AUTH_ERROR", "PROVIDER_ERROR", "INPUT_OVERFLOW",
        "MODEL_MISMATCH", "STRICT_JSON_FAILURE", "ENVELOPE_IDENTITY", "CIRCUIT_OPEN",
        *integrity_reasons}
    checks = {
        "provider_success_observed": normal.observed and len(normal.circuit_after.recent) == 1,
        "item_error_abstain_successful_attempt": abstain.observed
            and abstain.artifact.state == "symbol_quant_only"
            and abstain.circuit_after.consecutive_failures == 0
            and item_error.observed and item_error.artifact.state == "symbol_quant_only"
            and item_error.circuit_after.consecutive_failures == 0,
        "overflow_unobserved": not overflow.observed and not overflow.circuit_after.recent,
        "circuit_skip_unobserved": not skipped.observed
            and len(skipped.circuit_after.recent) == 3,
        "consecutive_three_opens": consecutive.is_open
            and consecutive.consecutive_failures == 3,
        "recent_rule_waits_for_twenty": not before_twenty.is_open
            and len(before_twenty.recent) == 19 and recent.is_open
            and len(recent.recent) == 20
            and sum(not item.succeeded for item in recent.recent) == 4,
        "next_regular_session_resets": not reset.circuit_before.is_open
            and len(reset.circuit_before.recent) == 0 and reset.observed,
        "all_fallback_reasons": fallback_reasons == expected_reasons,
        "raw_response_byte_identical": record.recorded_response.raw_response
            == normal_recorded.raw_response and replayed.byte_identical,
        "replay_router_outputs_identical": replayed.artifact_identical
            and replayed.circuit_identical,
        "replay_provider_zero": replayed.provider_call_count == 0,
    }
    mutations = {"replay_recall": "killed"
        if checks["replay_provider_zero"] and checks["raw_response_byte_identical"]
        else "survived"}
    hashes = {"replay_hash": replayed.replay_hash,
        "replay_artifact_hash": record.artifact_hash,
        "decision_bytes_hash": canonical_hash(record.decision_bytes.decode())}
    return checks, mutations, hashes
