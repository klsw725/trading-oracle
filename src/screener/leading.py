"""주도주 스크리닝 — 이광수 철학 기반

주도주 = 주가가 오르고 있고 + 오르는 이유가 분명한 종목
- 시가총액 상위
- 최근 20일 수익률 양수
- PER/PBR 합리적
- 거래량 활발
"""

from __future__ import annotations

from collections import Counter
from math import ceil
from typing import Any

import FinanceDataReader as fdr
import httpx
import pandas as pd

from src.data.market import fetch_ohlcv, load_krx_listing
from src.data.fundamentals import fetch_naver_fundamentals
from src.data.sectors import load_sector_lookup
from src.data.toss import TossApiError, get_toss_client
from src.portfolio.correlation import classify_sector


RECOMMEND_MARKET_COMPONENTS = {
    "KR": ["KOSPI", "KOSDAQ"],
    "US": ["NASDAQ", "NYSE"],
    "ALL": ["KOSPI", "KOSDAQ", "NASDAQ", "NYSE"],
}

RECOMMEND_DEFAULT_UNIVERSE_SIZE = {
    "KOSPI": 50,
    "KOSDAQ": 50,
    "NASDAQ": 50,
    "NYSE": 50,
}

RECOMMEND_DEFAULT_DIVERSIFICATION = {
    "sector_cap": 1,
    "prefer_market_balance": True,
    "relax_market_balance_if_needed": True,
    "relax_sector_cap_if_needed": True,
}

Candidate = dict[str, Any]


def screen_leading_stocks(market: str = "ALL", top_n: int = 30) -> list[Candidate]:
    if market in ("NASDAQ", "NYSE", "US"):
        return _screen_us_stocks(market, top_n)

    listing = load_krx_listing()
    if listing.empty:
        return []

    if market == "KOSPI":
        listing = pd.DataFrame(listing.loc[listing["Market"] == "KOSPI"])
    elif market == "KOSDAQ":
        listing = pd.DataFrame(listing.loc[listing["Market"] == "KOSDAQ"])

    common_shares = pd.Series(listing["Code"]).map(lambda code: str(code).endswith("0"))
    listing = pd.DataFrame(listing.loc[common_shares])
    listing = pd.DataFrame(listing.sort_values("Marcap", ascending=False).head(top_n))
    sector_lookup = load_sector_lookup([market])

    candidates = []
    for _, row in listing.iterrows():
        candidate = _build_candidate(
            ticker=str(row["Code"]),
            name=str(row["Name"]),
            market=str(row["Market"]),
            market_cap=row.get("Marcap", 0),
            sector_lookup=sector_lookup,
        )
        if candidate:
            candidates.append(candidate)

    candidates.sort(key=_candidate_sort_key, reverse=True)
    return candidates


def screen_recommendation_candidates(
    market: str = "KR",
    top_n: int = 6,
    config: dict[str, Any] | None = None,
) -> tuple[list[Candidate], dict[str, Any]]:
    recommend_cfg = config.get("recommend", {}) if config else {}
    universe_size = dict(RECOMMEND_DEFAULT_UNIVERSE_SIZE)
    universe_size.update(recommend_cfg.get("universe_size", {}))

    diversification = dict(RECOMMEND_DEFAULT_DIVERSIFICATION)
    diversification.update(recommend_cfg.get("diversification", {}))

    components = get_recommend_market_components(market)
    universe = []
    breakdown = {}
    for component in components:
        market_universe = _load_market_universe(
            component,
            int(
                universe_size.get(component, RECOMMEND_DEFAULT_UNIVERSE_SIZE[component])
            ),
        )
        breakdown[component] = len(market_universe)
        universe.extend(market_universe)

    selected, selection_meta = select_diversified_candidates(
        universe,
        top_n=top_n,
        market=market,
        diversification=diversification,
    )

    metadata: dict[str, Any] = {
        "market": market,
        "universe_size": len(universe),
        "universe_breakdown": breakdown,
        "screened": len(selected),
        "selection_constraints": selection_meta,
    }
    if config and config.get("v4", {}).get("native_capture", {}).get("enabled") is True:
        selected_by_ticker = {
            candidate["ticker"]: candidate for candidate in selected
        }
        capture_universe: Any = []
        for candidate in sorted(universe, key=_candidate_sort_key, reverse=True):
            member = dict(candidate)
            selected_candidate = selected_by_ticker.get(candidate["ticker"])
            member["selected"] = selected_candidate is not None
            member["selected_by"] = (
                selected_candidate.get("selected_by", [])
                if selected_candidate is not None
                else []
            )
            if selected_candidate is not None:
                member.pop("skipped_reason", None)
            capture_universe.append(member)
        metadata["capture_universe"] = capture_universe
    return selected, metadata


