from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

from .models import MinuteBar, V10ContractError


WATERMARK_DELAY: Final = timedelta(seconds=10)


@dataclass(frozen=True, slots=True)
class WatermarkPolicy:
    max_observation_lag_seconds: int


def watermark_at(interval_end: datetime) -> datetime:
    return interval_end + WATERMARK_DELAY


def verify_evaluation(interval_end: datetime, evaluated_at: datetime) -> datetime:
    watermark = watermark_at(interval_end)
    if evaluated_at < watermark:
        raise V10ContractError("V10_WATERMARK_EARLY", evaluated_at.isoformat())
    return watermark


def arrived_by(bar: MinuteBar, watermark: datetime) -> bool:
    return bar.observed_at <= watermark


def is_fresh(bar: MinuteBar, policy: WatermarkPolicy) -> bool:
    lag = (bar.observed_at - bar.interval_end).total_seconds()
    return lag <= policy.max_observation_lag_seconds
