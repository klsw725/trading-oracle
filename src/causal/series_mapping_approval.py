import ast
from datetime import datetime
from typing import TypedDict

from .series_mapping_models import (
    MAPPING_SCHEMA_VERSION,
    ApprovalProposal,
    CatalogEntry,
    MalformedEvidence,
    MappingKind,
    RejectionEvidence,
    StaleEvidence,
)
from src.v4.models import JsonValue, canonical_hash


class ApprovalBody(TypedDict):
    mapping_result: str
    mapping_kind: str
    mapping_expires_at: str
    formula: str | None
    formula_unit: str | None
    series_links: list[JsonValue]
    proxy_candidates_rejected: list[JsonValue]
    unmappable_reason: None


_FORMULA_NODES = (
    ast.Expression,
    ast.BinOp,
    ast.UnaryOp,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.UAdd,
    ast.USub,
    ast.Name,
    ast.Load,
)


def _formula_variables(formula: str) -> frozenset[str] | None:
    try:
        tree = ast.parse(formula, mode="eval")
    except SyntaxError:
        return None
    if any(not isinstance(node, _FORMULA_NODES) for node in ast.walk(tree)):
        return None
    return frozenset(node.id for node in ast.walk(tree) if isinstance(node, ast.Name))


def _malformed(pointer: str, error: str) -> MalformedEvidence:
    return MalformedEvidence(json_pointer=pointer, parse_error=error)


def approval_json(
    approval: ApprovalProposal, catalogs: dict[str, CatalogEntry]
) -> ApprovalBody:
    links: list[JsonValue] = []
    for link in approval.series_links:
        catalog = catalogs[link.series_id]
        links.append(
            {
                "series_id": link.series_id,
                "transform": link.transform.value,
                "unit": link.unit,
                "direction": link.direction.value,
                "source_id": link.source_id,
                "as_of": link.as_of.isoformat(),
                "source_expires_at": catalog.expires_at.isoformat(),
                "provenance_hash": link.provenance_hash,
                "suitability": link.suitability,
                "suitability_evidence": link.suitability_evidence,
                "manual_approval": {
                    "required": True,
                    "approved_by": link.manual_approval.approved_by,
                    "approved_at": link.manual_approval.approved_at.isoformat(),
                    "approval_reason": link.manual_approval.approval_reason,
                    "expires_at": link.manual_approval.expires_at.isoformat(),
                },
            }
        )
    return {
        "mapping_result": "approved_manual",
        "mapping_kind": approval.mapping_kind.value,
        "mapping_expires_at": approval.mapping_expires_at.isoformat(),
        "formula": approval.formula,
        "formula_unit": approval.formula_unit,
        "series_links": links,
        "proxy_candidates_rejected": [],
        "unmappable_reason": None,
    }


