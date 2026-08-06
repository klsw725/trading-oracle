# Trading Oracle v4 - Measurement & Attribution
> **상태**: 📝 초안

> 이전 기준: [v1 다관점 SPEC](../multi-perspective/SPEC.md), [v2 SPEC](../v2/SPEC.md), [v3 SPEC](../v3/SPEC.md), [Recommendation Pipeline SPEC](../recommend/SPEC.md), 초기 성과 추적 PRD

v4는 추천 품질을 다시 측정하기 위한 계약이다. v3의 자가 학습과 Recommendation Pipeline의 넓은 후보군 선택은 계속 중요하지만, 기존 성과 데이터는 추천 이후 N번째 거래 session 성과를 보장하지 못한다. v4는 측정, snapshot, legacy audit, market context, attribution, replay, calibration, evidence gate를 한 줄로 연결해 이후 개선이 잘못된 숫자 위에 쌓이지 않게 한다.

v4는 v5-v9 completion dependency 없음. v5부터 v9까지 문서 상태나 게이트 상태는 v4의 pass, fail, inconclusive를 바꾸지 않는다.

## PRD 연결

| Phase | PRD | 상태 | 설명 |
| --- | --- | --- | --- |
| Phase 22 | [phase22-measurement-contract.md](prds/phase22-measurement-contract.md) | 📝 초안 | 추천 다음 동일 시장 정규 session 종가를 entry로 쓰고, entry 이후 N번째 session 종가를 exit로 쓰는 측정 계약 |
| Phase 23 | [phase23-snapshot-reproducibility.md](prds/phase23-snapshot-reproducibility.md) | 📝 초안 | data cutoff, source freshness, prompt, raw result, parser, candidate audit, portfolio state를 보존하는 native v4 snapshot 계약 |
| Phase 24 | [phase24-legacy-backfill.md](prds/phase24-legacy-backfill.md) | 📝 초안 | 기존 82개 snapshot을 수정하지 않고 audit-only derived artifact로 분리하는 legacy 정책 |
| Phase 25 | [phase25-market-context-separation.md](prds/phase25-market-context-separation.md) | 📝 초안 | KR과 US의 calendar, timezone, benchmark, currency, FX, regime source를 분리하는 market context 계약 |
| Phase 26 | [phase26-recommendation-attribution.md](prds/phase26-recommendation-attribution.md) | 📝 초안 | BUY, SELL, HOLD, BLOCKED, CANDIDATE_REJECTED denominator와 append-only attribution ledger 계약 |
| Phase 27 | [phase27-full-workflow-replay.md](prds/phase27-full-workflow-replay.md) | 📝 초안 | verbatim, outcome, recompute replay를 분리하고 full workflow state machine을 검증하는 replay 계약 |
| Phase 28 | [phase28-hold-confidence-calibration.md](prds/phase28-hold-confidence-calibration.md) | 📝 초안 | HOLD를 new trade none으로 고정하고 confidence를 action별 correctness event 확률로 보정하는 calibration 계약 |
| Phase 29 | [phase29-evidence-gate.md](prds/phase29-evidence-gate.md) | 📝 초안 | measurement, snapshot, migration, attribution, replay, calibration 증거와 review matrix를 v4 gate로 묶는 evidence 계약 |

## 문제

초기 성과 추적은 snapshot 날짜의 추천 가격과 실행 시점의 최신 종가를 비교한다. 그 결과 5일과 20일 결과가 같은 최신 가격을 소비할 수 있고, 추천 이후 N번째 거래 session 결과라는 뜻을 보장하지 못한다. HOLD도 단순 deadband 안에 있으면 맞았다고 처리되어, 새 거래를 만들지 않는 결정이라는 의미가 흐려진다.

v3는 적중 패턴, 레짐별 가중치, 프롬프트 자가 튜닝을 전제로 한다. Recommendation Pipeline은 넓은 universe, diversified selection, BUY 합의, sizing visibility를 만든다. 하지만 둘 다 올바른 denominator와 재현 가능한 입력이 없으면 선택 편향을 키울 수 있다. v4는 이 두 흐름이 성과를 배웠다고 말하기 전에, 무엇을 언제 추천했고 무엇이 탈락했으며 어떤 가격과 benchmark로 평가했는지 먼저 고정한다.

