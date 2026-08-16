from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from pydantic import Field
from src.v11.canonical import canonical_hash, model_json

from .contract import StrictModel, V15Failure, V15FailureCode
from .kill_switch import TriggerKind, classify_trigger
from .liquidation import ExecutionScope, KillExecution
from .states import KillOverlay


class IncidentBody(StrictModel):
    schema_version: Literal["v15.incident.2"]
    trigger: Annotated[TriggerKind, Field(strict=False)]
    overlay: Annotated[KillOverlay, Field(strict=False)]
    scope: ExecutionScope
    session: date
    input_hash: str
    manifest_hash: str
    affected_accounts: Annotated[tuple[str, ...], Field(strict=False)]
    execution_hash: str
    critical_codes: Annotated[tuple[str, ...], Field(strict=False)]


class IncidentRecord(IncidentBody):
    incident_hash: str


def build_incident(
    body: IncidentBody, execution: KillExecution
) -> IncidentRecord:
    if body.overlay is not classify_trigger(body.trigger) \
            or body.scope != execution.scope \
            or body.input_hash != execution.incident_input_hash \
            or body.affected_accounts != execution.scope.affected_accounts \
            or body.execution_hash != execution.execution_hash:
        raise V15Failure(V15FailureCode.UPSTREAM_EVIDENCE, "incident_scope")
    return IncidentRecord(schema_version=body.schema_version,
        trigger=body.trigger, overlay=body.overlay, scope=body.scope,
        session=body.session, input_hash=body.input_hash,
        manifest_hash=body.manifest_hash,
        affected_accounts=body.affected_accounts,
        execution_hash=body.execution_hash,
        critical_codes=body.critical_codes,
        incident_hash=canonical_hash(model_json(body)))


def verify_incident(record: IncidentRecord, execution: KillExecution) -> None:
    body = IncidentBody.model_validate(record.model_dump(exclude={"incident_hash"}))
    if build_incident(body, execution) != record:
        raise V15Failure(V15FailureCode.BUNDLE_MISMATCH, "incident")
