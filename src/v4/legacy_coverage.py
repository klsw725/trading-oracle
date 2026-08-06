from pathlib import Path
from typing import Final

from .legacy import POLICY_VERSION, legacy_derived_body
from .legacy_models import (
    LegacyDerivedAudit,
    LegacyInventoryReport,
    LegacyParseState,
    LegacyProvenance,
)
from src.v4.models import JsonValue


_SOURCE_FAILURE_STATES: Final = {
    LegacyParseState.PARSED: None,
    LegacyParseState.MALFORMED: "malformed_source_json",
    LegacyParseState.MISSING_REQUIRED_FIELD: "missing_required_legacy_field",
}


def source_failure_state(state: LegacyParseState) -> str | None:
    return _SOURCE_FAILURE_STATES[state]


def legacy_derived_path(root: Path, audit: LegacyDerivedAudit) -> Path:
    return root / "snapshots" / f"{audit.source_path.stem}.{audit.legacy_snapshot_id}.derived.json"


def quarantine_document(report: LegacyInventoryReport) -> JsonValue:
    records: list[JsonValue] = []
    for source in report.records:
        failure_state = source_failure_state(source.parse_state)
        if failure_state is not None:
            records.append(
                {
                    "failure_state": failure_state,
                    "source_path": source.source_path.as_posix(),
                    "source_sha256": source.source_hash,
                }
            )
        for record in source.recommendation_records:
            if record.failure_states:
                records.append(
                    {
                        "failure_states": list(record.failure_states),
                        "legacy_recommendation_id": record.legacy_recommendation_id,
                        "source_path": source.source_path.as_posix(),
                        "source_record_index": record.source_record_index,
                        "source_sha256": source.source_hash,
                    }
                )
    return {
        "policy_version": POLICY_VERSION,
        "records": records,
        "invalid_record_count": len(records),
        "schema_version": "v4.legacy_backfill.quarantine.phase24.1",
    }


def _provenance(value: JsonValue | None) -> LegacyProvenance | None:
    match value:  # noqa: MATCH_OK - JSON boundary intentionally has a fallback
        case {"provenance": str() as provenance}:
            return LegacyProvenance(provenance)
        case _:
            return None


def coverage_document(
    inventory: LegacyInventoryReport,
    derived_root: Path,
    audits: tuple[LegacyDerivedAudit, ...],
) -> JsonValue:
    audit_by_path = {audit.source_path: audit for audit in audits}
    records: list[JsonValue] = []
    for source in inventory.records:
        audit = audit_by_path[source.source_path]
        body = legacy_derived_body(audit)
        source_body = body["source"]
        derived_records = body["records"]
        covered: dict[str, list[JsonValue]] = {
            provenance.value: [] for provenance in LegacyProvenance
        }
        if body.get("legacy_snapshot_id") is not None:
            covered[LegacyProvenance.DERIVED].append("legacy_snapshot_id")
        if isinstance(derived_records, list) and any(
            isinstance(record, dict) and record.get("legacy_recommendation_id") is not None
            for record in derived_records
        ):
            covered[LegacyProvenance.DERIVED].append("legacy_recommendation_id")
        if isinstance(source_body, dict):
            for body_field, coverage_field in (
                ("source_snapshot_date", "date"),
                ("market", "market"),
            ):
                if (provenance := _provenance(source_body.get(body_field))) is not None:
                    covered[provenance].append(coverage_field)
        if body.get("parse_state") == LegacyParseState.PARSED and isinstance(derived_records, list):
            covered[LegacyProvenance.DIRECT].append("recommendations")
            for body_field, coverage_field in (
                ("consensus_verdict", "consensus"),
                ("perspectives", "perspectives"),
            ):
                provenances = {
                    provenance
                    for record in derived_records
                    if isinstance(record, dict)
                    and (provenance := _provenance(record.get(body_field))) is not None
                }
                if len(provenances) == 1:
                    covered[provenances.pop()].append(coverage_field)
        else:
            covered[LegacyProvenance.UNKNOWN].append("recommendations")
        if isinstance(derived_records, list):
            covered[LegacyProvenance.UNKNOWN].extend(
                field
                for record in derived_records
                if isinstance(record, dict)
                and isinstance((fields := record.get("unknown_native_fields")), list)
                for field in fields
                if isinstance(field, str)
                and field not in covered[LegacyProvenance.UNKNOWN]
            )
        covered[LegacyProvenance.NOT_APPLICABLE].append(
            "code_quant_raw_provider_payload"
        )
        covered_fields: dict[str, JsonValue] = {
            provenance: list(fields) for provenance, fields in covered.items()
        }
        failure_states: list[JsonValue] = (
            [failure_state]
            if (failure_state := source_failure_state(source.parse_state)) is not None
            else []
        )
        failure_states.extend(
            failure
            for record in source.recommendation_records
            for failure in record.failure_states
        )
        parsed = source.parse_state is LegacyParseState.PARSED
        coverage_record: dict[str, JsonValue] = {
            "audit_only": True,
            "canonical_metric_eligible": False,
            "covered_fields": covered_fields,
            "derived_artifact_path": legacy_derived_path(derived_root, audit).as_posix() if parsed else None,
            "derived_artifact_sha256": audit.derived_artifact_hash if parsed else None,
            "failure_states": failure_states,
            "migration_tier": source.migration_tier,
            "parse_state": source.parse_state,
            "recommendation_count": source.recommendation_count,
            "source_path": source.source_path.as_posix(),
            "source_sha256": source.source_hash,
        }
        records.append(coverage_record)
    return {
        "canonical_metric_eligible_count": 0,
        "expected_source_count": inventory.expected_source_count,
        "failure_states": list(inventory.failure_states),
        "policy_version": POLICY_VERSION,
        "records": records,
        "schema_version": "v4.legacy_backfill.coverage.phase24.1",
        "source_root": inventory.records[0].source_path.parent.as_posix() if inventory.records else "",
        "summary": {
            "audit_only_sources": inventory.parsed_source_count,
            "canonical_metric_eligible_sources": 0,
            "coverage_complete": inventory.coverage_complete,
            "failed_sources": inventory.malformed_source_count,
            "invalid_recommendation_records": inventory.invalid_recommendation_count,
            "malformed_sources": inventory.malformed_source_count,
            "parsed_sources": inventory.parsed_source_count,
            "source_count_matches_expected": inventory.source_count_matches_expected,
        },
    }
