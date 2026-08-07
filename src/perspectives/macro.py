from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Final, override

from anthropic import APIError
from httpx import HTTPError
from pydantic import TypeAdapter

from src.causal.prompt_injection_models import VerifiedPromptRecord
from src.causal.prompt_injection_runtime import (
    PROMPT_PACKAGE_PATH,
    load_verified_prompt_records,
)
import src.perspectives.base as perspective_base
from src.perspectives.macro_prompt import build_macro_prompt
from src.perspectives.macro_prompt_models import (
    MACRO_PROMPT_SOURCE_ADAPTER,
    MacroPromptSource,
)
from src.perspectives.macro_response import parse_macro_response
from src.v4.models import JsonValue


SYSTEM_PROMPT: Final = """\
당신은 매크로 경제 분석 전문가입니다. 금리, 환율, 지정학, 섹터 사이클의 인과 체인으로 개별 종목의 투자 판단을 내립니다.

## 분석 원칙

1. **핵심 변수 식별**: 이 기업의 이익에 가장 직접적인 영향을 미치는 매크로 변수 파악
2. **인과 체인 구성**: A → B → C 형태로 매크로 변수가 기업 이익에 미치는 경로 추적
3. **섹터 사이클**: 해당 섹터의 현재 위치 (상승/피크/하강/바닥) 판단
4. **금리/환율 영향**: 금리 방향, 환율 수준이 이 기업에 미치는 구체적 영향
5. **지정학적 요인**: 무역 분쟁, 규제, 지정학 리스크가 이 기업에 미치는 영향
6. "다소", "일부" 금지 → 수치로 증명하거나 "확인 불가"로 명시

## 출력 규칙

**반드시 아래 JSON 형식으로만 응답하세요.**

```json
{
  "perspective": "macro",
  "verdict": "BUY 또는 SELL 또는 HOLD",
  "confidence": 0.0~1.0,
  "reasoning": [
    "매크로 인과 분석 1",
    "매크로 인과 분석 2"
  ],
  "reason": "한 줄 요약",
  "causal_chain": ["원인1", "원인2", "결과"],
  "action": {"type": "buy/sell/hold", "condition": "조건"}
}
```
"""


_CONFIG = TypeAdapter(dict[str, JsonValue])
_CALL_LLM: Final[
    Callable[[str, str, dict[str, JsonValue]], str]
] = perspective_base.call_llm
_LLM_ERRORS: Final = (
    APIError,
    HTTPError,
    OSError,
    RuntimeError,
    ValueError,
)


def get_macro_verified_prompt_records(
    keywords: list[str],
    package_path: Path = PROMPT_PACKAGE_PATH,
    as_of: str | None = None,
    source_path: Path | None = None,
) -> tuple[VerifiedPromptRecord, ...]:
    return (
        load_verified_prompt_records(keywords, package_path, as_of)
        if source_path is None
        else load_verified_prompt_records(keywords, package_path, as_of, source_path)
    )


def _prompt_source(data: perspective_base.PerspectiveInput) -> MacroPromptSource:
    return MACRO_PROMPT_SOURCE_ADAPTER.validate_python(
        {
            "ticker": data.ticker,
            "name": data.name,
            "signals": data.signals,
            "fundamentals": data.fundamentals,
            "market_context": data.market_context,
            "web_context": data.web_context,
            "fx_signal": data.fx_signal or None,
        }
    )


class MacroPerspective(perspective_base.Perspective):
    name: str = "macro"

    @override
    def analyze(
        self, data: perspective_base.PerspectiveInput
    ) -> perspective_base.PerspectiveResult:
        user_prompt = build_macro_prompt(_prompt_source(data)).text
        config = _CONFIG.validate_python(data.config)
        try:
            text = _CALL_LLM(SYSTEM_PROMPT, user_prompt, config)
        except _LLM_ERRORS as error:
            return perspective_base.make_na_result(self.name, f"LLM 호출 실패: {error}")
        parsed = parse_macro_response(text)
        if parsed is None:
            try:
                text = _CALL_LLM(SYSTEM_PROMPT, user_prompt, config)
            except _LLM_ERRORS as error:
                return perspective_base.make_na_result(
                    self.name, f"LLM 재시도 실패: {error}"
                )
            parsed = parse_macro_response(text)
        if parsed is None:
            return perspective_base.make_na_result(self.name, "JSON 파싱 실패 (2회 시도)")
        verdict = parsed.verdict.upper()
        if verdict not in ("BUY", "SELL", "HOLD"):
            return perspective_base.make_na_result(
                self.name, f"잘못된 verdict: {verdict}"
            )
        extra: dict[str, JsonValue] = {}
        if parsed.causal_chain is not None:
            extra["causal_chain"] = list(parsed.causal_chain)
        return perspective_base.PerspectiveResult(
            perspective=self.name,
            verdict=verdict,
            confidence=parsed.confidence,
            reasoning=list(parsed.reasoning),
            reason=parsed.reason,
            action=parsed.action,
            extra=extra,
        )
