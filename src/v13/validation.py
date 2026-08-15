from __future__ import annotations

from typing import Final

from src.v11.canonical import canonical_hash, model_json
from src.v4.models import JsonValue
from src.v13.models import CandidateEvidence
from src.v13.prd02_models import (
    BatchRequest,
    BatchScoringArtifact,
    CodexItem,
    FallbackDecision,
    ParsedEnvelope,
    ValidationIncident,
)


_VETO_CONTEXT: Final = {
    "TRADING_HALT": frozenset({"regulatory"}),
    "DELISTING": frozenset({"regulatory", "filing"}),
    "BANKRUPTCY": frozenset({"regulatory", "filing"}),
    "REGULATORY": frozenset({"regulatory"}),
    "CORPORATE_ACTION": frozenset({"corporate_event"}),
}


def _market_fallback(
    request: BatchRequest, raw_hash: str, reason: str, calls: int
) -> BatchScoringArtifact:
    candidates = tuple(item.model_copy(update={"llm_score": None,
        "confidence": None, "item_valid": False, "abstain": False,
        "hard_veto_verified": False}) for item in request.candidates)
    fallback = FallbackDecision(scope="market", subject=request.identity.market.value,
        reason_code=reason)
    validation: JsonValue = {"reason": reason, "scope": "market"}
    return BatchScoringArtifact(identity=request.identity,
        prompt_hash=request.prompt.prompt_hash, raw_response_hash=raw_hash,
        parsed_response_hash=None, validation_hash=canonical_hash(validation),
        candidates=candidates, incidents=(ValidationIncident(scope="market", code=reason,
            subject=request.identity.batch_id),), fallbacks=(fallback,),
        provider_call_count=calls, candidate_count_sent=0 if calls == 0 else len(candidates),
        state="market_quant_only")


def validate_envelope(
    request: BatchRequest, parsed: ParsedEnvelope, raw_hash: str
) -> BatchScoringArtifact:
    expected = set(request.identity.candidate_ids)
    observed = tuple(record.candidate_id for record in parsed.items
        if record.candidate_id is not None)
    identity_valid = (parsed.envelope_error is None
        and parsed.schema_version == request.identity.schema_version
        and parsed.batch_id == request.identity.batch_id
        and parsed.market == request.identity.market.value
        and parsed.cutoff == request.identity.cutoff.isoformat()
        and parsed.prompt_hash == request.prompt.prompt_hash)
    if not identity_valid:
        return _market_fallback(request, raw_hash, "ENVELOPE_IDENTITY", 1)
    if len(observed) != len(set(observed)):
        return _market_fallback(request, raw_hash, "DUPLICATE_CANDIDATE", 1)
    if any(candidate_id not in expected for candidate_id in observed):
        return _market_fallback(request, raw_hash, "UNKNOWN_CANDIDATE", 1)
    records = {record.candidate_id: record for record in parsed.items
        if record.candidate_id is not None}
    invalid_symbols = {candidate.symbol for candidate in request.candidates
        if candidate.candidate_id not in records or records[candidate.candidate_id].item is None}
    valid_items: dict[str, CodexItem] = {}
    for candidate_id, record in records.items():
        if record.item is not None:
            valid_items[candidate_id] = record.item
            if record.item.abstain:
                invalid_symbols.update(candidate.symbol for candidate in request.candidates
                    if candidate.candidate_id == candidate_id)
    incidents: list[ValidationIncident] = []
    fallbacks = [FallbackDecision(scope="symbol", subject=symbol,
        reason_code="ITEM_INVALID_OR_ABSTAIN") for symbol in sorted(invalid_symbols)]
    context_by_id = {record.artifact_id: record for record in request.context.records}
    output: list[CandidateEvidence] = []
    for candidate in request.candidates:
        item = valid_items.get(candidate.candidate_id)
        if candidate.symbol in invalid_symbols or item is None:
            output.append(candidate.model_copy(update={"llm_score": None,
                "confidence": None, "item_valid": False,
                "abstain": item.abstain if item is not None else False,
                "hard_veto_verified": False}))
            continue
        unknown_sources = set(item.source_artifact_ids) - set(context_by_id)
        if unknown_sources:
            invalid_symbols.add(candidate.symbol)
            fallbacks.append(FallbackDecision(scope="symbol", subject=candidate.symbol,
                reason_code="UNKNOWN_SOURCE_ARTIFACT"))
            output.append(candidate.model_copy(update={"llm_score": None,
                "confidence": None, "item_valid": False, "abstain": False,
                "hard_veto_verified": False}))
            continue
        veto_verified = False
        if item.veto_code is not None:
            evidence = tuple(context_by_id[source_id] for source_id in item.source_artifact_ids)
            veto_verified = any(candidate.symbol in record.symbols
                and record.context_type in _VETO_CONTEXT[item.veto_code]
                and record.published_at <= candidate.cutoff
                and record.observed_at <= candidate.cutoff for record in evidence)
            if not veto_verified:
                incidents.append(ValidationIncident(scope="candidate",
                    code="UNPROVEN_VETO", subject=candidate.candidate_id))
        output.append(candidate.model_copy(update={"llm_score": item.score,
            "confidence": item.confidence, "item_valid": True,
            "abstain": False, "hard_veto_verified": veto_verified}))
    if invalid_symbols:
        output = [item.model_copy(update={"llm_score": None, "confidence": None,
            "item_valid": False, "abstain": item.abstain,
            "hard_veto_verified": False}) if item.symbol in invalid_symbols else item
            for item in output]
    validation: JsonValue = {"incidents": [model_json(item) for item in incidents],
        "fallbacks": [model_json(item) for item in fallbacks]}
    return BatchScoringArtifact(identity=request.identity,
        prompt_hash=request.prompt.prompt_hash, raw_response_hash=raw_hash,
        parsed_response_hash=canonical_hash(model_json(parsed)),
        validation_hash=canonical_hash(validation), candidates=tuple(output),
        incidents=tuple(incidents), fallbacks=tuple(fallbacks),
        provider_call_count=1, candidate_count_sent=len(request.candidates),
        state="symbol_quant_only" if fallbacks else "scored")


def market_fallback(
    request: BatchRequest, raw_hash: str, reason: str, calls: int
) -> BatchScoringArtifact:
    return _market_fallback(request, raw_hash, reason, calls)
