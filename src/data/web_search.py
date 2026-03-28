"""웹 검색 보강 — DuckDuckGo 기반 종목별/시장 컨텍스트 수집

Phase 10 PRD: docs/specs/multi-perspective/prds/phase10-web-search.md
OUROBOROS Triple-Gate, Sector MESH, Dilution Dragnet 통합.
"""

import json
import time
from datetime import datetime
from pathlib import Path

from ddgs import DDGS

from src.data.market import is_us_ticker

CACHE_PATH = Path("data/web_cache.json")

# --- Sector MESH (OUROBOROS 차용) ---
SECTOR_MESH = {
    # 한국 섹터
    "반도체": ["{name} HBM AI 메모리 수요", "{name} 디램 낸드 가격 전망"],
    "자동차": ["{name} 전기차 판매량 수주", "{name} 배터리 공급망"],
    "방산": ["{name} 수주 잔고 계약", "{name} 국방 예산 NATO"],
    "금융": ["{name} NIM 순이자마진 금리", "{name} 건전성 부실채권"],
    "바이오": ["{name} 임상 FDA 승인 결과", "{name} 파이프라인 특허"],
    "에너지": ["{name} 배터리 2차전지 수요", "{name} 에너지 전환 수소"],
    "소비재": ["{name} 매출 성장 브랜드", "{name} 소비 트렌드"],
    # 미국 섹터
    "TECH": ["{ticker} AI revenue cloud growth", "{ticker} margin pressure competition"],
    "EV": ["{ticker} delivery numbers production", "{ticker} battery supply chain cost"],
    "PHARMA": ["{ticker} FDA approval clinical trial", "{ticker} patent cliff generic"],
    "FINTECH": ["{ticker} delinquency rate loan loss", "{ticker} regulation compliance"],
    "SAAS": ["{ticker} ARR NRR churn rate", "{ticker} AI integration margin"],
}


def _detect_sector(name: str, ticker: str) -> str | None:
    """종목명/티커에서 섹터 자동 감지."""
    if is_us_ticker(ticker):
        mapping = {
            "TECH": ["AAPL", "MSFT", "GOOGL", "META", "AMZN"],
            "EV": ["TSLA", "RIVN", "LCID", "NIO"],
            "PHARMA": ["PFE", "JNJ", "MRK", "LLY", "ABBV"],
            "FINTECH": ["SQ", "PYPL", "SOFI", "AFRM"],
            "SAAS": ["CRM", "SNOW", "PLTR", "DDOG"],
        }
        for sector, tickers_list in mapping.items():
            if ticker in tickers_list:
                return sector
        # GPU/반도체
        if ticker in ("NVDA", "AMD", "INTC", "AVGO", "TSM"):
            return "TECH"
        return None

    # 한국 종목 — 이름 기반
    kr_mapping = {
        "반도체": ["전자", "하이닉스", "반도체"],
        "자동차": ["자동차", "기아", "현대"],
        "방산": ["에어로", "한화", "LIG"],
        "금융": ["금융", "은행", "지주", "KB", "신한", "하나"],
        "바이오": ["바이오", "제약", "셀트리온"],
        "에너지": ["에너지", "배터리", "LG에너지"],
        "소비재": ["아모레", "LG생활", "CJ", "오리온"],
    }
    for sector, keywords in kr_mapping.items():
        if any(kw in name for kw in keywords):
            return sector
    return None


def _triple_gate(result: dict, ticker: str, name: str, query_type: str) -> bool:
    """OUROBOROS Triple-Gate: 시간/맥락/관련성 검증."""
    title = result.get("title", "")
    snippet = result.get("body", result.get("snippet", ""))
    text = f"{title} {snippet}".lower()

    # Gate 1: Relevance — 종목명/티커 포함 여부
    target_lower = name.lower()
    ticker_lower = ticker.lower()
    if target_lower not in text and ticker_lower not in text:
        return False

    # Gate 2: Context — 오인 방지 (광고, 무관 콘텐츠)
    spam_keywords = ["광고", "sponsored", "ad ", "쿠팡파트너스", "affiliate"]
    if any(kw in text for kw in spam_keywords):
        return False

    return True


