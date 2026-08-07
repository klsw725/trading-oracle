from datetime import datetime
from typing import Final
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .quality_derived_models import DerivedSourceEvidence
from .quality_models import FreshnessAssessment, QualityContractError
from .quality_registry_models import SourceKind
from .provenance import PRD02_FRESHNESS_SLA_HOURS

CURRENT_SLA_HOURS: Final[dict[SourceKind, float]] = {
    "market_price": PRD02_FRESHNESS_SLA_HOURS["market_price"],
    "fundamental_equity": PRD02_FRESHNESS_SLA_HOURS["fundamental_equity"],
    "news_search": PRD02_FRESHNESS_SLA_HOURS["news_search"],
    "web_context": PRD02_FRESHNESS_SLA_HOURS["web_context"],
    "macro_timeseries_daily": PRD02_FRESHNESS_SLA_HOURS["macro_timeseries_daily"],
    "macro_timeseries_monthly": PRD02_FRESHNESS_SLA_HOURS["macro_timeseries_monthly"],
}
AUDIT_TTL_HOURS: Final[dict[SourceKind, float]] = {
    "market_price": 24.0,
    "fundamental_equity": 720.0,
    "news_search": 720.0,
    "web_context": 720.0,
    "macro_timeseries_daily": 2160.0,
    "macro_timeseries_monthly": 2160.0,
}
EXPIRES_AFTER_HOURS: Final[dict[SourceKind, float]] = {
    "market_price": 48.0,
    "fundamental_equity": 2160.0,
    "news_search": 2160.0,
    "web_context": 2160.0,
    "macro_timeseries_daily": 4320.0,
    "macro_timeseries_monthly": 4320.0,
}


def _effective_kind(source: DerivedSourceEvidence) -> SourceKind:
    if source.source_kind == "local_cache":
        raise QualityContractError("CACHE_LINEAGE_INVALID", "cache kind was not resolved from upstream bundle")
    return source.source_kind


def _as_of(source: DerivedSourceEvidence) -> datetime | None:
    value = source.provenance.as_of
    if value.kind == "unknown":
        return None
    try:
        parsed = datetime.fromisoformat(value.value)
        if value.kind == "session":
            if value.timezone is None:
                raise QualityContractError("MALFORMED_QUALITY_PAYLOAD", "session as_of requires timezone")
            zone = ZoneInfo(value.timezone)
            return parsed.replace(tzinfo=zone) if parsed.tzinfo is None else parsed.astimezone(zone)
    except (ValueError, ZoneInfoNotFoundError) as error:
        raise QualityContractError("MALFORMED_QUALITY_PAYLOAD", "invalid PRD01 as_of timestamp") from error
    if parsed.tzinfo is None:
        raise QualityContractError("MALFORMED_QUALITY_PAYLOAD", "PRD01 as_of must include timezone")
    return parsed


def assess_freshness(source: DerivedSourceEvidence, evaluated_at: datetime) -> FreshnessAssessment:
    kind = _effective_kind(source)
    current_sla = CURRENT_SLA_HOURS[kind]
    audit_ttl = AUDIT_TTL_HOURS[kind]
    expires_after = EXPIRES_AFTER_HOURS[kind]
    as_of = _as_of(source)
    if as_of is None:
        return FreshnessAssessment(label="degraded", age_hours=None, current_sla_hours=current_sla, audit_ttl_hours=audit_ttl, expires_after_hours=expires_after, audit_status="unavailable")
    age_hours = (evaluated_at - as_of).total_seconds() / 3600
    if age_hours < 0:
        raise QualityContractError("MALFORMED_QUALITY_PAYLOAD", "as_of is later than evaluation time")
    if age_hours <= current_sla:
        label = "fresh"
    elif age_hours <= audit_ttl:
        label = "stale"
    else:
        label = "expired"
    if age_hours <= audit_ttl:
        audit_status = "active"
    elif age_hours <= expires_after:
        audit_status = "retained"
    else:
        audit_status = "expired"
    return FreshnessAssessment(label=label, age_hours=age_hours, current_sla_hours=current_sla, audit_ttl_hours=audit_ttl, expires_after_hours=expires_after, audit_status=audit_status)
