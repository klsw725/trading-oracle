from __future__ import annotations

from dataclasses import replace
from typing import Final, Literal

from src.v4.models import JsonValue

from .spec_markdown import read_spec_bundle
from .spec_models import SpecBundle, SpecDocumentError, SpecErrorCode
from .spec_validation import (
    parse_bundle_json,
    validate_document_structure,
    validate_lifecycle,
    validate_links,
    validate_mutation_coverage,
    validate_no_live_side_effect,
    validate_prd_table,
    validate_status,
)


type SpecMutation = Literal[
    "document_section_missing",
    "prd_table_reordered",
    "forward_link_duplicate",
    "backlink_missing",
    "spec_status_draft",
    "table_status_draft",
    "malformed_json",
    "duplicate_json_key",
    "non_finite_json",
    "lifecycle_alias",
    "mutation_coverage_missing",
    "live_side_effect",
]

MUTATIONS: Final[tuple[SpecMutation, ...]] = (
    "document_section_missing", "prd_table_reordered", "forward_link_duplicate",
    "backlink_missing", "spec_status_draft", "table_status_draft", "malformed_json",
    "duplicate_json_key", "non_finite_json", "lifecycle_alias",
    "mutation_coverage_missing", "live_side_effect",
)
_EXPECTED: Final[dict[SpecMutation, SpecErrorCode]] = {
    "document_section_missing": "V8_DOCUMENT_CONTRACT",
    "prd_table_reordered": "V8_PRD_TABLE_ORDER",
    "forward_link_duplicate": "V8_FORWARD_LINK_COUNT",
    "backlink_missing": "V8_BACKLINK_COUNT",
    "spec_status_draft": "V8_IMPLEMENTATION_STATUS",
    "table_status_draft": "V8_IMPLEMENTATION_STATUS",
    "malformed_json": "V8_JSON_MALFORMED",
    "duplicate_json_key": "V8_JSON_MALFORMED",
    "non_finite_json": "V8_JSON_MALFORMED",
    "lifecycle_alias": "V8_LIFECYCLE_FIELD",
    "mutation_coverage_missing": "V8_MUTATION_COVERAGE",
    "live_side_effect": "V8_LIVE_SIDE_EFFECT",
}


def _replace(text: str, old: str, new: str) -> str:
    if old not in text:
        raise SpecDocumentError("V8_DOCUMENT_CONTRACT", f"mutation target absent: {old}")
    return text.replace(old, new, 1)


def _prd(bundle: SpecBundle, index: int, text: str) -> SpecBundle:
    documents = list(bundle.prds)
    documents[index] = replace(documents[index], text=text)
    return replace(bundle, prds=tuple(documents))


def _swap_rows(text: str) -> str:
    lines = text.splitlines(keepends=True)
    first = next(index for index, line in enumerate(lines) if line.startswith("| PRD 01 |"))
    second = next(index for index, line in enumerate(lines) if line.startswith("| PRD 02 |"))
    lines[first], lines[second] = lines[second], lines[first]
    return "".join(lines)


def _drop_live_probes(bundle: SpecBundle) -> SpecBundle:
    blocked = ("live_state_contamination", "forbidden_field", "real_order_mutation")
    documents = tuple(
        replace(
            document,
            text="\n".join(
                line for line in document.text.splitlines()
                if not (line.startswith("|") and any(f"`{name}`" in line for name in blocked))
            ) + "\n",
        )
        for document in bundle.prds
    )
    return replace(bundle, prds=documents)