## v3와 Recommendation Pipeline에서 v4로 바뀌는 점

| 영역 | v3 또는 Recommendation Pipeline | v4 |
| --- | --- | --- |
| 성과 기준 | legacy hit rate와 레짐별 적중률 중심 | gross benchmark excess return을 primary decision-quality metric으로 사용 |
| entry와 exit | snapshot 가격과 최신 조회 가격을 섞을 수 있음 | 추천 이후 다음 동일 시장 정규 session 종가가 entry, entry 이후 N번째 session 종가가 exit |
| net 지표 | 성과 판단과 실행 품질이 섞일 수 있음 | net execution return은 secondary execution metric으로만 표시 |
| 후보 denominator | 최종 BUY 또는 분석 대상 위주로 보일 수 있음 | BUY, SELL, HOLD, BLOCKED, CANDIDATE_REJECTED를 모두 보존 |
| legacy snapshot | 적중률과 학습 입력으로 쓰일 수 있음 | 기존 82개 snapshot은 audit-only이며 canonical v4 metric과 calibration에서 제외 |
| market context | KOSPI context가 US 분석에 직접 섞일 수 있음 | exchange별 benchmark와 regime source를 분리하고 오염 field를 blocked로 닫음 |
| confidence | `high`, `moderate` 같은 표시 label 중심 | `confidence_probability`를 correctness event의 확률로 해석 |
| HOLD | 가격이 작게 움직이면 적중으로 보기 쉬움 | HOLD는 `new trade none`, opportunity cost와 avoided loss로 평가 |
| replay | signal-only backtest 중심 | full workflow replay는 signal-only backtest와 별도 layer |

## 사용자 시나리오

### 1. 추적 가능한 추천 happy path

사용자가 한국 시장 추천을 요청한다. Recommendation Pipeline은 KR universe를 넓게 확보하고, diversified selection과 signal filter를 거쳐 삼성전자 `005930`을 분석 대상으로 올린다. 다섯 관점은 고정 순서로 parsed result를 남기고, consensus는 BUY 강한 합의를 만든다. 추천은 `2026-06-02T10:32:10+09:00`에 사용자에게 노출된다.

v4는 이 추천을 다음처럼 추적한다.

1. Phase 23 snapshot이 `decision_at`, `emitted_at`, `decision_data_cutoff_at`, source freshness, prompt hash, parser version, candidate audit, portfolio state를 저장한다.
2. Phase 25 market context가 `KR`, `KOSPI`, `Asia/Seoul`, `KS11`, `KRW`, `decision_regime_source=KS11`을 고정한다.
3. Phase 22 measurement가 추천 다음 동일 시장 정규 session인 `2026-06-03` 종가를 entry로, entry 이후 다섯 번째 session인 `2026-06-10` 종가를 5-session exit로 쓴다.
4. Phase 26 attribution ledger가 `candidate_id`, `recommendation_id`, `RECOMMENDATION_EMITTED`, operator partial execution, order, fill, close, outcome event를 append-only로 연결한다.
5. Phase 27 outcome replay가 `gross_absolute_return_5=0.06`, `gross_benchmark_excess_return_5=0.03`, `net_execution_return_5=0.0569`, `net_execution_benchmark_excess_return_5=0.0269`을 서로 다른 denominator에 표시한다.
6. Phase 28 calibration은 이 BUY의 `confidence_probability`를 BUY correctness event의 확률로만 사용한다.
7. Phase 29 evidence gate는 manual Read, deterministic parser, mutation fixture, independent review가 모두 있을 때만 v4 gate state를 판정한다.

사용자는 같은 추천 화면에서 왜 이 종목이 선택됐는지, 어떤 후보가 탈락했는지, 언제 entry와 exit가 잡혔는지, benchmark 대비 얼마를 냈는지, 일부 체결이 execution metric에만 어떤 영향을 줬는지 볼 수 있어야 한다.

### 2. HOLD는 새 거래가 아님

