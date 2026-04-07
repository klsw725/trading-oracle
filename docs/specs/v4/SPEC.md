# Trading Oracle v4 — Skill-Path LLM Delegation Architecture

> v1 SPEC: [../multi-perspective/SPEC.md](../multi-perspective/SPEC.md) (Phase 1~10)
> v2 SPEC: [../v2/SPEC.md](../v2/SPEC.md) (Phase 11~13)
> v3 SPEC: [../v3/SPEC.md](../v3/SPEC.md) (Phase 14~19)
> v4는 **스킬 호출 경로에서만** 프로젝트 내부 LLM 호출과 스킬 호출자의 응답 생성을 분리하여, shacs-bot/스킬 호출자가 자신의 LLM으로 최종 답변을 생성하도록 만든다. 로컬 CLI와 비스킬 경로는 기존 구조를 유지한다.

## PRD 연결

| Phase | PRD | 상태 | 설명 |
|-------|-----|------|------|
| Phase 21 | [phase21-skill-owned-llm.md](prds/phase21-skill-owned-llm.md) | 📝 초안 | 스킬 경로 전용 LLM 위임 + payload 계약 도입 |

---

## 개요

### 현재 구조의 문제

현재 사용자 분석 흐름은 대체로 아래와 같다.

```text
SKILL.md
→ uv run scripts/daily.py --json
→ 프로젝트 내부에서 데이터 수집
→ 프로젝트 내부에서 Codex/Anthropic 호출
→ 프로젝트가 최종 reasoning/verdict 문장을 생성
→ 스킬 호출자는 이미 생성된 결과를 전달
```

이 구조는 **스킬 호출 경로에서** 다음 문제를 만든다.

1. **LLM 소유권 중복**
   - 스킬 호출자도 LLM을 갖고 있는데, 프로젝트 내부도 다시 LLM을 호출한다.
   - 응답 품질/톤/정책을 호출자 쪽에서 일관되게 제어하기 어렵다.

2. **경계 불명확**
   - 프로젝트는 데이터 공급자이면서 동시에 응답 생성자 역할까지 수행한다.
   - shacs-bot 스킬은 단순 CLI 래퍼가 되어 버린다.

3. **재사용성 저하**
   - 동일 분석 데이터를 다른 채널/호출자/모델에 재사용하기 어렵다.
   - 호출자 LLM이 더 풍부한 대화 맥락을 갖고 있어도 프로젝트 내부 LLM 결과에 묶인다.

4. **비용/관측성 분산**
   - 어떤 응답이 어느 LLM에서 생성됐는지 경로가 분산된다.
   - 스킬 호출자 기준 비용 통제와 실패 복구가 어려워진다.

### v4 목표

v4의 목표는 **스킬 호출 경로에서만** 사용자 응답 생성의 LLM 소유권을 스킬 호출자에게 이동하는 것이다.

즉:

- **스킬 호출 경로**: 호출자 LLM 소유
- **로컬 CLI / 비스킬 경로**: 기존 프로젝트 내부 provider 흐름 유지

스킬 경로에서 프로젝트는 아래 책임만 가진다.

- 시장/종목/포트폴리오 데이터 수집
- 시그널/펀더멘털/합의도 계산
- 관점별 판단 근거를 구조화된 payload로 반환
- (선택) 호출자 LLM이 쓰기 쉬운 prompt package 제공

그리고 스킬 경로의 최종 자연어 응답은 아래가 담당한다.

- shacs-bot 스킬 호출자
- 또는 이 프로젝트를 감싼 상위 오케스트레이터

---

## 설계 원칙

1. **스킬 경로에서만 호출자 소유**
   - 스킬 기반 사용자 응답은 호출자 LLM이 생성한다.
   - 로컬 CLI/비스킬 경로는 기존 provider 흐름을 유지한다.

2. **프로젝트는 판단 재료를 반환**
   - 최종 문장보다 근거 데이터, 중간 판정, 합의 메타데이터를 우선 반환한다.

3. **기존 CLI는 유지**
   - 기존 내부 LLM 경로는 즉시 제거하지 않는다.
   - v4는 스킬 경로용 분기를 추가하는 작업이지, 전체 경로 전면 교체가 아니다.

4. **스킬 친화적 contract 제공**
   - 호출자가 별도 역공학 없이 바로 사용할 수 있는 JSON schema를 제공한다.

5. **도메인 로직과 응답 생성 분리**
   - 시그널 계산, 합의도 계산, 포지션 사이징은 계속 프로젝트에 남긴다.
   - 자연어 스타일링, 답변 문체, 채널 최적화는 호출자에 둔다.

---

## 1. 사용자 시나리오

### 1-1. shacs-bot 일일 분석

1. 사용자가 스킬을 통해 "오늘 주식 분석해줘" 요청
2. 스킬이 `uv run scripts/daily.py --json --llm-mode payload` 실행
3. 프로젝트는 구조화된 분석 payload 반환
4. 스킬 호출자가 자신의 LLM에 payload + 사용자 맥락을 전달
5. 호출자 LLM이 최종 답변 생성

