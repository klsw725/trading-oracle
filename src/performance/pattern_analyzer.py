"""적중 패턴 분석 — Phase 14

관점별 × 레짐별 적중률 행렬, verdict별 정밀도, 시계열 추세.
Phase 15 레짐별 가중치의 입력.
"""

from src.performance.tracker import list_snapshots, load_snapshot, evaluate_snapshot

PERSPECTIVES = ["kwangsoo", "ouroboros", "quant", "macro", "value"]
REGIMES = ["bull", "bear", "sideways"]


def compute_regime_weights(regime: str, min_per_regime: int = 5, eval_window: int = 5) -> dict | None:
    """레짐별 관점 가중치 계산 (Phase 15).

    현재 레짐의 적중률을 가중치로 변환.
    해당 레짐의 표본이 부족하면 None (v2 가중치로 폴백).

    Returns:
        {"kwangsoo": 0.80, ...} 또는 None
    """
    patterns = analyze_hit_patterns(min_snapshots=min_per_regime, eval_window=eval_window)
    if not patterns:
        return None

    regime_data = patterns.get("by_regime", {}).get(regime)
    if not regime_data:
        return None

    # 해당 레짐에서 모든 관점의 최소 표본 확인
    for p in PERSPECTIVES:
        p_data = regime_data.get(p)
        if not p_data or p_data["total"] < min_per_regime:
            return None

    weights = {}
    for p in PERSPECTIVES:
        rate = regime_data[p]["rate"]
        if rate is not None:
            weights[p] = max(0.1, round(rate / 100, 3))
        else:
            weights[p] = 1.0

    return weights


def analyze_hit_patterns(min_snapshots: int = 5, eval_window: int = 5) -> dict | None:
    """적중 패턴 분석.

    Args:
        min_snapshots: 최소 스냅샷 수 (미달 시 None)
        eval_window: 적중 평가 윈도우 (일)

    Returns:
        {
            "overall": {"kwangsoo": {"total": N, "hits": N, "rate": float}, ...},
            "by_regime": {"bull": {"kwangsoo": {...}, ...}, ...},
            "by_verdict": {"BUY": {"kwangsoo": {...}, ...}, ...},
            "trend": {"kwangsoo": {"slope": float, "improving": bool}, ...},
            "metadata": {"snapshots_analyzed": N, "regime_distribution": {...}},
        }
    """
    snapshots = list_snapshots()
    if len(snapshots) < min_snapshots:
        return None

    # 스냅샷별 레짐 + 적중 데이터 수집
    records = []
    for date_str in snapshots:
        snap = load_snapshot(date_str)
        if not snap:
            continue

        # 레짐 정보 (스냅샷에 저장된 market 데이터에서 추출)
        regime = _extract_regime(snap)
        ev = evaluate_snapshot(snap, eval_days=[eval_window])

        for ticker, ticker_ev in ev.get("evaluations", {}).items():
            for p_name, p_data in ticker_ev.get("perspective_hits", {}).items():
                hit = p_data.get(str(eval_window))
                if hit is not None:
                    records.append({
                        "date": date_str,
                        "ticker": ticker,
                        "perspective": p_name,
                        "verdict": p_data.get("verdict", "N/A"),
                        "hit": hit,
                        "regime": regime,
                    })

    if not records:
        return None

    # 전체 적중률
    overall = _calc_rates_by_perspective(records)

    # 레짐별 적중률
    by_regime = {}
    for regime in REGIMES:
        regime_records = [r for r in records if r["regime"] == regime]
        if regime_records:
            by_regime[regime] = _calc_rates_by_perspective(regime_records)

    # verdict별 적중률
    by_verdict = {}
    for verdict in ("BUY", "SELL", "HOLD"):
        v_records = [r for r in records if r["verdict"] == verdict]
        if v_records:
            by_verdict[verdict] = _calc_rates_by_perspective(v_records)

    # 시계열 추세 (날짜순 적중률 기울기)
    trend = _calc_trend(records)

    # 레짐 분포
    regime_dist = {}
    dates_by_regime = {}
    for r in records:
        dates_by_regime.setdefault(r["regime"], set()).add(r["date"])
    for regime in REGIMES:
        regime_dist[regime] = len(dates_by_regime.get(regime, set()))

    return {
        "overall": overall,
        "by_regime": by_regime,
        "by_verdict": by_verdict,
        "trend": trend,
        "metadata": {
            "snapshots_analyzed": len(snapshots),
            "total_records": len(records),
            "regime_distribution": regime_dist,
        },
    }


def _extract_regime(snap: dict) -> str:
    """스냅샷에서 레짐 추출."""
    market = snap.get("market", {})
    regime = market.get("regime", {})
    return regime.get("regime", "unknown")


def _calc_rates_by_perspective(records: list[dict]) -> dict:
    """관점별 적중률 계산."""
    stats = {}
    for r in records:
        p = r["perspective"]
        if p not in stats:
            stats[p] = {"total": 0, "hits": 0}
        stats[p]["total"] += 1
        if r["hit"]:
            stats[p]["hits"] += 1

    for p in stats:
        s = stats[p]
        s["rate"] = round(s["hits"] / s["total"] * 100, 1) if s["total"] > 0 else None

    return stats


def _calc_trend(records: list[dict]) -> dict:
    """관점별 적중률 시계열 추세 (선형 회귀 기울기)."""
    import numpy as np

    # 날짜순 정렬
    dates = sorted(set(r["date"] for r in records))
    if len(dates) < 3:
        return {p: {"slope": 0.0, "improving": False} for p in PERSPECTIVES}

    trend = {}
    for p in PERSPECTIVES:
        p_records = [r for r in records if r["perspective"] == p]
        if len(p_records) < 3:
            trend[p] = {"slope": 0.0, "improving": False}
            continue

        # 날짜별 적중률 계산
        by_date = {}
        for r in p_records:
            by_date.setdefault(r["date"], {"total": 0, "hits": 0})
            by_date[r["date"]]["total"] += 1
            if r["hit"]:
                by_date[r["date"]]["hits"] += 1

        sorted_dates = sorted(by_date.keys())
        rates = [by_date[d]["hits"] / by_date[d]["total"] for d in sorted_dates if by_date[d]["total"] > 0]

        if len(rates) < 3:
            trend[p] = {"slope": 0.0, "improving": False}
            continue

        # 선형 회귀 기울기
        x = np.arange(len(rates))
        slope = float(np.polyfit(x, rates, 1)[0])
        trend[p] = {"slope": round(slope, 4), "improving": slope > 0}

    return trend
