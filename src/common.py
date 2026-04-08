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
from src.screener.leading import (
    screen_leading_stocks,
    screen_recommendation_candidates,
)
from src.portfolio.tracker import (
    load_portfolio,
    save_portfolio,
    add_position,
    remove_position,
    set_cash,
    get_cash_balance,
    adjust_cash_balance,
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
        if isinstance(obj, (np.bool_,)):
            return bool(obj)
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
        return yaml.safe_load(config_path.read_text(encoding="utf-8-sig")) or {}
    return {}


def get_index_summary(index_code: str, name: str) -> dict:
    df = fetch_index_ohlcv(index_code, days_back=60)
    if df.empty:
        return {}
    closes = df["close"].dropna().values
    if len(closes) < 20:
        return {}
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
        return {
            "regime": "bull",
            "label": "상승 추세",
            "description": f"코스피 20일 {change_20d:+.1f}%, EMA(20) 상회",
        }
    elif change_20d < -3 and above_ema is not True:
        return {
            "regime": "bear",
            "label": "하락 추세",
            "description": f"코스피 20일 {change_20d:+.1f}%, EMA(20) 하회",
        }
    else:
        return {
            "regime": "sideways",
            "label": "횡보",
            "description": f"코스피 20일 {change_20d:+.1f}%, 방향성 부재",
        }


def _check_causal_graph_age() -> dict | None:
    """인과 그래프 나이를 확인하여 갱신 경고를 반환한다. 90일 이상이면 경고."""
    try:
        from src.causal.graph import CausalGraph, CAUSAL_GRAPH_PATH

        if not CAUSAL_GRAPH_PATH.exists():
            return {
                "warn": True,
                "message": "인과 그래프가 없습니다. `uv run scripts/build_causal.py build`로 구축하세요.",
                "days": None,
            }
        graph = CausalGraph.load()
        updated = graph.metadata.get("updated_at")
        if not updated:
            return None
        age = (datetime.now() - datetime.strptime(updated, "%Y-%m-%d")).days
        if age >= 90:
            return {
                "warn": True,
                "message": f"인과 그래프가 {age}일 경과했습니다. `uv run scripts/build_causal.py build --fresh`로 갱신을 권장합니다.",
                "days": age,
            }
        return {"warn": False, "days": age}
    except Exception:
        return None


def collect_market_data(include_us: bool = False) -> dict:
    """지수 수집 + 시장 레짐 감지 + 인과 그래프 나이 체크

    나스닥/S&P500은 항상 수집 (한국 종목도 미국 지수 영향 받음).
    include_us는 미국 종목 데이터 수집 여부와 레짐 감지 폴백에만 영향.
    """
    market_data = {"date": datetime.now().strftime("%Y-%m-%d")}
    kospi = get_index_summary("KS11", "코스피")
    kosdaq = get_index_summary("KQ11", "코스닥")
    if kospi:
        market_data["kospi"] = kospi
    if kosdaq:
        market_data["kosdaq"] = kosdaq

    # 미국 지수 (항상 수집 — 크로스마켓 인과 분석에 필요)
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
        closes = (
            idx_ohlcv["close"].dropna().values.astype(float)
            if not idx_ohlcv.empty
            else None
        )
        market_data["regime"] = _detect_regime(regime_source, closes)
    else:
        market_data["regime"] = {
            "regime": "unknown",
            "label": "판정 불가",
            "description": "지수 데이터 부족",
        }

    # 인과 그래프 나이 체크
    causal_age = _check_causal_graph_age()
    if causal_age and causal_age.get("warn"):
        market_data["causal_warning"] = causal_age["message"]

    # 매크로 정량 시계열 (Phase 11)
    try:
        from src.data.macro import get_macro_snapshot

        macro_snapshot = get_macro_snapshot()
        if macro_snapshot:
            market_data["macro_quant"] = macro_snapshot
    except Exception:
        pass

    # 매크로 웹 검색 (Phase 10 M4)
    try:
        from src.data.web_search import search_market_context

        config = load_config()
        web_macro = search_market_context(include_us=include_us, config=config)
        if web_macro:
            market_data["web_macro"] = web_macro
    except Exception:
        pass

    # 환율 레짐 감지 (Phase 17)
    try:
        from src.data.macro import fetch_macro_series
        from src.signals.forex import detect_multi_fx_regimes

        config = load_config()
        macro_df = fetch_macro_series()
        if not macro_df.empty:
            fx_regimes = detect_multi_fx_regimes(macro_df, config)
            if fx_regimes:
                market_data["fx_regimes"] = fx_regimes
                # 메인 환율 레짐 = USD/KRW
                if "USD_KRW" in fx_regimes:
                    market_data["fx_regime"] = fx_regimes["USD_KRW"]
    except Exception:
        pass

    return market_data


def get_usd_krw_rate(market_data: dict) -> float | None:
    macro_quant = market_data.get("macro_quant", {})
    usd_krw = macro_quant.get("USD_KRW", {})
    value = usd_krw.get("value")
    if value is None:
        return None
    try:
        return float(value)
    except TypeError, ValueError:
        return None


def build_price_context(ticker: str, current_price: float, market_data: dict) -> dict:
    if not is_us_ticker(ticker):
        price_krw = round(float(current_price))
        return {
            "price": float(current_price),
            "price_currency": "KRW",
            "price_krw": price_krw,
            "price_display": f"{price_krw:,.0f}원",
            "exchange_rate": None,
        }

    exchange_rate = get_usd_krw_rate(market_data)
    price_krw = (
        round(float(current_price) * exchange_rate)
        if exchange_rate is not None
        else None
    )
    if price_krw is not None:
        price_display = (
            f"${float(current_price):,.2f} "
            f"(약 {price_krw:,.0f}원, 환율 {exchange_rate:,.2f}원/USD)"
        )
    else:
        price_display = f"${float(current_price):,.2f}"

    return {
        "price": float(current_price),
        "price_currency": "USD",
        "price_usd": round(float(current_price), 2),
        "price_krw": price_krw,
        "price_display": price_display,
        "exchange_rate": round(exchange_rate, 2) if exchange_rate is not None else None,
    }


def convert_price_to_krw(ticker: str, price: float | None, market_data) -> float | None:
    if price is None:
        return None
    if not is_us_ticker(ticker):
        return float(price)
    exchange_rate = get_usd_krw_rate(market_data)
    if exchange_rate is None:
        return None
    return float(price) * exchange_rate


def format_price_for_display(
    ticker: str,
    price: float | None,
    market_data,
    *,
    include_exchange_rate: bool = False,
) -> str:
    if price is None:
        return "N/A"

    if not is_us_ticker(ticker):
        return f"{float(price):,.0f}원"

    exchange_rate = get_usd_krw_rate(market_data)
    if exchange_rate is None:
        return f"${float(price):,.2f}"

    krw_price = round(float(price) * exchange_rate)
    if include_exchange_rate:
        return f"${float(price):,.2f} (약 {krw_price:,.0f}원, 환율 {exchange_rate:,.2f}원/USD)"
    return f"${float(price):,.2f} (약 {krw_price:,.0f}원)"


def build_cash_summary_for_display(portfolio: dict, market_data=None) -> dict:
    market_data = market_data or {}
    cash_krw = get_cash_balance(portfolio, "KRW")
    cash_usd = get_cash_balance(portfolio, "USD")
    exchange_rate = get_usd_krw_rate(market_data)
    cash_usd_krw = cash_usd * exchange_rate if exchange_rate is not None else None
    total_cash_krw = cash_krw + (cash_usd_krw or 0)

    if cash_usd > 0 and cash_usd_krw is not None:
        display = f"{cash_krw:,.0f}원 + ${cash_usd:,.2f} (약 {cash_usd_krw:,.0f}원)"
    elif cash_usd > 0:
        display = f"{cash_krw:,.0f}원 + ${cash_usd:,.2f}"
    else:
        display = f"{cash_krw:,.0f}원"

    return {
        "cash": total_cash_krw,
        "cash_krw": cash_krw,
        "cash_usd": cash_usd,
        "cash_usd_krw": cash_usd_krw,
        "cash_display": display,
    }


def build_portfolio_summary_for_display(portfolio: dict, market_data=None) -> dict:
    market_data = market_data or {}
    positions = portfolio.get("positions", [])
    cash_summary = build_cash_summary_for_display(portfolio, market_data)
    cash = cash_summary["cash"]

    total_invested = 0.0
    total_market_value = 0.0
    for pos in positions:
        shares = pos.get("shares", 0)
        entry_krw = convert_price_to_krw(
            pos["ticker"], pos.get("entry_price"), market_data
        )
        current_krw = convert_price_to_krw(
            pos["ticker"],
            pos.get("current_price", pos.get("entry_price")),
            market_data,
        )

        if entry_krw is None:
            entry_krw = float(pos.get("entry_price", 0))
        if current_krw is None:
            current_krw = float(pos.get("current_price", pos.get("entry_price", 0)))

        total_invested += float(entry_krw) * shares
        total_market_value += float(current_krw) * shares

    total_pnl = total_market_value - total_invested
    total_pnl_pct = (total_pnl / total_invested * 100) if total_invested > 0 else 0
    total_assets = total_market_value + cash
    cash_pct = (cash / total_assets * 100) if total_assets > 0 else 100

    return {
        "num_positions": len(positions),
        **cash_summary,
        "total_invested": total_invested,
        "total_market_value": total_market_value,
        "total_pnl": total_pnl,
        "total_pnl_pct": total_pnl_pct,
        "total_assets": total_assets,
        "cash_pct": cash_pct,
    }


def format_portfolio_alert(alert: dict, market_data=None) -> str:
    market_data = market_data or {}
    ticker = alert.get("ticker", "")
    name = alert.get("name", ticker)
    current_display = format_price_for_display(
        ticker,
        alert.get("price"),
        market_data,
        include_exchange_rate=True,
    )

    if alert.get("type") == "STOP_LOSS":
        stop_display = format_price_for_display(
            ticker, alert.get("stop_loss"), market_data
        )
        return (
            f"⚠️ 손절매 도달! {name}({ticker}) 현재가 {current_display} ≤ 손절가 {stop_display} "
            "→ 즉시 매도 검토"
        )

    trailing_display = format_price_for_display(
        ticker, alert.get("trailing_stop"), market_data
    )
    peak_display = format_price_for_display(ticker, alert.get("peak"), market_data)
    pnl_pct = alert.get("pnl_pct", 0)
    return (
        f"⚠️ 추적 손절매 도달! {name}({ticker}) 고점 {peak_display} → 현재 {current_display} "
        f"({pnl_pct:+.1f}%) → 매도 검토"
    )


def build_trade_record_display(record: dict, market_data=None) -> dict:
    market_data = market_data or {}
    ticker = record["ticker"]
    sell_shares = record.get("sell_shares", record.get("shares", 0))
    pnl_amount = (
        record.get("sell_price", 0) - record.get("entry_price", 0)
    ) * sell_shares

    return {
        **record,
        "currency": "USD" if is_us_ticker(ticker) else "KRW",
        "entry_price_display": format_price_for_display(
            ticker, record.get("entry_price"), market_data
        ),
        "sell_price_display": format_price_for_display(
            ticker, record.get("sell_price"), market_data, include_exchange_rate=True
        ),
        "pnl_amount": pnl_amount,
        "pnl_amount_display": format_price_for_display(
            ticker, pnl_amount, market_data, include_exchange_rate=True
        ),
    }


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
    return candidates[: max_positions * 2]


def collect_tickers(
    args_tickers: list[str] | None,
    config: dict,
    portfolio: dict,
    do_screen: bool = False,
) -> tuple[set[str], list[dict]]:
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


def has_us_tickers(
    tickers: set[str] | list[str], portfolio: dict | None = None
) -> bool:
    """종목 세트에 미국 종목이 포함되어 있는지."""
    for t in tickers:
        if is_us_ticker(t):
            return True
    if portfolio:
        for pos in portfolio.get("positions", []):
            if is_us_ticker(pos["ticker"]):
                return True
    return False


def analyze_tickers(
    tickers: set[str], config: dict, regime: str | None = None
) -> list[dict]:
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
        futures = {
            executor.submit(analyze_ticker, ticker, config, regime): ticker
            for ticker in tickers
        }
        for future in as_completed(futures):
            try:
                result = future.result()
                if result:
                    results.append(result)
            except Exception:
                pass
    return results


def run_multi_perspective(
    signals_data: list[dict],
    portfolio: dict,
    market_data: dict,
    config: dict,
    use_weights: bool = True,
) -> dict:
    """다관점 분석 실행. ticker → consensus dict 반환.

    Args:
        use_weights: True면 축적된 성과 데이터에서 가중치 자동 로드.
                     False면 동등 가중치 (기존 동작).
    """
    from src.perspectives.base import PerspectiveInput
    from src.consensus.voter import run_all_perspectives
    from src.consensus.scorer import compute_consensus

    # 가중치 로드 (Phase 15: 레짐별 → Phase 5: 전체 → 동등)
    weights = None
    if use_weights:
        # Phase 15: 레짐별 가중치 우선
        regime = market_data.get("regime", {}).get("regime")
        if regime:
            try:
                from src.performance.pattern_analyzer import compute_regime_weights

                weights = compute_regime_weights(regime)
            except Exception:
                pass
        # Phase 5: 전체 가중치 폴백
        if weights is None:
            try:
                from src.performance.tracker import compute_perspective_weights

                weights = compute_perspective_weights()
            except Exception:
                pass

    positions = portfolio.get("positions", [])
    market_context = {}
    for _idx_key in ("kospi", "kosdaq", "nasdaq", "sp500"):
        if _idx_key in market_data:
            market_context[_idx_key] = market_data[_idx_key]
    if "regime" in market_data:
        market_context["regime"] = market_data["regime"]
    if "web_macro" in market_data:
        market_context["web_macro"] = market_data["web_macro"]
    if "fx_regime" in market_data:
        market_context["fx_regime"] = market_data["fx_regime"]
    if "fx_regimes" in market_data:
        market_context["fx_regimes"] = market_data["fx_regimes"]

    # 환율 팩터용 매크로 시계열 (Phase 17)
    macro_df = None
    try:
        from src.data.macro import fetch_macro_series

        macro_df = fetch_macro_series()
    except Exception:
        pass

    fx_regime = market_data.get("fx_regime")

    def _analyze_one(item: dict) -> tuple[str, dict]:
        ticker = item["ticker"]
        pos = next((p for p in positions if p["ticker"] == ticker), None)
        fund = (
            fetch_fundamentals_cached(ticker)
            if not item.get("fundamentals")
            else item["fundamentals"]
        )

        ohlcv = item.get("_ohlcv")
        if ohlcv is None or ohlcv.empty:
            ohlcv = fetch_ohlcv(ticker, days_back=120)

        # 환율 시그널 계산 (Phase 17)
        fx_signal = {}
        if macro_df is not None and not macro_df.empty and fx_regime:
            try:
                from src.signals.forex import compute_fx_signal

                fx_signal = compute_fx_signal(
                    ticker,
                    item["name"],
                    ohlcv,
                    macro_df,
                    fx_regime,
                    config,
                )
            except Exception:
                pass

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
            fx_signal=fx_signal,
        )

        results = run_all_perspectives(pi)
        consensus = compute_consensus(results, weights=weights)

        # 숙의 합의 (Phase 13) — 분기/약한 합의 시 발동
        if config.get("deliberation", {}).get("enabled", True):
            try:
                from src.consensus.deliberator import should_deliberate, deliberate

                if should_deliberate(consensus):
                    consensus = deliberate(consensus, pi)
            except Exception:
                pass

        # consensus에 fx_signal 첨부 (Phase 17 — 출력용)
        if fx_signal:
            consensus["fx_signal"] = fx_signal

        return ticker, consensus

    multi_results = {}
    if len(signals_data) <= 1:
        for item in signals_data:
            ticker, consensus = _analyze_one(item)
            multi_results[ticker] = consensus
    else:
        from concurrent.futures import ThreadPoolExecutor, as_completed

        with ThreadPoolExecutor(max_workers=min(len(signals_data), 4)) as executor:
            futures = {
                executor.submit(_analyze_one, item): item["ticker"]
                for item in signals_data
            }
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

            save_snapshot(
                market_data.get("date", ""), market_data, multi_results, signals_data
            )
        except Exception:
            pass  # 스냅샷 저장 실패는 분석을 중단시키지 않음

    return multi_results


