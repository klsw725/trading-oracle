# Trading Oracle v12 SPEC: Intraday Strategy Cohort
> **상태**: 📝 초안

v12는 [v10](../v10/SPEC.md)의 완결 5분봉으로 생성하는 15개 deterministic intraday 전략 cohort를 정의한다. v12 전략은 스스로 LLM을 호출하지 않으며 실행 가능 strategy-symbol 후보와 독립 shadow ledger를 만든다. 정확한 feature, gate, score, 최대 4개 parameter set은 [Strategy Grids](STRATEGY-GRIDS.md)가 소유한다.

## 0. 구현 완결성 계약

- v12는 구현 완료된 v10 market artifact와 v11 paper execution·ledger만 의존한다.
- 각 strategy와 parameter set을 독립 shadow arm으로 실행해 candidate, intent, fill, cost, exit, attribution을 end-to-end 생성해야 한다.
- `uv run python -m src.v12.cli acceptance`가 v10·v11 canonical fixtures와 v12 로컬 strategy fixtures를 읽어 canonical JSON 보고서를 출력하고 exit 0이어야 한다.
- Acceptance는 15개 strategy ID와 모든 등록 parameter set의 happy path, no-signal, missing feature, duplicate-session signal, short eligibility, close exit mutation을 실행한다.
- v13 이후 디렉터리를 삭제하거나 아직 구현하지 않아도 v12 acceptance와 shadow run은 동일하게 동작해야 한다.
- 통계적 parameter 우열이나 승격 판정은 v12 완료 조건이 아니다. 명시적 `active_parameter_set_id`로 각 등록 set을 실행할 수 있으면 된다.
- 이 조건과 아래 Acceptance Criteria가 모두 통과하면 v12 구현은 단독으로 완료다.

## Local PRD Map

| PRD | Local document | Implementation owner | Produces |
| --- | --- | --- | --- |
| PRD 01 | [Strategy Runtime And Candidate Contract](prds/prd01-strategy-runtime-candidate-contract.md) | Common features, grids, candidates, identity | deterministic candidate artifacts |
| PRD 02 | [Long Strategy Cohort](prds/prd02-long-strategy-cohort.md) | Long 10개·40 parameter set | Long shadow candidates |
| PRD 03 | [Short, Shadow, Attribution](prds/prd03-short-shadow-attribution.md) | Short 5개·20 set, 60 arm isolation, attribution | shadow ledgers and trade lineage |
| PRD 04 | [Acceptance And Canonical Replay](prds/prd04-acceptance-canonical-replay.md) | 15 strategy·60 arm coverage and mutations | canonical acceptance report |

PRD 01→04 순서로 구현한다. Strategy Grids는 PRD 01~03의 동일-version 계약이며 PRD 04는 통계적 우열이나 후속 승격을 요구하지 않는다.

## 1. 전략 목록

### Long 10개

| ID | Strategy | 필수 신호 의미 |
| --- | --- | --- |
| `long_orb_15m` | 15-minute opening range breakout | 첫 15분 range 상단 돌파 |
| `long_orb_30m` | 30-minute opening range breakout | 첫 30분 range 상단 돌파 |
| `long_gap_continuation` | Gap continuation | 전일 종가 대비 상승 gap 이후 같은 방향 지속 |
| `long_session_high_breakout` | Session-high breakout | 현재 세션 확정 고점 돌파 |
| `long_vwap_reclaim` | VWAP reclaim | VWAP 아래에서 위로 회복 후 확인 |
| `long_ma_trend` | Moving-average trend | 단기·중기 추세 정렬과 가격 확인 |
| `long_relative_strength` | Relative-strength momentum | 시장 또는 sector 대비 상대 모멘텀 우위 |
| `long_volume_breakout` | Volume-confirmed breakout | 가격 돌파와 상대 거래량 확인 |
| `long_volatility_expansion` | Volatility expansion | 압축 또는 기준 변동성 대비 상방 확장 |
| `long_range_compression` | Range-compression breakout | 좁은 range 형성 후 상방 이탈 |

