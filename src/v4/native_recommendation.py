from collections.abc import Mapping, Sequence
from typing import Final, Protocol, assert_never

from .models import Action, JsonValue, Market
from .snapshot_validation import (
    LlmProvenance,
    RecommendationIdentityInput,
    RecommendationInput,
    RecommendationProvenance,
)

_EQUAL_WEIGHTS: Final[dict[str, JsonValue]] = {
    "kwangsoo": 0.2,
    "ouroboros": 0.2,
    "quant": 0.2,
    "macro": 0.2,
    "value": 0.2,
}
_PERSPECTIVE_ORDER: Final = tuple(_EQUAL_WEIGHTS)
_RECOMMENDATION_STAGES: Final = (
    "screening",
    "diversified_selection",
    "portfolio_exclusion",
    "signal_filter",
    "consensus",
    "risk_action",
)


class NativeCaptureSource(Protocol):
    @property
    def multi_results(self) -> Mapping[str, JsonValue]: ...

    @property
    def signals_data(self) -> Sequence[Mapping[str, JsonValue]]: ...

    @property
    def market_data(self) -> Mapping[str, JsonValue]: ...

    @property
    def portfolio(self) -> Mapping[str, JsonValue]: ...

    @property
    def config(self) -> Mapping[str, JsonValue]: ...


def record(value: JsonValue | None) -> dict[str, JsonValue] | None:
    match value:
        case dict() as parsed:
            return parsed
        case None | str() | bool() | int() | float() | list():
            return None
        case unreachable:
            assert_never(unreachable)


def text(source: Mapping[str, JsonValue], key: str) -> str | None:
    match source.get(key):
        case str() as value if value:
            return value
        case None | str() | bool() | int() | float() | list() | dict():
            return None
        case unreachable:
            assert_never(unreachable)


def _perspective_names(consensus: Mapping[str, JsonValue]) -> tuple[str, ...] | None:
    match consensus.get("perspectives"):
        case list() as perspectives:
            names: list[str] = []
            for value in perspectives:
                parsed = record(value)
                if parsed is None or (name := text(parsed, "perspective")) is None:
                    return None
                names.append(name)
            return tuple(names)
        case None | str() | bool() | int() | float() | dict():
            return None
        case unreachable:
            assert_never(unreachable)


def _perspective_record_order(value: JsonValue) -> tuple[int, int]:
    parsed = record(value)
    perspective = text(parsed, "perspective") if parsed is not None else None
    order = (
        _PERSPECTIVE_ORDER.index(perspective)
        if perspective in _PERSPECTIVE_ORDER
        else len(_PERSPECTIVE_ORDER)
    )
    attempt = parsed.get("attempt", 0) if parsed is not None else 0
    return order, attempt if isinstance(attempt, int) else 0


def _ordered_perspective_records(value: JsonValue) -> JsonValue:
    match value:
        case list() as records:
            return sorted(records, key=_perspective_record_order)
        case None | str() | bool() | int() | float() | dict():
            return value
        case unreachable:
            assert_never(unreachable)


