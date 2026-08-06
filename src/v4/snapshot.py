from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Final

from src.v4.models import ArtifactWriteStatus, IdPrefix, JsonValue
from src.v4.models import RecommendationId, SnapshotId, canonical_hash
from src.v4.models import deterministic_id, write_immutable_json
from .snapshot_redaction import prepare_recommendation, redact
from .snapshot_validation import MARKET_CONTEXT_CONTRACTS, context_record
from .snapshot_validation import ContractRefs as ContractRefs
from .snapshot_validation import LlmProvenance as LlmProvenance
from .snapshot_validation import RecommendationIdentityInput as RecommendationIdentityInput
from .snapshot_validation import RecommendationInput as RecommendationInput
from .snapshot_validation import RecommendationProvenance as RecommendationProvenance
from .snapshot_validation import RequestScope as RequestScope
from .snapshot_validation import RetentionPolicy as RetentionPolicy
from .snapshot_validation import SnapshotInput, validate_snapshot
from .snapshot_validation import SnapshotValidationError as SnapshotValidationError

SCHEMA_VERSION: Final = "v4.snapshot.phase23.1"
REDACTION_VERSION: Final = "v4.redaction.phase23.1"


@dataclass(frozen=True, slots=True)
class SnapshotDocument:
    snapshot_id: SnapshotId
    value: dict[str, JsonValue]


def _json_strings(values: Iterable[str]) -> list[JsonValue]:
    return [value for value in values]


def _require_degradation(
    context: dict[str, JsonValue],
    quality_states: JsonValue,
    root: str,
    field: str,
) -> None:
    state = context["context_state"]
    list_key = "degraded_fields" if state == "degraded" else "blocked_fields"
    if state not in {"degraded", "blocked"}:
        raise SnapshotValidationError(f"{root}.context_state", f"must be degraded or blocked when {field} is unavailable")
    match context[list_key]:  # noqa: MATCH_OK - wildcard rejects missing impact names.
        case list() as affected if affected:
            pass
        case _:
            raise SnapshotValidationError(f"{root}.{list_key}", f"must name fields affected by {field}")
    if field != "fx_as_of":
        return
    match quality_states:  # noqa: MATCH_OK - wildcard rejects missing quality evidence.
        case list() as states:
            for item in states:
                match item:  # noqa: MATCH_OK - wildcard skips unrelated quality entries.
                    case {"field": str() as quality_field, "state": str() as quality_state} if quality_field.startswith("market_context.fx") and quality_state == state:
                        return
                    case _:
                        continue
        case _:
            pass
    raise SnapshotValidationError(f"{root}.quality_states", f"must include market_context.fx with state {state}")


