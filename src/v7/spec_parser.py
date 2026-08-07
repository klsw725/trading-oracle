from pathlib import Path
import re
from typing import Final, Literal

from .spec_json import parse_spec_contract
from .spec_models import PrdDocument, SpecBundle, SpecVerificationError, SpecVerificationReport
from .spec_validation import validate_contract, validate_narrative, validate_prd_contracts


type SpecMutation = Literal[
    "prd_row_missing", "prd_link_duplicate", "bidirectional_gap", "state_jump",
    "quality_count_misuse", "source_addition_success", "latency_only_success",
    "harmful_source_current", "stale_cache_current", "policy_hash_mismatch",
]

_PROJECT_ROOT: Final = Path(__file__).resolve().parents[2]
_V7_ROOT: Final = (_PROJECT_ROOT / "docs/specs/v7").resolve()
_MAP_ROW: Final = re.compile(r"^\| (PRD 0[1-4]) \| \[[^]]+\]\(([^)]+)\) \|.*?\| (.*?) \| (.*?) \|$", re.MULTILINE)
_LOCAL_LINK: Final = re.compile(r"\[[^]]*\]\((?!https?://|mailto:|#)([^)]+)\)")
_EXPECTED_CODES: Final[dict[SpecMutation, str]] = {
    "prd_row_missing": "V7_PRD_ROW_MISSING",
    "prd_link_duplicate": "V7_PRD_LINK_DUPLICATE",
    "bidirectional_gap": "V7_PRD_BIDIRECTIONAL_GAP",
    "state_jump": "ILLEGAL_PROMOTION_JUMP",
    "quality_count_misuse": "COUNT_USED_AS_QUALITY",
    "source_addition_success": "REJECT_NO_INCREMENTAL_VALUE",
    "latency_only_success": "REJECT_LATENCY_ONLY",
    "harmful_source_current": "FALLBACK_USES_INELIGIBLE_SOURCE",
    "stale_cache_current": "STALE_CACHE_POLICY_MISMATCH",
    "policy_hash_mismatch": "POLICY_HASH_MISMATCH",
}


def _confined(path: Path) -> Path:
    resolved = path.resolve()
    try:
        _ = resolved.relative_to(_V7_ROOT)
    except ValueError as error:
        raise SpecVerificationError("V7_SPEC_PATH_UNSAFE", str(path)) from error
    return resolved


def _map_rows(text: str) -> tuple[tuple[str, str, str, str], ...]:
    return tuple(
        (match.group(1), match.group(2), match.group(3), match.group(4))
        for match in _MAP_ROW.finditer(text)
    )


def read_spec_bundle(spec_path: Path) -> SpecBundle:
    safe_spec = _confined(spec_path)
    try:
        text = safe_spec.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise SpecVerificationError("V7_PRD_LINK_BROKEN", str(error)) from error
    rows = _map_rows(text)
    documents: list[PrdDocument] = []
    for prd_id, href, _, _ in rows:
        if not href.startswith("prds/") or Path(href).is_absolute() or ".." in Path(href).parts:
            raise SpecVerificationError("V7_SPEC_PATH_UNSAFE", href)
        linked_path = _confined(safe_spec.parent / href)
        try:
            linked_text = linked_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            raise SpecVerificationError("V7_PRD_LINK_BROKEN", href) from error
        documents.append(PrdDocument(prd_id, linked_path, linked_text))
    return SpecBundle(safe_spec, text, tuple(documents))


def _validate_local_links(bundle: SpecBundle) -> None:
    documents = ((bundle.spec_path, bundle.spec_text),) + tuple(
        (document.path, document.text) for document in bundle.prds
    )
    for document_path, text in documents:
        for match in _LOCAL_LINK.finditer(text):
            href = match.group(1)
            target_text = href.partition("#")[0]
            if not target_text:
                continue
            target = _confined(document_path.parent / target_text)
            if not target.is_file():
                raise SpecVerificationError("V7_PRD_LINK_BROKEN", href)


