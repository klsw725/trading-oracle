# PRD: Phase 12 — Granger 기반 인과추론 검증

> **SPEC 참조**: [SPEC.md §4 (인과추론 검증 엔진)](../SPEC.md#4-인과추론-검증-엔진--phase-12)
> **상태**: 🔲 미착수
> **우선순위**: P1 — Phase 11 완료 후 착수
> **선행 조건**: Phase 11 (매크로 시계열 수집) 완료

---

## 문제

v1의 인과 그래프(1,500 트리플)는 LLM이 생성한 "상식적 인과 관계"를 무검증으로 저장한다. "금리 인상 → 성장주 하락"이 실제로 데이터에서 관찰되는지 확인하지 않는다. 거짓 트리플이 프롬프트에 주입되면 LLM 분석 품질을 오히려 떨어뜨린다.

## 솔루션

인과 그래프의 트리플을 실제 시계열 데이터로 Granger Causality Test를 수행하여 검증한다. 검증 결과(p-value, lag, 방향 일치성)를 신뢰도로 태깅하고, 검증 통과 트리플만 프롬프트에 우선 주입한다.

---

## 마일스톤

### M1: 노드 → 시계열 매핑
- [ ] `src/causal/node_mapper.py` 생성
- [ ] 규칙 기반 매핑 (핵심 50~100개 노드 → 시계열 심볼) — §4-3 전략 A
- [ ] `data/node_series_map.json`에 매핑 저장
- [ ] 매핑률 보고: 전체 노드 중 매핑 가능 비율

**검증**: 매핑 파일 생성. 매핑된 노드 수 ≥ 50개. 매핑 정합성 수동 검토 (10개 샘플).

### M2: Granger Causality 검증 엔진
- [ ] `src/causal/verifier.py` 생성
- [ ] ADF test로 정상성 검사 → 비정상 시 차분 적용
- [ ] 매핑된 트리플 쌍에 대해 Granger test 실행 (maxlag=30)
- [ ] 최소 p-value의 lag를 optimal로 선택
- [ ] 방향 일치성 확인: relation(increases/decreases)과 상관 부호 비교
- [ ] Bonferroni correction 적용

**검증**: 매핑된 320쌍 중 실행 완료율 90%+. p-value + lag + direction_match 출력 확인.

### M3: 신뢰도 태깅 및 저장
- [ ] 검증 결과를 트리플에 태깅 (§4-4 형식)
- [ ] `data/causal_graph_verified.json` 저장
- [ ] 상태 분류: verified / failed / unmappable
- [ ] 검증 통계 메타데이터 포함

**검증**: verified JSON 파일 생성. 메타데이터의 수치가 실제 검증 결과와 일치.

### M4: 프롬프트 주입 변경
- [ ] `macro.py`의 `_get_causal_context()`가 검증된 그래프를 우선 로드
- [ ] confidence ≥ 0.5인 트리플만 "데이터 검증됨" 섹션에 주입
- [ ] 미검증 트리플은 "참고용" 섹션에 축소 주입
- [ ] 검증된 그래프 없으면 v1 동작 유지 (graceful degradation)

**검증**: 프롬프트에 검증/미검증 섹션이 분리되어 있음. confidence 0.3 트리플이 검증됨 섹션에 없음.

### M5: CLI 통합
- [ ] `scripts/verify_causal.py` 생성 — 검증 실행 + 결과 조회
- [ ] `uv run scripts/verify_causal.py --json` → 검증 통계 출력
- [ ] `uv run scripts/verify_causal.py --detail` → 개별 트리플 검증 결과
- [ ] SKILL.md 갱신

**검증**: 스크립트 실행 → JSON 출력 파싱 가능. `--json` 형식 준수.

---

## 의존성

- `statsmodels`: ADF test + Granger Causality test. 신규 의존성.
- Phase 11의 `data/macro_series.parquet`: 매크로 시계열
- 기존 `data/causal_graph.json`: v1 트리플 원본

## 비용

- LLM (전략 B 자동 매핑): ~$0.50 (1회성, 선택적)
- 연산: 수 초 (statsmodels, ~320쌍)
- 저장: ~500KB

## 리스크

- **매핑 불가 노드**: "반도체 수요 증가" 같은 추상 노드는 단일 시계열로 대리 불가. 검증 범위 한계.
- **Spurious Granger**: 공통 원인이 있는 두 변수가 Granger test를 통과할 수 있음. 다중 비교 보정으로 완화.
- **구조 변화**: 2020 코로나, 2022 금리 급등 등 구조 변화 시기에 Granger 관계가 역전될 수 있음. Rolling window 검증은 v3 범위.
