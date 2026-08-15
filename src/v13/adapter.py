from __future__ import annotations

from pathlib import Path
from decimal import Decimal
from functools import lru_cache

from src.v10.build import build_fixture as build_v10
from src.v10.fixture_models import Prd04Fixture
from src.v10.verifier import verify_bundle as verify_v10
from src.v11.build import build_fixture as build_v11
from src.v11.canonical import canonical_hash, model_json, parse_json
from src.v11.models import Account, Market, Side
from src.v11.verifier import verify_bundle as verify_v11
from src.v12.artifacts import TradeAttribution
from src.v12.build import build_fixture as build_v12
from src.v12.bundle import ArtifactBundle as V12Bundle
from src.v12.models import CohortFixture, Scenario
from src.v12.verifier import verify_bundle as verify_v12
from src.v4.models import JsonValue, canonical_json
from src.v13.context import build_context_snapshot
from src.v13.models import BoundCandidateEvidence, CandidateLineage, V13ContractError
from src.v13.prd03_models import SwitchFixture
from src.v13.prd04_models import (
    AdapterOutput,
    Prd04InputDescriptor,
    Prd04SourceFixture,
    UpstreamProof,
)
from src.v13.prd04_recorded import request_for, response_for
from src.v13.prd02_models import RecordedResponse


def load_descriptor(path: Path) -> Prd04InputDescriptor:
    try:
        return Prd04InputDescriptor.model_validate_json(path.read_bytes())
    except OSError as error:
        raise V13ContractError("V13_PRD04_INPUT", str(error)) from error


def compile_source(descriptor: Prd04InputDescriptor, root: Path) -> Prd04SourceFixture:
    values = tuple(_read(root / relative) for relative in (
        descriptor.v10_context_path, descriptor.v11_account_path,
        descriptor.v11_execution_path, descriptor.v12_cohort_path,
        descriptor.switch_path))
    v10_value, account_value, execution_value, v12_value, switch_value = values
    preliminary = Prd04SourceFixture(schema_version="v13.prd04.source.1",
        v10_context_fixture=v10_value, v11_account_fixture=account_value,
        v11_execution_fixture=execution_value, v12_cohort_fixture=v12_value,
        switch_fixture=SwitchFixture.model_validate_json(canonical_json(switch_value)),
        candidate_fixture=(), canonical_symbols=(),
        recorded_response=RecordedResponse(outcome="response",
            model_id="gpt-5.1-codex", raw_response=b"{}"))
    adapted = _adapt(preliminary, compare_derived=False)
    request = request_for(adapted.router_candidates, adapted.context)
    return preliminary.model_copy(update={"candidate_fixture": adapted.candidates,
        "canonical_symbols": adapted.canonical_symbols,
        "recorded_response": response_for(request)})


def adapt_source(source: Prd04SourceFixture) -> AdapterOutput:
    return _adapt_cached(canonical_json(model_json(source)))


@lru_cache(maxsize=2)
def _adapt_cached(payload: bytes) -> AdapterOutput:
    source = Prd04SourceFixture.model_validate_json(payload)
    return _adapt(source, compare_derived=True)