def approval_problem(
    approval: ApprovalProposal,
    catalogs: dict[str, CatalogEntry],
    cutoff: datetime,
) -> RejectionEvidence | None:
    link_count = len(approval.series_links)
    if approval.mapping_kind is MappingKind.SINGLE and link_count != 1:
        return _malformed("/series_links", "single_series requires exactly one link")
    if approval.mapping_kind is MappingKind.COMPOSITE:
        if link_count < 2 or not approval.formula or not approval.formula_unit:
            return _malformed(
                "/formula", "composite requires links, formula, and formula_unit"
            )
        series_ids = [link.series_id for link in approval.series_links]
        if len(series_ids) != len(set(series_ids)):
            return _malformed("/series_links", "composite series IDs must be unique")
        formula_inputs = _formula_variables(approval.formula)
        if formula_inputs is None or formula_inputs != frozenset(series_ids):
            return _malformed(
                "/formula",
                "formula must use restricted arithmetic and exactly the linked series IDs",
            )
    missing = sorted(
        {link.series_id for link in approval.series_links} - catalogs.keys()
    )
    if missing:
        return _malformed("/series_links", f"series absent from catalog: {missing}")
    for link in approval.series_links:
        catalog = catalogs[link.series_id]
        if catalog.as_of > cutoff or link.as_of > cutoff:
            return _malformed(
                f"/series_links/{link.series_id}/as_of",
                "source as_of is later than the consuming run cutoff",
            )
        if (
            catalog.as_of >= catalog.expires_at
            or link.manual_approval.approved_at >= link.manual_approval.expires_at
        ):
            return _malformed(
                f"/series_links/{link.series_id}/expires_at",
                "source or approval expiry interval is invalid",
            )
        if link.manual_approval.approved_at > cutoff:
            return _malformed(
                f"/series_links/{link.series_id}/manual_approval/approved_at",
                "approval timestamp is later than the consuming run cutoff",
            )
        if (
            link.source_id != catalog.source_id
            or link.provenance_hash != catalog.provenance_hash
            or link.as_of != catalog.as_of
        ):
            return _malformed(
                f"/series_links/{link.series_id}/provenance_hash",
                "link provenance does not match catalog",
            )
    stale_links = [
        link
        for link in approval.series_links
        if catalogs[link.series_id].expires_at <= cutoff
        or link.manual_approval.expires_at <= cutoff
    ]
    if approval.mapping_expires_at <= cutoff or stale_links:
        expired_fields = [
            field
            for field, expired in (
                ("mapping_expires_at", approval.mapping_expires_at <= cutoff),
                (
                    "source_expires_at",
                    any(catalogs[link.series_id].expires_at <= cutoff for link in approval.series_links),
                ),
                (
                    "manual_approval.expires_at",
                    any(link.manual_approval.expires_at <= cutoff for link in approval.series_links),
                ),
            )
            if expired
        ]
        affected = tuple(
            link.series_id for link in (stale_links or list(approval.series_links))
        )
        return StaleEvidence(
            expired_field=tuple(expired_fields),
            run_cutoff=cutoff,
            affected_series_id=affected,
            mapping_expires_at=approval.mapping_expires_at,
            source_expiries={
                link.series_id: catalogs[link.series_id].expires_at
                for link in approval.series_links
            },
            approval_expiries={
                link.series_id: link.manual_approval.expires_at
                for link in approval.series_links
            },
        )
    effective_expiries = [
        expiry
        for link in approval.series_links
        for expiry in (catalogs[link.series_id].expires_at, link.manual_approval.expires_at)
    ]
    if approval.mapping_expires_at > min(effective_expiries):
        return _malformed(
            "/mapping_expires_at",
            "mapping expiry exceeds a source or approval expiry",
        )
    return None


def approved_record(
    proposal: ApprovalProposal,
    label: str,
    catalogs: dict[str, CatalogEntry],
) -> JsonValue:
    body = approval_json(proposal, catalogs)
    body_json: JsonValue = {
        "mapping_result": body["mapping_result"],
        "mapping_kind": body["mapping_kind"],
        "mapping_expires_at": body["mapping_expires_at"],
        "formula": body["formula"],
        "formula_unit": body["formula_unit"],
        "series_links": body["series_links"],
        "proxy_candidates_rejected": body["proxy_candidates_rejected"],
        "unmappable_reason": body["unmappable_reason"],
    }
    seed: JsonValue = {
        "schema_version": MAPPING_SCHEMA_VERSION,
        "canonical_node_id": proposal.canonical_node_id,
        "mapping": body_json,
    }
    return {
        "canonical_node_id": proposal.canonical_node_id,
        "canonical_label": label,
        "mapping_hash": canonical_hash(seed),
        "mapping_result": body["mapping_result"],
        "mapping_kind": body["mapping_kind"],
        "mapping_expires_at": body["mapping_expires_at"],
        "formula": body["formula"],
        "formula_unit": body["formula_unit"],
        "series_links": body["series_links"],
        "proxy_candidates_rejected": body["proxy_candidates_rejected"],
        "unmappable_reason": body["unmappable_reason"],
    }
