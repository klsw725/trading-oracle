# Trading Oracle v14 SPEC: Research Validation And Statistical Gates
> **상태**: ✅ 완료

v14는 [v12](../v12/SPEC.md)의 15개 전략과 [v13](../v13/SPEC.md)의 mixed router를 개발, validation, untouched holdout에서 평가하는 통계 계약이다. 결과를 본 뒤 기준을 바꾸거나 holdout을 반복 사용하는 것을 금지한다.

## 0. 구현 완결성 계약

- v14는 구현 완료된 v10 data manifests, v11 execution ledger, v12 strategy runs, v13 router runs만 의존한다.
- Development selection, validation gate, holdout one-shot, bootstrap, Holm, BH-FDR, manifest mismatch를 독립 research runner에서 end-to-end 실행해야 한다.
- `uv run python -m src.v14.cli acceptance`가 이전 버전 canonical fixtures와 v14 로컬 synthetic 12/6/6 cohort fixtures를 읽어 canonical JSON 보고서를 출력하고 exit 0이어야 한다.
- Acceptance는 PASS, REJECT_NO_EDGE, REJECT_COST_FRAGILE, REJECT_MULTIPLE_TESTING, INCONCLUSIVE, insufficient sample, invalid experiment를 모두 실행한다.
- v15 이후 디렉터리를 삭제하거나 아직 구현하지 않아도 v14 acceptance와 offline verdict 생성은 동일하게 동작해야 한다.
- Paper 운영이나 승격은 v14 완료 조건이 아니다. 동결 artifact와 verdict를 출력하면 v14의 책임은 끝난다.
- 이 조건과 아래 Acceptance Criteria가 모두 통과하면 v14 구현은 단독으로 완료다.

## Local PRD Map

| PRD | Local document | Implementation owner | Produces |
| --- | --- | --- | --- |
| PRD 01 | [Cohort And Development Selection](prds/prd01-cohort-development-selection.md) | 12/6/6 split, anchored folds, grid selection, pre-run manifest | frozen cohort, selection, experiment plan manifest |
| PRD 02 | [Metrics, Bootstrap, Cost Stress](prds/prd02-metrics-bootstrap-cost-stress.md) | Daily excess return, sample gates, CI, 2× cost | metric·CI·sample artifacts |
| PRD 03 | [Hypothesis And Verdicts](prds/prd03-hypothesis-verdicts.md) | ORB, Holm, BH-FDR, router hierarchy, verdicts | corrected verdict artifacts |
| PRD 04 | [Manifest, Holdout, Acceptance](prds/prd04-manifest-holdout-acceptance.md) | Manifest verification/finalization, one-shot holdout, version CLI | result manifest and acceptance report |

PRD 01→04 순서로 구현한다. PRD 04가 offline verdict를 출력하면 v14 책임은 끝나며 paper 운영은 완료 조건이 아니다.

## 1. 시장별 연구 cohort

KR과 US는 독립 cohort다. 각 시장은 연속된 24개월 point-in-time dataset을 다음 순서로 분리한다. Mixed-router cohort는 빈 자료 목록인 cutoff까지 포함해 v10 healthy context snapshot coverage가 전체 24개월에 연속적으로 존재해야 한다. Coverage gap을 quant-only나 행 삭제로 메우지 않는다.

| Segment | Length | Allowed use |
| --- | ---: | --- |
| Development | 12개월 | parameter와 NO_TRADE grid 선택 |
| Validation | 6개월 | 동결 버전 one-way gate |
| Untouched holdout | 6개월 | 승인 뒤 단 한 번 최종 평가 |

시장 간 데이터를 합쳐 한 시장의 표본 부족을 메우지 않는다. 기간 경계, calendar version, data manifest는 실험 manifest에 동결한다.

## 2. Development Walk-forward

12개월 개발구간은 다음 네 anchored fold를 사용한다.

- 첫 4개월로 설정하고 직후 2개월 평가
- 첫 6개월로 설정하고 직후 2개월 평가
- 첫 8개월로 설정하고 직후 2개월 평가
- 첫 10개월로 설정하고 직후 2개월 평가

전략별 최대 4개 parameter 조합과 router NO_TRADE 6개 조합은 이 fold 밖으로 확장할 수 없다. 시간순 OOS fold의 순비용 초과수익 중앙값이 가장 높은 조합을 선택한다. 비교 metric은 소수점 8자리 half-even quantize 뒤 정확히 같을 때 동률이며, 동률이면 turnover가 낮은 조합, 그래도 같으면 canonical ID 오름차순을 선택한다.

## 3. 비용과 체결 현실성

모든 segment는 [v11](../v11/SPEC.md)의 다음 조건을 그대로 적용한다.

- next-boundary execution과 stale signal cancellation
- 정수 주식, liquidity sizing, 실제 목표 분 기준 partial fill
- commission, tax, spread, slippage, borrow fee
- market-specific regulation, halt, recall, corporate action
- sector, correlation, gross, net, position-count risk

