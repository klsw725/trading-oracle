from __future__ import annotations

from pathlib import Path
import re

from pydantic import ValidationError

from .canonical import JsonValue
from .errors import FailureCode, V16Failure
from .models import Market, RuntimeConfig
from .registries import CONFIG_SCHEMAS, DATASET_KINDS, POLICIES


_INTEGER = re.compile(r"^-?(0|[1-9][0-9]*)$")
_FLOAT = re.compile(r"^-?(0|[1-9][0-9]*)\.[0-9]+$")
_MARKET_IDENTITIES = {
    Market.KR: ("KRW", "Asia/Seoul"),
    Market.US: ("USD", "America/New_York"),
}


def _scalar(text: str) -> JsonValue:
    value = text.strip()
    if value.startswith(("!!", "!<", "&", "*")) or value.lower() in {
            ".nan", ".inf", "+.inf", "-.inf"} or value.startswith(("{", "[")) or \
            re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}([Tt ].*)?", value):
        raise V16Failure(FailureCode.CONFIG_PARSE_ERROR, "forbidden YAML tag")
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    if _INTEGER.fullmatch(value):
        return int(value)
    if _FLOAT.fullmatch(value):
        return float(value)
    special: dict[str, JsonValue] = {"true": True, "false": False, "null": None, "~": None}
    return special.get(value.lower(), value)


def _mapping(text: str) -> dict[str, JsonValue]:
    root: dict[str, JsonValue] = {}
    stack: list[tuple[int, dict[str, JsonValue]]] = [(-1, root)]
    for source_line in text.splitlines():
        if not source_line.strip() or source_line.lstrip().startswith("#"):
            continue
        content = source_line.split(" #", maxsplit=1)[0].rstrip()
        indent = len(content) - len(content.lstrip(" "))
        if "\t" in source_line[:indent] or ":" not in content:
            raise V16Failure(FailureCode.CONFIG_PARSE_ERROR, "invalid YAML mapping")
        while stack[-1][0] >= indent:
            _ = stack.pop()
        parent = stack[-1][1]
        key, raw_value = content.strip().split(":", maxsplit=1)
        if not key or key in parent:
            raise V16Failure(FailureCode.CONFIG_PARSE_ERROR, "duplicate or empty YAML key")
        if raw_value.strip():
            parent[key] = _scalar(raw_value)
        else:
            child: dict[str, JsonValue] = {}
            parent[key] = child
            stack.append((indent, child))
    return root


def load_config(path: Path) -> RuntimeConfig:
    try:
        document = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise V16Failure(FailureCode.CONFIG_NOT_READABLE, "config cannot be read") from error
    if not document.strip():
        raise V16Failure(FailureCode.CONFIG_PARSE_ERROR, "empty YAML")
    try:
        config = RuntimeConfig.model_validate(_mapping(document))
    except ValidationError as error:
        code = FailureCode.UNKNOWN_CONFIG_KEY if any(item["type"] == "extra_forbidden"
                                                       for item in error.errors()) else FailureCode.CONFIG_PARSE_ERROR
        raise V16Failure(code, "config schema rejected") from error
    if config.config_schema_version not in CONFIG_SCHEMAS:
        raise V16Failure(FailureCode.UNSUPPORTED_CONFIG_SCHEMA, "unsupported schema")
    if config.policy_version not in POLICIES:
        raise V16Failure(FailureCode.UNKNOWN_POLICY_VERSION, "unknown policy")
    if set(config.markets) != {Market.KR, Market.US}:
        raise V16Failure(FailureCode.CONFIG_PARSE_ERROR, "KR and US settings required")
    if any(
            (settings.currency, settings.timezone) != _MARKET_IDENTITIES[market]
            for market, settings in config.markets.items()):
        raise V16Failure(FailureCode.CONFIG_PARSE_ERROR, "market identity mismatch")
    if set(config.data.freshness_minutes) != set(DATASET_KINDS):
        raise V16Failure(FailureCode.CONFIG_PARSE_ERROR, "unknown data policy")
    freshness = config.data.freshness_minutes["minute-bars"]
    if set(freshness) != {Market.KR, Market.US}:
        raise V16Failure(FailureCode.CONFIG_PARSE_ERROR, "invalid freshness policy")
    return config
