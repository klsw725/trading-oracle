from dataclasses import dataclass
from enum import StrEnum, unique
from typing import Final, NewType, TypedDict, override

from pydantic import StrictInt, StrictStr, TypeAdapter, ValidationError

from src.v4.models import JsonValue


CanonicalNodeId = NewType("CanonicalNodeId", str)


@unique
class Relation(StrEnum):
    INCREASES = "increases"
    DECREASES = "decreases"
    CAUSES = "causes"
    ENABLES = "enables"
    BLOCKS = "blocks"


@unique
class DirectionKind(StrEnum):
    LEVEL_CHANGE = "level_change"
    FLOW_CHANGE = "flow_change"
    EVENT = "event"
    STATE = "state"
    ENTITY = "entity"
    UNKNOWN = "unknown"


@unique
class Polarity(StrEnum):
    UP = "up"
    DOWN = "down"
    NEUTRAL = "neutral"
    MIXED = "mixed"
    UNKNOWN = "unknown"


@unique
class LegacyField(StrEnum):
    SUBJECT = "subject"
    OBJECT = "object"


class LegacyMetadataJson(TypedDict):
    created_at: StrictStr | None
    updated_at: StrictStr
    num_topics: StrictInt
    num_triples: StrictInt
    llm_model: StrictStr


class LegacyTripleJson(TypedDict):
    subject: str
    relation: Relation
    object: str
    domain: str


_METADATA: Final[TypeAdapter[LegacyMetadataJson]] = TypeAdapter(LegacyMetadataJson)
_TRIPLE: Final[TypeAdapter[LegacyTripleJson]] = TypeAdapter(LegacyTripleJson)


@dataclass(frozen=True, slots=True)
class LegacyMetadata:
    created_at: str | None
    updated_at: str
    num_topics: int
    num_triples: int
    llm_model: str


@dataclass(frozen=True, slots=True)
class LegacyTriple:
    subject: str
    relation: Relation
    object: str
    domain: str


@dataclass(frozen=True, slots=True)
class LegacyGraphParseError(Exception):
    field: str
    reason: str

    @override
    def __str__(self) -> str:
        return f"legacy causal graph {self.field}: {self.reason}"


@dataclass(frozen=True, slots=True)
class MalformedTriple:
    legacy_triple_index: int
    reason: str
    value: JsonValue

    def to_json(self) -> JsonValue:
        return {
            "legacy_triple_index": self.legacy_triple_index,
            "reason": self.reason,
            "value": self.value,
        }


@dataclass(frozen=True, slots=True)
class ParsedLegacyGraph:
    metadata: LegacyMetadata
    triples: tuple[tuple[int, LegacyTriple], ...]
    malformed_triples: tuple[MalformedTriple, ...]


@dataclass(frozen=True, slots=True)
class NodeDirection:
    kind: DirectionKind
    polarity: Polarity

    def to_json(self) -> JsonValue:
        return {"kind": self.kind.value, "polarity": self.polarity.value}


@dataclass(frozen=True, slots=True)
class AliasRecord:
    alias: str
    normalized_alias: str

    def to_json(self) -> JsonValue:
        return {
            "alias": self.alias,
            "normalized_alias": self.normalized_alias,
            "source": "legacy_triple",
            "merge_status": "merged",
        }


@dataclass(frozen=True, slots=True)
class SourceRecord:
    legacy_field: LegacyField
    legacy_text: str
    legacy_triple_index: int

    def to_json(self) -> JsonValue:
        return {
            "legacy_field": self.legacy_field.value,
            "legacy_text": self.legacy_text,
            "legacy_triple_index": self.legacy_triple_index,
        }


@dataclass(frozen=True, slots=True)
class NodeCandidate:
    canonical_label: str
    normalized_label: str
    concept_key: str
    direction: NodeDirection
    domain: str
    alias: AliasRecord
    source: SourceRecord


@dataclass(frozen=True, slots=True)
class CanonicalNode:
    canonical_node_id: CanonicalNodeId
    canonical_label: str
    normalized_label: str
    direction: NodeDirection
    owner_domain: str
    secondary_domains: tuple[str, ...]
    aliases: tuple[AliasRecord, ...]
    created_from: tuple[SourceRecord, ...]

    def to_json(self) -> JsonValue:
        return {
            "canonical_node_id": self.canonical_node_id,
            "canonical_label": self.canonical_label,
            "normalized_label": self.normalized_label,
            "direction": self.direction.to_json(),
            "owner_domain": self.owner_domain,
            "secondary_domains": list(self.secondary_domains),
            "aliases": [alias.to_json() for alias in self.aliases],
            "created_from": [source.to_json() for source in self.created_from],
        }


def parse_legacy_graph(value: JsonValue) -> ParsedLegacyGraph:
    if not isinstance(value, dict):
        raise LegacyGraphParseError("root", "expected object")
    if "schema_version" in value:
        raise LegacyGraphParseError("schema_version", "expected absent legacy schema version")
    try:
        parsed_metadata = _METADATA.validate_python(value.get("metadata"))
    except ValidationError as error:
        raise LegacyGraphParseError("metadata", str(error)) from error
    metadata = LegacyMetadata(**parsed_metadata)

    raw_triples = value.get("triples")
    if not isinstance(raw_triples, list):
        raise LegacyGraphParseError("triples", "expected array")
    triples: list[tuple[int, LegacyTriple]] = []
    malformed: list[MalformedTriple] = []
    for index, raw in enumerate(raw_triples):
        try:
            parsed_triple = _TRIPLE.validate_python(raw)
        except ValidationError as error:
            malformed.append(MalformedTriple(index, str(error), raw))
            continue
        triple = LegacyTriple(**parsed_triple)
        triples.append((index, triple))
    return ParsedLegacyGraph(metadata, tuple(triples), tuple(malformed))
