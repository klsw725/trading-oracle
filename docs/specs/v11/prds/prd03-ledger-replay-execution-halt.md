# PRD: v11 PRD 03 Ledger, Replay, Execution Halt
> **상태**: 📝 초안
> 상위 SPEC: [v11 SPEC](../SPEC.md)

## 의존성

- v11 PRD 01 risk·reservation
- v11 PRD 02 order·fill·cost·exit

## 목표

모든 paper execution을 append-only hash chain으로 저장하고, 중복 전달·재시작·reconciliation 실패를 결정론적으로 복구하거나 `execution_halt`로 종료한다.

## 구현 표면

| 경로 | 책임 |
| --- | --- |
| `src/v11/ledger.py` | Event append, hash chain, semantic order |
| `src/v11/identity.py` | Candidate·decision·strategy가 결합된 intent ID |
| `src/v11/replay.py` | Checkpoint 이후 state reconstruction |
| `src/v11/reconciliation.py` | Cash·position·intent·fill·cost 대조 |
| `src/v11/halt.py` | Halt request orchestration, pending cancel, new-intent block, reset |

## Event 흐름

```text
signal_observed -> order_intended -> risk_checked -> order_accepted
-> fill_partial|fill_complete|order_cancelled -> position_updated
-> cost_accrued -> reconciled -> session_closed
```

각 event는 index, occurred_at, recorded_at, payload hash, previous hash, event hash, manifest hash를 가진다. 동일 intent는 no-op이며 다른 strategy·candidate가 같은 ID를 공유할 수 없다.

`daily_loss_halt_request` 또는 `execution_halt_request`를 받으면 PRD 03이 pending intent를 취소하고 신규 intent를 차단한다. Daily-loss request는 PRD 02 forced-liquidation API를 호출해 다음 1분 전량청산을 기록하고 당일 halted 상태를 유지한 뒤 다음 공식 장에 reset한다. Integrity halt는 수동 reconciliation 전 reset하지 않는다.

## CLI

```bash
uv run python -m src.v11.cli prd03-build --input <fixture>
uv run python -m src.v11.cli prd03-replay --artifact <ledger>
uv run python -m src.v11.cli prd03-acceptance
```

## Acceptance와 Mutation

- Normal, partial-fill, cancellation event chain
- Duplicate intent no-op
- Strategy collision 차단
- Hash mutation, event gap, semantic duplicate 차단
- Restart checkpoint replay와 source snapshot 일치
- Numpy scalar canonical conversion
- Reconciliation mismatch의 pending cancel·execution halt

## 완료 조건

- Byte-identical replay state를 만든다.
- 불일치가 portfolio overwrite나 reorder로 복구되지 않는다.
- Halt 이후 risk-reducing forced exit 외 신규 intent는 생성되지 않는다.
