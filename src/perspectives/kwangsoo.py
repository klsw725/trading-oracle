"""이광수 관점 — 프로세스 중심 투자, 추적 손절매 + 모멘텀 기반 판정

SPEC §3-1 출력 형식 준수.
"""

import json
import re

from src.perspectives.base import (
    Perspective,
    PerspectiveInput,
    PerspectiveResult,
    make_na_result,
)
from src.agent.oracle import get_client, _parse_sse_response


SYSTEM_PROMPT = """\
당신은 이광수 투자 철학을 따르는 투자 분석 에이전트입니다.

## 핵심 투자 철학

1. **손실 줄이기, 이익 늘리기**: 투자의 본질. 인간 본성(손실 회피, 이익 조기 실현)을 극복해야 함.
2. **오르는 주식은 팔지 않는다**: 목표 주가를 설정하지 않음. 고점에서 10% 이상 하락할 때 매도 검토.
3. **추적 손절매**: 매수 시점부터 손절가 설정. 고점 갱신 시 손절가도 따라 올림.
4. **주도주 추종**: 남들이 좋아하는 주식, 시장을 이끄는 주식에 투자. 발명하지 말고 쫓아가라.
5. **3~5종목 집중**: 종목 수가 많으면 관리 불가.
6. **분할 매수**: 한 번에 올인하지 않음. 바닥 확인 후 나눠서 매수.
7. **예측 최소화, 대응 중심**: 예측은 종목 선택 시에만. 이후는 프로세스에 따라 대응.
8. **현금 = 기회**: 변동성 장에서 현금 비중 유지 필수.
9. **빠지면 판다**: 손절은 실패가 아니라 프로세스의 완성.

## 분석 원칙

- 추적 손절매 상태가 최우선 판단 기준
- 주도주 여부 (시장 대비 상대 강도)
- 오르는 주식인가 (모멘텀 양수)
- 분할 매수 가능 구간인가
- "다소", "일부" 금지 → 수치로 증명하거나 "확인 불가"로 명시

## 출력 규칙

**반드시 아래 JSON 형식으로만 응답하세요. JSON 외의 텍스트를 출력하지 마세요.**

```json
{
  "perspective": "kwangsoo",
  "verdict": "BUY 또는 SELL 또는 HOLD",
  "confidence": 0.0~1.0,
  "reasoning": [
    "단계별 추론 과정 1",
    "단계별 추론 과정 2",
    "..."
  ],
  "reason": "한 줄 요약 결론",
  "action": {"type": "buy/sell/hold", "price": 가격, "urgency": "immediate/planned/watch"},
  "philosophy": "이광수 철학에 기반한 한 줄 조언"
}
```
"""


