from __future__ import annotations

from src.v11.canonical import canonical_hash, model_json
from src.v4.models import JsonValue, canonical_json, sha256_bytes
from src.v13.context import bind_context_records, canonical_text
from src.v13.prd02_models import (
    BatchBuildInput,
    BatchIdentity,
    BatchRequest,
    ContextRecord,
    ContextSnapshot,
    InvocationPolicy,
    PromptArtifact,
)


def build_batch_request(
    inputs: BatchBuildInput,
) -> BatchRequest:
    empty_context = bind_context_records(inputs.context, ())
    if len(_request(inputs, empty_context).prompt.canonical_bytes) > inputs.max_input_bytes:
        return _request(inputs, empty_context)
    selected: list[ContextRecord] = []
    for record in inputs.context.records:
        trial_context = bind_context_records(inputs.context, (*selected, record))
        if len(_request(inputs, trial_context).prompt.canonical_bytes) > inputs.max_input_bytes:
            break
        selected.append(record)
    return _request(inputs, bind_context_records(inputs.context, tuple(selected)))


def _request(inputs: BatchBuildInput, context: ContextSnapshot) -> BatchRequest:
    candidates = inputs.candidates
    policy = inputs.policy
    candidate_ids = tuple(sorted(item.candidate_id for item in candidates))
    identity_body: JsonValue = {
        "market": candidates[0].market.value,
        "cutoff": candidates[0].cutoff.isoformat(),
        "candidate_ids": list(candidate_ids),
        "context_snapshot_hash": context.snapshot_hash,
        "context_corpus_hash": context.corpus_hash,
        "policy_hash": policy.policy_hash,
        "model_id": "gpt-5.1-codex",
        "prompt_version": "v13.prompt.1",
        "schema_version": "v13.codex_response.1",
        "detector_version": context.detector_version,
        "max_input_bytes": inputs.max_input_bytes,
    }
    identity = BatchIdentity(batch_id=canonical_hash(identity_body),
        market=candidates[0].market, cutoff=candidates[0].cutoff,
        candidate_ids=candidate_ids, context_snapshot_hash=context.snapshot_hash,
        context_corpus_hash=context.corpus_hash, policy_hash=policy.policy_hash,
        model_id="gpt-5.1-codex", prompt_version="v13.prompt.1",
        schema_version="v13.codex_response.1", detector_version=context.detector_version,
        max_input_bytes=inputs.max_input_bytes)
    prompt_body: JsonValue = {
        "identity": model_json(identity),
        "candidates": [model_json(item) for item in sorted(candidates,
            key=lambda candidate: candidate.candidate_id)],
        "untrusted_context": [{"artifact_id": item.artifact_id,
            "text": canonical_text(item.canonical_text)} for item in context.records],
        "allowed_output_fields": ["candidate_id", "score", "veto_code", "abstain",
            "confidence", "source_artifact_ids", "reason"],
    }
    prompt_bytes = canonical_json(prompt_body)
    prompt = PromptArtifact(identity=identity, canonical_bytes=prompt_bytes,
        prompt_hash=sha256_bytes(prompt_bytes),
        source_artifact_ids=tuple(item.artifact_id for item in context.records))
    return BatchRequest(identity=identity, prompt=prompt, context=context,
        candidates=candidates,
        invocation=InvocationPolicy(max_candidates=inputs.max_candidates,
            max_input_bytes=inputs.max_input_bytes))
