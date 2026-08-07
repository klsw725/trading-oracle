import re
from enum import StrEnum, unique
from typing import Final

from src.v4.models import JsonValue

_SECRET_KEYS: Final = frozenset(
    {
        "access_token",
        "api_key",
        "authorization",
        "bearer",
        "client_secret",
        "cookie",
        "credential",
        "password",
        "refresh_token",
        "session_id",
        "signed_url",
    }
)
_USER_KEYS: Final = frozenset(
    {
        "account",
        "account_number",
        "brokerage_account",
        "free_text",
        "portfolio_free_text",
        "portfolio_text",
        "user_input",
        "user_prompt",
        "user_text",
    }
)
_SECRET_TEXT: Final = re.compile(
    r"(?:bearer\s+[A-Za-z0-9._~+/=-]+|(?:token|api[_-]?key|cookie|password|session_id)\s*[=:]\s*[^\s&]+)",
    re.IGNORECASE,
)
_ACCOUNT_IDENTIFIER: Final = re.compile(r"(?<!\d)(?:\d[ -]?){10,16}(?!\d)")
_HASH_TEXT: Final = re.compile(r"^sha256:[0-9a-f]{64}$")
_FINANCIAL_FREE_TEXT: Final = re.compile(
    r"(?:\b(?:my|our)\s+(?:portfolio|account|holdings?)\b|\b(?:i|we)\s+(?:own|hold|bought|sold)\b|\b(?:average\s+(?:purchase\s+)?price|cost\s+basis)\b|(?:내|저의|우리)\s*(?:포트폴리오|계좌|보유)|(?:보유|매수|매도)\s*(?:수량|내역|종목)|평단(?:가)?)",
    re.IGNORECASE,
)


@unique
class SensitiveKind(StrEnum):
    SECRET = "secret"
    USER_FINANCIAL = "user_financial"


def key_kind(key: str) -> SensitiveKind | None:
    normalized = key.strip().lower().replace("-", "_")
    if normalized in _SECRET_KEYS:
        return SensitiveKind.SECRET
    if normalized in _USER_KEYS:
        return SensitiveKind.USER_FINANCIAL
    return None


def text_kind(text: str) -> SensitiveKind | None:
    if _HASH_TEXT.fullmatch(text):
        return None
    if _SECRET_TEXT.search(text):
        return SensitiveKind.SECRET
    if _ACCOUNT_IDENTIFIER.search(text) or _FINANCIAL_FREE_TEXT.search(text):
        return SensitiveKind.USER_FINANCIAL
    return None


def replacement(kind: SensitiveKind) -> str:
    return {
        SensitiveKind.SECRET: "[REDACTED_SECRET]",
        SensitiveKind.USER_FINANCIAL: "[REDACTED_USER_DATA]",
    }[kind]


def redact_text(text: str) -> tuple[str, int]:
    kind = text_kind(text)
    if kind is SensitiveKind.USER_FINANCIAL:
        return replacement(kind), 1
    replaced, count = _SECRET_TEXT.subn("[REDACTED_SECRET]", text)
    return replaced, count


def contains_sensitive(value: JsonValue) -> bool:
    match value:  # noqa: MATCH_OK - recursive JsonValue variants are fully handled
        case dict() as record:
            return any(
                key_kind(key) is not None or contains_sensitive(item)
                for key, item in record.items()
            )
        case list() as items:
            return any(contains_sensitive(item) for item in items)
        case str() as text:
            return text_kind(text) is not None
        case None | bool() | int() | float():
            return False
