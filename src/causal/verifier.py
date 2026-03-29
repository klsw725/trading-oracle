"""인과추론 검증 엔진 — Phase 12

Granger Causality Test로 인과 그래프 트리플을 검증.
Phase 11 매크로 시계열 + 종목 OHLCV를 입력으로 사용.
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd

VERIFIED_GRAPH_PATH = Path("data/causal_graph_verified.json")
NODE_MAP_PATH = Path("data/node_series_map.json")

# --- M1: 노드 → 시계열 매핑 (규칙 기반) ---

# 키워드 → 시계열 변수 매핑
NODE_KEYWORDS = {
    # 금리
    "US10YT": ["미국 기준금리", "미국 금리", "연준 금리", "미국 국채금리", "미 연준", "Fed", "기준금리 인상", "기준금리 인하", "미국의 기준금리", "미국 연준의 기준금리"],
    "US10YT": ["미국 10년", "US 10Y", "장기금리"],
    "US13WT": ["단기금리", "13주", "T-Bill"],
    # 환율
    "USD_KRW": ["원/달러", "원달러", "환율", "원화", "달러 강세", "달러 약세", "원화 약세", "원화 강세", "한국 원화"],
    "DXY": ["달러 인덱스", "Dollar Index", "달러화 가치"],
    # 원자재
    "WTI": ["유가", "원유", "국제유가", "WTI", "석유", "에너지 가격"],
    "GOLD": ["금", "금값", "금 가격", "안전자산", "Gold"],
    # 지수
    "KOSPI": ["코스피", "한국 증시", "한국 주식", "KOSPI", "한국 주가"],
    "KOSDAQ": ["코스닥", "KOSDAQ"],
    "NASDAQ": ["나스닥", "NASDAQ", "미국 기술주", "미국 증시", "미국 주식"],
    "SP500": ["S&P", "S&P500", "미국 대형주"],
}


def build_node_map(graph) -> dict:
    """인과 그래프 노드를 시계열 변수에 매핑.

    Returns:
        {"노드명": "시계열변수", ...}
    """
    node_map = {}
    for node in graph.graph.nodes:
        node_lower = node.lower()
        for series_key, keywords in NODE_KEYWORDS.items():
            for kw in keywords:
                if kw.lower() in node_lower:
                    node_map[node] = series_key
                    break
            if node in node_map:
                break
    return node_map


# --- M2: Granger Causality 검증 ---

def _ensure_stationary(series: pd.Series, max_diff: int = 2) -> pd.Series:
    """ADF test로 정상성 확인, 비정상이면 차분."""
    from statsmodels.tsa.stattools import adfuller
    s = series.dropna()
    if len(s) < 30:
        return s
    for d in range(max_diff + 1):
        try:
            result = adfuller(s, autolag="AIC")
            if result[1] < 0.05:  # p < 0.05 → 정상
                return s
        except Exception:
            pass
        s = s.diff().dropna()
    return s


def granger_test_pair(x: pd.Series, y: pd.Series, maxlag: int = 30) -> dict | None:
    """x → y 방향의 Granger test.

    Returns:
        {"p_value": float, "lag": int, "f_stat": float} or None
    """
    from statsmodels.tsa.stattools import grangercausalitytests

    # 정상성 확보
    x_stat = _ensure_stationary(x)
    y_stat = _ensure_stationary(y)

    # 공통 인덱스
    common = x_stat.index.intersection(y_stat.index)
    if len(common) < maxlag + 10:
        return None

    data = pd.DataFrame({"y": y_stat.loc[common], "x": x_stat.loc[common]}).dropna()
    if len(data) < maxlag + 10:
        return None

    actual_maxlag = min(maxlag, len(data) // 3)
    if actual_maxlag < 1:
        return None

    try:
        results = grangercausalitytests(data, maxlag=actual_maxlag, verbose=False)
    except Exception:
        return None

    # 최소 p-value의 lag 선택
    best_lag = None
    best_p = 1.0
    best_f = 0.0
    for lag, result in results.items():
        p = result[0]["ssr_ftest"][1]
        f = result[0]["ssr_ftest"][0]
        if p < best_p:
            best_p = p
            best_lag = lag
            best_f = f

    if best_lag is None:
        return None

    return {"p_value": round(best_p, 6), "lag": best_lag, "f_stat": round(best_f, 4)}


# --- M3: 전체 검증 + 신뢰도 태깅 ---

def verify_causal_graph(on_progress=None) -> dict:
    """인과 그래프의 매핑 가능한 트리플을 Granger test로 검증.

    Returns:
        {
            "metadata": {...},
            "verified_triples": [...],
            "failed_triples": [...],
            "unmappable_triples": [...]
        }
    """
    from src.causal.graph import CausalGraph
    from src.data.macro import fetch_macro_series

    graph = CausalGraph.load()
    macro_df = fetch_macro_series()

    if macro_df.empty:
        return {"metadata": {"error": "매크로 시계열 없음"}, "verified_triples": [], "failed_triples": [], "unmappable_triples": graph.triples}

    node_map = build_node_map(graph)

    # 기본 컬럼만 사용 (파생 제외)
    from src.data.macro import MACRO_SYMBOLS
    base_cols = [c for c in MACRO_SYMBOLS.keys() if c in macro_df.columns]

    verified = []
    failed = []
    unmappable = []
    total = len(graph.triples)

    # Bonferroni correction
    mappable_count = 0
    for t in graph.triples:
        if t["subject"] in node_map and t["object"] in node_map:
            s_key = node_map[t["subject"]]
            o_key = node_map[t["object"]]
            if s_key != o_key and s_key in base_cols and o_key in base_cols:
                mappable_count += 1

    alpha = 0.05
    corrected_alpha = alpha / max(mappable_count, 1)

    processed = 0
    for t in graph.triples:
        subj = t["subject"]
        obj = t["object"]

        s_key = node_map.get(subj)
        o_key = node_map.get(obj)

        if not s_key or not o_key or s_key == o_key:
            unmappable.append(t)
            continue

        if s_key not in base_cols or o_key not in base_cols:
            unmappable.append(t)
            continue

        x = macro_df[s_key]
        y = macro_df[o_key]

        result = granger_test_pair(x, y)

        processed += 1
        if on_progress:
            on_progress(processed, mappable_count)

        if result is None:
            t_copy = {**t, "verification": {"status": "failed", "reason": "test_error"}}
            failed.append(t_copy)
            continue

        # 방향 일치성: relation에 따른 상관 부호 확인
        relation = t.get("relation", "").lower()
        corr = x.corr(y)
        if "increase" in relation or "cause" in relation or "lead" in relation:
            direction_match = corr > 0
        elif "decrease" in relation or "reduce" in relation or "lower" in relation:
            direction_match = corr < 0
        else:
            direction_match = True  # 관계 방향 불명 → 패스

        # 신뢰도 계산
        p = result["p_value"]
        if p < corrected_alpha and direction_match:
            confidence = min(1.0, round(1.0 - p * 10, 2))
            t_copy = {
                **t,
                "verification": {
                    "status": "verified",
                    "p_value": p,
                    "lag": result["lag"],
                    "f_stat": result["f_stat"],
                    "direction_match": direction_match,
                    "confidence": confidence,
                    "series_pair": [s_key, o_key],
                }
            }
            verified.append(t_copy)
        else:
            t_copy = {
                **t,
                "verification": {
                    "status": "failed",
                    "p_value": p,
                    "lag": result.get("lag"),
                    "direction_match": direction_match,
                    "reason": "p_too_high" if p >= corrected_alpha else "direction_mismatch",
                    "series_pair": [s_key, o_key],
                }
            }
            failed.append(t_copy)

    result = {
        "metadata": {
            "total_triples": total,
            "mappable": mappable_count,
            "verified": len(verified),
            "failed": len(failed),
            "unmappable": len(unmappable),
            "alpha": alpha,
            "corrected_alpha": round(corrected_alpha, 6),
            "verified_at": pd.Timestamp.now().isoformat(),
        },
        "verified_triples": verified,
        "failed_triples": failed,
        "unmappable_triples": unmappable,
    }

    # 저장
    _save_verified(result)

    # 노드 매핑도 저장
    NODE_MAP_PATH.parent.mkdir(parents=True, exist_ok=True)
    NODE_MAP_PATH.write_text(json.dumps(node_map, ensure_ascii=False, indent=2))

    return result


def _save_verified(data: dict):
    """검증 결과 저장."""
    VERIFIED_GRAPH_PATH.parent.mkdir(parents=True, exist_ok=True)
    VERIFIED_GRAPH_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str))


def load_verified_graph() -> dict | None:
    """검증된 인과 그래프 로드."""
    if not VERIFIED_GRAPH_PATH.exists():
        return None
    try:
        return json.loads(VERIFIED_GRAPH_PATH.read_text())
    except Exception:
        return None


def get_verified_chains(keywords: list[str], min_confidence: float = 0.5) -> list[dict]:
    """검증된 인과 체인 중 키워드 관련 + confidence 이상인 트리플 반환."""
    data = load_verified_graph()
    if not data:
        return []

    results = []
    for t in data.get("verified_triples", []):
        v = t.get("verification", {})
        if v.get("confidence", 0) < min_confidence:
            continue
        text = f"{t['subject']} {t['object']}".lower()
        for kw in keywords:
            if kw.lower() in text:
                results.append(t)
                break

    return results
