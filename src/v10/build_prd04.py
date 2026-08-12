from __future__ import annotations

from pydantic import ValidationError

from src.v4.models import JsonValue, canonical_hash

from .bundle import seal_bundle
from .canonical import artifact_ref, model_json
from .context import ContextArtifact, archive_context, assert_historical_qualification, context_at
from .fixture_models import ContextInput, Prd04Fixture
from .models import ArtifactId, ArtifactMeta, ContentHash, V10ContractError
from .probe_runner import error_probe, outcome_probe


def build(value: JsonValue) -> JsonValue:
    try:
        fixture = Prd04Fixture.model_validate(value)
    except ValidationError as error:
        raise V10ContractError("V10_FIXTURE_ERROR", str(error)) from error
    contexts: list[ContextArtifact] = []
    for item in fixture.contexts:
        contexts.append(_context(fixture, item, tuple(contexts)))
    snapshot = context_at(tuple(contexts), fixture.market, fixture.cutoff, fixture.coverage)
    backfill = fixture.backfill_probe
    probes = (
        outcome_probe("context_supersede", contexts[0].meta.artifact_id,
                      contexts[1].supersedes.artifact_id if contexts[1].supersedes else "missing"),
        error_probe("backfilled_observation", "V10_POINT_IN_TIME_ARCHIVE_FAILURE",
                    lambda: assert_historical_qualification(contexts[backfill.context_index], backfill.cutoff)),
        outcome_probe("empty_healthy", "healthy", context_at((), fixture.market, fixture.cutoff).coverage),
    )
    artifacts = (*(model_json(item) for item in contexts), model_json(snapshot))
    return seal_bundle(4, value, artifacts, probes)


def _context(fixture: Prd04Fixture, item: ContextInput,
             prior: tuple[ContextArtifact, ...]) -> ContextArtifact:
    supersedes = None if item.supersedes_index is None else artifact_ref("supersedes", prior[item.supersedes_index])
    body: JsonValue = {"context_type": item.context_type, "market": fixture.market.value,
        "symbols": list(item.symbols), "sectors": list(item.sectors),
        "published_at": item.published_at.isoformat(), "observed_at": item.observed_at.isoformat(),
        "ingested_at": item.ingested_at.isoformat(), "canonical_text_hash": canonical_hash(item.text),
        "source_identity": item.source_identity, "archival_copy_verified": item.archival_copy_verified,
        "revision": item.revision, "supersedes": None if supersedes is None else supersedes.model_dump(mode="json")}
    value: dict[str, JsonValue] = {**body, "meta": model_json(ArtifactMeta(
        schema_version="unsealed", artifact_type="context_artifact", artifact_id=ArtifactId("unsealed"),
        content_hash=ContentHash("unsealed"), lineage=()))}
    return archive_context(value, item.text)
