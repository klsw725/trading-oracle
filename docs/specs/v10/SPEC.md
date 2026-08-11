# Trading Oracle v10 SPEC: Intraday Data Foundation
> **상태**: 📝 초안

v10은 KR·US 5분봉 paper research의 시장 범위, 원천 1분봉, 세션 정렬, 완결성, universe, corporate action, provenance 계약을 정의한다. v10이 성공해도 주문, 전략 판정, LLM 호출, paper 승격은 허용되지 않는다.

## 0. 구현 완결성 계약

- v10은 기존 공통 source adapter만 사용할 수 있으며 v11 이후의 schema, artifact, CLI, 구현 상태를 요구하지 않는다.
- 로컬 canonical fixtures만으로 calendar, 1분봉 정규화, 5분봉 집계, universe, context archive, supersede를 end-to-end 실행할 수 있어야 한다.
- `uv run python -m src.v10.cli acceptance`가 v10 문서와 로컬 fixtures만 읽어 canonical JSON 보고서를 출력하고 exit 0이어야 한다.
- Acceptance는 primary 정상 수신, secondary fallback, missing minute, late revision, holiday, early close, universe freeze, corporate action, context archive mutation을 실제로 실행한다.
- v11 이후 디렉터리를 삭제하거나 아직 구현하지 않아도 v10 acceptance는 동일하게 통과해야 한다.
- 이 조건과 아래 Acceptance Criteria가 모두 통과하면 v10 구현은 단독으로 완료다.

## Local PRD Map

| PRD | Local document | Implementation owner | Produces |
| --- | --- | --- | --- |
| PRD 01 | [Calendar, Source, Minute Contract](prds/prd01-calendar-source-minute-contract.md) | 공식 calendar, source provenance, canonical 1분봉 | calendar, source observation, minute bar, data incident |
| PRD 02 | [Five-Minute Watermark And Revision](prds/prd02-five-minute-watermark-revision.md) | 10초 watermark, 5분 집계, supersede replay | five-minute bar, supersede event |
| PRD 03 | [Universe, Corporate Action, Eligibility](prds/prd03-universe-corporate-action-eligibility.md) | Top 100, instrument exclusion, eligibility, price layers | universe, eligibility, corporate action artifacts |
| PRD 04 | [Context, Canonical Artifacts, Acceptance](prds/prd04-context-canonical-acceptance.md) | Context archive, canonical boundary, version CLI | context artifacts, canonical acceptance report |

PRD 01→04 순서로 구현한다. 각 PRD는 정확히 한 parent SPEC backlink을 가지며 PRD 04는 앞 PRD의 domain logic을 재구현하지 않고 acceptance orchestration만 소유한다.

## 1. 목표와 비목표

### 목표

- KR·US 정규장의 point-in-time 1분봉을 재현 가능한 5분봉으로 집계한다.
- 전일 정보만으로 시장별 거래대금 상위 100개 universe를 만든다.
- 세션, 지연, 누락, 정정, corporate action을 명시적 artifact로 남긴다.
- primary와 secondary source의 오류를 숨기지 않고 fail closed 한다.

### 비목표

- 실계좌 주문 또는 broker live submit
- 전략 신호, 포지션, 성과 verdict 생성
- 장전·장후 거래
- 장중 universe 재선정
- 깨진 pykrx API를 신규 intraday 경로에 재도입

## 2. 시장과 시간 계약

| 항목 | KR | US |
| --- | --- | --- |
| 연구 범위 | 거래소 공식 정규장 | 거래소 공식 정규장 |
| 세션 기준 | 공식 거래소 calendar | 공식 거래소 calendar, timezone, DST |
| 조기폐장 | 단축 정규장으로 처리 | 단축 정규장으로 처리 |
| 경매·중단·재개 | 연속매매와 별도 상태 | 연속매매와 별도 상태 |
| cohort | KR 독립 cohort | US 독립 cohort |

공식 calendar snapshot은 버전과 hash를 가진다. 고정 현지시간이나 broker calendar만으로 휴장, 임시 휴장, 조기폐장, DST를 추정해서는 안 된다. 정규장 밖의 봉은 연구 입력에 포함하지 않는다.

## 3. Source 계약

