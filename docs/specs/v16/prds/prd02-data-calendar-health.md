# PRD: v16 PRD 02 Data And Calendar Health
> **상태**: 📋 구현 예정
> 상위 SPEC: [v16 SPEC](../SPEC.md)

## 의존성

- [PRD 01](prd01-config-path-and-identity.md)의 `RuntimeConfig`와 canonical hash
- v16 local calendar·dataset fixtures

## 목표

명시적 replay cutoff에서 KR·US calendar와 dataset의 identity, hash, coverage, freshness를 독립 판정해 `InputHealthReport`를 만든다.

## 구현 표면

| 경로 | 책임 |
| --- | --- |
| `src/v16/calendar.py` | Versioned KR·US session parse와 timezone 검증 |
| `src/v16/input_manifest.py` | Dataset descriptor와 content hash binding |
| `src/v16/data_health.py` | Ordered health gate와 verdict |
| `src/v16/health_report.py` | Market별 canonical evidence report |

## 입력 계약

Calendar와 dataset은 fixture manifest가 열거한 파일만 읽는다. Directory scan 결과나 mtime을 입력으로 사용하지 않는다. 모든 상대 경로는 manifest 파일의 root가 아니라 v16 fixture root 기준이며 그 밖으로 나갈 수 없다.

Dataset descriptor 필수 필드는 kind, market, currency, session, source, source version, observed_at, expected interval, row count, min/max timestamp, SHA-256다. Manifest 자체도 schema version과 hash를 가진다.

## Calendar Health

- `KR/KRW/Asia/Seoul`, `US/USD/America/New_York` 조합만 허용한다.
- `OPEN`, `CLOSED`, `EARLY_CLOSE`만 허용한다.
- Open session은 유효한 local time과 UTC 변환, open < close를 요구한다.
- Market·date 중복, DST ambiguity 미해결, version/hash mismatch는 해당 market 실패다.
- `ALL`은 두 market을 모두 요구하며 부분 성공을 전체 성공으로 표시하지 않는다.

## Data Health 순서

1. Descriptor와 manifest schema
2. Market·currency·session·symbol identity
3. File bytes와 declared hash
4. Timestamp ascending과 duplicate 없음
5. Calendar 기반 expected coverage와 row count
6. `as_of - observed_at` freshness threshold

앞 gate 실패 뒤 뒤 gate가 성공으로 덮지 않는다. 모든 판정은 `as_of` 인자를 사용하고 현재 시각을 읽지 않는다.

## Verdict와 사용 규칙

`HEALTHY`만 소비 가능하다. `STALE`, `INCOMPLETE`, `HASH_MISMATCH`, `UNKNOWN`, `INVALID`는 모두 fail-closed다. Source priority나 자동 fallback은 이 PRD 범위가 아니다.

Health report는 market·dataset별 verdict, failure code, expected/actual summary, evidence hash를 가진다. Raw market rows와 host path는 포함하지 않는다.

## CLI

```bash
uv run python -m src.v16.cli data-health --manifest docs/specs/v16/fixtures/input-manifest.json --as-of 2026-01-05T21:00:00Z --market ALL
uv run python -m src.v16.cli prd02-acceptance
```

Healthy면 exit 0, 하나라도 요청 범위에서 unhealthy면 canonical failure report와 exit 2다.

## Acceptance와 Mutation

- KR·US healthy fixture가 독립 `HEALTHY`
- Duplicate session, invalid early close, calendar hash drift 차단
- `stale_at_replay_cutoff`, missing interval, out-of-order·duplicate row 차단
- `data_hash_forgery`, `market_currency_swap`, unknown source·kind 차단
- 같은 fixture와 `as_of`를 반복하면 byte-identical report
- KR failure가 US detail을 삭제하지 않지만 `ALL` overall은 실패

## 완료 조건

- Calendar와 data health를 manifest evidence로 재현할 수 있다.
- Unknown·stale·hash mismatch가 warning 경로로 소비되지 않는다.
- Network, vendor SDK, v17 state를 사용하지 않는다.

## 비목표

- 데이터 다운로드, 보정, fallback vendor 선택
- 새 vendor·calendar 생성
- account 또는 position reconciliation
