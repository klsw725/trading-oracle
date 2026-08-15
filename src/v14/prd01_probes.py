from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from decimal import Decimal

from pydantic import ValidationError

from src.v11.canonical import canonical_hash, model_json
from src.v12.models import Market
from src.v12.registry import REGISTRY
from src.v13.policy import policy_grid

from .cohort import expand_descriptor, freeze_cohort
from .cohort_models import MonthRow
from .contract import V14ContractError
from .fixture import load_fixture
from .pipeline import build_prd01
from .selection import build_development_selection, select_router, select_strategy
from .selection_models import DevelopmentGrid, SelectionCandidate, SelectionInputs
from .tiebreak import choose, quantized_median


def _candidate(
    candidate_id: str, value: str, turnover: str
) -> SelectionCandidate:
    return SelectionCandidate(canonical_id=candidate_id,
        fold_oos_net_excess_returns=(Decimal(value),) * 4,
        turnover=Decimal(turnover))


def _kills(code: str, operation: Callable[[], None]) -> bool:
    try:
        operation()
    except V14ContractError as error:
        return error.code == code
    return False


def _freeze(rows: tuple[MonthRow, ...]) -> None:
    _ = freeze_cohort(rows)


def _strategy(grid: DevelopmentGrid) -> None:
    _ = select_strategy("long_orb_15m", grid)


def _router(grid: DevelopmentGrid) -> None:
    _ = select_router(grid)


def _leakage_blocked(candidate: SelectionCandidate) -> bool:
    try:
        _ = DevelopmentGrid.model_validate({
            "segment": "validation", "candidates": (candidate,)
        })
    except ValidationError:
        return True
    return False


def run_probes() -> tuple[
    dict[str, bool], dict[str, str], dict[str, str]
]:
    fixture = load_fixture()
    artifacts = build_prd01(fixture)
    repeated = build_prd01(fixture)
    selection_without_payloads = build_development_selection(
        artifacts.cohort.cohort_hash, fixture.selection
    )
    rows = tuple(
        row for descriptor in fixture.cohorts for row in expand_descriptor(descriptor)
    )
    kr_rows = tuple(row for row in rows if row.market is Market.KR)
    gap_rows = tuple(
        row.model_copy(update={"context_snapshot_hash": ""}) if index == 5 else row
        for index, row in enumerate(rows)
    )
    overlap_rows = tuple(
        row.model_copy(update={"start": kr_rows[0].start})
        if row is kr_rows[1] else row for row in rows
    )
    future_rows = tuple(
        row.model_copy(update={"observed_at": row.end + timedelta(days=1)})
        if row is kr_rows[2] else row for row in rows
    )
    strategy_spec = REGISTRY[0]
    strategy_candidates = tuple(
        _candidate(item.parameter_set_id, "0.01", "0.01")
        for item in strategy_spec.parameter_sets
    )
    fifth_grid = DevelopmentGrid(segment="development", candidates=(
        *strategy_candidates, _candidate("L15_E", "0.01", "0.01")))
    router_candidates = tuple(
        _candidate(item.policy_hash, "0.01", "0.01") for item in policy_grid()
    )
    seventh_grid = DevelopmentGrid(segment="development", candidates=(
        *router_candidates, _candidate("sha256:seventh", "0.01", "0.01")))
    half_even_low = _candidate("low", "1.000000005", "0.01")
    half_even_high = _candidate("high", "1.000000015", "0.01")
    turnover_winner = choose((_candidate("high", "0.1", "0.02"),
        _candidate("low", "0.1", "0.01")), 4)
    id_winner = choose((_candidate("zeta", "0.1", "0.01"),
        _candidate("alpha", "0.1", "0.01")), 4)
    folds_by_market = tuple(artifacts.folds[index:index + 4]
        for index in range(0, len(artifacts.folds), 4))
    checks = {
        "exact_12_6_6": all((len(item.development.months),
            len(item.validation.months), len(item.holdout.months)) == (12, 6, 6)
            for item in artifacts.cohort.markets),
        "market_isolation": tuple(item.market for item in artifacts.cohort.markets)
            == (Market.KR, Market.US),
        "independent_boundaries": artifacts.cohort.markets[0].development.start
            != artifacts.cohort.markets[1].development.start,
        "anchored_folds": all(tuple((fold.setup_months, fold.oos_months)
            for fold in folds) == ((4, 2), (6, 2), (8, 2), (10, 2))
            for folds in folds_by_market),
        "strategy_inventory": all(len(item.strategies) == 15
            for item in artifacts.selection.markets),
        "router_policy_inventory": len(policy_grid()) == 6,
        "market_selection_independent": artifacts.selection.markets[0]
            .strategies[0].selected.canonical_id != artifacts.selection.markets[1]
            .strategies[0].selected.canonical_id,
        "half_even_8_places": quantized_median(half_even_low)
            == Decimal("1.00000000") and quantized_median(half_even_high)
            == Decimal("1.00000002"),
        "turnover_tiebreak": turnover_winner.canonical_id == "low",
        "canonical_id_tiebreak": id_winner.canonical_id == "alpha",
        "development_only_input": set(SelectionInputs.model_fields)
            == {"markets"},
        "selection_reproduces": artifacts.selection == repeated.selection
            == selection_without_payloads,
        "canonical_artifacts": all(value.startswith("sha256:") for value in (
            artifacts.cohort.cohort_hash, artifacts.selection.selection_hash,
            artifacts.plan.manifest_hash)),
        "manifest_complete": artifacts.plan.bootstrap.block_trading_days == 5
            and artifacts.plan.bootstrap.resamples == 10000
            and len(artifacts.plan.hypotheses.holm_family_ids) == 14,
        "primary_and_freeze_stage": artifacts.plan.hypotheses.primary_id
            == "long_orb_15m" and artifacts.plan.hypotheses
            .router_enabled_set_freeze_stage == "after_validation",
    }
    killed = {
        "context_gap": _kills("V14_CONTEXT_CONTINUITY",
            lambda: _freeze(gap_rows)),
        "segment_overlap": _kills("V14_SEGMENT_OVERLAP",
            lambda: _freeze(overlap_rows)),
        "future_row": _kills("V14_POINT_IN_TIME", lambda: _freeze(future_rows)),
        "strategy_fifth_grid": _kills("V14_GRID_OVERFLOW",
            lambda: _strategy(fifth_grid)),
        "router_seventh_policy": _kills("V14_GRID_OVERFLOW",
            lambda: _router(seventh_grid)),
        "validation_leakage": _leakage_blocked(strategy_candidates[0]),
    }
    mutations = {key: "killed" if value else "survived"
        for key, value in killed.items()}
    hashes = {
        "fixture_hash": canonical_hash(model_json(fixture)),
        "cohort_hash": artifacts.cohort.cohort_hash,
        "selection_hash": artifacts.selection.selection_hash,
        "plan_manifest_hash": artifacts.plan.manifest_hash,
    }
    return checks, mutations, hashes
