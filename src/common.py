"""공유 유틸리티 — scripts/ 와 main.py 모두 사용"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import yaml

from src.data.market import (
    fetch_index_ohlcv,
    fetch_market_cap,
    fetch_ohlcv,
    get_ticker_name,
    is_us_ticker,
)
from src.data.fundamentals import fetch_naver_fundamentals, fetch_fundamentals_cached
from src.signals.technical import compute_signals
from src.screener.leading import screen_leading_stocks
from src.portfolio.tracker import (
    load_portfolio,
    save_portfolio,
    add_position,
    remove_position,
    set_cash,
    update_positions,
    get_portfolio_summary,
)


class NumEncoder(json.JSONEncoder):
    """numpy 타입 JSON 직렬화"""

    def default(self, obj):
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return super().default(obj)


def json_dump(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, cls=NumEncoder)


def ensure_project_root():
    """프로젝트 루트로 chdir. scripts/ 등에서 호출 시 상대경로 보장."""
    # pyproject.toml이 있는 디렉터리 = 프로젝트 루트
    current = Path(__file__).resolve().parent.parent  # src/ → 프로젝트 루트
    if (current / "pyproject.toml").exists():
        os.chdir(current)
        return
    # fallback: CWD에서 탐색
    cwd = Path.cwd()
    for p in [cwd, cwd.parent, cwd.parent.parent]:
        if (p / "pyproject.toml").exists():
            os.chdir(p)
            return


def load_config() -> dict:
    config_path = Path("config.yaml")
    if config_path.exists():
        return yaml.safe_load(config_path.read_text()) or {}
    return {}


def get_index_summary(index_code: str, name: str) -> dict:
    df = fetch_index_ohlcv(index_code, days_back=60)
    if df.empty or len(df) < 20:
        return {}
    closes = df["close"].values
    return {
        "name": name,
        "close": float(closes[-1]),
        "change_5d": float((closes[-1] - closes[-5]) / closes[-5] * 100),
        "change_20d": float((closes[-1] - closes[-20]) / closes[-20] * 100),
    }


def _detect_regime(index_data: dict, ohlcv_closes: np.ndarray | None = None) -> dict:
    """코스피 지수 데이터에서 시장 레짐을 분류한다.

    판정 기준:
      bull: 20일 수익률 > 3% AND 종가 > EMA(20)
      bear: 20일 수익률 < -3% AND 종가 < EMA(20)
      sideways: 그 외

    Returns:
        {"regime": "bull"|"bear"|"sideways", "label": "상승 추세"|..., "description": "..."}
    """
    change_20d = index_data.get("change_20d", 0)

    # EMA(20) 비교 (OHLCV 데이터 있을 때만)
    above_ema = None
    if ohlcv_closes is not None and len(ohlcv_closes) >= 20:
        from src.signals.technical import ema
        ema20 = ema(ohlcv_closes[-30:], 20)
        above_ema = ohlcv_closes[-1] > ema20[-1]

    if change_20d > 3 and above_ema is not False:
        return {"regime": "bull", "label": "상승 추세", "description": f"코스피 20일 {change_20d:+.1f}%, EMA(20) 상회"}
    elif change_20d < -3 and above_ema is not True:
        return {"regime": "bear", "label": "하락 추세", "description": f"코스피 20일 {change_20d:+.1f}%, EMA(20) 하회"}
    else:
        return {"regime": "sideways", "label": "횡보", "description": f"코스피 20일 {change_20d:+.1f}%, 방향성 부재"}


def _check_causal_graph_age() -> dict | None:
    """인과 그래프 나이를 확인하여 갱신 경고를 반환한다. 90일 이상이면 경고."""
    try:
        from src.causal.graph import CausalGraph, CAUSAL_GRAPH_PATH
        if not CAUSAL_GRAPH_PATH.exists():
            return {"warn": True, "message": "인과 그래프가 없습니다. `uv run scripts/build_causal.py build`로 구축하세요.", "days": None}
        graph = CausalGraph.load()
        updated = graph.metadata.get("updated_at")
        if not updated:
            return None
        age = (datetime.now() - datetime.strptime(updated, "%Y-%m-%d")).days
        if age >= 90:
            return {"warn": True, "message": f"인과 그래프가 {age}일 경과했습니다. `uv run scripts/build_causal.py build --fresh`로 갱신을 권장합니다.", "days": age}
        return {"warn": False, "days": age}
    except Exception:
        return None


def collect_market_data(include_us: bool = False) -> dict:
    """지수 수집 + 시장 레짐 감지 + 인과 그래프 나이 체크"""
    market_data = {"date": datetime.now().strftime("%Y-%m-%d")}
    kospi = get_index_summary("KS11", "코스피")
    kosdaq = get_index_summary("KQ11", "코스닥")
    if kospi:
        market_data["kospi"] = kospi
    if kosdaq:
        market_data["kosdaq"] = kosdaq

    # 미국 지수
    if include_us:
        nasdaq = get_index_summary("IXIC", "나스닥")
        sp500 = get_index_summary("US500", "S&P 500")
        if nasdaq:
            market_data["nasdaq"] = nasdaq
        if sp500:
            market_data["sp500"] = sp500

    # 레짐 감지 (코스피 기준, 없으면 나스닥)
    regime_source = kospi or (market_data.get("nasdaq") if include_us else None)
    if regime_source:
        idx_code = "KS11" if kospi else "IXIC"
        idx_ohlcv = fetch_index_ohlcv(idx_code, days_back=60)
        closes = idx_ohlcv["close"].values.astype(float) if not idx_ohlcv.empty else None
        market_data["regime"] = _detect_regime(regime_source, closes)
    else:
        market_data["regime"] = {"regime": "unknown", "label": "판정 불가", "description": "지수 데이터 부족"}

    # 인과 그래프 나이 체크
    causal_age = _check_causal_graph_age()
    if causal_age and causal_age.get("warn"):
        market_data["causal_warning"] = causal_age["message"]

    return market_data


def analyze_ticker(ticker: str, config: dict, regime: str | None = None) -> dict | None:
    """종목 기술적 분석 + 펀더멘털. 실패 시 None."""
    name = get_ticker_name(ticker)
    if not name:
        return None

    ohlcv = fetch_ohlcv(ticker, days_back=120)
    if ohlcv.empty or len(ohlcv) < 60:
        return None

    signals = compute_signals(ohlcv, config, regime=regime)
    if "error" in signals:
        return None

    fund = fetch_fundamentals_cached(ticker)
    cap_data = fetch_market_cap(ticker)
    market_cap = cap_data.get("market_cap", 0)

    # 웹 검색 (Phase 10)
    web_context = {}
    try:
        from src.data.web_search import search_ticker_context
        web_context = search_ticker_context(ticker, name, config)
    except Exception:
        pass

    return {
        "ticker": ticker,
        "name": name,
        "signals": signals,
        "fundamentals": fund,
        "market_cap": market_cap,
        "web_context": web_context,
        "_ohlcv": ohlcv,  # 메모리 내 재사용 (JSON 직렬화 대상 아님)
    }


def run_screening(config: dict) -> list[dict]:
    """주도주 스크리닝. 후보 리스트 반환."""
    candidates = screen_leading_stocks(market="ALL", top_n=30)
    if not candidates:
        return []
    max_positions = config.get("max_positions", 3)
    return candidates[:max_positions * 2]


def collect_tickers(args_tickers: list[str] | None, config: dict, portfolio: dict, do_screen: bool = False) -> tuple[set[str], list[dict]]:
    """분석할 종목 세트 수집. (tickers, screening_candidates) 반환."""
    tickers = set()
    for pos in portfolio.get("positions", []):
        tickers.add(pos["ticker"])
    if args_tickers:
        for t in args_tickers:
            tickers.add(t)
    if config.get("watchlist"):
        for t in config["watchlist"]:
            tickers.add(t)

    candidates = []
    if do_screen or not tickers:
        candidates = run_screening(config)
        for c in candidates:
            tickers.add(c["ticker"])

    return tickers, candidates


def has_us_tickers(tickers: set[str] | list[str], portfolio: dict | None = None) -> bool:
    """종목 세트에 미국 종목이 포함되어 있는지."""
    for t in tickers:
        if is_us_ticker(t):
            return True
    if portfolio:
        for pos in portfolio.get("positions", []):
            if is_us_ticker(pos["ticker"]):
                return True
    return False


def analyze_tickers(tickers: set[str], config: dict, regime: str | None = None) -> list[dict]:
    """여러 종목 병렬 분석. 성공한 것만 반환."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    if len(tickers) <= 1:
        results = []
        for ticker in tickers:
            result = analyze_ticker(ticker, config, regime=regime)
            if result:
                results.append(result)
        return results

    results = []
    with ThreadPoolExecutor(max_workers=min(len(tickers), 6)) as executor:
        futures = {executor.submit(analyze_ticker, ticker, config, regime): ticker for ticker in tickers}
        for future in as_completed(futures):
            try:
                result = future.result()
                if result:
                    results.append(result)
            except Exception:
                pass
    return results


