# PRD: v10 PRD 03 Universe, Corporate Action, Eligibility
> **상태**: 📝 초안
> 상위 SPEC: [v10 SPEC](../SPEC.md)

## 의존성

- v10 PRD 01의 calendar·source·minute artifact
- v10 PRD 02의 complete 5분봉과 revision head

## 목표

1. 시장별 최근 20거래일 평균 거래대금 상위 100개를 T일 종가 뒤 생성한다.
2. T+1 세션 동안 membership을 고정하고 장중 대체 승격을 금지한다.
3. Instrument exclusions와 장중 eligibility를 분리한다.
4. Raw execution price와 point-in-time adjusted indicator price를 분리한다.

## 구현 표면

| 경로 | 책임 |
| --- | --- |
| `src/v10/universe.py` | 평균 거래대금, rank, Top 100, tie-break |
| `src/v10/instruments.py` | ETF·ETN·우선주·ADR·SPAC·unit·warrant 분류 |
| `src/v10/eligibility.py` | Halt·누락·규제 상태의 장중 차단 |
| `src/v10/corporate_actions.py` | 분할·병합·배당·권리락 artifact |
| `src/v10/price_layers.py` | Raw와 adjusted price 계층 |
| `docs/specs/v10/fixtures/prd03-*.json` | Universe와 action fixtures |

## 산출물

- `universe_snapshot`
- `eligibility_event`
- `corporate_action_snapshot`
- `price_adjustment_snapshot`

## 규칙

- Ranking은 T일까지의 데이터만 사용하며 동률은 canonical symbol 오름차순이다.
- 상장 20세션 미만, 분류 불명, 계산 누락 종목은 제외한다.
- T+1 부적격 종목은 차단하되 101위 종목을 올리지 않는다.
- Raw price는 fill·audit, adjusted price는 과거 feature에만 사용한다.
- 검증되지 않은 corporate action은 해당 symbol을 fail closed 한다.

## CLI

```bash
uv run python -m src.v10.cli prd03-build --input <fixture>
uv run python -m src.v10.cli prd03-verify --artifact <artifact>
uv run python -m src.v10.cli prd03-acceptance
```

## Acceptance와 Mutation

| Probe | Required result |
| --- | --- |
| `future_universe` | `V10_UNIVERSE_LOOKAHEAD` |
| `replacement_member` | `V10_UNIVERSE_NOT_FROZEN` |
| `excluded_instrument` | Ranking 전 제외 |
| `insufficient_history` | Eligibility false |
| `adjusted_execution` | `V10_PRICE_LAYER_MISMATCH` |
| `corporate_action_unknown` | Symbol blocked |

## 완료 조건

- KR·US snapshot을 독립 생성한다.
- Top 100, exclusion, freeze, eligibility, price layers를 replay할 수 있다.
- Membership과 장중 eligibility의 owner가 섞이지 않는다.
