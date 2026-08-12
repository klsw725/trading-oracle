from __future__ import annotations

from src.v4.models import JsonValue, canonical_hash

from .build import build_fixture
from .bundle import ArtifactBundle, parse_bundle
from .canonical import normalize_artifact_body
from .models import V10ContractError


def verify_bundle(payload: bytes) -> ArtifactBundle:
    bundle = parse_bundle(payload)
    rebuilt = build_fixture(bundle.source_fixture)
    expected = _record(rebuilt)
    actual = bundle.model_dump(mode="json")
    if actual != expected:
        raise V10ContractError("V10_DERIVED_FIELD_MISMATCH", "bundle differs from source fixture")
    _verify_artifacts(bundle.artifacts)
    return bundle


def _verify_artifacts(artifacts: tuple[JsonValue, ...]) -> None:
    known: dict[str, str] = {}
    for artifact in artifacts:
        record = _record(artifact)
        meta = _record(record.get("meta"))
        artifact_type = _text(meta.get("artifact_type"), "artifact_type")
        body = {key: value for key, value in record.items() if key != "meta"}
        expected_hash = canonical_hash(normalize_artifact_body(body))
        expected_id = f"v10:{artifact_type}:{expected_hash.removeprefix('sha256:')[:20]}"
        if meta.get("content_hash") != expected_hash or meta.get("artifact_id") != expected_id:
            raise V10ContractError("V10_HASH_MISMATCH", artifact_type)
        known[expected_id] = expected_hash
    for artifact in artifacts:
        _verify_refs(artifact, known)


def _verify_refs(value: JsonValue, known: dict[str, str]) -> None:
    match value:  # noqa: MATCH_OK - recursive JSON variants are fully handled
        case dict() as record:
            artifact_id = record.get("artifact_id")
            content_hash = record.get("content_hash")
            if "role" in record and isinstance(artifact_id, str):
                if artifact_id not in known or content_hash != known[artifact_id]:
                    raise V10ContractError("V10_LINEAGE_MISMATCH", artifact_id)
            for item in record.values():
                _verify_refs(item, known)
        case list() as items:
            for item in items:
                _verify_refs(item, known)
        case None | bool() | int() | float() | str():
            return


def _record(value: JsonValue) -> dict[str, JsonValue]:
    match value:  # noqa: MATCH_OK - verifier requires object JSON
        case dict() as record:
            return record
        case _:
            raise V10ContractError("V10_BUNDLE_MALFORMED", "object expected")


def _text(value: JsonValue | None, field: str) -> str:
    match value:  # noqa: MATCH_OK - verifier requires string JSON
        case str() as text:
            return text
        case _:
            raise V10ContractError("V10_BUNDLE_MALFORMED", field)
