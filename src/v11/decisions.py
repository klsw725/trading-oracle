from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .models import Decision, V11ContractError


def target_minute(decision: Decision) -> datetime:
    if decision.decision_ready_at < decision.watermark_at:
        raise V11ContractError("V11_DECISION_BEFORE_WATERMARK", decision.decision_id)
    if decision.decision_ready_at > decision.watermark_at + timedelta(seconds=20):
        raise V11ContractError("V11_DECISION_TOO_LATE", decision.decision_id)
    ready = decision.decision_ready_at.astimezone(timezone.utc)
    return ready.replace(second=0, microsecond=0) + timedelta(minutes=1)


def intent_is_timely(intent_recorded_at: datetime, target_at: datetime) -> bool:
    return intent_recorded_at <= target_at


def verify_intent_timing(decision: Decision, intent_recorded_at: datetime,
                         target_at: datetime) -> None:
    if not decision.decision_ready_at <= intent_recorded_at < target_at:
        raise V11ContractError("V11_STALE_INTENT", decision.decision_id)
