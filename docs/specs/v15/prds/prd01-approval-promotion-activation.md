# PRD: v15 PRD 01 Approval, Promotion, Activation
> **상태**: ✅ 구현 완료
> 상위 SPEC: [v15 SPEC](../SPEC.md)

## 의존성

- 구현 완료된 v10~v14 artifacts와 verdicts

## 목표

정상 자동 승인, data·policy 수동 승인, ORB paper 승격, 14개 shadow activation, router challenger 상태 전이를 구현한다.

## 구현 표면

| 경로 | 책임 |
| --- | --- |
| `src/v15/approvals.py` | Exception approval과 manifest binding |
| `src/v15/promotion.py` | ORB·strategy·router gate |
| `src/v15/activation.py` | Effective session과 arm activation |
| `src/v15/states.py` | Append-only lifecycle transition |

## 승인 계약

- 변경 없는 정상 run은 자동 승인
- Hash-verified source fallback·data exception evidence가 있으면 policy identity가 같아도 수동 승인
- Source fallback, missing, corporate action, borrow, hash·replay 이상은 수동
- Strategy, risk, cost, router, prompt, model, schema 변경은 수동
- 승인에는 exact manifest hash, effective session, reason, reviewer 포함
- 승인은 새 v14 gate를 대체하지 않음

## Promotion 흐름

```text
foundation_ready -> orb_paper
-> 별도 v11 qualification ledger의 20 sessions + 30 trades + 0 critical incidents
-> 14 strategies shadow
-> router gate passed -> router_challenger
```

## CLI

```bash
uv run python -m src.v15.cli prd01-acceptance
```

## Acceptance와 Mutation

- ORB holdout pass 자동 승격
- KR·US 독립 승격
- Data·policy 변경 자동 승인 차단
- `approval_hash_forgery_e2e`, `policy_data_auto_approval_e2e`, `orb_qualification_early_promotion_e2e`
- 20세션·30거래·0 incident 경계

## 완료 조건

- 모든 상태 전이가 exact manifest와 evidence refs를 가진다.
- 선행 gate를 건너뛰는 transition이 없다.
