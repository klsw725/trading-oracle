from typing import Annotated, Literal

from pydantic import AwareDatetime, Field

from src.v6.models import BoundaryModel

from .models import HashText
from .quality_registry_models import QualityTrustExpectation, QualityTrustFixture
from .value_models import CohortManifest, SourceBinding
from .value_observations import OutcomeRegistry, PairedObservation


class ValueTrustDocument(BoundaryModel):
    schema_version: Literal["v7.incremental_value_evaluation.trust.1"]
    contract_id: Literal["incremental_value_evaluation_prd03"]
    expected_cohort_root: HashText
    expected_outcome_root: HashText | None
    expected_provenance_manifest_root: HashText
    expected_quality_artifact_hash: HashText
    quality: QualityTrustExpectation


class ValueFixture(BoundaryModel):
    schema_version: Literal["v7.incremental_value_evaluation.prd03.2"]
    contract_id: Literal["incremental_value_evaluation_prd03"]
    report_id: Annotated[str, Field(min_length=1)]
    source_bundle_id: Annotated[str, Field(min_length=1)]
    generated_at: AwareDatetime
    source_binding: SourceBinding
    cohort_manifest: CohortManifest
    outcome_registry: OutcomeRegistry | None
    observations: tuple[PairedObservation, ...]
    quality_evidence: QualityTrustFixture
