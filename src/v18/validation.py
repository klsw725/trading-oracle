from datetime import date, datetime, timezone

from .errors import InputValueError


def canonical_utc(value: str) -> str:
    if len(value) != 20 or not value.endswith("Z"):
        raise InputValueError("UTC timestamp must use YYYY-MM-DDTHH:MM:SSZ")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise InputValueError("UTC timestamp is invalid") from error
    if parsed.tzinfo != timezone.utc or parsed.microsecond:
        raise InputValueError("UTC timestamp must be second precision")
    return value


def canonical_date(value: str) -> str:
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise InputValueError("session date is invalid") from error
    if parsed.isoformat() != value:
        raise InputValueError("session must use YYYY-MM-DD")
    return value


def canonical_decimal(value: str) -> str:
    whole, dot, fraction = value.partition(".")
    if dot != "." or len(fraction) != 6 or not whole.isdigit() or not fraction.isdigit():
        raise InputValueError("decimal must be unsigned with six places")
    return value
