from dataclasses import dataclass
from enum import StrEnum, unique
from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile
from typing import Final, Literal, NewType, overload, override

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]

SnapshotId = NewType("SnapshotId", str)
CandidateId = NewType("CandidateId", str)
RecommendationId = NewType("RecommendationId", str)
AttributionEventId = NewType("AttributionEventId", str)
PortfolioTradeId = NewType("PortfolioTradeId", str)
OrderId = NewType("OrderId", str)
CorrectionId = NewType("CorrectionId", str)
ArtifactId = NewType("ArtifactId", str)
ContentHash = NewType("ContentHash", str)

HASH_PREFIX: Final = "sha256:"
ID_HEX_LENGTH: Final = 20


@unique
class Action(StrEnum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"
    BLOCKED = "BLOCKED"
    CANDIDATE_REJECTED = "CANDIDATE_REJECTED"


@unique
class Market(StrEnum):
    KR = "KR"
    US = "US"


@unique
class QualityState(StrEnum):
    AVAILABLE = "available"
    UNKNOWN = "unknown"
    DEGRADED = "degraded"
    BLOCKED = "blocked"
    NOT_APPLICABLE = "not_applicable"


@unique
class GateState(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    INCONCLUSIVE = "inconclusive"


@unique
class MeasurementState(StrEnum):
    PENDING = "pending"
    MATURED = "matured"
    INSUFFICIENT_DATA = "insufficient_data"
    INSUFFICIENT_CONTEXT = "insufficient_context"


@unique
class ReplayMode(StrEnum):
    VERBATIM = "verbatim"
    OUTCOME = "outcome"
    RECOMPUTE = "recompute"


@unique
class IdPrefix(StrEnum):
    SNAPSHOT = "snap_v4_"
    CANDIDATE = "cand_v4_"
    RECOMMENDATION = "rec_v4_"
    ATTRIBUTION_EVENT = "att_v4_"
    PORTFOLIO_TRADE = "ptrade_v4_"
    ORDER = "order_v4_"
    CORRECTION = "corr_v4_"
    ARTIFACT = "artifact_v4_"


@unique
class ArtifactWriteStatus(StrEnum):
    CREATED = "created"
    UNCHANGED = "unchanged"


@dataclass(frozen=True, slots=True)
class MetricValue:
    state: QualityState
    value: int | float | None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class CanonicalJsonError(Exception):
    detail: str

    @override
    def __str__(self) -> str:
        return f"value cannot be encoded as canonical JSON: {self.detail}"


@dataclass(frozen=True, slots=True)
class ArtifactConflictError(Exception):
    path: Path
    existing_hash: ContentHash
    attempted_hash: ContentHash

    @override
    def __str__(self) -> str:
        return (
            f"immutable artifact conflict at {self.path}: "
            f"existing={self.existing_hash}, attempted={self.attempted_hash}"
        )


def canonical_json(value: JsonValue) -> bytes:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except ValueError as error:
        raise CanonicalJsonError(detail=str(error)) from error
    return encoded.encode("utf-8")


def sha256_bytes(value: bytes) -> ContentHash:
    return ContentHash(f"{HASH_PREFIX}{sha256(value).hexdigest()}")


def canonical_hash(value: JsonValue) -> ContentHash:
    return sha256_bytes(canonical_json(value))


@overload
def deterministic_id(
    prefix: Literal[IdPrefix.SNAPSHOT], seed: JsonValue
) -> SnapshotId: ...


@overload
def deterministic_id(
    prefix: Literal[IdPrefix.CANDIDATE], seed: JsonValue
) -> CandidateId: ...


@overload
def deterministic_id(
    prefix: Literal[IdPrefix.RECOMMENDATION], seed: JsonValue
) -> RecommendationId: ...


@overload
def deterministic_id(
    prefix: Literal[IdPrefix.ATTRIBUTION_EVENT], seed: JsonValue
) -> AttributionEventId: ...


@overload
def deterministic_id(
    prefix: Literal[IdPrefix.PORTFOLIO_TRADE], seed: JsonValue
) -> PortfolioTradeId: ...


@overload
def deterministic_id(
    prefix: Literal[IdPrefix.ORDER], seed: JsonValue
) -> OrderId: ...


@overload
def deterministic_id(
    prefix: Literal[IdPrefix.CORRECTION], seed: JsonValue
) -> CorrectionId: ...


@overload
def deterministic_id(
    prefix: Literal[IdPrefix.ARTIFACT], seed: JsonValue
) -> ArtifactId: ...


def deterministic_id(
    prefix: IdPrefix,
    seed: JsonValue,
) -> str:
    digest = sha256(canonical_json(seed)).hexdigest()
    return f"{prefix}{digest[:ID_HEX_LENGTH]}"


def _existing_write_status(path: Path, payload: bytes) -> ArtifactWriteStatus:
    existing = path.read_bytes()
    if existing == payload:
        return ArtifactWriteStatus.UNCHANGED
    raise ArtifactConflictError(
        path=path,
        existing_hash=sha256_bytes(existing),
        attempted_hash=sha256_bytes(payload),
    )


def write_immutable_json(path: Path, value: JsonValue) -> ArtifactWriteStatus:
    payload = canonical_json(value) + b"\n"
    if path.exists():
        return _existing_write_status(path, payload)

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            _ = stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary_path, path)
        except FileExistsError:
            return _existing_write_status(path, payload)
        return ArtifactWriteStatus.CREATED
    finally:
        temporary_path.unlink(missing_ok=True)
