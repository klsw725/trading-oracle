from dataclasses import dataclass
from pathlib import Path
from typing import Final, override

from pydantic import TypeAdapter, ValidationError

from src.causal.canonical_models import (
    LegacyGraphParseError,
    NodeDirection,
    Polarity,
    parse_legacy_graph,
)
from src.causal.canonical_rules import infer_direction
from src.causal.canonicalizer import canonicalize
from src.v4.models import JsonValue


_JSON: Final[TypeAdapter[JsonValue]] = TypeAdapter[JsonValue](JsonValue)


@dataclass(frozen=True, slots=True)
class CanonicalFixtureError(Exception):
    field: str
    reason: str

    @override
    def __str__(self) -> str:
        return f"canonical fixture {self.field}: {self.reason}"


def _record(value: JsonValue | None, field: str) -> dict[str, JsonValue]:
    match value:  # noqa: MATCH_OK - boundary rejects non-object JSON variants
        case dict() as record:
            return record
        case _:
            raise CanonicalFixtureError(field, "expected object")


def _records(value: JsonValue | None, field: str) -> list[dict[str, JsonValue]]:
    match value:  # noqa: MATCH_OK - boundary rejects non-array JSON variants
        case list() as records if all(isinstance(item, dict) for item in records):
            return [item for item in records if isinstance(item, dict)]
        case _:
            raise CanonicalFixtureError(field, "expected object array")


def _text(record: dict[str, JsonValue], field: str) -> str:
    match record.get(field):  # noqa: MATCH_OK - boundary rejects non-string JSON variants
        case str() as value:
            return value
        case _:
            raise CanonicalFixtureError(field, "expected string")


def _integer(record: dict[str, JsonValue], field: str) -> int:
    match record.get(field):  # noqa: MATCH_OK - boundary rejects non-integer JSON variants
        case bool():
            raise CanonicalFixtureError(field, "expected integer")
        case int() as value:
            return value
        case _:
            raise CanonicalFixtureError(field, "expected integer")


def _node_by_id(nodes: list[dict[str, JsonValue]], node_id: str) -> dict[str, JsonValue]:
    for node in nodes:
        if node.get("canonical_node_id") == node_id:
            return node
    raise CanonicalFixtureError("nodes", f"missing {node_id}")


def _node_by_label(nodes: list[dict[str, JsonValue]], label: str) -> dict[str, JsonValue]:
    for node in nodes:
        if node.get("canonical_label") == label:
            return node
    raise CanonicalFixtureError("nodes", f"missing label {label}")


def load_fixture(path: Path) -> JsonValue:
    try:
        return _JSON.validate_json(path.read_bytes())
    except ValidationError as error:
        raise CanonicalFixtureError("root", str(error)) from error


def _misleading_resolver(text: str) -> NodeDirection:
    inferred = infer_direction(text)
    if "상승" in text:
        return NodeDirection(inferred.kind, Polarity.DOWN)
    return inferred


def _strict_metadata_rejected(value: JsonValue | None) -> bool:
    try:
        _ = parse_legacy_graph(value)
    except LegacyGraphParseError:
        return True
    return False


