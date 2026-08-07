# Trading Oracle v6: Perspective Expansion
> **상태**: ✅ 구현 완료 (PRD 01~04, 4/4 완료)

v6는 새 투자 관점 후보를 기존 다섯 관점과 같은 힘으로 바로 넣지 않고, 독립 가설, 오프라인 검증, paper 관찰, 제한된 lifecycle 정책으로 나누어 다룬다. 핵심 흐름은 `candidate->evaluation->paper->lifecycle`이다.

이 SPEC은 v6 로컬 PRD 01부터 PRD 04만 종합한다. v4, v5, v7, v8, v9 SPEC의 작성 상태, gate 결과, 구현 여부는 v6 판단 입력이 아니다.

## PRD 연결

| PRD | 문서 | 상태 | SPEC에서 맡는 역할 |
| --- | --- | --- | --- |
| PRD 01 | [prd01-perspective-candidate-contract.md](prds/prd01-perspective-candidate-contract.md) | ✅ 구현 완료 | 후보 목적, 독립 가설, 입출력 schema, 중복 금지, 비용과 latency 예산, owner와 version 계약 |
| PRD 02 | [prd02-offline-evaluation.md](prds/prd02-offline-evaluation.md) | ✅ 구현 완료 | 고정 데이터셋, baseline 비교, incremental lift, error correlation, calibration, N/A, cost, ablation 판정 |
| PRD 03 | [prd03-paper-cohort.md](prds/prd03-paper-cohort.md) | ✅ 구현 완료 | shadow verdict, production isolation, deterministic assignment, ledger, drift, stop condition, contamination 차단 |
| PRD 04 | [prd04-consensus-lifecycle.md](prds/prd04-consensus-lifecycle.md) | ✅ 구현 완료 | 제한 승격, capped weight, deliberation 권한, rollback, retirement, version coexistence, audit policy |

## 문제

현재 합의기는 `kwangsoo`, `ouroboros`, `quant`, `macro`, `value` 다섯 관점을 고정 순서로 실행한다. 새 관점 후보가 단순히 표를 하나 늘리면 합의가 더 좋아 보일 수 있지만, 실제 정보량은 늘지 않을 수 있다. 특히 기존 quant 신호를 다시 가중하거나 value threshold만 바꾸는 후보는 사용자에게 독립 판단처럼 보이지만, 같은 오류를 반복한다.

v6는 새 관점을 막기 위한 문서가 아니다. 좋은 후보가 실제로 기존 관점의 실패를 설명하고, 비용을 지키며, 사용자 표면을 오염시키지 않고, 제한된 영향으로 되돌릴 수 있는지를 확인하는 통로다.

## 기존 다섯 관점 기준선

| 관점 | 현재 목적 | v6 후보가 피해야 할 중복 |
| --- | --- | --- |
| `kwangsoo` | 추적 손절매, 주도주, 모멘텀, 자금관리 | 손절가, 추세 추종, 2 percent 자금관리만 반복 |
| `ouroboros` | 희석, 내부자 거래, 기관 수급, 재무 리스크 | 포렌식 리스크 목록의 재배열 |
| `quant` | 코드 기반 6 시그널 verdict와 LLM reasoning | RSI, MACD, EMA, BB, momentum 투표 재가중 |
| `macro` | 금리, 환율, 섹터 사이클, 인과 체인 | 같은 macro 변수와 기존 인과 그래프 설명 반복 |
| `value` | PER, PBR, 배당, 상대 valuation | 같은 valuation threshold만 조정 |

새 후보는 기존 관점과 일부 입력을 공유할 수 있다. 다만 주 판단의 핵심 관측값과 실패 설명은 달라야 한다.

## 통합 흐름

```text
candidate proposal
  -> PRD 01 candidate contract parser
  -> accepted for offline evaluation or rejected as duplicate
  -> PRD 02 frozen offline evaluation
  -> pass, reject, or inconclusive
  -> PRD 03 paper cohort shadow run
  -> ready for lifecycle review, reject, inconclusive, or contamination stop
  -> PRD 04 limited consensus lifecycle
  -> capped production participation, rollback, renewal review, retirement, or rejection
```

각 전이는 같은 `candidate_id`, `candidate_version`, `hypothesis_id`를 따라야 한다. 값이 바뀌면 새 후보 version으로 시작한다.

