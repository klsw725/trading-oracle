from dataclasses import dataclass
from typing import Final

from src.causal.canonical_models import (
    AliasRecord,
    CanonicalNode,
    CanonicalNodeId,
    DirectionKind,
    LegacyField,
    NodeCandidate,
    ParsedLegacyGraph,
    Polarity,
    SourceRecord,
)
from .canonical_rules import (
    DirectionResolver,
    canonical_node_id_value,
    concept_key,
    direction_conflict_reason,
    infer_direction,
    normalize_text,
    requires_owner_review,
)
from src.v4.models import JsonValue


SCHEMA_VERSION: Final = "causal-node-canonicalization.1"
CANONICALIZER_VERSION: Final = "node-canonicalizer.1"


@dataclass(frozen=True, slots=True)
class CanonicalizationResult:
    artifact: JsonValue


def canonical_node_id(candidate: NodeCandidate) -> CanonicalNodeId:
    return CanonicalNodeId(
        canonical_node_id_value(
            candidate.canonical_label,
            candidate.normalized_label,
            (candidate.direction.kind.value, candidate.direction.polarity.value),
        )
    )


def _candidate(
    source: SourceRecord, domain: str, resolver: DirectionResolver
) -> NodeCandidate:
    canonical_label = normalize_text(source.legacy_text)
    return NodeCandidate(
        canonical_label=canonical_label,
        normalized_label=canonical_label,
        concept_key=concept_key(canonical_label),
        direction=resolver(canonical_label),
        domain=domain,
        alias=AliasRecord(source.legacy_text, canonical_label),
        source=source,
    )


def _merge_candidates(candidates: list[NodeCandidate]) -> tuple[CanonicalNode, ...]:
    grouped: dict[tuple[str, DirectionKind, Polarity], list[NodeCandidate]] = {}
    for candidate in candidates:
        key = (candidate.normalized_label, candidate.direction.kind, candidate.direction.polarity)
        grouped.setdefault(key, []).append(candidate)

    nodes: list[CanonicalNode] = []
    for key in sorted(grouped, key=lambda item: (item[0], item[1].value, item[2].value)):
        group = grouped[key]
        owner = next((item.domain for item in group if item.domain), "")
        aliases = {
            (item.alias.normalized_alias, item.alias.alias): item.alias for item in group
        }
        sources = {
            (item.source.legacy_triple_index, item.source.legacy_field.value): item.source
            for item in group
        }
        node_id = canonical_node_id(group[0])
        nodes.append(
            CanonicalNode(
                node_id,
                group[0].canonical_label,
                group[0].normalized_label,
                group[0].direction,
                owner,
                tuple(sorted({item.domain for item in group if item.domain and item.domain != owner})),
                tuple(aliases[key] for key in sorted(aliases)),
                tuple(sources[key] for key in sorted(sources)),
            )
        )
    return tuple(sorted(nodes, key=lambda node: node.canonical_node_id))


