# Trading Oracle v13 SPEC: Deterministic And LLM Strategy Router
> **상태**: 📝 초안

v13은 [v12](../v12/SPEC.md)의 실행 가능 strategy-symbol 후보 중 종목별 전략 하나를 선택하는 router 계약이다. 결정론적 점수 80%와 Codex 점수 20%를 사용하되, LLM은 후보·수량·가격·주문을 만들 수 없다.

## 0. 구현 완결성 계약

- v13은 구현 완료된 v10 context artifact, v11 execution contract, v12 execution-feasible candidate만 의존한다.
- Codex 정상 응답, timeout, abstain, item schema 오류, envelope 오류, veto, overflow, circuit breaker, quant-only fallback을 end-to-end 실행해야 한다.
- `uv run python -m src.v13.cli acceptance`가 이전 버전 canonical fixtures와 v13 로컬 Codex response fixtures를 읽어 canonical JSON 보고서를 출력하고 exit 0이어야 한다.
- Acceptance는 실제 credential이나 network 없이 recorded response fixtures로 전체 router·replay 경로를 검증한다. 별도 opt-in integration probe만 실제 지원 model ID를 확인할 수 있다.
- v14 이후 디렉터리를 삭제하거나 아직 구현하지 않아도 v13 acceptance와 router shadow run은 동일하게 동작해야 한다.
- 통계적으로 최적인 threshold 선택은 v13 완료 조건이 아니다. 로컬 `router_policy`가 명시한 허용 조합을 결정론적으로 실행할 수 있으면 된다.
- 이 조건과 아래 Acceptance Criteria가 모두 통과하면 v13 구현은 단독으로 완료다.

## Local PRD Map

| PRD | Local document | Implementation owner | Produces |
| --- | --- | --- | --- |
| PRD 01 | [Router Scoring And Policy](prds/prd01-router-scoring-policy.md) | Percentile, 80:20 score, NO_TRADE, total order | router policy and selection artifacts |
| PRD 02 | [Codex, Context, Schema](prds/prd02-codex-context-schema.md) | Batch call, context, output validation, prompt safety | prompt·response·validation artifacts |
| PRD 03 | [Switch, Fallback, Replay](prds/prd03-switch-fallback-replay.md) | Two-leg switch, quant fallback, circuit, immutable replay | switch·fallback·replay artifacts |
| PRD 04 | [Acceptance And Recorded Router](prds/prd04-acceptance-recorded-router.md) | Recorded response orchestration and mutation coverage | canonical acceptance report |

PRD 01→04 순서로 구현한다. PRD 04는 network와 credential 없이 앞 PRD를 검증하며 통계 threshold 선택은 완료 조건이 아니다.

## 1. 선택 단위와 흐름

```text
v12 candidates -> hard eligibility -> market batch snapshot
-> deterministic scoring -> Codex scoring -> validation
-> market-wide percentile -> 80:20 composite
-> per-symbol NO_TRADE/selection -> portfolio slot allocation
```

- KR·US는 독립 router cohort다.
- 매 5분 각 시장에서 종목별 전략 하나를 선택한다.
- 정량 엔진이 실제 진입 조건, v10 data, v11 risk·borrow를 통과한 후보만 LLM 입력이 된다.
- 시장별 한 번의 batch 호출에서 실행 가능 후보 전체를 평가한다.
- 실행 가능 후보가 고정 input budget을 넘으면 후보를 자르지 않고 해당 시장·cutoff 전체를 정량 100%로 전환한다.

## 2. 점수 계약

각 candidate는 `deterministic_score`와 `llm_score`를 가진다. 동일 시장·동일 cutoff의 모든 실행 가능 strategy-symbol 후보를 모집단으로 각 점수를 0~1 percentile rank로 변환한다.

Percentile은 오름차순 midrank를 사용한다. 모집단 크기 `n > 1`이면 `(midrank - 1) / (n - 1)`, `n = 1`이면 `1.0`이다. 모든 값이 동률이면 각 후보는 `0.5`다. Hard veto가 검증된 후보는 두 component의 percentile 모집단에서 제거한 뒤 rank를 다시 계산한다.

```text
composite_score = 0.80 * deterministic_percentile
                + 0.20 * llm_percentile
```

한 candidate라도 abstain하거나 개별 항목 validation에 실패하면 그 symbol의 모든 candidate를 정량-only로 전환한다. 정량-only composite는 `deterministic_percentile` 자체이며 0.80을 다시 곱하지 않는다. Confidence는 합성점수에 반영하지 않고 calibration·drift 분석용으로만 보존한다.

합성점수 동률은 다음 순서로 결정한다.

1. deterministic percentile 높은 후보
2. 예상 turnover 낮은 후보
3. strategy ID 오름차순

