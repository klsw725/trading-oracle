from __future__ import annotations

from pydantic import ValidationError

from src.v4.models import JsonValue
from src.v9.spec import parse_json_bytes
from src.v13.prd02_models import CodexItem, ItemRecord, ParsedEnvelope


def _text(record: dict[str, JsonValue], field: str) -> str | None:
    value = record.get(field)
    return value if isinstance(value, str) else None


def parse_recorded_response(payload: bytes) -> ParsedEnvelope:
    value = parse_json_bytes(payload)
    if not isinstance(value, dict):
        return ParsedEnvelope(schema_version=None, batch_id=None, market=None,
            cutoff=None, prompt_hash=None, items=(), envelope_error="ENVELOPE_SCHEMA")
    raw_items = value.get("items")
    if not isinstance(raw_items, list):
        return ParsedEnvelope(schema_version=_text(value, "schema_version"),
            batch_id=_text(value, "batch_id"), market=_text(value, "market"),
            cutoff=_text(value, "cutoff"), prompt_hash=_text(value, "prompt_hash"),
            items=(), envelope_error="ENVELOPE_SCHEMA")
    records: list[ItemRecord] = []
    for raw in raw_items:
        candidate_id = _text(raw, "candidate_id") if isinstance(raw, dict) else None
        try:
            item = CodexItem.model_validate(raw)
        except ValidationError:
            records.append(ItemRecord(candidate_id=candidate_id, item=None,
                error_code="ITEM_SCHEMA"))
        else:
            records.append(ItemRecord(candidate_id=item.candidate_id, item=item,
                error_code=None))
    allowed = {"schema_version", "batch_id", "market", "cutoff", "prompt_hash", "items"}
    envelope_error = "ENVELOPE_SCHEMA" if set(value) != allowed else None
    return ParsedEnvelope(schema_version=_text(value, "schema_version"),
        batch_id=_text(value, "batch_id"), market=_text(value, "market"),
        cutoff=_text(value, "cutoff"), prompt_hash=_text(value, "prompt_hash"),
        items=tuple(records), envelope_error=envelope_error)