def verify_fixture(value: JsonValue) -> JsonValue:
    root = _record(value, "root")
    expected = _record(root.get("expected"), "expected")
    legacy_graph = _record(root.get("legacy_graph"), "legacy_graph")
    main = canonicalize(parse_legacy_graph(legacy_graph)).artifact
    match legacy_graph.get("triples"):  # noqa: MATCH_OK - boundary rejects non-array triples
        case list() as triples:
            reordered_graph: JsonValue = {**legacy_graph, "triples": list(reversed(triples))}
        case _:
            raise CanonicalFixtureError("legacy_graph.triples", "expected array")
    reordered = canonicalize(parse_legacy_graph(reordered_graph)).artifact
    duplicate = canonicalize(parse_legacy_graph(root.get("dirty_duplicate_graph"))).artifact
    malformed = canonicalize(parse_legacy_graph(root.get("malformed_graph"))).artifact
    formatting = canonicalize(parse_legacy_graph(root.get("formatting_graph"))).artifact
    collision = canonicalize(parse_legacy_graph(root.get("domain_collision_graph"))).artifact
    misleading = canonicalize(
        parse_legacy_graph(root.get("misleading_graph")),
        direction_resolver=_misleading_resolver,
    ).artifact
    ownership = canonicalize(
        parse_legacy_graph(root.get("ownership_transaction_graph"))
    ).artifact
    empty_owner = canonicalize(parse_legacy_graph(root.get("empty_owner_graph"))).artifact
    exchange_direction = canonicalize(
        parse_legacy_graph(root.get("exchange_direction_graph"))
    ).artifact

    main_record = _record(main, "main")
    nodes = _records(main_record.get("nodes"), "main.nodes")
    report = _record(main_record.get("canonicalization_report"), "main.report")
    merged = _node_by_id(nodes, _text(expected, "merged_node_id"))
    opposite = _node_by_id(nodes, _text(expected, "opposite_node_id"))
    aliases = _records(merged.get("aliases"), "merged.aliases")
    sources = _records(merged.get("created_from"), "merged.created_from")
    secondary = merged.get("secondary_domains")
    mutations = _records(report.get("rejected_mutations"), "report.rejected_mutations")
    reordered_nodes = _records(_record(reordered, "reordered").get("nodes"), "reordered.nodes")
    node_ids = sorted(
        node_id for node in nodes if isinstance(node_id := node.get("canonical_node_id"), str)
    )
    reordered_node_ids = sorted(
        node_id
        for node in reordered_nodes
        if isinstance(node_id := node.get("canonical_node_id"), str)
    )

    duplicate_nodes = _records(
        _record(duplicate, "duplicate").get("nodes"), "duplicate.nodes"
    )
    duplicate_merged = _node_by_id(duplicate_nodes, _text(expected, "merged_node_id"))
    duplicate_aliases = _records(duplicate_merged.get("aliases"), "duplicate.aliases")
    duplicate_sources = _records(duplicate_merged.get("created_from"), "duplicate.created_from")
    malformed_report = _record(
        _record(malformed, "malformed").get("canonicalization_report"), "malformed.report"
    )
    formatting_triples = _records(
        _record(formatting, "formatting").get("triples"), "formatting.triples"
    )
    formatting_subject_ids = {
        node_id
        for triple in formatting_triples
        if isinstance(node_id := triple.get("subject_node_id"), str)
    }
    collision_record = _record(collision, "collision")
    collision_report = _record(
        collision_record.get("canonicalization_report"), "collision.report"
    )
    collision_mutations = _records(
        collision_report.get("rejected_mutations"), "collision.rejected_mutations"
    )
    collision_triples = _records(collision_record.get("triples"), "collision.triples")
    misleading_record = _record(misleading, "misleading")
    misleading_report = _record(
        misleading_record.get("canonicalization_report"), "misleading.report"
    )
    misleading_mutations = _records(
        misleading_report.get("rejected_mutations"), "misleading.rejected_mutations"
    )
    misleading_triples = _records(misleading_record.get("triples"), "misleading.triples")
    ownership_record = _record(ownership, "ownership")
    ownership_nodes = _records(ownership_record.get("nodes"), "ownership.nodes")
    ownership_triples = _records(ownership_record.get("triples"), "ownership.triples")
    demand_node = _node_by_label(ownership_nodes, "수요 증가")
    empty_owner_nodes = _records(
        _record(empty_owner, "empty_owner").get("nodes"), "empty_owner.nodes"
    )
    margin_node = _node_by_label(empty_owner_nodes, "마진 개선")
    exchange_nodes = _records(
        _record(exchange_direction, "exchange_direction").get("nodes"),
        "exchange_direction.nodes",
    )
    exchange_polarities = sorted(
        polarity
        for node in exchange_nodes
        if isinstance(label := node.get("canonical_label"), str)
        and label.startswith("원달러 환율")
        and isinstance(direction := node.get("direction"), dict)
        and isinstance(polarity := direction.get("polarity"), str)
    )

    checks: dict[str, JsonValue] = {
        "legacy_schema_detected": main_record.get("schema_version")
        == _text(expected, "schema_version"),
        "deterministic_ids_input_order": node_ids == reordered_node_ids,
        "happy_alias_merge": len(aliases) == _integer(expected, "merged_alias_count"),
        "provenance_preserved": len(sources)
        >= _integer(expected, "merged_created_from_minimum"),
        "owner_domain_preserved": merged.get("owner_domain")
        == _text(expected, "owner_domain"),
        "secondary_domain_preserved": isinstance(secondary, list)
        and _text(expected, "secondary_domain") in secondary,
        "opposite_node_preserved": opposite.get("canonical_node_id")
        == _text(expected, "opposite_node_id"),
        "opposite_merge_rejected": any(
            mutation.get("reason") == _text(expected, "opposite_rejection_reason")
            for mutation in mutations
        ),
        "duplicate_alias_deduplicated": len(duplicate_aliases)
        == _integer(expected, "duplicate_alias_count"),
        "duplicate_provenance_preserved": len(duplicate_sources)
        == _integer(expected, "duplicate_created_from_count"),
        "malformed_triples_rejected": malformed_report.get("malformed_triples_rejected")
        == _integer(expected, "malformed_triples_rejected"),
        "formatting_alias_direction_stable": len(formatting_subject_ids) == 1,
        "domain_collision_rejected": any(
            mutation.get("reason") == _text(expected, "domain_collision_reason")
            for mutation in collision_mutations
        )
        and len(collision_triples) == _integer(expected, "domain_collision_triples"),
        "misleading_direction_rejected": any(
            mutation.get("reason") == _text(expected, "misleading_rejection_reason")
            for mutation in misleading_mutations
        )
        and len(misleading_triples) == _integer(expected, "misleading_triples"),
        "metadata_types_strict": _strict_metadata_rejected(root.get("strict_metadata_graph")),
        "rejected_triple_has_no_ownership_effect": len(ownership_triples)
        == _integer(expected, "ownership_transaction_triples")
        and demand_node.get("owner_domain") == _text(expected, "transaction_owner_domain"),
        "empty_domain_not_owner": margin_node.get("owner_domain")
        == _text(expected, "empty_owner_domain"),
        "exchange_direction_words_preserved": exchange_polarities
        == expected.get("exchange_polarities"),
    }
    return {
        "state": "pass" if all(check is True for check in checks.values()) else "fail",
        "schema_version": root.get("schema_version"),
        "checks": checks,
    }
