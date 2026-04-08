"""시스템 프롬프트 — 이광수 투자 철학 + OUROBOROS 분석 프레임워크"""

SYSTEM_PROMPT = """당신은 '투자 오라클' — 30년 경력의 한국 주식 시장 전문 투자 분석가입니다.

## 핵심 투자 철학 (이광수 대표 기반)

1. **손실 줄이기, 이익 늘리기**: 투자의 본질. 인간 본성(손실 회피, 이익 조기 실현)을 극복해야 함.
2. **오르는 주식은 팔지 않는다**: 목표 주가를 설정하지 않음. 고점에서 10% 이상 하락할 때 매도 검토.
3. **추적 손절매**: 매수 시점부터 손절가 설정. 고점 갱신 시 손절가도 따라 올림.
4. **주도주 추종**: 남들이 좋아하는 주식, 시장을 이끄는 주식에 투자. 발명하지 말고 쫓아가라.
5. **3~5종목 집중**: 종목 수가 많으면 관리 불가. 집중 투자로 복기 가능하게.
6. **기록의 중요성**: 매수이유, 손절가, 변동이유, 매도이유 — 간결하게 기록.
7. **분할 매수**: 한 번에 올인하지 않음. 바닥 확인 후 나눠서 매수.
8. **10시 전 매수 지양**: 개장 초 심리적 충돌 구간. 변동성 큰 시간대 회피.
9. **장기 투자 = 시장에 오래 남기**: 한 종목을 오래 들고 있는 게 아님. 빠지면 팔고, 오르면 보유.
10. **예측 최소화, 대응 중심**: 예측은 종목 선택 시에만. 이후는 프로세스에 따라 대응.
11. **가격이 아닌 가치**: PER(이익 대비), PBR(자산 대비)로 판단. 절대 가격에 현혹되지 않음.
12. **이익이 증가하는 기업**: 실적 발표 확인 후 투자. "이익이 계속 증가할 수 있을까?"가 핵심 질문.
13. **현금의 중요성**: 현금 = 기회. 변동성 장에서 현금 비중 유지 필수.
14. **레버리지/선물/단타 금지**: 투기적 매매 지양. 도파민 중독 경계.

## 기술적 분석 (6-시그널 앙상블 보팅)

6개 시그널 투표 결과가 제공됨:
1. **모멘텀** (20일 수익률)
2. **단기 모멘텀** (5일 수익률)
3. **EMA 크로스오버** (단기 > 장기 = 상승)
4. **RSI** (50 이상 = 상승, 69 이상 = 과매수, 31 이하 = 과매도)
5. **MACD** (히스토그램 양수 = 상승)
6. **볼린저 밴드 압축** (밴드폭 하위 80% = 변동성 수축 = 돌파 임박)

**MIN_VOTES = 4**: 6개 중 4개 이상 동의해야 매수/매도 시그널.

## 출력 규칙

- **100% 한국어**로 출력 (티커, 고유명사 제외)
- 전문 용어는 괄호 안에 쉬운 설명 추가
- "다소", "일부" 금지 → 수치로 증명하거나 "확인 불가"로 명시
- 건조하고 냉소적인 전문가 문체 ("~함", "~임")
- 핵심 데이터는 **Bold** 처리
- 표 금지 → 카드/리스트 형태 출력

## 분석 구조 (포트폴리오 중심)

### 1단계: 시장 환경 진단
- 코스피/코스닥 지수 현황 + 추세 판단

### 2단계: 내 포트폴리오 진단
보유 종목 각각에 대해:
- 현재 수익률 + 평가손익
- 추적 손절매 상태 (정상/경고/이탈)
- 기술적 시그널 판정
- **오늘의 액션**: 계속 보유 / 비중 축소 / 손절 / 추가 매수

### 3단계: 신규 매수 후보 (있을 경우)
- 스크리닝된 종목 중 주도주 조건 충족 종목
- 매수 가격대, 분할 매수 계획, 손절가
- **보유 현금 기준 매수 가능 수량**: 현재가로 나눠서 실제 매수 가능 수량 계산

### 4단계: 종합 전략 (수량 필수)

**모든 행동 지침에 반드시 수량과 금액을 산술적으로 계산하여 제시할 것.**

- **보유 종목별 행동**:
  - 매도: "보유 N주 중 M주 매도 → 매도 대금 약 X원, 잔여 K주"
  - 전량 매도: "N주 전량 매도 → 회수 금액 X원"
  - 추가 매수: "현재가 X원 기준 N주 추가 매수 → 소요 금액 Y원, 매수 후 현금 잔고 Z원"
  - 분할 매수: "1차 N주 (X원 이하 시) → Y원 / 2차 M주 (Z원 이하 시) → W원"
  - 분할 매도: "1차 N주 (X원 도달 시) → 회수 Y원 / 2차 M주 (Z원 도달 시)"
- **현금 운용 계획**: 현재 현금 잔고에서 각 행동 후 남는 현금을 명시
- **포트폴리오 밸런스**: 집중도, 섹터 편중, 종목 수 적절성

**계산 예시**: 현금 1,000만원, 현재가 20만원 → 최대 50주 매수 가능. 분할 매수 시 1차 25주(500만원), 2차 25주(500만원).

### 5단계: 리스크 경고
- 매크로/섹터/개별 종목 리스크

### 투자자에게 한마디
- 이광수 철학에 기반한 조언 한 줄
"""


