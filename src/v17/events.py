from __future__ import annotations

from dataclasses import dataclass
from .canonical import JsonValue, canonical_hash, canonical_json
from .errors import V17Error
from .models import (
    AmountPayload,
    Command,
    EventPayload,
    EventType,
    OpenedPayload,
    PositionPayload,
    ReleasePayload,
    ReservationPayload,
)
from .schema import EVENT_SCHEMA_VERSION


@dataclass(frozen=True, slots=True)
class Event:
    sequence: int
    event_id: str
    event_type: EventType
    semantic_key: str
    runtime_identity: str
    config_version: str
    policy_version: str
    effective_at: str
    payload: EventPayload
    previous_event_hash: str
    event_hash: str


def payload_value(payload: EventPayload) -> JsonValue:
    return payload.model_dump(mode="json")


def parse_payload(event_type: str, payload_json: str) -> EventPayload:
    match event_type:  # noqa: MATCH_OK - untrusted event types require explicit rejection.
        case "account.opened":
            return OpenedPayload.model_validate_json(payload_json)
        case "cash.credited" | "cash.debited":
            return AmountPayload.model_validate_json(payload_json)
        case "position.adjusted":
            return PositionPayload.model_validate_json(payload_json)
        case "reservation.placed":
            return ReservationPayload.model_validate_json(payload_json)
        case "reservation.released":
            return ReleasePayload.model_validate_json(payload_json)
        case _:
            raise V17Error("UNKNOWN_EVENT_TYPE", event_type)


def validate_timestamp(value: str) -> None:
    import re

    if re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", value) is None:
        raise V17Error("INVALID_TIMESTAMP", value)
    from datetime import datetime

    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as error:
        raise V17Error("INVALID_TIMESTAMP", value) from error
    if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != value:
        raise V17Error("INVALID_TIMESTAMP", value)


def validate_payload(command: Command) -> None:
    match command.command_type, command.payload:  # noqa: MATCH_OK - payload mismatch is rejected.
        case "account.opened", OpenedPayload():
            return
        case ("cash.credited" | "cash.debited"), AmountPayload():
            return
        case "position.adjusted", PositionPayload():
            return
        case "reservation.placed", ReservationPayload():
            return
        case "reservation.released", ReleasePayload():
            return
        case _:
            raise V17Error("INVALID_EVENT_PAYLOAD", command.command_type)


def event_body(command: Command, sequence: int, semantic_key: str, previous_hash: str) -> JsonValue:
    return {
        "event_schema_version": EVENT_SCHEMA_VERSION,
        "sequence": sequence,
        "event_type": command.command_type,
        "semantic_key": semantic_key,
        "namespace": command.namespace.model_dump(mode="json"),
        "runtime_identity": command.identity.runtime_identity,
        "config_version": command.config_version,
        "policy_version": command.policy_version,
        "effective_at": command.effective_at,
        "payload": payload_value(command.payload),
        "previous_event_hash": previous_hash,
    }


def build_event(command: Command, sequence: int, semantic_key: str, previous_hash: str) -> Event:
    validate_timestamp(command.effective_at)
    validate_payload(command)
    event_hash = canonical_hash(event_body(command, sequence, semantic_key, previous_hash))
    return Event(sequence, event_hash, command.command_type, semantic_key,
                 command.identity.runtime_identity, command.config_version,
                 command.policy_version, command.effective_at, command.payload,
                 previous_hash, event_hash)


def event_payload_json(event: Event) -> str:
    return canonical_json(payload_value(event.payload)).decode("utf-8")
