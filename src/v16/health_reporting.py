from __future__ import annotations

from .canonical import JsonValue
from .models import InputHealthReport


def health_value(report: InputHealthReport) -> JsonValue:
    markets: list[JsonValue] = []
    for market in report.markets:
        markets.append({"calendar": {"actual": market.calendar.actual,
            "content_hash": market.calendar.content_hash, "evidence_hash": market.calendar.evidence_hash,
            "expected": market.calendar.expected, "failure_code": market.calendar.failure_code,
            "verdict": market.calendar.verdict.value, "version": market.calendar.version},
            "datasets": [{"actual": dataset.actual, "descriptor_hash": dataset.descriptor_hash,
                "evidence_hash": dataset.evidence_hash, "expected": dataset.expected,
                "failure_code": dataset.failure_code, "id": dataset.id,
                "verdict": dataset.verdict.value} for dataset in market.datasets],
            "evidence_hash": market.evidence_hash, "failure_code": market.failure_code,
            "market": market.market.value, "verdict": market.verdict.value})
    return {"as_of": report.as_of, "manifest_hash": report.manifest_hash,
            "markets": markets, "report_hash": report.report_hash,
            "schema_version": report.schema_version, "status": report.status}