사용자가 MSFT를 물었고 합의 결과가 HOLD라면 v4는 action plan을 `none`으로 기록한다. `portfolio_trade_id`, `order_ids`, `fill_ids`가 생기면 schema failure다. HOLD 결과는 opportunity cost와 avoided loss로만 평가하며 trading PnL을 만들지 않는다.

### 3. legacy 82개 snapshot 감사

기존 `data/snapshots/`의 82개 파일은 유용한 과거 흔적이지만 native v4 snapshot이 아니다. Phase 24는 원본을 바꾸지 않고, 별도 derived artifact에 direct, derived, external_backfill, unknown, not_applicable provenance를 남긴다. raw prompt, exact data cutoff, candidate universe, portfolio state가 없으면 unknown으로 남기며 canonical metric, calibration, adaptive weights에는 넣지 않는다.

### 4. 실패가 성공처럼 보이면 차단

최신 종가가 20-session exit를 대체하면 stale state failure다. US 종목에 KOSPI bear regime이 직접 들어가면 blocked context다. label-only confidence가 calibration에 들어가면 malformed input이다. missing migration coverage나 missing calibration report가 있는데 v4 release가 pass로 표시되면 misleading success output이다. 이런 실패는 v4만 닫고 v5부터 v9까지 상태는 바꾸지 않는다.

## 아키텍처와 데이터 흐름

```text
사용자 요청
  |
  v
Recommendation Pipeline
  | market scope, universe, selection, rejections
  v
Phase 23 native snapshot
  | timestamps, cutoff, source freshness, prompt, raw, parser, portfolio state
  v
Phase 25 market context
  | market, exchange, calendar, timezone, benchmark, currency, FX, regime
  v
Phase 22 measurement
  | next-session entry, N-session exit, gross absolute, gross benchmark excess, net execution secondary
  v
Phase 26 attribution ledger
  | candidate, recommendation, operator decision, order, fill, close, outcome, correction
  v
Phase 27 full workflow replay
  | verbatim replay, outcome replay, recompute replay, denominator report
  v
Phase 28 calibration
  | BUY, SELL, HOLD correctness events, probability calibration, no-op gate
  v
Phase 29 evidence gate
  | release manifest, review matrix, parser result, mutation result, gate decision
```

## Dependency diagram

```text
Phase 22 measurement contract
  -> Phase 25 market context separation
      -> Phase 23 snapshot reproducibility
          -> Phase 24 legacy backfill
          -> Phase 26 recommendation attribution
              -> Phase 27 full workflow replay
                  -> Phase 28 HOLD confidence calibration
                      -> Phase 29 evidence gate

v4 SPEC synthesis consumes Phase 22 through Phase 29.
v5 through v9 are outside the v4 evidence gate.
```

Phase 24 and Phase 26 both depend on Phase 23 but solve different problems. Phase 24 protects legacy audit evidence. Phase 26 preserves the native denominator for new recommendations. Phase 27 consumes both, but legacy can only appear as audit overlay, not as verbatim or recompute replay.

## 결정된 계약

### Measurement contract

| 항목 | 결정 |
| --- | --- |
| entry | 추천 이후 다음 동일 시장 정규 session 종가 |
| exit | entry 체결 session 이후 N번째 동일 시장 정규 session 종가 |
| 기본 horizon | `[5, 20]`, 추가 horizon은 양의 정수 N만 허용 |
| primary metric | `gross_benchmark_excess_return_N` |
| 보조 gross metric | `gross_absolute_return_N` |
| secondary execution metric | `net_execution_return_N`, `net_execution_benchmark_excess_return_N` |
| stale 방지 | 최신 조회 종가로 pending horizon을 채우지 않음 |
| corporate action | total-return series 우선, provenance 없으면 `insufficient_data` |

### Snapshot contract

Native v4 snapshot은 timestamp와 cutoff를 분리한다. `created_at`, `decision_at`, `recommendation_emitted_at`, `decision_data_cutoff_at`은 서로 다른 의미를 가진다. 각 recommendation은 market context, sources, candidate universe, selection, rejections, features, signals, provider/model/prompt/config/parser version, raw and parsed results, consensus, deliberation, portfolio state, risk state, quality states, section hashes를 가진다.

