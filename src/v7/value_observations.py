from decimal import Decimal
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field

from src.v4.models import JsonValue, canonical_hash
from src.v6.models import BoundaryModel, JsonBoundary

from .models import HashText
from .value_models import Action, Arm, FactAuditClass, Market


class FactAudit(BoundaryModel):
    audit_class: FactAuditClass
    known_baseline_error: bool
    correction_claimed: bool
    correction_true: bool
    correction_supported: bool
    new_false_fact: bool
    fact_audit_hash: HashText


class OutputArtifact(BoundaryModel):
    schema_version: Literal["v7.incremental_value_evaluation.output.1"]
    sample_id: str
    arm: Arm
    market: Market
    ticker: str
    action: Action
    horizon: Literal[5]
    prompt_bundle: str
    scorer_version: str
    portfolio_hash: HashText
    decision_cutoff: AwareDatetime
    outcome_cutoff: AwareDatetime
    emitted_at: AwareDatetime
    latest_feature_at: AwareDatetime
    confidence: Annotated[Decimal, Field(ge=0, le=1)]
    edge_5: Decimal
    wall_ms: Annotated[int, Field(strict=True, ge=0)]
    prompt_tokens: Annotated[int, Field(strict=True, ge=0)]
    fetches: Annotated[int, Field(strict=True, ge=0)]
    timeout: bool
    source_count: Annotated[int, Field(strict=True, ge=0)]
    source_eligible: bool
    source_fact_visible: bool
    provenance_hash: HashText | None
    provenance_manifest_root: HashText | None
    quality_hash: HashText | None
    quality_registry_root: HashText | None
    output_hash: HashText


class OutcomeAdapterIdentityBody(BoundaryModel):
    schema_version: Literal["v7.incremental_value_evaluation.outcome-adapter.1"]
    adapter_id: Literal["deterministic_matured_edge_5.v1"]
    adapter_version: Literal["1"]
    generated_at: AwareDatetime


class OutcomeAdapterIdentity(OutcomeAdapterIdentityBody):
    body_hash: HashText


class OutcomeArtifact(BoundaryModel):
    schema_version: Literal["v7.incremental_value_evaluation.outcome.1"]
    sample_id: str
    adapter_id: Literal["deterministic_matured_edge_5.v1"]
    adapter_body_hash: HashText
    decision_cutoff: AwareDatetime
    outcome_cutoff: AwareDatetime
    observed_at: AwareDatetime
    instrument_return_5: Decimal
    benchmark_return_5: Decimal
    execution_cost_return: Decimal
    off_correctness_edge_5: Decimal
    on_correctness_edge_5: Decimal
    masked_correctness_edge_5: Decimal
    outcome_hash: HashText


class OutcomeRegistryBody(BoundaryModel):
    schema_version: Literal["v7.incremental_value_evaluation.outcome-registry.1"]
    adapter: OutcomeAdapterIdentity
    outcomes: tuple[OutcomeArtifact, ...]


class OutcomeRegistry(OutcomeRegistryBody):
    registry_root: HashText


class PairedObservation(BoundaryModel):
    sample_id: Annotated[str, Field(pattern=r"^ive_sample_[0-9]{4}$")]
    market: Market
    ticker: str
    action: Action
    horizon: Literal[5]
    prompt_bundle: str
    scorer_version: str
    portfolio_hash: HashText
    decision_cutoff: AwareDatetime
    outcome_cutoff: AwareDatetime
    target_error: bool
    source_provenance_hash: HashText
    source_manifest_root: HashText
    source_quality_hash: HashText
    quality_registry_root: HashText
    off: OutputArtifact
    on: OutputArtifact
    masked: OutputArtifact
    fact_audit: FactAudit
    outcome: OutcomeArtifact
    content_hash: HashText


def _hash_body(value: BoundaryModel, excluded: set[str]) -> str:
    body = JsonBoundary.model_validate(value.model_dump(mode="json", exclude=excluded)).root
    return str(canonical_hash(body))


def fact_audit_hash(value: FactAudit) -> str:
    return _hash_body(value, {"fact_audit_hash"})


def output_hash(value: OutputArtifact) -> str:
    return _hash_body(value, {"output_hash"})


def outcome_hash(value: OutcomeArtifact) -> str:
    return _hash_body(value, {"outcome_hash"})


def outcome_adapter_hash(value: OutcomeAdapterIdentityBody | OutcomeAdapterIdentity) -> str:
    return _hash_body(value, {"body_hash"})


def outcome_registry_root(value: OutcomeRegistry) -> str:
    return _hash_body(value, {"registry_root"})


def observation_hash(value: PairedObservation) -> str:
    identity: JsonValue = {
        "sample_id": value.sample_id, "market": value.market, "ticker": value.ticker,
        "action": value.action, "horizon": value.horizon, "prompt_bundle": value.prompt_bundle,
        "scorer_version": value.scorer_version, "portfolio_hash": value.portfolio_hash,
        "decision_cutoff": value.decision_cutoff.isoformat(), "outcome_cutoff": value.outcome_cutoff.isoformat(),
        "target_error": value.target_error, "source_provenance_hash": value.source_provenance_hash,
        "source_manifest_root": value.source_manifest_root, "source_quality_hash": value.source_quality_hash,
        "quality_registry_root": value.quality_registry_root, "off_output_hash": value.off.output_hash,
        "on_output_hash": value.on.output_hash, "masked_output_hash": value.masked.output_hash,
        "fact_audit_hash": value.fact_audit.fact_audit_hash, "outcome_hash": value.outcome.outcome_hash,
    }
    return str(canonical_hash(identity))
