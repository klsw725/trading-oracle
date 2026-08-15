from __future__ import annotations

from src.v13.codex import execute_recorded
from src.v13.context import (
    bind_context_records,
    build_context_snapshot,
    load_v10_context_fixture,
)
from src.v13.integration_probe import run_integration_probe
from src.v13.models import CandidateEvidence
from src.v13.policy import build_policy
from src.v13.prd02_models import BatchBuildInput, RecordedResponse
from src.v13.prompts import build_batch_request


def run_context_budget_probes(
    candidates: tuple[CandidateEvidence, ...],
) -> dict[str, bool]:
    fixture = load_v10_context_fixture()
    old, revision = fixture.contexts
    old = old.model_copy(update={"symbols": ("US:AAPL",),
        "sectors": ("technology",), "source_identity": "direct",
        "text": "Direct old"})
    revision = revision.model_copy(update={"symbols": ("US:AAPL",),
        "sectors": ("technology",), "source_identity": "direct",
        "text": "Direct current"})
    market = old.model_copy(update={"symbols": (), "sectors": (),
        "source_identity": "market", "text": "Market context", "revision": 0})
    snapshot = build_context_snapshot(fixture.model_copy(update={
        "contexts": (old, revision, market)}), candidates)
    direct = snapshot.records[0]
    direct_context = bind_context_records(snapshot, (direct,))
    reference = build_batch_request(BatchBuildInput(candidates=candidates,
        context=direct_context, policy=build_policy(), max_candidates=10,
        max_input_bytes=4096))
    direct_budget = len(reference.prompt.canonical_bytes)
    constrained = build_batch_request(BatchBuildInput(candidates=candidates,
        context=snapshot, policy=build_policy(), max_candidates=10,
        max_input_bytes=direct_budget))
    overflow = build_batch_request(BatchBuildInput(candidates=candidates,
        context=snapshot, policy=build_policy(), max_candidates=10,
        max_input_bytes=1))
    overflow_result = execute_recorded(overflow, RecordedResponse(
        outcome="response", model_id="gpt-5.1-codex", raw_response=b"{}"))
    calls: list[tuple[str, int]] = []

    def successful_probe(model_id: str, timeout_seconds: int) -> str:
        calls.append((model_id, timeout_seconds))
        return "OK"

    def failed_probe(model_id: str, timeout_seconds: int) -> str:
        calls.append((model_id, timeout_seconds))
        raise RuntimeError("recorded provider failure")

    disabled_probe = run_integration_probe(False, successful_probe)
    disabled_call_count = len(calls)
    successful = run_integration_probe(True, successful_probe)
    failed = run_integration_probe(True, failed_probe)
    return {
        "context_priority_direct_before_market": len(snapshot.records) == 2
            and direct.canonical_text == "Direct current"
            and snapshot.records[1].canonical_text == "Market context",
        "context_budget_whole_record": constrained.prompt.source_artifact_ids
            == (direct.artifact_id,)
            and len(constrained.prompt.canonical_bytes) <= direct_budget,
        "budget_identity_frozen": constrained.identity.max_input_bytes == direct_budget
            and constrained.invocation.max_input_bytes == direct_budget,
        "byte_overflow_market_fallback": overflow_result.state == "market_quant_only"
            and overflow_result.provider_call_count == 0
            and overflow_result.candidate_count_sent == 0
            and len(overflow.prompt.canonical_bytes) > overflow.invocation.max_input_bytes,
        "integration_disabled_zero_call": disabled_probe["state"] == "disabled"
            and disabled_probe["provider_call_count"] == 0
            and disabled_call_count == 0,
        "integration_enabled_one_call": successful["state"] == "pass"
            and successful["provider_call_count"] == 1
            and calls[0] == ("gpt-5.1-codex", 20),
        "integration_failure_typed": failed["state"] == "fail"
            and failed["provider_call_count"] == 1
            and failed.get("error_code") == "codex_integration_failed"
            and calls == [("gpt-5.1-codex", 20), ("gpt-5.1-codex", 20)],
    }
