from collections.abc import Callable

from src.v4.models import JsonValue

from .quality_artifact import verify_quality_artifact
from .quality_models import QualityContractError, QualityErrorCode
from .quality_registry import QualityTrustContext

type QualityPath = tuple[str | int, ...]


def replace_quality(value: JsonValue, path: QualityPath, replacement: JsonValue) -> JsonValue:
    if not path:
        raise QualityContractError("MALFORMED_QUALITY_PAYLOAD", "attack path is empty")
    head, *remaining = path
    match value, head:  # noqa: MATCH_OK - recursive JSON path variants are fully rejected
        case dict() as record, str() as key:
            result = dict(record)
            result[key] = replacement if not remaining else replace_quality(result[key], tuple(remaining), replacement)
            return result
        case list() as items, int() as index:
            result = list(items)
            result[index] = replacement if not remaining else replace_quality(result[index], tuple(remaining), replacement)
            return result
        case _:
            raise QualityContractError("MALFORMED_QUALITY_PAYLOAD", "attack path is invalid")


def remove_quality(value: JsonValue, field: str) -> JsonValue:
    match value:  # noqa: MATCH_OK - artifact top level must be an object
        case dict() as record:
            result = dict(record)
            _ = result.pop(field)
            return result
        case _:
            raise QualityContractError("MALFORMED_QUALITY_PAYLOAD", "attack target is invalid")


def rejected_quality_code[T](action: Callable[[], T], expected: QualityErrorCode) -> bool:
    try:
        _ = action()
    except QualityContractError as error:
        return error.code == expected
    return False


def verify_attack(value: JsonValue, context: QualityTrustContext) -> JsonValue:
    return verify_quality_artifact(value, context).model_dump(mode="json")
