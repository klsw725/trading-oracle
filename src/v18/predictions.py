from .canonical import JsonValue, canonical_hash, model_json
from .models import PredictionInput, PredictionRecord
from .policies import validate_lineage


def prediction_identity_body(value: PredictionInput) -> JsonValue:
    source = model_json(value)
    if not isinstance(source, dict):
        raise AssertionError("prediction model must serialize to an object")
    result: dict[str, JsonValue] = dict(source)
    result["schema_version"] = "v18.prediction.1"
    result["source_payload_hash"] = canonical_hash(source)
    return result


def build_prediction(value: PredictionInput) -> PredictionRecord:
    identity = prediction_identity_body(value)
    source_hash = canonical_hash(model_json(value))
    return PredictionRecord(
        schema_version="v18.prediction.1",
        prediction_id=canonical_hash(identity),
        recommendation_id=value.recommendation_id,
        namespace=value.namespace,
        lineage=value.lineage,
        prediction_session=value.prediction_session,
        horizon_sessions=value.horizon_sessions,
        action=value.action,
        reference_price_minor=value.reference_price_minor,
        perspective_scores=value.perspective_scores,
        perspective_scores_as_of=value.perspective_scores_as_of,
        recorded_as_of=value.recorded_as_of,
        source_payload_hash=source_hash,
        current_state="REGISTERED",
    )


def prediction_semantic_key(value: PredictionRecord) -> str:
    return canonical_hash(
        {
            "recommendation_id": value.recommendation_id,
            "schema_version": "v18.prediction-semantic-key.1",
        }
    )


def validate_prediction_record(value: PredictionRecord) -> None:
    validate_lineage(value.lineage)
    source = PredictionInput(
        schema_version="v18.normalized-recommendation.1",
        recommendation_id=value.recommendation_id,
        namespace=value.namespace,
        lineage=value.lineage,
        prediction_session=value.prediction_session,
        horizon_sessions=value.horizon_sessions,
        action=value.action,
        reference_price_minor=value.reference_price_minor,
        perspective_scores=value.perspective_scores,
        perspective_scores_as_of=value.perspective_scores_as_of,
        recorded_as_of=value.recorded_as_of,
    )
    expected = build_prediction(source)
    if value != expected:
        from .errors import V18Error

        raise V18Error("PREDICTION_IDENTITY_CONFLICT", value.recommendation_id)