## 양방향 handoff 계약

| 생산자 | 산출물 | 소비자 | 역방향 검증 |
| --- | --- | --- | --- |
| prd01 | `candidate_proposal`, overlap matrix, budget, owner, version | prd02 | PRD 02는 같은 후보 id와 version이 없거나 PRD 01 rejection code가 있으면 evaluation을 만들지 않는다. |
| prd02 | `PASS_OFFLINE_EVALUATION`, lift, correlation, calibration, N/A, cost report | prd03 | PRD 03은 pass가 아닌 code, high correlation clone, missing outcome adapter success claim을 paper run 입력으로 받지 않는다. |
| prd03 | `STOP_READY_FOR_LIFECYCLE_REVIEW`, paper metrics, isolation proof, ledger hashes | prd04 | PRD 04는 ready stop code가 없거나 contamination event가 있으면 limited production을 막는다. |
| prd04 | lifecycle event, policy artifact, rollback pointer, active version rule | prd01 to prd03 audit refs | Replay와 audit은 어떤 후보 version이 어떤 upstream evidence를 근거로 capped weight를 받았는지 되짚을 수 있어야 한다. |

Forward handoff는 다음 문서가 읽는 최소 입력을 고정한다. Backward verification은 downstream 문서가 upstream 증거를 다시 확인하고, 누락이나 변조가 있으면 pass처럼 보이는 문구를 거절한다.

## 사용자 시나리오

### 1. 독립 후보가 제한 승격까지 가는 경우

Research owner가 `working_capital_quality` 후보를 제안한다. 후보는 운전자본 악화가 가격 모멘텀보다 먼저 이익 품질 저하를 드러낸다는 가설을 낸다. PRD 01 parser는 후보가 `quant`와 `value`의 BUY를 HOLD 또는 SELL로 낮출 수 있다는 disagreement를 확인하고, overlap ceiling과 예산을 통과시켜 오프라인 평가 대상으로만 접수한다.

PRD 02는 고정 holdout에서 baseline 대비 lift, target error lift, harm rate, error correlation, calibration, N/A rate, latency를 계산한다. 결과가 `PASS_OFFLINE_EVALUATION`이면 이는 production 채택이 아니라 paper 관찰로 넘어갈 수 있다는 뜻이다.

PRD 03은 실제 추천 입력을 보되 후보 verdict를 shadow로만 기록한다. 생산 `perspectives`, `vote_summary`, `consensus_verdict`, portfolio sizing, user output은 후보 실행 전후가 같아야 한다. Paper run이 최소 기간과 표본, drift, outcome, isolation 조건을 만족하면 `STOP_READY_FOR_LIFECYCLE_REVIEW`로 닫힌다.

PRD 04는 운영자 승인을 받은 뒤에만 제한 승격을 허용한다. `initial_weight`는 `0.25` 이하이고, 전체 유효 weight share는 `0.05` 이하이며, approval은 최대 60 market sessions다. 후보 reasoning은 별도 승인 전까지 기존 관점 prompt에 다수 압력으로 들어가지 않는다. 오류율, N/A, latency, parser failure, weight cap, dirty policy 문제가 생기면 rollback pointer로 되돌린다.

사용자는 새 후보가 충분한 증거를 쌓기 전에는 아무 변화를 보지 않는다. 제한 승격 뒤에도 사용자는 기존 다섯 관점이 갑자기 교체된 것이 아니라 capped candidate가 audit 가능한 정책 아래 작은 영향만 갖는다는 사실을 추적할 수 있어야 한다.

### 2. 중복 후보가 거절되는 경우

`quant_plus` 후보가 기존 6 시그널에 RSI와 MACD 가중치를 더해 BUY 정확도를 높인다고 주장한다. PRD 01은 핵심 입력이 `signals.rsi.value`, `signals.macd.histogram`, `signals.bull_votes`에 몰려 있고 quant overlap ceiling을 넘으므로 `DUPLICATES_EXISTING_PERSPECTIVE`로 거절한다.

이 후보가 오프라인 평가로 새어 들어가도 PRD 02는 `max_error_correlation >= 0.80` 또는 `max_verdict_correlation >= 0.90`이면 positive lift를 무시하고 `REJECT_HIGH_CORRELATION_CLONE`으로 닫는다. PRD 03 paper cohort와 PRD 04 lifecycle은 이 후보를 입력으로 받지 않는다.

