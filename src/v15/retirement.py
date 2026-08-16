from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from pydantic import Field
from src.v11.canonical import canonical_hash, model_json

from .contract import StrictModel, V15Failure, V15FailureCode


GENESIS = "sha256:" + "0" * 64


class RetirementBody(StrictModel):
    schema_version: Literal["v15.retirement_record.1"]
    sequence: int
    market: Literal["KR", "US"]
    router_version: str
    manifest_hash: str
    retired_session: date
    evidence_hash: str
    previous_hash: str


class RetirementRecord(RetirementBody):
    record_hash: str


class RetirementRegistry(StrictModel):
    schema_version: Literal["v15.retirement_registry.1"]
    records: Annotated[tuple[RetirementRecord, ...], Field(strict=False)]
    tail_hash: str


def empty_registry() -> RetirementRegistry:
    return RetirementRegistry(schema_version="v15.retirement_registry.1",
        records=(), tail_hash=GENESIS)


def append_retirement(
    registry: RetirementRegistry, body: RetirementBody
) -> RetirementRegistry:
    verify_registry(registry)
    if body.sequence != len(registry.records) + 1 \
            or body.previous_hash != registry.tail_hash \
            or any(item.market == body.market
                and item.router_version == body.router_version
                for item in registry.records):
        raise V15Failure(V15FailureCode.VERSION_RETIRED,
            body.router_version)
    record = RetirementRecord(schema_version=body.schema_version,
        sequence=body.sequence, market=body.market,
        router_version=body.router_version, manifest_hash=body.manifest_hash,
        retired_session=body.retired_session,
        evidence_hash=body.evidence_hash, previous_hash=body.previous_hash,
        record_hash=canonical_hash(model_json(body)))
    return RetirementRegistry(schema_version=registry.schema_version,
        records=(*registry.records, record), tail_hash=record.record_hash)


def verify_registry(registry: RetirementRegistry) -> None:
    previous = GENESIS
    seen: set[tuple[str, str]] = set()
    for index, record in enumerate(registry.records, start=1):
        body = RetirementBody.model_validate(record.model_dump(
            exclude={"record_hash"}))
        key = (record.market, record.router_version)
        if record.sequence != index or record.previous_hash != previous \
                or record.record_hash != canonical_hash(model_json(body)) \
                or key in seen:
            raise V15Failure(V15FailureCode.CHAIN_MISMATCH, "retirement")
        seen.add(key)
        previous = record.record_hash
    if registry.tail_hash != previous:
        raise V15Failure(V15FailureCode.CHAIN_MISMATCH, "retirement_tail")


def require_active(
    registry: RetirementRegistry, market: Literal["KR", "US"], version: str
) -> None:
    verify_registry(registry)
    if any(item.market == market and item.router_version == version
            for item in registry.records):
        raise V15Failure(V15FailureCode.VERSION_RETIRED, version)
