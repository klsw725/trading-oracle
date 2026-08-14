from __future__ import annotations

from pathlib import Path

from src.v4.models import JsonValue, canonical_json
from src.v10.acceptance import build_path as build_v10
from src.v10.models import ArtifactRef as V10ArtifactRef
from src.v10.strategy_input import build_strategy_input_path, verify_strategy_input
from src.v10.strategy_input_models import BorrowArtifact, CausalSizingArtifact, HistoricalObservationArtifact, StrategyBarArtifact, StrategySeriesArtifact, TargetSnapshotArtifact
from src.v10.verifier import verify_bundle as verify_v10
from src.v11.acceptance import build_path as build_v11
from src.v11.verifier import verify_bundle as verify_v11
from src.v11.canonical import canonical_hash
from src.v11.fixture_models import Prd01Fixture, Prd02Fixture
from src.v11.models import Account

from .models import ArtifactRef, Bar, CohortFixture, StrategyInput, V12ContractError


ROOT = Path(__file__).resolve().parents[2]


def verify_upstream(fixture: CohortFixture) -> str:
    verified: set[tuple[str, str, str, str]] = set()
    bundle_hashes: list[str] = []
    account: Account | None = None
    prd01: Prd01Fixture | None = None
    prd02: Prd02Fixture | None = None
    strategy_bars: dict[str, tuple[StrategyBarArtifact, str]] = {}
    strategy_series: dict[str, StrategySeriesArtifact] = {}
    strategy_history: dict[str, HistoricalObservationArtifact] = {}
    strategy_causal: dict[str, CausalSizingArtifact] = {}
    strategy_target: dict[str, TargetSnapshotArtifact] = {}
    strategy_borrow: dict[str, BorrowArtifact] = {}
    for source in fixture.upstream_bundles:
        path = ROOT / source.path
        match source.version:  # noqa: MATCH_OK - BundleRef version literal is exhaustively covered
            case "v10":
                bundle = verify_v10(canonical_json(build_v10(path)))
                artifacts = bundle.artifacts
            case "v10_strategy_input":
                strategy_bundle = verify_strategy_input(
                    canonical_json(build_strategy_input_path(path)))
                if strategy_bundle.bundle_hash != source.bundle_hash:
                    raise V12ContractError("V12_UPSTREAM_BUNDLE_HASH", source.path)
                bundle_hashes.append(strategy_bundle.bundle_hash)
                strategy_bars.update({str(item.meta.artifact_id): (item, strategy_bundle.bundle_hash)
                                      for item in strategy_bundle.bars})
                strategy_series.update({item.series_id: item
                                        for item in strategy_bundle.series})
                strategy_history.update({item.series_id: item
                                         for item in strategy_bundle.historical})
                strategy_causal.update({item.series_id: item
                                        for item in strategy_bundle.causal_sizing})
                strategy_target.update({item.series_id: item
                                        for item in strategy_bundle.target_snapshots})
                strategy_borrow.update({item.series_id: item for item in strategy_bundle.borrows})
                continue
            case "v11":
                bundle = verify_v11(canonical_json(build_v11(path)))
                artifacts = bundle.artifacts
                if bundle.prd == 1:
                    account = Account.model_validate(bundle.artifacts[0])
                    prd01 = Prd01Fixture.model_validate(bundle.source_fixture)
                if bundle.prd == 2:
                    prd02 = Prd02Fixture.model_validate(bundle.source_fixture)
        if bundle.bundle_hash != source.bundle_hash:
            raise V12ContractError("V12_UPSTREAM_BUNDLE_HASH", source.path)
        bundle_hashes.append(bundle.bundle_hash)
        for index, artifact in enumerate(artifacts):
            if isinstance(artifact, dict) and isinstance(meta := artifact.get("meta"), dict):
                artifact_type = meta.get("artifact_type")
                artifact_id = meta.get("artifact_id")
                content_hash = meta.get("content_hash")
                if isinstance(artifact_type, str) and isinstance(artifact_id, str) and isinstance(content_hash, str):
                    verified.add((artifact_type, artifact_id, content_hash, bundle.bundle_hash))
            if source.version == "v11":
                verified.add(("v11_bundle_artifact", f"v11:{bundle.prd}:{index}",
                    canonical_hash(artifact), bundle.bundle_hash))
        for ref in source.artifact_refs:
            _verify_ref(ref, verified)
    for case in fixture.cases:
        source = case.input
        series_id = f"{case.strategy_id}:{case.scenario.value}"
        series = strategy_series.get(series_id)
        if series is None:
            raise V12ContractError("V12_UPSTREAM_SERIES", series_id)
        _verify_series(source, series)
        _verify_bars(series_id, "prior", source.prior_bars, series.prior_refs, strategy_bars)
        _verify_bars(series_id, "symbol", source.bars, series.symbol_refs, strategy_bars)
        _verify_bars(series_id, "benchmark", source.benchmark_bars,
                     series.benchmark_refs, strategy_bars)
        _verify_history(source, strategy_history[series_id])
        _verify_execution_bindings(source, series_id, strategy_causal, strategy_target)
        _verify_borrow(source, strategy_borrow[series_id])
        for bar in (*source.prior_bars, *source.bars, *source.benchmark_bars):
            _verify_ref(bar.source_ref, verified)
            _verify_ref(bar.calendar_ref, verified)
        for ref in source.eligibility_refs:
            _verify_ref(ref, verified)
        if source.borrow is not None:
            for ref in source.borrow.refs:
                _verify_ref(ref, verified)
        snapshot = source.execution_snapshot
        for ref in (snapshot.source_ref, snapshot.calendar_ref, snapshot.watermark_ref):
            _verify_ref(ref, verified)
    execution = fixture.execution
    if account != execution.account or prd01 is None or prd02 is None:
        raise V12ContractError("V12_V11_ACCOUNT_BINDING", "account")
    risk_case = prd01.cases[2]
    if (execution.historical_turnovers != risk_case.historical_turnovers
            or execution.gates != risk_case.gates):
        raise V12ContractError("V12_V11_RISK_INPUT_BINDING", "risk")
    if execution.cost_policy != prd02.cost_policy:
        raise V12ContractError("V12_V11_COST_BINDING", "cost")
    values: list[JsonValue] = []
    values.extend(sorted(bundle_hashes))
    return canonical_hash(values)


