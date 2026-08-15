from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Final

from bs4 import BeautifulSoup

from src.v10.build import build_fixture
from src.v10.canonical import parse_json_bytes
from src.v10.context import ContextArtifact
from src.v10.fixture_models import Prd04Fixture
from src.v10.verifier import verify_bundle
from src.v11.canonical import canonical_hash, model_json
from src.v11.models import Market
from src.v4.models import JsonValue, canonical_json
from src.v13.models import CandidateEvidence, V13ContractError
from src.v13.prd02_models import ContextIncident, ContextRecord, ContextSnapshot


V10_CONTEXT_FIXTURE: Final = Path(__file__).parents[2] / "docs/specs/v10/fixtures/prd04-context.json"
_INJECTION_MARKERS: Final = (
    "ignore previous", "system prompt", "developer message", "tool call", "follow these instructions"
)


def load_v10_context_fixture() -> Prd04Fixture:
    return Prd04Fixture.model_validate(parse_json_bytes(V10_CONTEXT_FIXTURE.read_bytes()))


def canonical_text(text: str) -> str:
    soup = BeautifulSoup(text, "html.parser")
    for node in soup(["script", "style"]):
        node.decompose()
    for node in soup.select("[hidden]"):
        node.decompose()
    return " ".join(soup.get_text(" ").split())


def _verified_records(fixture: Prd04Fixture) -> tuple[tuple[ContextRecord, ...], str]:
    source: JsonValue = fixture.model_dump(mode="json")
    bundle = verify_bundle(canonical_json(build_fixture(source)))
    artifacts = tuple(
        ContextArtifact.model_validate(item)
        for item in bundle.artifacts[: len(fixture.contexts)]
    )
    records: list[ContextRecord] = []
    for artifact, item in zip(artifacts, fixture.contexts, strict=True):
        if artifact.canonical_text_hash != canonical_hash(item.text):
            raise V13ContractError("V13_CORPUS_HASH", str(artifact.meta.artifact_id))
        records.append(ContextRecord(artifact_id=str(artifact.meta.artifact_id),
            content_hash=str(artifact.meta.content_hash), context_type=artifact.context_type,
            symbols=tuple(str(symbol) for symbol in artifact.symbols), sectors=artifact.sectors,
            published_at=artifact.published_at, observed_at=artifact.observed_at,
            canonical_text_hash=artifact.canonical_text_hash, canonical_text=item.text,
            source_identity=artifact.source_identity, revision=artifact.revision))
    return tuple(records), bundle.bundle_hash


def build_context_snapshot(
    fixture: Prd04Fixture, candidates: tuple[CandidateEvidence, ...]
) -> ContextSnapshot:
    records, bundle_hash = _verified_records(fixture)
    cutoff = candidates[0].cutoff
    incidents: list[ContextIncident] = []
    qualified: list[ContextRecord] = []
    for record in records:
        if record.published_at > cutoff or record.observed_at > cutoff:
            incidents.append(ContextIncident(artifact_id=record.artifact_id,
                code="FUTURE_CONTEXT"))
            continue
        window = timedelta(hours=24) if record.context_type == "news" else timedelta(days=7)
        if cutoff - record.published_at > window:
            incidents.append(ContextIncident(artifact_id=record.artifact_id,
                code="STALE_CONTEXT"))
            continue
        cleaned = canonical_text(record.canonical_text).lower()
        if any(marker in cleaned for marker in _INJECTION_MARKERS):
            incidents.append(ContextIncident(artifact_id=record.artifact_id,
                code="PROMPT_INJECTION"))
            continue
        qualified.append(record)
    heads: dict[tuple[str, str, tuple[str, ...]], ContextRecord] = {}
    for record in qualified:
        key = (record.source_identity, record.context_type, record.symbols)
        prior = heads.get(key)
        if prior is None or record.revision > prior.revision:
            heads[key] = record
    candidate_symbols = {item.symbol for item in candidates}
    candidate_sectors = {item.sector for item in candidates}
    selected = tuple(sorted(heads.values(), key=lambda item: _priority(
        item, candidate_symbols, candidate_sectors)))
    snapshot = ContextSnapshot(market=Market(candidates[0].market.value), cutoff=cutoff,
        records=(), incidents=tuple(incidents), source_bundle_hash=bundle_hash,
        snapshot_hash="sha256:pending", corpus_hash="sha256:pending",
        detector_version="v13.detector.1")
    return bind_context_records(snapshot, selected)


def bind_context_records(
    snapshot: ContextSnapshot, records: tuple[ContextRecord, ...]
) -> ContextSnapshot:
    corpus: JsonValue = [{"artifact_id": item.artifact_id,
        "canonical_text_hash": item.canonical_text_hash,
        "canonical_text": item.canonical_text} for item in records]
    snapshot_body: JsonValue = {"market": snapshot.market.value,
        "cutoff": snapshot.cutoff.isoformat(),
        "records": [model_json(item) for item in records],
        "source_bundle_hash": snapshot.source_bundle_hash,
        "detector_version": snapshot.detector_version}
    return snapshot.model_copy(update={"records": records,
        "snapshot_hash": canonical_hash(snapshot_body),
        "corpus_hash": canonical_hash(corpus)})


def _priority(
    record: ContextRecord, candidate_symbols: set[str], candidate_sectors: set[str]
) -> tuple[int, int, float, float, str]:
    relevance = (0 if candidate_symbols.intersection(record.symbols)
        else 1 if candidate_sectors.intersection(record.sectors) else 2)
    source = 1 if record.context_type == "news" else 0
    return (relevance, source, -record.published_at.timestamp(),
        -record.observed_at.timestamp(), record.artifact_id)
