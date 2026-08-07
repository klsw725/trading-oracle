from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_EVEN
from enum import StrEnum, unique
from typing import NewType, override

from src.v4.models import JsonValue

from .statistical_math import GrangerEvidence, WindowEvidence


PairId = NewType("PairId", str)


@unique
class Status(StrEnum):
    VERIFIED = "verified_stable"
    IN_SAMPLE = "rejected_in_sample_only"
    DIRECTION = "rejected_direction_mismatch"
    MULTIPLE = "rejected_multiple_testing"
    BREAK = "rejected_structural_break"
    LEAKAGE = "rejected_leakage"
    P_HACKING = "rejected_p_hacking"
    FLAKY = "rejected_flaky"
    MALFORMED = "rejected_malformed"
    INCONCLUSIVE = "inconclusive"


@dataclass(frozen=True, slots=True)
class VerificationInputError(Exception):
    detail: str

    @override
    def __str__(self) -> str:
        return f"statistical verification input: {self.detail}"


@dataclass(frozen=True, slots=True)
class PairContext:
    pair_id: PairId
    subject_node_id: str
    object_node_id: str
    subject_label: str
    object_label: str
    relation: str
    subject_mapping_hash: str
    object_mapping_hash: str
    subject_series_id: str
    object_series_id: str
    mapping_expires_at: str
    verification_expires_at: str
    verification_cutoff: str
    declared_lag_grid: tuple[int, ...]
    input_fingerprint: str


@dataclass(frozen=True, slots=True)
class TestedPair:
    context: PairContext
    selected: GrangerEvidence
    holdout: GrangerEvidence
    subject_diff_order: int
    object_diff_order: int
    subject_adf_p: float
    object_adf_p: float
    lag_table: tuple[GrangerEvidence, ...]
    windows: tuple[WindowEvidence, ...]
    reversal: bool
    structural_break: bool
    inconclusive_windows: int


def decimal_text(value: float | Decimal, places: int) -> str:
    decimal = value if isinstance(value, Decimal) else Decimal(str(value))
    quantum = Decimal(1).scaleb(-places)
    return format(decimal.quantize(quantum, rounding=ROUND_HALF_EVEN), f".{places}f")


def evidence_json(evidence: GrangerEvidence) -> dict[str, JsonValue]:
    return {
        "p_value": decimal_text(evidence.p_value, 6),
        "f_stat": decimal_text(evidence.f_stat, 4),
        "direction_match": evidence.direction_match,
        "rows": evidence.rows,
    }