def _safe_search(ddgs: DDGS, method: str, query: str, max_results: int = 5,
                 timelimit: str | None = None, rate_limit: float = 0.5) -> list[dict]:
    """안전한 검색 — 실패 시 빈 리스트."""
    time.sleep(rate_limit)
    try:
        if method == "news":
            return list(ddgs.news(query, max_results=max_results, timelimit=timelimit or "w"))
        else:
            return list(ddgs.text(query, max_results=max_results))
    except Exception:
        return []


def _load_cache() -> dict:
    if CACHE_PATH.exists():
        try:
            return json.loads(CACHE_PATH.read_text())
        except Exception:
            pass
    return {}


def _save_cache(cache: dict):
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2))


def _is_cache_valid(entry: dict, ttl_hours: int = 12) -> bool:
    searched_at = entry.get("searched_at", "")
    if not searched_at:
        return False
    try:
        dt = datetime.fromisoformat(searched_at)
        return (datetime.now() - dt).total_seconds() < ttl_hours * 3600
    except Exception:
        return False


def search_ticker_context(ticker: str, name: str, config: dict) -> dict:
    """종목별 웹 컨텍스트 수집 (OUROBOROS 강화).

    Returns dict with news, forensic, flow, consensus, sector_deep, gate_stats.
    실패 시 빈 dict.
    """
    web_cfg = config.get("web_search", {})
    if not web_cfg.get("enabled", True):
        return {}

    # 캐시 확인
    cache = _load_cache()
    ttl = web_cfg.get("cache_ttl_hours", 12)
    if ticker in cache and _is_cache_valid(cache[ticker], ttl):
        return cache[ticker]

    is_us = is_us_ticker(ticker)
    rate_limit = web_cfg.get("rate_limit_sec", 0.5)
    max_news = web_cfg.get("max_news", 7)
    max_text = web_cfg.get("max_text", 5)
    consecutive_fails = 0

    ddgs = DDGS()
    result = {"searched_at": datetime.now().isoformat(), "gate_stats": {"total": 0, "passed": 0, "rejected": 0}}

    def _search_and_filter(key: str, query: str, method: str = "text", max_r: int = None, timelimit: str = None):
        nonlocal consecutive_fails
        if consecutive_fails >= 3:
            return
        raw = _safe_search(ddgs, method, query, max_results=max_r or max_text, timelimit=timelimit, rate_limit=rate_limit)
        if not raw:
            consecutive_fails += 1
        else:
            consecutive_fails = 0

        filtered = []
        for r in raw:
            result["gate_stats"]["total"] += 1
            if _triple_gate(r, ticker, name, key):
                result["gate_stats"]["passed"] += 1
                filtered.append({
                    "title": r.get("title", "")[:100],
                    "snippet": r.get("body", r.get("snippet", ""))[:200],
                    "date": r.get("date", r.get("published", "")),
                    "url": r.get("url", r.get("href", "")),
                })
            else:
                result["gate_stats"]["rejected"] += 1

        if key not in result:
            result[key] = filtered
        else:
            result[key].extend(filtered)

    # --- 기본 쿼리 ---
    if is_us:
        _search_and_filter("news", f'"{ticker}" stock', "news", max_news, "w")
        _search_and_filter("flow", f'"{ticker}" institutional ownership 13F')
        _search_and_filter("consensus", f'"{ticker}" price target analyst consensus')
    else:
        _search_and_filter("news", f'"{name}" 주식', "news", max_news, "w")
        _search_and_filter("flow", f'"{name}" 외국인 OR 기관 수급')
        _search_and_filter("consensus", f'"{name}" 목표주가 컨센서스')

    # --- 포렌식 쿼리 (OUROBOROS Dilution Dragnet) ---
    if is_us:
        _search_and_filter("forensic_dilution", f'"{ticker}" ATM offering OR convertible note OR PIPE OR warrant OR dilution')
        _search_and_filter("forensic_insider", f'"{ticker}" insider trading Form 4 purchase sale')
        _search_and_filter("forensic_short", f'"{ticker}" short interest cost to borrow', max_r=3)
    else:
        _search_and_filter("forensic_dilution", f'"{name}" 유상증자 OR 전환사채 OR CB OR BW OR 신주인수권')
        _search_and_filter("forensic_insider", f'"{name}" 대주주 OR 임원 매도 OR 매수 OR 지분 변동')
        _search_and_filter("forensic_short", f'"{name}" 공매도 OR 대차잔고', max_r=3)

    # --- 섹터 MESH ---
    sector = _detect_sector(name, ticker)
    if sector and sector in SECTOR_MESH:
        for i, q_template in enumerate(SECTOR_MESH[sector]):
            q = q_template.format(name=name, ticker=ticker)
            _search_and_filter(f"sector_{i}", q, max_r=3)

    # 캐시 저장
    cache[ticker] = result
    _save_cache(cache)

    return result