def get_recommend_market_components(market: str) -> list[str]:
    return RECOMMEND_MARKET_COMPONENTS.get(market, [market])


def select_diversified_candidates(
    candidates: list[Candidate],
    top_n: int,
    market: str,
    diversification: dict[str, Any] | None = None,
) -> tuple[list[Candidate], dict[str, Any]]:
    if top_n <= 0 or not candidates:
        return [], {
            "sector_cap": int(RECOMMEND_DEFAULT_DIVERSIFICATION["sector_cap"]),
            "prefer_market_balance": bool(
                RECOMMEND_DEFAULT_DIVERSIFICATION["prefer_market_balance"]
            ),
            "relaxed": False,
            "selected_markets": {},
            "selected_sectors": {},
        }

    settings = dict(RECOMMEND_DEFAULT_DIVERSIFICATION)
    if diversification:
        settings.update(diversification)

    ordered = sorted(candidates, key=_candidate_sort_key, reverse=True)
    for rank, candidate in enumerate(ordered, start=1):
        candidate["rank_before_filter"] = rank
    components = get_recommend_market_components(market)
    composite_market = len(components) > 1
    base_sector_cap = int(settings.get("sector_cap", 1))
    prefer_market_balance = (
        bool(settings.get("prefer_market_balance", True)) and composite_market
    )
    market_cap = ceil(top_n / len(components)) if prefer_market_balance else None

    phase_rules: list[dict[str, Any]] = [
        {
            "name": "primary",
            "sector_cap": base_sector_cap,
            "market_cap": market_cap,
            "selected_by": ["score", "sector_diversity"]
            + (["market_balance"] if market_cap is not None else []),
        }
    ]

    if market_cap is not None and settings.get("relax_market_balance_if_needed", True):
        phase_rules.append(
            {
                "name": "relax_market_balance",
                "sector_cap": base_sector_cap,
                "market_cap": None,
                "selected_by": ["score", "sector_diversity", "relaxed_market_balance"],
            }
        )

    if settings.get("relax_sector_cap_if_needed", True):
        phase_rules.append(
            {
                "name": "relax_sector_cap",
                "sector_cap": None,
                "market_cap": None,
                "selected_by": ["score", "relaxed_sector_cap"],
            }
        )

    phase_rules.append(
        {
            "name": "fill_by_score",
            "sector_cap": None,
            "market_cap": None,
            "selected_by": ["score_fill"],
        }
    )

    selected = []
    selected_tickers = set()
    sector_counts = Counter()
    market_counts = Counter()
    relaxed = False

    for phase_index, phase in enumerate(phase_rules):
        for candidate in ordered:
            ticker = candidate["ticker"]
            if ticker in selected_tickers:
                continue
            if len(selected) >= top_n:
                break
            if not _passes_selection_constraints(
                candidate,
                sector_counts=sector_counts,
                market_counts=market_counts,
                sector_cap=phase["sector_cap"],
                market_cap=phase["market_cap"],
            ):
                continue

            picked = dict(candidate)
            picked["selected_by"] = list(phase["selected_by"])
            selected.append(picked)
            selected_tickers.add(ticker)
            sector_counts[picked["sector"]] += 1
            market_counts[picked["market"]] += 1
            if phase_index > 0:
                relaxed = True

        if len(selected) >= top_n:
            break

    for candidate in ordered:
        if candidate["ticker"] in selected_tickers:
            continue
        candidate.setdefault("skipped_reason", "selection_cutoff")

    metadata = {
        "sector_cap": base_sector_cap,
        "prefer_market_balance": prefer_market_balance,
        "relaxed": relaxed,
        "selected_markets": dict(market_counts),
        "selected_sectors": dict(sector_counts),
    }
    return selected, metadata