### 1-2. 추천 파이프라인

1. 사용자가 "뭐 살까?" 요청
2. 스킬이 `uv run scripts/recommend.py --json --llm-mode payload` 실행
3. 프로젝트는 추천 후보, 합의도, 액션 플랜, selection metadata 반환
4. 호출자 LLM이 답변 채널에 맞게 요약/설명

### 1-3. 단일 관점 분석

1. 사용자가 "매크로 관점에서 삼성전자 어때?" 요청
2. 스킬이 `uv run scripts/perspective.py ... --json --llm-mode payload` 실행
3. 프로젝트는 관점별 구조화 reasoning만 반환
4. 호출자 LLM이 사용자 질문에 맞는 문장으로 재조립

### 1-4. 로컬 CLI/비스킬 경로

기존 로컬 사용자나 수동 실행 사용자는 기존 동작을 그대로 사용한다.

```text
uv run scripts/daily.py --json
```

즉, v4는 **스킬 경로용 호출 규약**을 추가하는 것이고, 로컬 CLI 기본 동작을 바꾸는 작업이 아니다.

---

## 2. 범위

### 포함

- `scripts/daily.py`
- `scripts/recommend.py`
- `scripts/perspective.py`
- `main.py`의 사용자 분석 진입점 중 스킬에서 호출 가능한 경로
- 다관점 분석/합의도/포지션 사이징 결과의 payload화
- 스킬 호출자를 위한 prompt package 또는 response schema 제공
- 스킬 경로와 비스킬 경로를 구분하는 호출 분기 규약

### 제외 (1차 범위 밖)

- `scripts/build_causal.py`의 내부 LLM 사용 제거
- `prompt_tuner.py` 같은 오프라인 개선/연구성 LLM 작업 제거
- 인과 그래프 구축/검증 등 배치성 내부 LLM 작업 전면 개편
- 로컬 CLI의 기본 provider 흐름 변경

즉, v4 1차 범위는 **스킬 기반 사용자 응답 경로**에 한정한다.

---

## 3. 아키텍처 변경

### 현재 (공통)

```text
Skill caller
→ project CLI
→ project internal LLM
→ final answer-like JSON/text
```

### 목표 (스킬 경로만)

```text
Skill caller
→ project CLI
→ analysis payload JSON
→ caller-owned LLM
→ final user answer
```

### 비스킬 경로

```text
Local CLI / manual execution
→ project CLI
→ project internal LLM
→ current output
```

### 계층 구조

```text
┌─────────────────────────────────────────────────────┐
│ Caller Layer                                         │
│  shacs-bot / orchestrator / skill runtime            │
│  - user context                                      │
│  - channel formatting                                │
│  - final LLM response generation                     │
├─────────────────────────────────────────────────────┤
│ Contract Layer                                       │
│  JSON payload / prompt package / schema version      │
├─────────────────────────────────────────────────────┤
│ Domain Layer                                         │
│  signals / perspectives / consensus / action plan    │
├─────────────────────────────────────────────────────┤
│ Data Layer                                           │
│  market / fundamentals / web / macro / portfolio     │
└─────────────────────────────────────────────────────┘
```

---

## 4. 스킬 경로 실행 모드

### 4-1. `payload`

프로젝트는 스킬 경로에서 내부 LLM 최종 응답을 만들지 않고, 호출자에게 필요한 구조화 결과만 반환한다.

```bash
uv run scripts/daily.py --json --llm-mode payload
```

**의도**:
- 스킬 호출자가 응답 생성 LLM을 완전히 소유
- 프로젝트는 데이터 공급자 역할만 수행

### 4-2. `prompt-ready`

프로젝트는 payload와 함께 호출자 LLM이 바로 사용할 수 있는 prompt package를 반환한다.

예:

```json
{
  "mode": "prompt-ready",
  "schema_version": "v1",
  "system_prompt": "...",
  "user_payload": {...},
  "response_schema": {...}
}
```

**의도**:
- 도메인 프롬프트 자산은 프로젝트에 남기되
- 실제 LLM 호출은 호출자가 수행

### 기본값 정책

- 스킬/자동화 경로 기본값: 장기적으로 `payload`
- 로컬 CLI 기본값: 기존 project-owned 흐름 유지
- `payload`/`prompt-ready`는 스킬 경로 전용 규약으로 본다.

---

## 5. Payload 계약

### 최상위 공통 필드

모든 **스킬 대상 명령**의 JSON은 최소한 아래 필드를 공통 제공해야 한다.

```json
{
  "schema_version": "v1",
  "llm_mode": "payload",
  "generated_at": "2026-04-07T17:00:00+09:00",
  "command": "daily",
  "user_intent": "portfolio_daily_analysis",
  "market": {...},
  "portfolio": {...},
  "analysis": {...},
  "render_hints": {...}
}
```

### 핵심 원칙

- `analysis`는 **문장 묶음이 아니라 판단 구조**여야 한다.
- `render_hints`는 호출자 LLM이 우선순위를 잡는 데 도움이 되는 최소 힌트만 담는다.
- payload만으로 호출자 LLM이 답변을 재구성할 수 있어야 한다.

