from pathlib import Path
from src.v4.models import JsonValue

from pydantic import ValidationError

from .fixture import parse_json_bytes
from .models import ProvenanceContractError
from .quality_models import QualityContractError, QualityFixture
from .quality_registry_models import QualityTrustDocument


def parse_quality_json_bytes(payload: bytes) -> JsonValue:
    try:
        return parse_json_bytes(payload)
    except ProvenanceContractError as error:
        raise QualityContractError("MALFORMED_QUALITY_PAYLOAD", error.detail) from error


def parse_quality_fixture_bytes(payload: bytes) -> QualityFixture:
    try:
        return QualityFixture.model_validate(parse_quality_json_bytes(payload))
    except ValidationError as error:
        code = "REQUIRED_FIELD_MISSING" if any(item["type"] == "missing" for item in error.errors()) else "MALFORMED_QUALITY_PAYLOAD"
        raise QualityContractError(code, str(error)) from error


def load_quality_fixture(path: Path) -> QualityFixture:
    return parse_quality_fixture_bytes(path.read_bytes())


def parse_quality_trust_bytes(payload: bytes) -> QualityTrustDocument:
    try:
        return QualityTrustDocument.model_validate(parse_quality_json_bytes(payload))
    except ValidationError as error:
        code = "REQUIRED_FIELD_MISSING" if any(item["type"] == "missing" for item in error.errors()) else "MALFORMED_QUALITY_PAYLOAD"
        raise QualityContractError(code, str(error)) from error


def load_quality_trust(path: Path) -> QualityTrustDocument:
    return parse_quality_trust_bytes(path.read_bytes())
