from __future__ import annotations

from datetime import datetime, timedelta
from typing import Final

from src.v4.models import JsonValue, canonical_hash

from .canonical import artifact_ref, model_json, seal_meta
from .models import AggregationFailure, ContentHash, FiveMinuteBar, MinuteBar, SessionState
from .watermark import WatermarkPolicy, arrived_by, is_fresh, verify_evaluation


INTERVAL: Final = timedelta(minutes=5)


def aggregate_five_minutes(
    bars: tuple[MinuteBar, ...],
    evaluated_at: datetime,
    policy: WatermarkPolicy,
) -> FiveMinuteBar | AggregationFailure:
    ordered = tuple(sorted(bars, key=lambda bar: bar.interval_start))
    interval_start = ordered[0].interval_start
    interval_end = interval_start + INTERVAL
    watermark = verify_evaluation(interval_end, evaluated_at)
    expected = tuple(interval_start + timedelta(minutes=index) for index in range(5))
    usable = tuple(
        bar
        for bar in ordered
        if bar.interval_start in expected and arrived_by(bar, watermark)
    )
    missing = tuple(start for start in expected if not any(bar.interval_start == start for bar in usable))
    stale = tuple(bar for bar in usable if not is_fresh(bar, policy))
    mixed = tuple(bar for bar in usable if bar.session_state is not SessionState.REGULAR)
    if missing or stale or mixed or len(usable) != 5:
        reason = "missing" if missing else "stale" if stale else "session_state"
        body: JsonValue = {
            "market": ordered[0].market.value,
            "symbol": ordered[0].symbol,
            "interval_start": interval_start.isoformat(),
            "interval_end": interval_end.isoformat(),
            "watermark_at": watermark.isoformat(),
            "reason": reason,
            "present_refs": [model_json(artifact_ref("minute", bar)) for bar in usable],
            "missing_starts": [start.isoformat() for start in missing],
            "downstream_eligible": False,
        }
        return AggregationFailure(
            meta=seal_meta("aggregation_failure", body),
            market=ordered[0].market,
            symbol=ordered[0].symbol,
            interval_start=interval_start,
            interval_end=interval_end,
            watermark_at=watermark,
            reason=reason,
            present_refs=tuple(artifact_ref("minute", bar) for bar in usable),
            missing_starts=missing,
            downstream_eligible=False,
        )
    return _complete(usable, evaluated_at, watermark, policy)


def _complete(
    bars: tuple[MinuteBar, ...],
    evaluated_at: datetime,
    watermark: datetime,
    policy: WatermarkPolicy,
) -> FiveMinuteBar:
    policy_body: JsonValue = {
        "watermark_delay_seconds": 10,
        "max_observation_lag_seconds": policy.max_observation_lag_seconds,
    }
    body: JsonValue = {
        "market": bars[0].market.value,
        "symbol": bars[0].symbol,
        "session_date": bars[0].session_date.isoformat(),
        "interval_start": bars[0].interval_start.isoformat(),
        "interval_end": bars[-1].interval_end.isoformat(),
        "open": str(bars[0].open),
        "high": str(max(bar.high for bar in bars)),
        "low": str(min(bar.low for bar in bars)),
        "close": str(bars[-1].close),
        "volume": sum(bar.volume for bar in bars),
        "minute_refs": [model_json(artifact_ref("minute", bar)) for bar in bars],
        "evaluated_at": evaluated_at.isoformat(),
        "watermark_at": watermark.isoformat(),
        "max_observation_lag_seconds": policy.max_observation_lag_seconds,
        "policy_hash": canonical_hash(policy_body),
        "complete": True,
    }
    return FiveMinuteBar(
        meta=seal_meta("five_minute_bar", body),
        market=bars[0].market,
        symbol=bars[0].symbol,
        session_date=bars[0].session_date,
        interval_start=bars[0].interval_start,
        interval_end=bars[-1].interval_end,
        open=bars[0].open,
        high=max(bar.high for bar in bars),
        low=min(bar.low for bar in bars),
        close=bars[-1].close,
        volume=sum(bar.volume for bar in bars),
        minute_refs=tuple(artifact_ref("minute", bar) for bar in bars),
        evaluated_at=evaluated_at,
        watermark_at=watermark,
        max_observation_lag_seconds=policy.max_observation_lag_seconds,
        policy_hash=ContentHash(canonical_hash(policy_body)),
        complete=True,
    )