def missing_provenance(source: NativeCaptureSource) -> tuple[str, ...]:
    missing: list[str] = []
    if not source.multi_results:
        missing.append("multi_results")
    run = record(source.market_data.get("v4_provenance"))
    for field in ("created_at", "decision_at", "emitted_at", "data_cutoff_at", "market_scope"):
        if run is None or text(run, field) is None:
            missing.append(f"market_data.v4_provenance.{field}")
    by_ticker = {
        ticker: item
        for item in source.signals_data
        if (ticker := text(item, "ticker")) is not None
    }
    for ticker in by_ticker.keys() - source.multi_results.keys():
        missing.append(f"multi_results.{ticker}")
    for ticker, value in source.multi_results.items():
        consensus = record(value)
        item = by_ticker.get(ticker)
        provenance = record(item.get("v4_provenance")) if item is not None else None
        if consensus is None:
            missing.append(f"multi_results.{ticker}")
            continue
        if consensus.get("weighted") is not False:
            missing.append(f"multi_results.{ticker}.equal_weight_consensus")
        if _perspective_names(consensus) != _PERSPECTIVE_ORDER:
            missing.append(f"multi_results.{ticker}.perspective_order")
        for field in ("market", "exchange", "data_cutoff_at", "market_context", "sources", "candidate_universe", "selection", "llm", "risk_state", "quality_states"):
            if provenance is None or provenance.get(field) is None:
                missing.append(f"signals_data.{ticker}.v4_provenance.{field}")
        universe = record(provenance.get("candidate_universe")) if provenance is not None else None
        members = None
        total_seen = None
        if universe is not None:
            members = universe.get("members")
            total_seen = universe.get("total_seen")
        if not isinstance(members, list) or len(members) != total_seen:
            missing.append(f"signals_data.{ticker}.v4_provenance.candidate_universe.members")
        selection = record(provenance.get("selection")) if provenance is not None else None
        stages = record(selection.get("pipeline_stages")) if selection is not None else None
        for stage in _RECOMMENDATION_STAGES:
            stage_record = record(stages.get(stage)) if stages is not None else None
            if stage_record is None or stage_record.get("status") != "complete":
                missing.append(
                    f"signals_data.{ticker}.v4_provenance.selection.pipeline_stages.{stage}"
                )
        risk_state = record(provenance.get("risk_state")) if provenance is not None else None
        for field in ("portfolio_check", "action_plan"):
            if risk_state is None or field not in risk_state:
                missing.append(f"signals_data.{ticker}.v4_provenance.risk_state.{field}")
        llm = record(provenance.get("llm")) if provenance is not None else None
        for field in ("provider_adapter_version", "prompt_bundle_version", "prompt_messages", "config_version", "config", "parser_version", "raw_results", "parsed_results"):
            if llm is None or llm.get(field) is None:
                missing.append(f"signals_data.{ticker}.v4_provenance.llm.{field}")
        if llm is not None and not llm.get("prompt_messages"):
            missing.append(f"signals_data.{ticker}.v4_provenance.llm.prompt_messages")
        if llm is not None and not llm.get("raw_results"):
            missing.append(f"signals_data.{ticker}.v4_provenance.llm.raw_results")
        verdict = text(consensus, "consensus_verdict")
        if verdict not in {Action.BUY, Action.SELL, Action.HOLD}:
            missing.append(f"multi_results.{ticker}.action")
    return tuple(missing)


def _recommendation(
    ticker: str,
    run: Mapping[str, JsonValue],
    source: NativeCaptureSource,
) -> RecommendationInput:
    consensus = record(source.multi_results[ticker]) or {}
    item = next(item for item in source.signals_data if text(item, "ticker") == ticker)
    provenance = record(item["v4_provenance"]) or {}
    llm_provenance = record(provenance["llm"]) or {}
    consensus_with_provenance: dict[str, JsonValue] = {
        **consensus,
        "scorer_version": "maxs-lite.v1",
        "weighted": False,
        "weights_used": _EQUAL_WEIGHTS,
    }
    parsed_results = _ordered_perspective_records(
        llm_provenance.get("parsed_results", consensus.get("perspectives", []))
    )
    llm = LlmProvenance(
        provider_adapter_version=text(llm_provenance, "provider_adapter_version") or "",
        provider=text(llm_provenance, "provider"),
        model=text(llm_provenance, "model"),
        provider_request_id=text(llm_provenance, "provider_request_id"),
        prompt_bundle_version=text(llm_provenance, "prompt_bundle_version") or "",
        prompt_messages=_ordered_perspective_records(llm_provenance["prompt_messages"]),
        config_version=text(llm_provenance, "config_version") or "",
        config=llm_provenance["config"],
        parser_version=text(llm_provenance, "parser_version") or "",
        raw_results=_ordered_perspective_records(llm_provenance["raw_results"]),
        parsed_results=parsed_results,
    )
    return RecommendationInput(
        identity=RecommendationIdentityInput(
            ticker=ticker,
            name=text(item, "name") or ticker,
            market=Market(text(provenance, "market") or ""),
            exchange=text(provenance, "exchange") or "",
            action=Action(text(consensus, "consensus_verdict") or ""),
            decision_at=text(run, "decision_at") or "",
            emitted_at=text(run, "emitted_at") or "",
            data_cutoff_at=text(provenance, "data_cutoff_at") or "",
        ),
        provenance=RecommendationProvenance(
            market_context=provenance["market_context"],
            sources=provenance["sources"],
            candidate_universe=provenance["candidate_universe"],
            selection=provenance["selection"],
            rejections=provenance.get("rejections", []),
            features=provenance.get("features", {}),
            signals=item.get("signals", "unknown"),
            llm=llm,
            consensus=consensus_with_provenance,
            deliberation=consensus.get("deliberation", "not_applicable"),
            portfolio_state=dict(source.portfolio),
            risk_state=provenance["risk_state"],
            quality_states=provenance["quality_states"],
        ),
    )


def build_recommendations(
    source: NativeCaptureSource,
    run: Mapping[str, JsonValue],
) -> tuple[RecommendationInput, ...]:
    return tuple(
        _recommendation(ticker, run, source)
        for ticker in sorted(source.multi_results)
    )
