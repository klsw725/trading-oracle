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


def collect_market_data() -> dict:
    """코스피/코스닥 지수 수집"""
    market_data = {"date": datetime.now().strftime("%Y-%m-%d")}
    kospi = get_index_summary("KS11", "코스피")
    kosdaq = get_index_summary("KQ11", "코스닥")
    if kospi:
        market_data["kospi"] = kospi
    if kosdaq:
        market_data["kosdaq"] = kosdaq
    return market_data


def analyze_ticker(ticker: str, config: dict) -> dict | None:
    """종목 기술적 분석 + 펀더멘털. 실패 시 None."""
    name = get_ticker_name(ticker)
    if not name:
        return None

    ohlcv = fetch_ohlcv(ticker, days_back=120)
    if ohlcv.empty or len(ohlcv) < 60:
        return None

    signals = compute_signals(ohlcv, config)
    if "error" in signals:
        return None

    fund = fetch_naver_fundamentals(ticker)
    cap_data = fetch_market_cap(ticker)
    market_cap = cap_data.get("market_cap", 0)

    return {
        "ticker": ticker,
        "name": name,
        "signals": signals,
        "fundamentals": fund,
        "market_cap": market_cap,
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


def analyze_tickers(tickers: set[str], config: dict) -> list[dict]:
    """여러 종목 분석. 성공한 것만 반환."""
    results = []
    for ticker in tickers:
        result = analyze_ticker(ticker, config)
        if result:
            results.append(result)
    return results


def run_multi_perspective(signals_data: list[dict], portfolio: dict, market_data: dict, config: dict) -> dict:
    """다관점 분석 실행. ticker → consensus dict 반환."""
    from src.perspectives.base import PerspectiveInput
    from src.consensus.voter import run_all_perspectives
    from src.consensus.scorer import compute_consensus

    positions = portfolio.get("positions", [])
    market_context = {}
    if "kospi" in market_data:
        market_context["kospi"] = market_data["kospi"]
    if "kosdaq" in market_data:
        market_context["kosdaq"] = market_data["kosdaq"]

    multi_results = {}
    for item in signals_data:
        ticker = item["ticker"]
        pos = next((p for p in positions if p["ticker"] == ticker), None)
        fund = fetch_fundamentals_cached(ticker) if not item.get("fundamentals") else item["fundamentals"]

        pi = PerspectiveInput(
            ticker=ticker,
            name=item["name"],
            ohlcv=fetch_ohlcv(ticker, days_back=120),
            signals=item["signals"],
            fundamentals=fund,
            position=pos,
            market_context=market_context,
            config=config,
        )

        results = run_all_perspectives(pi)
        consensus = compute_consensus(results)
        multi_results[ticker] = consensus

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

    results = {}
    for item in signals_data:
        ticker = item["ticker"]
        pos = next((p for p in positions if p["ticker"] == ticker), None)
        fund = fetch_fundamentals_cached(ticker) if not item.get("fundamentals") else item["fundamentals"]

        pi = PerspectiveInput(
            ticker=ticker,
            name=item["name"],
            ohlcv=fetch_ohlcv(ticker, days_back=120),
            signals=item["signals"],
            fundamentals=fund,
            position=pos,
            market_context=market_context,
            config=config,
        )

        result = perspective.analyze(pi)
        results[ticker] = result.to_dict()

    return results


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
