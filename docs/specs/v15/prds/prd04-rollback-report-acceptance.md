# PRD: v15 PRD 04 Rollback, Report, Acceptance
> **상태**: 📝 초안
> 상위 SPEC: [v15 SPEC](../SPEC.md)

## 의존성

- v15 PRD 01~03

## 목표

Router 운영·성과 rollback, version 폐기·복구, 운영 보고, 최종 paper boundary와 v15 version acceptance를 구현한다.

## 구현 표면

| 경로 | 책임 |
| --- | --- |
| `src/v15/rollback.py` | Operational·performance rollback |
| `src/v15/reporting.py` | Market·arm·session report |
| `src/v15/paper_boundary.py` | Live destination hard guard |
| `src/v15/acceptance.py` | Multi-session operation scenarios |
| `src/v15/cli.py` | PRD별·version acceptance |

## Rollback 계약

- Critical ledger·replay·risk 오류는 즉시 ORB primary 복귀
- Manifest 불변 외부 운영 복구만 같은 router version 재개 가능
- 최근 20 common days 안에서 각 arm 100거래 이상이고 paired CI upper<=0이면 성과 rollback
- 성과 rollback version은 retired이며 재승격 금지

## 운영 보고

Manifest, data health, candidates, NO_TRADE, fills, exposures, P&L 비용, LLM fallback, kill·recovery, paired performance를 market·arm·session별로 출력한다.

## Version CLI

```bash
uv run python -m src.v15.cli prd04-acceptance
uv run python -m src.v15.cli acceptance
```

## 필수 시나리오

- 정상 승격과 sample 보류
- Router 승리와 primary 전환
- Operational rollback·same-version recovery
- Performance rollback·retired rejection
- Arm·market·global kill과 next-session reset
- `hidden_quant_fallback`, `performance_repromote`, `live_destination`
- Credential, raw account ID, `data/portfolio.json` mutation 차단

## 완료 조건

- `uv run python -m src.v15.cli acceptance` exit 0
- v10~v14 canonical fixtures와 v15 local fixtures만 사용
- 최종 runnable paper system이 live side effect 없이 multi-session replay를 통과
