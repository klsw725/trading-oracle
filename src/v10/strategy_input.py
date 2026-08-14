from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Annotated, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from src.v4.models import JsonValue, canonical_hash, canonical_json

from .canonical import model_json, parse_json_bytes, reject_forbidden, seal_meta, verify_seal
from .models import ArtifactRef, V10ContractError
from .strategy_input_models import (
    BorrowArtifact,
    BorrowInput,
    CausalSizingArtifact,
    CausalSizingInput,
    HistoricalObservationArtifact,
    HistoricalObservationInput,
    TargetSnapshotArtifact,
    TargetSnapshotInput,
    StrategyBarArtifact,
    StrategyBarInput,
    StrategyInputFixture,
    StrategySeriesArtifact,
    StrategySeriesInput,
)


class StrategyInputBundle(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["v10.strategy_input.bundle.1"]
    fixture_hash: str
    source_fixture: JsonValue
    bars: Annotated[tuple[StrategyBarArtifact, ...], Field(strict=False)]
    series: Annotated[tuple[StrategySeriesArtifact, ...], Field(strict=False)]
    historical: Annotated[tuple[HistoricalObservationArtifact, ...], Field(strict=False)]
    causal_sizing: Annotated[tuple[CausalSizingArtifact, ...], Field(strict=False)]
    target_snapshots: Annotated[tuple[TargetSnapshotArtifact, ...], Field(strict=False)]
    borrows: Annotated[tuple[BorrowArtifact, ...], Field(strict=False)]
    bundle_hash: str


_BUNDLE = TypeAdapter(StrategyInputBundle)


def build_strategy_input(value: JsonValue) -> JsonValue:
    try:
        fixture = StrategyInputFixture.model_validate(value)
    except ValidationError as error:
        raise V10ContractError("V10_STRATEGY_INPUT_FIXTURE", str(error)) from error
    series_ids = {item.series_id for item in fixture.series}
    if len(series_ids) != len(fixture.series):
        raise V10ContractError("V10_STRATEGY_INPUT_SERIES", "duplicate series")
    bars = tuple(_bar(item) for item in fixture.bars)
    grouped = {series_id: tuple(item for item in bars if item.series_id == series_id)
               for series_id in series_ids}
    if any(not grouped[series_id] for series_id in series_ids):
        raise V10ContractError("V10_STRATEGY_INPUT_SERIES", "empty series")
    for item in fixture.series:
        _verify_series_input(item, grouped[item.series_id])
    historical = tuple(_historical(item.series_id,
        tuple(value for value in fixture.historical if value.series_id == item.series_id))
        for item in fixture.series)
    causals = tuple(_causal(item) for item in fixture.causal_sizing)
    targets = tuple(_target(item) for item in fixture.target_snapshots)
    borrows = tuple(_borrow(item) for item in fixture.borrows)
    if ({item.series_id.split("@", 1)[0] for item in causals} != series_ids
            or {item.series_id.split("@", 1)[0] for item in targets} != series_ids
            or {item.series_id for item in borrows} != series_ids):
        raise V10ContractError("V10_STRATEGY_INPUT_SERIES", "execution/borrow inventory")
    series = tuple(_series(item, grouped[item.series_id], historical[index],
        tuple(value for value in causals if value.series_id.startswith(f"{item.series_id}@"))[-1],
        tuple(value for value in targets if value.series_id.startswith(f"{item.series_id}@"))[-1],
        borrows[index]) for index, item in enumerate(fixture.series))
    body: dict[str, JsonValue] = {"schema_version": "v10.strategy_input.bundle.1",
        "fixture_hash": canonical_hash(value), "source_fixture": value,
        "bars": [model_json(item) for item in bars],
        "series": [model_json(item) for item in series],
        "historical": [model_json(item) for item in historical],
        "causal_sizing": [model_json(item) for item in causals],
        "target_snapshots": [model_json(item) for item in targets],
        "borrows": [model_json(item) for item in borrows]}
    return {**body, "bundle_hash": canonical_hash(body)}


def verify_strategy_input(payload: bytes) -> StrategyInputBundle:
    value = parse_json_bytes(payload)
    reject_forbidden(value)
    try:
        bundle = _BUNDLE.validate_python(value)
    except ValidationError as error:
        raise V10ContractError("V10_STRATEGY_INPUT_BUNDLE", str(error)) from error
    rebuilt = build_strategy_input(bundle.source_fixture)
    if canonical_json(rebuilt) != canonical_json(bundle.model_dump(mode="json")):
        raise V10ContractError("V10_STRATEGY_INPUT_DERIVED", "bundle")
    for artifact in (*bundle.bars, *bundle.series, *bundle.historical,
                     *bundle.causal_sizing, *bundle.target_snapshots, *bundle.borrows):
        verify_seal(artifact)
    known = {str(item.meta.artifact_id): item.meta.content_hash for item in bundle.bars}
    for item in bundle.series:
        refs = (*item.prior_refs, *item.symbol_refs, *item.benchmark_refs)
        if any(str(ref.artifact_id) not in known
               or known[str(ref.artifact_id)] != ref.content_hash
               for ref in refs):
            raise V10ContractError("V10_STRATEGY_INPUT_LINEAGE", item.series_id)
    return bundle


def build_strategy_input_path(path: Path) -> JsonValue:
    try:
        return build_strategy_input(parse_json_bytes(path.read_bytes()))
    except OSError as error:
        raise V10ContractError("V10_FIXTURE_ERROR", str(error)) from error


def _bar(item: StrategyBarInput) -> StrategyBarArtifact:
    body = model_json(item)
    return StrategyBarArtifact(meta=seal_meta("strategy_input_bar", body),
        series_id=item.series_id, role=item.role, benchmark_id=item.benchmark_id,
        symbol=item.symbol, session_date=item.session_date,
        interval_start=item.interval_start, interval_end=item.interval_end,
        open=item.open, high=item.high, low=item.low, close=item.close,
        volume=item.volume, complete=item.complete, observed_at=item.observed_at,
        watermark_at=item.watermark_at, source_ref=item.source_ref,
        calendar_ref=item.calendar_ref, adjustment_factor=item.adjustment_factor)


def _series(item: StrategySeriesInput, bars: tuple[StrategyBarArtifact, ...],
            historical: HistoricalObservationArtifact, causal: CausalSizingArtifact,
            target: TargetSnapshotArtifact,
            borrow: BorrowArtifact) -> StrategySeriesArtifact:
    refs = {role: tuple(ArtifactRef(role=bar.role, artifact_type=bar.meta.artifact_type,
        artifact_id=bar.meta.artifact_id, content_hash=bar.meta.content_hash)
        for bar in bars if bar.role == role) for role in ("prior", "symbol", "benchmark")}
    history_ref = ArtifactRef(role="historical", artifact_type=historical.meta.artifact_type,
        artifact_id=historical.meta.artifact_id, content_hash=historical.meta.content_hash)
    causal_ref = ArtifactRef(role="causal", artifact_type=causal.meta.artifact_type,
        artifact_id=causal.meta.artifact_id, content_hash=causal.meta.content_hash)
    target_ref = ArtifactRef(role="target", artifact_type=target.meta.artifact_type,
        artifact_id=target.meta.artifact_id, content_hash=target.meta.content_hash)
    borrow_ref = ArtifactRef(role="borrow", artifact_type=borrow.meta.artifact_type,
        artifact_id=borrow.meta.artifact_id, content_hash=borrow.meta.content_hash)
    body: dict[str, JsonValue] = {"series_id": item.series_id, "symbol": item.symbol,
        "benchmark_id": item.benchmark_id, "adjustment_factor": str(item.adjustment_factor),
        "risk_kill_at": None if item.risk_kill_at is None else item.risk_kill_at.isoformat(),
        "eligibility_refs": [model_json(ref) for ref in item.eligibility_refs],
        "prior_refs": [model_json(ref) for ref in refs["prior"]],
        "symbol_refs": [model_json(ref) for ref in refs["symbol"]],
        "benchmark_refs": [model_json(ref) for ref in refs["benchmark"]],
        "historical_ref": model_json(history_ref), "causal_ref": model_json(causal_ref),
        "target_ref": model_json(target_ref),
        "borrow_ref": model_json(borrow_ref)}
    return StrategySeriesArtifact(meta=seal_meta("strategy_input_series", body),
        series_id=item.series_id, symbol=item.symbol, benchmark_id=item.benchmark_id,
        adjustment_factor=item.adjustment_factor, risk_kill_at=item.risk_kill_at,
        eligibility_refs=item.eligibility_refs,
        prior_refs=refs["prior"], symbol_refs=refs["symbol"],
        benchmark_refs=refs["benchmark"], historical_ref=history_ref,
        causal_ref=causal_ref, target_ref=target_ref, borrow_ref=borrow_ref)


def _historical(series_id: str, values: tuple[HistoricalObservationInput, ...]) -> HistoricalObservationArtifact:
    body: JsonValue = {"series_id": series_id,
        "observations": [model_json(item) for item in values]}
    return HistoricalObservationArtifact(meta=seal_meta("strategy_history", body),
        series_id=series_id, observations=values)


def _causal(item: CausalSizingInput) -> CausalSizingArtifact:
    return CausalSizingArtifact.model_validate({"meta": model_json(
        seal_meta("strategy_causal_sizing", model_json(item))), **item.model_dump(mode="json")})


def _target(item: TargetSnapshotInput) -> TargetSnapshotArtifact:
    return TargetSnapshotArtifact.model_validate({"meta": model_json(
        seal_meta("strategy_execution_snapshot", model_json(item))), **item.model_dump(mode="json")})


def _borrow(item: BorrowInput) -> BorrowArtifact:
    if item.effective_from >= item.effective_until:
        raise V10ContractError("V10_STRATEGY_INPUT_BORROW_PERIOD", item.series_id)
    if item.annual_fee < 0:
        raise V10ContractError("V10_STRATEGY_INPUT_BORROW_FEE", item.series_id)
    if (item.recalled_at is not None
            and not item.effective_from <= item.recalled_at < item.effective_until):
        raise V10ContractError("V10_STRATEGY_INPUT_BORROW_RECALL", item.series_id)
    return BorrowArtifact.model_validate({"meta": model_json(
        seal_meta("strategy_borrow", model_json(item))), **item.model_dump(mode="json")})


def _verify_series_input(item: StrategySeriesInput,
                         bars: tuple[StrategyBarArtifact, ...]) -> None:
    benchmark = tuple(bar for bar in bars if bar.role == "benchmark")
    symbols = tuple(bar for bar in bars if bar.role != "benchmark")
    if not benchmark or not symbols:
        raise V10ContractError("V10_STRATEGY_INPUT_SERIES", item.series_id)
    if any(bar.symbol != item.symbol or bar.benchmark_id is not None for bar in symbols):
        raise V10ContractError("V10_STRATEGY_INPUT_SYMBOL", item.series_id)
    if any(bar.symbol != item.benchmark_id or bar.benchmark_id != item.benchmark_id
           for bar in benchmark):
        raise V10ContractError("V10_STRATEGY_INPUT_BENCHMARK", item.series_id)
    if any(bar.adjustment_factor != item.adjustment_factor for bar in bars):
        raise V10ContractError("V10_STRATEGY_INPUT_ADJUSTMENT", item.series_id)
    if any(bar.interval_start >= bar.interval_end or bar.observed_at > bar.watermark_at
           or bar.high < max(bar.open, bar.close) or bar.low > min(bar.open, bar.close)
           for bar in bars):
        raise V10ContractError("V10_STRATEGY_INPUT_BAR", item.series_id)
    for role in ("prior", "symbol", "benchmark"):
        sequence = tuple(bar for bar in bars if bar.role == role)
        if any(bar.interval_end - bar.interval_start != timedelta(minutes=5)
               for bar in sequence):
            raise V10ContractError("V10_STRATEGY_INPUT_DURATION", item.series_id)
        if any(current.interval_start != previous.interval_end
               or current.session_date != previous.session_date
               for previous, current in zip(sequence, sequence[1:], strict=False)):
            raise V10ContractError("V10_STRATEGY_INPUT_CONTINUITY", item.series_id)
