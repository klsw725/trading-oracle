# PRD: v11 PRD 02 Execution, Cost, Short
> **상태**: 📝 초안
> 상위 SPEC: [v11 SPEC](../SPEC.md)

## 의존성

- v10 complete 1분·5분봉, session, eligibility
- v11 PRD 01 account·risk·reservation

## 목표

로컬 `execution_decision`을 첫 거래 가능한 1분 경계의 부분체결·비용·short 규제·장마감 청산으로 변환한다.

## 구현 표면

| 경로 | 책임 |
| --- | --- |
| `src/v11/decisions.py` | Immediate·delayed execution decision schema |
| `src/v11/liquidity.py` | 과거 20개 1분 중앙 거래대금 5% sizing cap |
| `src/v11/fills.py` | 목표 1분 실제 volume 5% partial fill |
| `src/v11/costs.py` | Market bucket, fee, tax, 2× variable-cost stress |
| `src/v11/shorts.py` | Locate·ETB·borrow·SSR·KR 규제·recall |
| `src/v11/session_exit.py` | Close-20 entry block, close-5 exit와 halt liquidation API |

## 실행 계약

1. V10 watermark 뒤 `decision_ready_at` 이후 최초 1분 경계만 사용한다.
2. 목표 경계를 놓치면 stale cancel하고 순연하지 않는다.
3. 실제 목표 분 volume의 5%까지만 fill하고 잔량은 분 종료 때 취소한다.
4. Variable spread·slippage·impact·borrow만 stress에서 2배로 한다.
5. Short snapshot 누락은 fail closed이며 recall은 다음 1분 강제청산한다.
6. PRD 01 `daily_loss_halt_request`와 PRD 03 halt orchestrator가 요청한 forced-liquidation intent를 다음 신뢰 가능한 1분 경계에서 체결한다.

## CLI

```bash
uv run python -m src.v11.cli prd02-build --input <fixture>
uv run python -m src.v11.cli prd02-verify --artifact <artifact>
uv run python -m src.v11.cli prd02-acceptance
```

## Acceptance와 Mutation

| Probe | Required result |
| --- | --- |
| `future_volume` | Lookahead failure |
| `overfill` | Participation failure |
| `carry_remainder` | Stale execution failure |
| `missed_boundary` | Order cancelled |
| `missing_borrow` | Short blocked |
| `late_entry` | Close risk blocked |
| `fixed_cost_doubled` | Cost contract failure |

## 완료 조건

- 전략·LLM 없이 immediate·20초 delayed fixture를 모두 체결한다.
- Long·Short fill과 비용을 canonical artifact로 재현한다.
- Overnight position이 공식 session close 전에 모두 종료된다.
