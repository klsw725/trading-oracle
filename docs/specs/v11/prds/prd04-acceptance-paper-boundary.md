# PRD: v11 PRD 04 Acceptance And Paper Boundary
> **상태**: 📝 초안
> 상위 SPEC: [v11 SPEC](../SPEC.md)

## 의존성

- 구현 완료된 v10 canonical fixtures
- v11 PRD 01~03

## 목표

v11 전체 실행 경로를 로컬 `execution_decision` fixtures로 검증하고 real-order side effect가 없음을 증명한다.

## 구현 표면

| 경로 | 책임 |
| --- | --- |
| `src/v11/acceptance.py` | PRD orchestration, mutation assertions |
| `src/v11/cli.py` | PRD별 command와 version acceptance |
| `docs/specs/v11/fixtures/` | KR·US, immediate·delayed, short, halt fixtures |
| `src/v11/paper_boundary.py` | Forbidden destination·field·mutation guard |

## Version CLI

```bash
uv run python -m src.v11.cli acceptance
```

## 필수 End-to-end 시나리오

1. KR·US 계좌, sizing, reservation, risk pass
2. Immediate·20초 delayed decision의 최초 1분 체결
3. Liquidity partial fill, cost, short, recall
4. Close-20 block과 close-5 exit
5. 비용 포함 2% daily loss halt와 다음 장 reset
6. Duplicate·restart·replay·reconciliation halt
7. Live destination·credential·raw account ID·portfolio mutation 차단

## Report 계약

Canonical JSON report는 PRD별 case count, mutation code, artifact hash, side-effect count, dependency manifest를 포함한다. v12 이후 module import count는 0이어야 한다.

Normative probe inventory는 `fractional_quantity`, `future_volume`, `overfill`, `carry_remainder`, `duplicate_intent`, `strategy_collision`, `unreserved_batch`, `ledger_break`, `missing_borrow`, `late_entry`, `overnight`, `correlation_unknown`을 정확한 ID로 포함한다.

## 완료 조건

- `uv run python -m src.v11.cli acceptance` exit 0
- SPEC의 모든 mutation이 정확한 owner PRD 결과로 검증됨
- Broker submit 0, live artifact 0, `data/portfolio.json` write 0
- v10과 v11 로컬 fixtures만으로 반복 실행 결과가 동일함
