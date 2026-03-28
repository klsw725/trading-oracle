"""추천 성과 추적 — 스냅샷 저장/로드, 적중 평가, 리포트 생성

Phase 4 PRD: docs/specs/multi-perspective/prds/phase4-performance.md
"""

import json
from datetime import datetime
from pathlib import Path

from src.data.market import fetch_ohlcv

SNAPSHOTS_DIR = Path("data/snapshots")

# --- 적중 판정 기준 ---
# (verdict, window) → (방향 함수, 임계값)
# BUY: 수익률 > threshold → 적중
# SELL: 수익률 < -threshold → 적중
# HOLD: |수익률| < threshold → 적중
_HIT_CRITERIA = {
    ("BUY", 5): ("positive", 0.0),
    ("BUY", 20): ("positive", 3.0),
    ("SELL", 5): ("negative", 0.0),
    ("SELL", 20): ("negative", 3.0),
    ("HOLD", 5): ("neutral", 3.0),
    ("HOLD", 20): ("neutral", 5.0),
}


def save_snapshot(date: str, market_data: dict, multi_results: dict, signals_data: list[dict]):
    """다관점 분석 결과를 스냅샷으로 저장한다.

    Args:
        date: 분석 날짜 (YYYY-MM-DD)
        market_data: collect_market_data() 결과
        multi_results: run_multi_perspective() 결과 (ticker → consensus dict)
        signals_data: analyze_tickers() 결과
    """
    prices = {s["ticker"]: s["signals"]["current_price"] for s in signals_data}
    names = {s["ticker"]: s["name"] for s in signals_data}

    recommendations = {}
    for ticker, consensus in multi_results.items():
        perspectives = []
        for p in consensus.get("perspectives", []):
            perspectives.append({
                "perspective": p["perspective"],
                "verdict": p["verdict"],
                "confidence": p["confidence"],
                "reason": p.get("reason", ""),
            })

        recommendations[ticker] = {
            "name": names.get(ticker, ticker),
            "price": prices.get(ticker, 0),
            "consensus_verdict": consensus["consensus_verdict"],
            "consensus_confidence": consensus["confidence"],
            "consensus_label": consensus["consensus_label"],
            "vote_summary": consensus["vote_summary"],
            "perspectives": perspectives,
        }

    snapshot = {
        "date": date,
        "market": {
            k: v for k, v in market_data.items()
            if k in ("kospi", "kosdaq")
        },
        "recommendations": recommendations,
    }

    SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    path = SNAPSHOTS_DIR / f"{date}.json"
    path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2))
    return path


def load_snapshot(date: str) -> dict | None:
    """특정 날짜의 스냅샷 로드."""
    path = SNAPSHOTS_DIR / f"{date}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())


def list_snapshots() -> list[str]:
    """저장된 스냅샷 날짜 목록 (오래된 순)."""
    if not SNAPSHOTS_DIR.exists():
        return []
    dates = sorted(p.stem for p in SNAPSHOTS_DIR.glob("*.json"))
    return dates


def _check_hit(verdict: str, return_pct: float, window: int) -> bool | None:
    """적중 여부 판정. 미평가 대상이면 None 반환."""
    key = (verdict, window)
    criteria = _HIT_CRITERIA.get(key)
    if not criteria:
        return None

    direction, threshold = criteria
    if direction == "positive":
        return return_pct > threshold
    elif direction == "negative":
        return return_pct < -threshold
    elif direction == "neutral":
        return abs(return_pct) < threshold
    return None