def canonicalize(
    graph: ParsedLegacyGraph,
    canonicalized_at: str | None = None,
    direction_resolver: DirectionResolver = infer_direction,
) -> CanonicalizationResult:
    rejected: list[JsonValue] = []
    triple_candidates: list[tuple[int, NodeCandidate, str, NodeCandidate, str]] = []
    for index, triple in graph.triples:
        subject = _candidate(
            SourceRecord(LegacyField.SUBJECT, triple.subject, index),
            triple.domain,
            direction_resolver,
        )
        object_ = _candidate(
            SourceRecord(LegacyField.OBJECT, triple.object, index),
            triple.domain,
            direction_resolver,
        )
        misleading = tuple(
            candidate
            for candidate in (subject, object_)
            if direction_conflict_reason(candidate.canonical_label, candidate.direction)
        )
        if misleading:
            rejected.extend(
                {
                    "mutation": "reject_candidate",
                    "reason": "misleading_direction",
                    "legacy_text": candidate.source.legacy_text,
                    "direction": candidate.direction.to_json(),
                    "legacy_triple_index": candidate.source.legacy_triple_index,
                }
                for candidate in misleading
            )
            continue
        triple_candidates.append((index, subject, triple.relation.value, object_, triple.domain))

    accepted_candidates: list[NodeCandidate] = []
    accepted_triples: list[tuple[int, NodeCandidate, str, NodeCandidate, str]] = []
    owner_by_key: dict[tuple[str, DirectionKind, Polarity], NodeCandidate] = {}
    for triple_candidate in triple_candidates:
        _, subject, _, object_, _ = triple_candidate
        collisions: list[tuple[NodeCandidate, NodeCandidate]] = []
        for candidate in (subject, object_):
            key = (candidate.normalized_label, candidate.direction.kind, candidate.direction.polarity)
            owner = owner_by_key.get(key)
            if (
                owner is not None
                and bool(candidate.domain)
                and owner.domain != candidate.domain
                and requires_owner_review(candidate.normalized_label)
            ):
                collisions.append((owner, candidate))
        if collisions:
            rejected.extend(
                {
                    "mutation": "reject_merge",
                    "reason": "domain_collision",
                    "left": {"legacy_text": owner.source.legacy_text, "domain": owner.domain},
                    "right": {"legacy_text": candidate.source.legacy_text, "domain": candidate.domain},
                }
                for owner, candidate in collisions
            )
            continue
        accepted_triples.append(triple_candidate)
        accepted_candidates.extend((subject, object_))
        for candidate in (subject, object_):
            if candidate.domain:
                key = (
                    candidate.normalized_label,
                    candidate.direction.kind,
                    candidate.direction.polarity,
                )
                _ = owner_by_key.setdefault(key, candidate)

    nodes = _merge_candidates(accepted_candidates)
    node_by_key = {
        (node.normalized_label, node.direction.kind, node.direction.polarity): node for node in nodes
    }
    by_concept: dict[str, list[NodeCandidate]] = {}
    for candidate in accepted_candidates:
        peers = by_concept.setdefault(candidate.concept_key, [])
        for peer in peers:
            if peer.direction.kind is not candidate.direction.kind:
                reason = "direction_kind_conflict"
            elif {peer.direction.polarity, candidate.direction.polarity} == {
                Polarity.UP,
                Polarity.DOWN,
            }:
                reason = "opposite_direction"
            else:
                continue
            rejected.append(
                {
                    "mutation": "reject_merge",
                    "reason": reason,
                    "left": {"legacy_text": peer.source.legacy_text, "direction": peer.direction.to_json()},
                    "right": {"legacy_text": candidate.source.legacy_text, "direction": candidate.direction.to_json()},
                }
            )
            break
        peers.append(candidate)

    triples: list[JsonValue] = []
    for _, subject, relation, object_, domain in accepted_triples:
        subject_node = node_by_key[(subject.normalized_label, subject.direction.kind, subject.direction.polarity)]
        object_node = node_by_key[(object_.normalized_label, object_.direction.kind, object_.direction.polarity)]
        triples.append(
            {
                "subject_node_id": subject_node.canonical_node_id,
                "relation": relation,
                "object_node_id": object_node.canonical_node_id,
                "domain": domain,
                "legacy_subject": subject.source.legacy_text,
                "legacy_object": object_.source.legacy_text,
            }
        )

    aliases_merged = sum(max(len(node.aliases) - 1, 0) for node in nodes)
    artifact: JsonValue = {
        "schema_version": SCHEMA_VERSION,
        "metadata": {
            "created_at": graph.metadata.created_at,
            "updated_at": graph.metadata.updated_at,
            "num_topics": graph.metadata.num_topics,
            "num_triples": graph.metadata.num_triples,
            "llm_model": graph.metadata.llm_model,
            "canonicalized_at": canonicalized_at or graph.metadata.updated_at,
            "canonicalizer_version": CANONICALIZER_VERSION,
        },
        "nodes": [node.to_json() for node in nodes],
        "triples": triples,
        "canonicalization_report": {
            "legacy_nodes_seen": len(graph.triples) * 2,
            "canonical_nodes_created": len(nodes),
            "aliases_merged": aliases_merged,
            "conflicts_rejected": len(rejected),
            "malformed_triples_rejected": len(graph.malformed_triples),
            "rejected_mutations": rejected,
            "malformed_triples": [item.to_json() for item in graph.malformed_triples],
        },
    }
    return CanonicalizationResult(artifact)