각 verdict는 baseline execution cost와 [v11](../v11/SPEC.md)이 정의한 2× execution-cost stress 결과를 함께 낸다. Spread, slippage, participation impact, borrow·locate 같은 모델링된 가변 비용만 2배로 하고 법정 세금과 계약상 고정 commission은 baseline 실액을 유지한다. 비용모델은 development 종료 후 validation·holdout에서 바뀌지 않는다.

## 4. Primary Metric

Primary metric은 비거래 기준선 대비 순비용 일별 초과수익이다. uncertainty는 거래일 의존성을 보존하는 사전등록 block-bootstrap 95% confidence interval로 계산한다.

- block rule과 seed는 결과 조회 전에 manifest에 고정한다.
- KR·US는 별도 CI를 가진다.
- 완료 거래 수, win rate, Sharpe, drawdown, turnover는 secondary metric이다.
- secondary metric이 primary 실패를 뒤집을 수 없다.
- 거래가 없던 날도 일별 series에서 임의 삭제하지 않는다.

Canonical block-bootstrap은 연속 5 공식 거래일 block, 10,000 resample, manifest에서 파생한 고정 seed를 사용한다. Paper paired 비교도 같은 block rule을 사용한다.

## 5. 최소 표본

시장별 untouched holdout verdict는 다음을 모두 충족해야 한다.

- 독립 신호일 100일 이상
- OOS 완료 거래 300건 이상

둘 중 하나라도 부족하면 `INCONCLUSIVE_INSUFFICIENT_SAMPLE`이다. 기간을 임의 연장해 같은 holdout 이름으로 결과를 덮어쓰지 않는다.

`독립 신호일`은 해당 시장 공식 세션에서 v12 `pre_portfolio_candidate`가 하나 이상 생성된 거래일이다. 즉 data·session·instrument·corporate-action·short borrow/regulation은 통과했지만 cash·slot·sector·correlation·gross·net·daily-loss 계좌 gate는 아직 적용하지 않은 stage다. 같은 날 candidate 수와 무관하게 하루로 센다. Data integrity 실패로 무효화된 날은 표본으로 세지 않고 무효 이유를 보고한다.

## 6. 다중검정 계층

1. v12 `long_orb_15m`은 사전 지정 primary hypothesis다.
2. 나머지 전략 family의 confirmatory 비교는 Holm correction을 사용한다.
3. 탐색적 secondary metric과 후보 발견 보고는 BH-FDR을 사용하고 confirmatory pass로 표시하지 않는다.
4. Mixed router는 구성 전략 gate 뒤에 위치한 계층형 hypothesis다.
5. Router는 ORB와 필요한 구성 후보가 각자의 선행 gate를 통과하기 전에 confirmatory 승격할 수 없다.
6. 시장별 분석을 별도 family로 보고 family 정의를 manifest에 고정한다.

전략의 confirmatory null hypothesis는 비거래 기준선 대비 순비용 일별 초과수익이 0 이하라는 것이다. v12 `long_orb_15m`은 primary로 단독 검사하고 나머지 14개 enabled 전략은 동일 시장 family 안에서 Holm 보정한다. Mixed router의 null hypothesis는 deterministic-only router 대비 paired 순비용 일별 초과수익이 0 이하라는 것이다. Validation을 통과한 enabled 후보 집합은 holdout을 열기 전에 `HoldoutPlan`에 동결한다. Holdout에서 구성 전략이 실패해도 같은 version에서 후보 subset을 다시 구성하거나 재실행하지 않는다.

One-sided bootstrap p-value는 `(1 + count(resampled_mean <= 0)) / (10000 + 1)`이다. 같은 시장의 비-ORB confirmatory p-value m개를 오름차순 정렬하고, i번째 값을 `0.05/(m-i+1)`과 순차 비교하는 Holm step-down을 적용한다. 최초 실패와 그 뒤 hypothesis는 correction 실패다. Validation과 holdout의 비-ORB `PASS`는 해당 segment sign·비용·CI 조건과 Holm reject를 모두 요구하며, correction 실패는 `REJECT_MULTIPLE_TESTING`이다. ORB primary와 선행 gate가 열린 mixed-router paired test는 각각 one-sided alpha 0.05를 사용한다.

Parameter grid 내부 선택은 development에만 존재하며 validation과 holdout에서 새 hypothesis를 만들지 않는다.

## 7. Verdict 규칙

### Validation gate

Validation은 최소 독립 신호일 60일과 OOS 완료 거래 150건을 요구한다. 무결성 오류가 0건이고 baseline 순수익과 2× cost 순수익이 모두 0보다 크며 primary metric 95% CI upper bound가 0보다 클 때 `VALIDATION_PASS`다. CI lower bound가 0보다 클 필요는 없으며, 이는 untouched holdout의 최종 역할을 보존한다. 표본 미달은 `VALIDATION_INCONCLUSIVE`이고 pass가 아니므로 holdout을 열 수 없다. Baseline 순수익이 0 이하이거나 CI upper bound가 0 이하이거나 2× cost 순수익이 0 이하이면 `VALIDATION_REJECT`다.

