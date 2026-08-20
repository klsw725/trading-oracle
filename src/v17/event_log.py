from __future__ import annotations

from .canonical import JsonValue, canonical_hash
from .database import Connection
from .errors import V17Error
from .events import Event, event_payload_json, parse_payload, payload_value
from .identity import SUPPORTED_POLICIES
from .models import AccountNamespace, EventType
from .schema import EVENT_SCHEMA_VERSION


def namespace_key(namespace: AccountNamespace) -> tuple[str, str, str, str]:
    return (namespace.account_id, namespace.market.value, namespace.currency.value, namespace.arm_id)


def append(connection: Connection, namespace: AccountNamespace, event: Event) -> None:
    _ = connection.execute(
        "INSERT INTO events VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (*namespace_key(namespace), event.sequence, EVENT_SCHEMA_VERSION, event.event_id,
         event.event_type, event.semantic_key, event.runtime_identity, event.config_version,
         event.policy_version, event.effective_at, event_payload_json(event),
         event.previous_event_hash, event.event_hash),
    )


def parse_event_type(value: str) -> EventType:
    match value:  # noqa: MATCH_OK - untrusted database values require explicit rejection.
        case "account.opened": return "account.opened"
        case "cash.credited": return "cash.credited"
        case "cash.debited": return "cash.debited"
        case "position.adjusted": return "position.adjusted"
        case "reservation.placed": return "reservation.placed"
        case "reservation.released": return "reservation.released"
        case _: raise V17Error("UNKNOWN_EVENT_TYPE", value)


def verify_hash(namespace: AccountNamespace, event: Event) -> None:
    namespace_value: JsonValue = {
        "account_id": namespace.account_id,
        "market": namespace.market.value,
        "currency": namespace.currency.value,
        "arm_id": namespace.arm_id,
    }
    body: JsonValue = {
        "event_schema_version": EVENT_SCHEMA_VERSION,
        "sequence": event.sequence,
        "event_type": event.event_type,
        "semantic_key": event.semantic_key,
        "namespace": namespace_value,
        "runtime_identity": event.runtime_identity,
        "config_version": event.config_version,
        "policy_version": event.policy_version,
        "effective_at": event.effective_at,
        "payload": payload_value(event.payload),
        "previous_event_hash": event.previous_event_hash,
    }
    expected = canonical_hash(body)
    if event.event_hash != expected or event.event_id != expected:
        raise V17Error("EVENT_HASH_MISMATCH", event.event_id)


def event_from_row(row: tuple[int, str, str, str, str, str, str, str, str, str, str, str]) -> Event:
    sequence, schema, event_id, event_type, semantic, runtime, config, policy, effective, payload, previous, event_hash = row
    if schema != EVENT_SCHEMA_VERSION:
        raise V17Error("UNKNOWN_EVENT_SCHEMA", schema)
    if policy not in SUPPORTED_POLICIES:
        raise V17Error("UNKNOWN_EVENT_POLICY", policy)
    parsed_type = parse_event_type(event_type)
    return Event(sequence, event_id, parsed_type, semantic, runtime, config, policy,
                 effective, parse_payload(event_type, payload), previous, event_hash)
