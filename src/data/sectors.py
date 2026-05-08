"""섹터 데이터 조회 + 캐시.

섹터는 종목명 substring보다 상장/프로필 데이터가 우선이다.
외부 조회 실패 시에는 캐시 또는 이름 fallback을 사용한다.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import FinanceDataReader as fdr
import pandas as pd

from src.data.market import is_us_ticker


_CACHE_PATH = Path("data/sector_cache.json")
_CACHE_TTL_DAYS = 30

_IGNORED_LABELS = {
    "중견기업부",
    "우량기업부",
    "벤처기업부",
    "기술성장기업부",
    "투자주의환기종목",
}

NAME_SECTOR_MAP = {
    "반도체": "반도체",
    "전자": "반도체",
    "하이닉스": "반도체",
    "마이크론": "반도체",
    "자동차": "자동차",
    "기아": "자동차",
    "현대차": "자동차",
    "현대모비스": "자동차",
    "금융": "금융",
    "은행": "금융",
    "KB": "금융",
    "신한": "금융",
    "에어로": "방산",
    "한화": "방산",
    "바이오": "바이오",
    "제약": "바이오",
    "셀트리온": "바이오",
    "화학": "화학",
    "LG화학": "화학",
    "배터리": "에너지",
    "SDI": "에너지",
    "에코프로": "에너지",
    "포스코퓨처엠": "에너지",
    "NAVER": "IT",
    "카카오": "IT",
    "네이버": "IT",
    "조선": "조선",
    "중공업": "조선",
    "철강": "철강",
    "포스코": "철강",
}

_LABEL_SECTOR_MAP = {
    "semiconductor": "반도체",
    "반도체": "반도체",
    "memory": "반도체",
    "automobile": "자동차",
    "자동차": "자동차",
    "bank": "금융",
    "financial": "금융",
    "금융": "금융",
    "은행": "금융",
    "insurance": "금융",
    "aerospace": "방산",
    "defense": "방산",
    "방산": "방산",
    "biotechnology": "바이오",
    "biotech": "바이오",
    "pharmaceutical": "바이오",
    "바이오": "바이오",
    "제약": "바이오",
    "chemical": "화학",
    "화학": "화학",
    "battery": "에너지",
    "energy": "에너지",
    "에너지": "에너지",
    "조선": "조선",
    "shipbuilding": "조선",
    "steel": "철강",
    "철강": "철강",
    "software": "IT",
    "internet": "IT",
    "information technology": "IT",
}


def _normalize_ticker(ticker: str) -> str:
    text = str(ticker).strip().upper()
    return text if is_us_ticker(text) else text.zfill(6)


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() == "nan" or text in _IGNORED_LABELS:
        return None
    return text


def normalize_sector_label(*labels: Any) -> str | None:
    for value in labels:
        text = _clean_text(value)
        if not text:
            continue
        lower = text.lower()
        for keyword, sector in _LABEL_SECTOR_MAP.items():
            if keyword in lower or keyword in text:
                return sector
    return None


def classify_sector_by_name(name: str) -> str:
    for keyword, sector in NAME_SECTOR_MAP.items():
        if keyword in name:
            return sector
    return "기타"


def _load_cache() -> dict[str, dict[str, Any]]:
    if _CACHE_PATH.exists():
        try:
            return json.loads(_CACHE_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_cache(cache: dict[str, dict[str, Any]]) -> None:
    _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2))


def _is_cache_valid(entry: dict[str, Any]) -> bool:
    cached_at = entry.get("cached_at")
    if not cached_at:
        return False
    try:
        cached_date = datetime.fromisoformat(str(cached_at))
    except ValueError:
        return False
    return (datetime.now() - cached_date).days < _CACHE_TTL_DAYS


def _entry(
    ticker: str,
    source: str,
    raw_sector: Any = None,
    raw_industry: Any = None,
    name: Any = None,
) -> dict[str, Any]:
    sector = normalize_sector_label(raw_industry, raw_sector)
    if not sector:
        return {}
    return {
        "ticker": _normalize_ticker(ticker),
        "name": _clean_text(name),
        "sector": sector,
        "raw_sector": _clean_text(raw_sector),
        "raw_industry": _clean_text(raw_industry),
        "source": source,
    }


def _match_row(df: pd.DataFrame, column: str, ticker: str) -> pd.Series | None:
    if df.empty or column not in df.columns:
        return None
    normalized = _normalize_ticker(ticker)
    rows = df[df[column].astype(str).str.upper().map(_normalize_ticker).eq(normalized)]
    if rows.empty:
        return None
    return rows.iloc[0]


def _fetch_kr_sector(ticker: str) -> dict[str, Any]:
    try:
        listing = pd.DataFrame(fdr.StockListing("KRX-DESC"))
        row = _match_row(listing, "Code", ticker)
        if row is None:
            return {}
        return _entry(
            ticker,
            source="fdr:krx-desc",
            raw_sector=row.get("Sector"),
            raw_industry=row.get("Industry"),
            name=row.get("Name"),
        )
    except Exception:
        return {}


def _fetch_us_sector(ticker: str) -> dict[str, Any]:
    for market, source in (("S&P500", "fdr:sp500"),):
        try:
            listing = pd.DataFrame(fdr.StockListing(market))
            row = _match_row(listing, "Symbol", ticker)
            if row is not None:
                entry = _entry(
                    ticker,
                    source=source,
                    raw_sector=row.get("Sector"),
                    raw_industry=row.get("Industry"),
                    name=row.get("Name"),
                )
                if entry:
                    return entry
        except Exception:
            pass

    try:
        import yfinance as yf

        info = yf.Ticker(ticker).info
        entry = _entry(
            ticker,
            source="yfinance:info",
            raw_sector=info.get("sector"),
            raw_industry=info.get("industry"),
            name=info.get("longName") or info.get("shortName"),
        )
        if entry:
            return entry
    except Exception:
        pass

    for market in ("NASDAQ", "NYSE"):
        try:
            listing = pd.DataFrame(fdr.StockListing(market))
            row = _match_row(listing, "Symbol", ticker)
            if row is not None:
                entry = _entry(
                    ticker,
                    source=f"fdr:{market.lower()}",
                    raw_industry=row.get("Industry"),
                    name=row.get("Name"),
                )
                if entry:
                    return entry
        except Exception:
            pass
    return {}


def fetch_sector_from_sources(ticker: str) -> dict[str, Any]:
    normalized = _normalize_ticker(ticker)
    if not normalized:
        return {}
    if is_us_ticker(normalized):
        return _fetch_us_sector(normalized)
    return _fetch_kr_sector(normalized)


def fetch_sector_cached(ticker: str) -> dict[str, Any]:
    normalized = _normalize_ticker(ticker)
    cache = _load_cache()
    cached = cache.get(normalized)
    if cached and _is_cache_valid(cached):
        return {k: v for k, v in cached.items() if k != "cached_at"}

    result = fetch_sector_from_sources(normalized)
    if result:
        cache[normalized] = {**result, "cached_at": datetime.now().isoformat()}
        _save_cache(cache)
        return result

    if cached:
        stale = {k: v for k, v in cached.items() if k != "cached_at"}
        stale["cache_date"] = str(cached.get("cached_at", ""))[:10]
        return stale
    return {}


def load_sector_lookup(markets: list[str]) -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}
    if any(market in ("KR", "KOSPI", "KOSDAQ", "ALL") for market in markets):
        try:
            listing = pd.DataFrame(fdr.StockListing("KRX-DESC"))
            if not listing.empty:
                if "ALL" not in markets and "KR" not in markets and "Market" in listing.columns:
                    listing = listing[listing["Market"].isin(markets)]
                for _, row in listing.iterrows():
                    ticker = _normalize_ticker(str(row.get("Code", "")))
                    entry = _entry(
                        ticker,
                        source="fdr:krx-desc",
                        raw_sector=row.get("Sector"),
                        raw_industry=row.get("Industry"),
                        name=row.get("Name"),
                    )
                    if entry:
                        lookup[ticker] = entry
        except Exception:
            pass
    return lookup


def resolve_sector(
    name: str,
    ticker: str | None = None,
    listing_sector: str | None = None,
    listing_industry: str | None = None,
    sector_lookup: dict[str, Any] | None = None,
    allow_fetch: bool = False,
) -> str:
    sector = normalize_sector_label(listing_industry, listing_sector)
    if sector:
        return sector

    if ticker:
        normalized = _normalize_ticker(ticker)
        if sector_lookup and normalized in sector_lookup:
            entry = sector_lookup[normalized]
            if isinstance(entry, str):
                sector = normalize_sector_label(entry)
            else:
                sector = normalize_sector_label(
                    entry.get("sector"),
                    entry.get("raw_industry"),
                    entry.get("raw_sector"),
                )
            if sector:
                return sector

        if allow_fetch:
            entry = fetch_sector_cached(normalized)
            sector = normalize_sector_label(
                entry.get("sector"),
                entry.get("raw_industry"),
                entry.get("raw_sector"),
            )
            if sector:
                return sector

    return classify_sector_by_name(name)
