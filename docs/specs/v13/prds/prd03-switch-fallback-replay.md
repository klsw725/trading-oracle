# PRD: v13 PRD 03 Switch, Fallback, Replay
> **상태**: 📝 초안
> 상위 SPEC: [v13 SPEC](../SPEC.md)

## 의존성

- v11 fill·cost·risk·ledger
- v13 PRD 01 scoring과 PRD 02 validation result

## 목표

15분 hold·0.10 challenger switch, quant fallback, circuit breaker, immutable LLM replay를 구현한다.

## 구현 표면

| 경로 | 책임 |
| --- | --- |
| `src/v13/switch.py` | Frozen incumbent score와 two-leg switch |
| `src/v13/fallback.py` | Symbol·market quant-only decision |
| `src/v13/circuit_breaker.py` | 3연속 또는 최근20회 20% rule |
| `src/v13/replay.py` | Raw response와 validation 결과 재사용 |
| `src/v13/events.py` | Switch·fallback·circuit event |

## Switch 흐름

1. Entry composite를 immutable incumbent score로 저장한다.
2. 최소 15분 뒤 challenger가 +0.10 이상일 때만 시작한다.
3. 첫 1분 경계에 incumbent 전량청산을 시도한다.
4. Reconciliation 뒤 flat 상태에서 risk를 다시 검사한다.
5. 다음 1분 경계에 challenger를 진입한다.
6. Partial exit이면 challenger 없음, entry 실패면 flat 유지한다.

## Fallback·Replay

- Timeout, provider, schema, hash, version, overflow는 quant-only다.
- 3회 연속 또는 최근 20회 중 20% 실패면 남은 세션 circuit open이다.
- 다음 정규장에서 reset probe를 실행한다.
- Replay는 저장된 원본 response를 사용하며 Codex 재호출은 0회다.

## Acceptance

- Hold 15분 미만, 정확히 +0.10, 미만·초과
- Same·opposite direction two-leg switch
- Partial liquidation, missed boundary, rejected entry
- Circuit 조건 두 종류와 next-session reset
- `switch_same_boundary`, `replay_recall`

## 완료 조건

- Switch의 각 leg가 독립 비용·liquidity와 ledger event를 가진다.
- 원본 replay가 최초 decision과 byte-identical하다.