def _adapt(source: Prd04SourceFixture, compare_derived: bool) -> AdapterOutput:
    v10_bundle = verify_v10(canonical_json(build_v10(source.v10_context_fixture)))
    account_bundle = verify_v11(canonical_json(build_v11(source.v11_account_fixture)))
    execution_bundle = verify_v11(canonical_json(build_v11(source.v11_execution_fixture)))
    v12_bundle = verify_v12(canonical_json(build_v12(source.v12_cohort_fixture)))
    account = Account.model_validate(account_bundle.artifacts[0])
    cohort = CohortFixture.model_validate(source.v12_cohort_fixture)
    if cohort.execution.account != account:
        raise V13ContractError("V13_ACCOUNT_BINDING", account_bundle.bundle_hash)
    candidates = _candidates(v12_bundle, cohort, canonical_hash(model_json(account)))
    router_cutoff = max(item.cutoff for item in candidates)
    router_candidates = tuple(item for item in candidates if item.cutoff == router_cutoff)
    symbols = tuple(sorted({item.symbol for item in candidates}))
    context = build_context_snapshot(
        Prd04Fixture.model_validate(source.v10_context_fixture), router_candidates)
    if compare_derived and (source.candidate_fixture != candidates
            or source.canonical_symbols != symbols
            or source.recorded_response != response_for(request_for(router_candidates, context))):
        raise V13ContractError("V13_SOURCE_DERIVED_MISMATCH", "candidate/context/response")
    evaluations = v12_bundle.run.evaluations
    proof = UpstreamProof(v10_context_bundle_hash=v10_bundle.bundle_hash,
        v11_account_bundle_hash=account_bundle.bundle_hash,
        v11_execution_bundle_hash=execution_bundle.bundle_hash,
        v12_bundle_hash=v12_bundle.bundle_hash, v12_run_hash=v12_bundle.run.manifest_hash,
        verified_account_hash=canonical_hash(model_json(account)),
        strategy_count=len({item.strategy_id for item in evaluations}),
        long_trade_count=sum(item.candidate.side.value == "long" for item in v12_bundle.run.trades),
        short_trade_count=sum(item.candidate.side.value == "short" for item in v12_bundle.run.trades),
        namespace_count=len({item.manifest.owner_namespace for item in v12_bundle.run.trades}),
        happy_count=len({item.case_id for item in evaluations if item.scenario is Scenario.HAPPY}),
        no_signal_count=len({item.case_id for item in evaluations if item.scenario is Scenario.NO_SIGNAL}),
        missing_count=len({item.case_id for item in evaluations if item.scenario is Scenario.MISSING}))
    return AdapterOutput(candidates=candidates, router_candidates=router_candidates,
        canonical_symbols=symbols,
        account=account, context=context, upstream=proof)


def _candidates(
    bundle: V12Bundle, cohort: CohortFixture, account_hash: str
) -> tuple[BoundCandidateEvidence, ...]:
    candidates = tuple(_candidate(trade, cohort, bundle, account_hash)
        for trade in bundle.run.trades)
    if any(item.candidate.lifecycle != "execution_feasible_candidate"
            for item in bundle.run.trades):
        raise V13ContractError("V13_EXECUTION_FEASIBILITY", bundle.bundle_hash)
    return tuple(sorted(candidates, key=lambda item: item.candidate_id))


def _candidate(
    trade: TradeAttribution, cohort: CohortFixture, bundle: V12Bundle,
    account_hash: str,
) -> BoundCandidateEvidence:
    ref = trade.causal_sizing.ref
    if ref is None:
        raise V13ContractError("V13_CAUSAL_REF", trade.candidate.candidate_id)
    return BoundCandidateEvidence(candidate_id=trade.candidate.candidate_id,
        market=Market(trade.candidate.market.value), symbol=trade.candidate.symbol,
        sector=trade.decision.sector, strategy_id=trade.candidate.strategy_id,
        strategy_version=trade.candidate.strategy_version,
        side=Side(trade.candidate.side.value), cutoff=trade.candidate.signal_cutoff,
        watermark_at=trade.decision.watermark_at,
        decision_ready_at=trade.decision.decision_ready_at,
        deterministic_score=trade.candidate.deterministic_score,
        llm_score=None, confidence=None, hard_veto_verified=False,
        item_valid=False, abstain=False, target_quantity=trade.risk.quantity,
        reference_price=Decimal(trade.risk.reference_price),
        expected_cost=Decimal(trade.risk.reservation.expected_cost)
            if trade.risk.reservation else Decimal(0),
        candidate_returns=(), gates=cohort.execution.gates,
        lineage=CandidateLineage(v12_bundle_hash=bundle.bundle_hash,
            v12_run_hash=bundle.run.manifest_hash,
            v12_candidate_id=trade.candidate.candidate_id,
            risk_input_hash=trade.risk.input_hash,
            causal_artifact_id=ref.artifact_id, causal_content_hash=ref.content_hash,
            causal_bundle_hash=ref.bundle_hash, verified_account_hash=account_hash))


def _read(path: Path) -> JsonValue:
    try:
        return parse_json(path.read_bytes())
    except OSError as error:
        raise V13ContractError("V13_PRD04_INPUT", str(error)) from error
