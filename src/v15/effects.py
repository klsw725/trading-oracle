from __future__ import annotations

from enum import StrEnum, unique
from typing import Annotated, Literal

from pydantic import Field
from src.v11.canonical import canonical_hash, model_json

from .contract import StrictModel, V15Failure, V15FailureCode


@unique
class EffectKind(StrEnum):
    LOCAL_FIXTURE_READ = "local_fixture_read"
    PAPER_ARTIFACT = "paper_artifact"
    NETWORK = "network"
    PROVIDER = "provider"
    BROKER_SUBMIT = "broker_submit"
    LIVE_ARTIFACT = "live_artifact"
    PORTFOLIO_READ = "portfolio_read"
    PORTFOLIO_WRITE = "portfolio_write"
    CREDENTIAL = "credential"
    RAW_ACCOUNT = "raw_account"


class EffectRecord(StrictModel):
    kind: EffectKind
    target_hash: str


class EffectLedger(StrictModel):
    schema_version: Literal["v15.effect_ledger.1"]
    records: Annotated[tuple[EffectRecord, ...], Field(strict=False)]
    ledger_hash: str


class SideEffectInventory(StrictModel):
    local_fixture_reads: int
    paper_artifacts: int
    network_calls: int
    provider_calls: int
    broker_submits: int
    live_artifacts: int
    portfolio_reads: int
    portfolio_writes: int
    credential_reads: int
    raw_account_reads: int


def build_effect_ledger(records: tuple[EffectRecord, ...]) -> EffectLedger:
    draft = EffectLedger(schema_version="v15.effect_ledger.1",
        records=records, ledger_hash="")
    return draft.model_copy(update={"ledger_hash": canonical_hash(
        model_json(draft.model_copy(update={"ledger_hash": ""})))})


def inventory(ledger: EffectLedger) -> SideEffectInventory:
    counts = {kind: sum(record.kind is kind for record in ledger.records)
        for kind in EffectKind}
    return SideEffectInventory(
        local_fixture_reads=counts[EffectKind.LOCAL_FIXTURE_READ],
        paper_artifacts=counts[EffectKind.PAPER_ARTIFACT],
        network_calls=counts[EffectKind.NETWORK],
        provider_calls=counts[EffectKind.PROVIDER],
        broker_submits=counts[EffectKind.BROKER_SUBMIT],
        live_artifacts=counts[EffectKind.LIVE_ARTIFACT],
        portfolio_reads=counts[EffectKind.PORTFOLIO_READ],
        portfolio_writes=counts[EffectKind.PORTFOLIO_WRITE],
        credential_reads=counts[EffectKind.CREDENTIAL],
        raw_account_reads=counts[EffectKind.RAW_ACCOUNT])


def verify_paper_effects(ledger: EffectLedger) -> SideEffectInventory:
    expected = build_effect_ledger(ledger.records)
    if expected.ledger_hash != ledger.ledger_hash:
        raise V15Failure(V15FailureCode.BUNDLE_MISMATCH, "effect_ledger")
    result = inventory(ledger)
    prohibited = (result.network_calls + result.provider_calls
        + result.broker_submits + result.live_artifacts + result.portfolio_reads
        + result.portfolio_writes + result.credential_reads
        + result.raw_account_reads)
    if prohibited:
        raise V15Failure(V15FailureCode.SIDE_EFFECT, str(prohibited))
    return result