## 핵심 계약

### Candidate contract

후보 제안은 목적, 독립 가설, 입력, 출력, overlap, budget, owner, version을 가진다. `PerspectiveResult`와 호환되는 `perspective`, `verdict`, `confidence`, `reasoning`, `reason`, `action`, `extra`를 내야 하며, `N/A`는 confidence `0.0`과 action `none`을 가진다.

Budget 초과, 필수 입력 부재, parser 실패, timeout은 BUY, SELL, HOLD로 숨기지 않는다. 해당 sample은 `N/A`로 닫힌다.

### Offline evaluation

평가는 outcome을 보기 전에 고정한 manifest만 쓴다. Baseline은 기존 합의, 가장 가까운 기존 관점, 동등 가중 기존 다섯 관점으로 나뉜다. 후보는 전체 holdout과 target error cohort에서 lift를 보여야 하며, high correlation clone이면 lift가 좋아도 거절된다.

Calibration은 confidence가 맞을 확률인지 본다. N/A와 coverage, latency, cost, ablation, 최소 표본이 함께 판정된다. 표본이 부족하거나 outcome adapter가 없으면 inconclusive다.

### Paper cohort

Paper는 실제 입력을 보지만 생산 vote에 영향을 주지 않는다. Assignment는 candidate id, version, production decision id, emitted time, ticker, market, policy salt로 deterministic하게 계산한다. Ledger는 append-only이며 hash chain으로 검증한다.

Shadow verdict가 production vote, scorer, deliberation, portfolio output, adaptive weight, prompt tuning, user output에 닿으면 contamination이다. Contamination은 후보 품질과 무관하게 lifecycle 검토를 막는다.

### Consensus lifecycle

Limited production은 영구 편입이 아니다. 후보 version마다 lifecycle record가 있고, 같은 candidate id의 active scorer version은 하나만 허용된다. PRD 04 compiler는 promotion, expiry/review, incident, renewal, rollback, retirement assessment, retirement, reopen operation을 검증된 prior `LifecycleHistory` head에서만 append한다. 각 operation/key는 정확히 한 번만 commit되며 promotion creation/transition pair 외 payload replay는 금지된다. 불충분한 incident evidence는 immutable renewal-review policy로 닫고, rollback 뒤 reopen은 rollback이 보존한 source paper와 다른 최신 READY paper를 요구한다.

History identity는 hypothesis까지 포함하고 policy projection은 compiler에서 재도출한다. Caller-authored operation registry와 별도로 trusted `CompilerContext` persistence head를 compiler/build 경계에 주입하며 mismatch를 거절한다. Policy emission만 registry revision을 하나 증가시키고 prior head hash를 연결하며, non-emission은 head를 보존한다. Partial persistence는 hash-bound checkpoint action matrix로 복구하며 rollback을 promotion보다 우선하고, genesis initial promotion은 명시적 zero-head checkpoint로 재개한다. 다섯 retirement trigger와 만료된 renewal-review version의 atomic replacement를 지원한다. Source TTL은 promotion policy에 compiler-fixed 값으로 보존하고, source/falsification은 trusted context의 full typed self-validating artifacts와 exact candidate, hypothesis, source paper에 결합한다.

Rollback은 audit record를 지우지 않는다. Retirement 뒤 후보 version은 replay와 attribution을 위해 읽을 수 있지만 새 scorer weight, deliberation prompt, adaptive weight, prompt tuning, portfolio sizing, user output의 active guidance로 쓰지 않는다.

## 품질과 비용 gate

| 영역 | pass에 필요한 조건 | 실패 처리 |
| --- | --- | --- |
| 독립성 | falsifiable claim, novel signal family, overlap ceiling 이하 | duplicate 또는 no independent hypothesis rejection |
| Output schema | verdict enum, confidence range, N/A contract, owner와 version 존재 | malformed input rejection |
| Offline lift | holdout lift, target error lift, harm rate, baseline miss recovery 기준 충족 | no lift, harmful, insufficient, flaky, missing outcome 중 하나 |
| Clone 방지 | error correlation과 verdict correlation ceiling 이하 | high correlation clone rejection |
| Calibration | Brier, ECE, overconfident bucket 기준 충족 | reject 또는 inconclusive |
| Coverage | overall N/A와 target N/A ceiling 이하 | 제한 후보로만 보거나 inconclusive |
| Cost | PRD 01 budget 이하, p95 wall time 최대 6000 ms, timeout rate ceiling 이하 | `N/A`, drift stop, rollback 중 하나 |
| Paper isolation | production before와 after 동일, vote effect none, user visible false | contamination stop |
| Lifecycle blast radius | weight `0.25` 이하, total share `0.05` 이하, approval 60 sessions 이하 | parser failure 또는 rollback |
| Auditability | append-only event, hash chain, idempotent resume, rollback pointer | orphan, dirty policy, duplicate event rejection |

