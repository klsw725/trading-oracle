from __future__ import annotations

from dataclasses import dataclass

from anthropic.types import TextBlock
from pydantic import TypeAdapter, ValidationError

from src.v4.models import JsonValue


@dataclass(frozen=True, slots=True)
class ProviderText:
    text: str
    raw_text: str
    request_id: str | None


@dataclass(frozen=True, slots=True)
class ProviderRequest:
    provider: str
    model: str
    system_prompt: str
    user_prompt: str
    max_tokens: int


_JSON_RECORD = TypeAdapter(dict[str, JsonValue])


def _parse_sse_response(raw: str) -> str:
    text_parts: list[str] = []
    for line in raw.split("\n"):
        stripped = line.strip()
        if not stripped.startswith("data:"):
            continue
        data_text = stripped[5:].strip()
        if not data_text or data_text == "[DONE]":
            continue
        try:
            value = _JSON_RECORD.validate_json(data_text)
        except ValidationError:
            continue
        if value.get("type") != "content_block_delta":
            continue
        delta = value.get("delta")
        if isinstance(delta, dict) and delta.get("type") == "text_delta":
            text = delta.get("text")
            if isinstance(text, str):
                text_parts.append(text)
    return "".join(text_parts)


def generate_provider_text(
    request: ProviderRequest,
) -> ProviderText:
    if request.provider == "codex":
        from src.agent.codex import generate

        text = generate(
            request.system_prompt, request.user_prompt, model=request.model
        )
        return ProviderText(text, text, None)
    from src.agent.oracle import get_client

    response = get_client().messages.create(
        model=request.model,
        max_tokens=request.max_tokens,
        system=request.system_prompt,
        messages=[{"role": "user", "content": request.user_prompt}],
    )
    if isinstance(response, str):
        return ProviderText(_parse_sse_response(response), response, None)
    block = response.content[0]
    if not isinstance(block, TextBlock):
        raise AttributeError("first Anthropic content block is not text")
    return ProviderText(block.text, block.text, response.id)
