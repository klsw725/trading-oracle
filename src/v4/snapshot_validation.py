from dataclasses import dataclass
from datetime import datetime
import re
from typing import Final, override

from src.v4.models import Action, JsonValue, Market

_CONTENT_HASH_PATTERN: Final = re.compile(r"sha256:[0-9a-f]{64}")


@dataclass(frozen=True, slots=True)
class MarketContextContract:
    market: Market
    benchmark: str
    calendar: str
    timezone: str
    quote_currency: str
    regime_source: str
    fx_pair: str


MARKET_CONTEXT_CONTRACTS: Final = {
    "KOSPI": MarketContextContract(Market.KR, "KS11", "KRX", "Asia/Seoul", "KRW", "KS11", "KRW_KRW"),
    "KOSDAQ": MarketContextContract(Market.KR, "KQ11", "KRX", "Asia/Seoul", "KRW", "KQ11", "KRW_KRW"),
    "KOSDAQ GLOBAL": MarketContextContract(Market.KR, "KQ11", "KRX", "Asia/Seoul", "KRW", "KQ11", "KRW_KRW"),
    "NASDAQ": MarketContextContract(Market.US, "IXIC", "NASDAQ", "America/New_York", "USD", "IXIC", "USD_KRW"),
    "NYSE": MarketContextContract(Market.US, "US500", "NYSE", "America/New_York", "USD", "US500", "USD_KRW"),
}


@dataclass(frozen=True, slots=True)
class RequestScope:
    market_scope: str
    tickers_requested: tuple[str, ...]
    top_n: int | None
    operator_request_id: str | None = None


@dataclass(frozen=True, slots=True)
class ContractRefs:
    measurement_contract: str
    market_context_contract: str


@dataclass(frozen=True, slots=True)
class RetentionPolicy:
    policy_version: str
    raw_llm_text_days: int
    market_payload_retention: str


@dataclass(frozen=True, slots=True)
class RecommendationIdentityInput:
    ticker: str
    name: str
    market: Market
    exchange: str
    action: Action
    decision_at: str
    emitted_at: str
    data_cutoff_at: str


@dataclass(frozen=True, slots=True)
class LlmProvenance:
    provider_adapter_version: str
    provider: str | None
    model: str | None
    provider_request_id: str | None
    prompt_bundle_version: str
    prompt_messages: JsonValue
    config_version: str
    config: JsonValue
    parser_version: str
    raw_results: JsonValue
    parsed_results: JsonValue


@dataclass(frozen=True, slots=True)
class RecommendationProvenance:
    market_context: JsonValue
    sources: JsonValue
    candidate_universe: JsonValue
    selection: JsonValue
    rejections: JsonValue
    features: JsonValue
    signals: JsonValue
    llm: LlmProvenance
    consensus: JsonValue
    deliberation: JsonValue
    portfolio_state: JsonValue
    risk_state: JsonValue
    quality_states: JsonValue


@dataclass(frozen=True, slots=True)
class RecommendationInput:
    identity: RecommendationIdentityInput
    provenance: RecommendationProvenance


@dataclass(frozen=True, slots=True)
class SnapshotInput:
    created_at: str
    decision_at: str
    recommendation_emitted_at: str
    decision_data_cutoff_at: str
    request_scope: RequestScope
    contract_refs: ContractRefs
    retention_policy: RetentionPolicy
    recommendations: tuple[RecommendationInput, ...]


@dataclass(frozen=True, slots=True)
class CandidateIdentityEvidence:
    universe_id: str
    selection_stage: str
    rank_seed_hash: str


@dataclass(frozen=True, slots=True)
class SnapshotValidationError(ValueError):
    path: str
    detail: str

    @override
    def __str__(self) -> str:
        return f"invalid snapshot input at {self.path}: {self.detail}"


def context_record(value: JsonValue, path: str) -> dict[str, JsonValue]:
    match value:  # noqa: MATCH_OK - generic validation already requires an object.
        case dict() as context:
            return context
        case _:
            raise SnapshotValidationError(path, "must be a JSON object")


