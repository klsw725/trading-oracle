from __future__ import annotations

from datetime import datetime
from typing import Final

from src.v8.risk_json import JsonValue, canonical_hash, deterministic_id, model_json
from src.v8.risk_models import (
    AckVerificationContext,
    KillSwitchRecord,
    ResetAttempt,
    ResetResult,
    RiskAcknowledgement,
    RiskDecision,
    Scope,
)

_RESET_EVIDENCE: Final = frozenset(
    {
        "root_cause_recorded",
        "fresh_quote_evidence",
        "market_calendar_evidence",
        "daily_loss_evidence_when_applicable",
        "hash_chain_recomputed",
        "forbidden_fields_absent",
    }
)
_FORBIDDEN_SWITCH_KEY_PARTS: Final = (
    "account",
    "credential",
    "access_token",
    "refresh_token",
    "client_secret",
    "api_key",
    "broker_order",
    "live_",
)


def _contains_forbidden_switch_key(value: JsonValue) -> bool:
    match value:
        case dict() as record:
            return any(
                any(part in key.lower() for part in _FORBIDDEN_SWITCH_KEY_PARTS)
                or _contains_forbidden_switch_key(child)
                for key, child in record.items()
            )
        case list() as values:
            return any(_contains_forbidden_switch_key(child) for child in values)
        case None | bool() | int() | float() | str():
            return False


def _valid_source_hashes(source_hashes: dict[str, str]) -> bool:
    return bool(source_hashes) and all(
        value.startswith("sha256:")
        and len(value) == 71
        and all(character in "0123456789abcdef" for character in value[7:])
        for value in source_hashes.values()
    )


def activate_switch(
    scope: Scope,
    scope_value: str | None,
    actor: str,
    activated_at: datetime,
    reason_code: str,
    source_hashes: dict[str, str],
    previous_hash: str = "sha256:genesis",
) -> KillSwitchRecord:
    source_values: dict[str, JsonValue] = {
        key: value for key, value in source_hashes.items()
    }
    seed: dict[str, JsonValue] = {
        "scope": scope,
        "scope_value": scope_value,
        "actor": actor,
        "activated_at": activated_at.isoformat(),
        "reason_code": reason_code,
        "source_hashes": source_values,
        "prev_record_hash": previous_hash,
    }
    record = KillSwitchRecord(
        schema_version="v8.risk_controls.kill_switch.1",
        kill_switch_id=deterministic_id("ksw_v8_", seed),
        switch_status="active",
        scope=scope,
        scope_value=scope_value,
        activated_by=actor,
        activated_at=activated_at,
        reason_codes=(reason_code,),
        covered_actions=("BUY", "SELL"),
        reset_requirements=tuple(sorted(_RESET_EVIDENCE)),
        source_hashes=source_hashes,
        prev_record_hash=previous_hash,
        record_hash="sha256:pending",
    )
    return record.model_copy(
        update={"record_hash": canonical_hash(model_json(record, exclude={"record_hash"}))}
    )


def risk_version(decision: RiskDecision) -> str:
    warning_values: list[JsonValue] = list(decision.ack_required_reasons)
    source_values: dict[str, JsonValue] = {
        key: value for key, value in decision.source_hashes.items()
    }
    seed: dict[str, JsonValue] = {
        "risk_decision_id": decision.risk_decision_id,
        "warnings": warning_values,
        "source_hashes": source_values,
        "ticker": decision.ticker,
    }
    return canonical_hash(seed)


def build_acknowledgement(
    decision: RiskDecision,
    operator_ref: str,
    reason_code: str,
    acknowledged_at: datetime,
    expires_at: datetime,
) -> RiskAcknowledgement | None:
    if decision.risk_status != "requires_ack" or decision.blocking_reasons:
        return None
    if acknowledged_at > expires_at or reason_code not in decision.ack_required_reasons:
        return None
    version = risk_version(decision)
    seed: dict[str, JsonValue] = {
        "risk_decision_id": decision.risk_decision_id,
        "risk_version": version,
        "operator_ref": operator_ref,
        "reason_code": reason_code,
        "acknowledged_at": acknowledged_at.isoformat(),
        "expires_at": expires_at.isoformat(),
    }
    acknowledgement = RiskAcknowledgement(
        schema_version="v8.risk_controls.acknowledgement.1",
        risk_ack_id=deterministic_id("rack_v8_", seed),
        risk_decision_id=decision.risk_decision_id,
        risk_version=version,
        operator_ref=operator_ref,
        permission="risk.acknowledge",
        reason_code=reason_code,
        acknowledged_at=acknowledged_at,
        expires_at=expires_at,
        source_hashes=decision.source_hashes,
        prev_record_hash="sha256:genesis",
        record_hash="sha256:pending",
    )
    return acknowledgement.model_copy(
        update={"record_hash": canonical_hash(model_json(acknowledgement, exclude={"record_hash"}))}
    )


