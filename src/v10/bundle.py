from __future__ import annotations

from typing import Literal

from pydantic import TypeAdapter, ValidationError

from src.v4.models import JsonValue, canonical_hash

from .canonical import parse_json_bytes, reject_forbidden
from .models import StrictModel, V10ContractError


class ArtifactBundle(StrictModel):
    schema_version: Literal["v10.artifact_bundle.1"]
    prd: Literal[1, 2, 3, 4]
    fixture_hash: str
    source_fixture: JsonValue
    artifacts: tuple[JsonValue, ...]
    probes: tuple[JsonValue, ...]
    bundle_hash: str


_BUNDLE = TypeAdapter(ArtifactBundle)


def seal_bundle(prd: Literal[1, 2, 3, 4], fixture: JsonValue,
                artifacts: tuple[JsonValue, ...], probes: tuple[JsonValue, ...]) -> JsonValue:
    body: dict[str, JsonValue] = {
        "schema_version": "v10.artifact_bundle.1",
        "prd": prd,
        "fixture_hash": canonical_hash(fixture),
        "source_fixture": fixture,
        "artifacts": list(artifacts),
        "probes": list(probes),
    }
    return {**body, "bundle_hash": canonical_hash(body)}


def parse_bundle(payload: bytes) -> ArtifactBundle:
    value = parse_json_bytes(payload)
    reject_forbidden(value)
    try:
        bundle = _BUNDLE.validate_python(value)
    except ValidationError as error:
        raise V10ContractError("V10_BUNDLE_MALFORMED", str(error)) from error
    body = bundle.model_dump(mode="json", exclude={"bundle_hash"})
    if bundle.bundle_hash != canonical_hash(body):
        raise V10ContractError("V10_HASH_MISMATCH", "artifact bundle")
    if bundle.fixture_hash != canonical_hash(bundle.source_fixture):
        raise V10ContractError("V10_HASH_MISMATCH", "source fixture")
    return bundle