def _timestamp(path: str, value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise SnapshotValidationError(path, "must be an ISO 8601 timestamp") from error
    if parsed.utcoffset() is None:
        raise SnapshotValidationError(path, "must include a timezone offset")
    return parsed


def _require_record(
    value: JsonValue,
    path: str,
    required: tuple[str, ...],
) -> dict[str, JsonValue]:
    match value:  # noqa: MATCH_OK - all JsonValue variants return or raise.
        case dict() as record:
            missing = tuple(field for field in required if field not in record)
            if missing:
                raise SnapshotValidationError(
                    path, f"missing required fields: {', '.join(missing)}"
                )
            return record
        case None | str() | bool() | int() | float() | list():
            raise SnapshotValidationError(path, "must be a JSON object")


def _required_text(record: dict[str, JsonValue], key: str, path: str) -> str:
    match record[key]:  # noqa: MATCH_OK - wildcard rejects non-text boundary values.
        case str() as value if value:
            return value
        case _:
            raise SnapshotValidationError(f"{path}.{key}", "must be non-empty text")


def _validate_value(value: JsonValue, path: str, hashes: bool = False) -> None:
    match value:  # noqa: MATCH_OK - basedpyright proves JsonValue is exhaustive.
        case dict() as record:
            for key, item in record.items():
                item_path = f"{path}.{key}"
                if hashes or key.endswith("_hash"):
                    match item:  # noqa: MATCH_OK - wildcard rejects malformed hashes.
                        case str() if _CONTENT_HASH_PATTERN.fullmatch(item) is not None:
                            pass
                        case _:
                            raise SnapshotValidationError(
                                item_path, "must be sha256:<64 lowercase hex>"
                            )
                if key.endswith("_at") and item is not None:
                    match item:  # noqa: MATCH_OK - wildcard rejects malformed timestamps.
                        case str():
                            _ = _timestamp(item_path, item)
                        case _:
                            raise SnapshotValidationError(
                                item_path, "must be an ISO 8601 timestamp or null"
                            )
                _validate_value(item, item_path, key.endswith("_hashes"))
        case list() as items:
            for index, item in enumerate(items):
                _validate_value(item, f"{path}[{index}]", hashes)
        case None | str() | bool() | int() | float():
            return


def _validate_recommendation(
    recommendation: RecommendationInput,
    index: int,
) -> CandidateIdentityEvidence:
    root = f"recommendations[{index}]"
    identity = recommendation.identity
    cutoff = _timestamp(f"{root}.data_cutoff_at", identity.data_cutoff_at)
    decision = _timestamp(f"{root}.decision_at", identity.decision_at)
    emitted = _timestamp(f"{root}.emitted_at", identity.emitted_at)
    if not cutoff <= decision <= emitted:
        raise SnapshotValidationError(
            f"{root}.timestamps", "must satisfy cutoff <= decision <= emitted"
        )
    provenance = recommendation.provenance
    context_fields = (
        "schema_version", "market", "exchange", "calendar_id", "timezone",
        "quote_currency", "base_reporting_currency", "benchmark_id",
        "benchmark_source", "benchmark_as_of", "decision_data_cutoff_at",
        "target_session_close_at", "decision_regime", "decision_regime_source",
        "analysis_regime", "fx_pair", "fx_rate", "fx_as_of",
        "fx_freshness_state", "blocked_fields", "degraded_fields",
        "provenance_hashes", "context_state",
    )
    context = _require_record(provenance.market_context, f"{root}.market_context", context_fields)
    _ = _require_record(
        context["provenance_hashes"],
        f"{root}.market_context.provenance_hashes",
        ("benchmark", "calendar", "fx"),
    )
    universe = _require_record(
        provenance.candidate_universe,
        f"{root}.candidate_universe",
        ("universe_id", "market_scope", "source", "adapter_version", "total_seen", "members_hash"),
    )
    selection = _require_record(
        provenance.selection,
        f"{root}.selection",
        ("selection_stage", "rank_seed_hash"),
    )
    match provenance.sources:  # noqa: MATCH_OK - empty and non-list values reject.
        case list() as sources if sources:
            for source_index, source in enumerate(sources):
                _ = _require_record(
                    source,
                    f"{root}.sources[{source_index}]",
                    ("source_id", "adapter_version", "record_type", "as_of", "fetched_at", "freshness_state", "provenance_hash", "raw_retention"),
                )
        case _:
            raise SnapshotValidationError(
                f"{root}.sources", "must contain at least one source object"
            )
    for field, value in (
        ("market_context", context), ("sources", provenance.sources),
        ("candidate_universe", universe), ("selection", selection),
        ("rejections", provenance.rejections), ("features", provenance.features),
        ("signals", provenance.signals), ("prompt_messages", provenance.llm.prompt_messages),
        ("config", provenance.llm.config), ("raw_results", provenance.llm.raw_results),
        ("parsed_results", provenance.llm.parsed_results), ("consensus", provenance.consensus),
        ("deliberation", provenance.deliberation), ("portfolio_state", provenance.portfolio_state),
        ("risk_state", provenance.risk_state), ("quality_states", provenance.quality_states),
    ):
        _validate_value(value, f"{root}.{field}")
    return CandidateIdentityEvidence(
        _required_text(universe, "universe_id", f"{root}.candidate_universe"),
        _required_text(selection, "selection_stage", f"{root}.selection"),
        _required_text(selection, "rank_seed_hash", f"{root}.selection"),
    )


def validate_snapshot(snapshot: SnapshotInput) -> tuple[CandidateIdentityEvidence, ...]:
    cutoff = _timestamp("decision_data_cutoff_at", snapshot.decision_data_cutoff_at)
    decision = _timestamp("decision_at", snapshot.decision_at)
    emitted = _timestamp("recommendation_emitted_at", snapshot.recommendation_emitted_at)
    created = _timestamp("created_at", snapshot.created_at)
    if not cutoff <= decision <= emitted <= created:
        raise SnapshotValidationError(
            "timestamps", "must satisfy cutoff <= decision <= emitted <= created"
        )
    return tuple(
        _validate_recommendation(recommendation, index)
        for index, recommendation in enumerate(snapshot.recommendations)
    )