def verify_acknowledgement(
    decision: RiskDecision,
    acknowledgement: RiskAcknowledgement,
    context: AckVerificationContext,
) -> bool:
    return (
        decision.risk_status == "requires_ack"
        and not decision.blocking_reasons
        and acknowledgement.risk_decision_id == decision.risk_decision_id
        and acknowledgement.risk_version == risk_version(decision)
        and acknowledgement.operator_ref == context.operator_ref
        and acknowledgement.reason_code in decision.ack_required_reasons
        and acknowledgement.acknowledged_at <= context.observed_at
        and context.observed_at <= acknowledgement.expires_at
        and acknowledgement.record_hash
        == canonical_hash(model_json(acknowledgement, exclude={"record_hash"}))
    )


def verify_switch_chain(records: tuple[KillSwitchRecord, ...]) -> bool:
    if not records or records[0].switch_status != "active":
        return False
    previous = "sha256:genesis"
    identities: set[str] = set()
    hashes: set[str] = set()
    for record in records:
        valid = (
            record.prev_record_hash == previous
            and record.record_hash == canonical_hash(model_json(record, exclude={"record_hash"}))
            and _valid_source_hashes(record.source_hashes)
            and not _contains_forbidden_switch_key(model_json(record))
            and record.kill_switch_id not in identities
            and record.record_hash not in hashes
        )
        if not valid:
            return False
        previous = record.record_hash
        identities.add(record.kill_switch_id)
        hashes.add(record.record_hash)
    return True


def reset_switch(
    active: KillSwitchRecord,
    stream: tuple[KillSwitchRecord, ...],
    attempt: ResetAttempt,
) -> ResetResult:
    reviewers = frozenset(attempt.reviewer_refs)
    elapsed = (attempt.reviewed_at - attempt.requested_at).total_seconds()
    valid = (
        active.switch_status == "active"
        and verify_switch_chain(stream)
        and stream[-1] == active
        and len(reviewers) >= 2
        and attempt.requester_ref not in reviewers
        and len(attempt.permissions) >= 2
        and _RESET_EVIDENCE.issubset(attempt.evidence)
        and attempt.chain_recomputed
        and attempt.cooldown_seconds >= 900
        and elapsed >= attempt.cooldown_seconds
    )
    if not valid:
        return ResetResult("blocked", (), "reset_requirements_not_met")
    reviewer_values: list[JsonValue] = [reviewer for reviewer in sorted(reviewers)]
    seed: dict[str, JsonValue] = {
        "active_switch_id": active.kill_switch_id,
        "reviewers": reviewer_values,
        "reviewed_at": attempt.reviewed_at.isoformat(),
        "prev_record_hash": active.record_hash,
    }
    records: list[KillSwitchRecord] = []
    previous = active.record_hash
    for status, reason in (
        ("reset_requested", "reset_requested"),
        ("reset_approved", "independent_review_approved"),
        ("inactive", "reset_requirements_satisfied"),
    ):
        record_seed: dict[str, JsonValue] = {
            **seed,
            "switch_status": status,
            "prev_record_hash": previous,
        }
        record = active.model_copy(
            update={
                "kill_switch_id": deterministic_id("ksw_v8_", record_seed),
                "switch_status": status,
                "activated_by": attempt.requester_ref,
                "activated_at": attempt.reviewed_at,
                "reason_codes": (reason,),
                "covered_actions": () if status == "inactive" else active.covered_actions,
                "source_hashes": {"reset": canonical_hash(record_seed)},
                "prev_record_hash": previous,
                "record_hash": "sha256:pending",
            }
        )
        record = record.model_copy(
            update={"record_hash": canonical_hash(model_json(record, exclude={"record_hash"}))}
        )
        records.append(record)
        previous = record.record_hash
    return ResetResult("approved", tuple(records))
