from src.causal.series_mapping_models import (
    DirtyEvidence,
    MalformedEvidence,
    MisleadingEvidence,
    ProxyEvidence,
    RejectionEvidence,
)
from src.v4.models import JsonValue


def rejection_result(evidence: RejectionEvidence) -> str:
    if isinstance(evidence, DirtyEvidence):
        return "rejected_dirty"
    if isinstance(evidence, ProxyEvidence):
        return "rejected_proxy"
    if isinstance(evidence, MisleadingEvidence):
        return "rejected_misleading"
    if isinstance(evidence, MalformedEvidence):
        return "rejected_malformed"
    return "rejected_stale"


def rejection_candidate_id(evidence: RejectionEvidence) -> str | None:
    if isinstance(evidence, ProxyEvidence):
        return evidence.candidate_series_id
    if isinstance(evidence, MisleadingEvidence):
        return evidence.candidate_series_id
    return None


def rejection_json(evidence: RejectionEvidence) -> JsonValue:
    if isinstance(evidence, DirtyEvidence):
        return {
            "conflict_kind": evidence.conflict_kind.value,
            "original_records": list(evidence.original_records),
            "conflict_reason": evidence.conflict_reason,
        }
    if isinstance(evidence, ProxyEvidence):
        return {
            "candidate_series_id": evidence.candidate_series_id,
            "proxy_reason": evidence.proxy_reason,
            "missing_direct_source_explanation": evidence.missing_direct_source_explanation,
        }
    if isinstance(evidence, MisleadingEvidence):
        return {
            "candidate_series_id": evidence.candidate_series_id,
            "expected_direction": evidence.expected_direction.value,
            "observed_conflict": evidence.observed_conflict,
        }
    if isinstance(evidence, MalformedEvidence):
        return {
            "json_pointer": evidence.json_pointer,
            "parse_error": evidence.parse_error,
        }
    return {
        "expired_field": list(evidence.expired_field),
        "run_cutoff": evidence.run_cutoff.isoformat(),
        "affected_series_id": list(evidence.affected_series_id),
        "mapping_expires_at": evidence.mapping_expires_at.isoformat(),
        "source_expiries": {
            key: value.isoformat() for key, value in evidence.source_expiries.items()
        },
        "approval_expiries": {
            key: value.isoformat() for key, value in evidence.approval_expiries.items()
        },
    }
