# PRD: v11 PRD 01 Account, Risk, Reservation
> **상태**: 📝 초안
> 상위 SPEC: [v11 SPEC](../SPEC.md)

## 의존성

- 구현 완료된 v10 calendar, minute, universe, eligibility artifact

## 목표

KRW 1억·USD 10만 독립 virtual account에 2% 정수 sizing, cash·short collateral reservation, position·gross·net·sector·correlation gate, 2% daily-loss halt를 구현한다.

## 구현 표면

| 경로 | 책임 |
| --- | --- |
| `src/v11/models.py` | Account, position, risk, reservation, halt model |
| `src/v11/accounts.py` | Currency별 NAV·cash·position state |
| `src/v11/sizing.py` | 직전 complete 1분 종가 기반 2% 정수 수량 |
| `src/v11/risk.py` | Slot, gross/net, sector, correlation gate |
| `src/v11/reservations.py` | Cash·collateral·exposure 순차 예약 |
| `src/v11/daily_loss.py` | 비용 포함 1분 MTM, risk block, halt request |

## Risk 계약

- 시장별 최대 10종목, gross 20%, net ±10%, sector gross 6%
- 기존 보유와 20개 유한 paired return의 `|rho| > 0.7`이면 차단
- Missing·zero variance·non-finite correlation은 fail closed
- Margin 없음, short proceeds 재사용 금지
- 같은 cutoff decision은 deterministic score desc, symbol asc, decision ID asc로 예약
- 정상 가격 drift는 신규 진입 차단, accounting mismatch는 `execution_halt_request`

## Daily Loss

전일 NAV 대비 2% 손실에 실현·미실현·commission·tax·spread·slippage·borrow를 포함한다. PRD 01은 즉시 신규 risk decision을 차단하고 immutable `daily_loss_halt_request`를 생성한다. Pending intent 취소, 다음 1분 전량청산, 세션 halt·reset 실행은 이 PRD의 책임이 아니며 PRD 02·03이 request를 소비한다.

## CLI

```bash
uv run python -m src.v11.cli prd01-build --input <fixture>
uv run python -m src.v11.cli prd01-verify --artifact <artifact>
uv run python -m src.v11.cli prd01-acceptance
```

## Acceptance와 Mutation

- KRW·USD 계좌 격리와 FX 비혼합
- Fractional quantity 거부
- Cash·collateral 중복 reservation 차단
- Position 11번째, gross/net/sector 초과 차단
- Correlation unknown과 high correlation 차단
- 2% loss의 risk block과 `daily_loss_halt_request`
- 비용 누락 손실 계산과 halt 우회 차단

## 완료 조건

- 계좌 생성부터 risk decision·reservation·daily-loss trigger까지 로컬 fixture로 실행된다.
- Risk-increasing intent가 blocker를 우회하지 않는다.
- 계좌 artifact는 live account나 `data/portfolio.json`을 읽거나 쓰지 않는다.
