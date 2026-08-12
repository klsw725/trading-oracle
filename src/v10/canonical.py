from __future__ import annotations

from hashlib import sha256
from typing import Final, Protocol

from pydantic import BaseModel, TypeAdapter

from src.v4.models import JsonValue, canonical_json
from src.v9.contract import V9ContractError
from src.v9.spec import parse_json_bytes as parse_v9_json_bytes
from src.v10.models import ArtifactId, ArtifactMeta, ArtifactRef, ContentHash, V10ContractError


_JSON: Final = TypeAdapter[JsonValue](JsonValue)
_FORBIDDEN: Final = frozenset(
    {
        "access_token",
        "account_id",
        "account_number",
        "client_secret",
        "credential",
        "oauth_token",
        "raw_account_identifier",
        "raw_config",
    }
)


class SealedArtifact(Protocol):
    meta: ArtifactMeta


def model_json(model: BaseModel, exclude: set[str] | None = None) -> JsonValue:
    return _JSON.validate_python(
        model.model_dump(mode="json", exclude=exclude, exclude_none=False)
    )


def parse_json_bytes(payload: bytes) -> JsonValue:
    try:
        return parse_v9_json_bytes(payload)
    except V9ContractError as error:
        raise V10ContractError("V10_JSON_PARSE_ERROR", error.detail) from error


def reject_forbidden(value: JsonValue) -> None:
    match value:  # noqa: MATCH_OK - recursive JSON variants are fully handled
        case dict() as record:
            forbidden = _FORBIDDEN.intersection(record)
            if forbidden:
                raise V10ContractError("V10_FORBIDDEN_FIELD", min(forbidden))
            for item in record.values():
                reject_forbidden(item)
        case list() as items:
            for item in items:
                reject_forbidden(item)
        case None | bool() | int() | float() | str():
            return


def seal_meta(artifact_type: str, payload: JsonValue) -> ArtifactMeta:
    digest = sha256(canonical_json(normalize_artifact_body(payload))).hexdigest()
    return ArtifactMeta(
        schema_version="v10.artifact.1",
        artifact_type=artifact_type,
        artifact_id=ArtifactId(f"v10:{artifact_type}:{digest[:20]}"),
        content_hash=ContentHash(f"sha256:{digest}"),
        lineage=(),
    )


def normalize_artifact_body(value: JsonValue) -> JsonValue:
    match value:  # noqa: MATCH_OK - recursive JSON variants are fully handled
        case dict() as record:
            return {key: normalize_artifact_body(item) for key, item in record.items()}
        case list() as items:
            return [normalize_artifact_body(item) for item in items]
        case str() as text if text.endswith("+00:00") and "T" in text:
            return f"{text[:-6]}Z"
        case None | bool() | int() | float() | str():
            return value


def artifact_ref(role: str, model: SealedArtifact) -> ArtifactRef:
    return ArtifactRef(
        role=role,
        artifact_type=model.meta.artifact_type,
        artifact_id=model.meta.artifact_id,
        content_hash=model.meta.content_hash,
    )


def verify_seal(model: BaseModel) -> None:
    raw = model_json(model)
    match raw:  # noqa: MATCH_OK - sealed artifacts require object JSON
        case {"meta": dict() as meta, **body}:
            artifact_type = meta.get("artifact_type")
            if not isinstance(artifact_type, str):
                raise V10ContractError("V10_HASH_MISMATCH", "artifact type")
            expected = seal_meta(artifact_type, body)
            if meta.get("content_hash") != expected.content_hash:
                raise V10ContractError("V10_HASH_MISMATCH", artifact_type)
            if meta.get("artifact_id") != expected.artifact_id:
                raise V10ContractError("V10_ARTIFACT_ID_MISMATCH", artifact_type)
        case _:
            raise V10ContractError("V10_HASH_MISMATCH", "artifact shape")
