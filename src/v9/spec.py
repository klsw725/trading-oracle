from __future__ import annotations

import json
from math import isfinite
from pathlib import Path
import re
from typing import Final

from pydantic import RootModel, ValidationError

from src.v4.models import JsonValue
from src.v9.contract import V9ContractError


_ROOT: Final = Path(__file__).resolve().parents[2]
SPEC_PATH: Final = _ROOT / "docs/specs/v9/SPEC.md"
PRD_PATHS: Final = tuple(sorted((SPEC_PATH.parent / "prds").glob("prd*.md")))
_PRD_NAMES: Final = (
    "prd01-dashboard-input-contract.md",
    "prd02-replay-information-architecture.md",
    "prd03-risk-health-calibration-surfaces.md",
    "prd04-accessibility-responsive-errors.md",
    "prd05-rollout-observability.md",
)
_JSON_FENCE: Final = re.compile(
    r"^```json[ \t]*\n(?P<body>.*?)^```[ \t]*$", re.MULTILINE | re.DOTALL
)


class JsonBoundary(RootModel[JsonValue]):
    pass


class DuplicateKeyError(ValueError):
    pass


def _pairs(values: list[tuple[str, JsonValue]]) -> dict[str, JsonValue]:
    result: dict[str, JsonValue] = {}
    for key, value in values:
        if key in result:
            raise DuplicateKeyError(key)
        result[key] = value
    return result


def _constant(value: str) -> JsonValue:
    raise V9ContractError("V9_JSON_PARSE_ERROR", f"forbidden constant {value}")


def _finite(value: JsonValue) -> None:
    match value:  # noqa: MATCH_OK - recursive JSON variants are fully handled
        case dict() as record:
            for item in record.values():
                _finite(item)
        case list() as items:
            for item in items:
                _finite(item)
        case float() as number if not isfinite(number):
            raise V9ContractError("V9_JSON_PARSE_ERROR", "non-finite JSON number")
        case None | bool() | int() | float() | str():
            return


def parse_json_fences(markdown: str) -> tuple[JsonValue, ...]:
    blocks: list[JsonValue] = []
    for match in _JSON_FENCE.finditer(markdown):
        try:
            value = JsonBoundary.model_validate(
                json.loads(
                    match.group("body"),
                    object_pairs_hook=_pairs,
                    parse_constant=_constant,
                )
            ).root
        except (json.JSONDecodeError, DuplicateKeyError, ValidationError) as error:
            raise V9ContractError("V9_JSON_PARSE_ERROR", str(error)) from error
        _finite(value)
        blocks.append(value)
    return tuple(blocks)


def parse_json_bytes(payload: bytes) -> JsonValue:
    try:
        value = JsonBoundary.model_validate(
            json.loads(payload, object_pairs_hook=_pairs, parse_constant=_constant)
        ).root
    except (json.JSONDecodeError, DuplicateKeyError, UnicodeDecodeError, ValidationError) as error:
        raise V9ContractError("V9_JSON_PARSE_ERROR", str(error)) from error
    _finite(value)
    return value


def _table_rows(markdown: str) -> tuple[tuple[str, ...], ...]:
    lines = markdown.splitlines()
    start = lines.index("## Local PRD Map")
    rows: list[tuple[str, ...]] = []
    for line in lines[start + 1 :]:
        if line.startswith("## "):
            break
        if re.match(r"^\| PRD \d{2} \|", line):
            rows.append(tuple(cell.strip() for cell in line[1:-1].split("|")))
    return tuple(rows)