def _validate_map(bundle: SpecBundle) -> None:
    rows = _map_rows(bundle.spec_text)
    expected = ("PRD 01", "PRD 02", "PRD 03", "PRD 04")
    if tuple(row[0] for row in rows) != expected or tuple(item.prd_id for item in bundle.prds) != expected:
        raise SpecVerificationError("V7_PRD_ROW_MISSING", "local PRD map")
    links = tuple(row[1] for row in rows)
    for link in links:
        if bundle.spec_text.count(f"]({link})") != 1:
            raise SpecVerificationError("V7_PRD_LINK_DUPLICATE", link)
    for index in range(3):
        prior = expected[index]
        later = expected[index + 1]
        if later not in rows[index][3] or prior not in rows[index + 1][2]:
            raise SpecVerificationError("V7_PRD_BIDIRECTIONAL_GAP", f"{prior} -> {later}")


def verify_spec_bundle(bundle: SpecBundle) -> SpecVerificationReport:
    _validate_map(bundle)
    _validate_local_links(bundle)
    contract = parse_spec_contract(bundle.spec_text)
    validate_contract(contract)
    validate_narrative(bundle.spec_text)
    prd_blocks = validate_prd_contracts(bundle.prds)
    return SpecVerificationReport(contract.schema_version, prd_blocks + 1, len(bundle.prds))


def expected_mutation_code(mutation: SpecMutation) -> str:
    return _EXPECTED_CODES[mutation]


def _replace(text: str, old: str, new: str) -> str:
    if old not in text:
        raise SpecVerificationError("V7_SPEC_MALFORMED", f"mutation target absent: {old}")
    return text.replace(old, new, 1)


def mutate_bundle(bundle: SpecBundle, mutation: SpecMutation) -> SpecBundle:
    text = bundle.spec_text
    match mutation:  # noqa: MATCH_OK - every SpecMutation Literal has a returning case
        case "prd_row_missing":
            row = next(line for line in text.splitlines(keepends=True) if line.startswith("| PRD 02 |"))
            text = text.replace(row, "", 1)
            prds = tuple(item for item in bundle.prds if item.prd_id != "PRD 02")
            return SpecBundle(bundle.spec_path, text, prds)
        case "prd_link_duplicate":
            text = _replace(text, "## Current Source Baseline", "[duplicate](prds/prd01-source-adapter-provenance.md)\n\n## Current Source Baseline")
            return SpecBundle(bundle.spec_path, text, bundle.prds)
        case "bidirectional_gap":
            text = _replace(text, "PRD 03 prompt eligibility input and PRD 04 quality gate.", "Quality gate output omitted.")
            return SpecBundle(bundle.spec_path, text, bundle.prds)
        case "state_jump":
            text = _replace(text, "candidate -> shadow", "candidate -> primary")
            return SpecBundle(bundle.spec_path, text, bundle.prds)
        case "quality_count_misuse":
            text = _replace(text, "Count is not quality.", "Count is quality.")
            return SpecBundle(bundle.spec_path, text, bundle.prds)
        case "source_addition_success":
            text = _replace(text, "is not success.", "is success.")
            return SpecBundle(bundle.spec_path, text, bundle.prds)
        case "latency_only_success":
            text = _replace(text, "still fails when factual correction and verdict lift do not pass", "passes with zero source value")
            return SpecBundle(bundle.spec_path, text, bundle.prds)
        case "harmful_source_current":
            text = _replace(text, "keeps disabled fallback", "removes disabled fallback")
            return SpecBundle(bundle.spec_path, text, bundle.prds)
        case "stale_cache_current":
            text = _replace(text, "counts stale cache as fresh", "keeps stale cache current")
            return SpecBundle(bundle.spec_path, text, bundle.prds)
        case "policy_hash_mismatch":
            text = _replace(text, "matching policy hash", "mismatched policy hash")
            return SpecBundle(bundle.spec_path, text, bundle.prds)