def evaluate_snapshot(snapshot: dict, eval_days: list[int] | None = None) -> dict:
    """과거 스냅샷의 추천을 현재 가격과 비교하여 적중 평가.

    Returns:
        {
            "date": "2026-03-20",
            "evaluations": {
                "005930": {
                    "name": "삼성전자",
                    "recommendation_price": 179700,
                    "consensus_verdict": "SELL",
                    "consensus_confidence": "high",
                    "windows": {
                        "5": {"current_price": 175000, "return_pct": -2.6, "hit": True},
                        "20": {"current_price": null, "return_pct": null, "hit": null}
                    },
                    "perspective_hits": {
                        "kwangsoo": {"verdict": "SELL", "5": True, "20": null},
                        ...
                    }
                }
            },
            "summary": { ... }
        }
    """
    if eval_days is None:
        eval_days = [5, 20]

    snap_date = snapshot["date"]
    recommendations = snapshot.get("recommendations", {})
    evaluations = {}

    for ticker, rec in recommendations.items():
        rec_price = rec["price"]
        if not rec_price or rec_price <= 0:
            continue

        consensus_v = rec["consensus_verdict"]

        # 현재 가격 가져오기 (스냅샷 날짜 이후 데이터)
        windows = {}
        for days in eval_days:
            ohlcv = fetch_ohlcv(ticker, days_back=days + 10)
            if ohlcv.empty or len(ohlcv) < days:
                windows[str(days)] = {"current_price": None, "return_pct": None, "hit": None}
                continue

            # 스냅샷 날짜 이후 N일째 종가
            price_after = float(ohlcv["close"].iloc[-1])
            ret = (price_after - rec_price) / rec_price * 100
            hit = _check_hit(consensus_v, ret, days)

            windows[str(days)] = {
                "current_price": price_after,
                "return_pct": round(ret, 2),
                "hit": hit,
            }

        # 관점별 적중
        perspective_hits = {}
        for p in rec.get("perspectives", []):
            p_name = p["perspective"]
            p_verdict = p["verdict"]
            p_hits = {}
            for days in eval_days:
                w = windows.get(str(days), {})
                ret = w.get("return_pct")
                if ret is not None and p_verdict not in ("N/A", "DIVIDED", "INSUFFICIENT"):
                    p_hits[str(days)] = _check_hit(p_verdict, ret, days)
                else:
                    p_hits[str(days)] = None
            perspective_hits[p_name] = {"verdict": p_verdict, **p_hits}

        evaluations[ticker] = {
            "name": rec["name"],
            "recommendation_price": rec_price,
            "consensus_verdict": consensus_v,
            "consensus_confidence": rec["consensus_confidence"],
            "windows": windows,
            "perspective_hits": perspective_hits,
        }

    summary = _compute_summary(evaluations, eval_days)
    return {"date": snap_date, "evaluations": evaluations, "summary": summary}


def _compute_summary(evaluations: dict, eval_days: list[int]) -> dict:
    """전체 적중률 요약 계산."""
    # 합의 적중률
    consensus_stats = {}
    for days in eval_days:
        total = 0
        hits = 0
        for ev in evaluations.values():
            w = ev["windows"].get(str(days), {})
            hit = w.get("hit")
            if hit is not None:
                total += 1
                if hit:
                    hits += 1
        consensus_stats[str(days)] = {
            "total": total,
            "hits": hits,
            "rate": round(hits / total * 100, 1) if total > 0 else None,
        }

    # 관점별 적중률
    perspective_stats = {}
    for days in eval_days:
        day_stats = {}
        for ev in evaluations.values():
            for p_name, p_data in ev.get("perspective_hits", {}).items():
                hit = p_data.get(str(days))
                if hit is not None:
                    if p_name not in day_stats:
                        day_stats[p_name] = {"total": 0, "hits": 0}
                    day_stats[p_name]["total"] += 1
                    if hit:
                        day_stats[p_name]["hits"] += 1
        for p_name in day_stats:
            s = day_stats[p_name]
            s["rate"] = round(s["hits"] / s["total"] * 100, 1) if s["total"] > 0 else None
        perspective_stats[str(days)] = day_stats

    # 합의도별 적중률
    confidence_stats = {}
    for days in eval_days:
        conf_map: dict[str, dict] = {}
        for ev in evaluations.values():
            conf = ev["consensus_confidence"]
            w = ev["windows"].get(str(days), {})
            hit = w.get("hit")
            if hit is not None:
                if conf not in conf_map:
                    conf_map[conf] = {"total": 0, "hits": 0}
                conf_map[conf]["total"] += 1
                if hit:
                    conf_map[conf]["hits"] += 1
        for conf in conf_map:
            s = conf_map[conf]
            s["rate"] = round(s["hits"] / s["total"] * 100, 1) if s["total"] > 0 else None
        confidence_stats[str(days)] = conf_map

    return {
        "consensus": consensus_stats,
        "by_perspective": perspective_stats,
        "by_confidence": confidence_stats,
    }


