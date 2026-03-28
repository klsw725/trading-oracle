"""퀀트 시그널 관점 — 하이브리드 구조

verdict/signals는 technical.py에서 코드로 직접 계산 (실패 없음).
LLM은 reasoning 텍스트만 생성. LLM 실패 시 코드 결과만 반환.
SPEC §3-3 출력 형식 준수.
"""

from src.perspectives.base import (
    Perspective,
    PerspectiveInput,
    PerspectiveResult,
    call_llm,
    extract_json,
)


SYSTEM_PROMPT = """\
당신은 감정 없는 퀀트 분석 기계입니다. 6-시그널 앙상블 보팅 결과를 해석합니다.

## 퀀트 투자 철학 (퀀트의 정석 — 김성진)

1. **확률적 사고**: 퀀트는 예측하지 않는다. 카지노처럼 확률적 우위가 있는 게임을 반복할 뿐이다. 개별 거래의 결과는 알 수 없으나, 대수의 법칙에 따라 장기적으로 수렴한다.
2. **팩터 독립성 (MECE)**: 6개 시그널은 각각 시장의 서로 다른 단면을 포착한다. 모멘텀(추세), EMA(방향), RSI(과열), MACD(가속도), BB(변동성). 이 독립적 시그널들의 앙상블이 단일 시그널보다 견고하다.
3. **과최적화 경계**: 과거에 잘 맞는 것과 미래에 작동하는 것은 다르다. 데이터를 고문하면 거짓 발견을 토해낸다. 시그널의 경제적 논리가 있어야 한다.
4. **손익의 비대칭성**: 10%% 손실 → 11.1%% 수익 필요. 50%% 손실 → 100%% 수익 필요. 손절매는 생존의 도구이며, 손절 없는 매매는 자살행위다.
5. **시장 국면 의존**: 동일한 시그널도 시장 국면(상승/하락/횡보)에 따라 성과가 달라진다. Bull 만장일치여도 하락 추세장에서는 신중해야 한다.

## 분석 대상 시그널

1. 모멘텀 (20일 수익률): >3%% Bull, <-3%% Bear
2. 단기 모멘텀 (5일 수익률): >1.5%% Bull, <-1.5%% Bear
3. EMA 크로스오버: 단기 > 장기 = Bull
4. RSI: >50 Bull, <50 Bear. 69+ 과매수, 31- 과매도
5. MACD 히스토그램: >0 Bull, <0 Bear
6. BB 압축: 80%%ile 미만 = 변동성 수축 (돌파 임박)

MIN_VOTES = 4: 6개 중 4개 이상 동의 시 시그널 발생.

## 분석 원칙

- 각 시그널의 현재 값과 Bull/Bear 여부를 순서대로 해석
- 투표 결과를 종합하여 왜 이 verdict가 나왔는지 설명
- 시그널 간 합의도(몇 대 몇)의 신뢰도를 확률적으로 해석
- RSI 과매수/과매도 상태는 별도 경고
- ATR 기반 손절매 가격 해석 — 손절은 실패가 아니라 시스템의 일부
- "다소", "일부" 금지 → 수치 기반 판단만

## 출력 규칙

**반드시 아래 JSON 형식으로만 응답하세요.**

```json
{
  "reasoning": [
    "시그널별 해석 1",
    "시그널별 해석 2"
  ]
}
```

reasoning 필드만 생성하세요. verdict, confidence, signals는 코드에서 계산합니다.
"""