### Holdout verdict

최소 표본을 충족한 시장별 holdout에서:

| Condition | Verdict |
| --- | --- |
| Primary 95% CI lower bound > 0, baseline net return > 0, 2× cost net return > 0 | `PASS` |
| Primary 95% CI upper bound <= 0 | `REJECT_NO_EDGE` |
| 2× cost net return <= 0 | `REJECT_COST_FRAGILE` |
| 그 밖의 CI가 0을 포함 | `INCONCLUSIVE` |
| 최소 표본 미달 | `INCONCLUSIVE_INSUFFICIENT_SAMPLE` |
| data·manifest·replay 무결성 실패 | `INVALID_EXPERIMENT` |

`PASS`는 다음 단계 검토 자격이지 live trading 허가가 아니다.

## 8. Validation과 Holdout 오염 방지

- Development 종료 시 code, config, parameters, risk, router, universe, calendar, data, source, cost, prompt, model, schema, seed를 동결한다.
- Validation 실패 버전은 종료한다.
- 실패한 validation 데이터는 이후 새 실험의 development 데이터로만 편입할 수 있다.
- 같은 validation 구간에서 수정 버전을 반복 평가하지 않는다.
- Validation 실패 뒤 untouched holdout을 열지 않는다.
- Holdout은 validation 통과와 운영자의 hash·기간·비용모델 수동 승인 뒤 단 한 번 실행한다.
- Holdout 결과를 본 뒤 같은 version을 재튜닝하거나 재평가하지 않는다.

## 9. Experiment Manifest

하나의 실험 version은 다음 전체 실행 계약의 canonical hash다.

- code commit과 dirty-worktree 상태
- runtime과 dependency lock
- config와 feature flags
- strategy·parameter·risk·router version
- universe와 eligibility snapshot chain
- market calendar와 corporate action version
- raw·normalized·derived data manifests
- source provenance와 fallback history
- baseline·2× cost model
- prompt canonical bytes, Codex model, output schema
- random seeds와 bootstrap rule
- 기간 경계와 hypothesis family

하나라도 바뀌면 새 manifest hash와 새 실험 version이다. 결과 파일 hash만으로 실험 identity를 대체할 수 없다.

## 10. Router 검증

Mixed router도 전략과 동일한 development, validation, untouched holdout, 최소 표본, 비용 stress를 독립 통과해야 한다. ORB가 통과했다는 이유로 router가 자동 통과하지 않는다. LLM timeout·abstain·schema failure·circuit breaker가 실제 발생한 빈도와 quant fallback 성과를 숨기지 않는다.

Router 비교는 다음 arm을 최소한 포함한다.

- deterministic-only router
- 80:20 mixed router
- 비거래 기준선

LLM 소스, prompt, model, schema가 바뀌면 별도 router version이다.

## 11. Failure와 Mutation 계약

| Probe | Mutation | Required result |
| --- | --- | --- |
| `validation_tune` | validation 결과 뒤 threshold 변경 | invalid experiment |
| `holdout_repeat` | 같은 holdout 두 번째 실행 | holdout reuse failure |
| `cost_change` | holdout에서 cost model 갱신 | manifest mismatch |
| `sample_or` | 100일 또는 300거래 중 하나만 충족 | insufficient sample |
| `validation_undefined` | 60일·150거래 또는 validation sign gate 없이 holdout 개봉 | validation gate failure |
| `uncorrected_family` | 14개 전략에 보정 없는 p-value 사용 | multiple-testing failure |
| `context_gap_fill` | archive gap cutoff를 삭제하거나 quant-only로 대체 | cohort continuity failure |
| `secondary_override` | Sharpe로 primary reject 뒤집기 | verdict failure |
| `future_revision` | 미래 supersede를 과거 decision에 적용 | point-in-time failure |
| `manifest_partial` | prompt 또는 data hash 누락 | manifest failure |

## 12. Acceptance Criteria

- 시장별 24개월이 12/6/6으로 분리되고 segment 역할이 섞이지 않는다.
- 개발 fold는 4→2, 6→2, 8→2, 10→2개월로 고정된다.
- 전략별 최대 4개 grid와 router 6개 grid만 development에서 선택된다.
- primary metric, block-bootstrap CI, 100일·300거래, baseline·2×비용 verdict가 명시된다.
- Validation의 60일·150거래와 sign·CI upper-bound gate가 holdout 최종 verdict와 분리된다.
- ORB primary, Holm, BH-FDR, router 계층 gate가 분리된다.
- One-sided bootstrap p-value와 Holm step-down이 비-ORB PASS 판정에 직접 연결된다.
- Validation 실패와 holdout one-shot 규칙이 데이터 재사용을 통제한다.
- 전체 실행 계약 manifest 없이는 어떤 결과도 pass로 인정되지 않는다.
- Offline runner와 로컬 12/6/6 fixtures만으로 이후 버전 없이 acceptance와 verdict 생성을 완료한다.
