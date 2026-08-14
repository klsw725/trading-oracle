from __future__ import annotations

from typing import Literal

from src.v4.models import canonical_json
from src.v10.strategy_input import StrategyInputBundle, build_strategy_input, verify_strategy_input
from src.v10.strategy_input_models import BorrowInput, CausalSizingInput, ExternalRef, HistoricalObservationInput, StrategyBarInput, StrategyInputFixture, StrategySeriesInput, TargetSnapshotInput
from src.v11.canonical import model_json

from .models import ArtifactRef, Bar, ExecutionBinding, FixtureCase, StrategyInput, V12ContractError


def build_source_fixture(inputs: tuple[tuple[str, StrategyInput], ...]) -> StrategyInputFixture:
    series = tuple(StrategySeriesInput(series_id=series_id, symbol=source.symbol,
        benchmark_id=source.benchmark_id, adjustment_factor=source.adjustment_factor,
        risk_kill_at=source.risk_kill_at,
        eligibility_refs=tuple(ExternalRef.model_validate(item.model_dump(mode="json"))
                               for item in source.eligibility_refs))
        for series_id, source in inputs)
    bars: list[StrategyBarInput] = []
    for series_id, source in inputs:
        bars.extend(_bar(series_id, "prior", source, bar) for bar in source.prior_bars)
        bars.extend(_bar(series_id, "symbol", source, bar) for bar in source.bars)
        bars.extend(_bar(series_id, "benchmark", source, bar)
                    for bar in source.benchmark_bars)
    historical = tuple(HistoricalObservationInput(series_id=series_id, feature=feature,
        session_date=value.session_date, minute_slot=value.minute_slot, value=value.value)
        for series_id, source in inputs for feature, values in source.historical.items()
        for value in values)
    causals = tuple(CausalSizingInput(series_id=f"{series_id}@{binding.cutoff.isoformat()}",
        market=source.market.value, symbol=source.symbol,
        causal_observed_at=binding.causal_sizing.observed_at,
        causal_close=binding.causal_sizing.close,
        prior_turnovers=binding.causal_sizing.prior_turnovers)
        for series_id, source in inputs for binding in source.execution_bindings)
    targets = tuple(TargetSnapshotInput(series_id=f"{series_id}@{binding.cutoff.isoformat()}",
        market=source.market.value, symbol=source.symbol,
        target_at=binding.execution_snapshot.target_at,
        target_open=binding.execution_snapshot.open,
        target_volume=binding.execution_snapshot.volume,
        source_ref=ExternalRef.model_validate(
            binding.execution_snapshot.source_ref.model_dump(mode="json")),
        calendar_ref=ExternalRef.model_validate(
            binding.execution_snapshot.calendar_ref.model_dump(mode="json")))
        for series_id, source in inputs for binding in source.execution_bindings)
    borrows = tuple(BorrowInput(series_id=series_id, market=source.market.value,
        symbol=source.symbol, effective_from=borrow.effective_from,
        effective_until=borrow.effective_until, evaluated_at=borrow.evaluated_at,
        recalled_at=borrow.recalled_at, annual_fee=borrow.annual_fee,
        locate=borrow.locate, etb=borrow.etb, shortable=borrow.shortable,
        regulation_known=borrow.regulation_known,
        source_refs=tuple(ExternalRef.model_validate(ref.model_dump(mode="json"))
                          for ref in borrow.refs))
        for series_id, source in inputs if (borrow := source.borrow) is not None)
    if len(borrows) != len(inputs):
        raise V12ContractError("V12_BORROW_FIXTURE_INVENTORY", str(len(borrows)))
    return StrategyInputFixture(schema_version="v10.strategy_input.fixture.1",
        bars=tuple(bars), series=series, historical=historical,
        causal_sizing=causals, target_snapshots=targets, borrows=borrows)