def _verify_content(spec: str, prds: tuple[str, ...]) -> tuple[int, int]:
    if spec.splitlines()[:2] != [
        "# Trading Oracle v9 SPEC: Dashboard Read Contract",
        "> **상태**: 📝 초안",
    ]:
        raise V9ContractError("V9_SPEC_DRAFT_INVALID", "SPEC title or draft marker")
    if len(PRD_PATHS) != 5 or tuple(path.name for path in PRD_PATHS) != _PRD_NAMES:
        raise V9ContractError("V9_PRD_TABLE_INVALID", "exact PRD file inventory")
    rows = _table_rows(spec)
    if len(rows) != 5 or tuple(row[0] for row in rows) != tuple(
        f"PRD {index:02d}" for index in range(1, 6)
    ):
        raise V9ContractError("V9_PRD_TABLE_INVALID", "exact PRD row order")
    for index, name in enumerate(_PRD_NAMES):
        link = f"prds/{name}"
        if link not in rows[index][1] or spec.count(f"]({link})") != 1:
            raise V9ContractError("V9_PRD_TABLE_INVALID", link)
        lines = prds[index].splitlines()
        if len(lines) < 3 or lines[1] != "> **상태**: 📝 초안":
            raise V9ContractError("V9_SPEC_DRAFT_INVALID", name)
        if lines[2] != "> **SPEC 참조**: [v9 SPEC](../SPEC.md)" or prds[index].count(
            "](../SPEC.md)"
        ) != 1:
            raise V9ContractError("V9_PRD_BACKLINK_INVALID", name)
    json_count = sum(len(parse_json_fences(text)) for text in (spec, *prds))
    return len(prds), json_count


def verify_documents() -> tuple[int, int]:
    try:
        spec = SPEC_PATH.read_text(encoding="utf-8")
        prds = tuple(path.read_text(encoding="utf-8") for path in PRD_PATHS)
    except OSError as error:
        raise V9ContractError("V9_SPEC_DRAFT_INVALID", str(error)) from error
    return _verify_content(spec, prds)


def run_document_probes() -> JsonValue:
    try:
        spec = SPEC_PATH.read_text(encoding="utf-8")
        prds = tuple(path.read_text(encoding="utf-8") for path in PRD_PATHS)
    except OSError as error:
        raise V9ContractError("V9_SPEC_DRAFT_INVALID", str(error)) from error
    lines = spec.splitlines(keepends=True)
    first = next(index for index, line in enumerate(lines) if line.startswith("| PRD 01 |"))
    second = next(index for index, line in enumerate(lines) if line.startswith("| PRD 02 |"))
    lines[first], lines[second] = lines[second], lines[first]
    malformed = prds[0].replace('"schema_version":', '"schema_version"', 1)
    duplicate_target = '  "schema_version": "1.0.0",'
    duplicate = prds[0].replace(duplicate_target, f"{duplicate_target}\n{duplicate_target}", 1)
    non_finite = prds[0].replace('"score": 0.98', '"score": NaN', 1)
    mutations = (
        ("draft_marker", spec.replace("📝 초안", "✅ 구현 완료", 1), prds, "V9_SPEC_DRAFT_INVALID"),
        ("prd_row_order", "".join(lines), prds, "V9_PRD_TABLE_INVALID"),
        ("backlink", spec, (prds[0].replace("](../SPEC.md)", "](removed.md)", 1), *prds[1:]), "V9_PRD_BACKLINK_INVALID"),
        ("malformed_json", spec, (malformed, *prds[1:]), "V9_JSON_PARSE_ERROR"),
        ("duplicate_json_key", spec, (duplicate, *prds[1:]), "V9_JSON_PARSE_ERROR"),
        ("non_finite_json", spec, (non_finite, *prds[1:]), "V9_JSON_PARSE_ERROR"),
    )
    results: dict[str, JsonValue] = {}
    for name, mutated_spec, mutated_prds, expected in mutations:
        observed: str | None = None
        try:
            _ = _verify_content(mutated_spec, mutated_prds)
        except V9ContractError as error:
            observed = error.code
        results[name] = {
            "state": "pass" if observed == expected else "fail",
            "expected_error_code": expected,
            "observed_error_code": observed,
        }
    return results