1. Toss Open API를 primary intraday source로 사용한다.
2. secondary source는 동일 시장, 1분 OHLCV, 거래량, timestamp, 세션 상태, 정정 식별 capability를 실제로 검증한 뒤에만 활성화한다.
3. primary 실패를 secondary 성공으로 덮어쓰지 않는다. fallback 사용 여부와 원인을 artifact에 남긴다.
4. source identity, adapter version, fetched_at, observed_at, market timestamp, raw payload hash, normalization version을 보존한다.
5. source onboarding과 lifecycle은 [v7](../v7/SPEC.md)의 provenance·quality·promotion 원칙을 따른다.
6. `pykrx.get_market_fundamental()`, `pykrx.get_market_cap()`, `pykrx.get_index_ohlcv()`는 알려진 비호환성 때문에 이 계약의 fallback 후보가 아니다.

Source fallback, 누락, corporate action 이상, timestamp 불일치, reconciliation 실패는 v10 `data_incident` artifact를 만들고 affected symbol 또는 market ingest를 fail closed 한다.

## 4. 1분봉 정규화

Canonical 1분봉은 최소한 다음 필드를 가진다.

| 필드 | 규칙 |
| --- | --- |
| `market` | `KR` 또는 `US` |
| `symbol` | 시장 namespace가 포함된 canonical symbol |
| `session_date` | 공식 거래소 현지 거래일 |
| `interval_start`, `interval_end` | timezone이 명시된 반개구간 |
| `open`, `high`, `low`, `close` | raw execution price, 유한 decimal |
| `volume` | 음수가 아닌 정수 |
| `session_state` | regular, auction, halted, resumed 중 명시값 |
| `source_artifact_id` | provenance artifact 참조 |
| `observed_at` | 시스템이 실제 수신한 시각 |
| `revision` | 원본은 0, 정정은 증가 |

동일 symbol·interval·revision은 하나만 존재해야 한다. timestamp 중복, 역전, OHLC 불변식 위반, 음수 거래량, 시장 calendar 밖의 regular 표시는 malformed로 차단한다.

### Router context artifact

v10은 뉴스·공시·기업행사·규제자료의 point-in-time archive도 생산한다. 각 `context_artifact`는 `artifact_id`, `artifact_type`, `market`, 직접 관련 symbol·sector, `published_at`, archival source가 최초로 관측한 `observed_at`, Trading Oracle의 `ingested_at`, canonical text hash, source identity, revision, supersede ref를 가진다.

Historical artifact는 당시 시점의 보존본과 당시 `observed_at`을 증명하는 archival source가 있을 때만 과거 cutoff에 사용할 수 있다. 현재 시점에 처음 수집한 문서의 `published_at`만 과거라는 이유로 과거 관측 자료처럼 취급하지 않는다. v10은 빈 자료 목록인 cutoff도 healthy context snapshot으로 기록하며 archive coverage gap을 숨기지 않는다.

## 5. 5분봉 집계와 Watermark

1. 5분 구간 종료 후 정확히 10초까지 원천 1분봉을 기다린다.
2. 공식 세션에 속하는 연속된 원천 1분봉 5개가 모두 있을 때만 5분봉을 `complete`로 만든다.
3. `open`은 첫 봉 시가, `high`는 최대 고가, `low`는 최소 저가, `close`는 마지막 봉 종가, `volume`은 합계다.
4. 경매, 중단, 재개가 섞인 구간은 일반 regular 5분봉으로 합치지 않는다.
5. 10초 watermark에 하나라도 없거나 stale이면 해당 symbol·cutoff는 fail closed 하고 신규 신호 입력이 될 수 없다.
6. watermark 이후 도착한 정정은 기존 artifact를 수정하지 않는다. 새 `supersede` event가 이전 hash와 새 hash를 연결한다.
7. 당시 결정 replay는 당시 승인된 원본 또는 당시 존재했던 supersede head만 사용한다. 미래 정정으로 과거 결정을 다시 쓰지 않는다.

## 6. 일일 Universe

각 시장은 독립적으로 다음 절차를 수행한다.

1. T일 공식 종가 데이터 reconciliation이 끝난 뒤 최근 20거래일 평균 거래대금을 계산한다.
2. 평균 거래대금 내림차순 상위 100개를 T+1 universe snapshot으로 고정한다.
3. 동률은 canonical symbol 오름차순으로 결정한다.
4. T+1 정규장 동안 membership을 바꾸지 않는다.

