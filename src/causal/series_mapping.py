from dataclasses import dataclass
from typing import override

from pydantic import ValidationError

from .series_mapping_models import (
    APPROVAL_ADAPTER,
    BUILD_INPUT_ADAPTER,
    ENVELOPE_ADAPTER,
    MAPPING_POLICY_VERSION,
    MAPPING_SCHEMA_VERSION,
    REJECTION_ADAPTER,
    SOURCE_NODE_SCHEMA_VERSION,
    UNMAPPABLE_ADAPTER,
    CatalogEntry,
    DirtyConflictKind,
    DirtyEvidence,
    MalformedEvidence,
    MappingBuildInput,
    ProposalKind,
    RejectionProposal,
    UnmappableProposal,
)
from .series_mapping_approval import approved_record, approval_problem
from .series_mapping_conflicts import detect_conflicts
from .series_mapping_rejections import (
    rejection_candidate_id,
    rejection_json,
    rejection_result,
)
from src.v4.models import JsonValue, canonical_hash, canonical_json


@dataclass(frozen=True, slots=True)
class MappingInputError(Exception):
    detail: str

    @override
    def __str__(self) -> str:
        return f"series mapping input: {self.detail}"


@dataclass(frozen=True, slots=True)
class MappingBuildResult:
    artifact: JsonValue


@dataclass(frozen=True, slots=True)
class MappingIdentity:
    canonical_node_id: str
    canonical_label: str


def parse_mapping_input(value: JsonValue) -> MappingBuildInput:
    try:
        return BUILD_INPUT_ADAPTER.validate_python(value)
    except ValidationError as error:
        raise MappingInputError(str(error)) from error


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


def _rejected(identity: MappingIdentity, evidence: DirtyEvidence | MalformedEvidence) -> JsonValue:
    result = rejection_result(evidence)
    evidence_json = rejection_json(evidence)
    return {
        "canonical_node_id": identity.canonical_node_id,
        "canonical_label": identity.canonical_label,
        "mapping_result": result,
        "mapping_kind": "rejected",
        "series_links": [],
        "proxy_candidates_rejected": [],
        "unmappable_reason": result,
        "rejection_evidence": evidence_json,
    }


def _unmappable_record(proposal: UnmappableProposal, label: str) -> JsonValue:
    return {
        "canonical_node_id": proposal.canonical_node_id,
        "canonical_label": label,
        "mapping_result": "unmappable",
        "mapping_kind": "unmappable",
        "series_links": [],
        "proxy_candidates_rejected": [
            {"series_id": item.series_id, "reason": item.reason}
            for item in proposal.proxy_candidates_rejected
        ],
        "unmappable_reason": proposal.reason,
    }


def _rejection_record(proposal: RejectionProposal, label: str) -> JsonValue:
    evidence_json = rejection_json(proposal.evidence)
    return {
        "canonical_node_id": proposal.canonical_node_id,
        "canonical_label": label,
        "mapping_result": rejection_result(proposal.evidence),
        "mapping_kind": "rejected",
        "series_links": [],
        "proxy_candidates_rejected": [],
        "unmappable_reason": proposal.reason.value,
        "rejection_evidence": evidence_json,
    }


