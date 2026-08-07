from typing import Literal, Self

from pydantic import Field, model_validator

from src.v4.models import JsonValue, canonical_hash

from .models import BoundaryModel, ContractInvariantError, JsonBoundary
from .paper_evaluator import evaluate_paper
from .paper_ledger import validate_ledger
from .paper_models import LedgerEvent, LedgerEventType, PaperCohortInput, PaperDecision, ProductionSnapshot


class PaperArtifactBody(BoundaryModel):
    schema_version: Literal["v6.paper-cohort-artifact.1"]
    generated_at: str
    paper_input_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    paper_input: PaperCohortInput
    production_before_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    production_after_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    ledger: tuple[LedgerEvent, ...]
    ledger_head_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    decision: PaperDecision
    production_isolation: Literal["shadow_only_no_production_mutation"]
    prd04_handoff: Literal["evidence_only_not_production_adoption"]


def boundary_json(value: BoundaryModel) -> JsonValue:
    return JsonBoundary.model_validate(value.model_dump(mode="json")).root


def snapshot_hash(snapshot: ProductionSnapshot) -> str:
    return canonical_hash(boundary_json(snapshot))


class PaperCohortArtifact(PaperArtifactBody):
    artifact_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")

    @model_validator(mode="after")
    def verified_integrity(self) -> Self:
        validate_ledger(self.paper_input, self.ledger)
        if not self.ledger or self.ledger[-1].event_type is not LedgerEventType.STOPPED:
            raise ContractInvariantError("paper artifact ledger must end with stopped event")
        if self.paper_input_hash != canonical_hash(boundary_json(self.paper_input)):
            raise ContractInvariantError("paper input hash mismatch")
        isolation = self.paper_input.isolation
        if self.production_before_hash != snapshot_hash(isolation.production_before) or self.production_after_hash != snapshot_hash(isolation.production_after):
            raise ContractInvariantError("production snapshot hash mismatch")
        if self.ledger_head_hash != self.ledger[-1].event_hash:
            raise ContractInvariantError("ledger head hash mismatch")
        expected = evaluate_paper(self.paper_input)
        if self.decision != expected or self.paper_input.reported_stop_code is not expected.stop_code:
            raise ContractInvariantError("paper decision forgery")
        body = PaperArtifactBody.model_validate(self.model_dump(mode="json", exclude={"artifact_hash"}))
        if self.artifact_hash != canonical_hash(boundary_json(body)):
            raise ContractInvariantError("paper artifact hash mismatch")
        return self


def build_paper_artifact(value: PaperCohortInput, ledger: tuple[LedgerEvent, ...]) -> PaperCohortArtifact:
    validate_ledger(value, ledger)
    decision = evaluate_paper(value)
    if value.reported_stop_code is not decision.stop_code:
        raise ContractInvariantError("reported paper decision differs from derived decision")
    isolation = value.isolation
    body = PaperArtifactBody(
        schema_version="v6.paper-cohort-artifact.1",
        generated_at=value.generated_at,
        paper_input_hash=canonical_hash(boundary_json(value)),
        paper_input=value,
        production_before_hash=snapshot_hash(isolation.production_before),
        production_after_hash=snapshot_hash(isolation.production_after),
        ledger=ledger,
        ledger_head_hash=ledger[-1].event_hash,
        decision=decision,
        production_isolation="shadow_only_no_production_mutation",
        prd04_handoff="evidence_only_not_production_adoption",
    )
    return PaperCohortArtifact.model_validate({**body.model_dump(mode="json"), "artifact_hash": canonical_hash(boundary_json(body))})


def paper_artifact_json(artifact: PaperCohortArtifact) -> JsonValue:
    return boundary_json(artifact)