다음 종목은 ranking 전에 제외한다.

- ETF, ETN, 우선주
- ADR, SPAC, unit, warrant
- 상장 후 20 공식 거래세션 미만
- 거래정지 또는 20일 계산에 필요한 데이터가 불완전한 종목
- 시장별 instrument classification이 확정되지 않은 종목

T+1 장 시작 전 또는 장중 거래정지, 데이터 누락, 규제 제한이 생기면 해당 종목의 eligibility만 차단한다. 101위 이하 종목을 대체 승격하지 않는다. 일일 정상 snapshot은 자동 승인할 수 있지만 데이터 이상은 수동 승인 예외다.

## 7. Corporate Action과 가격 계층

- 체결, 원장, 감사에는 raw 가격을 보존한다.
- 분할, 병합, 배당, 권리락 등은 point-in-time corporate action artifact와 조정계수로 별도 저장한다.
- 과거 수익률, lookback, 기술 지표에는 해당 cutoff 당시 이용 가능했던 조정계수만 사용한다.
- 수정주가를 실제 체결가격처럼 기록하거나 현재 조정계수를 과거 cutoff에 소급 적용해서는 안 된다.
- corporate action이 검증되지 않은 종목은 eligibility를 차단하고 대체 종목을 넣지 않는다.

## 8. Canonical 산출물

| Artifact | 최소 내용 | Downstream role |
| --- | --- | --- |
| `market_calendar_snapshot` | 시장, 세션, 휴장, 조기폐장, timezone, DST, version, hash | 세션 판정 입력 |
| `source_observation` | source identity, 원본 hash, observed_at, 상태 | provenance와 incident 입력 |
| `minute_bar` | canonical 1분봉과 provenance | 체결과 집계 입력 |
| `five_minute_bar` | 5개 원천 hash, watermark, complete 상태 | 신호 계산 입력 |
| `universe_snapshot` | T+1 members, rank inputs, exclusions, hash | 후보 eligibility 입력 |
| `eligibility_event` | 차단 원인, 시작·종료 시각, source refs | risk와 audit 입력 |
| `corporate_action_snapshot` | action type, effective time, adjustment factor, refs | 가격 조정 입력 |
| `context_artifact` | type, relevance, published_at, observed_at, ingested_at, canonical text hash, provenance | point-in-time context 입력 |
| `supersede_event` | prior hash, replacement hash, reason, observed_at | replay, audit |

모든 artifact는 canonical serialization과 content hash를 가진다. secret, raw account identifier, credential은 포함하지 않는다.

## 9. 실패와 Mutation 계약

| Probe | Mutation | Required result |
| --- | --- | --- |
| `missing_minute` | 5개 중 1분봉 하나 제거 | incomplete, 신호 입력 차단 |
| `late_revision` | watermark 이후 OHLC 변경 | 원본 불변, supersede 생성 |
| `calendar_mismatch` | 휴장일을 regular로 표시 | calendar mismatch failure |
| `auction_mixed` | auction 봉을 regular 집계에 포함 | aggregation failure |
| `future_universe` | T+1 거래대금을 T+1 ranking에 사용 | lookahead failure |
| `replacement_member` | 장중 101위 종목 승격 | frozen universe failure |
| `adjusted_execution` | 수정주가를 fill price로 사용 | price layer failure |
| `hidden_fallback` | secondary 결과를 primary로 표시 | provenance failure |
| `backfilled_observation` | 현재 수집시각을 과거 observed_at으로 변경 | point-in-time archive failure |

## 10. Acceptance Criteria

- KR·US 정규장 1분봉과 공식 calendar를 point-in-time으로 replay할 수 있다.
- 정확히 10초 watermark와 5개 원천 봉 조건이 명시적이다.
- 누락·stale·정정은 hidden success가 아니라 차단 또는 supersede가 된다.
- 시장별 Top 100 universe가 T일 종가 후 생성되고 T+1 동안 고정된다.
- 제외 종목과 장중 eligibility 차단은 대체 승격 없이 적용된다.
- raw execution price와 adjusted indicator price가 분리된다.
- Router context의 published, observed, ingested 시각과 historical archive 자격이 분리된다.
- 모든 후속 계약이 동일 artifact ID와 hash를 참조할 수 있다.
