from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from decimal import Decimal
from math import ceil

from src.v11.canonical import canonical_hash, decimal_value, model_json, money
from src.v11.costs import verify_stress
from src.v11.models import V11ContractError
from src.v4.models import JsonValue

from .bootstrap import LOWER_INDEX, UPPER_INDEX, resampled_means
from .bootstrap_models import SeriesKind
from .contract import V14ContractError
from .fixture import load_fixture
from .manifest_models import ExperimentPlanManifest
from .metrics import build_metrics
from .pipeline import build_prd01
from .prd02_fixture import load_prd02_fixture
from .prd02_inventory_probes import inventory_checks
from .prd02_pipeline import build_prd02
from .samples import sample_sufficient
from .series import build_daily_series, generate_run
from .series_models import DailyRunInput, DailySeriesArtifact, ResearchSegment


def _kills(code: str, operation: Callable[[], None]) -> bool:
    try:
        operation()
    except V14ContractError as error:
        return error.code == code
    return False


def _kills_v11(code: str, operation: Callable[[], None]) -> bool:
    try:
        operation()
    except V11ContractError as error:
        return error.code == code
    return False


def _build_series(plan: ExperimentPlanManifest, run: DailyRunInput) -> None:
    _ = build_daily_series(plan, run)


def _verify_fixed(series: DailySeriesArtifact) -> None:
    point = next(item for item in series.points
        if decimal_value(item.baseline_costs.commission) > 0)
    stressed = point.stress_costs.model_copy(update={
        "commission": money(decimal_value(point.baseline_costs.commission) * 2)
    })
    verify_stress(point.baseline_costs, stressed)


def _cost_contract(series: tuple[DailySeriesArtifact, ...]) -> bool:
    points = tuple(point for item in series for point in item.points
        if point.traded_notional > 0)
    fixed = all(point.baseline_costs.commission == point.stress_costs.commission
        and point.baseline_costs.tax == point.stress_costs.tax for point in points)
    variable = all(all(decimal_value(stressed) == decimal_value(baseline) * 2
        for baseline, stressed in (
            (point.baseline_costs.spread, point.stress_costs.spread),
            (point.baseline_costs.slippage, point.stress_costs.slippage),
            (point.baseline_costs.participation, point.stress_costs.participation),
            (point.baseline_costs.borrow, point.stress_costs.borrow),
            (point.baseline_costs.locate, point.stress_costs.locate),
        )) for point in points)
    tax_seen = any(decimal_value(point.baseline_costs.tax) > 0 for point in points)
    short_seen = any(decimal_value(point.baseline_costs.borrow) > 0
        and decimal_value(point.baseline_costs.locate) > 0 for point in points)
    return fixed and variable and tax_seen and short_seen