`expected_turnover`는 v11 causal sizing reference에서 계산한 `abs(target_signed_quantity-current_signed_quantity) * reference_price / previous_close_NAV`다. 비교 metric은 소수점 8자리 half-even quantize 뒤 정확히 같을 때만 동률이다. Per-symbol 선택 뒤 portfolio slot total order는 composite 내림차순, deterministic percentile 내림차순, expected turnover 오름차순, canonical symbol 오름차순, strategy ID 오름차순이다.

## 3. `NO_TRADE` 임계값

종목별 최고 후보는 최소 합성점수와 2위 대비 격차를 모두 통과해야 한다. 후보 조합은 다음 6개만 허용한다.

- 최소점수: 0.70, 0.80, 0.90
- 최소격차: 0.05, 0.10

v13 로컬 `router_policy`는 위 6개 중 정확히 한 조합과 policy hash를 run 전에 고정한다. 별도 선택 artifact가 없을 때 canonical default는 최소점수 0.80, 최소격차 0.05다. Acceptance는 6개 조합을 모두 fixture로 실행한다. Threshold 미달, 격차 미달, 실행 가능 후보 없음, stale·불완전 데이터, risk·borrow 차단은 모두 명시적 `NO_TRADE`다.

후보가 하나뿐이면 2위 격차 조건은 충족한 것으로 보되 최소점수는 그대로 적용한다. Quant-only symbol과 시장 전체 quant fallback에도 동일한 최소점수·격차 grid를 적용한다.

## 4. Codex 실행 계약

- Provider는 Codex 단일 모델이다.
- 실제 계정에서 지원되는 model ID를 확인한 뒤 model·prompt·schema version을 실험 동안 고정한다.
- 5분봉마다 시장별 최대 한 번 batch 호출한다.
- timeout은 20초이며 재시도하지 않는다.
- timeout 또는 전체 실패는 해당 시장·cutoff를 정량 100%로 전환한다.
- model ID를 provider와 맞지 않는 이름으로 설정해서는 안 된다.
- 호출 중 웹, 검색, 파일, 추가 tool 접근은 금지한다.

## 5. Structured Output

LLM은 입력으로 받은 candidate마다 다음 필드만 반환할 수 있다.

| Field | Rule |
| --- | --- |
| `candidate_id` | 입력 후보와 정확히 일치 |
| `score` | 유한한 0~1 decimal |
| `veto_code` | 허용 enum 또는 null |
| `abstain` | boolean |
| `confidence` | 0~1, 기록·분석 전용 |
| `source_artifact_ids` | 입력 snapshot에 있던 ID만 참조 |
| `reason` | 길이가 제한된 비명령형 설명 |

Ticker 생성, 수량, 가격, order type, 주문 instruction, 새로운 strategy ID는 schema에서 금지한다.

개별 candidate 항목의 score·필드 오류는 해당 symbol만 정량 전환한다. 중복 ID, 알 수 없는 candidate, cutoff mismatch, prompt hash mismatch, batch identity 오류는 envelope 무결성 실패이므로 시장 전체를 정량 전환한다. Parser가 누락이나 형식을 추정 보정해서는 안 된다.

## 6. Veto와 Abstain

Hard veto는 다음 조건을 모두 만족할 때만 적용한다.

1. 사전 정의된 규제, 거래정지, 상장폐지, 파산, 중대 corporate action code다.
2. 해당 사실을 직접 뒷받침하는 입력 `source_artifact_id`가 있다.
3. artifact의 published_at과 observed_at이 cutoff 이전이다.
4. deterministic validator가 code와 artifact 관계를 확인한다.

그 밖의 veto는 분석용으로 기록하지만 후보를 차단하지 않는다. `abstain=true`인 symbol은 NO_TRADE가 아니라 정량 100% 경로로 전환한다.

## 7. Point-in-time 자료

각 호출은 v10 `context_artifact`에서 만든 다음 snapshot만 읽는다.

- 뉴스: cutoff 이전 24시간
- 공시, 기업행사, 규제자료: cutoff 이전 7일 안에서 아직 유효한 artifact
- published_at과 observed_at이 모두 5분봉 cutoff 이전
- immutable content hash와 provenance가 검증된 자료

최초 historical evaluation은 archival source가 cutoff 당시 `observed_at`을 증명한 context corpus로 Codex를 한 번 호출해 immutable scoring artifact를 만든다. 이후 같은 experiment replay는 저장된 원본 응답을 사용한다. 증명 가능한 context corpus가 없는 historical cutoff에 현재 수집한 문서를 소급 주입하지 않는다.

입력 한도 선별 순서는 다음과 같다.

1. 종목 직접 관련
2. sector 관련
3. 시장 전체 관련
4. 같은 범위에서는 공식자료
5. 검증 뉴스
6. 최신 시각
7. artifact ID 오름차순

## 8. Prompt Injection 경계

