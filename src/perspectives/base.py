"""다관점 투자 판정 시스템 — 공통 인터페이스

모든 관점은 이 ABC를 구현한다.
SPEC §4-0 공통 필드 규격 준수.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass, field
from threading import Lock
from typing import Final, Protocol

from pydantic import TypeAdapter, ValidationError

from src.v4.models import JsonValue
from src.perspectives.provider_runtime import ProviderRequest, generate_provider_text


class OhlcvFrame(Protocol):
    @property
    def empty(self) -> bool: ...


@dataclass(frozen=True, slots=True)
class PerspectiveInput:
    """관점 분석에 필요한 입력 데이터 묶음"""

    ticker: str
    name: str
    ohlcv: OhlcvFrame
    signals: dict[str, JsonValue]  # compute_signals() 결과
    fundamentals: dict[str, JsonValue]  # fetch_naver_fundamentals() 결과
    position: dict[str, JsonValue] | None  # 포트폴리오 포지션 (미보유 시 None)
    market_context: dict[str, JsonValue]  # {"kospi": {...}, "kosdaq": {...}}
    config: dict[str, JsonValue]
    web_context: dict[str, JsonValue] = field(default_factory=dict)  # 웹 검색 결과 (Phase 10)
    fx_signal: dict[str, JsonValue] = field(default_factory=dict)  # 환율 팩터 (Phase 17)
    provenance_collector: LlmProvenanceCollector | None = None


@dataclass(frozen=True, slots=True)
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
    action: dict[str, JsonValue]
    extra: dict[str, JsonValue] = field(default_factory=dict)

    def to_dict(self) -> dict[str, JsonValue]:
        reasoning: list[JsonValue] = [item for item in self.reasoning]
        base: dict[str, JsonValue] = {
            "perspective": self.perspective,
            "verdict": self.verdict,
            "confidence": self.confidence,
            "reasoning": reasoning,
            "reason": self.reason,
            "action": self.action,
        }
        base.update(self.extra)
        return base


class LlmProvenanceCollector:
    def __init__(self, config: Mapping[str, JsonValue]) -> None:
        self._config: dict[str, JsonValue] = deepcopy(dict(config))
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
        self._lock: Lock = Lock()
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


_JSON_RECORD: Final = TypeAdapter(dict[str, JsonValue])


def extract_json(text: str) -> dict[str, JsonValue] | None:
    """LLM 응답에서 JSON 추출. 코드블록 내부 또는 raw JSON 모두 처리."""
    code_block = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    candidates = [code_block.group(1).strip()] if code_block is not None else []
    raw_object = re.search(r"\{.*\}", text, re.DOTALL)
    if raw_object is not None:
        candidates.append(raw_object.group(0))
    for candidate in candidates:
        try:
            return _JSON_RECORD.validate_json(candidate)
        except ValidationError:
            continue
    return None


def call_llm(
    system_prompt: str,
    user_prompt: str,
    config: dict[str, JsonValue],
    max_tokens: int = 2048,
) -> str:
    """LLM 호출 → 텍스트 반환. config.llm.provider에 따라 Anthropic/Codex 분기."""
    llm_value = config.get("llm")
    llm_config = llm_value if isinstance(llm_value, dict) else {}
    provider_value = llm_config.get("provider", "anthropic")
    provider = provider_value if isinstance(provider_value, str) else "anthropic"
    model_value = llm_config.get(
        "model",
        "gpt-5.1-codex" if provider == "codex" else "claude-sonnet-4-20250514",
    )
    model = model_value if isinstance(model_value, str) else (
        "gpt-5.1-codex" if provider == "codex" else "claude-sonnet-4-20250514"
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

    response = generate_provider_text(
        ProviderRequest(provider, model, system_prompt, user_prompt, max_tokens)
    )
    if binding is not None:
        binding[0].record_response(
            binding[1], attempt, provider, model, response.raw_text, response.request_id
        )
    return response.text


class Perspective(ABC):
    """투자 관점 ABC — 모든 관점이 구현해야 하는 인터페이스"""

    name: str

    @abstractmethod
    def analyze(self, data: PerspectiveInput) -> PerspectiveResult:
        """종목 데이터를 받아 판정 결과를 반환한다."""
        ...
