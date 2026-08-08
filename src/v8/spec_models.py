from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, override


type SpecErrorCode = Literal[
    "V8_DOCUMENT_CONTRACT",
    "V8_PRD_TABLE_ORDER",
    "V8_FORWARD_LINK_COUNT",
    "V8_BACKLINK_COUNT",
    "V8_IMPLEMENTATION_STATUS",
    "V8_JSON_MALFORMED",
    "V8_LIFECYCLE_FIELD",
    "V8_MUTATION_COVERAGE",
    "V8_LIVE_SIDE_EFFECT",
]


@dataclass(frozen=True, slots=True)
class SpecDocumentError(ValueError):
    code: SpecErrorCode
    detail: str

    @override
    def __str__(self) -> str:
        return f"{self.code}: {self.detail}"


@dataclass(frozen=True, slots=True)
class MarkdownDocument:
    name: str
    path: Path
    text: str


@dataclass(frozen=True, slots=True)
class SpecBundle:
    spec: MarkdownDocument
    prds: tuple[MarkdownDocument, ...]
