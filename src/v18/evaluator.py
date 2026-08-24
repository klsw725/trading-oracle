from .canonical import JsonValue, canonical_hash, model_json
from .errors import V18Error
from .models import (
    Action,
    AdjustedClose,
    CalendarSession,
    OutcomeEvaluation,
    PredictionRecord,
    Verdict,
)
from .policies import EvaluatorPolicy
from .sessions import require_mature, target_session


def round_half_away_from_zero(numerator: int, denominator: int) -> int:
    magnitude, remainder = divmod(abs(numerator), denominator)
    rounded = magnitude + (1 if remainder * 2 >= denominator else 0)
    return rounded if numerator >= 0 else -rounded


def return_bps(reference_price_minor: int, target_price_minor: int) -> int:
    return round_half_away_from_zero(
        (target_price_minor - reference_price_minor) * 10_000,
        reference_price_minor,
    )


def verdict(action: Action, value_bps: int, neutral_band_bps: int) -> Verdict:
    match action:  # noqa: MATCH_OK - Action is a closed enum.
        case Action.BUY:
            if value_bps > neutral_band_bps:
                return Verdict.CORRECT
            if value_bps < -neutral_band_bps:
                return Verdict.INCORRECT
            return Verdict.NEUTRAL
        case Action.SELL:
            if value_bps < -neutral_band_bps:
                return Verdict.CORRECT
            if value_bps > neutral_band_bps:
                return Verdict.INCORRECT
            return Verdict.NEUTRAL
        case Action.HOLD:
            return Verdict.CORRECT if abs(value_bps) <= neutral_band_bps else Verdict.INCORRECT


def exact_adjusted_close(
    prediction: PredictionRecord,
    target: CalendarSession,
    prices: tuple[AdjustedClose, ...],
) -> AdjustedClose:
    observed = tuple(
        item
        for item in prices
        if item.session == target.session and item.namespace.symbol == prediction.namespace.symbol
    )
    rows = tuple(item for item in observed if item.namespace == prediction.namespace)
    if not rows and observed:
        raise V18Error("NAMESPACE_MISMATCH", prediction.prediction_id)
    if not rows:
        raise V18Error("TARGET_PRICE_MISSING", target.session)
    if len(rows) != 1:
        raise V18Error("TARGET_PRICE_AMBIGUOUS", target.session)
    price = rows[0]
    if price.namespace != prediction.namespace:
        raise V18Error("NAMESPACE_MISMATCH", prediction.prediction_id)
    if price.adjustment_version != prediction.lineage.price_adjustment_version:
        raise V18Error("PRICE_ADJUSTMENT_MISMATCH", price.adjustment_version)
    if price.adjusted_close_minor <= 0:
        raise V18Error("TARGET_PRICE_MISSING", target.session)
    if price_content_hash(prices) != price.dataset_hash:
        raise V18Error("PRICE_ADJUSTMENT_MISMATCH", "dataset hash")
    return price


def price_content_hash(prices: tuple[AdjustedClose, ...]) -> str:
    versions = {item.adjustment_version for item in prices}
    if len(versions) != 1:
        raise V18Error("PRICE_ADJUSTMENT_MISMATCH", "adjustment versions")
    rows: list[JsonValue] = [
        {
            "adjusted_close_minor": item.adjusted_close_minor,
            "currency": item.namespace.currency.value,
            "market": item.namespace.market.value,
            "session": item.session,
            "symbol": item.namespace.symbol,
        }
        for item in sorted(
            prices,
            key=lambda value: (
                value.namespace.market.value,
                value.namespace.symbol,
                value.session,
            ),
        )
    ]
    return canonical_hash(
        {
            "adjustment_version": next(iter(versions)),
            "prices": rows,
            "schema_version": "v18.adjusted-close-dataset.1",
        }
    )


def evaluate_prediction(
    prediction: PredictionRecord,
    sessions: tuple[CalendarSession, ...],
    prices: tuple[AdjustedClose, ...],
    as_of: str,
    policy: EvaluatorPolicy,
) -> OutcomeEvaluation:
    target = target_session(prediction, sessions)
    require_mature(target, as_of)
    price = exact_adjusted_close(prediction, target, prices)
    value_bps = return_bps(prediction.reference_price_minor, price.adjusted_close_minor)
    body: JsonValue = {
        "calendar_hash": target.calendar_hash,
        "evaluator_policy_version": policy.version,
        "maturity_as_of": as_of,
        "prediction_id": prediction.prediction_id,
        "price_dataset_hash": price.dataset_hash,
        "return_bps": value_bps,
        "schema_version": "v18.outcome.1",
        "target_adjusted_price_minor": price.adjusted_close_minor,
        "target_session": target.session,
        "verdict": verdict(prediction.action, value_bps, policy.neutral_band_bps).value,
    }
    outcome_id = canonical_hash(body)
    outcome = OutcomeEvaluation(
        outcome_id=outcome_id,
        prediction_id=prediction.prediction_id,
        target_session=target.session,
        target_adjusted_price_minor=price.adjusted_close_minor,
        return_bps=value_bps,
        verdict=verdict(prediction.action, value_bps, policy.neutral_band_bps),
        maturity_as_of=as_of,
        evaluator_policy_version=policy.version,
        calendar_hash=target.calendar_hash,
        price_dataset_hash=price.dataset_hash,
    )
    if canonical_hash(model_json(outcome, exclude={"outcome_id"})) != canonical_hash(body):
        raise V18Error("OUTCOME_HASH_MISMATCH", prediction.prediction_id)
    return outcome
