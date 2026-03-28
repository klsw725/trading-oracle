# PRD: Phase 1 — 다관점 투자 판정 시스템

> **SPEC 참조**: [SPEC.md §3 (5개 투자 관점 정의)](../SPEC.md#3-5개-투자-관점-정의), [§4 (합의도 시스템)](../SPEC.md#4-합의도-시스템-maxs-lite)
> **상태**: 🟡 미착수
> **우선순위**: P0 — 핵심 기능

---

## 문제

현재 시스템은 단일 LLM 프롬프트(`src/agent/prompts.py`)로 분석을 수행한다. 하나의 관점에 의존하면 확증 편향, 단일 장애점, 판단 근거의 불투명성 문제가 발생한다. 사용자는 "왜 매도해야 하는가"에 대해 복수의 독립적 근거를 비교하고 싶어한다.

## 솔루션

5개 독립 투자 관점(이광수, 포렌식, 퀀트, 매크로, 가치)이 동일 데이터를 기반으로 병렬 판정하고, 합의도 시스템(MAXS-lite)이 결과를 종합하여 행동 지침을 제공한다.

## 현재 상태 (구현 기준선)

| 컴포넌트 | 상태 | 비고 |
|----------|------|------|
| `src/signals/technical.py` | ✅ 완성 | 6-시그널 앙상블 보팅 |
| `src/data/market.py` | ✅ 완성 | OHLCV + 지수 |
| `src/data/fundamentals.py` | ✅ 완성 | 네이버 PER/PBR 스크래핑 |
| `src/agent/oracle.py` | ✅ 완성 | Claude API 연동 (SSE 파싱 포함) |
| `src/agent/prompts.py` | ✅ 완성 | 단일 관점 프롬프트 (하위 호환 유지) |
| `src/perspectives/` | ❌ 미구현 | 5개 관점 + base 인터페이스 |
| `src/consensus/` | ❌ 미구현 | voter + scorer |
| 펀더멘털 캐시 | ❌ 미구현 | `data/fundamentals_cache.json` |

## 기술적 의존성

- `anthropic` SDK — `client.messages.create()`가 SSE raw string을 반환하는 환경. `oracle.py`의 `_parse_sse_response()` 패턴을 따라야 함.
- 퀀트 관점은 `technical.py`에서 verdict/signals를 코드로 직접 계산. LLM은 reasoning 텍스트만 생성하는 하이브리드 구조.
- 네이버 금융 PER/PBR은 `em` 태그의 `id` 속성(`_per`, `_pbr`)으로 추출. 캐시 도입 시 7일 TTL 정책.

## 위험 요소

| 위험 | 영향 | 완화 |
|------|------|------|
| LLM JSON 파싱 실패 | 관점 N/A 처리 | 1회 재시도 후 N/A. 퀀트는 코드 폴백 |
| 5개 병렬 API 호출 비용 | 일 $0.10~$0.20 | 퀀트 LLM은 reasoning만. 월 $3~$6 예산 내 |
| 네이버 스크래핑 불안정 | 가치 관점 비활성화 | 7일 캐시 도입 |
| Anthropic SDK SSE 반환 | 모든 관점에서 파싱 필요 | `oracle.py`의 `_parse_sse_response` 재사용 |

---

## 마일스톤

### M1: Perspective 기반 인터페이스 및 이광수 관점 구현
- [ ] `src/perspectives/base.py` — `Perspective` ABC 정의 (공통 필드 규격: perspective, verdict, confidence, reasoning, reason, action)
- [ ] `src/perspectives/kwangsoo.py` — 기존 `prompts.py` 로직을 이광수 관점으로 분리. 추적 손절매 + 모멘텀 기반 판정.
- [ ] 이광수 관점 단독 실행 시 SPEC §3-1 출력 형식의 JSON 반환 확인

**검증**: 이광수 관점에 삼성전자 데이터 입력 → verdict/confidence/reasoning/action 포함 JSON 반환

### M2: 나머지 4개 관점 구현
- [ ] `src/perspectives/ouroboros.py` — 포렌식 감사관. 희석 리스크, 내부자 거래, 기관 수급 판정.
- [ ] `src/perspectives/quant_perspective.py` — 하이브리드 구조: `technical.py`에서 verdict/signals 코드 계산 + LLM reasoning. LLM 실패 시 코드 결과만 반환.
- [ ] `src/perspectives/macro.py` — 매크로 인과 체인. 금리/환율/섹터 사이클 판정.
- [ ] `src/perspectives/value.py` — PER/PBR/배당 기반 절대 가치 평가.

**검증**: 각 관점에 동일 종목 데이터 입력 → SPEC §3 출력 형식 준수 확인. 퀀트 관점은 LLM 없이도 verdict/signals 반환.

### M3: 합의도 시스템 (MAXS-lite) 구현
- [ ] `src/consensus/voter.py` — 5개 관점 병렬 호출 (`asyncio`/`ThreadPool`). 부분 실패 허용, 파싱 실패 1회 재시도.
- [ ] `src/consensus/scorer.py` — 합의도 계산: 만장일치 / 강한 합의 / 약한 합의 / 분기 / 판정 보류.
- [ ] 분기 시 양측 근거 구조화 (SPEC §4-3 형식)

**검증**: 5개 관점 중 1개를 의도적으로 실패시켜도 나머지 4개로 합의도 계산 성공. 분기 결과가 양측 근거를 포함.

### M4: 펀더멘털 캐시 및 가치 관점 안정화
- [ ] `data/fundamentals_cache.json` 도입. 스크래핑 성공 시 갱신, 실패 시 7일 TTL 캐시 사용, 초과 시 가치 관점 비활성화.
- [ ] 캐시 사용 시 출력에 `(캐시: YYYY-MM-DD 기준)` 표시

**검증**: 네이버 스크래핑 차단 시뮬레이션 → 7일 이내 캐시 사용, 7일 초과 시 가치 관점 N/A 처리 확인

### M5: main.py 통합 및 하위 호환
- [ ] `main.py`에 `--multi` 또는 기본 모드로 다관점 분석 경로 추가. 기존 단일 관점은 `--legacy` 플래그로 유지.
- [ ] `--json` 출력에 5개 관점 판정 + 합의도 포함
- [ ] 기존 CLI 명령어(`add`, `remove`, `cash`, `portfolio`, `history`) 변경 없음 확인

**검증**: `uv run main.py --json` 실행 → 5개 관점 + 합의도 JSON 출력. 기존 명령어 모두 동작.

---

## 진행 로그

| 날짜 | 내용 |
|------|------|
| 2026-03-28 | PRD 작성. 현재 코드베이스 분석 완료. |