def run_probes() -> tuple[
    dict[str, bool], dict[str, str], dict[str, str], int, int
]:
    prd01 = build_prd01(load_fixture())
    plan = prd01.plan
    fixture = load_prd02_fixture()
    artifacts = build_prd02()
    repeated = build_prd02()
    first_series = artifacts.series[0]
    first_metrics = artifacts.metrics[0]
    first_run = generate_run(plan, fixture.descriptors[0], fixture.policy)
    future_observations = (first_run.observations[0].model_copy(update={
        "revision_observed_at": first_run.observations[0].session_date
            + timedelta(days=1)
    }), *first_run.observations[1:])
    future_run = first_run.model_copy(update={"observations": future_observations})
    missing_run = first_run.model_copy(update={
        "official_sessions": first_run.official_sessions[:-1],
        "observations": first_run.observations[:-1]
    })
    changed_points = tuple(point.model_copy(update={"winning_trades": 0,
        "turnover": point.turnover * 2}) for point in first_series.points)
    changed_series = first_series.model_copy(update={"points": changed_points})
    changed_metrics = build_metrics(plan, changed_series)
    first_means = resampled_means(plan, first_series, SeriesKind.BASELINE)
    bootstraps = tuple(primary.bootstrap for metrics in artifacts.metrics
        for primary in (metrics.baseline, metrics.stress))
    no_trade = tuple(point for series in artifacts.series for point in series.points
        if point.traded_notional == 0)
    inventory = inventory_checks(artifacts, prd01.selection)
    checks: dict[str, bool] = {
        "strategy_metrics_exact_60": inventory["strategy_metrics_exact_60"],
        "router_comparisons_exact_4": inventory["router_comparisons_exact_4"],
        "selected_configuration_lineage":
            inventory["selected_configuration_lineage"],
        "strategy_scope_inventory": inventory["strategy_scope_inventory"],
        "router_arm_lineage": inventory["router_arm_lineage"],
        "market_segment_matrix": {(item.market.value, item.segment.value)
            for item in artifacts.series} == {("KR", "validation"),
                ("KR", "holdout"), ("US", "validation"), ("US", "holdout")},
        "calendar_aligned": all(series.official_sessions
            == tuple(point.session_date for point in series.points)
            for series in artifacts.series),
        "no_trade_days_preserved": bool(no_trade) and all(
            point.baseline_net_excess_return == 0
            and point.stress_net_excess_return == 0 for point in no_trade),
        "cost_stress_components": _cost_contract(artifacts.series),
        "sample_and_thresholds": all(metrics.sample.sufficient
            for metrics in artifacts.metrics),
        "validation_thresholds": all((metrics.sample.required_signal_days,
            metrics.sample.required_completed_trades) == (60, 150)
            for metrics in artifacts.metrics
            if metrics.segment is ResearchSegment.VALIDATION),
        "holdout_thresholds": all((metrics.sample.required_signal_days,
            metrics.sample.required_completed_trades) == (100, 300)
            for metrics in artifacts.metrics
            if metrics.segment is ResearchSegment.HOLDOUT),
        "bootstrap_contract": all(item.block_trading_days == 5
            and item.resamples == 10000
            and item.possible_block_starts == item.observation_count - 4
            and item.blocks_per_resample == ceil(item.observation_count / 5)
            for item in bootstraps),
        "empirical_indices_exact": first_metrics.baseline.bootstrap.ci_lower
            == first_means[LOWER_INDEX]
            and first_metrics.baseline.bootstrap.ci_upper
            == first_means[UPPER_INDEX],
        "p_value_inputs": all(item.one_sided_p_value
            == Decimal(1 + item.non_positive_mean_count) / Decimal(10001)
            for item in bootstraps),
        "derived_seed_dimensions": len({item.derived_seed_hash
            for item in bootstraps}) == len(bootstraps),
        "byte_identical_bootstrap": artifacts.metrics == repeated.metrics,
        "canonical_artifacts": all(value.startswith("sha256:") for value in (
            *(item.series_hash for item in artifacts.series),
            *(item.metrics_hash for item in artifacts.metrics))),
    }
    killed = {
        "sample_or": not sample_sufficient(ResearchSegment.HOLDOUT, 100, 299)
            and not sample_sufficient(ResearchSegment.HOLDOUT, 99, 300),
        "future_revision": _kills("V14_FUTURE_REVISION",
            lambda: _build_series(plan, future_run)),
        "missing_day": _kills("V14_MISSING_TRADING_DAY",
            lambda: _build_series(plan, missing_run)),
        "fixed_cost_stress": _kills_v11("V11_FIXED_COST_STRESSED",
            lambda: _verify_fixed(first_series)),
        "secondary_override": changed_metrics.baseline == first_metrics.baseline
            and changed_metrics.stress == first_metrics.stress
            and changed_metrics.secondary != first_metrics.secondary,
    }
    mutations = {key: "killed" if value else "survived"
        for key, value in killed.items()}
    metrics_json: JsonValue = [model_json(item) for item in artifacts.metrics]
    hashes = {
        "fixture_hash": canonical_hash(model_json(fixture)),
        "series_set_hash": canonical_hash([item.series_hash
            for item in artifacts.series]),
        "metrics_set_hash": canonical_hash(metrics_json),
        "router_comparison_set_hash": canonical_hash([
            item.comparison_hash for item in artifacts.router_comparisons]),
        "baseline_bootstrap_hash": first_metrics.baseline.bootstrap.bootstrap_hash,
        "stress_bootstrap_hash": first_metrics.stress.bootstrap.bootstrap_hash,
    }
    return checks, mutations, hashes, len(artifacts.metrics), \
        len(artifacts.router_comparisons)
