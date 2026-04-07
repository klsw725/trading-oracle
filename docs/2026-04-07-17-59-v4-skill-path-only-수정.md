# 작업 기록 — v4 스펙/PRD skill-path only 수정

- 시각: 2026-04-07 17:59 (Asia/Seoul)
- 사용자 프롬프트:
  - "그래서 스킬 호출할때는 다르게 하고 싶다는건뎀"
  - "스펙, PRD 다 수정해"

## 요약

- v4 스펙과 Phase 21 PRD의 범위를 **전면 caller-owned 전환**에서 **스킬 호출 경로 전용 분기**로 축소했다.
- 로컬 CLI/비스킬 경로는 기존 내부 provider 흐름을 유지하도록 문서를 수정했다.

## 변경 파일

- `docs/specs/v4/SPEC.md`
- `docs/specs/v4/prds/phase21-skill-owned-llm.md`

## 핵심 수정점

- "스킬 경로에서만" 호출자 LLM ownership 적용
- 로컬 CLI 기본 동작 유지 명시
- 성공 기준/리스크/마이그레이션을 skill-path only 전제로 재작성
- Phase 21 PRD의 마일스톤과 검증 기준을 같은 전제로 수정