def build_mapping_artifact(build_input: MappingBuildInput) -> MappingBuildResult:
    conflicts = detect_conflicts(build_input)
    nodes = conflicts.nodes
    catalogs = conflicts.catalogs
    mappings: list[JsonValue] = []
    mutations: list[JsonValue] = []
    blocked_ids: set[str] = set()
    malformed_count = 0

    for node_id, records in sorted(conflicts.duplicate_nodes.items()):
        node = next(
            item
            for item in build_input.source_node_artifact.nodes
            if item.canonical_node_id == node_id
        )
        dirty_evidence = DirtyEvidence(
            conflict_kind=DirtyConflictKind.DUPLICATE_NODE,
            original_records=records,
            conflict_reason="canonical_node_id appears more than once",
        )
        mappings.append(_rejected(MappingIdentity(node_id, node.canonical_label), dirty_evidence))
        mutations.append({"mutation": "reject_mapping", "canonical_node_id": node_id, "reason": "rejected_dirty", "evidence": rejection_json(dirty_evidence), "mutated_at": build_input.generated_at.isoformat(), "mutated_by": MAPPING_POLICY_VERSION})
        blocked_ids.add(node_id)
    for node_id, records in sorted(conflicts.duplicate_proposals.items()):
        node = nodes.get(node_id)
        if node is None or node_id in blocked_ids:
            continue
        dirty_evidence = DirtyEvidence(
            conflict_kind=DirtyConflictKind.DUPLICATE_PROPOSAL,
            original_records=records,
            conflict_reason="canonical node has multiple terminal proposals",
        )
        mappings.append(_rejected(MappingIdentity(node_id, node.canonical_label), dirty_evidence))
        mutations.append({"mutation": "reject_mapping", "canonical_node_id": node_id, "reason": "rejected_dirty", "evidence": rejection_json(dirty_evidence), "mutated_at": build_input.generated_at.isoformat(), "mutated_by": MAPPING_POLICY_VERSION})
        blocked_ids.add(node_id)
    for series_id, records in sorted(conflicts.duplicate_catalogs.items()):
        dirty_evidence = DirtyEvidence(
            conflict_kind=DirtyConflictKind.DUPLICATE_CATALOG,
            original_records=records,
            conflict_reason="series_id appears more than once in the catalog",
        )
        mutations.append({"mutation": "reject_mapping", "candidate_series_id": series_id, "reason": "rejected_dirty", "evidence": rejection_json(dirty_evidence), "mutated_at": build_input.generated_at.isoformat(), "mutated_by": MAPPING_POLICY_VERSION})

    for index, raw in enumerate(build_input.proposals):
        try:
            envelope = ENVELOPE_ADAPTER.validate_python(raw)
        except ValidationError as error:
            malformed_count += 1
            malformed_evidence = MalformedEvidence(json_pointer=f"/proposals/{index}", parse_error=str(error))
            mutations.append({"mutation": "reject_mapping", "reason": "rejected_malformed", "evidence": rejection_json(malformed_evidence), "mutated_at": build_input.generated_at.isoformat(), "mutated_by": MAPPING_POLICY_VERSION})
            continue
        if envelope.canonical_node_id in blocked_ids:
            continue
        node = nodes.get(envelope.canonical_node_id)
        if node is None:
            malformed_count += 1
            malformed_evidence = MalformedEvidence(json_pointer=f"/proposals/{index}/canonical_node_id", parse_error="canonical node does not exist")
            mutations.append({"mutation": "reject_mapping", "canonical_node_id": envelope.canonical_node_id, "reason": "rejected_malformed", "evidence": rejection_json(malformed_evidence), "mutated_at": build_input.generated_at.isoformat(), "mutated_by": MAPPING_POLICY_VERSION})
            continue
        try:
            if envelope.proposal_kind is ProposalKind.APPROVE:
                proposal = APPROVAL_ADAPTER.validate_python(raw)
                duplicate_series_ids = sorted(
                    {
                        link.series_id
                        for link in proposal.series_links
                        if link.series_id in conflicts.duplicate_catalogs
                    }
                )
                if duplicate_series_ids:
                    records = tuple(
                        record
                        for series_id in duplicate_series_ids
                        for record in conflicts.duplicate_catalogs[series_id]
                    )
                    dirty_evidence = DirtyEvidence(
                        conflict_kind=DirtyConflictKind.DUPLICATE_CATALOG,
                        original_records=records,
                        conflict_reason="approval references a conflicting catalog series_id",
                    )
                    mappings.append(_rejected(MappingIdentity(proposal.canonical_node_id, node.canonical_label), dirty_evidence))
                    continue
                problem = approval_problem(proposal, catalogs, build_input.run_cutoff)
                if problem is None:
                    mappings.append(approved_record(proposal, node.canonical_label, catalogs))
                    mutations.append({"mutation": "approve_mapping", "canonical_node_id": proposal.canonical_node_id, "mutated_at": build_input.generated_at.isoformat(), "mutated_by": MAPPING_POLICY_VERSION})
                else:
                    result = rejection_result(problem)
                    evidence_json = rejection_json(problem)
                    mappings.append({"canonical_node_id": proposal.canonical_node_id, "canonical_label": node.canonical_label, "mapping_result": result, "mapping_kind": "rejected", "series_links": [], "proxy_candidates_rejected": [], "unmappable_reason": result, "rejection_evidence": evidence_json})
                    mutations.append({"mutation": "expire_mapping" if result == "rejected_stale" else "reject_mapping", "canonical_node_id": proposal.canonical_node_id, "reason": result, "evidence": evidence_json, "mutated_at": build_input.generated_at.isoformat(), "mutated_by": MAPPING_POLICY_VERSION})
                continue
            if envelope.proposal_kind is ProposalKind.UNMAPPABLE:
                proposal = UNMAPPABLE_ADAPTER.validate_python(raw)
                mappings.append(_unmappable_record(proposal, node.canonical_label))
                mutations.append({"mutation": "mark_unmappable", "canonical_node_id": proposal.canonical_node_id, "reason": proposal.reason, "mutated_at": build_input.generated_at.isoformat(), "mutated_by": MAPPING_POLICY_VERSION})
                continue
            if envelope.proposal_kind is ProposalKind.REJECT:
                proposal = REJECTION_ADAPTER.validate_python(raw)
                evidence_series_id = rejection_candidate_id(proposal.evidence)
                if (
                    evidence_series_id is not None
                    and evidence_series_id != proposal.candidate_series_id
                ):
                    malformed_evidence = MalformedEvidence(
                        json_pointer=f"/proposals/{index}/candidate_series_id",
                        parse_error="top-level candidate_series_id differs from rejection evidence",
                    )
                    evidence_json = rejection_json(malformed_evidence)
                    mappings.append(_rejected(MappingIdentity(proposal.canonical_node_id, node.canonical_label), malformed_evidence))
                    mutations.append({"mutation": "reject_mapping", "canonical_node_id": proposal.canonical_node_id, "reason": "rejected_malformed", "evidence": evidence_json, "mutated_at": build_input.generated_at.isoformat(), "mutated_by": MAPPING_POLICY_VERSION})
                    continue
                mappings.append(_rejection_record(proposal, node.canonical_label))
                mutations.append({"mutation": "reject_mapping", "canonical_node_id": proposal.canonical_node_id, "candidate_series_id": proposal.candidate_series_id, "reason": proposal.reason.value, "evidence": rejection_json(proposal.evidence), "mutated_at": build_input.generated_at.isoformat(), "mutated_by": MAPPING_POLICY_VERSION})
        except ValidationError as error:
            malformed_count += 1
            malformed_evidence = MalformedEvidence(json_pointer=f"/proposals/{index}", parse_error=str(error))
            evidence_json = rejection_json(malformed_evidence)
            mappings.append(_rejected(MappingIdentity(envelope.canonical_node_id, node.canonical_label), malformed_evidence))
            mutations.append({"mutation": "reject_mapping", "canonical_node_id": envelope.canonical_node_id, "reason": "rejected_malformed", "evidence": evidence_json, "mutated_at": build_input.generated_at.isoformat(), "mutated_by": MAPPING_POLICY_VERSION})

    mapped_ids: set[str] = set()
    for mapping in mappings:
        if isinstance(mapping, dict) and isinstance(node_id := mapping.get("canonical_node_id"), str):
            mapped_ids.add(node_id)
    for label, series_id in sorted(build_input.legacy_flat_map.items()):
        node = next((item for item in build_input.source_node_artifact.nodes if item.canonical_label == label), None)
        if node is None or node.canonical_node_id in mapped_ids:
            continue
        candidate_evidence: JsonValue = {"source": "legacy_flat_map", "node_text": label, "candidate_series_id": series_id}
        mappings.append({"canonical_node_id": node.canonical_node_id, "canonical_label": node.canonical_label, "mapping_result": "needs_manual_review", "mapping_kind": "rejected", "series_links": [], "proxy_candidates_rejected": [], "unmappable_reason": "Legacy keyword evidence requires manual review.", "candidate_evidence": candidate_evidence})
        mutations.append({"mutation": "add_candidate", "canonical_node_id": node.canonical_node_id, "candidate_series_id": series_id, "evidence": candidate_evidence, "mutated_at": build_input.generated_at.isoformat(), "mutated_by": MAPPING_POLICY_VERSION})

    mappings.sort(key=lambda item: canonical_json(item))
    mutations.sort(key=lambda item: canonical_json(item))
    artifact: JsonValue = {
        "schema_version": MAPPING_SCHEMA_VERSION,
        "source_node_schema_version": SOURCE_NODE_SCHEMA_VERSION,
        "source_node_artifact_hash": canonical_hash(
            build_input.source_node_artifact.model_dump(mode="json")
        ),
        "mapping_policy_version": MAPPING_POLICY_VERSION,
        "generated_at": build_input.generated_at.isoformat(),
        "series_catalog": [_catalog_json(entry) for entry in sorted(catalogs.values(), key=lambda item: item.series_id)],
        "mappings": mappings,
        "mapping_mutations": mutations,
        "qa": {
            "read_checks": ["canonical_node_id_primary_key", "legacy_flat_map_candidate_only"],
            "json_checks": ["approved_fields_complete", "catalog_membership", "mapping_cardinality", f"malformed_rejected:{malformed_count}"],
            "mutation_checks": ["add_candidate", "approve_mapping", "reject_mapping", "expire_mapping", "mark_unmappable"],
        },
    }
    return MappingBuildResult(artifact)
