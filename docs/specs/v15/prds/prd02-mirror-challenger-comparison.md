# PRD: v15 PRD 02 Mirror Challenger Comparison
> **상태**: ✅ 구현 완료
> 상위 SPEC: [v15 SPEC](../SPEC.md)

## 의존성

- v11 account·execution·ledger
- v12 ORB strategy
- v13 mixed router
- v14 bootstrap·verdict artifact

## 목표

Comparison epoch에서 ORB baseline과 router challenger의 독립 mirror account를 만들고 60일·300거래 paired 승자 판정을 구현한다.

## 구현 표면

| 경로 | 책임 |
| --- | --- |
| `src/v15/mirrors.py` | 동일 initial NAV의 독립 arm |
| `src/v15/challenger.py` | Router challenger lifecycle |
| `src/v15/paired.py` | Common-day series와 sample gate |
| `src/v15/winner.py` | CI·2× cost·integrity winner decision |

## 핵심 계약

- Challenger 시작일에 두 새 ledger를 동시에 생성한다.
- Account, slot, position을 공유하지 않는다.
- 한쪽 또는 양쪽 no-trade·loss-kill day도 common-day series에 남긴다.
- 각 arm 60일·300거래 후 5일 block·10,000 resample paired CI를 계산한다.
- Router 승리는 CI lower>0, router 2× cost return>0, critical integrity error 0을 모두 요구한다.
- 승격 후 ORB mirror도 계속 virtual fills·cost·NAV를 생성한다.

## CLI

```bash
uv run python -m src.v15.cli prd02-acceptance
```

## Acceptance와 Mutation

- Same epoch·NAV·data·cost initialization
- `shared_account_namespace_e2e`, `paired_series_missing_official_session_e2e`, `winner_sample_below_300_replayed_ledger_e2e`
- Router win·inconclusive·loss
- `mirror_day_evidence_drift_reaches_report_e2e`, `winner_integrity_forgery_e2e`

## 완료 조건

- Paired series와 winner artifact를 replay할 수 있다.
- Router가 이기기 전 primary를 변경하지 않는다.
