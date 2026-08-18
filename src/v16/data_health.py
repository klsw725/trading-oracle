from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import re

from pydantic import ValidationError

from .calendar import expected_currency, load_calendar, session_window
from .canonical import JsonValue, canonical_hash, content_hash
from .errors import FailureCode, V16Failure
from .models import (
    CalendarArtifact,
    CalendarDescriptor,
    CalendarHealth,
    DatasetArtifact,
    DatasetDescriptor,
    DatasetHealth,
    HealthRequest,
    HealthVerdict,
    InputHealthReport,
    Market,
    MarketHealth,
    MarketScope,
)
from .paths import fixture_file
from .registries import DATASET_KINDS, SOURCES


_KR_SYMBOL = re.compile(r"^[0-9]{6}$")
_US_SYMBOL = re.compile(r"^[A-Z][A-Z0-9]{0,9}(?:[.-][A-Z0-9]{1,5})?$")


@dataclass(frozen=True, slots=True)
class DatasetContext:
    request: HealthRequest
    calendar: CalendarArtifact


@dataclass(frozen=True, slots=True)
class DatasetOutcome:
    verdict: HealthVerdict
    failure_code: str
    expected: str
    actual: str


def _time(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def descriptor_value(descriptor: DatasetDescriptor) -> JsonValue:
    return {
        "content_hash": descriptor.content_hash,
        "currency": descriptor.currency,
        "dataset_kind": descriptor.dataset_kind,
        "expected_interval_minutes": descriptor.expected_interval_minutes,
        "id": descriptor.id,
        "market": descriptor.market.value,
        "max_timestamp": _time(descriptor.max_timestamp),
        "min_timestamp": _time(descriptor.min_timestamp),
        "observed_at": _time(descriptor.observed_at),
        "path": descriptor.path,
        "row_count": descriptor.row_count,
        "session": descriptor.session,
        "source": descriptor.source,
        "source_version": descriptor.source_version,
        "symbols": list(descriptor.symbols),
    }


def _dataset_result(
    descriptor: DatasetDescriptor,
    request: HealthRequest,
    outcome: DatasetOutcome,
) -> DatasetHealth:
    descriptor_hash = canonical_hash(descriptor_value(descriptor))
    calendar = next(item for item in request.verified_manifest.manifest.calendars
                    if item.market is descriptor.market)
    evidence: JsonValue = {
        "actual": outcome.actual,
        "as_of": _time(request.as_of),
        "calendar_content_hash": calendar.content_hash,
        "calendar_version": calendar.calendar_version,
        "descriptor": descriptor_value(descriptor),
        "expected": outcome.expected,
        "failure_code": outcome.failure_code,
        "manifest_hash": request.verified_manifest.manifest_hash,
        "verdict": outcome.verdict.value,
    }
    return DatasetHealth(
        id=descriptor.id,
        verdict=outcome.verdict,
        failure_code=outcome.failure_code,
        expected=outcome.expected,
        actual=outcome.actual,
        descriptor_hash=descriptor_hash,
        evidence_hash=canonical_hash(evidence),
    )


def _symbol_valid(market: Market, symbol: str) -> bool:
    pattern = _KR_SYMBOL if market is Market.KR else _US_SYMBOL
    return pattern.fullmatch(symbol) is not None


def _artifact_verdict(
    descriptor: DatasetDescriptor, artifact: DatasetArtifact, context: DatasetContext
) -> DatasetHealth:
    request = context.request
    rows = artifact.rows
    timestamps = tuple(row.timestamp.astimezone(timezone.utc) for row in rows)
    pairs = tuple((row.timestamp.astimezone(timezone.utc), row.symbol) for row in rows)
    if timestamps != tuple(sorted(timestamps)) or len(set(pairs)) != len(pairs):
        return _dataset_result(descriptor, request, DatasetOutcome(HealthVerdict.INVALID,
                               FailureCode.INVALID.value, "ORDERED_UNIQUE", "INVALID"))
    if not rows or len(rows) != descriptor.row_count:
        return _dataset_result(descriptor, request, DatasetOutcome(HealthVerdict.INCOMPLETE,
                               FailureCode.INCOMPLETE.value, str(descriptor.row_count), str(len(rows))))
    if min(timestamps) != descriptor.min_timestamp or max(timestamps) != descriptor.max_timestamp:
        return _dataset_result(descriptor, request, DatasetOutcome(HealthVerdict.INVALID,
                               FailureCode.INVALID.value, "DECLARED_RANGE", "RANGE_MISMATCH"))
    declared = descriptor.symbols
    actual = tuple(sorted({row.symbol for row in rows}))
    if not declared or len(set(declared)) != len(declared) or any(
        not _symbol_valid(descriptor.market, symbol) for symbol in declared
    ) or any(not _symbol_valid(descriptor.market, symbol) for symbol in actual):
        return _dataset_result(descriptor, request, DatasetOutcome(HealthVerdict.INVALID,
                               FailureCode.INVALID.value, "VALID_SYMBOLS", "INVALID_SYMBOL"))
    if set(actual) != set(declared):
        verdict = HealthVerdict.INCOMPLETE if set(actual) < set(declared) else HealthVerdict.INVALID
        return _dataset_result(descriptor, request, DatasetOutcome(verdict, verdict.value,
                               "DECLARED_SYMBOLS", "SYMBOL_MISMATCH"))
    cutoff = request.as_of.astimezone(timezone.utc)
    observed = descriptor.observed_at.astimezone(timezone.utc)
    if max(timestamps) > cutoff or observed < max(timestamps) or observed > cutoff:
        return _dataset_result(descriptor, request, DatasetOutcome(HealthVerdict.INVALID,
                               FailureCode.INVALID.value, "CAUSAL_TIMESTAMPS", "FUTURE_OBSERVATION"))
    window = session_window(context.calendar, descriptor.session)
    if window is None or any(
        timestamp < window.opened_at or timestamp > window.closed_at for timestamp in timestamps
    ):
        return _dataset_result(descriptor, request, DatasetOutcome(HealthVerdict.INVALID,
                               FailureCode.INVALID.value, "SESSION_WINDOW", "OUTSIDE_SESSION"))
    step = timedelta(minutes=descriptor.expected_interval_minutes)
    grid: list[datetime] = []
    cursor = descriptor.min_timestamp.astimezone(timezone.utc)
    maximum = descriptor.max_timestamp.astimezone(timezone.utc)
    while cursor <= maximum:
        grid.append(cursor)
        cursor += step
    by_symbol = {
        symbol: tuple(timestamp for timestamp, row_symbol in pairs if row_symbol == symbol)
        for symbol in declared
    }
    if any(by_symbol[symbol] != tuple(grid) for symbol in declared):
        return _dataset_result(descriptor, request, DatasetOutcome(HealthVerdict.INCOMPLETE,
                               FailureCode.INCOMPLETE.value, "EXACT_SYMBOL_GRIDS", "GRID_GAP"))
    threshold = request.config.data.freshness_minutes[descriptor.dataset_kind][descriptor.market]
    if cutoff - observed > timedelta(minutes=threshold):
        return _dataset_result(descriptor, request, DatasetOutcome(HealthVerdict.STALE,
                               FailureCode.STALE.value, f"<={threshold}m", "STALE"))
    return _dataset_result(descriptor, request, DatasetOutcome(
        HealthVerdict.HEALTHY, "NONE", "HEALTHY", "HEALTHY"))


def _dataset_health(descriptor: DatasetDescriptor, context: DatasetContext) -> DatasetHealth:
    request = context.request
    if descriptor.dataset_kind not in DATASET_KINDS or \
            (descriptor.source, descriptor.source_version) not in SOURCES:
        return _dataset_result(descriptor, request, DatasetOutcome(HealthVerdict.UNKNOWN,
                               FailureCode.UNKNOWN.value, "REGISTERED_INPUT", "UNKNOWN"))
    if descriptor.currency != expected_currency(descriptor.market) or not descriptor.session:
        return _dataset_result(descriptor, request, DatasetOutcome(HealthVerdict.INVALID,
                               FailureCode.INVALID.value, "MARKET_IDENTITY", "INVALID"))
    try:
        payload = fixture_file(request.root, descriptor.path).read_bytes()
    except (OSError, V16Failure):
        return _dataset_result(descriptor, request, DatasetOutcome(HealthVerdict.INVALID,
                               FailureCode.INVALID.value, descriptor.content_hash, "UNREADABLE"))
    observed_hash = content_hash(payload)
    if observed_hash != descriptor.content_hash:
        return _dataset_result(descriptor, request, DatasetOutcome(HealthVerdict.HASH_MISMATCH,
                               FailureCode.HASH_MISMATCH.value, descriptor.content_hash, observed_hash))
    try:
        artifact = DatasetArtifact.model_validate_json(payload)
    except ValidationError:
        return _dataset_result(descriptor, request, DatasetOutcome(HealthVerdict.INVALID,
                               FailureCode.INVALID.value, "VALID_DATASET", "SCHEMA_REJECTED"))
    return _artifact_verdict(descriptor, artifact, context)


def _calendar_health(
    descriptor: CalendarDescriptor, request: HealthRequest
) -> tuple[CalendarHealth, CalendarArtifact | None]:
    expected = request.config.markets[descriptor.market].calendar_version
    observed_hash = "UNREADABLE"
    try:
        payload = fixture_file(request.root, descriptor.path).read_bytes()
        observed_hash = content_hash(payload)
        if observed_hash != descriptor.content_hash:
            raise V16Failure(FailureCode.HASH_MISMATCH, "calendar hash mismatch")
        artifact = load_calendar(fixture_file(request.root, descriptor.path))
        if artifact.market is not descriptor.market or \
                artifact.calendar_version != descriptor.calendar_version or \
                descriptor.calendar_version != expected:
            raise V16Failure(FailureCode.CALENDAR_INVALID, "calendar identity mismatch")
    except (OSError, V16Failure) as error:
        code = error.code.value if isinstance(error, V16Failure) else FailureCode.CALENDAR_INVALID.value
        body: JsonValue = {"actual": observed_hash, "as_of": _time(request.as_of),
                           "descriptor_hash": descriptor.content_hash, "expected": expected,
                           "failure_code": code, "manifest_hash": request.verified_manifest.manifest_hash}
        return CalendarHealth(verdict=HealthVerdict.INVALID, failure_code=code,
                              version=descriptor.calendar_version, content_hash=observed_hash,
                              expected=expected, actual=observed_hash,
                              evidence_hash=canonical_hash(body)), None
    body = {"actual": artifact.calendar_version, "as_of": _time(request.as_of),
            "descriptor_hash": descriptor.content_hash, "expected": expected,
            "failure_code": "NONE", "manifest_hash": request.verified_manifest.manifest_hash}
    return CalendarHealth(verdict=HealthVerdict.HEALTHY, failure_code="NONE",
                          version=artifact.calendar_version, content_hash=observed_hash,
                          expected=expected, actual=artifact.calendar_version,
                          evidence_hash=canonical_hash(body)), artifact


def health_report(request: HealthRequest) -> InputHealthReport:
    requested = (Market.KR, Market.US) if request.scope is MarketScope.ALL else (
        Market(request.scope.value),)
    details: list[MarketHealth] = []
    for market in requested:
        descriptor = next(item for item in request.verified_manifest.manifest.calendars
                          if item.market is market)
        calendar_health, calendar = _calendar_health(descriptor, request)
        datasets = tuple(item for item in request.verified_manifest.manifest.datasets
                         if item.market is market)
        if calendar is None:
            dataset_health = tuple(_dataset_result(item, request, DatasetOutcome(
                HealthVerdict.INVALID, FailureCode.CALENDAR_INVALID.value,
                "HEALTHY_CALENDAR", "CALENDAR_UNAVAILABLE")) for item in datasets)
        else:
            context = DatasetContext(request, calendar)
            dataset_health = tuple(_dataset_health(item, context) for item in datasets)
        healthy = calendar_health.verdict is HealthVerdict.HEALTHY and bool(dataset_health) and all(
            item.verdict is HealthVerdict.HEALTHY for item in dataset_health)
        verdict = HealthVerdict.HEALTHY if healthy else next(
            (item.verdict for item in dataset_health if item.verdict is not HealthVerdict.HEALTHY),
            calendar_health.verdict)
        failure = "NONE" if healthy else next(
            (item.failure_code for item in dataset_health if item.verdict is not HealthVerdict.HEALTHY),
            calendar_health.failure_code,
        )
        body: JsonValue = {"as_of": _time(request.as_of), "calendar": calendar_health.evidence_hash,
                           "datasets": [item.evidence_hash for item in dataset_health],
                           "failure_code": failure, "manifest_hash": request.verified_manifest.manifest_hash,
                           "market": market.value, "verdict": verdict.value}
        details.append(MarketHealth(market=market, verdict=verdict, failure_code=failure,
                                    calendar=calendar_health, datasets=dataset_health,
                                    evidence_hash=canonical_hash(body)))
    status = "PASS" if all(item.verdict is HealthVerdict.HEALTHY for item in details) else "FAIL"
    report_body: JsonValue = {"as_of": _time(request.as_of),
                              "manifest_hash": request.verified_manifest.manifest_hash,
                              "markets": [item.evidence_hash for item in details],
                              "schema_version": "v16.input-health.1", "status": status}
    return InputHealthReport(schema_version="v16.input-health.1", status=status,
                             as_of=_time(request.as_of),
                             manifest_hash=request.verified_manifest.manifest_hash,
                             markets=tuple(details), report_hash=canonical_hash(report_body))