`available`, `unknown`, `degraded`, `blocked`, `not_applicable`은 first-class state다. 결측을 null이나 성공 값으로 덮지 않는다. Redaction은 prompt, raw provider output, config, portfolio, request free text가 hash되기 전에 먼저 실행된다.

### Legacy contract

기존 82개 snapshot은 source immutable이다. `data/snapshots/**`를 수정하거나 in-place migration하지 않는다. Derived output은 `data/derived/v4/legacy-backfill/**`에만 쓴다. Legacy derived record는 audit-only이고 `canonical_metric_eligible=false`, `calibration_eligible=false`다.

Backfill은 충분한 외부 provenance가 있을 때 outcome과 benchmark field만 채울 수 있다. Raw prompt, exact data cutoff, candidate audit, portfolio state, risk state는 추정하지 않고 unknown으로 남긴다.

### Market context contract

| exchange | benchmark | regime source | timezone | currency rule |
| --- | --- | --- | --- | --- |
| `KOSPI` | `KS11` | `KS11` | `Asia/Seoul` | KRW quote and KRW reporting |
| `KOSDAQ` | `KQ11` | `KQ11` | `Asia/Seoul` | KRW quote and KRW reporting |
| `KOSDAQ GLOBAL` | `KQ11` | `KQ11` | `Asia/Seoul` | KRW quote and KRW reporting |
| `NASDAQ` | `IXIC` | `IXIC` | `America/New_York` | USD quote and KRW reporting through USD/KRW |
| `NYSE` | `US500` | `US500` | `America/New_York` | USD quote and KRW reporting through USD/KRW |

Unsupported market or missing benchmark creates `insufficient_context` for benchmark excess while leaving gross absolute return separate when price provenance is enough. Stale or missing FX degrades mixed portfolio normalization, not quote return. US market-cap in `KRW_100M` is blocked for valuation-derived fields.

### Attribution contract

Action taxonomy is fixed to `BUY`, `SELL`, `HOLD`, `BLOCKED`, and `CANDIDATE_REJECTED`. All five belong to denominator reporting. Evaluation cannot shrink to executed BUY trades.

The attribution ledger is append-only. Corrections append new events and never mutate old event content. `candidate_id`, `recommendation_id`, `attribution_event_id`, `portfolio_trade_id`, `order_id`, and `correction_id` are deterministic IDs based on Phase 23 canonical JSON rules.

### Replay contract

| mode | purpose | provider call |
| --- | --- | --- |
| `verbatim` | retained raw input and parser output reproduce stored parsed output and hashes | forbidden |
| `outcome` | Phase 22 horizons mature price, benchmark, execution, selection, and risk outcomes | forbidden |
| `recompute` | same cutoff input is run through current provider/model/parser to inspect drift | allowed only with explicit opt-in budget |

Signal-only backtest remains a separate layer. Reporting signal-only backtest as full workflow replay is misleading success output.

### Calibration contract

Confidence means probability. `confidence_probability` is the model's predicted probability that the action-specific correctness event is true for a given horizon. `confidence_label` is display-only.

BUY, SELL, and HOLD never share correctness labels. HOLD is `new trade none`; its outcome is opportunity cost and avoided loss, not trade PnL. BLOCKED and CANDIDATE_REJECTED remain in denominator reports but are excluded from Phase 28 confidence calibration samples.

Calibration cohorts do not pool across contract version, snapshot schema version, attribution schema version, market, exchange, action, horizon, prompt bundle, scorer, weights, decision regime, or analysis regime. Sample shortage returns insufficient_sample no-op and cannot change adaptive weights, regime weights, prompt tuning, or consensus thresholds.

### Evidence contract

Phase 29 accepts only evidence artifacts with identity, schema version, producer tool, producer tool version, generated timestamp, input refs, content hash, tool config hash, and review refs. Worker self-report and grep hit cannot pass. Manual Read, deterministic parser, fixture mutation, independent review, and resume review are part of the gate.

## Implementation order

