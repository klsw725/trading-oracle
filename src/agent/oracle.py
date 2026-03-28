"""LLM Agent — 투자 분석 (Anthropic / Codex provider 지원)"""

import json
import os

from anthropic import Anthropic

from src.agent.prompts import SYSTEM_PROMPT, build_analysis_prompt


def get_client() -> Anthropic:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY 환경변수가 설정되지 않았습니다.\n"
            "export ANTHROPIC_API_KEY='your-key-here'"
        )
    return Anthropic(api_key=api_key)


def _parse_sse_response(raw: str) -> str:
    """SSE 스트림 응답에서 텍스트 추출"""
    text_parts = []
    for line in raw.split("\n"):
        line = line.strip()
        if not line.startswith("data:"):
            continue
        data_str = line[5:].strip()
        if not data_str or data_str == "[DONE]":
            continue
        try:
            data = json.loads(data_str)
            if data.get("type") == "content_block_delta":
                delta = data.get("delta", {})
                if delta.get("type") == "text_delta":
                    text_parts.append(delta.get("text", ""))
        except (json.JSONDecodeError, KeyError):
            continue
    return "".join(text_parts)


def _analyze_anthropic(
    market_data: dict,
    signals_data: list[dict],
    portfolio: dict,
    config: dict,
) -> str:
    """Anthropic Claude API로 분석."""
    client = get_client()
    user_prompt = build_analysis_prompt(market_data, signals_data, portfolio, config)

    llm_config = config.get("llm", {})
    model = llm_config.get("model", "claude-sonnet-4-20250514")
    max_tokens = llm_config.get("max_tokens", 4096)

    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )

    if isinstance(response, str):
        return _parse_sse_response(response)

    return response.content[0].text


def _analyze_codex(
    market_data: dict,
    signals_data: list[dict],
    portfolio: dict,
    config: dict,
) -> str:
    """OpenAI Codex Responses API로 분석."""
    from src.agent.codex import generate

    user_prompt = build_analysis_prompt(market_data, signals_data, portfolio, config)
    llm_config = config.get("llm", {})
    model = llm_config.get("model", "gpt-5.1-codex")

    return generate(SYSTEM_PROMPT, user_prompt, model=model)


def analyze(
    market_data: dict,
    signals_data: list[dict],
    portfolio: dict,
    config: dict,
) -> str:
    """시장 데이터 + 시그널 + 포트폴리오 → LLM 분석 결과

    config.llm.provider로 provider 선택:
      - "anthropic" (기본): Claude API
      - "codex": OpenAI Codex Responses API (OAuth)
    """
    provider = config.get("llm", {}).get("provider", "anthropic")

    if provider == "codex":
        return _analyze_codex(market_data, signals_data, portfolio, config)
    return _analyze_anthropic(market_data, signals_data, portfolio, config)
