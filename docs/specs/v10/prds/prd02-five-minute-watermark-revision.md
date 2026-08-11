# PRD: v10 PRD 02 Five-Minute Watermark And Revision
> **상태**: 📝 초안
> 상위 SPEC: [v10 SPEC](../SPEC.md)

## 의존성

- v10 PRD 01의 `minute_bar`, `market_calendar_snapshot`, `data_incident`

## 문제와 목표

원천 1분봉이 늦거나 정정될 수 있으므로 5분봉 완결 시점과 과거 replay head를 명시해야 한다. 이 PRD는 정확히 10초 watermark, 5개 원천 봉, 세션 상태 분리, append-only supersede를 구현한다.

## 구현 표면

| 경로 | 책임 |
| --- | --- |
| `src/v10/aggregation.py` | 5개 1분봉의 OHLCV 집계 |
| `src/v10/watermark.py` | 종료 후 10초 complete 판정 |
| `src/v10/revision.py` | Late revision과 supersede chain |
| `src/v10/replay.py` | Cutoff 당시 revision head 선택 |
| `docs/specs/v10/fixtures/prd02-*.json` | Complete, missing, auction, revision fixtures |

## 핵심 규칙

1. 5분 구간 종료 후 정확히 10초에 평가한다.
2. 같은 symbol·regular session의 연속 1분봉 5개가 있어야 `complete`다.
3. Auction·halt·resume 봉을 regular 집계에 섞지 않는다.
4. Watermark 이후 정정은 원본을 수정하지 않고 `supersede_event`를 append한다.
5. Replay는 당시 존재했던 head만 선택하며 미래 정정으로 과거 결정을 바꾸지 않는다.

## 산출물

- `five_minute_bar`: 원천 5개 ID·hash, watermark, complete status
- `supersede_event`: prior hash, replacement hash, reason, observed_at
- `aggregation_failure`: missing·stale·session-state reason

## CLI

```bash
uv run python -m src.v10.cli prd02-build --input <fixture>
uv run python -m src.v10.cli prd02-verify --artifact <artifact>
uv run python -m src.v10.cli prd02-acceptance
```

## Acceptance와 Mutation

| Case | Required result |
| --- | --- |
| 정상 5개 봉 | Complete canonical 5분봉 |
| `missing_minute` | Incomplete, downstream 차단 |
| `watermark_early` | Complete 판정 금지 |
| `auction_mixed` | `V10_SESSION_STATE_MIXED` |
| `late_revision` | 원본 불변, supersede 생성 |
| `future_revision_replay` | `V10_REPLAY_LOOKAHEAD` |
| 같은 revision 중복 | Idempotent no-op |

## 완료 조건

- 모든 세션 경계 fixture를 독립 실행한다.
- Original과 supersede chain을 canonical replay로 재구성한다.
- PRD 01 외 다른 구현 없이 5분봉과 revision artifact를 생성한다.
