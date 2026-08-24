from .canonical import JsonValue, canonical_hash
from .errors import V18Error
from .models import CalendarSession, PredictionRecord, SessionStatus


def calendar_content_hash(sessions: tuple[CalendarSession, ...]) -> str:
    versions = {item.calendar_version for item in sessions}
    if len(versions) != 1:
        raise V18Error("CALENDAR_IDENTITY_MISMATCH", "calendar versions")
    rows: list[JsonValue] = [
        {
            "close_at": item.close_at,
            "market": item.market.value,
            "session": item.session,
            "status": item.status.value,
        }
        for item in sorted(sessions, key=lambda value: (value.market.value, value.session))
    ]
    return canonical_hash(
        {
            "calendar_version": next(iter(versions)),
            "schema_version": "v18.official-session-calendar.1",
            "sessions": rows,
        }
    )


def target_session(
    prediction: PredictionRecord, sessions: tuple[CalendarSession, ...]
) -> CalendarSession:
    observed_hash = calendar_content_hash(sessions)
    if observed_hash != prediction.lineage.calendar_hash:
        raise V18Error("CALENDAR_IDENTITY_MISMATCH", observed_hash)
    matching = tuple(item for item in sessions if item.market is prediction.namespace.market)
    if any(
        item.calendar_version != prediction.lineage.calendar_version
        or item.calendar_hash != prediction.lineage.calendar_hash
        for item in matching
    ):
        raise V18Error("CALENDAR_IDENTITY_MISMATCH", prediction.prediction_id)
    dates = [item.session for item in matching]
    if len(dates) != len(set(dates)):
        raise V18Error("TARGET_SESSION_UNRESOLVED", "duplicate calendar session")
    prediction_rows = tuple(
        item for item in matching if item.session == prediction.prediction_session
    )
    if (
        len(prediction_rows) != 1
        or prediction_rows[0].status not in {SessionStatus.OPEN, SessionStatus.EARLY_CLOSE}
    ):
        raise V18Error("TARGET_SESSION_UNRESOLVED", prediction.prediction_session)
    open_after = tuple(
        item
        for item in sorted(matching, key=lambda value: value.session)
        if item.session > prediction.prediction_session
        and item.status in {SessionStatus.OPEN, SessionStatus.EARLY_CLOSE}
    )
    if len(open_after) < prediction.horizon_sessions:
        raise V18Error("TARGET_SESSION_UNRESOLVED", prediction.prediction_id)
    result = open_after[prediction.horizon_sessions - 1]
    if result.close_at is None:
        raise V18Error("TARGET_SESSION_UNRESOLVED", result.session)
    return result


def require_mature(target: CalendarSession, as_of: str) -> None:
    if target.close_at is None:
        raise V18Error("TARGET_SESSION_UNRESOLVED", target.session)
    if as_of < target.close_at:
        raise V18Error("OUTCOME_IMMATURE", target.session)


def next_effective_session(
    market_sessions: tuple[CalendarSession, ...], created_as_of: str
) -> CalendarSession:
    eligible = tuple(
        item
        for item in sorted(market_sessions, key=lambda value: value.session)
        if item.status in {SessionStatus.OPEN, SessionStatus.EARLY_CLOSE}
        and item.close_at is not None
        and item.close_at > created_as_of
    )
    if not eligible:
        raise V18Error("CANDIDATE_EFFECTIVE_SESSION_INVALID", created_as_of)
    return eligible[0]
