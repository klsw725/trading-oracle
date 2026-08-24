from .cohorts import load_outcome
from .models import CohortManifest, Verdict
from .policies import WeightPolicy
from .repository import MeasurementRepository


def perspective_contributions(
    repository: MeasurementRepository,
    manifest: CohortManifest,
    policy: WeightPolicy,
) -> dict[str, int]:
    result = {perspective: 0 for perspective in policy.perspectives}
    verdict_sign = {
        Verdict.CORRECT: 1,
        Verdict.INCORRECT: -1,
        Verdict.NEUTRAL: 0,
    }
    for prediction_id in manifest.member_ids:
        prediction = repository.get_prediction(prediction_id)
        outcome, _ = load_outcome(repository, prediction_id)
        sign = verdict_sign[outcome.verdict]
        for perspective in policy.perspectives:
            score = int(prediction.perspective_scores[perspective].replace(".", ""))
            result[perspective] += sign * score
    return result