def run_multi_perspective(signals_data: list[dict], portfolio: dict, market_data: dict, config: dict, use_weights: bool = True) -> dict:
    """다관점 분석 실행. ticker → consensus dict 반환.

    Args:
        use_weights: True면 축적된 성과 데이터에서 가중치 자동 로드.
                     False면 동등 가중치 (기존 동작).
    """
    from src.perspectives.base import PerspectiveInput
    from src.consensus.voter import run_all_perspectives
    from src.consensus.scorer import compute_consensus

    # 가중치 로드
    weights = None
    if use_weights:
        try:
            from src.performance.tracker import compute_perspective_weights
            weights = compute_perspective_weights()
        except Exception:
            pass

    positions = portfolio.get("positions", [])
    market_context = {}
    if "kospi" in market_data:
        market_context["kospi"] = market_data["kospi"]
    if "kosdaq" in market_data:
        market_context["kosdaq"] = market_data["kosdaq"]
    if "regime" in market_data:
        market_context["regime"] = market_data["regime"]

    def _analyze_one(item: dict) -> tuple[str, dict]:
        ticker = item["ticker"]
        pos = next((p for p in positions if p["ticker"] == ticker), None)
        fund = fetch_fundamentals_cached(ticker) if not item.get("fundamentals") else item["fundamentals"]

        ohlcv = item.get("_ohlcv")
        if ohlcv is None or ohlcv.empty:
            ohlcv = fetch_ohlcv(ticker, days_back=120)

        pi = PerspectiveInput(
            ticker=ticker,
            name=item["name"],
            ohlcv=ohlcv,
            signals=item["signals"],
            fundamentals=fund,
            position=pos,
            market_context=market_context,
            config=config,
            web_context=item.get("web_context", {}),
        )

        results = run_all_perspectives(pi)
        consensus = compute_consensus(results, weights=weights)
        return ticker, consensus

    multi_results = {}
    if len(signals_data) <= 1:
        for item in signals_data:
            ticker, consensus = _analyze_one(item)
            multi_results[ticker] = consensus
    else:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        with ThreadPoolExecutor(max_workers=min(len(signals_data), 4)) as executor:
            futures = {executor.submit(_analyze_one, item): item["ticker"] for item in signals_data}
            for future in as_completed(futures):
                try:
                    ticker, consensus = future.result()
                    multi_results[ticker] = consensus
                except Exception:
                    pass

    # 스냅샷 자동 저장
    if multi_results:
        try:
            from src.performance.tracker import save_snapshot
            save_snapshot(market_data.get("date", ""), market_data, multi_results, signals_data)
        except Exception:
            pass  # 스냅샷 저장 실패는 분석을 중단시키지 않음

    return multi_results


