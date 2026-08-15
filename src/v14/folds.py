from __future__ import annotations

from typing import Annotated, Final, Literal

from pydantic import Field

from .cohort_models import JsonDate, MarketCohort
from .contract import StrictModel, V14ContractError


ANCHORS: Final = (4, 6, 8, 10)


class AnchoredFold(StrictModel):
    fold_id: Literal["fold_4_2", "fold_6_2", "fold_8_2", "fold_10_2"]
    setup_start: JsonDate
    setup_end: JsonDate
    oos_start: JsonDate
    oos_end: JsonDate
    setup_months: int
    oos_months: int


def anchored_folds(cohort: MarketCohort) -> Annotated[
    tuple[AnchoredFold, ...], Field(strict=False)
]:
    months = cohort.development.months
    if len(months) != 12:
        raise V14ContractError("V14_DEVELOPMENT_LENGTH", cohort.market.value)
    folds: list[AnchoredFold] = []
    for anchor in ANCHORS:
        folds.append(AnchoredFold.model_validate({
            "fold_id": f"fold_{anchor}_2", "setup_start": months[0].start,
            "setup_end": months[anchor - 1].end,
            "oos_start": months[anchor].start,
            "oos_end": months[anchor + 1].end,
            "setup_months": anchor, "oos_months": 2,
        }))
    return tuple(folds)
