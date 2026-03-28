# 분할 매수/매도 + 수량 기반 추천 — 스펙 & PRD

## 문제 정의

현재 Trading Oracle은:
1. **매도가 전량만 가능** — `remove_position()`이 해당 종목 전체를 제거함. "3주 중 1주만 매도" 불가.
2. **LLM이 수량을 제시하지 않음** — 시스템 프롬프트가 "가격"만 요구. "삼성전자 5주 매도" 같은 구체적 수량 추천 없음.
3. **매도 시 현금 반영 안 됨** — `cmd_remove()`가 매도 대금을 `cash`에 더하지 않음. `cmd_add()`도 매수 대금을 `cash`에서 차감하지 않음.

## 변경 범위

### 1. `src/portfolio/tracker.py` — `remove_position()` 분할 매도 지원

**현재**: `remove_position(portfolio, ticker, sell_price, reason)` → 전량 제거
**변경**: `remove_position(portfolio, ticker, sell_price, reason, shares=None)` → shares가 None이면 전량, 숫자면 해당 수량만 매도

- 분할 매도 시: 보유 수량 감소, 평단가 유지, history에 매도 수량 기록
- 전량 매도 시: 기존 동작 유지 (positions에서 제거)
- shares > 보유 수량: 에러 (매도 수량 초과)
- shares == 보유 수량: 전량 매도와 동일 처리

### 2. `main.py` — `cmd_remove()` CLI 인터페이스

**현재**: `uv run main.py remove 005930 --price 60000`
**변경**: `uv run main.py remove 005930 --price 60000 --shares 5`

- `--shares` 옵션 추가 (기본값: 전량)
- 출력에 매도 수량 표시

### 3. `main.py` — `cmd_add()`, `cmd_remove()` 현금 연동

**현재**: 매수/매도 시 cash 변동 없음
**변경**:
- `cmd_add()`: 매수 대금(`price × shares`)을 cash에서 차감. cash 부족 시 경고 (차단하지 않음 — 실제 매수는 이미 완료된 기록이므로)
- `cmd_remove()`: 매도 대금(`sell_price × shares`)을 cash에 가산

### 4. `src/agent/prompts.py` — LLM 수량 추천 지시

시스템 프롬프트의 "4단계: 종합 전략" 섹션에 수량 기반 추천 지시 추가:
- 보유 종목: "N주 중 M주 매도" 또는 "전량 매도" 형태
- 신규 매수: "N주 분할 매수 (1차 M주, 2차 K주)" 형태
- 현금 잔고 대비 투자 비중 계산하여 제시

### 5. 변경하지 않는 것

- `add_position()` — 이미 분할 매수(동일 종목 평단가 합산) 지원. 변경 불필요.
- `update_positions()` — 현재가 업데이트 로직은 수량과 무관. 변경 불필요.
- `get_portfolio_summary()` — 이미 shares 기반 계산. 변경 불필요.
- 기존 JSON 출력 포맷 — 하위 호환 유지

## 성공 기준

1. `uv run main.py remove 005930 --price 60000 --shares 5` → 5주만 매도, 나머지 보유
2. `uv run main.py remove 005930 --price 60000` → 전량 매도 (기존 동작 유지)
3. 매수 시 cash 차감, 매도 시 cash 가산
4. LLM 응답에 구체적 수량이 포함됨 (프롬프트 지시)
5. `--shares`가 보유 수량 초과 시 에러 메시지
