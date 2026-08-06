"""다관점 투자 판정 시스템 — 공통 인터페이스

모든 관점은 이 ABC를 구현한다.
SPEC §4-0 공통 필드 규격 준수.
"""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass, field
from threading import Lock
from typing import Final

import pandas as pd

from src.v4.models import JsonValue


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
    fx_signal: dict = field(default_factory=dict)  # 환율 팩터 (Phase 17)
    provenance_collector: LlmProvenanceCollector | None = None


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


class LlmProvenanceCollector:
    def __init__(self, config: Mapping[str, JsonValue]) -> None:
        self._config = deepcopy(dict(config))
        v4_config = self._config.get("v4")
        if isinstance(v4_config, dict):
            capture_config = v4_config.get("native_capture")
            if isinstance(capture_config, dict):
                self._config["v4"] = {
                    **v4_config,
                    "native_capture": {
                        "enabled": capture_config.get("enabled") is True
                    },
                }
        self._lock = Lock()
        self._prompts: list[JsonValue] = []
        self._raw_results: list[JsonValue] = []
        self._parsed_results: list[JsonValue] = []
        self._attempts: dict[str, int] = {}

    def record_prompt(
        self,
        perspective: str,
        provider: str,
        model: str,
        system_prompt: str,
        user_prompt: str,
    ) -> int:
        with self._lock:
            attempt = self._attempts.get(perspective, 0) + 1
            self._attempts[perspective] = attempt
            self._prompts.append(
                {
                    "perspective": perspective,
                    "attempt": attempt,
                    "provider": provider,
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                }
            )
            return attempt

    def record_response(
        self,
        perspective: str,
        attempt: int,
        provider: str,
        model: str,
        raw_text: str,
        provider_request_id: str | None,
    ) -> None:
        with self._lock:
            self._raw_results.append(
                {
                    "perspective": perspective,
                    "attempt": attempt,
                    "provider": provider,
                    "model": model,
                    "provider_request_id": provider_request_id,
                    "raw_text": raw_text,
                    "quality_state": "available",
                }
            )

    def record_result(self, result: PerspectiveResult) -> None:
        with self._lock:
            self._parsed_results.append(deepcopy(result.to_dict()))
            if not any(
                isinstance(raw, dict)
                and raw.get("perspective") == result.perspective
                for raw in self._raw_results
            ):
                self._raw_results.append(
                    {"perspective": result.perspective, "raw_text": None,
                     "provider_error_type": "unknown", "quality_state": "unknown"}
                )

    def export(self) -> dict[str, JsonValue]:
        llm_config = self._config.get("llm")
        config_record = llm_config if isinstance(llm_config, dict) else {}
        with self._lock:
            return {
                "provider_adapter_version": "src.perspectives.base.call_llm.v1",
                "provider": config_record.get("provider", "anthropic"),
                "model": config_record.get("model"),
                "provider_request_id": None,
                "prompt_bundle_version": "runtime-perspectives.v1",
                "prompt_messages": deepcopy(self._prompts),
                "config_version": "runtime-config.v1",
                "config": deepcopy(self._config),
                "parser_version": "src.perspectives.base.extract_json.v1",
                "raw_results": deepcopy(self._raw_results),
                "parsed_results": deepcopy(self._parsed_results),
            }


type _LlmCaptureBinding = tuple[LlmProvenanceCollector, str]
_LLM_CAPTURE: Final[ContextVar[_LlmCaptureBinding | None]] = ContextVar(
    "llm_capture", default=None
)


@contextmanager
def llm_capture_scope(
    collector: LlmProvenanceCollector | None,
    perspective: str,
) -> Iterator[None]:
    if collector is None:
        yield
        return
    token = _LLM_CAPTURE.set((collector, perspective))
    try:
        yield
    finally:
        _LLM_CAPTURE.reset(token)


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
    model = llm_config.get(
        "model",
        "gpt-5.1-codex" if provider == "codex" else "claude-sonnet-4-20250514",
    )
    binding = _LLM_CAPTURE.get()
    attempt = (
        binding[0].record_prompt(
            binding[1],
            provider,
            model,
            system_prompt,
            user_prompt,
        )
        if binding is not None
        else 0
    )

    if provider == "codex":
        from src.agent.codex import generate

        text = generate(system_prompt, user_prompt, model=model)
        if binding is not None:
            binding[0].record_response(
                binding[1], attempt, provider, model, text, None
            )
        return text

    from src.agent.oracle import get_client, _parse_sse_response
    client = get_client()

    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )

    if isinstance(response, str):
        text = _parse_sse_response(response)
        provider_raw_text = response
        request_id = None
    else:
        text = response.content[0].text
        provider_raw_text = text
        request_id = getattr(response, "id", None)
    if binding is not None:
        binding[0].record_response(
            binding[1], attempt, provider, model, provider_raw_text, request_id
        )
    return text


class Perspective(ABC):
    """투자 관점 ABC — 모든 관점이 구현해야 하는 인터페이스"""

    name: str

    @abstractmethod
    def analyze(self, data: PerspectiveInput) -> PerspectiveResult:
        """종목 데이터를 받아 판정 결과를 반환한다."""
        ...
