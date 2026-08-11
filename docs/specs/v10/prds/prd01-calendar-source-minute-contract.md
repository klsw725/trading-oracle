# PRD: v10 PRD 01 Calendar, Source, Minute Contract
> **상태**: 📝 초안
> 상위 SPEC: [v10 SPEC](../SPEC.md)

## 문제

5분 연구 입력을 만들기 전에 KR·US 공식 세션, primary·secondary source, canonical 1분봉을 같은 provenance 경계로 고정해야 한다. Calendar 또는 source 실패를 fallback 성공으로 숨기면 이후 모든 artifact가 재현 불가능해진다.

## 목표

1. 공식 calendar, timezone, DST, 휴장·조기폐장·경매·중단·재개를 versioned snapshot으로 만든다.
2. Toss primary와 capability 검증 secondary를 source observation으로 기록한다.
3. 1분 OHLCV를 canonical schema로 정규화하고 malformed 입력을 fail closed 한다.
4. Source·calendar·timestamp 불일치를 `data_incident`로 남긴다.

## 범위 밖

- 5분봉 집계, universe, 전략, 주문
- 깨진 pykrx fundamental·market-cap·index API 재도입
- credential 또는 raw account identifier 저장

## 구현 표면

| 경로 | 책임 |
| --- | --- |
| `src/v10/models.py` | Calendar, source observation, minute bar, incident typed model |
| `src/v10/calendar.py` | 공식 세션 snapshot과 session-state 판정 |
| `src/v10/sources.py` | Toss primary, verified secondary, fallback provenance |
| `src/v10/minute.py` | Canonical OHLCV·timestamp·revision 정규화 |
| `src/v10/identity.py` | Canonical serialization, artifact ID, content hash |
| `docs/specs/v10/fixtures/prd01-*.json` | Happy, fallback, holiday, malformed fixtures |

## 산출물 계약

- `market_calendar_snapshot`
- `source_observation`
- `minute_bar`
- `data_incident`

모든 산출물은 source identity, observed_at, market timestamp, adapter version, raw hash, canonical hash를 가진다. Secondary 사용은 primary 실패 원인과 함께 기록한다.

## 실행 흐름

```text
official calendar -> source fetch -> source observation
-> minute normalization -> canonical hash -> minute_bar|data_incident
```

## CLI와 검증

```bash
uv run python -m src.v10.cli prd01-build --input <fixture>
uv run python -m src.v10.cli prd01-verify --artifact <artifact>
uv run python -m src.v10.cli prd01-acceptance
```

`build`는 기본적으로 stdout만 사용한다. 파일 출력은 `data/paper/v10/**` 아래에서만 허용한다.

## 필수 Acceptance

- KR·US 정상 세션과 US DST 전환
- 휴장과 조기폐장
- Primary 정상 수신과 secondary fallback provenance
- 중복·역전 timestamp, OHLC 불변식 위반, 음수 volume
- Calendar 밖 regular 표시와 source reconciliation 실패
- 같은 입력의 canonical JSON·hash 결정성

## Mutation

| Probe | Expected result |
| --- | --- |
| `calendar_mismatch` | `V10_CALENDAR_MISMATCH` |
| `hidden_fallback` | `V10_SOURCE_PROVENANCE_MISMATCH` |
| `negative_volume` | `V10_MINUTE_BAR_MALFORMED` |
| `timestamp_reversed` | `V10_MINUTE_BAR_MALFORMED` |
| `secret_field` | `V10_FORBIDDEN_FIELD` |

## 완료 조건

- PRD 01 세 CLI가 exit contract를 지킨다.
- Happy와 모든 mutation이 canonical report에 나타난다.
- 후속 PRD 없이 calendar부터 minute artifact까지 end-to-end 실행된다.
