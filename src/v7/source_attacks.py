from collections.abc import Callable

from src.v4.models import JsonValue

from .source_models import SourcePolicyCode, SourcePolicyError

type SourcePath = tuple[str | int, ...]


def replace_source(value: JsonValue, path: SourcePath, replacement: JsonValue) -> JsonValue:
    if not path:
        raise SourcePolicyError("MALFORMED_SOURCE_POLICY", "empty attack path")
    head, *remaining = path
    match value, head:  # noqa: MATCH_OK - recursive JSON attack paths reject unsupported variants
        case dict() as record, str() as key:
            result = dict(record)
            result[key] = replacement if not remaining else replace_source(result[key], tuple(remaining), replacement)
            return result
        case list() as items, int() as index:
            result = list(items)
            result[index] = replacement if not remaining else replace_source(result[index], tuple(remaining), replacement)
            return result
        case _:
            raise SourcePolicyError("MALFORMED_SOURCE_POLICY", "invalid attack path")


def remove_source(value: JsonValue, path: SourcePath) -> JsonValue:
    if not path:
        raise SourcePolicyError("MALFORMED_SOURCE_POLICY", "empty attack path")
    head, *remaining = path
    match value, head:  # noqa: MATCH_OK - recursive JSON attack paths reject unsupported variants
        case dict() as record, str() as key:
            result = dict(record)
            if remaining:
                result[key] = remove_source(result[key], tuple(remaining))
            else:
                _ = result.pop(key)
            return result
        case list() as items, int() as index if remaining:
            result = list(items)
            result[index] = remove_source(result[index], tuple(remaining))
            return result
        case _:
            raise SourcePolicyError("MALFORMED_SOURCE_POLICY", "invalid attack path")


def rejected_source_code(action: Callable[[], JsonValue], expected: SourcePolicyCode) -> bool:
    try:
        _ = action()
    except SourcePolicyError as error:
        return error.code == expected
    return False
