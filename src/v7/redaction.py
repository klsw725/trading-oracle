from dataclasses import dataclass
import re
from typing import Final

from src.v4.models import JsonValue, canonical_json

from .sensitive_data import contains_sensitive, key_kind, redact_text, replacement
_INJECTION_TEXT: Final = re.compile(
    r"(?:ignore\s+(?:all\s+)?previous\s+instructions|system\s+prompt|developer\s+message)",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class RedactionResult:
    value: JsonValue
    replacement_count: int


def redact(value: JsonValue) -> RedactionResult:
    match value:  # noqa: MATCH_OK - recursive JsonValue variants are fully handled
        case dict() as record:
            result: dict[str, JsonValue] = {}
            count = 0
            for key, item in record.items():
                if (kind := key_kind(key)) is not None:
                    result[key] = replacement(kind)
                    count += 1
                else:
                    nested = redact(item)
                    result[key] = nested.value
                    count += nested.replacement_count
            return RedactionResult(result, count)
        case list() as items:
            values: list[JsonValue] = []
            count = 0
            for item in items:
                nested = redact(item)
                values.append(nested.value)
                count += nested.replacement_count
            return RedactionResult(values, count)
        case str() as text:
            replaced, count = redact_text(text)
            return RedactionResult(replaced, count)
        case None as scalar:
            return RedactionResult(scalar, 0)
        case bool() as scalar:
            return RedactionResult(scalar, 0)
        case int() as scalar:
            return RedactionResult(scalar, 0)
        case float() as scalar:
            return RedactionResult(scalar, 0)


def contains_secret(value: JsonValue) -> bool:
    return contains_sensitive(value)


def contains_trusted_injection(value: JsonValue) -> bool:
    match value:  # noqa: MATCH_OK - only object records can carry trust metadata
        case dict() as record:
            trusted = record.get("external_text_trust") == "trusted" or record.get("prompt_eligible") is True
            return trusted and bool(_INJECTION_TEXT.search(canonical_json(value).decode("utf-8")))
        case _:
            return False