def bind_cases(cases: tuple[FixtureCase, ...],
               source_fixture: StrategyInputFixture) -> tuple[tuple[FixtureCase, ...], str]:
    bundle = verify_strategy_input(canonical_json(build_strategy_input(model_json(source_fixture))))
    bound: list[FixtureCase] = []
    for case in cases:
        series_id = f"{case.strategy_id}:{case.scenario.value}"
        artifacts = iter(item for item in bundle.bars if item.series_id == series_id)
        def bind(values: tuple[Bar, ...]) -> tuple[Bar, ...]:
            return tuple(value.model_copy(update={"ref": ArtifactRef(
                artifact_type=(artifact := next(artifacts)).meta.artifact_type,
                artifact_id=artifact.meta.artifact_id, content_hash=artifact.meta.content_hash,
                bundle_hash=bundle.bundle_hash)}) for value in values)
        source = case.input.model_copy(update={"prior_bars": bind(case.input.prior_bars),
            "bars": bind(case.input.bars), "benchmark_bars": bind(case.input.benchmark_bars),
            "risk_kill_at": next(item for item in bundle.series
                if item.series_id == series_id).risk_kill_at})
        history_artifact = next(item for item in bundle.historical if item.series_id == series_id)
        history_ref = ArtifactRef(artifact_type=history_artifact.meta.artifact_type,
            artifact_id=history_artifact.meta.artifact_id,
            content_hash=history_artifact.meta.content_hash, bundle_hash=bundle.bundle_hash)
        history = {key: tuple(item.model_copy(update={"ref": history_ref}) for item in values)
                   for key, values in source.historical.items()}
        bindings = tuple(_bind_execution(binding, series_id, bundle)
                         for binding in source.execution_bindings)
        borrow_artifact = next(item for item in bundle.borrows if item.series_id == series_id)
        borrow_ref = ArtifactRef(artifact_type=borrow_artifact.meta.artifact_type,
            artifact_id=borrow_artifact.meta.artifact_id, content_hash=borrow_artifact.meta.content_hash,
            bundle_hash=bundle.bundle_hash)
        source = source.model_copy(update={"historical": history,
            "causal_sizing": bindings[-1].causal_sizing,
            "execution_snapshot": bindings[-1].execution_snapshot,
            "execution_bindings": bindings,
            "borrow": None if source.borrow is None else source.borrow.model_copy(update={
                "ref": borrow_ref, "effective_from": borrow_artifact.effective_from,
                "effective_until": borrow_artifact.effective_until,
                "evaluated_at": borrow_artifact.evaluated_at,
                "recalled_at": borrow_artifact.recalled_at,
                "annual_fee": borrow_artifact.annual_fee})})
        bound.append(case.model_copy(update={"input": source}))
    return tuple(bound), bundle.bundle_hash


def _bind_execution(binding: ExecutionBinding, series_id: str,
                    bundle: StrategyInputBundle) -> ExecutionBinding:
    key = f"{series_id}@{binding.cutoff.isoformat()}"
    causal = next(item for item in bundle.causal_sizing if item.series_id == key)
    target = next(item for item in bundle.target_snapshots if item.series_id == key)
    causal_ref = ArtifactRef(artifact_type=causal.meta.artifact_type,
        artifact_id=causal.meta.artifact_id, content_hash=causal.meta.content_hash,
        bundle_hash=bundle.bundle_hash)
    target_ref = ArtifactRef(artifact_type=target.meta.artifact_type,
        artifact_id=target.meta.artifact_id, content_hash=target.meta.content_hash,
        bundle_hash=bundle.bundle_hash)
    return binding.model_copy(update={
        "causal_sizing": binding.causal_sizing.model_copy(update={"ref": causal_ref}),
        "execution_snapshot": binding.execution_snapshot.model_copy(update={"ref": target_ref})})


def _bar(series_id: str, role: Literal["prior", "symbol", "benchmark"],
         source: StrategyInput, bar: Bar) -> StrategyBarInput:
    return StrategyBarInput(series_id=series_id, role=role,
        benchmark_id=source.benchmark_id if role == "benchmark" else None,
        symbol=source.benchmark_id if role == "benchmark" else source.symbol,
        session_date=bar.session_date, interval_start=bar.start, interval_end=bar.end,
        open=bar.open, high=bar.high, low=bar.low, close=bar.close, volume=bar.volume,
        complete=bar.complete, observed_at=bar.observed_at, watermark_at=bar.watermark_at,
        source_ref=ExternalRef.model_validate(bar.source_ref.model_dump(mode="json")),
        calendar_ref=ExternalRef.model_validate(bar.calendar_ref.model_dump(mode="json")),
        adjustment_factor=bar.adjustment_factor)
