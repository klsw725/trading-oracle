from collections.abc import Callable

from src.v4.models import JsonValue

from .value_artifact import verify_value_artifact
from .value_models import ValueContractError, ValueErrorCode
from .value_trust import ValueTrustContext

type ValuePath = tuple[str | int, ...]


def replace_value(value: JsonValue, path: ValuePath, replacement: JsonValue) -> JsonValue:
    if not path:
        raise ValueContractError("MALFORMED_EVALUATION_INPUT", "attack path is empty")
    head, *remaining = path
    match value, head:  # noqa: MATCH_OK - recursive JSON path variants are rejected
        case dict() as record, str() as key:
            result = dict(record)
            result[key] = replacement if not remaining else replace_value(result[key], tuple(remaining), replacement)
            return result
        case list() as items, int() as index:
            result = list(items)
            result[index] = replacement if not remaining else replace_value(result[index], tuple(remaining), replacement)
            return result
        case _:
            raise ValueContractError("MALFORMED_EVALUATION_INPUT", "attack path is invalid")


def remove_value(value: JsonValue, path: ValuePath) -> JsonValue:
    if not path:
        raise ValueContractError("MALFORMED_EVALUATION_INPUT", "attack path is empty")
    head, *remaining = path
    match value, head:  # noqa: MATCH_OK - recursive JSON path variants are rejected
        case dict() as record, str() as key:
            result = dict(record)
            if remaining:
                result[key] = remove_value(result[key], tuple(remaining))
            else:
                _ = result.pop(key)
            return result
        case list() as items, int() as index if remaining:
            result = list(items)
            result[index] = remove_value(result[index], tuple(remaining))
            return result
        case _:
            raise ValueContractError("MALFORMED_EVALUATION_INPUT", "attack path is invalid")


def rejected_value_code(action: Callable[[], JsonValue], expected: ValueErrorCode) -> bool:
    try:
        _ = action()
    except ValueContractError as error:
        return error.code == expected
    return False


def verify_value_attack(value: JsonValue, context: ValueTrustContext) -> JsonValue:
    return verify_value_artifact(value, context).model_dump(mode="json")
