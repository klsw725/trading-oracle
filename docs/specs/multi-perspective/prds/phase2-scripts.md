# PRD: Phase 2 — Scripts 분리 및 shacs-bot 연동

> **SPEC 참조**: [SPEC.md §8 (shacs-bot 연동)](../SPEC.md#8-shacs-bot-연동), [§2-2 (디렉터리 구조)](../SPEC.md#2-2-디렉터리-구조)
> **상태**: ✅ 완료 (M1~M4 구현)
> **우선순위**: P1 — Phase 1 완료 후 착수
> **선행 조건**: Phase 1 (다관점 시스템) M5 완료

---

## 문제

현재 `main.py`가 분석, 포트폴리오 관리, 스크리닝을 모두 담당하는 모놀리스 구조다. shacs-bot에서 호출할 때 기능별 진입점이 없어 argparse 분기가 복잡하고, 새 기능(단일 관점 분석, 인과 그래프 구축) 추가 시 `main.py`가 비대해진다.

## 솔루션

`scripts/` 디렉터리에 기능별 진입점을 분리한다. 각 스크립트는 `--json` 플래그로 shacs-bot 파싱 가능한 JSON을 stdout에 출력한다. `main.py`는 하위 호환을 위해 유지하되, 공유 로직은 `src/common.py`로 추출.

## 현재 상태

| 컴포넌트 | 상태 | 비고 |
|----------|------|------|
| `src/common.py` | ✅ 완성 | 공유 유틸리티 (분석, 스크리닝, 다관점 실행, JSON 인코더) |
| `scripts/daily.py` | ✅ 완성 | 다관점 일일 분석 진입점 |
| `scripts/portfolio.py` | ✅ 완성 | 포트폴리오 CRUD (add/remove/cash/show/history) |
| `scripts/screen.py` | ✅ 완성 | 주도주 스크리닝 단독 실행 |
| `scripts/perspective.py` | ✅ 완성 | 단일 관점 분석 (5개 관점 선택) |
| `main.py` | ✅ 완성 | src/common.py 사용. 하위 호환 유지 |
| `SKILL.md` | ✅ 갱신 | scripts/ 기반 매핑 테이블 반영 |

## 기술적 제약

- `PORTFOLIO_PATH`는 상대 경로 `Path("data/portfolio.json")`. scripts/ 에서 `_PROJECT_ROOT` 계산 후 `os.chdir()` + `sys.path` 조작으로 해결.
- argparse help 문자열에 `%` 리터럴 사용 금지 (Python 3.14 크래시). `%%` 이스케이프 필수.
- numpy 타입 JSON 직렬화 — `src/common.py`의 `NumEncoder` 패턴을 모든 스크립트에서 통일 적용.

---

## 마일스톤

### M1: scripts/ 디렉터리 구성 및 daily.py 분리
- [x] `scripts/daily.py` — 다관점 일일 분석 진입점. Phase 1의 consensus 파이프라인 호출.
- [x] `scripts/daily.py -t 005930 --json` 실행 → 5개 관점 + 합의도 JSON 출력
- [x] 프로젝트 루트 기준 경로 해결 (`_PROJECT_ROOT` + `os.chdir` + `sys.path.insert`)

**검증**: `cd /tmp && uv --directory /path/to scripts/portfolio.py show --json` → `data/portfolio.json` 정상 접근 ✅

### M2: portfolio.py 및 나머지 CRUD 스크립트 분리
- [x] `scripts/portfolio.py` — add, remove, cash, show, history 서브커맨드
- [x] `scripts/screen.py` — 주도주 스크리닝 단독 실행
- [x] `scripts/perspective.py` — 단일 관점 분석 (`--kwangsoo`, `--quant` 등 플래그)

**검증**: SPEC §8-2의 모든 사용자 요청 → 스크립트 매핑 테이블 통과 ✅

### M3: main.py thin wrapper 전환
- [x] `main.py`가 `src/common.py` 공유 로직 사용. `cmd_analyze()`는 `common.collect_market_data()`, `common.run_multi_perspective()` 등 호출.
- [x] 기존 CLI 인터페이스 100% 하위 호환 유지 (`uv run main.py add ...`, `uv run main.py --screen` 등)

**검증**: 기존 main.py 사용법 전체 동작 확인 ✅

### M4: SKILL.md 갱신 및 shacs-bot 연동 테스트
- [x] `SKILL.md`를 SPEC §8-2 매핑 테이블 기준으로 갱신. scripts/ 기반 명령어 매핑.
- [x] 모든 스크립트의 `--json` 출력이 구조화된 JSON
- [x] 에러 시에도 JSON 형태의 에러 응답 반환 (`{"status": "error", "message": "..."}`)

**검증**: SKILL.md의 모든 예시 명령어 --help 실행 확인 ✅

---

## 진행 로그

| 날짜 | 내용 |
|------|------|
| 2026-03-28 | PRD 작성. |
| 2026-03-28 | M1~M4 구현: src/common.py 공유 로직 추출, scripts/ 4개 생성, main.py 리팩터, SKILL.md 갱신. |
| 2026-03-28 | call_llm() provider 분기 수정 (Codex/Anthropic). perspectives가 config.llm.provider를 따르도록. |
