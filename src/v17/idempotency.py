from __future__ import annotations

from .canonical import canonical_hash
from .models import Command
from .events import payload_value


def semantic_key(command: Command) -> str:
    return canonical_hash({
        "command_type": command.command_type,
        "namespace": command.namespace.model_dump(mode="json"),
        "command_id": command.command_id,
        "config_version": command.config_version,
        "policy_version": command.policy_version,
    })


def request_hash(command: Command) -> str:
    return canonical_hash({
        "runtime_identity": command.identity.runtime_identity,
        "effective_at": command.effective_at,
        "payload": payload_value(command.payload),
        "precondition": command.expected_previous_event_hash,
    })