def run_single_perspective(perspective_name: str, signals_data: list[dict], portfolio: dict, market_data: dict, config: dict) -> dict:
    """단일 관점 분석. ticker → PerspectiveResult dict 반환."""
    from src.perspectives.base import PerspectiveInput
    from src.consensus.voter import ALL_PERSPECTIVES

    perspective = next((p for p in ALL_PERSPECTIVES if p.name == perspective_name), None)
    if not perspective:
        return {"error": f"알 수 없는 관점: {perspective_name}. 사용 가능: kwangsoo, ouroboros, quant, macro, value"}

    positions = portfolio.get("positions", [])
    market_context = {}
    if "kospi" in market_data:
        market_context["kospi"] = market_data["kospi"]
    if "kosdaq" in market_data:
        market_context["kosdaq"] = market_data["kosdaq"]
    if "regime" in market_data:
        market_context["regime"] = market_data["regime"]

    results = {}
    for item in signals_data:
        ticker = item["ticker"]
        pos = next((p for p in positions if p["ticker"] == ticker), None)
        fund = fetch_fundamentals_cached(ticker) if not item.get("fundamentals") else item["fundamentals"]

        ohlcv = item.get("_ohlcv")
        if ohlcv is None or ohlcv.empty:
            ohlcv = fetch_ohlcv(ticker, days_back=120)

        pi = PerspectiveInput(
            ticker=ticker,
            name=item["name"],
            ohlcv=ohlcv,
            signals=item["signals"],
            fundamentals=fund,
            position=pos,
            market_context=market_context,
            config=config,
        )

        result = perspective.analyze(pi)
        results[ticker] = result.to_dict()

    return results


