"""가치 투자 관점 — PER/PBR/배당 기반 절대 가치 평가

펀더멘털 데이터 없으면 N/A 반환.
SPEC §3-5 출력 형식 준수.
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
당신은 가치 투자 분석 전문가입니다. PER, PBR, 배당수익률 기반으로 절대적 가치를 평가합니다.

## 분석 원칙

1. **PER 분석**: 업종 평균 대비 위치. 15 이하 저평가, 15-25 적정, 25+ 고평가 (업종별 상이)
2. **PBR 분석**: 1.0 이하 자산 대비 저평가, 1.0-2.0 적정, 2.0+ 고평가
3. **배당수익률**: 시장금리 대비 비교 (한국 3.5%%, 미국 4.5%%). 시장금리 이상이면 배당 매력
4. **PEG 비율**: PER / 이익성장률. 1.0 이하 = 성장 대비 저평가
5. **동종 비교**: 같은 섹터 내 밸류에이션 상대 비교
6. "다소", "일부" 금지 → 수치 기반 판단만

## 출력 규칙

**반드시 아래 JSON 형식으로만 응답하세요.**

```json
{
  "perspective": "value",
  "verdict": "BUY 또는 SELL 또는 HOLD",
  "confidence": 0.0~1.0,
  "reasoning": [
    "밸류에이션 분석 1",
    "밸류에이션 분석 2"
  ],
  "reason": "한 줄 요약",
  "metrics": {"per": 수치, "pbr": 수치, "div_yield": 수치, "sector_avg_per": 추정치},
  "action": {"type": "buy/sell/hold", "fair_value_estimate": 적정가}
}
```
"""


def _build_user_prompt(data: PerspectiveInput) -> str:
    from src.data.market import is_us_ticker
    is_us = is_us_ticker(data.ticker)
    currency = "달러" if is_us else "원"

    lines = []
    lines.append(f"## 종목: {data.name} ({data.ticker})")
    if is_us:
        lines.append("(미국 시장 종목)")
    lines.append("")

    sig = data.signals
    lines.append(f"### 현재가: {sig['current_price']:,.2f}{currency}" if is_us else f"### 현재가: {sig['current_price']:,.0f}{currency}")
    lines.append(f"- 52주 고가: {sig['high_52w']:,.2f}{currency} / 저가: {sig['low_52w']:,.2f}{currency}" if is_us else f"- 52주 고가: {sig['high_52w']:,.0f}{currency} / 저가: {sig['low_52w']:,.0f}{currency}")
    lines.append("")

    lines.append("### 펀더멘털 데이터")
    f = data.fundamentals
    lines.append(f"- PER: {f.get('per', 'N/A')}")
    lines.append(f"- PBR: {f.get('pbr', 'N/A')}")
    lines.append(f"- 배당수익률: {f.get('div_yield', 'N/A')}%%")
    if "consensus_per" in f:
        lines.append(f"- 컨센서스 PER: {f['consensus_per']}")
    if "market_cap_billion" in f:
        lines.append(f"- 시가총액: {f['market_cap_billion']}억원")
    lines.append("")

    if data.position:
        pos = data.position
        lines.append("### 보유 포지션")
        lines.append(f"- 매수가: {pos['entry_price']:,.2f}{currency}" if is_us else f"- 매수가: {pos['entry_price']:,.0f}{currency}")
        pnl = pos.get("pnl_pct")
        if pnl is not None:
            lines.append(f"- 현재 수익률: {pnl:+.2f}%%")
    lines.append("")

    # 웹 검색 컨텍스트 (Phase 10)
    if data.web_context:
        from src.data.web_search import format_web_context_for_prompt
        web_text = format_web_context_for_prompt(data.web_context, "value")
        if web_text:
            lines.append("")
            lines.append(web_text)

    lines.append("위 데이터를 기반으로 가치 투자 관점에서 절대/상대 밸류에이션을 분석하고 JSON으로 응답하세요.")
    lines.append("웹 검색으로 컨센서스/목표주가가 제공된 경우 이를 참조하세요.")

    return "\n".join(lines)


class ValuePerspective(Perspective):
    """가치 투자 관점 — PER/PBR/배당 기반 절대 가치 평가"""

    name = "value"

    def analyze(self, data: PerspectiveInput) -> PerspectiveResult:
        # 펀더멘털 데이터 없으면 N/A
        if not data.fundamentals or ("per" not in data.fundamentals and "pbr" not in data.fundamentals):
            return make_na_result(self.name, "PER/PBR 데이터 없음 — 가치 관점 비활성화")

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
        if "metrics" in parsed:
            extra["metrics"] = parsed["metrics"]

        return PerspectiveResult(
            perspective=self.name,
            verdict=verdict,
            confidence=float(parsed.get("confidence", 0.5)),
            reasoning=parsed.get("reasoning", []),
            reason=parsed.get("reason", ""),
            action=parsed.get("action", {"type": "none"}),
            extra=extra,
        )
