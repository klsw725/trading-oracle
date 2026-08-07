from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum, unique
from typing import Annotated, Literal, override

from pydantic import AwareDatetime, Field

from src.v6.models import BoundaryModel

from .models import HashText

SourcePolicyCode = Literal[
    "PROMOTION_ACCEPTED_GRADUAL", "SOURCE_DISABLED_IMMEDIATELY", "SOURCE_RETIRED",
    "CONTRACT_EXPIRED_SOURCE_RETIRED", "ILLEGAL_PROMOTION_JUMP", "ILLEGAL_TRAFFIC_SHARE",
    "INSUFFICIENT_OBSERVATIONS", "OWNER_APPROVAL_MISSING", "OWNER_REVIEWER_CONFLICT",
    "POLICY_HASH_MISMATCH", "SOURCE_BUNDLE_HASH_MISMATCH", "PRD01_LINEAGE_INVALID",
    "PRD02_LINEAGE_INVALID", "PRD03_LINEAGE_INVALID", "CONTRACT_HASH_MISMATCH",
    "QUALITY_STALE", "QUALITY_DEGRADED", "QUALITY_CONTRADICTORY", "VALUE_NOT_PASS",
    "MISSING_OUTCOME_ADAPTER", "DISABLE_TRAFFIC_NOT_ZERO", "FALLBACK_USES_INELIGIBLE_SOURCE",
    "FALLBACK_ORDER_MISMATCH", "FALLBACK_TIE_BREAK_MISMATCH", "STALE_CACHE_POLICY_MISMATCH",
    "CACHE_POLICY_HASH_MISSING", "INTERRUPTED_TRANSITION_UNSAFE", "AUDIT_SENSITIVE_DATA",
    "AUDIT_HASH_MISSING", "AUDIT_HASH_MISMATCH", "EVENT_CHAIN_SPLICE", "HISTORY_HASH_MISMATCH",
    "DUPLICATE_OPERATION_CONFLICT", "STALE_TRUSTED_REGISTRY", "CLOSED_STATE_REOPEN",
    "RETENTION_DELETION_FORBIDDEN", "PRODUCTION_ISOLATION_VIOLATION",
    "CONTRACT_EXPIRED_SOURCE_ACTIVE", "MALFORMED_SOURCE_POLICY", "OUTPUT_PATH_UNSAFE",
    "TRUSTED_SOURCE_CONTEXT_REQUIRED", "SOURCE_CONTEXT_MISMATCH", "INCIDENT_UNAUTHORIZED",
    "OBSERVATION_CONTEXT_MISMATCH", "LIFECYCLE_REPLAY_MISMATCH", "LICENSE_CURRENT_USE_FORBIDDEN",
    "SOURCE_TRUST_MISMATCH",
]


@dataclass(frozen=True, slots=True)
class SourcePolicyError(ValueError):
    code: SourcePolicyCode
    detail: str

    @override
    def __str__(self) -> str:
        return f"{self.code}: {self.detail}"


@unique
class LifecycleState(StrEnum):
    CANDIDATE = "candidate"
    SHADOW = "shadow"
    CANARY = "canary"
    LIMITED = "limited"
    PRIMARY = "primary"
    DISABLED = "disabled"
    RETIRING = "retiring"
    RETIRED = "retired"
    EXPIRED = "expired"


@unique
class IncidentCode(StrEnum):
    SECRET_LEAKAGE = "secret_leakage"
    PROMPT_INJECTION = "prompt_injection_trusted"
    SEVERE_HARM = "severe_harm_breach"
    CONTRACT_EXPIRED = "contract_expired"
    AUTH_BREACH = "auth_boundary_breach"
    STALE_AS_FRESH = "stale_cache_served_as_fresh"
    OUTAGE = "source_outage_masked_as_success"


@unique
class RetirementReason(StrEnum):
    CONTRACT_EXPIRED = "contract_expired"
    REPLACED = "replaced_by_better_source"
    HARMFUL = "harmful"
    NO_VALUE = "no_incremental_value"
    COVERAGE_LOST = "coverage_lost"
    OWNER_REQUEST = "owner_request"


class OwnerApproval(BoundaryModel):
    accountable_owner: Annotated[str, Field(min_length=1)]
    reviewer: Annotated[str, Field(min_length=1)]
    approved_at: AwareDatetime
    expiry_review_at: AwareDatetime


class ContractMetadata(BoundaryModel):
    contract_ref_hash: HashText
    license_scope: Literal["internal_prompt_eligible_hash_only", "internal_only", "hash_only"]
    valid_from: AwareDatetime
    valid_until: AwareDatetime | None
    expiry_review_at: AwareDatetime


class PromotionObservation(BoundaryModel):
    attempts: Annotated[int, Field(strict=True, ge=0)]
    harm_events: Annotated[int, Field(strict=True, ge=0)] = 0
    timeout_spikes: Annotated[int, Field(strict=True, ge=0)] = 0
    stale_cache_events: Annotated[int, Field(strict=True, ge=0)] = 0


def traffic(value: str) -> Decimal:
    try:
        return Decimal(value)
    except ArithmeticError as error:
        raise SourcePolicyError("ILLEGAL_TRAFFIC_SHARE", value) from error


def contract_expired(contract: ContractMetadata, evaluated_at: datetime) -> bool:
    return contract.valid_until is not None and contract.valid_until <= evaluated_at
