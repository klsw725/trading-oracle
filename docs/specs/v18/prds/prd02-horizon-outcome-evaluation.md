# PRD: v18 PRD 02 Horizon Outcome Evaluation
> **상태**: ✅ 구현 완료
> 상위 SPEC: [v18 SPEC](../SPEC.md)

## 의존성

- [PRD 01](prd01-prediction-identity-and-quarantine.md)의 immutable `PredictionRecord`
- [v16 SPEC](../../v16/SPEC.md)의 versioned official calendar와 adjusted-price manifest
- v18 local KR·US session·price fixtures

## 목표

Prediction 다음 정확한 N번째 official market session을 target으로 정하고 explicit `as_of`에서 성숙한 adjusted-price outcome을 한 번만 확정한다.

## 구현 표면

| 경로 | 책임 |
| --- | --- |
| `src/v18/sessions.py` | Market별 exact Nth open-session selection과 maturity |
| `src/v18/prices.py` | Adjusted close identity·uniqueness 검증 |
| `src/v18/evaluator.py` | Integer return과 directional verdict 계산 |
| `src/v18/outcomes.py` | Immutable evaluation event·row transaction |
| `src/v18/policies.py` | Evaluator policy와 neutral band registry |

## Horizon 계약

N=1은 prediction session 뒤 첫 `OPEN` 또는 `EARLY_CLOSE` session이다. `CLOSED`, weekend와 market holiday는 세지 않는다. Prediction session 자체는 cutoff 시각과 무관하게 세지 않는다. KR과 US는 각 prediction에 고정된 calendar version만 사용한다.

Target 선택은 calendar `(market, session_date)` explicit order를 사용한다. Target까지 calendar coverage가 없거나 duplicate/conflict가 있으면 maturity를 추정하지 않는다.

## Maturity와 `as_of`

Target session official close를 UTC로 변환한 instant 이상일 때만 mature다. `as_of`는 caller가 제공한 canonical UTC RFC 3339이고 wall clock fallback은 없다.

| Condition | Verdict | Persistence |
| --- | --- | --- |
| `as_of < target_close` | `OUTCOME_IMMATURE` | write 0건 |
| target calendar 누락·상충 | `TARGET_SESSION_UNRESOLVED` | write 0건 |
| target close 이상, price valid | `MATURE` 후 `EVALUATED` | event·row atomic commit |
| 이미 같은 outcome 확정 | stored outcome | write 0건 |
| 이미 다른 outcome 확정 | `EVALUATION_IMMUTABLE` | write 0건 |

## Adjusted Price 계약

`v18.adjusted-close.1` row는 market, currency, symbol, session, positive minor-unit adjusted close, adjustment version, dataset hash를 가진다. Exact target에 row가 하나여야 한다. Raw close, nearest date, prior close, fill price 또는 다른 adjustment version fallback은 없다.

Reference와 target price의 currency와 adjustment version은 prediction lineage와 같아야 한다. Split로 raw close가 달라지는 fixture에서도 adjusted series만 결과를 결정한다.

## Outcome 계약

`return_bps = round_half_away_from_zero((target-reference) * 10000 / reference)`를 integer rational arithmetic으로 계산한다. Schema `v18.outcome.1`은 prediction ID, target session, target adjusted price, return bps, `CORRECT|INCORRECT|NEUTRAL`, maturity `as_of`, evaluator policy, calendar/price evidence hash를 저장한다.

BUY/SELL은 neutral band 양쪽 방향으로, HOLD는 absolute return이 band 이내인지로 판정한다. Neutral band는 evaluator policy registry의 canonical integer basis points다.

## Failure 계약

| Code | 조건 |
| --- | --- |
| `OUTCOME_IMMATURE` | target official close 전 `as_of` |
| `TARGET_SESSION_UNRESOLVED` | calendar coverage·order·uniqueness 실패 |
| `CALENDAR_IDENTITY_MISMATCH` | prediction과 calendar version/hash 불일치 |
| `TARGET_PRICE_MISSING` | exact target adjusted close 없음 |
| `TARGET_PRICE_AMBIGUOUS` | exact target row 중복 |
| `PRICE_ADJUSTMENT_MISMATCH` | raw/unknown/different adjustment version |
| `NAMESPACE_MISMATCH` | market·currency·symbol 불일치 |
| `EVALUATION_IMMUTABLE` | terminal outcome을 다른 input으로 재평가 |

## CLI

```bash
uv run python -m src.v18.cli evaluate --prediction-id sha256:... --as-of 2026-01-20T21:00:00Z --database data/paper/v17/paper.sqlite3
uv run python -m src.v18.cli prd02-acceptance
```

## Acceptance와 Mutation

| Probe | Mutation | Required result |
| --- | --- | --- |
| `nth_session` | weekend·holiday가 낀 KR/US horizon | exact Nth open session |
| `early_close` | US early close 포함/제외 비교 | 한 official session으로 포함 |
| `immature_one_second` | close 1초 전 `as_of` | immature, write 0건 |
| `adjusted_split` | raw와 adjusted series 분기 | adjusted result만 채택 |
| `missing_or_duplicate_price` | target row 삭제·복제 | stable failure, write 0건 |
| `calendar_drift` | version/hash 교체 | identity mismatch |
| `reevaluation_conflict` | price 또는 evaluator policy 변경 | immutable, state hash 불변 |

## 완료 조건

- Exact Nth session과 maturity가 market calendar로 재현된다.
- Outcome은 adjusted price와 explicit `as_of`만으로 deterministic하다.
- Immature·missing·ambiguous·mismatched input이 terminal row를 만들지 않는다.
- 한 prediction의 outcome은 한 번만 확정된다.

## 비목표

- Intraday horizon, nearest-price interpolation
- Fill price, slippage, fee, paper P&L 또는 account NAV
- Calendar·corporate-action data 생산
- Cohort selection과 policy candidate
