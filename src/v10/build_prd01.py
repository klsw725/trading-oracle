from __future__ import annotations

from pydantic import ValidationError
from zoneinfo import ZoneInfo

from src.v4.models import JsonValue

from .bundle import seal_bundle
from .calendar import build_calendar
from .canonical import artifact_ref, model_json, reject_forbidden
from .fixture_models import MinuteInput, Prd01Fixture
from .minute import build_minute, build_minutes
from .models import ArtifactId, ArtifactMeta, ContentHash, MarketCalendarSnapshot, SessionState, SourceObservation, V10ContractError
from .sources import build_sources


def build(value: JsonValue) -> JsonValue:
    reject_forbidden(value)
    try:
        fixture = Prd01Fixture.model_validate(value)
    except ValidationError as error:
        raise V10ContractError("V10_FIXTURE_ERROR", str(error)) from error
    calendar_body = _record(model_json(fixture.calendar))
    calendar_body["meta"] = _empty_meta("market_calendar_snapshot")
    calendar = build_calendar(calendar_body)
    us_body = _record(model_json(fixture.us_calendar))
    us_body["meta"] = _empty_meta("market_calendar_snapshot")
    us_calendar = build_calendar(us_body)
    observations, incidents = build_sources(fixture.source.model_dump(mode="json"))
    selected = next(item for item in observations if item.selected)
    minute_values = tuple(_minute_value(item, calendar, selected) for item in fixture.minutes)
    minutes = build_minutes(minute_values, calendar, selected)
    artifacts = (model_json(calendar), model_json(us_calendar), *(model_json(item) for item in observations),
                 *(model_json(item) for item in incidents), *(model_json(item) for item in minutes))
    probes = _probes(value, fixture, calendar_body, us_calendar, calendar, selected, minute_values)
    return seal_bundle(1, value, artifacts, probes)


def _probes(value: JsonValue, fixture: Prd01Fixture, calendar_body: dict[str, JsonValue],
            us_calendar: MarketCalendarSnapshot, calendar: MarketCalendarSnapshot, selected: SourceObservation,
            minute_values: tuple[JsonValue, ...]) -> tuple[JsonValue, ...]:
    from .probe_runner import error_probe, outcome_probe
    hidden_source = fixture.source.model_copy(update={"expected_selected_role": "primary"})
    negative = {**_record(minute_values[0]), "volume": -1}
    malformed_ohlc = {**_record(minute_values[0]), "low": "103.00"}
    holiday = {**_record(minute_values[0]), "session_date": "2026-01-06",
               "interval_start": "2026-01-06T09:00:00+09:00", "interval_end": "2026-01-06T09:01:00+09:00"}
    offsets = tuple(item.regular_open.utcoffset() for item in us_calendar.sessions if item.regular_open)
    return (
        error_probe("calendar_mismatch", "V10_CALENDAR_MISMATCH",
                    lambda: build_calendar({**calendar_body, "timezone": "Invalid/Zone"})),
        error_probe("hidden_fallback", "V10_SOURCE_PROVENANCE_MISMATCH",
                    lambda: _hidden_fallback(hidden_source.model_dump(mode="json"))),
        error_probe("negative_volume", "V10_MINUTE_BAR_MALFORMED",
                    lambda: build_minute(negative, calendar, selected)),
        error_probe("ohlc_invariant", "V10_MINUTE_BAR_MALFORMED",
                    lambda: build_minute(malformed_ohlc, calendar, selected)),
        error_probe("calendar_outside_regular", "V10_CALENDAR_MISMATCH",
                    lambda: build_minute(holiday, calendar, selected)),
        error_probe("timestamp_reversed", "V10_MINUTE_BAR_MALFORMED",
                    lambda: _reversed(tuple(reversed(minute_values)), calendar, selected)),
        outcome_probe("us_dst_transition", "different_offsets",
                      "different_offsets" if len(set(offsets)) == 2 else "same_offsets"),
        error_probe("secret_field", "V10_FORBIDDEN_FIELD",
                    lambda: reject_forbidden({"source": value, "client_secret": "x"})),
    )


def _minute_value(item: MinuteInput, calendar: MarketCalendarSnapshot,
                  selected: SourceObservation) -> JsonValue:
    return {**item.model_dump(mode="json"), "meta": _empty_meta("minute_bar"),
        "market": calendar.market.value, "symbol": selected.symbol,
        "session_date": item.interval_start.astimezone(ZoneInfo(calendar.timezone)).date().isoformat(),
        "session_state": SessionState.REGULAR.value,
        "source_ref": artifact_ref("source", selected).model_dump(mode="json"),
        "calendar_ref": artifact_ref("calendar", calendar).model_dump(mode="json")}


def _record(value: JsonValue) -> dict[str, JsonValue]:
    match value:  # noqa: MATCH_OK - internal builder emits object JSON
        case dict() as record:
            return record
        case _:
            raise V10ContractError("V10_FIXTURE_ERROR", "minute object")


def _hidden_fallback(value: JsonValue) -> None:
    _ = build_sources(value)


def _reversed(values: tuple[JsonValue, ...], calendar: MarketCalendarSnapshot,
              selected: SourceObservation) -> None:
    _ = build_minutes(values, calendar, selected)


def _empty_meta(artifact_type: str) -> JsonValue:
    return ArtifactMeta(schema_version="unsealed", artifact_type=artifact_type,
        artifact_id=ArtifactId("unsealed"), content_hash=ContentHash("unsealed"), lineage=()).model_dump(mode="json")