def _build_user_prompt(data: PerspectiveInput) -> str:
    sig = data.signals
    s = sig["signals"]

    lines = []
    lines.append(f"## {data.name} ({data.ticker}) 시그널 해석 요청")
    lines.append("")
    lines.append(f"현재가: {sig['current_price']:,.0f}원")
    lines.append(f"판정: {sig['verdict']} (Bull {sig['bull_votes']}/6, Bear {sig['bear_votes']}/6)")
    lines.append("")
    lines.append("### 시그널 상세")
    lines.append(f"1. 모멘텀 20일: {s['momentum']['value']:+.1f}%% → {'Bull' if s['momentum']['bull'] else 'Bear' if s['momentum']['bear'] else 'Neutral'}")
    lines.append(f"2. 단기 모멘텀 5일: {s['short_momentum']['value']:+.1f}%% → {'Bull' if s['short_momentum']['bull'] else 'Bear' if s['short_momentum']['bear'] else 'Neutral'}")
    lines.append(f"3. EMA: 단기 {s['ema_crossover']['fast']:,.0f} vs 장기 {s['ema_crossover']['slow']:,.0f} → {'Bull (골든크로스)' if s['ema_crossover']['bull'] else 'Bear (데드크로스)'}")
    lines.append(f"4. RSI(8): {s['rsi']['value']:.1f} → {'과매수' if s['rsi']['overbought'] else '과매도' if s['rsi']['oversold'] else 'Bull' if s['rsi']['bull'] else 'Bear'}")
    lines.append(f"5. MACD 히스토그램: {s['macd']['histogram']:+.2f} → {'Bull' if s['macd']['bull'] else 'Bear'}")
    lines.append(f"6. BB 압축: {s['bb_compression']['percentile']:.0f}%%ile → {'압축 (돌파 임박)' if s['bb_compression']['compressed'] else '확장'}")
    lines.append("")
    lines.append(f"ATR 손절매: {sig['trailing_stop_atr']:,.0f}원")
    lines.append(f"추적 손절매 (고점-10%%): {sig['trailing_stop_10pct']:,.0f}원")
    lines.append("")
    lines.append("각 시그널을 순서대로 해석하고, 종합 판단의 근거를 reasoning으로 제공하세요.")

    return "\n".join(lines)


def _code_verdict_to_perspective(sig: dict) -> tuple[str, float]:
    """technical.py의 verdict를 perspective verdict로 변환"""
    verdict_map = {"BULLISH": "BUY", "BEARISH": "SELL", "NEUTRAL": "HOLD"}
    verdict = verdict_map.get(sig["verdict"], "HOLD")

    bull = sig["bull_votes"]
    bear = sig["bear_votes"]
    total = max(bull + bear, 1)
    confidence = max(bull, bear) / 6.0

    return verdict, round(confidence, 2)


def _build_signals_dict(sig: dict) -> dict:
    """시그널 상세 dict 구성"""
    s = sig["signals"]
    d = {
        "momentum": "bull" if s["momentum"]["bull"] else "bear" if s["momentum"]["bear"] else "neutral",
        "short_momentum": "bull" if s["short_momentum"]["bull"] else "bear" if s["short_momentum"]["bear"] else "neutral",
        "ema": "bull" if s["ema_crossover"]["bull"] else "bear",
        "rsi": "bull" if s["rsi"]["bull"] else "bear",
        "macd": "bull" if s["macd"]["bull"] else "bear",
        "bb": "compressed" if s["bb_compression"]["compressed"] else "expanded",
    }
    if "bb_position" in s:
        d["bb_position"] = round(s["bb_position"]["value"], 2)
    if "volume" in s:
        d["volume_ratio"] = round(s["volume"]["ratio"], 2)
    return d


class QuantPerspective(Perspective):
    """퀀트 관점 — 하이브리드: 코드 계산 verdict + LLM reasoning"""

    name = "quant"

    def analyze(self, data: PerspectiveInput) -> PerspectiveResult:
        sig = data.signals
        verdict, confidence = _code_verdict_to_perspective(sig)
        signals_dict = _build_signals_dict(sig)

        # LLM reasoning 생성 (실패해도 코드 결과 반환)
        reasoning = []
        try:
            user_prompt = _build_user_prompt(data)
            text = call_llm(SYSTEM_PROMPT, user_prompt, data.config, max_tokens=1024)
            parsed = extract_json(text)
            if parsed and "reasoning" in parsed:
                reasoning = parsed["reasoning"]
        except Exception:
            pass

        # LLM reasoning 실패 시 코드 기반 최소 reasoning
        if not reasoning:
            s = sig["signals"]
            reasoning = [
                f"Bull {sig['bull_votes']}/6, Bear {sig['bear_votes']}/6 → {sig['verdict']}",
                f"RSI {s['rsi']['value']:.1f} ({'과매수' if s['rsi']['overbought'] else '과매도' if s['rsi']['oversold'] else '중립'})",
                f"MACD 히스토그램 {s['macd']['histogram']:+.2f}",
            ]

        action = {"type": verdict.lower()}
        if verdict == "SELL":
            action["stop_loss"] = sig["trailing_stop_atr"]

        return PerspectiveResult(
            perspective=self.name,
            verdict=verdict,
            confidence=confidence,
            reasoning=reasoning,
            reason=f"{'Bull' if verdict == 'BUY' else 'Bear' if verdict == 'SELL' else 'Neutral'} {sig['bull_votes']}/6 vs {sig['bear_votes']}/6",
            action=action,
            extra={"signals": signals_dict},
        )