def compute_perspective_weights(min_snapshots: int = 5, eval_window: int = 5) -> dict | None:
    """축적된 스냅샷에서 관점별 적중률 기반 가중치를 계산한다.

    5일 윈도우 적중률을 가중치로 사용.
    min_snapshots 미만이면 None 반환 (cold start → 동등 가중치).

    Returns:
        {"kwangsoo": 0.7, "ouroboros": 0.5, ...} 또는 None
    """
    snapshots = list_snapshots()
    if len(snapshots) < min_snapshots:
        return None

    # 관점별 적중/전체 집계
    stats: dict[str, dict] = {}
    evaluated_count = 0

    for date_str in snapshots:
        snapshot = load_snapshot(date_str)
        if not snapshot:
            continue

        ev = evaluate_snapshot(snapshot, eval_days=[eval_window])
        has_eval = False

        for ticker_ev in ev["evaluations"].values():
            for p_name, p_data in ticker_ev.get("perspective_hits", {}).items():
                hit = p_data.get(str(eval_window))
                if hit is not None:
                    if p_name not in stats:
                        stats[p_name] = {"total": 0, "hits": 0}
                    stats[p_name]["total"] += 1
                    if hit:
                        stats[p_name]["hits"] += 1
                    has_eval = True

        if has_eval:
            evaluated_count += 1

    if evaluated_count < min_snapshots:
        return None

    # 적중률 → 가중치 (최소 0.1, 데이터 없으면 1.0)
    weights = {}
    for name in ("kwangsoo", "ouroboros", "quant", "macro", "value"):
        s = stats.get(name)
        if s and s["total"] > 0:
            weights[name] = max(0.1, round(s["hits"] / s["total"], 3))
        else:
            weights[name] = 1.0

    return weights


def generate_report(days_back: int = 30, eval_days: list[int] | None = None) -> dict:
    """최근 N일간 스냅샷의 성과 리포트 생성.

    Returns:
        {
            "period": "최근 30일",
            "snapshots_count": 15,
            "consensus": {"5": {"total": 30, "hits": 20, "rate": 66.7}, ...},
            "by_perspective": {"5": {"kwangsoo": {...}, ...}, ...},
            "by_confidence": {"5": {"high": {...}, ...}, ...},
            "details": [{"date": "...", "evaluations": {...}}, ...]
        }
    """
    if eval_days is None:
        eval_days = [5, 20]

    snapshots = list_snapshots()
    if not snapshots:
        return {"period": f"최근 {days_back}일", "snapshots_count": 0, "consensus": {}, "by_perspective": {}, "by_confidence": {}, "details": []}

    # 최근 N일 필터
    cutoff = datetime.now()
    recent = []
    for date_str in snapshots:
        try:
            snap_date = datetime.strptime(date_str, "%Y-%m-%d")
            if (cutoff - snap_date).days <= days_back:
                recent.append(date_str)
        except ValueError:
            continue

    details = []
    all_evaluations = {}
    for date_str in recent:
        snapshot = load_snapshot(date_str)
        if not snapshot:
            continue
        ev = evaluate_snapshot(snapshot, eval_days)
        details.append(ev)
        for ticker, ticker_ev in ev["evaluations"].items():
            key = f"{date_str}_{ticker}"
            all_evaluations[key] = ticker_ev

    summary = _compute_summary(all_evaluations, eval_days)

    return {
        "period": f"최근 {days_back}일",
        "snapshots_count": len(recent),
        **summary,
        "details": details,
    }
