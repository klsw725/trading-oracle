from typing import Literal

from .lifecycle_registry import PolicyVersionRegistry
from .lifecycle_retirement import HypothesisFalsificationArtifact, SourceAvailabilityArtifact
from .models import BoundaryModel


type TrustedRetirementEvidence = SourceAvailabilityArtifact | HypothesisFalsificationArtifact


class CompilerContext(BoundaryModel):
    schema_version: Literal["v6.consensus_lifecycle.compiler-context.1"]
    policy_registry: PolicyVersionRegistry
    retirement_evidence: tuple[TrustedRetirementEvidence, ...] = ()
