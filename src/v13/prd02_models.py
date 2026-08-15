from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import Field, StrictInt

from src.v11.models import Market
from src.v13.models import CandidateEvidence, RouterPolicy, StrictModel


class ContextRecord(StrictModel):
    artifact_id: str
    content_hash: str
    context_type: Literal["news", "filing", "corporate_event", "regulatory"]
    symbols: Annotated[tuple[str, ...], Field(strict=False)]
    sectors: Annotated[tuple[str, ...], Field(strict=False)]
    published_at: Annotated[datetime, Field(strict=False)]
    observed_at: Annotated[datetime, Field(strict=False)]
    canonical_text_hash: str
    canonical_text: str
    source_identity: str
    revision: StrictInt


class ContextIncident(StrictModel):
    artifact_id: str
    code: Literal["FUTURE_CONTEXT", "STALE_CONTEXT", "PROMPT_INJECTION"]


class ContextSnapshot(StrictModel):
    market: Annotated[Market, Field(strict=False)]
    cutoff: Annotated[datetime, Field(strict=False)]
    records: Annotated[tuple[ContextRecord, ...], Field(strict=False)]
    incidents: Annotated[tuple[ContextIncident, ...], Field(strict=False)]
    source_bundle_hash: str
    snapshot_hash: str
    corpus_hash: str
    detector_version: Literal["v13.detector.1"]


class BatchIdentity(StrictModel):
    batch_id: str
    market: Annotated[Market, Field(strict=False)]
    cutoff: Annotated[datetime, Field(strict=False)]
    candidate_ids: Annotated[tuple[str, ...], Field(strict=False)]
    context_snapshot_hash: str
    context_corpus_hash: str
    policy_hash: str
    model_id: Literal["gpt-5.1-codex"]
    prompt_version: Literal["v13.prompt.1"]
    schema_version: Literal["v13.codex_response.1"]
    detector_version: Literal["v13.detector.1"]
    max_input_bytes: Annotated[StrictInt, Field(gt=0)]


class PromptArtifact(StrictModel):
    identity: BatchIdentity
    canonical_bytes: bytes
    prompt_hash: str
    source_artifact_ids: Annotated[tuple[str, ...], Field(strict=False)]


VetoCode = Literal[
    "TRADING_HALT", "DELISTING", "BANKRUPTCY", "REGULATORY", "CORPORATE_ACTION"
]


class CodexItem(StrictModel):
    candidate_id: str
    score: Annotated[Decimal, Field(ge=0, le=1, strict=False)]
    veto_code: VetoCode | None
    abstain: bool
    confidence: Annotated[Decimal, Field(ge=0, le=1, strict=False)]
    source_artifact_ids: Annotated[tuple[str, ...], Field(strict=False)]
    reason: Annotated[str, Field(max_length=240)]


class CodexEnvelope(StrictModel):
    schema_version: Literal["v13.codex_response.1"]
    batch_id: str
    market: Annotated[Market, Field(strict=False)]
    cutoff: Annotated[datetime, Field(strict=False)]
    prompt_hash: str
    items: Annotated[tuple[CodexItem, ...], Field(strict=False)]


class ItemRecord(StrictModel):
    candidate_id: str | None
    item: CodexItem | None
    error_code: str | None


class ParsedEnvelope(StrictModel):
    schema_version: str | None
    batch_id: str | None
    market: str | None
    cutoff: str | None
    prompt_hash: str | None
    items: Annotated[tuple[ItemRecord, ...], Field(strict=False)]
    envelope_error: str | None


class ValidationIncident(StrictModel):
    scope: Literal["market", "symbol", "candidate", "context"]
    code: str
    subject: str


class FallbackDecision(StrictModel):
    scope: Literal["market", "symbol"]
    subject: str
    reason_code: str


class InvocationPolicy(StrictModel):
    timeout_seconds: Literal[20] = 20
    retry_count: Literal[0] = 0
    tools_enabled: Literal[False] = False
    max_candidates: Annotated[StrictInt, Field(gt=0)]
    max_input_bytes: Annotated[StrictInt, Field(gt=0)]


class BatchBuildInput(StrictModel):
    candidates: Annotated[tuple[CandidateEvidence, ...], Field(strict=False)]
    context: ContextSnapshot
    policy: RouterPolicy
    max_candidates: Annotated[StrictInt, Field(gt=0)]
    max_input_bytes: Annotated[StrictInt, Field(gt=0)] = 65536


class BatchRequest(StrictModel):
    identity: BatchIdentity
    prompt: PromptArtifact
    context: ContextSnapshot
    candidates: Annotated[tuple[CandidateEvidence, ...], Field(strict=False)]
    invocation: InvocationPolicy


class RecordedResponse(StrictModel):
    outcome: Literal["response", "timeout", "auth_error", "provider_error"]
    model_id: str
    raw_response: bytes


class BatchScoringArtifact(StrictModel):
    identity: BatchIdentity
    prompt_hash: str
    raw_response_hash: str
    parsed_response_hash: str | None
    validation_hash: str
    candidates: Annotated[tuple[CandidateEvidence, ...], Field(strict=False)]
    incidents: Annotated[tuple[ValidationIncident, ...], Field(strict=False)]
    fallbacks: Annotated[tuple[FallbackDecision, ...], Field(strict=False)]
    provider_call_count: Annotated[StrictInt, Field(ge=0, le=1)]
    candidate_count_sent: Annotated[StrictInt, Field(ge=0)]
    state: Literal["scored", "symbol_quant_only", "market_quant_only"]
