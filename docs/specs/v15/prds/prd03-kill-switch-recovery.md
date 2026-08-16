# PRD: v15 PRD 03 Kill Switch And Recovery
> **상태**: ✅ 구현 완료
> 상위 SPEC: [v15 SPEC](../SPEC.md)

## 의존성

- v10 data incidents
- v11 daily-loss halt·ledger·reconciliation
- v13 fallback·circuit events

## 목표

Market·arm 2% loss kill과 symbol·arm·market·global 운영 kill scope, cancel·flatten·reset·manual recovery를 구현한다.

## 구현 표면

| 경로 | 책임 |
| --- | --- |
| `src/v15/kill_switch.py` | Trigger classification과 scope |
| `src/v15/risk_monitor.py` | 1분 MTM·incident monitoring |
| `src/v15/liquidation.py` | Pending cancel과 next-1m flatten |
| `src/v15/recovery.py` | Automatic loss reset과 manual operation reset |
| `src/v15/incidents.py` | Append-only trigger·recovery evidence |

## Scope

| Trigger | Scope |
| --- | --- |
| Isolated symbol data·action·borrow | 관련 market arm 전체에서 target symbol만 취소·청산, NORMAL 포지션 보존 |
| Arm ledger·reservation mismatch | Market·arm kill |
| Shared market calendar·source·regulation | All market arms kill |
| Manifest·code·policy identity failure | Global paper kill |

## 동작

Pending intent 취소, 신규 차단, 신뢰 가능한 다음 1분 전량청산, 당일 재진입 금지를 수행한다. Loss kill만 다음 장 해당 arm reset이며 운영 kill은 root cause·replay·수동 승인 뒤 재개한다.

## CLI

```bash
uv run python -m src.v15.cli prd03-acceptance
```

## Acceptance와 Mutation

- 비용 포함 2% loss와 arm 격리
- Symbol defect가 market kill로 확대되지 않음
- 범위 불명 시 한 단계 fail-closed 확대
- `daily_economics_and_loss_mark_lineage_e2e`, `kill_and_recovery_chain_truncation_e2e`
- `operation_recovery_approval_forgery_e2e`, `isolated_symbol_escalates_market_e2e`
- LLM quant fallback을 kill로 오분류하지 않음

## 완료 조건

- Trigger부터 reset까지 append-only replay 가능
- 운영 incident가 자동으로 다음 장 재개되지 않음
