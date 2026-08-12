from __future__ import annotations

from pathlib import Path
from typing import Final

from src.v4.models import JsonValue

from .models import V10ContractError


ROOT: Final = Path(__file__).resolve().parents[2]
SPEC_PATH: Final = ROOT / "docs/specs/v10/SPEC.md"
PRD_PATHS: Final = tuple(sorted((SPEC_PATH.parent / "prds").glob("prd*.md")))
EXPECTED_PRDS: Final = (
    "prd01-calendar-source-minute-contract.md",
    "prd02-five-minute-watermark-revision.md",
    "prd03-universe-corporate-action-eligibility.md",
    "prd04-context-canonical-acceptance.md",
)


def verify_documents() -> JsonValue:
    try:
        spec = SPEC_PATH.read_text(encoding="utf-8")
        prds = tuple(path.read_text(encoding="utf-8") for path in PRD_PATHS)
    except OSError as error:
        raise V10ContractError("V10_SPEC_INVALID", str(error)) from error
    if spec.splitlines()[:2] != [
        "# Trading Oracle v10 SPEC: Intraday Data Foundation",
        "> **상태**: 📝 초안",
    ]:
        raise V10ContractError("V10_SPEC_INVALID", "title or draft marker")
    if tuple(path.name for path in PRD_PATHS) != EXPECTED_PRDS:
        raise V10ContractError("V10_PRD_MAP_INVALID", "exact PRD inventory")
    rows = tuple(line for line in spec.splitlines() if line.startswith("| PRD 0"))
    if len(rows) != 4:
        raise V10ContractError("V10_PRD_MAP_INVALID", "four PRD rows required")
    for index, (name, prd) in enumerate(zip(EXPECTED_PRDS, prds, strict=True), start=1):
        if not rows[index - 1].startswith(f"| PRD {index:02d} |"):
            raise V10ContractError("V10_PRD_MAP_INVALID", "row order")
        link = f"prds/{name}"
        if spec.count(f"]({link})") != 1:
            raise V10ContractError("V10_PRD_MAP_INVALID", link)
        lines = prd.splitlines()
        if len(lines) < 3 or lines[1] != "> **상태**: 📝 초안":
            raise V10ContractError("V10_SPEC_INVALID", name)
        if lines[2] != "> 상위 SPEC: [v10 SPEC](../SPEC.md)" or prd.count("](../SPEC.md)") != 1:
            raise V10ContractError("V10_PRD_BACKLINK_INVALID", name)
    return {"state": "pass", "linked_prd_count": 4, "draft_document_count": 5}
