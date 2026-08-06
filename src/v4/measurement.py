from dataclasses import dataclass, replace
from typing import assert_never

from .measurement_parsing import (
    CorporateActionProvenance as CorporateActionProvenance, CostModel as CostModel,
    MarketContextView as MarketContextView, MeasurementParseError as MeasurementParseError,
    MeasurementRequest as MeasurementRequest, RegularSessionView as RegularSessionView,
    ReturnCloseEvidence as ReturnCloseEvidence, SessionProgress as SessionProgress,
    parse_measurement_request as parse_measurement_request,
)
from .models import Action, MeasurementState, MetricValue, QualityState


@dataclass(frozen=True, slots=True)
class MeasurementResult:
    state: MeasurementState
    horizon: int
    benchmark_id: str
    entry_session: RegularSessionView | None
    target_exit_session: RegularSessionView | None
    actual_exit_session: RegularSessionView | None
    price_lag_sessions: int | None
    session_progress: SessionProgress | None
    closed_sessions_after_entry: int | None
    remaining_sessions: int | None
    gross_absolute_return: MetricValue
    gross_benchmark_excess_return: MetricValue
    net_execution_return: MetricValue
    net_execution_benchmark_excess_return: MetricValue
    return_basis: str | None
    cost_model_version: str | None
    reason: str | None


def _empty_result(
    request: MeasurementRequest,
    state: MeasurementState,
    reason: str,
    selection: tuple[RegularSessionView | None, RegularSessionView | None],
) -> MeasurementResult:
    unavailable = MetricValue(QualityState.UNKNOWN, None, reason)
    closed: int | None = None
    if state is MeasurementState.PENDING:
        if request.session_progress is not None:
            closed = request.session_progress.closed_sessions_after_entry
        elif selection[0] is not None:
            closed = sum(
                item.session_date > selection[0].session_date
                for item in request.context.ordered_regular_sessions
            )
    return MeasurementResult(
        state=state,
        horizon=request.horizon,
        benchmark_id=request.context.benchmark_id,
        entry_session=selection[0],
        target_exit_session=selection[1],
        actual_exit_session=None,
        price_lag_sessions=None,
        session_progress=request.session_progress,
        closed_sessions_after_entry=closed,
        remaining_sessions=max(request.horizon - closed, 0) if closed is not None else None,
        gross_absolute_return=unavailable,
        gross_benchmark_excess_return=unavailable,
        net_execution_return=unavailable,
        net_execution_benchmark_excess_return=unavailable,
        return_basis=None,
        cost_model_version=None,
        reason=reason,
    )


def _direction(action: Action) -> float:
    match action:
        case Action.BUY:
            return 1.0
        case Action.SELL:
            return -1.0
        case Action.HOLD | Action.BLOCKED:
            return 0.0
        case remaining:
            if remaining is Action.CANDIDATE_REJECTED:
                return 0.0
            assert_never(remaining)


