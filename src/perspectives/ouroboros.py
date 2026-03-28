"""포렌식 감사관 관점 — OUROBOROS 프레임워크 기반

희석 리스크, 내부자 거래, 기관 수급 판정.
SPEC §3-2 출력 형식 준수.
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
당신은 OUROBOROS 프레임워크 기반의 포렌식 감사관입니다. 기업의 숨겨진 리스크를 파헤치는 냉소적 전문가.

## 분석 원칙

1. **희석 리스크**: 유상증자, 전환사채(CB), 신주인수권부사채(BW), 워런트 발행 이력 확인
2. **내부자 거래**: 경영진/대주주 매도 패턴 → 탈출 신호 여부
3. **기관 수급**: 외국인/기관 순매매 추이 → 스마트 머니 이탈 여부
4. **재무 건전성**: 부채비율, 현금소진율, 영업이익률 추세
5. **Devil's Advocate**: 기관이 이 종목을 버린다면 그 이유는 무엇인가?

## 판단 기준

- 희석 리스크 감지 시 → 즉시 경고
- 내부자 대량 매도 → 강한 매도 시그널
- 기관 이탈 + 고평가 → 매도
- 리스크 요인 없음 → HOLD (적극 매수는 다른 관점의 영역)
- "다소", "일부" 금지 → 수치로 증명하거나 "확인 불가"로 명시

## 출력 규칙

**반드시 아래 JSON 형식으로만 응답하세요. JSON 외의 텍스트를 출력하지 마세요.**

```json
{
  "perspective": "ouroboros",
  "verdict": "BUY 또는 SELL 또는 HOLD",
  "confidence": 0.0~1.0,
  "reasoning": [
    "단계별 포렌식 분석 1",
    "단계별 포렌식 분석 2"
  ],
  "reason": "한 줄 요약",
  "risks": ["리스크1", "리스크2"],
  "action": {"type": "buy/sell/hold", "watch": "모니터링 대상"}
}
```
"""


def _build_user_prompt(data: PerspectiveInput) -> str:
    from src.data.market import is_us_ticker
    is_us = is_us_ticker(data.ticker)
    c = "$" if is_us else ""
    u = "" if is_us else "원"
    fmt = ",.2f" if is_us else ",.0f"

    lines = []
    lines.append(f"## 종목: {data.name} ({data.ticker})")
    if is_us:
        lines.append("(미국 시장 종목)")
    lines.append("")

    sig = data.signals
    lines.append(f"### 시장 데이터")
    lines.append(f"- 현재가: {c}{sig['current_price']:{fmt}}{u}")
    lines.append(f"- 20일 수익률: {sig['change_20d']:+.2f}%%")
    lines.append(f"- 5일 수익률: {sig['change_5d']:+.2f}%%")
    lines.append(f"- 52주 고가: {c}{sig['high_52w']:{fmt}}{u} / 저가: {c}{sig['low_52w']:{fmt}}{u}")
    lines.append(f"- 시그널 판정: {sig['verdict']} (Bull {sig['bull_votes']}/6, Bear {sig['bear_votes']}/6)")
    lines.append("")

    if data.fundamentals:
        lines.append("### 펀더멘털")
        f = data.fundamentals
        if "per" in f:
            lines.append(f"- PER: {f['per']}")
        if "pbr" in f:
            lines.append(f"- PBR: {f['pbr']}")
        if "div_yield" in f:
            lines.append(f"- 배당수익률: {f['div_yield']}%%")
        if "market_cap_billion" in f:
            lines.append(f"- 시가총액: {f['market_cap_billion']}억원")
        lines.append("")

    if data.position:
        pos = data.position
        lines.append("### 보유 포지션")
        lines.append(f"- 매수가: {c}{pos['entry_price']:{fmt}}{u} × {pos['shares']}주")
        pnl = pos.get("pnl_pct")
        if pnl is not None:
            lines.append(f"- 현재 수익률: {pnl:+.2f}%%")
    else:
        lines.append("### 미보유 종목")

    if data.market_context:
        lines.append("")
        lines.append("### 시장 환경")
        regime = data.market_context.get("regime")
        if regime:
            lines.append(f"- **시장 레짐: {regime['label']}** ({regime['description']})")
        for key in ("kospi", "kosdaq", "nasdaq", "sp500"):
            idx = data.market_context.get(key)
            if idx:
                lines.append(f"- {idx['name']}: {idx['close']:,.2f} (20일 {idx['change_20d']:+.1f}%%)")

    lines.append("")
    lines.append("위 데이터를 기반으로 포렌식 감사관 관점에서 숨겨진 리스크를 분석하고 JSON으로 응답하세요.")
    lines.append("주의: 제공된 데이터 범위 내에서 분석하되, 공개적으로 알려진 기업 정보(유상증자, CB 이력 등)를 활용하세요.")

    return "\n".join(lines)


class OuroborosPerspective(Perspective):
    """포렌식 감사관 — 희석 리스크, 내부자 거래, 기관 수급 판정"""

    name = "ouroboros"

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
        if "risks" in parsed:
            extra["risks"] = parsed["risks"]

        return PerspectiveResult(
            perspective=self.name,
            verdict=verdict,
            confidence=float(parsed.get("confidence", 0.5)),
            reasoning=parsed.get("reasoning", []),
            reason=parsed.get("reason", ""),
            action=parsed.get("action", {"type": "none"}),
            extra=extra,
        )
