from __future__ import annotations

from typing import Final

from src.v4.models import JsonValue

from .spec_markdown import PRD_FILES, link_targets, parse_json_fences, section_table
from .spec_models import MarkdownDocument, SpecBundle, SpecDocumentError


_PRD_IDS: Final = tuple(f"PRD {index:02d}" for index in range(1, 6))
_PRD_LINKS: Final = tuple(f"prds/{filename}" for filename in PRD_FILES)
_STATUS: Final = "> **상태**: ✅ 구현 완료"
_LIFECYCLE_KEYS: Final = (
    (),
    ("approval_status",),
    ("order_status",),
    ("risk_status", "switch_status"),
    ("promotion_status", "promotion_status_before", "promotion_status_after"),
)
_FORBIDDEN_KEYS: Final = frozenset(
    ("access_token", "account_number", "broker_order_id", "client_secret", "live_order_id", "raw_broker_order_id")
)
_MUTATION_GROUPS: Final = (
    frozenset(("malformed_input", "malformed_json", "json_malformed")),
    frozenset(("stale_state", "dirty_worktree", "stale_quote", "dirty_declared_input", "stale_broker_truth", "stale_source", "dirty_policy")),
    frozenset(("misleading_success_output", "misleading_success")),
    frozenset(("live_state_contamination", "forbidden_field", "real_order_mutation")),
    frozenset(("duplicate_approval", "idempotency_conflict", "interruption_duplicate")),
    frozenset(("hash_mismatch", "hash_mutation")),
    frozenset(("repeated_interruption", "interruption_duplicate_fill", "interruption_duplicate", "interruption_duplicate_promotion")),
    frozenset(("live_state_contamination", "real_order_mutation")),
)


def validate_document_structure(bundle: SpecBundle) -> None:
    for heading in ("Local PRD Links", "Operating Stages", "Link, JSON, And Mutation QA", "Acceptance Criteria"):
        _ = section_table(bundle.spec.text, heading) if heading != "Acceptance Criteria" else _require_heading(bundle.spec, heading)
    for document in bundle.prds:
        _require_heading(document, "Acceptance criteria")


def _require_heading(document: MarkdownDocument, heading: str) -> None:
    if f"## {heading}" not in document.text.splitlines():
        raise SpecDocumentError("V8_DOCUMENT_CONTRACT", f"{document.name}: {heading}")


def validate_prd_table(bundle: SpecBundle) -> None:
    rows = section_table(bundle.spec.text, "Local PRD Links")
    if len(rows) != 5 or any(len(row) != 4 for row in rows):
        raise SpecDocumentError("V8_PRD_TABLE_ORDER", "exact five-row PRD table")
    if tuple(row[0] for row in rows) != _PRD_IDS:
        raise SpecDocumentError("V8_PRD_TABLE_ORDER", "exact PRD 01 to PRD 05 order")
    links = tuple(_link_cell(row[1]) for row in rows)
    if links != _PRD_LINKS:
        raise SpecDocumentError("V8_FORWARD_LINK_COUNT", "exact local PRD link inventory")


def _link_cell(cell: str) -> str:
    targets = link_targets(cell)
    if len(targets) != 1:
        raise SpecDocumentError("V8_FORWARD_LINK_COUNT", cell)
    return targets[0]


def validate_links(bundle: SpecBundle) -> None:
    spec_targets = link_targets(bundle.spec.text)
    for link in _PRD_LINKS:
        if spec_targets.count(link) != 1:
            raise SpecDocumentError("V8_FORWARD_LINK_COUNT", link)
        if not (bundle.spec.path.parent / link).is_file():
            raise SpecDocumentError("V8_FORWARD_LINK_COUNT", f"broken: {link}")
    for document in bundle.prds:
        if link_targets(document.text).count("../SPEC.md") != 1:
            raise SpecDocumentError("V8_BACKLINK_COUNT", document.name)


