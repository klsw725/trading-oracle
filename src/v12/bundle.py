from __future__ import annotations

from typing import Literal

from pydantic import TypeAdapter, ValidationError

from src.v4.models import JsonValue
from src.v11.canonical import canonical_hash, model_json, parse_json, reject_forbidden

from .artifacts import RunArtifacts
from .models import StrictModel, V12ContractError


class ArtifactBundle(StrictModel):
    schema_version: Literal["v12.strategy.bundle.2"]
    fixture_hash: str
    upstream_hash: str
    registry_hash: str
    source_fixture: JsonValue
    run: RunArtifacts
    bundle_hash: str


_BUNDLE = TypeAdapter(ArtifactBundle)


def seal_bundle(fixture: JsonValue, upstream_hash: str, registry_hash: str,
                run: RunArtifacts) -> JsonValue:
    body: dict[str, JsonValue] = {"schema_version": "v12.strategy.bundle.2",
        "fixture_hash": canonical_hash(fixture), "upstream_hash": upstream_hash,
        "registry_hash": registry_hash, "source_fixture": fixture, "run": model_json(run)}
    return {**body, "bundle_hash": canonical_hash(body)}


def parse_bundle(payload: bytes) -> ArtifactBundle:
    value = parse_json(payload)
    reject_forbidden(value)
    try:
        bundle = _BUNDLE.validate_python(value)
    except ValidationError as error:
        raise V12ContractError("V12_BUNDLE_MALFORMED", str(error)) from error
    body = bundle.model_dump(mode="json", exclude={"bundle_hash"})
    if bundle.fixture_hash != canonical_hash(bundle.source_fixture):
        raise V12ContractError("V12_FIXTURE_HASH", "source_fixture")
    if bundle.bundle_hash != canonical_hash(body):
        raise V12ContractError("V12_HASH_MISMATCH", "bundle")
    return bundle
