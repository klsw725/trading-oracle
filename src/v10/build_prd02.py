from __future__ import annotations

from datetime import timedelta

from pydantic import ValidationError

from src.v4.models import JsonValue

from .aggregation import aggregate_five_minutes
from .bundle import seal_bundle
from .canonical import model_json, seal_meta
from .fixture_models import Prd02Fixture
from .models import ArtifactRef, MinuteBar, SessionState, V10ContractError
from .probe_runner import error_probe, outcome_probe
from .replay import revision_head
from .revision import supersede
from .watermark import WatermarkPolicy


def build(value: JsonValue) -> JsonValue:
    try:
        fixture = Prd02Fixture.model_validate(value)
    except ValidationError as error:
        raise V10ContractError("V10_FIXTURE_ERROR", str(error)) from error
    bars = tuple(_minute(fixture, index) for index in range(len(fixture.minutes)))
    policy = WatermarkPolicy(fixture.max_observation_lag_seconds)
    aggregate = aggregate_five_minutes(bars, fixture.evaluated_at, policy)
    revision_input = fixture.revision
    prior = bars[revision_input.minute_index]
    replacement = prior.model_copy(update={
        "close": revision_input.close, "observed_at": revision_input.observed_at,
        "revision": revision_input.revision,
    })
    replacement_body = replacement.model_dump(mode="json", exclude={"meta"})
    replacement = replacement.model_copy(update={"meta": seal_meta("minute_bar", replacement_body)})
    event = supersede(prior, replacement)
    if event is None:
        raise V10ContractError("V10_REVISION_MISMATCH", "fixture revision was idempotent")
    if revision_head((prior, replacement), (event,), replacement.observed_at).revision != revision_input.revision:
        raise V10ContractError("V10_REVISION_MISMATCH", "replay head")
    missing = aggregate_five_minutes(bars[:-1], fixture.evaluated_at, policy)
    stale_bars = (bars[0].model_copy(update={"observed_at": bars[0].interval_end + timedelta(seconds=11)}), *bars[1:])
    stale = aggregate_five_minutes(stale_bars, fixture.evaluated_at, policy)
    mixed_bars = (bars[0].model_copy(update={"session_state": SessionState.AUCTION}), *bars[1:])
    mixed = aggregate_five_minutes(mixed_bars, fixture.evaluated_at, policy)
    probes = (
        outcome_probe("missing_minute", "missing", getattr(missing, "reason", "complete")),
        outcome_probe("stale_minute", "stale", getattr(stale, "reason", "complete")),
        error_probe("watermark_early", "V10_WATERMARK_EARLY",
                    lambda: aggregate_five_minutes(bars, fixture.evaluated_at - timedelta(seconds=1), policy)),
        outcome_probe("auction_mixed", "session_state", getattr(mixed, "reason", "complete")),
        error_probe("future_revision_replay", "V10_REPLAY_LOOKAHEAD",
                    lambda: revision_head((replacement,), (event,), prior.observed_at)),
        outcome_probe("same_revision_idempotent", "no_op",
                      "no_op" if supersede(prior, prior) is None else "superseded"),
    )
    source_artifact = _fixture_artifact("source_observation", "fixture-source")
    calendar_artifact = _fixture_artifact("market_calendar_snapshot", "fixture-calendar")
    artifacts = (source_artifact, calendar_artifact, *(model_json(item) for item in bars),
                 model_json(aggregate), model_json(replacement), model_json(event))
    return seal_bundle(2, value, artifacts, probes)


def _minute(fixture: Prd02Fixture, index: int) -> MinuteBar:
    source = _fixture_ref("source", "source_observation", "fixture-source")
    calendar = _fixture_ref("calendar", "market_calendar_snapshot", "fixture-calendar")
    item = fixture.minutes[index]
    end = item.start + timedelta(minutes=1)
    body: JsonValue = {"market": fixture.market.value, "symbol": fixture.symbol,
        "session_date": fixture.session_date.isoformat(), "interval_start": item.start.isoformat(),
        "interval_end": end.isoformat(), "open": str(item.open), "high": str(item.high),
        "low": str(item.low), "close": str(item.close), "volume": item.volume,
        "session_state": "regular", "observed_at": item.observed_at.isoformat(), "revision": 0,
        "source_ref": source.model_dump(mode="json"), "calendar_ref": calendar.model_dump(mode="json")}
    return MinuteBar(meta=seal_meta("minute_bar", body), market=fixture.market, symbol=fixture.symbol,
        session_date=fixture.session_date, interval_start=item.start, interval_end=end, open=item.open,
        high=item.high, low=item.low, close=item.close, volume=item.volume,
        session_state=SessionState.REGULAR, observed_at=item.observed_at, revision=0,
        source_ref=source, calendar_ref=calendar)


def _fixture_artifact(artifact_type: str, identifier: str) -> JsonValue:
    body: JsonValue = {"fixture_identity": identifier}
    meta = seal_meta(artifact_type, body)
    return {"meta": model_json(meta), **body}


def _fixture_ref(role: str, artifact_type: str, identifier: str) -> ArtifactRef:
    meta = seal_meta(artifact_type, {"fixture_identity": identifier})
    return ArtifactRef(role=role, artifact_type=artifact_type,
                       artifact_id=meta.artifact_id, content_hash=meta.content_hash)
