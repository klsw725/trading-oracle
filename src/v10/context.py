from __future__ import annotations

from datetime import datetime
from typing import Literal

from src.v4.models import JsonValue, canonical_hash

from .canonical import seal_meta
from .models import ArtifactMeta, ArtifactRef, Market, StrictModel, Symbol, V10ContractError


class ContextArtifact(StrictModel):
    meta: ArtifactMeta
    context_type: Literal["news", "filing", "corporate_event", "regulatory"]
    market: Market
    symbols: tuple[Symbol, ...]
    sectors: tuple[str, ...]
    published_at: datetime
    observed_at: datetime
    ingested_at: datetime
    canonical_text_hash: str
    source_identity: str
    archival_copy_verified: bool
    revision: int
    supersedes: ArtifactRef | None


class ContextSnapshot(StrictModel):
    meta: ArtifactMeta
    market: Market
    cutoff: datetime
    artifacts: tuple[ArtifactRef, ...]
    coverage: Literal["healthy", "gap"]


def archive_context(value: JsonValue, text: str) -> ContextArtifact:
    unsealed = ContextArtifact.model_validate(value)
    if unsealed.observed_at > unsealed.ingested_at:
        raise V10ContractError("V10_CONTEXT_TIME_INVALID", unsealed.source_identity)
    expected_hash = canonical_hash(text)
    if unsealed.canonical_text_hash != expected_hash:
        raise V10ContractError("V10_HASH_MISMATCH", "context text")
    body = unsealed.model_dump(mode="json", exclude={"meta"})
    return unsealed.model_copy(update={"meta": seal_meta("context_artifact", body)})


def context_at(artifacts: tuple[ContextArtifact, ...], market: Market,
               cutoff: datetime, coverage: Literal["healthy", "gap"] = "healthy") -> ContextSnapshot:
    qualified = tuple(
        item for item in artifacts
        if item.market is market and item.archival_copy_verified and item.observed_at <= cutoff
    )
    from .canonical import artifact_ref
    refs = tuple(artifact_ref("context", item) for item in qualified)
    body: JsonValue = {"market": market.value, "cutoff": cutoff.isoformat(),
                       "artifacts": [ref.model_dump(mode="json") for ref in refs], "coverage": coverage}
    return ContextSnapshot(meta=seal_meta("context_snapshot", body), market=market,
                           cutoff=cutoff, artifacts=refs, coverage=coverage)


def assert_historical_qualification(artifact: ContextArtifact, cutoff: datetime) -> None:
    if not artifact.archival_copy_verified or artifact.observed_at > cutoff:
        raise V10ContractError("V10_POINT_IN_TIME_ARCHIVE_FAILURE", artifact.source_identity)