1. Implement Phase 22 first, because every later domain consumes entry, exit, horizon, state, and metric semantics.
2. Implement Phase 25 next, because measurement needs market, exchange, calendar, timezone, benchmark, currency, and regime context.
3. Implement Phase 23 snapshot before any native attribution or replay, because replay requires retained inputs and hashes.
4. Implement Phase 24 legacy audit as a read-only path, without touching existing snapshots.
5. Implement Phase 26 ledger after native snapshot shape is stable, preserving all five action cohorts.
6. Implement Phase 27 replay once snapshot and ledger references are stable.
7. Implement Phase 28 calibration only after Phase 22 outcomes and Phase 26 denominator are valid.
8. Implement Phase 29 evidence gate last, and run it before any v4 promotion claim.

## Costs

| cost area | v4 expectation |
| --- | --- |
| Storage | Native snapshots, attribution ledger, replay reports, calibration artifacts, and evidence manifests grow with recommendations and retained redacted raw text. Hash-only retention is allowed where the PRDs define it. |
| Compute | Phase 22 measurements, hash validation, parser checks, calibration arithmetic, and outcome replay are deterministic local work. Long replay needs checkpoint and resume. |
| Provider calls | Verbatim and outcome replay call no provider. Recompute replay can call a provider only with explicit opt-in budget and nondeterminism reporting. |
| Market data | Outcome replay needs price, benchmark, calendar, corporate action, and FX provenance. Missing source creates pending, insufficient_data, insufficient_context, degraded, or blocked states instead of guessed numbers. |
| Execution | Net execution metrics need a versioned cost model and fill/order linkage. They remain secondary and cannot replace gross benchmark excess return. |

## Risks and mitigations

| risk | impact | mitigation |
| --- | --- | --- |
| Stale latest close replaces N-session exit | False hit rate and false calibration | Phase 22 stale state failure and Phase 29 stale evidence probe |
| Legacy 82 snapshots are treated as native v4 | Invalid learning and overconfident reporting | Phase 24 audit-only marking and Phase 29 invalid legacy report |
| Denominator collapses to executed BUY | Selection bias | Phase 26 five-action denominator and rejected or blocked preservation |
| KOSPI context drives US decisions directly | Wrong regime and benchmark attribution | Phase 25 exchange-level benchmark and regime source rules |
| HOLD creates trade PnL | HOLD semantics become contradictory | Phase 26 HOLD linkage failure and Phase 28 new trade none rule |
| Confidence labels are treated as probabilities | Bad calibration and bad promotion | Phase 28 numeric `confidence_probability` requirement |
| Recompute drift is hidden | Non-deterministic provider output looks stable | Phase 27 recompute report with cost, provider, model, and drift status |
| Evidence gate trusts prose | Promotion without artifacts | Phase 29 parser, mutation, manual Read, and independent review requirements |

## Success criteria

1. Every native v4 recommendation can be traced from user-visible `emitted_at` to next-session entry, N-session exit, market context, benchmark, denominator cohort, replay result, and calibration eligibility.
2. `gross_benchmark_excess_return_N` is the primary decision-quality metric, `gross_absolute_return_N` is retained, and net execution metrics remain secondary.
3. Existing 82 legacy snapshots remain immutable and audit-only, with zero canonical metric and zero calibration eligibility.
4. HOLD always means no new trade, and any HOLD with portfolio trade, order, or fill linkage fails schema validation.
5. Confidence calibration consumes numeric `confidence_probability`, not display labels, and returns no-op when sample gates are not met.
6. Full workflow replay separates verbatim, outcome, and recompute modes, and never labels signal-only backtest as full replay.
7. Phase 29 gate can fail stale, dirty, misleading, malformed, interrupted verification, bad resume, and duplicate or missing artifact cases before a v4 promotion claim.
8. The v4 gate neither waits for nor changes v5, v6, v7, v8, or v9 document state.

## Validation requirements for this SPEC

The authoring QA for this SPEC must include:

1. Manual Read of this file and the eight v4 PRDs.
2. Deterministic parser check that the PRD table has exactly Phase 22 through Phase 29 in order.
3. Deterministic parser check that each relative v4 PRD link appears exactly once.
4. Link and anchor validation for every Markdown link in this file.
5. Terminology checks for next-session entry, gross benchmark excess primary, net secondary, legacy audit-only, HOLD new trade none, and confidence probability.
6. Failure probes for malformed links, duplicate Phase rows, missing Phase rows, misleading v5-v9 dependency text, stale latest-close wording, and forbidden completion marker.