def _build_user_prompt(data: PerspectiveInput) -> str:
    lines = []
    lines.append(f"## 종목: {data.name} ({data.ticker})")
    lines.append("")

    sig = data.signals
    lines.append(f"### 현재가: {sig['current_price']:,.0f}원")
    lines.append(f"- 20일 수익률: {sig['change_20d']:+.2f}%")
    lines.append(f"- 5일 수익률: {sig['change_5d']:+.2f}%")
    lines.append(f"- 52주 고가: {sig['high_52w']:,.0f}원 / 저가: {sig['low_52w']:,.0f}원")
    lines.append(f"- 20일 고가: {sig['high_20d']:,.0f}원")
    lines.append(f"- 추적 손절매 (고점-10%%): {sig['trailing_stop_10pct']:,.0f}원")
    lines.append(f"- ATR 손절매: {sig['trailing_stop_atr']:,.0f}원")
    lines.append("")

    # 시그널
    lines.append("### 6-시그널 앙상블")
    lines.append(f"- 판정: {sig['verdict']} (Bull {sig['bull_votes']}/6, Bear {sig['bear_votes']}/6)")
    s = sig["signals"]
    lines.append(f"- 모멘텀 20일: {s['momentum']['value']:+.1f}%% ({'Bull' if s['momentum']['bull'] else 'Bear' if s['momentum']['bear'] else 'Neutral'})")
    lines.append(f"- 단기 모멘텀 5일: {s['short_momentum']['value']:+.1f}%% ({'Bull' if s['short_momentum']['bull'] else 'Bear' if s['short_momentum']['bear'] else 'Neutral'})")
    lines.append(f"- EMA: 단기 {s['ema_crossover']['fast']:,.0f} vs 장기 {s['ema_crossover']['slow']:,.0f} ({'Bull' if s['ema_crossover']['bull'] else 'Bear'})")
    lines.append(f"- RSI({data.config.get('signals', {}).get('rsi_period', 8)}): {s['rsi']['value']:.1f} ({'과매수' if s['rsi']['overbought'] else '과매도' if s['rsi']['oversold'] else 'Bull' if s['rsi']['bull'] else 'Bear'})")
    lines.append(f"- MACD 히스토그램: {s['macd']['histogram']:+.2f} ({'Bull' if s['macd']['bull'] else 'Bear'})")
    lines.append(f"- BB 압축: {s['bb_compression']['percentile']:.0f}%%ile ({'압축' if s['bb_compression']['compressed'] else '확장'})")
    lines.append("")

    # 포트폴리오 포지션
    if data.position:
        pos = data.position
        lines.append("### 보유 포지션")
        lines.append(f"- 매수가: {pos['entry_price']:,.0f}원 × {pos['shares']}주")
        lines.append(f"- 손절가: {pos['stop_loss']:,.0f}원")
        lines.append(f"- 고점: {pos.get('peak_price', pos['entry_price']):,.0f}원")
        trailing = pos.get("trailing_stop")
        if trailing:
            lines.append(f"- 추적 손절매: {trailing:,.0f}원")
        pnl = pos.get("pnl_pct")
        if pnl is not None:
            lines.append(f"- 현재 수익률: {pnl:+.2f}%%")
        if pos.get("reason"):
            lines.append(f"- 매수 이유: {pos['reason']}")
    else:
        lines.append("### 미보유 종목 — 신규 매수 여부 판단 필요")

    # 시장 맥락
    if data.market_context:
        lines.append("")
        lines.append("### 시장 환경")
        for key in ("kospi", "kosdaq"):
            idx = data.market_context.get(key)
            if idx:
                lines.append(f"- {idx['name']}: {idx['close']:,.2f} (5일 {idx['change_5d']:+.1f}%%, 20일 {idx['change_20d']:+.1f}%%)")

    # 펀더멘털
    if data.fundamentals:
        lines.append("")
        lines.append("### 펀더멘털")
        f = data.fundamentals
        if "per" in f:
            lines.append(f"- PER: {f['per']}")
        if "pbr" in f:
            lines.append(f"- PBR: {f['pbr']}")
        if "div_yield" in f:
            lines.append(f"- 배당수익률: {f['div_yield']}%%")

    lines.append("")
    lines.append("위 데이터를 이광수 투자 철학에 따라 분석하고, 지정된 JSON 형식으로 응답하세요.")

    return "\n".join(lines)


def _extract_json(text: str) -> dict | None:
    """LLM 응답에서 JSON 추출. 코드블록 내부 또는 raw JSON 모두 처리."""
    # 코드블록 내부 JSON
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # raw JSON (첫 번째 { ... } 블록)
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    return None


def _call_llm(user_prompt: str, config: dict) -> str:
    """Claude API 호출 → 텍스트 반환. SSE raw string 처리 포함."""
    client = get_client()
    llm_config = config.get("llm", {})
    model = llm_config.get("model", "claude-sonnet-4-20250514")
    max_tokens = llm_config.get("max_tokens", 2048)

    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )

    if isinstance(response, str):
        return _parse_sse_response(response)
    return response.content[0].text


class KwangsooPerspective(Perspective):
    """이광수 관점 — 프로세스 중심 투자, 추적 손절매 + 모멘텀 기반 판정"""

    name = "kwangsoo"

    def analyze(self, data: PerspectiveInput) -> PerspectiveResult:
        user_prompt = _build_user_prompt(data)

        # 1차 시도
        try:
            text = _call_llm(user_prompt, data.config)
        except Exception as e:
            return make_na_result(self.name, f"LLM 호출 실패: {e}")

        parsed = _extract_json(text)

        # 파싱 실패 → 1회 재시도 (SPEC §4-2)
        if parsed is None:
            try:
                text = _call_llm(user_prompt, data.config)
            except Exception as e:
                return make_na_result(self.name, f"LLM 재시도 실패: {e}")
            parsed = _extract_json(text)

        if parsed is None:
            return make_na_result(self.name, "JSON 파싱 실패 (2회 시도)")

        # verdict 검증
        verdict = parsed.get("verdict", "").upper()
        if verdict not in ("BUY", "SELL", "HOLD"):
            return make_na_result(self.name, f"잘못된 verdict: {verdict}")

        extra = {}
        if "philosophy" in parsed:
            extra["philosophy"] = parsed["philosophy"]

        return PerspectiveResult(
            perspective=self.name,
            verdict=verdict,
            confidence=float(parsed.get("confidence", 0.5)),
            reasoning=parsed.get("reasoning", []),
            reason=parsed.get("reason", ""),
            action=parsed.get("action", {"type": "none"}),
            extra=extra,
        )
