# PRD: Phase 2 — Scripts 분리 및 shacs-bot 연동

> **SPEC 참조**: [SPEC.md §8 (shacs-bot 연동)](../SPEC.md#8-shacs-bot-연동), [§2-2 (디렉터리 구조)](../SPEC.md#2-2-디렉터리-구조)
> **상태**: 🟡 미착수
> **우선순위**: P1 — Phase 1 완료 후 착수
> **선행 조건**: Phase 1 (다관점 시스템) M5 완료

---

## 문제

현재 `main.py`가 분석, 포트폴리오 관리, 스크리닝을 모두 담당하는 모놀리스 구조다. shacs-bot에서 호출할 때 기능별 진입점이 없어 argparse 분기가 복잡하고, 새 기능(단일 관점 분석, 인과 그래프 구축) 추가 시 `main.py`가 비대해진다.

## 솔루션

`scripts/` 디렉터리에 기능별 진입점을 분리한다. 각 스크립트는 `--json` 플래그로 shacs-bot 파싱 가능한 JSON을 stdout에 출력한다. `main.py`는 하위 호환을 위해 유지하되, 내부적으로 `scripts/`를 호출하는 thin wrapper로 전환한다.

## 현재 상태

| 컴포넌트 | 상태 | 비고 |
|----------|------|------|
| `main.py` (모놀리스) | ✅ 동작 | 분석 + 포트폴리오 + 스크리닝 통합 |
| `scripts/` | ❌ 미존재 | 디렉터리 자체 없음 |
| `SKILL.md` | ✅ 존재 | 현재 main.py 기준. 갱신 필요 |

## 기술적 제약

- `PORTFOLIO_PATH`는 상대 경로 `Path("data/portfolio.json")`. scripts/에서 실행 시 프로젝트 루트 기준 경로 보장 필요.
- argparse help 문자열에 `%` 리터럴 사용 금지 (Python 3.14 크래시). `%%` 이스케이프 필수.
- numpy 타입 JSON 직렬화 — `_NumEncoder` 패턴을 scripts에서도 일관 적용.

---

## 마일스톤

### M1: scripts/ 디렉터리 구성 및 daily.py 분리
- [ ] `scripts/daily.py` — 다관점 일일 분석 진입점. Phase 1의 consensus 파이프라인 호출.
- [ ] `scripts/daily.py -t 005930 --json` 실행 → 5개 관점 + 합의도 JSON 출력
- [ ] 프로젝트 루트 기준 경로 해결 (모든 scripts에서 `data/` 접근 가능)

**검증**: `cd /tmp && uv run /path/to/scripts/daily.py --json` → `data/portfolio.json` 정상 접근

### M2: portfolio.py 및 나머지 CRUD 스크립트 분리
- [ ] `scripts/portfolio.py` — add, remove, cash, show, history 서브커맨드
- [ ] `scripts/screen.py` — 주도주 스크리닝 단독 실행
- [ ] `scripts/perspective.py` — 단일 관점 분석 (`--kwangsoo`, `--quant` 등 플래그)

**검증**: SPEC §8-2의 모든 사용자 요청 → 스크립트 매핑 테이블 통과

### M3: main.py thin wrapper 전환
- [ ] `main.py`가 내부적으로 `scripts/*`를 import/호출하는 구조로 전환
- [ ] 기존 CLI 인터페이스 100% 하위 호환 유지 (`uv run main.py add ...`, `uv run main.py --screen` 등)

**검증**: 기존 main.py 사용법 전체 동작 확인. 새 기능도 main.py 경유 가능.

### M4: SKILL.md 갱신 및 shacs-bot 연동 테스트
- [ ] `SKILL.md`를 SPEC §8-2 매핑 테이블 기준으로 갱신
- [ ] 모든 스크립트의 `--json` 출력이 shacs-bot 서브에이전트에서 파싱 가능한 구조 확인
- [ ] 에러 시에도 JSON 형태의 에러 응답 반환 (`{"status": "error", "message": "..."}`)

**검증**: SKILL.md의 모든 예시 명령어 실행 → 유효 JSON 반환 (성공/실패 모두)

---

## 진행 로그

| 날짜 | 내용 |
|------|------|
| 2026-03-28 | PRD 작성. |
