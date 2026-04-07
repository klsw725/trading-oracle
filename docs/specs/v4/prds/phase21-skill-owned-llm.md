# PRD: Phase 21 — 스킬 경로 전용 LLM 위임 구조

> **SPEC 참조**: [../SPEC.md](../SPEC.md)
> **상태**: 📝 초안
> **우선순위**: P1
> **선행 조건**: Phase 19 완료, Phase 20 스펙 초안 존재

---

## 한 줄 요약

스킬 기반 사용자 응답 경로에서만 **프로젝트 내부 LLM 호출을 호출자 쪽으로 위임**하고, 로컬 CLI/비스킬 경로는 기존 provider 흐름을 유지한다.

---

## 문제

현재 스킬 기반 사용자 분석 경로는 프로젝트 내부에서 LLM(Codex/Anthropic)을 직접 호출하여 최종 reasoning 성격의 결과를 생성한다.

이 구조는 다음 문제를 만든다.

1. **스킬 호출자의 LLM 소유권 상실**
   - 상위 호출자가 사용자 맥락과 채널 특성을 알고 있어도, 최종 응답 생성은 프로젝트 내부 provider에 묶인다.

2. **프로젝트 책임 과다**
   - 프로젝트가 데이터 수집, 도메인 판단, 자연어 응답 생성까지 모두 담당한다.

3. **통합 경직성**
   - 다른 호출자/채널/LLM으로 동일 분석을 재사용하기 어렵다.

4. **비용과 실패 지점 분산**
   - 내부 provider 오류가 스킬 경로 전체를 깨뜨린다.

## 사용자 문제 / 기대 변화

### 해결하려는 사용자 문제

- 스킬 호출자가 이미 사용자 대화 맥락과 채널 제약을 알고 있는데, 최종 응답 생성이 프로젝트 내부 provider에 묶여 있다.
- 스킬 호출자는 "답변 재료"가 아니라 이미 생성된 결과만 받아 후처리 여지가 작다.
- 같은 분석 결과를 서로 다른 호출자/LLM/채널에 재사용하기 어렵다.

### 사용자에게 생기는 변화

- 스킬 호출자는 동일 payload로 더 일관된 답변 톤과 정책을 유지할 수 있다.
- provider 자격 증명이 없는 스킬 환경에서도 payload 모드 실행이 가능해진다.
- 프로젝트는 스킬 경로에서는 도메인 분석 엔진으로, 호출자는 응답 엔진으로 역할이 명확해진다.
- 로컬 CLI 사용자는 기존 사용 방식을 바꿀 필요가 없다.

## 솔루션

스킬 기반 사용자 응답 경로에 `--llm-mode`를 도입하고, 스킬 호출 시 기본 목표 모드를 `payload`로 정의한다.

```text
skill caller
→ project CLI (--llm-mode payload)
→ structured analysis payload
→ caller-owned LLM
→ final answer
```

프로젝트는 스킬 경로에서 구조화된 판단 재료를 반환하고, 최종 자연어 응답은 호출자 LLM이 생성한다. 로컬 CLI와 비스킬 경로는 기존 내부 provider 흐름을 유지한다.

---

## 사용자 여정

1. 사용자가 스킬에서 분석/추천/관점 질문을 한다.
2. 스킬 호출자는 해당 CLI를 `--llm-mode payload` 또는 `--llm-mode prompt-ready`로 실행한다.
3. 프로젝트는 시장/포트폴리오/합의도/액션 플랜을 구조화된 JSON으로 반환한다.
4. 스킬 호출자는 자신의 LLM에 사용자 질문 + payload를 함께 전달한다.
5. 호출자 LLM이 채널에 맞는 최종 응답을 생성한다.
6. 로컬 CLI 사용자는 별도 전환 없이 기존 동작을 그대로 사용한다.

---

## 설계 원칙

- **스킬 경로 전용 위임**: 최종 답변 생성 위임은 스킬 호출 경로에만 적용
- **외과적 변경**: 시그널/합의도/액션 플랜 계산 로직은 유지
- **기존 경로 유지**: 로컬 CLI/비스킬 경로는 그대로 둔다
- **명시적 계약**: schema version과 필수 필드를 문서화
- **단계적 전환**: 사용자-facing 명령부터 우선 전환

## 통합 지점

