from __future__ import annotations

from datetime import datetime
from pathlib import Path

from src.v4.models import JsonValue, canonical_json
from src.v10.acceptance import build_path
from src.v10.verifier import verify_bundle

from .canonical import canonical_hash
from .models import Market, MarketInput, V11ContractError


def load_v10_market_input(paths: tuple[str, ...]) -> MarketInput:
    root = Path(__file__).resolve().parents[2]
    artifacts: list[JsonValue] = []
    refs: list[str] = []
    for raw_path in paths:
        bundle = verify_bundle(canonical_json(build_path(root / raw_path)))
        refs.append(bundle.bundle_hash)
        artifacts.extend(bundle.artifacts)
    minutes = [item for item in artifacts if _type(item) == "minute_bar"
               and isinstance(item, dict) and item.get("market") == "KR"]
    bars = [item for item in artifacts if _type(item) == "five_minute_bar" and isinstance(item, dict)]
    calendars = [item for item in artifacts if _type(item) == "market_calendar_snapshot"
                 and isinstance(item, dict) and item.get("market") == "KR"]
    eligibility = [item for item in artifacts if _type(item) == "eligibility_event"
                   and isinstance(item, dict)]
    if not minutes or not bars or not calendars:
        raise V11ContractError("V11_V10_INPUT_MISSING", "minute/calendar/watermark")
    bar = bars[-1]
    watermark_text = _text(bar, "watermark_at")
    watermark = datetime.fromisoformat(watermark_text.replace("Z", "+00:00"))
    causal_minutes = [item for item in minutes
        if datetime.fromisoformat(_text(item, "observed_at").replace("Z", "+00:00")) <= watermark]
    if not causal_minutes:
        raise V11ContractError("V11_V10_INPUT_MISSING", "causal minute")
    minute = max(causal_minutes, key=lambda item: _text(item, "interval_end"))
    calendar = calendars[0]
    sessions = calendar.get("sessions")
    if not isinstance(sessions, list) or not sessions or not isinstance(sessions[0], dict):
        raise V11ContractError("V11_V10_INPUT_MISSING", "session")
    session = sessions[0]
    close = _text(session, "regular_end")
    payload: dict[str, JsonValue] = {"minute": minute, "bar": bar, "calendar": calendar,
        "eligibility": [dict(item) for item in eligibility], "refs": list(refs)}
    symbol = _text(minute, "symbol")
    blocked = any(_text(item, "symbol") == symbol
        and datetime.fromisoformat(_text(item, "effective_at").replace("Z", "+00:00")) <= watermark
        and item.get("eligible") is False for item in eligibility)
    return MarketInput(market=Market.KR, symbol=symbol,
        reference_price=_text(minute, "close"), target_volume=_integer(minute, "volume"),
        watermark_at=watermark,
        regular_close=datetime.fromisoformat(close.replace("Z", "+00:00")),
        eligible=not blocked, provenance_refs=tuple(refs), input_hash=canonical_hash(payload))


def _type(value: JsonValue) -> str | None:
    if isinstance(value, dict) and isinstance(meta := value.get("meta"), dict):
        item = meta.get("artifact_type")
        return item if isinstance(item, str) else None
    return None


def _text(value: dict[str, JsonValue], field: str) -> str:
    item = value.get(field)
    if isinstance(item, str):
        return item
    raise V11ContractError("V11_V10_INPUT_MISSING", field)


def _integer(value: dict[str, JsonValue], field: str) -> int:
    item = value.get(field)
    if isinstance(item, int) and not isinstance(item, bool):
        return item
    raise V11ContractError("V11_V10_INPUT_MISSING", field)