### Short 5개

| ID | Strategy | 필수 신호 의미 |
| --- | --- | --- |
| `short_orb_15m` | 15-minute opening range breakdown | 첫 15분 range 하단 이탈 |
| `short_gap_continuation` | Gap-down continuation | 전일 종가 대비 하락 gap 이후 같은 방향 지속 |
| `short_session_low_breakdown` | Session-low breakdown | 현재 세션 확정 저점 이탈 |
| `short_vwap_rejection` | VWAP rejection | VWAP 회복 실패 후 하방 확인 |
| `short_volume_breakdown` | Volume-confirmed downside breakout | 하방 돌파와 상대 거래량 확인 |

각 전략의 정확한 lookback, gap, volume, volatility, confirmation 임계값은 사전등록 parameter grid에만 존재한다. 구현자가 문서 밖의 임계값을 임의로 추가해서는 안 된다.

## 2. 최초 Paper 전략: 15분 ORB

`long_orb_15m`은 최초 기준 전략이다.

1. 공식 정규장 개장 뒤 첫 15분의 complete 5분봉 3개로 opening range를 만든다.
2. 개장 15분 이후부터 60분 이내에 완결된 5분봉 종가가 range high를 처음 상향 돌파하면 Long 신호를 확정한다.
3. wick 또는 미완결 봉의 장중 고가만으로 돌파를 인정하지 않는다.
4. v10의 10초 watermark 뒤 신호를 확정하고, [v11](../v11/SPEC.md)에 따라 결정 완료 후 최초 1분 경계를 체결 목표로 사용한다.
5. stop-loss와 profit target을 두지 않는다.
6. 정규장 종료 5분 전에 청산 intent를 만들고 그 뒤 최초 거래 가능한 1분 경계에 전량 청산한다.
7. 같은 symbol·session에서 최초 유효 돌파 하나만 허용한다.

`short_orb_15m`은 range low, 하향 돌파, short eligibility를 대칭 적용하지만 최초 paper 기준 전략은 아니다.

## 3. Candidate 계약

전략은 조건을 만족할 때 다음 정보를 가진 immutable candidate를 생성한다.

| Field | Rule |
| --- | --- |
| `candidate_id` | market·symbol·strategy_id·strategy_version·parameter_set_id·cutoff hash |
| `market`, `symbol` | v10 universe와 eligibility 통과 |
| `strategy_id`, `strategy_version` | manifest와 일치 |
| `side` | long 또는 short |
| `signal_cutoff` | complete 5분봉 종료시각 |
| `feature_snapshot_hash` | 모든 계산 입력과 조정계수 포함 |
| `deterministic_score` | Strategy Grids의 고정 0~1 scoring contract 결과 |
| `entry_boundary` | `first_1m_after_decision` 고정값 |
| `exit_policy` | 장마감 청산과 강제 risk exit 참조 |
| `eligibility_refs` | universe, data, borrow, regulation, risk refs |

신호가 없거나 data·session·instrument·corporate-action·short borrow/regulation gate 중 하나라도 실패하면 candidate를 만들지 않는다. 이 단계 산출물을 `pre_portfolio_candidate`라 한다. Cash, slot, sector, correlation, gross, net, daily-loss 같은 계좌 상태 gate까지 통과한 산출물만 `execution_feasible_candidate`다. v12 밖의 consumer도 신호가 없는 전략-symbol 조합을 새로 만들 수 없다.

## 4. Parameter Governance

1. 각 전략은 문헌과 시장관행으로 정한 최대 4개 parameter 조합만 가진다.
2. 4개를 넘는 탐색, 결과를 본 뒤 grid 확장, Bayesian optimization은 허용하지 않는다.
3. 후보 grid 정의는 KR·US가 공유한다.
4. 모든 등록 조합은 `active_parameter_set_id`로 직접 실행 가능해야 하며 v12 acceptance가 각각을 검증한다.
5. 활성 조합은 run 시작 전에 strategy version과 local run manifest에 동결한다.
6. 실질적 동률이면 turnover가 낮은 조합, 그래도 같으면 canonical parameter ID 오름차순을 선택한다.
7. validation 결과를 보고 같은 version의 parameter를 수정할 수 없다.

