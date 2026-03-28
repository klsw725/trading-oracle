"""다관점 투자 판정 시스템 — 공통 인터페이스

모든 관점은 이 ABC를 구현한다.
SPEC §4-0 공통 필드 규격 준수.
"""

import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import pandas as pd


@dataclass
class PerspectiveInput:
    """관점 분석에 필요한 입력 데이터 묶음"""

    ticker: str
    name: str
    ohlcv: pd.DataFrame
    signals: dict  # compute_signals() 결과
    fundamentals: dict  # fetch_naver_fundamentals() 결과
    position: dict | None  # 포트폴리오 포지션 (미보유 시 None)
    market_context: dict  # {"kospi": {...}, "kosdaq": {...}}
    config: dict
    web_context: dict = field(default_factory=dict)  # 웹 검색 결과 (Phase 10)


@dataclass
class PerspectiveResult:
    """관점 분석 결과 — SPEC §4-0 공통 필드

    perspective: 관점 식별자 (kwangsoo, ouroboros, quant, macro, value)
    verdict: BUY / SELL / HOLD / N/A
    confidence: 0.0 ~ 1.0
    reasoning: 단계별 추론 과정 리스트
    reason: 한 줄 요약
    action: 구체적 행동 지침 dict
    extra: 관점별 추가 필드 (philosophy, signals, metrics 등)
    """

    perspective: str
    verdict: str
    confidence: float
    reasoning: list[str]
    reason: str
    action: dict
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        base = {
            "perspective": self.perspective,
            "verdict": self.verdict,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "reason": self.reason,
            "action": self.action,
        }
        base.update(self.extra)
        return base


def make_na_result(perspective: str, reason: str = "판정 불가") -> PerspectiveResult:
    """LLM 호출 실패 등으로 판정 불가 시 N/A 결과 생성"""
    return PerspectiveResult(
        perspective=perspective,
        verdict="N/A",
        confidence=0.0,
        reasoning=[reason],
        reason=reason,
        action={"type": "none"},
    )


def extract_json(text: str) -> dict | None:
    """LLM 응답에서 JSON 추출. 코드블록 내부 또는 raw JSON 모두 처리."""
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    return None


def call_llm(system_prompt: str, user_prompt: str, config: dict, max_tokens: int = 2048) -> str:
    """LLM 호출 → 텍스트 반환. config.llm.provider에 따라 Anthropic/Codex 분기."""
    llm_config = config.get("llm", {})
    provider = llm_config.get("provider", "anthropic")

    if provider == "codex":
        from src.agent.codex import generate
        model = llm_config.get("model", "gpt-5.1-codex")
        return generate(system_prompt, user_prompt, model=model)

    from src.agent.oracle import get_client, _parse_sse_response
    client = get_client()
    model = llm_config.get("model", "claude-sonnet-4-20250514")

    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )

    if isinstance(response, str):
        return _parse_sse_response(response)
    return response.content[0].text


class Perspective(ABC):
    """투자 관점 ABC — 모든 관점이 구현해야 하는 인터페이스"""

    name: str

    @abstractmethod
    def analyze(self, data: PerspectiveInput) -> PerspectiveResult:
        """종목 데이터를 받아 판정 결과를 반환한다."""
        ...