def mutate_bundle(bundle: SpecBundle, mutation: SpecMutation) -> SpecBundle:
    match mutation:  # noqa: MATCH_OK - every SpecMutation has a returning case
        case "document_section_missing":
            return replace(bundle, spec=replace(bundle.spec, text=_replace(bundle.spec.text, "## Link, JSON, And Mutation QA", "## Removed QA")))
        case "prd_table_reordered":
            return replace(bundle, spec=replace(bundle.spec, text=_swap_rows(bundle.spec.text)))
        case "forward_link_duplicate":
            return replace(bundle, spec=replace(bundle.spec, text=_replace(bundle.spec.text, "prds/prd02-operator-approval-dry-run.md", "prds/prd01-paper-portfolio-ledger.md")))
        case "backlink_missing":
            return _prd(bundle, 0, _replace(bundle.prds[0].text, "](../SPEC.md)", "](SPEC-removed.md)"))
        case "spec_status_draft":
            return replace(bundle, spec=replace(bundle.spec, text=_replace(bundle.spec.text, "✅ 구현 완료", "📝 초안")))
        case "table_status_draft":
            marker = "| ✅ 구현 완료 |"
            return replace(bundle, spec=replace(bundle.spec, text=_replace(bundle.spec.text, marker, "| 📝 초안 |")))
        case "malformed_json":
            return _prd(bundle, 0, _replace(bundle.prds[0].text, '"schema_version":', '"schema_version"'))
        case "duplicate_json_key":
            target = '  "schema_version": "v8.paper_portfolio_ledger.prd01.fixture.1",'
            return _prd(bundle, 0, _replace(bundle.prds[0].text, target, f"{target}\n{target}"))
        case "non_finite_json":
            return _prd(bundle, 3, _replace(bundle.prds[3].text, '"cooldown_seconds": 900', '"cooldown_seconds": NaN'))
        case "lifecycle_alias":
            return _prd(bundle, 1, _replace(bundle.prds[1].text, '"approval_status":', '"state":'))
        case "mutation_coverage_missing":
            return _drop_live_probes(bundle)
        case "live_side_effect":
            return _prd(bundle, 1, _replace(bundle.prds[1].text, '"live_submission": false', '"live_submission": true'))


def verify_spec_bundle(bundle: SpecBundle) -> tuple[dict[str, bool], int]:
    validate_document_structure(bundle)
    validate_prd_table(bundle)
    validate_links(bundle)
    validate_status(bundle)
    parsed = parse_bundle_json(bundle)
    validate_lifecycle(parsed)
    validate_mutation_coverage(bundle)
    validate_no_live_side_effect(parsed)
    checks = {
        "document_structure": True,
        "exact_prd_table_order": True,
        "forward_links_once": True,
        "backlinks_once": True,
        "implementation_status_complete": True,
        "all_json_fences_strict": True,
        "lifecycle_fields_exact": True,
        "mutation_coverage_complete": True,
        "no_live_side_effect_boundary": True,
    }
    return checks, sum(len(blocks) for blocks in parsed)


def run_spec_acceptance() -> JsonValue:
    try:
        bundle = read_spec_bundle()
        checks, json_count = verify_spec_bundle(bundle)
    except SpecDocumentError as error:
        return {"state": "fail", "error_code": error.code, "detail": str(error)}
    results: dict[str, JsonValue] = {}
    accepted_results: list[bool] = []
    for mutation in MUTATIONS:
        observed: SpecErrorCode | None = None
        try:
            _ = verify_spec_bundle(mutate_bundle(bundle, mutation))
        except SpecDocumentError as error:
            observed = error.code
        expected = _EXPECTED[mutation]
        accepted = observed == expected
        accepted_results.append(accepted)
        results[mutation] = {
            "state": "pass" if accepted else "fail",
            "expected_error_code": expected,
            "observed_error_code": observed,
        }
    state = "pass" if all(accepted_results) else "fail"
    checks_json: dict[str, JsonValue] = {
        name: accepted for name, accepted in checks.items()
    }
    report: dict[str, JsonValue] = {
        "state": state,
        "schema_version": "v8.spec.document-acceptance.1",
        "check_count": len(checks),
        "checks": checks_json,
        "json_block_count": json_count,
        "linked_prd_count": len(bundle.prds),
        "mutation_count": len(MUTATIONS),
        "mutations": results,
    }
    return report
