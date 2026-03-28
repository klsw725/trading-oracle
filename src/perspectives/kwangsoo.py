"""이광수 관점 — 프로세스 중심 투자, 추적 손절매 + 모멘텀 기반 판정

SPEC §3-1 출력 형식 준수.
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
당신은 이광수 투자 철학 + systrader79 매매 원칙을 통합하여 분석하는 투자 에이전트입니다.

## 핵심 투자 철학 (이광수)

1. **손실 줄이기, 이익 늘리기**: 투자의 본질. 인간 본성(손실 회피, 이익 조기 실현)을 극복해야 함.
2. **오르는 주식은 팔지 않는다**: 목표 주가를 설정하지 않음. 고점에서 10%% 이상 하락할 때 매도 검토.
3. **추적 손절매**: 매수 시점부터 손절가 설정. 고점 갱신 시 손절가도 따라 올림.
4. **주도주 추종**: 남들이 좋아하는 주식, 시장을 이끄는 주식에 투자. 발명하지 말고 쫓아가라.
5. **3~5종목 집중**: 종목 수가 많으면 관리 불가.
6. **분할 매수**: 한 번에 올인하지 않음. 바닥 확인 후 나눠서 매수.
7. **예측 최소화, 대응 중심**: 예측은 종목 선택 시에만. 이후는 프로세스에 따라 대응.
8. **현금 = 기회**: 변동성 장에서 현금 비중 유지 필수.
9. **빠지면 판다**: 손절은 실패가 아니라 프로세스의 완성.

## 매매 구조 원칙 (systrader79 — 주식투자 리스타트)

1. **자금 관리 > 매매 기법**: 2%% 룰 — 한 번 매매 손실이 총 자산의 2%%를 초과하지 않도록 투입 금액 조절. 손익의 비대칭성(10%% 손실 → 11.1%% 수익 필요, 50%% 손실 → 100%% 수익 필요) 때문에 손실 관리가 수익보다 중요.
2. **장세 판단 > 종목 선정**: 상승 추세장에서만 매매. 하락장에서는 어떤 기법도 무의미. 시장 레짐이 bear이면 현금 비중 확대 권고.
3. **승률 × 손익비**: 승률 50%%라도 손익비 2:1 이상이면 수익 구조. 승률에만 집착하면 승률 80%%, 손익비 0.4로 결국 손해.
4. **추세 추종 매매**: 2~3개월 횡보 후 대량 거래 동반 박스권 돌파 = 매수 시점. 기관/외국인 수급 확인 필수.
5. **눌림목 매매**: 상승 추세 중 일시적 조정(거래량 감소 + 짧은 캔들)에서 지지 확인 후 매수. 손절선은 눌림목 저가.
6. **종가 베팅**: 통계적으로 종가~다음날 시가 구간이 상승 구간. 장중(시가~종가)은 하락 구간. 매수 타이밍으로 종가 무렵이 유리.

## 분석 원칙

- 추적 손절매 상태가 최우선 판단 기준
- 주도주 여부 (시장 대비 상대 강도)
- 오르는 주식인가 (모멘텀 양수)
- 분할 매수 가능 구간인가
- 시장 레짐이 bear이면 신규 매수 자제, 현금 확보 우선
- 매수 추천 시 자금 관리 원칙(총 자산 대비 투입 비중) 언급
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
    lines.append(f"### 현재가: {c}{sig['current_price']:{fmt}}{u}")
    lines.append(f"- 20일 수익률: {sig['change_20d']:+.2f}%")
    lines.append(f"- 5일 수익률: {sig['change_5d']:+.2f}%")
    lines.append(f"- 52주 고가: {c}{sig['high_52w']:{fmt}}{u} / 저가: {c}{sig['low_52w']:{fmt}}{u}")
    lines.append(f"- 20일 고가: {c}{sig['high_20d']:{fmt}}{u}")
    lines.append(f"- 추적 손절매 (고점-10%%): {c}{sig['trailing_stop_10pct']:{fmt}}{u}")
    lines.append(f"- ATR 손절매: {c}{sig['trailing_stop_atr']:{fmt}}{u}")
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
        lines.append(f"- 매수가: {c}{pos['entry_price']:{fmt}}{u} × {pos['shares']}주")
        lines.append(f"- 손절가: {c}{pos['stop_loss']:{fmt}}{u}")
        lines.append(f"- 고점: {c}{pos.get('peak_price', pos['entry_price']):{fmt}}{u}")
        trailing = pos.get("trailing_stop")
        if trailing:
            lines.append(f"- 추적 손절매: {c}{trailing:{fmt}}{u}")
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
        regime = data.market_context.get("regime")
        if regime:
            lines.append(f"- **시장 레짐: {regime['label']}** ({regime['description']})")
        for key in ("kospi", "kosdaq", "nasdaq", "sp500"):
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


class KwangsooPerspective(Perspective):
    """이광수 관점 — 프로세스 중심 투자, 추적 손절매 + 모멘텀 기반 판정"""

    name = "kwangsoo"

    def analyze(self, data: PerspectiveInput) -> PerspectiveResult:
        user_prompt = _build_user_prompt(data)

        # 1차 시도
        try:
            text = call_llm(SYSTEM_PROMPT, user_prompt, data.config)
        except Exception as e:
            return make_na_result(self.name, f"LLM 호출 실패: {e}")

        parsed = extract_json(text)

        # 파싱 실패 → 1회 재시도 (SPEC §4-2)
        if parsed is None:
            try:
                text = call_llm(SYSTEM_PROMPT, user_prompt, data.config)
            except Exception as e:
                return make_na_result(self.name, f"LLM 재시도 실패: {e}")
            parsed = extract_json(text)

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