- HTML, script, style, hidden element를 제거하고 canonical text로 정규화한다.
- 외부 본문은 명시적 untrusted-data 구역에 격리한다.
- instruction-like pattern이 탐지된 artifact는 LLM 입력에서 제외하고 incident를 기록한다.
- 공식 출처도 trusted instruction으로 승격하지 않는다.
- System prompt만으로 외부 지시를 무시할 것이라고 가정하지 않는다.

## 9. Position Switch

보유 symbol에 더 높은 challenger가 생겨도 최소 15분 동안 incumbent를 유지한다. Incumbent 비교점수는 진입을 결정한 cutoff의 immutable composite score다. 그 뒤 현재 challenger composite score가 그 frozen incumbent score보다 0.10 이상 높을 때만 교체한다.

- 같은 방향도 기존 포지션 청산 후 재진입한다.
- 반대 방향도 청산 완료와 risk 재검사 뒤 신규 진입한다.
- 1단계는 switch 결정 후 최초 1분 경계에 incumbent 청산을 시도한다. 그 경계를 놓치거나 전량청산되지 않으면 challenger 진입 없이 switch를 종료하고 잔여 incumbent를 유지한다.
- 전량청산 reconciliation이 끝나면 flat 상태에서 모든 risk를 다시 계산하고, 그 다음 최초 1분 경계에 challenger 신규 진입을 시도한다.
- 2단계 경계를 놓치거나 신규 주문이 거부·미체결되면 flat 상태를 유지하며 과거 incumbent를 복원하지 않는다.
- 각 leg는 [v11](../v11/SPEC.md)의 비용과 liquidity를 독립 적용한다.
- 단순 strategy owner 변경이나 pyramiding은 허용하지 않는다.

## 10. Fallback와 Circuit Breaker

다음은 정량 100% fallback 원인이다.

- timeout, provider error, authentication error
- input budget overflow
- envelope schema 또는 identity failure
- model·prompt·schema version mismatch
- artifact cutoff 또는 hash failure

Codex 실패가 3회 연속이거나 최근 20회 중 20% 이상이면 해당 시장의 남은 세션 동안 LLM arm을 비활성화한다. 다음 정규장에서 자동 재시험하며, 반복 실패 사실과 fallback 비율을 숨기지 않는다.

## 11. Replay

당시 prompt canonical bytes, prompt hash, model ID, prompt version, schema version, source artifact IDs, raw response, parsed response, validation report, fallback decision을 immutable하게 저장한다. 과거 replay는 Codex를 다시 호출하지 않고 당시 원본 응답을 재사용한다. 현재 모델 재호출은 별도 drift 연구일 뿐 체결 replay가 아니다.

## 12. Failure와 Mutation 계약

| Probe | Mutation | Required result |
| --- | --- | --- |
| `invented_candidate` | 입력에 없던 ticker·strategy 반환 | market cutoff fallback |
| `order_instruction` | 수량·가격·주문 반환 | schema failure |
| `future_news` | observed_at이 cutoff 이후 | artifact rejection |
| `partial_item_bad` | 한 항목 score 범위 오류 | 해당 symbol quant-only |
| `duplicate_id` | candidate ID 중복 | market cutoff fallback |
| `unbounded_batch` | input budget 초과 후보 자르기 | overflow contract failure |
| `confidence_weight` | confidence로 20% 비중 변경 | score contract failure |
| `unproven_veto` | artifact 없는 hard veto | veto ignored, incident logged |
| `replay_recall` | replay에서 Codex 재호출 | replay failure |
| `rank_tie_drift` | 동률에 다른 percentile 알고리즘 사용 | scoring failure |
| `single_candidate_gap` | 하나뿐인 후보를 gap 미달로 처리 | NO_TRADE contract failure |
| `slot_tie_nondeterministic` | symbol tie-break 없이 reservation 순서 변경 | allocation failure |
| `switch_same_boundary` | 청산 reconciliation 전 challenger 진입 | switch sequencing failure |

## 13. Acceptance Criteria

- 종목별 하나의 전략을 선택하되 LLM은 실행 가능 후보 밖의 신호를 만들지 못한다.
- 시장·cutoff 전체 후보 percentile과 80:20 가중치가 고정된다.
- Midrank, 동률, 단일 후보, veto 제거, symbol quant-only의 순서가 결정론적이다.
- NO_TRADE는 허용된 6개 조합만 지원하며 로컬 `router_policy`가 run 전에 하나를 동결하고 acceptance가 6개를 모두 검증한다.
- Codex 단일 모델, 20초, no retry, no tools, quant fallback이 명시된다.
- confidence, veto, abstain, 부분 schema 오류의 역할이 분리된다.
- 뉴스 24시간, 공시 7일, published·observed cutoff, injection 격리를 지킨다.
- 원본 LLM 응답 replay와 circuit breaker를 재현할 수 있다.
- 로컬 canonical router policy와 recorded Codex fixtures만으로 이후 버전 없이 acceptance를 통과한다.
