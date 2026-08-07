from collections import Counter
from dataclasses import dataclass

from pydantic import ValidationError

from .series_mapping_models import (
    PROPOSAL_NODE_ADAPTER,
    CanonicalNode,
    CatalogEntry,
    MappingBuildInput,
)
from src.v4.models import JsonValue


@dataclass(frozen=True, slots=True)
class ConflictIndex:
    nodes: dict[str, CanonicalNode]
    catalogs: dict[str, CatalogEntry]
    duplicate_nodes: dict[str, tuple[JsonValue, ...]]
    duplicate_catalogs: dict[str, tuple[JsonValue, ...]]
    duplicate_proposals: dict[str, tuple[JsonValue, ...]]


def _node_json(node: CanonicalNode) -> JsonValue:
    return {
        "canonical_node_id": node.canonical_node_id,
        "canonical_label": node.canonical_label,
        "direction": {
            "kind": node.direction.kind,
            "polarity": node.direction.polarity,
        },
    }


def _catalog_json(entry: CatalogEntry) -> JsonValue:
    return {
        "series_id": entry.series_id,
        "raw_symbol": entry.raw_symbol,
        "source_id": entry.source_id,
        "adapter_version": entry.adapter_version,
        "native_unit": entry.native_unit,
        "native_frequency": entry.native_frequency,
        "as_of": entry.as_of.isoformat(),
        "expires_at": entry.expires_at.isoformat(),
        "provenance_hash": entry.provenance_hash,
    }


def detect_conflicts(build_input: MappingBuildInput) -> ConflictIndex:
    node_counts = Counter(
        node.canonical_node_id for node in build_input.source_node_artifact.nodes
    )
    catalog_counts = Counter(entry.series_id for entry in build_input.series_catalog)
    proposal_ids: list[str] = []
    for raw in build_input.proposals:
        try:
            proposal_ids.append(PROPOSAL_NODE_ADAPTER.validate_python(raw).canonical_node_id)
        except ValidationError:
            continue
    proposal_counts = Counter(proposal_ids)
    duplicate_node_ids = {key for key, count in node_counts.items() if count > 1}
    duplicate_catalog_ids = {key for key, count in catalog_counts.items() if count > 1}
    duplicate_proposal_ids = {key for key, count in proposal_counts.items() if count > 1}
    return ConflictIndex(
        nodes={
            node.canonical_node_id: node
            for node in build_input.source_node_artifact.nodes
            if node.canonical_node_id not in duplicate_node_ids
        },
        catalogs={
            entry.series_id: entry
            for entry in build_input.series_catalog
            if entry.series_id not in duplicate_catalog_ids
        },
        duplicate_nodes={
            node_id: tuple(
                _node_json(node)
                for node in build_input.source_node_artifact.nodes
                if node.canonical_node_id == node_id
            )
            for node_id in duplicate_node_ids
        },
        duplicate_catalogs={
            series_id: tuple(
                _catalog_json(entry)
                for entry in build_input.series_catalog
                if entry.series_id == series_id
            )
            for series_id in duplicate_catalog_ids
        },
        duplicate_proposals={
            node_id: tuple(
                raw
                for raw in build_input.proposals
                if _proposal_node_id(raw) == node_id
            )
            for node_id in duplicate_proposal_ids
        },
    )


def _proposal_node_id(raw: JsonValue) -> str | None:
    try:
        return PROPOSAL_NODE_ADAPTER.validate_python(raw).canonical_node_id
    except ValidationError:
        return None