def validate_status(bundle: SpecBundle) -> None:
    documents = (bundle.spec,) + bundle.prds
    lines = tuple(document.text.splitlines() for document in documents)
    if any(len(document_lines) < 2 or document_lines[1] != _STATUS for document_lines in lines):
        raise SpecDocumentError("V8_IMPLEMENTATION_STATUS", "all line 2 markers")
    rows = section_table(bundle.spec.text, "Local PRD Links")
    if any(len(row) != 4 or row[2] != "✅ 구현 완료" for row in rows):
        raise SpecDocumentError("V8_IMPLEMENTATION_STATUS", "local PRD status column")


def parse_bundle_json(bundle: SpecBundle) -> tuple[tuple[JsonValue, ...], ...]:
    parsed = tuple(parse_json_fences(document) for document in (bundle.spec,) + bundle.prds)
    if sum(len(blocks) for blocks in parsed) != 16:
        raise SpecDocumentError("V8_JSON_MALFORMED", "expected exactly 16 JSON fences")
    return parsed


def _json_keys(value: JsonValue) -> set[str]:
    match value:  # noqa: MATCH_OK - recursive JsonValue variants are fully handled
        case dict() as record:
            record_keys: set[str] = set(record)
            for item in record.values():
                record_keys.update(_json_keys(item))
            return record_keys
        case list() as items:
            array_keys: set[str] = set()
            for item in items:
                array_keys.update(_json_keys(item))
            return array_keys
        case None | bool() | int() | float() | str():
            return set()


def validate_lifecycle(parsed: tuple[tuple[JsonValue, ...], ...]) -> None:
    for index, required in enumerate(_LIFECYCLE_KEYS, start=1):
        keys: set[str] = set()
        for block in parsed[index]:
            keys.update(_json_keys(block))
        if not set(required).issubset(keys) or keys.intersection(("state", "stage")):
            raise SpecDocumentError("V8_LIFECYCLE_FIELD", _PRD_IDS[index - 1])


def _probe_names(document: MarkdownDocument) -> set[str]:
    names: set[str] = set()
    active = False
    for line in document.text.splitlines():
        if line in ("## Failure probes", "## Mutation probes"):
            active = True
            continue
        if active and line.startswith("## "):
            active = False
        if active and line.startswith("|"):
            cells = tuple(cell.strip().strip("`") for cell in line[1:-1].split("|"))
            if cells and cells[0] not in ("probe", "Probe", "---"):
                names.add(cells[0])
    return names


def validate_mutation_coverage(bundle: SpecBundle) -> None:
    names: set[str] = set()
    for document in bundle.prds:
        names.update(_probe_names(document))
    if any(names.isdisjoint(group) for group in _MUTATION_GROUPS):
        raise SpecDocumentError("V8_MUTATION_COVERAGE", "required mutation category missing")


def _validate_side_effect_value(value: JsonValue) -> None:
    match value:  # noqa: MATCH_OK - recursive JsonValue variants are fully handled
        case dict() as record:
            if set(record).intersection(_FORBIDDEN_KEYS):
                raise SpecDocumentError("V8_LIVE_SIDE_EFFECT", "forbidden live field")
            for key, item in record.items():
                if key in ("live_submission", "real_order_created", "portfolio_mutated") and item is not False:
                    raise SpecDocumentError("V8_LIVE_SIDE_EFFECT", key)
                if key == "destination" and item not in ("paper_engine", "broker_dry_run", "internal_dry_run"):
                    raise SpecDocumentError("V8_LIVE_SIDE_EFFECT", "live destination")
                _validate_side_effect_value(item)
        case list() as items:
            for item in items:
                _validate_side_effect_value(item)
        case None | bool() | int() | float() | str():
            return


def validate_no_live_side_effect(parsed: tuple[tuple[JsonValue, ...], ...]) -> None:
    for blocks in parsed:
        for block in blocks:
            _validate_side_effect_value(block)
