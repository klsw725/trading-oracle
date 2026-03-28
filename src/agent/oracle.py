"""LLM Agent — Claude API를 통한 투자 분석"""

import json
import os
import re

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


def analyze(
    market_data: dict,
    signals_data: list[dict],
    portfolio: dict,
    config: dict,
) -> str:
    """시장 데이터 + 시그널 + 포트폴리오 → LLM 분석 결과"""
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

    # Handle both parsed response objects and raw SSE strings
    if isinstance(response, str):
        return _parse_sse_response(response)

    return response.content[0].text