def _verify_ref(ref: ArtifactRef, verified: set[tuple[str, str, str, str]]) -> None:
    key = (ref.artifact_type, ref.artifact_id, ref.content_hash, ref.bundle_hash)
    if key not in verified:
        raise V12ContractError("V12_UPSTREAM_ARTIFACT_REF", ref.artifact_id)


def _verify_bars(series_id: str, role: str, bars: tuple[Bar, ...],
                 refs: tuple[V10ArtifactRef, ...],
                 artifacts: dict[str, tuple[StrategyBarArtifact, str]]) -> None:
    expected_ids = tuple(str(ref.artifact_id) for ref in refs)
    if tuple(bar.ref.artifact_id for bar in bars) != expected_ids:
        raise V12ContractError("V12_UPSTREAM_SERIES_ORDER", f"{series_id}:{role}")
    for bar in bars:
        found = artifacts.get(bar.ref.artifact_id)
        if found is None:
            raise V12ContractError("V12_UPSTREAM_ARTIFACT_REF", bar.ref.artifact_id)
        artifact, bundle_hash = found
        if (bar.ref.bundle_hash != bundle_hash
                or bar.ref.artifact_type != artifact.meta.artifact_type
                or bar.ref.content_hash != artifact.meta.content_hash):
            raise V12ContractError("V12_UPSTREAM_ARTIFACT_REF", bar.ref.artifact_id)
        expected_benchmark = artifact.benchmark_id if role == "benchmark" else None
        actual = (artifact.series_id, artifact.role, artifact.benchmark_id,
            artifact.symbol,
            artifact.session_date, artifact.interval_start, artifact.interval_end,
            artifact.open, artifact.high, artifact.low, artifact.close,
            artifact.volume, artifact.complete, artifact.observed_at, artifact.watermark_at,
            artifact.source_ref.model_dump(mode="json"),
            artifact.calendar_ref.model_dump(mode="json"), artifact.adjustment_factor)
        expected_symbol = artifact.benchmark_id if role == "benchmark" else artifact.symbol
        observed = (series_id, role, expected_benchmark, expected_symbol,
            bar.session_date, bar.start, bar.end, bar.open, bar.high, bar.low, bar.close,
            bar.volume, bar.complete, bar.observed_at, bar.watermark_at,
            bar.source_ref.model_dump(mode="json"), bar.calendar_ref.model_dump(mode="json"),
            bar.adjustment_factor)
        if actual != observed:
            raise V12ContractError("V12_UPSTREAM_BAR_BODY", bar.ref.artifact_id)


