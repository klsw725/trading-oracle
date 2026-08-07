from typing import Literal

from src.v6.models import BoundaryModel

from .models import HashText
from .source_events import AuditEvent, AuditEventBody, AuditPayload, build_event, event_hash
from .source_models import SourcePolicyError


class AuditHistoryBody(BoundaryModel):
    schema_version: Literal["v7.source-policy.audit-history.1"]
    events: tuple[AuditEvent, ...]
    head_event_hash: HashText


class AuditHistory(AuditHistoryBody):
    history_hash: HashText


def append_event(history: AuditHistory, payload: AuditPayload) -> AuditHistory:
    event = build_event(len(history.events), history.head_event_hash, payload)
    body = AuditHistoryBody(schema_version="v7.source-policy.audit-history.1", events=(*history.events, event), head_event_hash=event.audit_event_hash)
    return AuditHistory.model_validate({**body.model_dump(mode="json"), "history_hash": event_hash(body)})


def empty_history() -> AuditHistory:
    body = AuditHistoryBody(schema_version="v7.source-policy.audit-history.1", events=(), head_event_hash="sha256:" + "0" * 64)
    return AuditHistory.model_validate({**body.model_dump(mode="json"), "history_hash": event_hash(body)})


def verify_history(history: AuditHistory) -> None:
    previous = "sha256:" + "0" * 64
    for index, event in enumerate(history.events):
        if event.event_index != index or event.previous_event_hash != previous:
            raise SourcePolicyError("EVENT_CHAIN_SPLICE", str(index))
        body = AuditEventBody.model_validate(event.model_dump(mode="json", exclude={"audit_event_hash"}))
        if event.payload_hash != event_hash(event.payload) or event.audit_event_hash != event_hash(body):
            raise SourcePolicyError("AUDIT_HASH_MISMATCH", str(index))
        previous = event.audit_event_hash
    body = AuditHistoryBody.model_validate(history.model_dump(mode="json", exclude={"history_hash"}))
    if history.head_event_hash != previous or history.history_hash != event_hash(body):
        raise SourcePolicyError("HISTORY_HASH_MISMATCH", "history projection")