def measure(request: MeasurementRequest) -> MeasurementResult:
    sessions = request.context.ordered_regular_sessions
    emitted_date = request.emitted_at.astimezone(request.context.timezone).date()
    entry_index = next(
        (index for index, item in enumerate(sessions) if item.session_date > emitted_date),
        None,
    )
    if entry_index is None:
        return _empty_result(
            request, MeasurementState.PENDING, "target_exit_session_not_closed"
            if request.session_progress else "entry_session_not_closed",
            (None, None)
        )
    entry = sessions[entry_index]
    if (
        request.session_progress is not None
        and request.session_progress.entry_session != entry.session_date
    ):
        return _empty_result(
            request, MeasurementState.INSUFFICIENT_DATA,
            "session_progress_entry_mismatch", (entry, None)
        )
    target_index = entry_index + request.horizon
    if target_index >= len(sessions):
        return _empty_result(
            request, MeasurementState.PENDING, "target_exit_session_not_closed",
            (entry, None)
        )
    target = sessions[target_index]
    selection = (entry, target)
    if request.instrument_prices is None:
        state = (
            MeasurementState.INSUFFICIENT_DATA
            if len(sessions) - target_index - 1 >= 5
            else MeasurementState.PENDING
        )
        return _empty_result(request, state, "instrument_exit_price_missing", selection)
    if request.corporate_action_provenance is None:
        return _empty_result(
            request, MeasurementState.INSUFFICIENT_DATA,
            "corporate_action_provenance_missing", selection
        )
    instrument = request.instrument_prices
    if instrument.entry_session != entry.session_date:
        return _empty_result(
            request, MeasurementState.INSUFFICIENT_DATA,
            "instrument_entry_session_mismatch", selection
        )
    if instrument.target_exit_session != target.session_date:
        return _empty_result(
            request, MeasurementState.INSUFFICIENT_DATA,
            "instrument_target_session_mismatch", selection
        )
    actual = target
    price_lag = 0
    actual_date = instrument.actual_exit_session
    if actual_date is not None:
        actual_index = next(
            (
                index
                for index, item in enumerate(sessions)
                if item.session_date == actual_date
            ),
            None,
        )
        if (
            actual_index is None
            or actual_index <= target_index
            or actual_index > target_index + 5
        ):
            return _empty_result(
                request,
                MeasurementState.INSUFFICIENT_DATA,
                "actual_exit_outside_five_session_grace",
                selection,
            )
        actual = sessions[actual_index]
        price_lag = actual_index - target_index
    if (
        instrument.as_of < actual.regular_close_at
        or request.corporate_action_provenance.checked_through < actual.session_date
    ):
        return _empty_result(
            request,
            MeasurementState.INSUFFICIENT_DATA,
            "price_or_corporate_action_provenance_stale",
            selection,
        )

    instrument_return = (
        instrument.exit_total_return_close
        / instrument.entry_total_return_close
        - 1
    )
    gross_absolute = MetricValue(QualityState.AVAILABLE, instrument_return)
    if request.benchmark_prices is None:
        return replace(
            _empty_result(
                request, MeasurementState.INSUFFICIENT_CONTEXT,
                "benchmark_prices_missing", selection
            ),
            actual_exit_session=actual,
            price_lag_sessions=price_lag,
            gross_absolute_return=gross_absolute,
            return_basis=request.corporate_action_provenance.return_basis,
            cost_model_version=request.cost_model.version if request.cost_model else None,
        )
    benchmark = request.benchmark_prices
    if benchmark.entry_session != entry.session_date:
        return _empty_result(
            request, MeasurementState.INSUFFICIENT_DATA,
            "benchmark_entry_session_mismatch", selection
        )
    if benchmark.target_exit_session != target.session_date:
        return _empty_result(
            request, MeasurementState.INSUFFICIENT_DATA,
            "benchmark_target_session_mismatch", selection
        )
    if benchmark.actual_exit_session is not None:
        return _empty_result(
            request, MeasurementState.INSUFFICIENT_DATA,
            "benchmark_must_remain_bound_to_target_session", selection
        )

    benchmark_return = (
        benchmark.exit_total_return_close
        / benchmark.entry_total_return_close
        - 1
    )
    if benchmark.as_of < target.regular_close_at:
        return replace(
            _empty_result(
                request,
                MeasurementState.INSUFFICIENT_CONTEXT,
                "benchmark_prices_stale",
                selection,
            ),
            actual_exit_session=actual,
            price_lag_sessions=price_lag,
            gross_absolute_return=gross_absolute,
            return_basis=request.corporate_action_provenance.return_basis,
        )
    direction = _direction(request.action)
    directional_return = direction * instrument_return
    directional_benchmark = direction * benchmark_return
    gross_excess = MetricValue(
        QualityState.AVAILABLE, directional_return - directional_benchmark
    )
    if request.action not in (Action.BUY, Action.SELL):
        net_return = MetricValue(
            QualityState.NOT_APPLICABLE, None, "action_has_no_execution_pnl"
        )
        net_excess = net_return
    elif request.cost_model is None:
        net_return = MetricValue(QualityState.UNKNOWN, None, "cost_model_missing")
        net_excess = net_return
    else:
        net_value = directional_return - request.cost_model.total_rate
        net_return = MetricValue(QualityState.AVAILABLE, net_value)
        net_excess = MetricValue(
            QualityState.AVAILABLE, net_value - directional_benchmark
        )

    return replace(
        _empty_result(request, MeasurementState.MATURED, "", selection),
        actual_exit_session=actual,
        price_lag_sessions=price_lag,
        closed_sessions_after_entry=request.horizon + price_lag,
        remaining_sessions=0,
        gross_absolute_return=gross_absolute,
        gross_benchmark_excess_return=gross_excess,
        net_execution_return=net_return,
        net_execution_benchmark_excess_return=net_excess,
        return_basis=request.corporate_action_provenance.return_basis,
        cost_model_version=request.cost_model.version if request.cost_model else None,
        reason=None,
    )
