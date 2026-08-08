from __future__ import annotations

from pathlib import Path
import re
from typing import Final

from src.v4.models import JsonValue
from src.v8.fixture import parse_json_bytes
from src.v8.models import LedgerContractError

from .spec_models import MarkdownDocument, SpecBundle, SpecDocumentError


PROJECT_ROOT: Final = Path(__file__).resolve().parents[2]
SPEC_PATH: Final = PROJECT_ROOT / "docs/specs/v8/SPEC.md"
PRD_FILES: Final = (
    "prd01-paper-portfolio-ledger.md",
    "prd02-operator-approval-dry-run.md",
    "prd03-order-state-reconciliation.md",
    "prd04-risk-controls-kill-switch.md",
    "prd05-limited-automation-promotion.md",
)
_LINK: Final = re.compile(r"\[[^]]*\]\(([^)]+)\)")


def read_spec_bundle() -> SpecBundle:
    try:
        spec = MarkdownDocument("SPEC", SPEC_PATH, SPEC_PATH.read_text(encoding="utf-8"))
        prds = tuple(
            MarkdownDocument(
                f"PRD {index:02d}",
                SPEC_PATH.parent / "prds" / filename,
                (SPEC_PATH.parent / "prds" / filename).read_text(encoding="utf-8"),
            )
            for index, filename in enumerate(PRD_FILES, start=1)
        )
    except (OSError, UnicodeError) as error:
        raise SpecDocumentError("V8_DOCUMENT_CONTRACT", str(error)) from error
    return SpecBundle(spec, prds)


def section_table(text: str, heading: str) -> tuple[tuple[str, ...], ...]:
    lines = text.splitlines()
    marker = f"## {heading}"
    try:
        start = lines.index(marker) + 1
    except ValueError as error:
        raise SpecDocumentError("V8_DOCUMENT_CONTRACT", f"missing section: {heading}") from error
    table_lines: list[str] = []
    for line in lines[start:]:
        if line.startswith("## "):
            break
        if line.strip().startswith("|"):
            table_lines.append(line.strip())
    if len(table_lines) < 3:
        raise SpecDocumentError("V8_DOCUMENT_CONTRACT", f"missing table: {heading}")
    return tuple(
        tuple(cell.strip() for cell in line[1:-1].split("|"))
        for line in table_lines[2:]
    )


def link_targets(text: str) -> tuple[str, ...]:
    return tuple(match.group(1) for match in _LINK.finditer(text))


def parse_json_fences(document: MarkdownDocument) -> tuple[JsonValue, ...]:
    blocks: list[JsonValue] = []
    body: list[str] | None = None
    for line in document.text.splitlines():
        if body is None:
            if line.strip() == "```json":
                body = []
            continue
        if line.strip() == "```":
            try:
                blocks.append(parse_json_bytes("\n".join(body).encode("utf-8")))
            except LedgerContractError as error:
                raise SpecDocumentError(
                    "V8_JSON_MALFORMED", f"{document.name}: {error}"
                ) from error
            body = None
            continue
        body.append(line)
    if body is not None:
        raise SpecDocumentError("V8_JSON_MALFORMED", f"{document.name}: unclosed JSON fence")
    return tuple(blocks)
