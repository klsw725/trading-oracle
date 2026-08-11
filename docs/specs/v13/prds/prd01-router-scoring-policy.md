# PRD: v13 PRD 01 Router Scoring And Policy
> **상태**: 📝 초안
> 상위 SPEC: [v13 SPEC](../SPEC.md)

## 의존성

- v11 causal sizing reference·reservation
- v12 execution-feasible candidate와 deterministic score

## 목표

시장·cutoff 전체 후보 percentile, deterministic 80%·LLM 20% 합성, 종목별 선택, NO_TRADE, slot total order를 결정론적으로 구현한다.

## 구현 표면

| 경로 | 책임 |
| --- | --- |
| `src/v13/models.py` | Router policy, score, selection typed model |
| `src/v13/scoring.py` | Midrank percentile와 80:20 합성 |
| `src/v13/policy.py` | 6개 NO_TRADE 조합과 policy hash |
| `src/v13/selection.py` | Per-symbol winner와 slot total order |

## Scoring 계약

- `n>1`: `(midrank-1)/(n-1)`, singleton 1.0, 전체 동률 0.5
- Hard veto 후보 제거 후 두 component rank 재계산
- Quant-only는 deterministic percentile 자체 사용
- Confidence는 기록만 하고 weight에 사용하지 않음
- Expected turnover는 signed quantity change notional / previous NAV
- Total order: composite desc, deterministic desc, turnover asc, symbol asc, strategy ID asc

## Router Policy

허용 최소점수는 0.70·0.80·0.90, 최소격차는 0.05·0.10이다. Run 전에 한 조합을 hash로 동결하며 기본은 0.80·0.05다.

## CLI

```bash
uv run python -m src.v13.cli prd01-build --input <fixture>
uv run python -m src.v13.cli prd01-acceptance
```

## Acceptance와 Mutation

- Singleton, ties, veto removal, quant-only
- 6개 policy 조합 pass·NO_TRADE
- `confidence_weight`, `rank_tie_drift`, `single_candidate_gap`
- `slot_tie_nondeterministic`
- 반복 scoring·allocation determinism

## 완료 조건

- LLM response fixture를 score component로 받아 주문 없이 selection artifact를 생성한다.
- 모든 tie와 reservation order가 total order로 닫힌다.