- `scripts/daily.py`: 일일 분석 payload 출력
- `scripts/recommend.py`: 추천 결과/selection metadata payload 출력
- `scripts/perspective.py`: 단일 관점 구조화 결과 출력
- `src/common.py`: 공통 응답 구조 조립, 모드 분기, 재사용 유틸리티
- `src/perspectives/base.py`: 내부 provider 호출 경계 분리
- `src/agent/oracle.py`, `src/agent/codex.py`: 비스킬/기존 경로 유지 대상
- `SKILL.md`: 스킬 실행 예시와 권장 모드 반영
- `README.md`: 새로운 권장 호출 방식 문서화 대상

---

## 마일스톤

### M1: 실행 모드와 공통 contract 정의

**목표**: 스킬 경로에서 사용할 `payload`, `prompt-ready` 모드를 명시하고 공통 schema를 정의한다.

**변경 파일**:
- `docs/specs/v4/SPEC.md`
- `scripts/daily.py`
- `scripts/recommend.py`
- `scripts/perspective.py`
- 필요 시 `main.py`

- [ ] `--llm-mode` 플래그 추가
  - 허용값: `payload`, `prompt-ready`
- [ ] 공통 최상위 필드 정의
  - `schema_version`
  - `llm_mode`
  - `generated_at`
  - `command`
  - `user_intent`
- [ ] 스킬 경로에서 사용할 권장 모드를 문서에 명시
- [ ] 로컬 CLI/비스킬 경로는 기존 동작 유지라고 명시

**검증 기준**:
- 세 진입점이 동일한 모드 개념을 사용한다.
- schema version 없는 응답이 새 모드에서 나오지 않는다.
- payload/prompt-ready 선택이 스킬 문서에 명확히 반영된다.
- 로컬 CLI 기본 동작이 바뀌지 않는다.

---

### M2: `daily` payload 분리

**목표**: 스킬 경로의 일일 분석을 내부 최종 답변 없이도 재구성 가능한 payload로 반환한다.

**변경 파일**:
- `scripts/daily.py`
- `src/common.py`
- `src/consensus/*`
- `src/perspectives/*`
- 필요 시 신규 `src/contracts/` 또는 `src/payloads/`

- [ ] 종목별 공통 payload 구조 정의
  - `signals`
  - `fundamentals`
  - `perspectives`
  - `consensus`
  - `action_plan`
- [ ] 시장/포트폴리오/리스크 경고를 최상위 payload에 포함
- [ ] `render_hints` 포함
- [ ] payload만으로 사용자 응답 재구성이 가능하도록 필수 필드 보강

**검증 기준**:
- `uv run scripts/daily.py --json --llm-mode payload` 결과만으로
  - 시장 요약
  - 보유 종목 판단
  - 우선 행동 제안
  을 호출자에서 재작성 가능하다.
- 스킬 경로에서는 내부 provider 자격 증명이 없어도 payload 출력은 가능하다.
- 로컬 CLI 기본 경로는 기존과 동일하다.

---

### M3: `recommend` / `perspective` payload 분리

**목표**: 스킬 경로의 추천/단일 관점도 동일 contract 철학으로 맞춘다.

**변경 파일**:
- `scripts/recommend.py`
- `scripts/perspective.py`
- `src/common.py`

- [ ] 추천 결과에 다음 메타데이터 필수화
  - `universe_size`
  - `universe_breakdown`
  - `selection_constraints`
  - 종목별 `market`, `sector`, `selected_by`
- [ ] 단일 관점 응답도 perspective별 공통 구조 사용
- [ ] `daily`, `recommend`, `perspective` 간 필드명 최대한 통일

**검증 기준**:
- 호출자가 명령 종류별로 서로 다른 임시 파서를 만들 필요가 없다.
- 추천 결과의 선택 이유를 payload만으로 설명할 수 있다.
- 세 명령의 payload가 공통 최상위 필드를 공유한다.

---

### M4: 내부 LLM 호출 경로 격리

**목표**: 스킬 전용 새 모드에서는 프로젝트 내부 provider 호출이 일어나지 않도록 경계를 분명히 한다.

**변경 파일**:
- `src/perspectives/base.py`
- `src/agent/oracle.py`
- `src/agent/codex.py`
- `src/common.py`

- [ ] 새 모드에서 내부 provider 분기 진입 여부를 명확히 통제
- [ ] payload 생성에 꼭 필요한 reasoning은 가능한 구조화 데이터/기존 계산 결과로 보강
- [ ] 스킬 경로와 비스킬 경로의 분기 기준을 문서화