def run_recommend(config: dict, market: str = "ALL", top_n: int = 6, signal_filter: bool = True, use_llm: bool = True) -> dict:
    """1-step 종목 추천 파이프라인.

    스크리닝 → 시그널 필터(Bull 4/6+) → 다관점 분석 → BUY 합의 필터.

    Args:
        market: "ALL", "KOSPI", "KOSDAQ", "US", "NASDAQ", "NYSE"
        top_n: 스크리닝 후보 수
        signal_filter: True면 Bull 4/6+ 종목만 LLM 분석 (비용 절감)
        use_llm: False면 시그널까지만 (LLM 없이)

    Returns:
        {"date", "market", "regime", "screened", "signal_filtered", "analyzed",
         "recommendations": [...], "no_recommendation_reason": str|None}
    """
    include_us = market in ("US", "NASDAQ", "NYSE")
    market_data = collect_market_data(include_us=include_us)
    min_votes = config.get("signals", {}).get("min_votes", 4)

    # 1단계: 스크리닝
    candidates = screen_leading_stocks(market=market, top_n=top_n)
    if not candidates:
        return {
            "date": market_data["date"], "market": market, "regime": market_data.get("regime", {}),
            "screened": 0, "signal_filtered": 0, "analyzed": 0,
            "recommendations": [], "no_recommendation_reason": "스크리닝 실패",
        }

    # 기술적 분석
    tickers = {c["ticker"] for c in candidates}
    signals_data = analyze_tickers(tickers, config)

    if not signals_data:
        return {
            "date": market_data["date"], "market": market, "regime": market_data.get("regime", {}),
            "screened": len(candidates), "signal_filtered": 0, "analyzed": 0,
            "recommendations": [], "no_recommendation_reason": "시그널 분석 실패",
        }

    # 2단계: 시그널 필터
    if signal_filter:
        bull_data = [s for s in signals_data if s["signals"]["bull_votes"] >= min_votes]
    else:
        bull_data = signals_data

    if not use_llm:
        # LLM 없이 시그널 Bull 종목만 반환
        recs = []
        for s in bull_data:
            recs.append({
                "ticker": s["ticker"], "name": s["name"], "price": s["signals"]["current_price"],
                "score": next((c["score"] for c in candidates if c["ticker"] == s["ticker"]), 0),
                "signals": {"verdict": s["signals"]["verdict"], "bull_votes": s["signals"]["bull_votes"], "bear_votes": s["signals"]["bear_votes"]},
                "consensus": None,
            })
        recs.sort(key=lambda x: x["score"], reverse=True)
        return {
            "date": market_data["date"], "market": market, "regime": market_data.get("regime", {}),
            "screened": len(candidates), "signal_filtered": len(bull_data), "analyzed": 0,
            "recommendations": recs, "no_recommendation_reason": None if recs else "시그널 Bull 종목 없음",
        }

    if not bull_data:
        return {
            "date": market_data["date"], "market": market, "regime": market_data.get("regime", {}),
            "screened": len(candidates), "signal_filtered": 0, "analyzed": 0,
            "recommendations": [], "no_recommendation_reason": "시그널 Bull 종목 없음",
        }

    # 3단계: 다관점 분석 (Bull 종목만)
    portfolio = load_portfolio()
    multi_results = run_multi_perspective(bull_data, portfolio, market_data, config)

    # 4단계: BUY 합의 필터
    recs = []
    for ticker, consensus in multi_results.items():
        if consensus["consensus_verdict"] == "BUY":
            item = next((s for s in bull_data if s["ticker"] == ticker), None)
            if item:
                recs.append({
                    "ticker": ticker, "name": item["name"], "price": item["signals"]["current_price"],
                    "score": next((c["score"] for c in candidates if c["ticker"] == ticker), 0),
                    "signals": {"verdict": item["signals"]["verdict"], "bull_votes": item["signals"]["bull_votes"], "bear_votes": item["signals"]["bear_votes"]},
                    "consensus": consensus,
                })

    recs.sort(key=lambda x: x["score"], reverse=True)

    reason = None
    if not recs:
        reason = "BUY 합의 종목 없음"

    return {
        "date": market_data["date"], "market": market, "regime": market_data.get("regime", {}),
        "screened": len(candidates), "signal_filtered": len(bull_data), "analyzed": len(multi_results),
        "recommendations": recs, "no_recommendation_reason": reason,
    }


def build_signals_json(signals_data: list[dict]) -> list[dict]:
    """시그널 데이터를 JSON 출력용으로 변환."""
    return [
        {
            "ticker": s["ticker"],
            "name": s["name"],
            "price": s["signals"]["current_price"],
            "verdict": s["signals"]["verdict"],
            "bull_votes": s["signals"]["bull_votes"],
            "bear_votes": s["signals"]["bear_votes"],
            "rsi": s["signals"]["signals"]["rsi"]["value"],
            "trailing_stop": s["signals"]["trailing_stop_10pct"],
            "change_5d": s["signals"]["change_5d"],
            "change_20d": s["signals"]["change_20d"],
            "per": s.get("fundamentals", {}).get("per"),
            "pbr": s.get("fundamentals", {}).get("pbr"),
        }
        for s in signals_data
    ]