### `analysis` 필드 예시 (`daily`)

```json
{
  "tickers": [
    {
      "ticker": "005930",
      "name": "삼성전자",
      "signals": {...},
      "fundamentals": {...},
      "perspectives": [
        {
          "perspective": "kwangsoo",
          "verdict": "SELL",
          "confidence": 0.9,
          "reasoning": ["..."],
          "reason": "손절가 이탈"
        }
      ],
      "consensus": {
        "consensus_verdict": "SELL",
        "confidence": "high",
        "vote_summary": {"BUY": 1, "SELL": 4, "HOLD": 0, "N/A": 0},
        "action_plan": {...}
      }
    }
  ]
}
```

### `render_hints` 예시

```json
{
  "primary_order": ["portfolio_alerts", "sell_first", "buy_candidates"],
  "highlight_tickers": ["005930"],
  "max_reasons_per_perspective": 2,
  "tone": "decisive_brief"
}
```

`render_hints`는 최종 답변을 강제하지 않는다. 호출자 LLM이 정렬/요약을 쉽게 하기 위한 보조 정보다.

---

## 6. Prompt package 계약 (`prompt-ready`)

`prompt-ready` 모드에서는 payload 외에 아래 필드를 추가로 제공할 수 있다.

- `system_prompt`: 호출자 LLM에 넣을 시스템 지침
- `prompt_context`: 도메인 컨텍스트 요약
- `response_schema`: 기대 응답 구조
- `answer_constraints`: 과장 금지, 포맷 요구 등

예시:

```json
{
  "schema_version": "v1",
  "llm_mode": "prompt-ready",
  "system_prompt": "당신은 보수적인 투자 분석 보조자다...",
  "prompt_context": {
    "analysis": {...},
    "user_question": "오늘 주식 분석해줘"
  },
  "response_schema": {
    "sections": ["시장", "보유종목", "행동 제안"],
    "must_include": ["consensus", "action_plan", "risk alerts"]
  }
}
```

---

## 7. 기존 기능과의 관계

### 유지되는 것

- 시그널 계산
- 관점별 verdict 계산
- 합의도 계산
- 포지션 사이징/action plan
- 추천 후보군 선택
- 웹 검색/매크로/환율 등 보조 데이터 수집
- 로컬 CLI/비스킬 경로의 내부 provider 사용 방식

### 바뀌는 것

- 스킬 경로에서 최종 자연어 응답 생성 주체
- 프로젝트 JSON의 책임 범위
- `--no-llm`의 의미 확장 또는 대체

### `--no-llm`와의 관계

현재 `--no-llm`은 단순히 LLM 분석을 생략한다. 하지만 v4의 `payload`는 스킬 경로에서 **호출자에게 넘길 충분한 판단 구조를 제공하는 모드**여야 한다.

즉:

- `--no-llm`: reasoning 자체를 줄이는 비용 절감 모드
- `--llm-mode payload`: 호출자 LLM용 구조화 응답 모드

둘은 동일 개념이 아니다.

---

## 8. 마이그레이션 전략

### 1단계

- 스킬 경로에서 호출되는 `daily`, `recommend`, `perspective`에 `--llm-mode` 도입
- `payload` schema 정의
- 로컬 CLI 기본 경로 유지

### 2단계

- 스킬 정의에서 `payload` 모드 사용 시작
- 호출자 LLM이 payload 기반 답변 생성

### 3단계

- 필요 시 `prompt-ready` 모드 추가
- 내부 prompt 자산을 호출자 친화적으로 노출

### 4단계

- 스킬 문서/가이드에서 권장 경로를 payload 기반으로 전환
- 비스킬 경로는 유지하되, 스킬 경로 분기 문서를 명확히 함

---

## 9. 리스크

| 리스크 | 영향 | 완화 |
|--------|------|------|
| payload가 불충분함 | 호출자 LLM이 품질 낮은 답변 생성 | schema에 reasoning/action/risk 필수화 |
| schema 드리프트 | 스킬 호출자가 쉽게 깨짐 | `schema_version` 명시 + 하위 호환 규칙 |
| 스킬 경로와 비스킬 경로 이중 유지 비용 | 복잡도 증가 | 스킬 경로에 한정해 점진 전환 |
| 호출자별 답변 편차 | 재현성 저하 | `prompt-ready` 옵션과 `render_hints` 제공 |
| 기존 내부 LLM 의존 관점 파서 | payload 모드 구현 범위 혼선 | 1차는 사용자-facing 명령 중심으로 제한 |

---

## 10. 성공 기준

v4는 아래가 가능할 때 성공이다.

1. 스킬 호출자가 `daily/recommend/perspective` 결과만으로 최종 답변을 생성할 수 있다.
2. 스킬 경로에서 프로젝트 내부 Codex/Anthropic 호출 없이도 사용자 응답 품질이 유지된다.
3. 기존 CLI 사용자는 추가 설정 없이 기존 동작을 유지할 수 있다.
4. payload schema만 보고 호출자가 역공학 없이 통합할 수 있다.
