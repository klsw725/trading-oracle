# PRD: v12 PRD 03 Short, Shadow, Attribution
> **상태**: 📝 초안
> 상위 SPEC: [v12 SPEC](../SPEC.md)

## 의존성

- v11 short eligibility·fill·cost·ledger
- v12 PRD 01 common runtime
- [v12 Strategy Grids](../STRATEGY-GRIDS.md)의 Short 계약

## 목표

Short 5개·20 parameter set을 규제·borrow fail-closed로 구현하고 전체 60개 strategy-parameter arm의 독립 shadow ledger와 거래 귀속을 만든다.

## Short Inventory

| ID | Grid prefix |
| --- | --- |
| `short_orb_15m` | `S15_A`~`S15_D` |
| `short_gap_continuation` | `SGC_A`~`SGC_D` |
| `short_session_low_breakdown` | `SSL_A`~`SSL_D` |
| `short_vwap_rejection` | `SVR_A`~`SVR_D` |
| `short_volume_breakdown` | `SVB_A`~`SVB_D` |

## 구현 표면

| 경로 | 책임 |
| --- | --- |
| `src/v12/strategies/short.py` | 5 Short gate·score |
| `src/v12/shadow.py` | 60개 독립 arm namespace |
| `src/v12/attribution.py` | Candidate→intent→fill→cost→exit lineage |
| `src/v12/trades.py` | Completed trade와 forced-exit report |

## 핵심 규칙

- Borrow·locate·regulation eligibility를 feature보다 먼저 평가한다.
- Arm 사이 cash, slot, position, strategy owner를 공유하지 않는다.
- Partial fill, liquidity cancel, recall, risk kill, close exit를 attribution에 보존한다.
- Strategy ID를 fill 없이 바꾸거나 다른 arm으로 position을 이전하지 않는다.

## CLI

```bash
uv run python -m src.v12.cli prd03-acceptance
uv run python -m src.v12.cli shadow --strategy <id> --parameter-set <id>
```

## Acceptance

- Short 5/5, parameter 20/20
- Missing borrow·locate·regulation에서 candidate 0
- Same-session low requirement
- Recall과 장마감 forced exit
- 60/60 arm namespace isolation
- Ownership transfer와 candidate ID reuse 차단

## 완료 조건

- 모든 Long·Short parameter arm이 독립 ledger를 생성한다.
- Completed trade에서 signal, parameter, fills, 모든 비용, exit reason을 추적한다.