**검증 기준**:
- `payload` 모드에서는 스킬 대상 명령 실행 시 내부 provider 자격 증명이 없어도 동작 가능하다.
- 로컬 CLI/비스킬 경로에서는 기존 provider 동작이 유지된다.
- provider 오류가 payload 모드 전체를 깨뜨리지 않는다.

---

### M5: 호출자 통합 친화성 강화

**목표**: 상위 스킬 호출자가 payload를 쉽게 소비하도록 prompt-ready 옵션과 문서를 보강한다.

**변경 파일**:
- `docs/specs/v4/SPEC.md`
- `SKILL.md`
- 필요 시 `README.md`

- [ ] `prompt-ready` 모드 스키마 정의
- [ ] 스킬 호출 예시 문서화
- [ ] 어떤 필드를 caller LLM 입력으로 넣어야 하는지 가이드 추가

**검증 기준**:
- 새 호출자는 저장소 코드를 읽지 않고도 문서만으로 통합 가능하다.

---

## 문서화 영향

- `docs/specs/v4/SPEC.md`: PRD 링크/상태 반영
- `SKILL.md`: 스킬 호출 예시를 payload 중심으로 정리
- `README.md`: 스킬 경로와 로컬 CLI 경로의 차이 설명 추가 필요
- 로컬 작업 기록 문서: 구현/수정 작업마다 `docs/YYYY-MM-DD-HH-mm-*.md` 유지

---

## 비목표

- 인과 그래프 구축/배치성 연구 작업의 내부 LLM 제거
- 프롬프트 자가 튜닝 등 오프라인 개선 루프의 즉시 재설계
- 모든 기존 텍스트 응답 포맷의 완전한 유지 보장

---

## 주요 리스크와 완화

1. **payload 정보 부족**
   - 영향: 호출자 LLM 답변 품질 저하
   - 완화: `signals`, `perspectives`, `consensus`, `action_plan`, `render_hints`를 필수 필드화

2. **스킬/비스킬 이중 경로 복잡도**
   - 영향: 유지보수 비용 증가
   - 완화: 범위를 `daily/recommend/perspective` 3개 진입점으로 한정

3. **호출자별 답변 편차**
   - 영향: 결과 재현성 저하
   - 완화: `prompt-ready` 모드와 `response_schema` 제공

4. **기존 LLM 의존 reasoning 손실**
   - 영향: payload만으로 설명성이 부족할 수 있음
   - 완화: 구조화 reasoning과 render hints를 함께 제공하고, 필요한 최소 reasoning 필드를 유지

5. **문서와 구현 불일치**
   - 영향: 통합 실패
   - 완화: 문서 업데이트를 마일스톤 완료 조건에 포함

---

## 종속성

- 기존 다관점 분석/합의도/action plan 로직이 안정적으로 유지되어야 함
- `daily`, `recommend`, `perspective`가 모두 JSON 경로를 지원해야 함
- 스킬 호출자가 JSON payload를 LLM 입력으로 주입할 수 있어야 함
- 내부 provider(OAuth/API key)는 비스킬/기존 경로에서만 필수여야 함

---

## 수동 검증 시나리오

테스트 인프라가 없으므로 아래 커맨드 기반 수동 검증을 기준으로 한다.

1. `uv run scripts/daily.py --json --llm-mode payload`
2. `uv run scripts/recommend.py --json --llm-mode payload`
3. `uv run scripts/perspective.py --kwangsoo -t 005930 --json --llm-mode payload`
4. 내부 provider 자격 증명 없이도 payload 모드가 동작하는지 확인
5. 로컬 CLI 기본 실행에서 기존 결과가 유지되는지 확인
6. 동일 payload를 호출자 LLM에 넣어 시장/보유종목/행동제안 응답을 재구성할 수 있는지 확인

---

## 완료 정의

Phase 21은 아래가 모두 만족되면 완료다.

- 스킬 대상 3개 명령이 `payload` 모드를 지원한다.
- payload schema가 문서화되어 있다.
- payload만으로 호출자 LLM이 최종 답변을 생성할 수 있다.
- 로컬 CLI/비스킬 경로가 기존 방식대로 유지된다.

---

## 진행 로그

- 2026-04-07: 초안 작성 — v4 SPEC 기반으로 Phase 21 문제/솔루션/마일스톤 정의
- 2026-04-07: PRD 보강 — 사용자 여정, 통합 지점, 문서화 영향, 리스크, 종속성, 진행 로그 추가
- 2026-04-07: scope 수정 — 전면 caller-owned 해석을 줄이고 skill-path only 분기 구조로 재정의