def _validate_market_semantics(recommendation: RecommendationInput, index: int) -> None:
    identity = recommendation.identity
    root = f"recommendations[{index}].market_context"
    context = context_record(recommendation.provenance.market_context, root)
    contract = MARKET_CONTEXT_CONTRACTS.get(identity.exchange)
    if contract is None:
        raise SnapshotValidationError(f"{root}.exchange", "unsupported exchange")
    expected: tuple[tuple[str, JsonValue], ...] = (
        ("market", contract.market), ("exchange", identity.exchange),
        ("benchmark_id", contract.benchmark), ("calendar_id", contract.calendar),
        ("timezone", contract.timezone), ("quote_currency", contract.quote_currency),
        ("base_reporting_currency", "KRW"), ("decision_regime_source", contract.regime_source),
        ("fx_pair", contract.fx_pair),
    )
    if identity.market is not contract.market:
        raise SnapshotValidationError(f"{root}.market", f"{identity.exchange} requires {contract.market}")
    for field, value in expected:
        if context[field] != value:
            raise SnapshotValidationError(f"{root}.{field}", f"must equal {value}")
    cutoff = datetime.fromisoformat(identity.data_cutoff_at)
    if context["decision_data_cutoff_at"] != identity.data_cutoff_at:
        raise SnapshotValidationError(f"{root}.decision_data_cutoff_at", "must equal recommendation data_cutoff_at")
    benchmark_as_of = context["benchmark_as_of"]
    match benchmark_as_of:  # noqa: MATCH_OK - wildcard rejects invalid boundary values.
        case str() if datetime.fromisoformat(benchmark_as_of) <= cutoff:
            pass
        case None:
            _require_degradation(context, recommendation.provenance.quality_states, root, "benchmark_as_of")
        case str():
            raise SnapshotValidationError(f"{root}.benchmark_as_of", "must not exceed decision data cutoff")
        case _:
            raise SnapshotValidationError(f"{root}.benchmark_as_of", "must be a timestamp or null")
    fx_as_of = context["fx_as_of"]
    freshness = context["fx_freshness_state"]
    match fx_as_of:  # noqa: MATCH_OK - wildcard rejects invalid boundary values.
        case str() if datetime.fromisoformat(fx_as_of) <= cutoff:
            if freshness not in {"fresh", "stale"}:
                raise SnapshotValidationError(f"{root}.fx_freshness_state", "must be fresh or stale when fx_as_of exists")
            match context["fx_rate"]:  # noqa: MATCH_OK - non-numeric variants reject.
                case bool() | None | str() | list() | dict():
                    raise SnapshotValidationError(f"{root}.fx_rate", "must be numeric when fx_as_of exists")
                case int() | float():
                    pass
            if freshness == "stale":
                _require_degradation(context, recommendation.provenance.quality_states, root, "fx_as_of")
        case None:
            if freshness != "missing":
                raise SnapshotValidationError(f"{root}.fx_freshness_state", "must be missing when fx_as_of is null")
            if context["fx_rate"] is not None:
                raise SnapshotValidationError(f"{root}.fx_rate", "must be null when fx_as_of is null")
            _require_degradation(context, recommendation.provenance.quality_states, root, "fx_as_of")
        case str():
            raise SnapshotValidationError(f"{root}.fx_as_of", "must not exceed decision data cutoff")
        case _:
            raise SnapshotValidationError(f"{root}.fx_as_of", "must be a timestamp or null")
    match recommendation.provenance.sources:  # noqa: MATCH_OK - shape was validated earlier.
        case list() as sources:
            for source_index, source in enumerate(sources):
                match source:  # noqa: MATCH_OK - wildcard rejects inconsistent freshness.
                    case {"as_of": str() as as_of, "freshness_state": str() as source_state}:
                        if datetime.fromisoformat(as_of) > cutoff:
                            raise SnapshotValidationError(f"recommendations[{index}].sources[{source_index}].as_of", "must not exceed decision data cutoff")
                        if source_state not in {"fresh", "stale"}:
                            raise SnapshotValidationError(f"recommendations[{index}].sources[{source_index}].freshness_state", "must be fresh or stale when as_of exists")
                        if source_state == "stale":
                            _require_degradation(context, recommendation.provenance.quality_states, root, f"sources[{source_index}]")
                    case {"as_of": None, "freshness_state": "missing"}:
                        _require_degradation(context, recommendation.provenance.quality_states, root, f"sources[{source_index}]")
                    case {"as_of": None, "freshness_state": "not_applicable"}:
                        pass
                    case _:
                        raise SnapshotValidationError(f"recommendations[{index}].sources[{source_index}]", "as_of and freshness_state are inconsistent")
        case _:
            raise SnapshotValidationError(f"recommendations[{index}].sources", "must be a JSON array")


