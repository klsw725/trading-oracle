from collections.abc import Callable

from src.v4.models import JsonValue

from .models import BuildContext, ErrorCode, ProvenanceContractError
from .provenance import compile_provenance


def replace(value: JsonValue, path: tuple[str, ...], replacement: JsonValue) -> JsonValue:
    match value:  # noqa: MATCH_OK - boundary rejects non-object JSON variants
        case dict() as record if path:
            key, *remaining = path
            result = dict(record)
            result[key] = replacement if not remaining else replace(result[key], tuple(remaining), replacement)
            return result
        case _:
            raise ProvenanceContractError("MALFORMED_PAYLOAD", "attack path is invalid")


def remove(value: JsonValue, path: tuple[str, ...]) -> JsonValue:
    match value:  # noqa: MATCH_OK - boundary rejects non-object JSON variants
        case dict() as record if path:
            key, *remaining = path
            result = dict(record)
            if remaining:
                result[key] = remove(result[key], tuple(remaining))
            else:
                _ = result.pop(key)
            return result
        case _:
            raise ProvenanceContractError("MALFORMED_PAYLOAD", "attack path is invalid")


def insert(value: JsonValue, path: tuple[str, ...], key: str, item: JsonValue) -> JsonValue:
    match value:  # noqa: MATCH_OK - boundary rejects non-object JSON variants
        case dict() as record if path:
            head, *remaining = path
            result = dict(record)
            result[head] = insert(result[head], tuple(remaining), key, item)
            return result
        case dict() as record:
            return {**record, key: item}
        case _:
            raise ProvenanceContractError("MALFORMED_PAYLOAD", "attack path is invalid")


def rejected_code(action: Callable[[], JsonValue], expected: ErrorCode) -> bool:
    try:
        _ = action()
    except ProvenanceContractError as error:
        return error.code == expected
    return False


def compile_attack(value: JsonValue, context: BuildContext) -> JsonValue:
    return compile_provenance(value, context).model_dump(mode="json")
