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


def _get_causal_context(name: str, ticker: str) -> str:
    """인과 그래프에서 종목 관련 인과 체인 조회. 없으면 빈 문자열."""
    try:
        from src.causal.graph import CausalGraph
        from src.data.market import is_us_ticker
        graph = CausalGraph.load_if_exists()
        if not graph:
            return ""

        keywords = [name]

        if is_us_ticker(ticker):
            # 미국 종목 키워드 매핑
            name_upper = name.upper()
            ticker_upper = ticker.upper()
            if ticker_upper in ("NVDA", "AMD", "INTC", "AVGO", "QCOM", "MU", "TSM") or "SEMICONDUCTOR" in name_upper:
                keywords.extend(["반도체", "AI 반도체", "메모리", "GPU"])
            elif ticker_upper in ("AAPL", "MSFT", "GOOGL", "GOOG", "META", "AMZN") or "TECH" in name_upper:
                keywords.extend(["빅테크", "클라우드", "AI"])
            elif ticker_upper in ("TSLA", "RIVN", "LCID", "NIO", "LI", "XPEV"):
                keywords.extend(["전기차", "자율주행", "배터리"])
            elif ticker_upper in ("JPM", "BAC", "GS", "MS", "C", "WFC"):
                keywords.extend(["금리", "금융", "미국 금리"])
            elif ticker_upper in ("XOM", "CVX", "COP", "SLB", "OXY"):
                keywords.extend(["원유", "에너지", "원자재"])
            elif ticker_upper in ("JNJ", "PFE", "UNH", "ABBV", "MRK", "LLY"):
                keywords.extend(["헬스케어", "바이오", "신약"])
            elif ticker_upper in ("LMT", "RTX", "NOC", "GD", "BA"):
                keywords.extend(["방산", "지정학"])
            else:
                keywords.extend(["미국 금리", "빅테크"])
        else:
            # 한국 종목 키워드 매핑
            if "전자" in name or "반도체" in name or "하이닉스" in name:
                keywords.extend(["반도체", "메모리", "디램"])
            elif "자동차" in name or "기아" in name or "현대" in name:
                keywords.extend(["자동차", "전기차"])
            elif "에어로" in name or "한화" in name:
                keywords.extend(["방산", "무기"])
            elif "금융" in name or "은행" in name or "지주" in name:
                keywords.extend(["금리", "금융"])
            elif "바이오" in name or "제약" in name:
                keywords.extend(["바이오", "신약"])
            elif "에너지" in name or "배터리" in name:
                keywords.extend(["에너지", "배터리", "2차전지"])

        chains = graph.get_related_chains(keywords, depth=2)
        if not chains:
            return ""

        seen = set()
        lines = []
        for chain in chains[:5]:
            for items in (chain.get("causes", [])[:2], chain.get("effects", [])[:2]):
                for c in items:
                    key = (c["subject"], c["relation"], c["object"])
                    if key not in seen:
                        seen.add(key)
                        lines.append(f"- {c['subject']} → ({c['relation']}) → {c['object']}")
        return "\n".join(lines) if lines else ""
    except Exception:
        return ""


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
        regime = data.market_context.get("regime")
        if regime:
            lines.append(f"- **시장 레짐: {regime['label']}** ({regime['description']})")
        for key in ("kospi", "kosdaq", "nasdaq", "sp500"):
            idx = data.market_context.get(key)
            if idx:
                lines.append(f"- {idx['name']}: {idx['close']:,.2f} (5일 {idx['change_5d']:+.1f}%%, 20일 {idx['change_20d']:+.1f}%%)")
        lines.append("")

    # 검증된 인과 체인 (Phase 12 — Granger 검증 통과 트리플 우선)
    try:
        from src.causal.verifier import get_verified_chains
        keywords = [data.name, "환율", "원달러"]
        if "전자" in data.name or "하이닉스" in data.name:
            keywords.extend(["반도체", "금리", "수출 경쟁력"])
        elif "자동차" in data.name or "기아" in data.name or "현대" in data.name:
            keywords.extend(["자동차", "엔화", "수출 경쟁력"])
        elif "에어로" in data.name:
            keywords.extend(["방산", "금리"])
        elif "금융" in data.name or "은행" in data.name:
            keywords.extend(["금리", "금융"])
        elif "화학" in data.name or "철강" in data.name or "포스코" in data.name:
            keywords.extend(["위안화", "원자재 수입", "환율 비용"])
        elif "조선" in data.name:
            keywords.extend(["유로", "수출 경쟁력"])
        # 환율 민감도별 키워드 추가
        if data.fx_signal:
            fx_class = data.fx_signal.get("fx_class", "neutral")
            if fx_class == "export":
                keywords.extend(["수출 경쟁력", "원화 약세 수혜"])
            elif fx_class == "import":
                keywords.extend(["원자재 수입", "환율 비용"])
        verified = get_verified_chains(keywords, min_confidence=0.5)
        if verified:
            lines.append("### 인과 체인 (데이터 검증됨 — Granger test)")
            seen = set()
            for t in verified[:5]:
                v = t["verification"]
                key = (t["subject"], t["object"])
                if key not in seen:
                    seen.add(key)
                    lines.append(f"- {t['subject']} →(lag {v['lag']}일, p={v['p_value']:.4f})→ {t['object']}")
            lines.append("")
    except Exception:
        pass

    # 미검증 인과 그래프 (참고용)
    causal_context = _get_causal_context(data.name, data.ticker)
    if causal_context:
        lines.append("### 인과 그래프 참조 (참고용 — 미검증)")
        lines.append(causal_context)
        lines.append("")

    # 매크로 정량 시계열 (Phase 11)
    try:
        from src.data.macro import get_macro_snapshot, format_macro_for_prompt
        macro_snapshot = get_macro_snapshot()
        macro_quant = format_macro_for_prompt(macro_snapshot)
        if macro_quant:
            lines.append(macro_quant)
            lines.append("")
    except Exception:
        pass

    # 매크로 글로벌 뉴스 (Phase 10 M4)
    web_macro = data.market_context.get("web_macro", {})
    macro_news = []
    for key in ("kr_macro", "us_macro", "rates", "fx"):
        macro_news.extend(web_macro.get(key, []))
    if macro_news:
        lines.append("### 매크로 최신 동향 (웹 검색)")
        for n in macro_news[:7]:
            lines.append(f"- {n.get('title', '')[:80]}")
        lines.append("")

    # 종목별 웹 검색 컨텍스트 (Phase 10 M3)
    if data.web_context:
        from src.data.web_search import format_web_context_for_prompt
        web_text = format_web_context_for_prompt(data.web_context, "macro")
        if web_text:
            lines.append(web_text)

    # 환율 팩터 (Phase 17)
    if data.fx_signal:
        fx = data.fx_signal
        lines.append("### 환율 팩터")
        fx_class_label = {"export": "수출주", "import": "내수/수입주", "neutral": "중립"}.get(fx.get("fx_class", ""), "중립")
        lines.append(f"- 종목 환율 민감도: {fx_class_label} (β={fx.get('fx_beta', 'N/A')})")
        comp = fx.get("components", {})
        mom = comp.get("momentum", {})
        if mom:
            dir_label = {"weakening": "원화 약세 방향", "strengthening": "원화 강세 방향", "flat": "횡보"}.get(mom.get("direction", ""), "")
            lines.append(f"- USD/KRW 5일 변화: {mom.get('usd_krw_5d', 0):+.2f}%% ({dir_label})")
        align = comp.get("regime_alignment", {})
        if align:
            lines.append(f"- 환율-종목 정합성: {align.get('boost', 'NEUTRAL')}")
        cross = comp.get("cross_currency", {})
        for cur, sig in cross.items():
            cur_label = {"JPY_KRW": "엔화", "CNY_KRW": "위안화", "EUR_KRW": "유로"}.get(cur, cur)
            lines.append(f"- {cur_label} 시그널: {sig}")
        lines.append(f"- **환율 종합 판정: {fx.get('fx_verdict', 'NEUTRAL')}** (신뢰도 {fx.get('fx_confidence', 0):.0%%})")
        lines.append("")

    lines.append("위 데이터를 기반으로 매크로 인과 관점에서 분석하고 JSON으로 응답하세요.")
    lines.append("이 기업의 이익에 가장 큰 영향을 미치는 매크로 변수를 식별하고, 인과 체인을 구성하세요.")
    if causal_context:
        lines.append("인과 그래프의 배경 지식을 참고하되, 현재 시장 상황에 맞게 판단하세요.")

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
