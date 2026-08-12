from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import ValidationError

from src.v4.models import JsonValue
from src.v10.canonical import model_json, seal_meta
from src.v10.models import (
    DataIncident,
    Market,
    SourceObservation,
    StrictModel,
    Symbol,
    V10ContractError,
)


class SourceAttempt(StrictModel):
    market: Market
    symbol: Symbol
    role: Literal["primary", "secondary"]
    source_identity: str
    adapter_version: str
    fetched_at: datetime
    observed_at: datetime
    source_timestamp: datetime
    success: bool
    raw_payload_hash: str | None
    failure_code: str | None
    capabilities_verified: bool


class SourceFixture(StrictModel):
    attempts: tuple[SourceAttempt, ...]
    expected_selected_role: Literal["primary", "secondary"]


def build_sources(value: JsonValue) -> tuple[tuple[SourceObservation, ...], tuple[DataIncident, ...]]:
    try:
        fixture = SourceFixture.model_validate(value)
    except ValidationError as error:
        raise V10ContractError("V10_SOURCE_PROVENANCE_MISMATCH", str(error)) from error
    primary = next((item for item in fixture.attempts if item.role == "primary"), None)
    secondary = next((item for item in fixture.attempts if item.role == "secondary"), None)
    if primary is None:
        raise V10ContractError("V10_SOURCE_PROVENANCE_MISMATCH", "primary missing")
    selected = primary if primary.success else secondary
    if selected is None or not selected.success:
        raise V10ContractError("V10_SOURCE_PROVENANCE_MISMATCH", "no successful source")
    if selected.role != fixture.expected_selected_role:
        raise V10ContractError("V10_SOURCE_PROVENANCE_MISMATCH", "hidden fallback")
    if selected.role == "secondary" and (
        primary.failure_code is None or not selected.capabilities_verified
    ):
        raise V10ContractError("V10_SOURCE_PROVENANCE_MISMATCH", "unverified fallback")
    observations = tuple(_observation(item, item is selected) for item in fixture.attempts)
    incidents: tuple[DataIncident, ...] = ()
    if selected.role == "secondary":
        body: JsonValue = {
            "code": "source_fallback",
            "market": selected.market.value,
            "symbol": selected.symbol,
            "detected_at": selected.observed_at.isoformat(),
            "disposition": "degraded",
            "affected_refs": [],
        }
        incidents = (
            DataIncident(
                meta=seal_meta("data_incident", body),
                code="source_fallback",
                market=selected.market,
                symbol=selected.symbol,
                detected_at=selected.observed_at,
                disposition="degraded",
                affected_refs=(),
            ),
        )
    return observations, incidents


def _observation(attempt: SourceAttempt, selected: bool) -> SourceObservation:
    outcome = (
        "accepted_fallback"
        if selected and attempt.role == "secondary"
        else "success"
        if attempt.success
        else "failure"
    )
    attempt_json = model_json(attempt)
    if not isinstance(attempt_json, dict):
        raise V10ContractError("V10_SOURCE_PROVENANCE_MISMATCH", "attempt shape")
    body: dict[str, JsonValue] = {
        **attempt_json,
        "outcome": outcome,
        "selected": selected,
    }
    _ = body.pop("success")
    return SourceObservation(
        meta=seal_meta("source_observation", body),
        market=attempt.market,
        symbol=attempt.symbol,
        role=attempt.role,
        source_identity=attempt.source_identity,
        adapter_version=attempt.adapter_version,
        fetched_at=attempt.fetched_at,
        observed_at=attempt.observed_at,
        source_timestamp=attempt.source_timestamp,
        outcome=outcome,
        selected=selected,
        raw_payload_hash=attempt.raw_payload_hash,
        failure_code=attempt.failure_code,
        capabilities_verified=attempt.capabilities_verified,
    )
