from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, TypeAdapter, ValidationError

from src.v4.models import JsonValue

from .canonical import canonical_hash, parse_json, reject_forbidden
from .models import StrictModel, V11ContractError


class ArtifactBundle(StrictModel):
    schema_version: Literal["v11.paper_execution.bundle.1"]
    prd: Literal[1, 2, 3, 4]
    fixture_hash: str
    source_fixture: JsonValue
    artifacts: Annotated[tuple[JsonValue, ...], Field(strict=False)]
    probes: Annotated[tuple[JsonValue, ...], Field(strict=False)]
    bundle_hash: str


_BUNDLE = TypeAdapter(ArtifactBundle)


def seal_bundle(prd: Literal[1, 2, 3, 4], fixture: JsonValue,
                artifacts: tuple[JsonValue, ...], probes: tuple[JsonValue, ...]) -> JsonValue:
    body: dict[str, JsonValue] = {"schema_version": "v11.paper_execution.bundle.1",
        "prd": prd, "fixture_hash": canonical_hash(fixture), "source_fixture": fixture,
        "artifacts": list(artifacts), "probes": list(probes)}
    return {**body, "bundle_hash": canonical_hash(body)}


def parse_bundle(payload: bytes) -> ArtifactBundle:
    value = parse_json(payload)
    reject_forbidden(value)
    try:
        bundle = _BUNDLE.validate_python(value)
    except ValidationError as error:
        raise V11ContractError("V11_BUNDLE_MALFORMED", str(error)) from error
    body = bundle.model_dump(mode="json", exclude={"bundle_hash"})
    if bundle.bundle_hash != canonical_hash(body):
        raise V11ContractError("V11_HASH_MISMATCH", "bundle")
    return bundle
