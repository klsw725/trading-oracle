---
name: trading-oracle
description: "한국 주식 투자 조언 에이전트. 포트폴리오 관리 + 주도주 스크리닝 + 기술적 분석 + LLM 종합 전략 제공."
metadata: {"shacs-bot":{"emoji":"🔮","requires":{"bins":["uv"],"env":["ANTHROPIC_API_KEY"]}}}
---

# Trading Oracle — 한국 주식 투자 조언

이광수 투자 철학 기반 일일 투자 조언 에이전트. 6-시그널 앙상블 보팅 + LLM 종합 판단.

모든 명령은 이 스킬의 디렉터리에서 실행해야 함. `uv run main.py`가 진입점.

## 일일 분석 (가장 많이 쓰는 명령)

포트폴리오 기반 분석 — 보유 종목 시그널 + LLM 종합 전략:
```bash
uv run main.py
```

LLM 없이 시그널만:
```bash
uv run main.py --no-llm
```

주도주 스크리닝 포함:
```bash
uv run main.py --screen
```

특정 종목 추가 분석:
```bash
uv run main.py --tickers 005930 000660
```

JSON 출력 (프로그래밍용):
```bash
uv run main.py --json
```

## 포트폴리오 관리

매수 기록:
```bash
uv run main.py add <종목코드> <매수가> <수량> --reason "매수 이유"
```

매도 기록:
```bash
uv run main.py remove <종목코드> --price <매도가> --reason "매도 이유"
```

현금 설정:
```bash
uv run main.py cash <금액>
```

포트폴리오 조회:
```bash
uv run main.py portfolio --json
```

거래 내역:
```bash
uv run main.py history
```

## 종목 코드 참고

| 종목명 | 코드 |
|--------|------|
| 삼성전자 | 005930 |
| SK하이닉스 | 000660 |
| 현대차 | 005380 |
| 한화에어로스페이스 | 012450 |
| KB금융 | 105560 |
| 신한지주 | 055550 |
| LG에너지솔루션 | 373220 |
| 삼성바이오로직스 | 207940 |
| 두산에너빌리티 | 034020 |
| 기아 | 000270 |

## 사용자 요청별 매핑

| 사용자 요청 | 실행 명령 |
|-------------|-----------|
| "오늘 주식 분석해줘" | `uv run main.py` |
| "내 포트폴리오 보여줘" | `uv run main.py portfolio --json` |
| "삼성전자 어때?" | `uv run main.py --tickers 005930 --no-llm` |
| "주도주 뭐 있어?" | `uv run main.py --screen` |
| "삼성전자 20만원에 10주 샀어" | `uv run main.py add 005930 200000 10` |
| "SK하이닉스 팔았어" | `uv run main.py remove 000660` |
| "현금 천만원 있어" | `uv run main.py cash 10000000` |

## 핵심 투자 원칙 (사용자에게 전달 시)

- 오르는 주식은 팔지 마라 — 고점에서 10% 빠질 때 매도
- 손절매는 반드시 설정 — 매수 시 10% 손절 기본
- 주도주를 쫓아가라 — 발명하지 말고 시장이 선택한 종목
- 3~5종목 집중 — 종목 수 늘리면 관리 불가
- 10시 전 매수 금지 — 변동성 큰 시간대 회피
- 현금은 기회의 실탄 — 변동성 장에서 현금 비중 유지

## 응답 포맷

trading-oracle의 출력을 사용자에게 전달할 때:
1. 핵심 결론부터 (매수/매도/관망)
2. 가격과 수량은 구체적으로
3. 손절가 항상 명시
4. 이광수 철학 기반 한 줄 조언 포함
