from dataclasses import dataclass

from src.causal.canonical_rules import canonical_node_id_value

from .statistical_models import CanonicalNode, VerificationInput


@dataclass(frozen=True, slots=True)
class NodeResolution:
    node: CanonicalNode | None
    reason: str | None


def resolve_node(build: VerificationInput, node_id: str) -> NodeResolution:
    candidates = tuple(
        node
        for node in build.source_node_artifact.nodes
        if node.canonical_node_id == node_id
    )
    if not candidates:
        return NodeResolution(None, "canonical_node_missing")
    if len(candidates) != 1:
        return NodeResolution(None, "duplicate_canonical_nodes")
    node = candidates[0]
    expected = canonical_node_id_value(
        node.canonical_label,
        node.normalized_label,
        (node.direction.kind, node.direction.polarity),
    )
    if node.canonical_node_id != expected:
        return NodeResolution(None, "canonical_node_identity_mismatch")
    return NodeResolution(node, None)