def run_single_perspective(
    perspective_name: str,
    signals_data: list[dict],
    portfolio: dict,
    market_data: dict,
    config: dict,
) -> dict:
    """단일 관점 분석. ticker → PerspectiveResult dict 반환."""
    from src.perspectives.base import PerspectiveInput
    from src.consensus.voter import ALL_PERSPECTIVES

    perspective = next(
        (p for p in ALL_PERSPECTIVES if p.name == perspective_name), None
    )
    if not perspective:
        return {
            "error": f"알 수 없는 관점: {perspective_name}. 사용 가능: kwangsoo, ouroboros, quant, macro, value"
        }

    positions = portfolio.get("positions", [])
    market_context = {}
    for _idx_key in ("kospi", "kosdaq", "nasdaq", "sp500"):
        if _idx_key in market_data:
            market_context[_idx_key] = market_data[_idx_key]
    if "regime" in market_data:
        market_context["regime"] = market_data["regime"]

    results = {}
    for item in signals_data:
        ticker = item["ticker"]
        pos = next((p for p in positions if p["ticker"] == ticker), None)
        fund = (
            fetch_fundamentals_cached(ticker)
            if not item.get("fundamentals")
            else item["fundamentals"]
        )

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


def run_recommend(
    config: dict,
    market: str = "KR",
    top_n: int = 6,
    signal_filter: bool = True,
    use_llm: bool = True,
) -> dict:
    """1-step 종목 추천 파이프라인.

    스크리닝 → 시그널 필터(Bull 4/6+) → 다관점 분석 → BUY 합의 필터.

    Args:
        market: "KR", "US", "ALL", "KOSPI", "KOSDAQ", "NASDAQ", "NYSE"
        top_n: 최종 분석 대상 수
        signal_filter: True면 Bull 4/6+ 종목만 LLM 분석 (비용 절감)
        use_llm: False면 시그널까지만 (LLM 없이)

    Returns:
        {"date", "market", "regime", "screened", "signal_filtered", "analyzed",
         "recommendations": [...], "no_recommendation_reason": str|None}
    """
    include_us = market in ("US", "NASDAQ", "NYSE", "ALL")
    market_data = collect_market_data(include_us=include_us)
    usd_krw_rate = get_usd_krw_rate(market_data)
    min_votes = config.get("signals", {}).get("min_votes", 4)

    # 1단계: 스크리닝
    candidates, screening_meta = screen_recommendation_candidates(
        market=market,
        top_n=top_n,
        config=config,
    )
    if not candidates:
        return {
            "date": market_data["date"],
            "market": market,
            "regime": market_data.get("regime", {}),
            "universe_size": screening_meta.get("universe_size", 0),
            "universe_breakdown": screening_meta.get("universe_breakdown", {}),
            "screened": 0,
            "signal_filtered": 0,
            "analyzed": 0,
            "selection_constraints": screening_meta.get("selection_constraints", {}),
            "recommendations": [],
            "no_recommendation_reason": "스크리닝 실패",
        }

    # 기술적 분석
    tickers = {c["ticker"] for c in candidates}
    signals_data = analyze_tickers(tickers, config)

    if not signals_data:
        return {
            "date": market_data["date"],
            "market": market,
            "regime": market_data.get("regime", {}),
            "universe_size": screening_meta.get("universe_size", 0),
            "universe_breakdown": screening_meta.get("universe_breakdown", {}),
            "screened": len(candidates),
            "signal_filtered": 0,
            "analyzed": 0,
            "selection_constraints": screening_meta.get("selection_constraints", {}),
            "recommendations": [],
            "no_recommendation_reason": "시그널 분석 실패",
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
            price_ctx = build_price_context(
                s["ticker"], s["signals"]["current_price"], market_data
            )
            recs.append(
                {
                    "ticker": s["ticker"],
                    "name": s["name"],
                    **price_ctx,
                    "score": next(
                        (c["score"] for c in candidates if c["ticker"] == s["ticker"]),
                        0,
                    ),
                    "market": next(
                        (c["market"] for c in candidates if c["ticker"] == s["ticker"]),
                        market,
                    ),
                    "sector": next(
                        (c["sector"] for c in candidates if c["ticker"] == s["ticker"]),
                        "기타",
                    ),
                    "selected_by": next(
                        (
                            c.get("selected_by", [])
                            for c in candidates
                            if c["ticker"] == s["ticker"]
                        ),
                        [],
                    ),
                    "signals": {
                        "verdict": s["signals"]["verdict"],
                        "bull_votes": s["signals"]["bull_votes"],
                        "bear_votes": s["signals"]["bear_votes"],
                    },
                    "consensus": None,
                }
            )
        recs.sort(key=lambda x: x["score"], reverse=True)
        return {
            "date": market_data["date"],
            "market": market,
            "usd_krw_rate": usd_krw_rate,
            "regime": market_data.get("regime", {}),
            "universe_size": screening_meta.get("universe_size", 0),
            "universe_breakdown": screening_meta.get("universe_breakdown", {}),
            "screened": len(candidates),
            "signal_filtered": len(bull_data),
            "analyzed": 0,
            "selection_constraints": screening_meta.get("selection_constraints", {}),
            "recommendations": recs,
            "no_recommendation_reason": None if recs else "시그널 Bull 종목 없음",
        }

    if not bull_data:
        return {
            "date": market_data["date"],
            "market": market,
            "regime": market_data.get("regime", {}),
            "universe_size": screening_meta.get("universe_size", 0),
            "universe_breakdown": screening_meta.get("universe_breakdown", {}),
            "screened": len(candidates),
            "signal_filtered": 0,
            "analyzed": 0,
            "selection_constraints": screening_meta.get("selection_constraints", {}),
            "recommendations": [],
            "no_recommendation_reason": "시그널 Bull 종목 없음",
        }

    # 3단계: 다관점 분석 (Bull 종목만)
    portfolio = load_portfolio()
    multi_results = run_multi_perspective(bull_data, portfolio, market_data, config)

    # 4단계: BUY 합의 필터 + action_plan 부착
    from src.portfolio.sizer import check_portfolio_health, compute_action_plan

    regime_str = market_data.get("regime", {}).get("regime", "sideways")
    pf_check = check_portfolio_health(
        portfolio,
        regime_str,
        config,
        exchange_rate=get_usd_krw_rate(market_data),
    )

    recs = []
    for ticker, consensus in multi_results.items():
        if consensus["consensus_verdict"] == "BUY":
            item = next((s for s in bull_data if s["ticker"] == ticker), None)
            if item:
                stop_price = item["signals"]["trailing_stop_10pct"]
                current_price = item["signals"]["current_price"]
                price_ctx = build_price_context(ticker, current_price, market_data)
                exchange_rate = price_ctx.get("exchange_rate")
                plan_current_price = (
                    price_ctx["price_krw"]
                    if price_ctx.get("price_currency") == "USD"
                    and price_ctx.get("price_krw") is not None
                    else current_price
                )
                plan_stop_price = (
                    round(stop_price * exchange_rate)
                    if price_ctx.get("price_currency") == "USD"
                    and exchange_rate is not None
                    else stop_price
                )
                plan = compute_action_plan(
                    ticker,
                    plan_current_price,
                    plan_stop_price,
                    consensus["consensus_verdict"],
                    consensus["confidence"],
                    portfolio,
                    pf_check,
                    config,
                )
                rec_entry = {
                    "ticker": ticker,
                    "name": item["name"],
                    **price_ctx,
                    "score": next(
                        (c["score"] for c in candidates if c["ticker"] == ticker), 0
                    ),
                    "market": next(
                        (c["market"] for c in candidates if c["ticker"] == ticker),
                        market,
                    ),
                    "sector": next(
                        (c["sector"] for c in candidates if c["ticker"] == ticker),
                        "기타",
                    ),
                    "selected_by": next(
                        (
                            c.get("selected_by", [])
                            for c in candidates
                            if c["ticker"] == ticker
                        ),
                        [],
                    ),
                    "signals": {
                        "verdict": item["signals"]["verdict"],
                        "bull_votes": item["signals"]["bull_votes"],
                        "bear_votes": item["signals"]["bear_votes"],
                    },
                    "consensus": consensus,
                }
                if plan:
                    if price_ctx.get("price_currency") == "USD":
                        plan["entry_price_usd"] = price_ctx.get("price_usd")
                        plan["stop_loss_usd"] = round(stop_price, 2)
                        plan["exchange_rate"] = exchange_rate
                        plan["native_currency"] = "USD"
                    rec_entry["action_plan"] = plan
                recs.append(rec_entry)

    recs.sort(key=lambda x: x["score"], reverse=True)

    reason = None
    if not recs:
        reason = "BUY 합의 종목 없음"

    return {
        "date": market_data["date"],
        "market": market,
        "usd_krw_rate": usd_krw_rate,
        "regime": market_data.get("regime", {}),
        "universe_size": screening_meta.get("universe_size", 0),
        "universe_breakdown": screening_meta.get("universe_breakdown", {}),
        "screened": len(candidates),
        "signal_filtered": len(bull_data),
        "analyzed": len(multi_results),
        "selection_constraints": screening_meta.get("selection_constraints", {}),
        "recommendations": recs,
        "no_recommendation_reason": reason,
    }


def build_signals_json(signals_data: list[dict], market_data=None) -> list[dict]:
    """시그널 데이터를 JSON 출력용으로 변환."""
    market_data = market_data or {}
    return [
        {
            "ticker": s["ticker"],
            "name": s["name"],
            **build_price_context(
                s["ticker"], s["signals"]["current_price"], market_data
            ),
            "verdict": s["signals"]["verdict"],
            "bull_votes": s["signals"]["bull_votes"],
            "bear_votes": s["signals"]["bear_votes"],
            "rsi": s["signals"]["signals"]["rsi"]["value"],
            "trailing_stop": s["signals"]["trailing_stop_10pct"],
            "trailing_stop_display": format_price_for_display(
                s["ticker"], s["signals"]["trailing_stop_10pct"], market_data
            ),
            "trailing_stop_krw": convert_price_to_krw(
                s["ticker"], s["signals"]["trailing_stop_10pct"], market_data
            ),
            "change_5d": s["signals"]["change_5d"],
            "change_20d": s["signals"]["change_20d"],
            "per": s.get("fundamentals", {}).get("per"),
            "pbr": s.get("fundamentals", {}).get("pbr"),
        }
        for s in signals_data
    ]