def _passes_selection_constraints(
    candidate: Candidate,
    sector_counts: Counter[str],
    market_counts: Counter[str],
    sector_cap: int | None,
    market_cap: int | None,
) -> bool:
    sector = candidate["sector"]
    market = candidate["market"]
    if sector_cap is not None and sector_counts[sector] >= sector_cap:
        candidate["skipped_reason"] = "same_sector_cap"
        return False
    if market_cap is not None and market_counts[market] >= market_cap:
        candidate["skipped_reason"] = "market_balance_cap"
        return False
    return True


def _load_market_universe(market: str, universe_size: int) -> list[Candidate]:
    toss_universe = _load_toss_market_universe(market, universe_size)
    if toss_universe:
        return toss_universe
    if market in ("KOSPI", "KOSDAQ"):
        return _load_kr_market_universe(market, universe_size)
    return _load_us_market_universe(market, universe_size)


def _load_toss_market_universe(market: str, universe_size: int) -> list[Candidate]:
    toss = get_toss_client()
    if toss is None:
        return []
    country = "KR" if market in ("KOSPI", "KOSDAQ") else "US"
    try:
        rankings = toss.rankings(country, 100)
        symbols = [str(item.get("symbol", "")) for item in rankings]
        stocks = toss.stocks([symbol for symbol in symbols if symbol])
    except (httpx.HTTPError, TossApiError, KeyError, TypeError, ValueError):
        return []

    stock_lookup = {str(item.get("symbol", "")): item for item in stocks}
    candidates = []
    for ranking in rankings:
        symbol = str(ranking.get("symbol", ""))
        stock = stock_lookup.get(symbol)
        if not stock or stock.get("market") != market:
            continue
        price_data = ranking.get("price", {})
        if not isinstance(price_data, dict):
            continue
        price = _safe_number(price_data.get("lastPrice"))
        shares = _safe_number(stock.get("sharesOutstanding"))
        candidate = _build_candidate(
            ticker=symbol,
            name=str(stock.get("name") or symbol),
            market=market,
            market_cap=price * shares,
        )
        if candidate:
            candidates.append(candidate)
        if len(candidates) >= universe_size:
            break
    return candidates


def _load_kr_market_universe(market: str, universe_size: int) -> list[Candidate]:
    listing = load_krx_listing()
    if listing.empty:
        return []

    listing = pd.DataFrame(listing.loc[listing["Market"] == market])
    common_shares = pd.Series(listing["Code"]).map(lambda code: str(code).endswith("0"))
    listing = pd.DataFrame(listing.loc[common_shares])
    listing = pd.DataFrame(
        listing.sort_values("Marcap", ascending=False).head(universe_size)
    )
    sector_lookup = load_sector_lookup([market])

    candidates = []
    for _, row in listing.iterrows():
        candidate = _build_candidate(
            ticker=str(row["Code"]),
            name=str(row["Name"]),
            market=market,
            market_cap=row.get("Marcap", 0),
            sector_lookup=sector_lookup,
        )
        if candidate:
            candidates.append(candidate)
    return candidates


def _load_us_market_universe(market: str, universe_size: int) -> list[Candidate]:
    listing = pd.DataFrame(fdr.StockListing(market))
    if listing.empty:
        return []

    if "Marcap" in listing.columns:
        listing = listing.sort_values("Marcap", ascending=False)

    listing = listing.head(universe_size)
    ticker_col = "Symbol" if "Symbol" in listing.columns else "Code"

    candidates = []
    for _, row in listing.iterrows():
        ticker = str(row.get(ticker_col, "")).strip().upper()
        if not ticker:
            continue
        candidate = _build_candidate(
            ticker=ticker,
            name=str(row.get("Name", ticker)),
            market=market,
            market_cap=row.get("Marcap", 0),
            listing_industry=row.get("Industry"),
        )
        if candidate:
            candidates.append(candidate)
    return candidates


