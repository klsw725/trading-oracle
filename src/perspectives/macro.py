"""매크로 인과 관점 — 금리/환율/섹터 사이클 판정

인과 그래프(Phase 3)가 있으면 참조, 없으면 LLM 내부 지식으로 동작.
SPEC §3-4 출력 형식 준수.
"""

from src.perspectives.base import (
    Perspective,
    PerspectiveInput,
    PerspectiveResult,
    call_llm,
    extract_json,
    make_na_result,
)


SYSTEM_PROMPT = """\
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


def _build_user_prompt(data: PerspectiveInput) -> str:
    lines = []
    lines.append(f"## 종목: {data.name} ({data.ticker})")
    lines.append("")

    sig = data.signals
    lines.append(f"### 시장 데이터")
    lines.append(f"- 현재가: {sig['current_price']:,.0f}원")
    lines.append(f"- 20일 수익률: {sig['change_20d']:+.2f}%%")
    lines.append(f"- 5일 수익률: {sig['change_5d']:+.2f}%%")
    lines.append(f"- 52주 고가: {sig['high_52w']:,.0f}원 / 저가: {sig['low_52w']:,.0f}원")
    lines.append("")

    if data.fundamentals:
        lines.append("### 펀더멘털")
        f = data.fundamentals
        if "per" in f:
            lines.append(f"- PER: {f['per']}")
        if "pbr" in f:
            lines.append(f"- PBR: {f['pbr']}")
        lines.append("")

    if data.market_context:
        lines.append("### 시장 환경")
        for key in ("kospi", "kosdaq"):
            idx = data.market_context.get(key)
            if idx:
                lines.append(f"- {idx['name']}: {idx['close']:,.2f} (5일 {idx['change_5d']:+.1f}%%, 20일 {idx['change_20d']:+.1f}%%)")
        lines.append("")

    # 인과 그래프 참조 (Phase 3 구현 후 활성화)
    # TODO: data/causal_graph.json에서 관련 인과 체인 조회하여 삽입

    lines.append("위 데이터를 기반으로 매크로 인과 관점에서 분석하고 JSON으로 응답하세요.")
    lines.append("이 기업의 이익에 가장 큰 영향을 미치는 매크로 변수를 식별하고, 인과 체인을 구성하세요.")

    return "\n".join(lines)


class MacroPerspective(Perspective):
    """매크로 인과 관점 — 금리/환율/섹터 사이클 판정"""

    name = "macro"

    def analyze(self, data: PerspectiveInput) -> PerspectiveResult:
        user_prompt = _build_user_prompt(data)

        try:
            text = call_llm(SYSTEM_PROMPT, user_prompt, data.config)
        except Exception as e:
            return make_na_result(self.name, f"LLM 호출 실패: {e}")

        parsed = extract_json(text)

        if parsed is None:
            try:
                text = call_llm(SYSTEM_PROMPT, user_prompt, data.config)
            except Exception as e:
                return make_na_result(self.name, f"LLM 재시도 실패: {e}")
            parsed = extract_json(text)

        if parsed is None:
            return make_na_result(self.name, "JSON 파싱 실패 (2회 시도)")

        verdict = parsed.get("verdict", "").upper()
        if verdict not in ("BUY", "SELL", "HOLD"):
            return make_na_result(self.name, f"잘못된 verdict: {verdict}")

        extra = {}
        if "causal_chain" in parsed:
            extra["causal_chain"] = parsed["causal_chain"]

        return PerspectiveResult(
            perspective=self.name,
            verdict=verdict,
            confidence=float(parsed.get("confidence", 0.5)),
            reasoning=parsed.get("reasoning", []),
            reason=parsed.get("reason", ""),
            action=parsed.get("action", {"type": "none"}),
            extra=extra,
        )