## 사용자 영향

| 사용자 관점 | v6가 보장해야 할 것 |
| --- | --- |
| 추천을 받는 사용자 | 후보가 paper인 동안 추천 verdict, consensus, action plan이 바뀌지 않는다. |
| 제한 승격 뒤 사용자 | 후보 영향은 capped weight로만 나타나며 기존 다섯 관점 교체처럼 표시되지 않는다. |
| 운영자 | 후보별 evidence, approval, policy version, rollback pointer, incident threshold를 확인할 수 있다. |
| 리뷰어 | duplicate rejection, offline lift, paper isolation, lifecycle policy를 같은 candidate id와 version으로 추적할 수 있다. |

## 성공 기준

1. v6는 새 후보를 기존 다섯 관점과 분리된 후보로 접수하고, 같은 candidate id, version, hypothesis id로 끝까지 추적한다.
2. 기존 다섯 관점의 생산 순서와 기본 의미는 paper 기간 동안 변하지 않는다.
3. 중복 후보는 PRD 01에서 거절되며, 새어 들어간 경우 PRD 02 high correlation rule로 다시 거절된다.
4. Offline pass는 paper 진입만 뜻하고, paper ready는 lifecycle 검토만 뜻하며, lifecycle approval은 capped limited production만 뜻한다.
5. Cost, latency, N/A, calibration, ablation, drift, incident 기준은 품질 metric과 함께 판정된다.
6. Shadow verdict는 user output, scorer, deliberation, portfolio, tuning에 영향을 주지 않는다.
7. Limited production은 rollback pointer, incident threshold, active version rule, audit event를 가진다.
8. Parser와 mutation 증거 없이 pass 문구만으로 v6 판단을 바꿀 수 없다.

## SPEC 검증 요구

Authoring QA는 다음을 확인해야 한다.

1. 이 파일과 PRD 01부터 PRD 04를 manual Read로 확인한다.
2. PRD 연결 table의 첫 열은 `PRD 01`, `PRD 02`, `PRD 03`, `PRD 04` 순서다.
3. 각 v6 PRD relative link는 이 파일에서 정확히 한 번만 나타난다.
4. 이 파일에는 전역 numbered planning label이 없다.
5. Draft metadata는 한 번만 있고, 채택이나 종료를 뜻하는 marker가 없다.
6. Happy promotion 시나리오는 candidate, evaluation, paper, lifecycle을 모두 지난다.
7. Duplicate rejection 시나리오는 PRD 01과 PRD 02 방어선을 모두 설명한다.
8. Parser probe는 malformed link, duplicate PRD row, missing PRD row, misleading status, stale upstream claim, missing mutation evidence를 실패로 분류한다.

## Mutation probe matrix

| probe | mutation | expected result |
| --- | --- | --- |
| `duplicate_prd_row` | PRD 연결 table에 `PRD 02`를 두 번 둔다. | parser failure |
| `missing_prd_link` | PRD 03 link를 제거한다. | parser failure |
| `malformed_prd_link` | PRD 04 link를 다른 filename으로 바꾼다. | parser failure |
| `misleading_adoption` | Offline pass를 production 채택으로 표현한다. | parser failure |
| `paper_vote_mutation` | Shadow verdict가 vote summary를 바꾼다고 쓴다. | parser failure |
| `duplicate_candidate_pass` | high correlation quant clone이 lift 때문에 pass한다고 쓴다. | parser failure |
| `missing_cost_gate` | 비용과 latency gate를 제거한다. | parser failure |
| `other_spec_dependency` | 다른 SPEC 작성 상태를 v6 pass 조건으로 둔다. | parser failure |