최대 4개 grid의 실제 숫자, feature 공식, score tie-break는 [Strategy Grids](STRATEGY-GRIDS.md)에 고정한다. 그 문서가 변경되면 새 strategy와 experiment version이다.

## 5. Strategy 상태

```text
specified -> implemented -> fixture_verified -> shadow_ready
```

- 15분 ORB는 최초 end-to-end execution fixture다.
- 나머지 14개 전략도 독립 shadow arm으로 실행한다.
- 전략 하나의 fixture 통과가 다른 전략의 통과를 의미하지 않는다.
- Short 전략은 신호 품질과 별개로 v11 borrow·regulation gate를 통과해야 한다.
- `shadow_ready`는 구현 완료 상태이며 통계적 우수성이나 paper primary 승격을 주장하지 않는다.

## 6. 독립 Shadow 소유권

각 strategy·parameter set은 별도 shadow arm과 v11 ledger namespace를 가진다. 다른 전략의 후보가 기존 shadow position을 교체하거나 소유권을 이전하지 않는다. 최소 보유, challenger 비교, 전략 교체는 v12 runtime 기능이 아니며 없어도 v12가 완결된다. 단순 strategy ID 이전, pyramiding, arm 간 cash·slot 공유는 허용하지 않는다.

## 7. 성과 귀속

각 완료 거래는 signal version, selected parameter ID, entry candidate, router decision 또는 deterministic selection, 모든 fill, cost, forced exit 이유를 참조한다. 청산 후 재진입은 두 거래다. 강제청산, 부분체결, liquidity 취소, short recall도 원래 전략 성과에서 숨기지 않는다.

## 8. 금지 사항

- incomplete 또는 superseded-after-cutoff 봉으로 신호 생성
- 현재 세션 이후 정보나 미래 corporate action factor 사용
- LLM이 전략 feature 또는 deterministic score를 수정
- validation·holdout에서 parameter 재선택
- stop·target을 15분 ORB에 임의 추가
- 장마감 이후 포지션 유지
- short eligibility 없이 short candidate 생성

## 9. Failure와 Mutation 계약

| Probe | Mutation | Required result |
| --- | --- | --- |
| `wick_breakout` | 종가 미돌파인데 고가만 돌파 | ORB signal 없음 |
| `late_orb` | 개장 60분 뒤 첫 돌파 | ORB signal 없음 |
| `incomplete_feature` | 불완전 봉으로 feature 계산 | candidate failure |
| `grid_fifth` | 다섯 번째 parameter 조합 추가 | grid contract failure |
| `market_grid_drift` | KR·US 후보 grid 정의 변경 | shared-grid failure |
| `hidden_stop` | ORB에 미등록 stop 추가 | strategy version failure |
| `llm_signal_creation` | LLM이 없던 candidate 생성 | candidate boundary failure |
| `ownership_transfer` | fill 없이 strategy ID 변경 | attribution failure |
| `candidate_collision` | 다른 strategy ID가 같은 candidate ID 생성 | identity failure |

## 10. Acceptance Criteria

- Long 10개와 Short 5개가 stable strategy ID와 명시적 신호 의미를 가진다.
- 15분 ORB의 range, 첫 close breakout, 15~60분 window, watermark 뒤 최초 1분 경계, 무 stop·target, 장마감 청산이 고정된다.
- 모든 전략은 deterministic candidate만 생성하고 LLM은 후보 생성 권한이 없다.
- 전략별 최대 4개 shared grid와 명시적 `active_parameter_set_id`·run 동결 절차가 있다.
- 나머지 14개 전략은 ORB 기반이 검증된 뒤 shadow로 활성화된다.
- 거래 attribution이 부분체결, 비용, 장마감·risk 강제청산까지 보존된다.
- 모든 전략과 parameter set이 독립 shadow arm에서 실행되며 이후 버전 없이 acceptance를 통과한다.