def search_market_context(include_us: bool = False, config: dict | None = None) -> dict:
    """시장 전체 매크로 컨텍스트 검색."""
    web_cfg = (config or {}).get("web_search", {})
    if not web_cfg.get("enabled", True):
        return {}

    cache = _load_cache()
    ttl = web_cfg.get("cache_ttl_hours", 12)
    if "_market" in cache and _is_cache_valid(cache["_market"], ttl):
        return cache["_market"]

    rate_limit = web_cfg.get("rate_limit_sec", 0.5)
    ddgs = DDGS()
    result = {"searched_at": datetime.now().isoformat()}

    def _search(key, query, method="news", max_r=5, timelimit="w"):
        raw = _safe_search(ddgs, method, query, max_results=max_r, timelimit=timelimit, rate_limit=rate_limit)
        result[key] = [{"title": r.get("title", "")[:100], "snippet": r.get("body", r.get("snippet", ""))[:200]} for r in raw]

    _search("kr_macro", "한국 주식시장 전망 코스피")
    _search("rates", "기준금리 FOMC 한국은행", max_r=3)
    _search("fx", "원달러 환율 전망", max_r=3)

    if include_us:
        _search("us_macro", "US stock market outlook Fed S&P500")

    cache["_market"] = result
    _save_cache(cache)

    return result


def format_web_context_for_prompt(web_context: dict, perspective: str) -> str:
    """관점별 웹 컨텍스트를 프롬프트 삽입용 텍스트로 포맷."""
    if not web_context:
        return ""

    lines = []
    searched_at = web_context.get("searched_at", "")[:10]

    # 뉴스 (전 관점 공통)
    news = web_context.get("news", [])
    if news:
        lines.append(f"### 최근 뉴스 (웹 검색 {searched_at})")
        for n in news[:5]:
            date = n.get("date", "")[:10]
            lines.append(f"- [{date}] {n['title']}")
        lines.append("")

    # 관점별 특화 섹션
    if perspective == "ouroboros":
        # 포렌식: 희석/내부자/공매도
        for key, label in [("forensic_dilution", "희석 리스크"), ("forensic_insider", "내부자 거래"), ("forensic_short", "공매도")]:
            items = web_context.get(key, [])
            count = len(items)
            status = "⚠️" if count > 0 else "✅"
            lines.append(f"- {label} 검색: {count}건 {status}")
            for item in items[:3]:
                lines.append(f"  - {item['title'][:80]}")
        lines.append("")

        # 수급
        flow = web_context.get("flow", [])
        if flow:
            lines.append("### 기관/외국인 수급 (웹 검색)")
            for f in flow[:3]:
                lines.append(f"- {f['title'][:80]}")
            lines.append("")

    elif perspective == "macro":
        # 섹터 동향
        for key in ("sector_0", "sector_1"):
            items = web_context.get(key, [])
            if items:
                if not any("섹터" in l for l in lines):
                    lines.append("### 섹터 동향 (웹 검색)")
                for item in items[:3]:
                    lines.append(f"- {item['title'][:80]}")
        if any("섹터" in l for l in lines):
            lines.append("")

    elif perspective == "value":
        consensus = web_context.get("consensus", [])
        if consensus:
            lines.append("### 밸류에이션 참고 (웹 검색)")
            for c in consensus[:3]:
                lines.append(f"- {c['title'][:80]}")
            lines.append("")

    return "\n".join(lines)
