from __future__ import annotations

import json
import re
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from src.v4.models import JsonValue


class MacroResponse(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="ignore")

    verdict: str = ""
    confidence: float = 0.5
    reasoning: tuple[str, ...] = ()
    reason: str = ""
    action: dict[str, JsonValue] = Field(default_factory=lambda: {"type": "none"})
    causal_chain: tuple[JsonValue, ...] | None = None


_RESPONSE = TypeAdapter(MacroResponse)


def parse_macro_response(text: str) -> MacroResponse | None:
    code_block = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    candidates = [code_block.group(1).strip()] if code_block is not None else []
    raw_object = re.search(r"\{.*\}", text, re.DOTALL)
    if raw_object is not None:
        candidates.append(raw_object.group(0))
    for candidate in candidates:
        try:
            return _RESPONSE.validate_json(candidate)
        except (json.JSONDecodeError, ValidationError):
            continue
    return None