def _verify_series(source: StrategyInput, series: StrategySeriesArtifact) -> None:
    expected_refs = tuple(item.model_dump(mode="json") for item in series.eligibility_refs)
    observed_refs = tuple(item.model_dump(mode="json") for item in source.eligibility_refs)
    if (series.symbol != source.symbol or series.benchmark_id != source.benchmark_id
            or series.adjustment_factor != source.adjustment_factor
            or series.risk_kill_at != source.risk_kill_at
            or expected_refs != observed_refs):
        raise V12ContractError("V12_UPSTREAM_SERIES_BODY", series.series_id)


def _verify_history(source: StrategyInput, artifact: HistoricalObservationArtifact) -> None:
    observed = sorted((key, item.session_date, item.minute_slot, item.value)
        for key, values in source.historical.items() for item in values)
    expected = sorted((item.feature, item.session_date, item.minute_slot, item.value)
                      for item in artifact.observations)
    refs = {item.ref.artifact_id for values in source.historical.values()
            for item in values if item.ref is not None}
    if observed != expected or refs != {str(artifact.meta.artifact_id)}:
        raise V12ContractError("V12_UPSTREAM_HISTORY_BODY", artifact.series_id)


def _verify_execution(source: StrategyInput, causal_artifact: CausalSizingArtifact,
                      target_artifact: TargetSnapshotArtifact) -> None:
    causal, target = source.causal_sizing, source.execution_snapshot
    actual = (source.market.value, source.symbol, causal.observed_at, causal.close,
        causal.prior_turnovers, target.target_at, target.open, target.volume,
        target.source_ref.model_dump(mode="json"), target.calendar_ref.model_dump(mode="json"))
    expected = (causal_artifact.market, causal_artifact.symbol,
        causal_artifact.causal_observed_at, causal_artifact.causal_close,
        causal_artifact.prior_turnovers, target_artifact.target_at,
        target_artifact.target_open, target_artifact.target_volume,
        target_artifact.source_ref.model_dump(mode="json"),
        target_artifact.calendar_ref.model_dump(mode="json"))
    if (actual != expected or causal.ref is None or target.ref is None
            or causal.ref.artifact_id != causal_artifact.meta.artifact_id
            or target.ref.artifact_id != target_artifact.meta.artifact_id):
        raise V12ContractError("V12_UPSTREAM_EXECUTION_BODY", causal_artifact.series_id)
    if causal.observed_at > source.bars[-1].end:
        raise V12ContractError("V12_CAUSAL_LOOKAHEAD", causal_artifact.series_id)


def _verify_execution_bindings(source: StrategyInput, series_id: str,
                               causals: dict[str, CausalSizingArtifact],
                               targets: dict[str, TargetSnapshotArtifact]) -> None:
    for binding in source.execution_bindings:
        key = f"{series_id}@{binding.cutoff.isoformat()}"
        causal = causals.get(key)
        target = targets.get(key)
        if causal is None or target is None:
            raise V12ContractError("V12_EXECUTION_BINDING_MISSING", key)
        bound = source.model_copy(update={"bars": tuple(
            item for item in source.bars if item.end <= binding.cutoff),
            "causal_sizing": binding.causal_sizing,
            "execution_snapshot": binding.execution_snapshot})
        _verify_execution(bound, causal, target)


def _verify_borrow(source: StrategyInput, artifact: BorrowArtifact) -> None:
    borrow = source.borrow
    if borrow is None:
        raise V12ContractError("V12_UPSTREAM_BORROW_BODY", artifact.series_id)
    actual = (borrow.market.value, borrow.symbol, borrow.effective_from,
        borrow.effective_until, borrow.evaluated_at, borrow.recalled_at, borrow.annual_fee,
        borrow.locate, borrow.etb, borrow.shortable, borrow.regulation_known,
        tuple(ref.model_dump(mode="json") for ref in borrow.refs))
    expected = (artifact.market, artifact.symbol, artifact.effective_from,
        artifact.effective_until, artifact.evaluated_at, artifact.recalled_at,
        artifact.annual_fee,
        artifact.locate, artifact.etb, artifact.shortable, artifact.regulation_known,
        tuple(ref.model_dump(mode="json") for ref in artifact.source_refs))
    if (actual != expected or borrow.ref is None
            or borrow.ref.artifact_id != artifact.meta.artifact_id):
        raise V12ContractError("V12_UPSTREAM_BORROW_BODY", artifact.series_id)