def build_snapshot(snapshot: SnapshotInput) -> SnapshotDocument:
    evidence = validate_snapshot(snapshot)
    for index, recommendation in enumerate(snapshot.recommendations):
        if (recommendation.identity.decision_at, recommendation.identity.emitted_at, recommendation.identity.data_cutoff_at) != (snapshot.decision_at, snapshot.recommendation_emitted_at, snapshot.decision_data_cutoff_at):
            raise SnapshotValidationError(f"recommendations[{index}].timestamps", "must equal snapshot decision, emitted, and cutoff timestamps")
        _validate_market_semantics(recommendation, index)
    events: list[JsonValue] = []
    request_scope: dict[str, JsonValue] = {
        "market_scope": snapshot.request_scope.market_scope,
        "tickers_requested": list(snapshot.request_scope.tickers_requested),
        "top_n": snapshot.request_scope.top_n,
        "operator_request_id": redact(
            snapshot.request_scope.operator_request_id,
            "request_scope.operator_request_id",
            events,
            "operator_request_id",
        ),
    }
    prepared = tuple(
        prepare_recommendation(recommendation, evidence[index], index, events)
        for index, recommendation in enumerate(snapshot.recommendations)
    )
    base_seed: dict[str, JsonValue] = {
        "schema_version": SCHEMA_VERSION,
        "market_scope": snapshot.request_scope.market_scope,
        "decision_at": snapshot.decision_at,
        "recommendation_emitted_at": snapshot.recommendation_emitted_at,
        "decision_data_cutoff_at": snapshot.decision_data_cutoff_at,
        "candidate_universe_hash": str(canonical_hash(_json_strings(sorted(item.candidate_universe_hash for item in prepared)))),
        "prompt_bundle_hash": str(canonical_hash(_json_strings(sorted(item.prompt_hash for item in prepared)))),
        "config_hash": str(canonical_hash(_json_strings(sorted(item.config_hash for item in prepared)))),
    }
    base_hash = str(canonical_hash(base_seed))
    recommendation_values: list[JsonValue] = []
    recommendation_ids: list[RecommendationId] = []
    for item in prepared:
        identity = item.source.identity
        candidate_id = deterministic_id(
            IdPrefix.CANDIDATE,
            {
                "schema_version": SCHEMA_VERSION,
                "snapshot_identity_hash": base_hash,
                "universe_id": item.evidence.universe_id,
                "market": identity.market,
                "exchange": identity.exchange,
                "ticker": identity.ticker,
                "selection_stage": item.evidence.selection_stage,
                "rank_seed_hash": item.evidence.rank_seed_hash,
            },
        )
        recommendation_id = deterministic_id(
            IdPrefix.RECOMMENDATION,
            {
                "schema_version": SCHEMA_VERSION,
                "snapshot_identity_hash": base_hash,
                "market": identity.market,
                "exchange": identity.exchange,
                "ticker": identity.ticker,
                "action": identity.action,
                "emitted_at": identity.emitted_at,
                "data_cutoff_at": identity.data_cutoff_at,
                "candidate_universe_hash": item.candidate_universe_hash,
                "parsed_result_hash": item.parsed_result_hash,
            },
        )
        recommendation_ids.append(recommendation_id)
        recommendation_values.append(
            {
                "candidate_id": candidate_id,
                "recommendation_id": recommendation_id,
                **item.body,
            }
        )
    final_seed: dict[str, JsonValue] = {
        **base_seed,
        "recommendation_ids": _json_strings(
            sorted(str(value) for value in recommendation_ids)
        ),
    }
    identity_hash = str(canonical_hash(final_seed))
    snapshot_id = deterministic_id(IdPrefix.SNAPSHOT, final_seed)
    body: dict[str, JsonValue] = {
        "schema_version": SCHEMA_VERSION,
        "snapshot_id": snapshot_id,
        "created_at": snapshot.created_at,
        "decision_at": snapshot.decision_at,
        "recommendation_emitted_at": snapshot.recommendation_emitted_at,
        "decision_data_cutoff_at": snapshot.decision_data_cutoff_at,
        "request_scope": request_scope,
        "contract_refs": {
            "measurement_contract": snapshot.contract_refs.measurement_contract,
            "market_context_contract": snapshot.contract_refs.market_context_contract,
        },
        "retention_policy": {
            "policy_version": snapshot.retention_policy.policy_version,
            "raw_llm_text_days": snapshot.retention_policy.raw_llm_text_days,
            "market_payload_retention": snapshot.retention_policy.market_payload_retention,
        },
        "redaction": {
            "redaction_version": REDACTION_VERSION,
            "redaction_events": events,
        },
        "recommendations": recommendation_values,
        "content_hashes": {},
    }
    content_hash = str(canonical_hash(body))
    body["content_hashes"] = {
        "snapshot_identity_base_hash": base_hash,
        "snapshot_identity_hash": identity_hash,
        "snapshot_content_hash": content_hash,
    }
    return SnapshotDocument(snapshot_id=snapshot_id, value=body)


def snapshot_path(directory: Path, snapshot_id: SnapshotId) -> Path:
    return directory / f"{snapshot_id}.json"


def write_snapshot(
    directory: Path,
    snapshot: SnapshotDocument,
) -> ArtifactWriteStatus:
    return write_immutable_json(
        snapshot_path(directory, snapshot.snapshot_id), snapshot.value
    )
