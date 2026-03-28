# PRD: Phase 3 — 인과 그래프 (DEMOCRITUS-lite)

> **SPEC 참조**: [SPEC.md §5 (인과 그래프)](../SPEC.md#5-인과-그래프-democritus-lite), [§1-5 (인과 그래프 구축 시나리오)](../SPEC.md#1-5-인과-그래프-구축-1회성)
> **상태**: ✅ 완료 (M1~M5 구현)
> **우선순위**: P2 — Phase 1+2 완료 후 착수
> **선행 조건**: Phase 1 M2 (매크로 관점 구현) 완료

---

## 문제

매크로 관점(`macro.py`)이 "왜 이 종목이 이 매크로 변수에 영향받는가"를 설명할 때, LLM의 내부 지식에만 의존한다. 인과 관계의 명시적 구조가 없어 설명의 일관성이 떨어지고, "반도체 가격이 오르면 어떤 종목이 수혜?"같은 그래프 순회 질문에 답할 수 없다.

## 솔루션

LLM으로 한국 주식 시장 도메인의 인과 관계를 대량 추출하여 networkx DiGraph로 구축한다. 1회 구축(~500 토픽, ~1500 트리플), 분기 1회 증분 갱신. 매크로 관점 프롬프트에 관련 인과 체인을 주입하여 근거의 구조화 수준을 높인다.

## 현재 상태

| 컴포넌트 | 상태 | 비고 |
|----------|------|------|
| `src/causal/graph.py` | ✅ 완성 | networkx DiGraph 래퍼, JSON 직렬화, 경로/원인/결과 탐색 |
| `src/causal/builder.py` | ✅ 완성 | BFS 토픽 확장, 병렬 트리플 추출, 체크포인트 저장/재개 |
| `scripts/build_causal.py` | ✅ 완성 | build/update/info 서브커맨드, --json 지원 |
| `macro.py` 연동 | ✅ 완성 | 종목/섹터 키워드로 인과 체인 조회, 프롬프트에 주입 |
| `data/causal_graph.json` | ✅ 테스트 생성 | 15토픽 테스트 빌드 (88노드, 45트리플) |

---

## 마일스톤

### M1: 인과 그래프 데이터 구조 및 저장/로드
- [x] `src/causal/graph.py` — networkx DiGraph 래퍼. JSON 직렬화/역직렬화. SPEC §5-2 저장 형식 준수.
- [x] `data/causal_graph.json` 로드 시 메타데이터(created_at, num_topics, num_triples) 검증
- [x] 그래프 조회 API: 노드 검색 (`search_nodes`), 경로 탐색 (`find_paths`), 원인/결과 탐색 (`find_causes`/`find_effects`), 도메인 필터링 (`filter_by_domain`), 관련 체인 조회 (`get_related_chains`)

**검증**: 샘플 트리플 10개로 그래프 생성 → JSON 저장 → 로드 → 경로 탐색 동작 ✅

### M2: 토픽 확장 및 인과 진술 생성
- [x] `src/causal/builder.py` — 루트 토픽 8개(매크로경제, 반도체, 자동차, 방산, 금융, 바이오, 에너지, 소비재)에서 BFS 확장. ThreadPoolExecutor 병렬.
- [x] 각 토픽에서 인과 트리플 3개 생성 (subject, relation, object, domain)
- [x] 체크포인트 저장: `data/causal_checkpoint.json`에 진행 상태 저장. 재개 지원.

**검증**: 15토픽 빌드 → 45 트리플 생성 확인 ✅

### M3: 트리플 추출 및 그래프 구축 파이프라인
- [x] 트리플 추출은 `builder.py`의 `extract_triples()`에 통합 (별도 triples.py 불필요)
- [x] `scripts/build_causal.py` — build/update/info 서브커맨드. `--json`, `--max-topics`, `--max-depth`, `--fresh` 플래그.
- [x] 전체 파이프라인: 토픽 확장 → 트리플 추출 → 그래프 저장

**검증**: `uv run scripts/build_causal.py build --max-topics 15 --json` → `data/causal_graph.json` 생성 ✅

### M4: 매크로 관점 연동
- [x] `macro.py`의 `_get_causal_context()`가 종목명/섹터 키워드로 인과 체인 조회하여 프롬프트에 삽입
- [x] 인과 그래프 없으면 기존대로 LLM 내부 지식으로 동작 (graceful degradation)
- [x] 중복 제거된 인과 체인이 프롬프트에 포함

**검증**: 삼성전자 → 반도체 인과 체인 조회 성공. 한화에어로 → 방산 체인 조회 성공. ✅

### M5: 증분 갱신 및 문서화
- [x] `scripts/build_causal.py update <도메인>` — 기존 그래프에 새 도메인 추가
- [x] SKILL.md에 인과 그래프 명령어 추가
- [x] `networkx` 의존성 pyproject.toml에 추가

**검증**: help 메시지 및 info 명령어 동작 확인 ✅

---

## 진행 로그

| 날짜 | 내용 |
|------|------|
| 2026-03-28 | PRD 작성. |
| 2026-03-28 | M1~M5 구현: graph.py (DiGraph 래퍼), builder.py (BFS 확장 + 병렬 트리플 추출), build_causal.py (CLI), macro.py 연동, SKILL.md 갱신. |
| 2026-03-28 | 15토픽 테스트 빌드 검증: 88노드, 45트리플. 매크로 관점 인과 컨텍스트 주입 확인. |