def _build_candidate(
    ticker: str,
    name: str,
    market: str,
    market_cap,
    listing_sector: str | None = None,
    listing_industry: str | None = None,
    sector_lookup: dict[str, Any] | None = None,
) -> Candidate | None:
    try:
        ohlcv = fetch_ohlcv(ticker, days_back=60)
        if ohlcv.empty or len(ohlcv) < 20:
            return None

        closes = ohlcv["close"].astype(float).to_numpy()
        volumes = ohlcv["volume"].astype(float).to_numpy()
        current_price = closes[-1]
        ret_20d = (closes[-1] - closes[-20]) / closes[-20]
        ret_5d = (closes[-1] - closes[-5]) / closes[-5]
        avg_volume_20d = volumes[-20:].mean()

        fund = fetch_naver_fundamentals(ticker)
        per = fund.get("per", 0)
        pbr = fund.get("pbr", 0)
        div_yield = fund.get("div_yield", 0)

        score = _score_candidate(
            ret_20d=ret_20d,
            ret_5d=ret_5d,
            market_cap=market_cap,
            per=per,
            pbr=pbr,
            volumes=volumes,
            avg_volume_20d=avg_volume_20d,
        )

        return {
            "ticker": ticker,
            "name": name,
            "market": market,
            "sector": classify_sector(
                name,
                ticker=ticker,
                listing_sector=_normalize_listing_text(listing_sector),
                listing_industry=_normalize_listing_text(listing_industry),
                sector_lookup=sector_lookup,
            ),
            "price": current_price,
            "market_cap": _safe_number(market_cap),
            "ret_5d": ret_5d * 100,
            "ret_20d": ret_20d * 100,
            "per": per,
            "pbr": pbr,
            "div_yield": div_yield,
            "avg_volume": avg_volume_20d,
            "score": score,
        }
    except Exception:
        return None


def _score_candidate(
    ret_20d: float,
    ret_5d: float,
    market_cap,
    per,
    pbr,
    volumes: Any,
    avg_volume_20d,
) -> float:
    score = 0.0

    if ret_20d > 0.05:
        score += 3
    elif ret_20d > 0:
        score += 1

    if ret_5d > 0.02:
        score += 2
    elif ret_5d > 0:
        score += 1

    market_cap_value = _safe_number(market_cap)
    if market_cap_value > 50_000_000_000_000:
        score += 3
    elif market_cap_value > 10_000_000_000_000:
        score += 2
    elif market_cap_value > 1_000_000_000_000:
        score += 1

    if 0 < per < 15:
        score += 2
    elif 0 < per < 30:
        score += 1

    if 0 < pbr < 1.0:
        score += 2
    elif 0 < pbr < 2.0:
        score += 1

    if len(volumes) >= 40 and avg_volume_20d > volumes[-40:-20].mean() * 1.2:
        score += 1

    return score


def _candidate_sort_key(candidate: Candidate) -> tuple[float, float, float, float]:
    return (
        candidate.get("score", 0),
        candidate.get("ret_20d", 0),
        candidate.get("ret_5d", 0),
        candidate.get("market_cap", 0),
    )


def _normalize_listing_text(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return None
    return text


def _safe_number(value) -> float:
    try:
        if value is None:
            return 0.0
        return float(value)
    except TypeError, ValueError:
        return 0.0


def _screen_us_stocks(market: str = "NASDAQ", top_n: int = 30) -> list[Candidate]:
    exchange = "NASDAQ" if market in ("NASDAQ", "US") else "NYSE"
    listing = pd.DataFrame(fdr.StockListing(exchange))
    if listing.empty:
        return []

    if "Marcap" in listing.columns:
        listing = listing.sort_values("Marcap", ascending=False).head(top_n)
    else:
        listing = listing.head(top_n)

    ticker_col = "Symbol" if "Symbol" in listing.columns else "Code"

    candidates = []
    for _, row in listing.iterrows():
        ticker = str(row.get(ticker_col, "")).strip().upper()
        if not ticker:
            continue
        candidate = _build_candidate(
            ticker=ticker,
            name=str(row.get("Name", ticker)),
            market=exchange,
            market_cap=row.get("Marcap", 0),
            listing_industry=row.get("Industry"),
        )
        if candidate:
            candidates.append(candidate)

    candidates.sort(key=_candidate_sort_key, reverse=True)
    return candidates