def build_analysis_prompt(
    market_data: dict, signals_data: list[dict], portfolio: dict, config: dict
) -> str:
    """분석용 유저 프롬프트 생성"""
    from src.common import build_portfolio_summary_for_display, format_price_for_display

    lines = []
    lines.append(f"## 오늘 날짜: {market_data.get('date', 'N/A')}")
    lines.append("")

    # 시장 현황
    if "kospi" in market_data:
        k = market_data["kospi"]
        lines.append(f"### 코스피 지수")
        lines.append(f"- 현재: {k.get('close', 'N/A'):,.2f}")
        lines.append(f"- 5일 변동: {k.get('change_5d', 0):+.2f}%")
        lines.append(f"- 20일 변동: {k.get('change_20d', 0):+.2f}%")
        lines.append("")

    if "kosdaq" in market_data:
        k = market_data["kosdaq"]
        lines.append(f"### 코스닥 지수")
        lines.append(f"- 현재: {k.get('close', 'N/A'):,.2f}")
        lines.append(f"- 5일 변동: {k.get('change_5d', 0):+.2f}%")
        lines.append(f"- 20일 변동: {k.get('change_20d', 0):+.2f}%")
        lines.append("")

    if "nasdaq" in market_data:
        k = market_data["nasdaq"]
        lines.append(f"### 나스닥 지수")
        lines.append(f"- 현재: {k.get('close', 'N/A'):,.2f}")
        lines.append(f"- 5일 변동: {k.get('change_5d', 0):+.2f}%")
        lines.append(f"- 20일 변동: {k.get('change_20d', 0):+.2f}%")
        lines.append("")

    if "sp500" in market_data:
        k = market_data["sp500"]
        lines.append(f"### S&P 500 지수")
        lines.append(f"- 현재: {k.get('close', 'N/A'):,.2f}")
        lines.append(f"- 5일 변동: {k.get('change_5d', 0):+.2f}%")
        lines.append(f"- 20일 변동: {k.get('change_20d', 0):+.2f}%")
        lines.append("")

    # 포트폴리오 현황 (최우선)
    positions = portfolio.get("positions", [])
    summary = build_portfolio_summary_for_display(portfolio, market_data)

    lines.append("### 📋 내 포트폴리오 현황")
    lines.append(f"- 보유 종목 수: {summary['num_positions']}개")
    lines.append(f"- 총 투자금: {summary['total_invested']:,.0f}원")
    lines.append(f"- 총 평가금: {summary['total_market_value']:,.0f}원")
    lines.append(
        f"- 총 손익: {summary['total_pnl']:+,.0f}원 ({summary['total_pnl_pct']:+.2f}%)"
    )
    lines.append(
        f"- 보유 현금: {summary['cash_display']} (현금 비중 {summary['cash_pct']:.1f}%)"
    )
    lines.append(f"- 총 자산: {summary['total_assets']:,.0f}원")
    lines.append("")

    if positions:
        lines.append("### 📊 보유 종목 상세")
        for pos in positions:
            ticker = pos["ticker"]
            lines.append(f"\n#### {pos['name']} ({ticker})")
            lines.append(
                f"- 매수가: {format_price_for_display(ticker, pos['entry_price'], market_data)} × {pos['shares']}주"
            )
            lines.append(
                f"- 투자금: {format_price_for_display(ticker, pos['entry_price'] * pos['shares'], market_data)}"
            )

            current = pos.get("current_price")
            if current:
                pnl_pct = pos.get("pnl_pct", 0)
                pnl_amt = pos.get("pnl_amount", 0)
                lines.append(
                    f"- 현재가: {format_price_for_display(ticker, current, market_data, include_exchange_rate=True)}"
                )
                lines.append(
                    f"- 평가손익: {format_price_for_display(ticker, pnl_amt, market_data, include_exchange_rate=True)} ({pnl_pct:+.2f}%)"
                )
                lines.append(
                    f"- 평가금액: {format_price_for_display(ticker, pos.get('market_value', 0), market_data)}"
                )

            lines.append(
                f"- 손절가: {format_price_for_display(ticker, pos['stop_loss'], market_data)}"
            )
            lines.append(
                f"- 고점: {format_price_for_display(ticker, pos.get('peak_price', pos['entry_price']), market_data)}"
            )
            trailing = pos.get("trailing_stop")
            if trailing:
                lines.append(
                    f"- 추적 손절매: {format_price_for_display(ticker, trailing, market_data)}"
                )

            # 해당 종목의 시그널 매칭
            sig_match = next((s for s in signals_data if s["ticker"] == ticker), None)
            if sig_match:
                sig = sig_match["signals"]
                lines.append(
                    f"- 시그널 판정: **{sig['verdict']}** (Bull {sig['bull_votes']}/6, Bear {sig['bear_votes']}/6)"
                )
                lines.append(f"- RSI: {sig['signals']['rsi']['value']:.1f}")
                lines.append(f"- MACD: {sig['signals']['macd']['histogram']:.2f}")
                lines.append(f"- 20일 수익률: {sig['change_20d']:+.2f}%")

            if pos.get("reason"):
                lines.append(f"- 매수 이유: {pos['reason']}")
            lines.append(f"- 매수일: {pos.get('entry_date', 'N/A')[:10]}")
    else:
        lines.append("**현재 보유 종목 없음** — 신규 매수 후보 분석 필요")

    # 스크리닝/추가 종목 시그널
    portfolio_tickers = {p["ticker"] for p in positions}
    non_portfolio_signals = [
        s for s in signals_data if s["ticker"] not in portfolio_tickers
    ]

    if non_portfolio_signals:
        lines.append("\n### 🔍 신규 매수 후보 기술적 분석")
        for item in non_portfolio_signals:
            lines.append(f"\n#### {item['name']} ({item['ticker']})")
            sig = item["signals"]
            lines.append(
                f"- 현재가: {format_price_for_display(item['ticker'], sig['current_price'], market_data, include_exchange_rate=True)}"
            )
            lines.append(
                f"- 판정: **{sig['verdict']}** (Bull {sig['bull_votes']}/6, Bear {sig['bear_votes']}/6)"
            )
            lines.append(
                f"- 52주 고가: {format_price_for_display(item['ticker'], sig['high_52w'], market_data)} / 저가: {format_price_for_display(item['ticker'], sig['low_52w'], market_data)}"
            )
            lines.append(
                f"- 추적 손절매 (고점-10%): {format_price_for_display(item['ticker'], sig['trailing_stop_10pct'], market_data)}"
            )
            lines.append(
                f"- 5일: {sig['change_5d']:+.2f}% / 20일: {sig['change_20d']:+.2f}%"
            )

            s = sig["signals"]
            lines.append(
                f"- RSI: {s['rsi']['value']:.1f} ({'과매수' if s['rsi']['overbought'] else '과매도' if s['rsi']['oversold'] else '중립'})"
            )
            lines.append(f"- MACD: {s['macd']['histogram']:.2f}")
            lines.append(f"- BB 압축: {s['bb_compression']['percentile']:.0f}%ile")

            if "fundamentals" in item:
                f = item["fundamentals"]
                lines.append(
                    f"- PER: {f.get('per', 'N/A')} / PBR: {f.get('pbr', 'N/A')} / 배당: {f.get('div_yield', 'N/A')}%"
                )

            if item.get("market_cap"):
                cap = item["market_cap"] / 1_000_000_000_000
                lines.append(f"- 시가총액: {cap:.1f}조원")

    # 설정
    lines.append(f"\n### 투자 설정")
    lines.append(f"- 총 자산: {summary['total_assets']:,.0f}원")
    lines.append(f"- 최대 종목 수: {config.get('max_positions', 3)}개")
    lines.append(f"- 손절매 기준: {config.get('stop_loss_pct', 10)}%")
    lines.append(f"- 투자 성향: {config.get('risk_tolerance', 'moderate')}")

    # 현금 기반 매수력 계산 보조
    if summary["cash"] > 0 and non_portfolio_signals:
        lines.append(f"\n### 💰 매수력 참고")
        lines.append(f"- 가용 현금: {summary['cash']:,.0f}원")
        for item in non_portfolio_signals:
            price = item["signals"]["current_price"]
            max_shares = (
                int(summary["cash"] // price) if not item["ticker"].isalpha() else 0
            )
            if max_shares > 0:
                lines.append(
                    f"- {item['name']}: 현재가 {price:,.0f}원 기준 최대 **{max_shares}주** 매수 가능 ({price * max_shares:,.0f}원)"
                )

    lines.append("\n---")
    lines.append(
        "위 데이터를 기반으로 내 포트폴리오 중심의 오늘 투자 전략을 분석 구조에 따라 출력해주세요."
    )
    lines.append(
        "**필수**: 모든 매수/매도 추천에 반드시 **수량(주)**과 **금액(원)**을 산술적으로 계산하여 제시하세요."
    )
    lines.append(
        "분할 매수/매도 시 1차/2차 수량, 목표가, 소요/회수 금액을 구체적으로 나누어 제시하세요."
    )
    lines.append("각 행동 후 예상 현금 잔고를 명시하세요.")

    return "\n".join(lines)
