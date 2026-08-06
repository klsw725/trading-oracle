from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import override

from .models import Action, IdPrefix, JsonValue, Market, canonical_hash, deterministic_id
from .snapshot import ContractRefs, LlmProvenance, RecommendationIdentityInput, RecommendationInput, RecommendationProvenance, RequestScope, RetentionPolicy, build_snapshot
from .snapshot_redaction import prepare_recommendation
from .snapshot_validation import SnapshotInput, SnapshotValidationError, validate_snapshot


@dataclass(frozen=True, slots=True)
class FixtureSupportParseError(Exception):
    field: str
    expected: str

    @override
    def __str__(self) -> str:
        return f"{self.field} must be {self.expected}"


def _record(value: JsonValue, field: str) -> Mapping[str, JsonValue]:
    if not isinstance(value, dict):
        raise FixtureSupportParseError(field, "an object")
    return value


def _text(value: Mapping[str, JsonValue], field: str) -> str:
    item = value[field]
    if not isinstance(item, str):
        raise FixtureSupportParseError(field, "a string")
    return item


def _records(value: JsonValue, field: str) -> Sequence[Mapping[str, JsonValue]]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise FixtureSupportParseError(field, "an array of objects")
    return tuple(item for item in value if isinstance(item, dict))


def _texts(value: JsonValue, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise FixtureSupportParseError(field, "an array of strings")
    return tuple(item for item in value if isinstance(item, str))


def _snapshot_input(root: Mapping[str, JsonValue]) -> SnapshotInput:
    clock = _record(root["clock"], "clock")
    source = _record(_record(root["identity"], "identity")["snapshot_input"], "snapshot_input")
    contexts = _record(root["market_contexts"], "market_contexts")
    recommendations: list[RecommendationInput] = []
    for item in _records(source["recommendations"], "recommendations"):
        context = _record(contexts[_text(item, "market_context_ref")], "market_context")
        source_body: JsonValue = {"ticker": _text(item, "ticker"), "cutoff": _text(clock, "decision_data_cutoff_at")}
        context_hash = canonical_hash(dict(context)); parsed = item["parsed_result"]
        is_us = _text(item, "market") == "US"
        market_context: JsonValue = {
            "schema_version": "v4.market_context.phase25.1", "market": context["market"], "exchange": context["exchange"], "calendar_id": context["calendar_id"],
            "timezone": context["timezone"], "quote_currency": context["quote_currency"], "base_reporting_currency": context["base_reporting_currency"],
            "benchmark_id": context["benchmark_id"], "benchmark_source": "fixture", "benchmark_as_of": _text(clock, "decision_data_cutoff_at"),
            "decision_data_cutoff_at": _text(clock, "decision_data_cutoff_at"), "target_session_close_at": None, "decision_regime": context["decision_regime"],
            "decision_regime_source": context["decision_regime_source"], "analysis_regime": context["decision_regime"], "fx_pair": "USD_KRW" if is_us else "KRW_KRW", "fx_rate": 1380.25 if is_us else 1.0,
            "fx_as_of": _text(clock, "decision_data_cutoff_at"), "fx_freshness_state": "fresh", "blocked_fields": [], "degraded_fields": [], "context_state": "matured",
            "provenance_hashes": {"benchmark": context_hash, "calendar": context_hash, "fx": context_hash},
        }
        universe: JsonValue = {"universe_id": f"fixture-{_text(item, 'market').lower()}-universe", "market_scope": source["market_scope"], "source": "fixture", "adapter_version": "1", "total_seen": 2, "members_hash": canonical_hash(source_body)}
        rank_seed = canonical_hash({"ticker": _text(item, "ticker"), "stage": "fixture_selection"})
        llm = LlmProvenance("fixture-adapter-1", "offline", "fixture", None, "fixture-prompt-1", [{"role": "user", "content": _text(item, "ticker")}], "fixture-config-1", {"temperature": 0}, "perspective-json-v1", [parsed], parsed)
        provenance = RecommendationProvenance(market_context, [{"source_id": "fixture", "adapter_version": "1", "record_type": "quote", "as_of": _text(clock, "decision_data_cutoff_at"), "fetched_at": _text(clock, "decision_at"), "freshness_state": "fresh", "provenance_hash": canonical_hash(source_body), "raw_retention": "hash_only"}], universe, {"selection_stage": "fixture_selection", "rank_seed_hash": rank_seed}, [], {}, {}, llm, parsed, "not_applicable", {}, {}, {})
        identity = RecommendationIdentityInput(_text(item, "ticker"), _text(item, "name"), Market(_text(item, "market")), _text(item, "exchange"), Action(_text(item, "action")), _text(clock, "decision_at"), _text(clock, "recommendation_emitted_at"), _text(clock, "decision_data_cutoff_at"))
        recommendations.append(RecommendationInput(identity, provenance))
    top_n = source["top_n"]
    return SnapshotInput(_text(clock, "generated_at"), _text(clock, "decision_at"), _text(clock, "recommendation_emitted_at"), _text(clock, "decision_data_cutoff_at"), RequestScope(_text(source, "market_scope"), _texts(source["tickers_requested"], "tickers_requested"), top_n if isinstance(top_n, int) and not isinstance(top_n, bool) else None), ContractRefs("v4.phase22.1", "v4.market_context.phase25.1"), RetentionPolicy("v4.retention.phase23.1", 180, "hash_only"), tuple(recommendations))


def snapshot_report(root: Mapping[str, JsonValue]) -> JsonValue:
    source = _snapshot_input(root); document = build_snapshot(source)
    identity = _record(root["identity"], "identity"); expected = _record(identity["expected"], "identity.expected")
    evidence = validate_snapshot(source); events: list[JsonValue] = []
    prepared = tuple(prepare_recommendation(item, evidence[index], index, events) for index, item in enumerate(source.recommendations))
    candidate_values: list[JsonValue] = []; prompt_values: list[JsonValue] = []; config_values: list[JsonValue] = []
    for value in sorted(item.candidate_universe_hash for item in prepared): candidate_values.append(value)
    for value in sorted(item.prompt_hash for item in prepared): prompt_values.append(value)
    for value in sorted(item.config_hash for item in prepared): config_values.append(value)
    base_seed: dict[str, JsonValue] = {"schema_version": "v4.snapshot.phase23.1", "market_scope": source.request_scope.market_scope, "decision_at": source.decision_at, "recommendation_emitted_at": source.recommendation_emitted_at, "decision_data_cutoff_at": source.decision_data_cutoff_at, "candidate_universe_hash": canonical_hash(candidate_values), "prompt_bundle_hash": canonical_hash(prompt_values), "config_hash": canonical_hash(config_values)}
    base_hash = canonical_hash(base_seed); candidate_ids: list[str] = []; recommendation_ids: list[str] = []
    for item in prepared:
        identity_input = item.source.identity
        candidate_ids.append(deterministic_id(IdPrefix.CANDIDATE, {"schema_version": "v4.snapshot.phase23.1", "snapshot_identity_hash": base_hash, "universe_id": item.evidence.universe_id, "market": identity_input.market, "exchange": identity_input.exchange, "ticker": identity_input.ticker, "selection_stage": item.evidence.selection_stage, "rank_seed_hash": item.evidence.rank_seed_hash}))
        recommendation_ids.append(deterministic_id(IdPrefix.RECOMMENDATION, {"schema_version": "v4.snapshot.phase23.1", "snapshot_identity_hash": base_hash, "market": identity_input.market, "exchange": identity_input.exchange, "ticker": identity_input.ticker, "action": identity_input.action, "emitted_at": identity_input.emitted_at, "data_cutoff_at": identity_input.data_cutoff_at, "candidate_universe_hash": item.candidate_universe_hash, "parsed_result_hash": item.parsed_result_hash}))
    sorted_recommendations: list[JsonValue] = [value for value in sorted(recommendation_ids)]; final_seed: JsonValue = {**base_seed, "recommendation_ids": sorted_recommendations}
    identity_hash = canonical_hash(final_seed); snapshot_id = deterministic_id(IdPrefix.SNAPSHOT, final_seed)
    body = dict(document.value); body["content_hashes"] = {}; content_hash = canonical_hash(body)
    output_recommendations = _records(document.value["recommendations"], "snapshot.recommendations")
    actual_candidate_ids = [_text(item, "candidate_id") for item in output_recommendations]; actual_recommendation_ids = [_text(item, "recommendation_id") for item in output_recommendations]
    valid = candidate_ids == actual_candidate_ids and recommendation_ids == actual_recommendation_ids and document.snapshot_id == snapshot_id
    valid = valid and _record(document.value["content_hashes"], "content_hashes") == {"snapshot_identity_base_hash": base_hash, "snapshot_identity_hash": identity_hash, "snapshot_content_hash": content_hash}
    valid = valid and candidate_ids == expected["candidate_ids"] and recommendation_ids == expected["recommendation_ids"] and snapshot_id == expected["snapshot_id"] and content_hash == expected["snapshot_content_hash"]
    contaminated_context = dict(_record(source.recommendations[1].provenance.market_context, "market_context")); contaminated_context["decision_regime_source"] = "KS11"
    contaminated = replace(source.recommendations[1], provenance=replace(source.recommendations[1].provenance, market_context=contaminated_context))
    try:
        _ = build_snapshot(replace(source, recommendations=(source.recommendations[0], contaminated)))
        contamination_rejected = False
    except SnapshotValidationError:
        contamination_rejected = True
    valid = valid and contamination_rejected
    result: dict[str, JsonValue] = {"state": "pass" if valid else "fail", "candidate_ids": [value for value in candidate_ids], "recommendation_ids": [value for value in recommendation_ids], "snapshot_id": str(snapshot_id), "snapshot_identity_hash": identity_hash, "snapshot_content_hash": content_hash, "contaminated_context_rejected": contamination_rejected}
    return result


def owned_file_hashes() -> JsonValue:
    integration = (
        Path("src/common.py"), Path("src/perspectives/base.py"), Path("src/consensus/voter.py"),
        Path("src/consensus/deliberator.py"), Path("src/data/market.py"), Path("main.py"),
        Path("scripts/daily.py"), Path("scripts/recommend.py"), Path("scripts/v4.py"),
        Path("config.yaml"), Path("pyproject.toml"), Path("uv.lock"),
    )
    v4_sources = tuple(sorted(Path("src/v4").glob("*.py")))
    v4_specs = tuple(sorted(Path("docs/specs/v4").rglob("*.md")))
    fixture_inputs = tuple(sorted(path for path in Path("docs/specs/v4/fixtures").glob("*.json")))
    paths = (*v4_sources, *integration, *v4_specs, *fixture_inputs)
    return {path.as_posix(): canonical_hash(path.read_text()) for path in paths}
