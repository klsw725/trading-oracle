from dataclasses import dataclass
from pathlib import Path
import re
from typing import Final, override

from pydantic import ConfigDict, TypeAdapter, ValidationError

from .series_mapping import build_mapping_artifact, parse_mapping_input
from src.v4.models import JsonValue


_JSON: Final[TypeAdapter[JsonValue]] = TypeAdapter[JsonValue](JsonValue)
_RECORD: Final = TypeAdapter(dict[str, JsonValue])
_RECORDS: Final = TypeAdapter(list[dict[str, JsonValue]])
_STRINGS: Final = TypeAdapter(list[str])
_INTEGER: Final[TypeAdapter[int]] = TypeAdapter(int, config=ConfigDict(strict=True))
_HASH: Final = re.compile(r"^sha256:[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class MappingFixtureError(Exception):
    field: str
    reason: str

    @override
    def __str__(self) -> str:
        return f"series mapping fixture {self.field}: {self.reason}"


def load_json(path: Path) -> JsonValue:
    try:
        return _JSON.validate_json(path.read_bytes())
    except ValidationError as error:
        raise MappingFixtureError("root", str(error)) from error


def _record(value: JsonValue | None, field: str) -> dict[str, JsonValue]:
    try:
        return _RECORD.validate_python(value)
    except ValidationError as error:
        raise MappingFixtureError(field, "expected object") from error


def _records(value: JsonValue | None, field: str) -> list[dict[str, JsonValue]]:
    try:
        return _RECORDS.validate_python(value)
    except ValidationError as error:
        raise MappingFixtureError(field, "expected object array") from error


def _strings(value: JsonValue | None, field: str) -> list[str]:
    try:
        return _STRINGS.validate_python(value)
    except ValidationError as error:
        raise MappingFixtureError(field, "expected string array") from error


def _integer(record: dict[str, JsonValue], field: str) -> int:
    try:
        return _INTEGER.validate_python(record.get(field))
    except ValidationError as error:
        raise MappingFixtureError(field, "expected integer") from error


def _mapping_by_result(
    mappings: list[dict[str, JsonValue]], result: str
) -> dict[str, JsonValue]:
    for mapping in mappings:
        if mapping.get("mapping_result") == result:
            return mapping
    raise MappingFixtureError("mappings", f"missing result {result}")


def _replace_proposal(
    proposals: list[dict[str, JsonValue]], node_id: str, replacement: dict[str, JsonValue]
) -> list[JsonValue]:
    return [
        replacement if item.get("canonical_node_id") == node_id else item
        for item in proposals
    ]


def _built(value: JsonValue) -> dict[str, JsonValue]:
    return _record(build_mapping_artifact(parse_mapping_input(value)).artifact, "artifact")


def _result_for(artifact: dict[str, JsonValue], node_id: str) -> dict[str, JsonValue]:
    for mapping in _records(artifact.get("mappings"), "mappings"):
        if mapping.get("canonical_node_id") == node_id:
            return mapping
    raise MappingFixtureError("mappings", f"missing node {node_id}")


def _evidence(mapping: dict[str, JsonValue]) -> dict[str, JsonValue]:
    return _record(mapping.get("rejection_evidence"), "rejection_evidence")


def verify_fixture(value: JsonValue) -> JsonValue:
    root = _record(value, "root")
    expected = _record(root.get("expected"), "expected")
    raw_input = _record(root.get("build_input"), "build_input")
    adversarial = _record(root.get("adversarial"), "adversarial")
    build_input = parse_mapping_input(raw_input)
    first = _record(build_mapping_artifact(build_input).artifact, "artifact")
    second = build_mapping_artifact(build_input).artifact
    mappings = _records(first.get("mappings"), "mappings")
    mutations = _records(first.get("mapping_mutations"), "mapping_mutations")
    approved = [item for item in mappings if item.get("mapping_result") == "approved_manual"]
    rejected = [
        result
        for item in mappings
        if isinstance(result := item.get("mapping_result"), str)
        and result.startswith("rejected_")
    ]
    composite = next(
        item for item in approved if item.get("mapping_kind") == "composite_series"
    )
    candidate = _mapping_by_result(mappings, "needs_manual_review")
    unmappable = _mapping_by_result(mappings, "unmappable")
    stale = _mapping_by_result(mappings, "rejected_stale")
    malformed = _mapping_by_result(mappings, "rejected_malformed")
    approved_links = [
        link
        for mapping in approved
        for link in _records(mapping.get("series_links"), "approved.series_links")
    ]
    mutation_names = {
        name
        for mutation in mutations
        if isinstance(name := mutation.get("mutation"), str)
    }
    source = _record(raw_input.get("source_node_artifact"), "source")
    nodes = _records(source.get("nodes"), "source.nodes")
    catalogs = _records(raw_input.get("series_catalog"), "series_catalog")
    proposals = _records(raw_input.get("proposals"), "proposals")
    node_ids = {
        label: node_id
        for item in nodes
        if isinstance(label := item.get("canonical_label"), str)
        and isinstance(node_id := item.get("canonical_node_id"), str)
    }
    usd_node = node_ids["원달러 환율 상승"]
    term_node = node_ids["미국 장단기 금리차 확대"]
    proxy_node = node_ids["미국 기준금리 인상"]
    dirty_node = node_ids["중복 환율 후보"]
    duplicate_node = _built({**raw_input, "source_node_artifact": {**source, "nodes": [*nodes, _record(adversarial.get("duplicate_node"), "duplicate_node")]}})
    duplicate_catalog = _built({**raw_input, "series_catalog": [*catalogs, _record(adversarial.get("duplicate_catalog"), "duplicate_catalog")]})
    duplicate_proposal = _built({**raw_input, "proposals": [*proposals, _record(adversarial.get("duplicate_terminal_proposal"), "duplicate_terminal_proposal")]})
    composite_proposal = next(item for item in proposals if item.get("canonical_node_id") == term_node)
    unknown_formula_proposal = {**composite_proposal, "formula": adversarial.get("formula_unknown_variable")}
    unknown_formula = _built({**raw_input, "proposals": _replace_proposal(proposals, term_node, unknown_formula_proposal)})
    forbidden_formula_proposal = {**composite_proposal, "formula": adversarial.get("formula_forbidden_syntax")}
    forbidden_formula = _built({**raw_input, "proposals": _replace_proposal(proposals, term_node, forbidden_formula_proposal)})
    composite_links = _records(composite_proposal.get("series_links"), "composite.links")
    duplicate_link_proposal: dict[str, JsonValue] = {
        **composite_proposal,
        "series_links": [*composite_links, composite_links[0]],
    }
    duplicate_link = _built({**raw_input, "proposals": _replace_proposal(proposals, term_node, duplicate_link_proposal)})
    single_proposal = next(item for item in proposals if item.get("canonical_node_id") == usd_node)
    single_links = _records(single_proposal.get("series_links"), "single.links")
    approval = _record(single_links[0].get("manual_approval"), "single.approval")
    future_link: dict[str, JsonValue] = {
        **single_links[0],
        "manual_approval": {
            **approval,
            "approved_at": adversarial.get("future_approved_at"),
        },
    }
    future_proposal: dict[str, JsonValue] = {
        **single_proposal,
        "series_links": [future_link],
    }
    future_approval = _built({**raw_input, "proposals": _replace_proposal(proposals, usd_node, future_proposal)})
    overlong_proposal = {**single_proposal, "mapping_expires_at": adversarial.get("overlong_mapping_expires_at")}
    overlong_expiry = _built({**raw_input, "proposals": _replace_proposal(proposals, usd_node, overlong_proposal)})
    proxy_proposal = next(item for item in proposals if item.get("canonical_node_id") == proxy_node)
    proxy_evidence = _record(proxy_proposal.get("evidence"), "proxy.evidence")
    mismatched_proxy_evidence: JsonValue = {**proxy_evidence, "candidate_series_id": adversarial.get("mismatched_evidence_series_id")}
    mismatched_proxy: dict[str, JsonValue] = {**proxy_proposal, "evidence": mismatched_proxy_evidence}
    mismatched_id = _built({**raw_input, "proposals": _replace_proposal(proposals, proxy_node, mismatched_proxy)})
    dirty_proposal = next(item for item in proposals if item.get("canonical_node_id") == dirty_node)
    dirty_evidence = _record(dirty_proposal.get("evidence"), "dirty.evidence")
    empty_dirty_evidence: JsonValue = {**dirty_evidence, "original_records": []}
    empty_dirty: dict[str, JsonValue] = {**dirty_proposal, "evidence": empty_dirty_evidence}
    empty_dirty_records = _built({**raw_input, "proposals": _replace_proposal(proposals, dirty_node, empty_dirty)})
    future_catalogs: list[JsonValue] = [{**item, "as_of": adversarial.get("future_as_of")} if item.get("series_id") == "USD_KRW" else item for item in catalogs]
    future_as_of_link: dict[str, JsonValue] = {**single_links[0], "as_of": adversarial.get("future_as_of")}
    future_as_of_proposal: dict[str, JsonValue] = {**single_proposal, "series_links": [future_as_of_link]}
    future_as_of_input: JsonValue = {**raw_input, "series_catalog": future_catalogs, "proposals": _replace_proposal(proposals, usd_node, future_as_of_proposal)}
    future_as_of = _built(future_as_of_input)
    checks: dict[str, JsonValue] = {
        "schema_version": first.get("schema_version") == "causal-series-mapping.1",
        "canonical_node_primary_key": all(
            isinstance(item.get("canonical_node_id"), str) for item in mappings
        ),
        "approved_contract_complete": len(approved)
        == _integer(expected, "approved_count")
        and all(
            all(
                field in link
                for field in (
                    "transform",
                    "unit",
                    "direction",
                    "source_id",
                    "as_of",
                    "source_expires_at",
                    "provenance_hash",
                    "suitability",
                    "manual_approval",
                )
            )
            for link in approved_links
        ),
        "mapping_hash_deterministic": first == second
        and all(
            isinstance(value := item.get("mapping_hash"), str)
            and _HASH.fullmatch(value) is not None
            for item in approved
        ),
        "composite_formula_and_provenance": composite.get("formula")
        == expected.get("composite_formula")
        and len(_records(composite.get("series_links"), "composite.links")) == 2,
        "unmappable_preserves_evidence": bool(
            _records(unmappable.get("proxy_candidates_rejected"), "unmappable.proxies")
        ),
        "required_rejections": sorted(set(rejected))
        == sorted(_strings(expected.get("rejection_results"), "rejection_results"))
        and rejected.count("rejected_malformed")
        == _integer(expected, "malformed_count")
        and isinstance(stale.get("rejection_evidence"), dict)
        and isinstance(malformed.get("rejection_evidence"), dict),
        "legacy_import_candidate_only": candidate.get("canonical_node_id")
        == expected.get("legacy_candidate_node_id")
        and sum(item.get("mapping_result") == "needs_manual_review" for item in mappings)
        == _integer(expected, "candidate_count"),
        "read_json_mutation_qa": mutation_names
        == {"add_candidate", "approve_mapping", "reject_mapping", "expire_mapping", "mark_unmappable"}
        and isinstance(first.get("qa"), dict),
        "duplicate_node_rejected_dirty": _result_for(duplicate_node, usd_node).get("mapping_result") == "rejected_dirty"
        and len([item for item in _records(duplicate_node.get("mappings"), "duplicate_node.mappings") if item.get("canonical_node_id") == usd_node]) == 1,
        "duplicate_catalog_rejected_dirty": _result_for(duplicate_catalog, usd_node).get("mapping_result") == "rejected_dirty"
        and all(item.get("series_id") != "USD_KRW" for item in _records(duplicate_catalog.get("series_catalog"), "duplicate_catalog.catalog")),
        "duplicate_proposal_rejected_dirty": _result_for(duplicate_proposal, usd_node).get("mapping_result") == "rejected_dirty"
        and sum(item.get("canonical_node_id") == usd_node for item in _records(duplicate_proposal.get("mappings"), "duplicate_proposal.mappings")) == 1,
        "formula_variables_exact": _result_for(unknown_formula, term_node).get("mapping_result") == "rejected_malformed"
        and _result_for(duplicate_link, term_node).get("mapping_result") == "rejected_malformed"
        and _result_for(forbidden_formula, term_node).get("mapping_result") == "rejected_malformed",
        "approval_time_bounded": _result_for(future_approval, usd_node).get("mapping_result") == "rejected_malformed"
        and _result_for(overlong_expiry, usd_node).get("mapping_result") == "rejected_malformed",
        "rejection_evidence_typed": set(_evidence(_mapping_by_result(mappings, "rejected_dirty"))) >= {"conflict_kind", "original_records", "conflict_reason"}
        and set(_evidence(_mapping_by_result(mappings, "rejected_proxy"))) >= {"candidate_series_id", "proxy_reason", "missing_direct_source_explanation"}
        and set(_evidence(_mapping_by_result(mappings, "rejected_misleading"))) >= {"candidate_series_id", "expected_direction", "observed_conflict"}
        and set(_evidence(stale)) >= {"expired_field", "run_cutoff", "affected_series_id"}
        and set(_evidence(malformed)) >= {"json_pointer", "parse_error"},
        "candidate_evidence_id_consistent": _result_for(mismatched_id, proxy_node).get("mapping_result") == "rejected_malformed"
        and str(_evidence(_result_for(mismatched_id, proxy_node)).get("json_pointer", "")).endswith("/candidate_series_id"),
        "dirty_evidence_nonempty": _result_for(empty_dirty_records, dirty_node).get("mapping_result") == "rejected_malformed",
        "as_of_not_future": _result_for(future_as_of, usd_node).get("mapping_result") == "rejected_malformed"
        and str(_evidence(_result_for(future_as_of, usd_node)).get("json_pointer", "")).endswith("/as_of"),
    }
    return {
        "state": "pass" if all(check is True for check in checks.values()) else "fail",
        "schema_version": root.get("schema_version"),
        "checks": checks,
    }
