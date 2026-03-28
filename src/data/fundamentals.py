"""네이버 금융에서 PER/PBR/배당수익률 스크래핑"""

import re
import requests
from bs4 import BeautifulSoup


_HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}


def fetch_naver_fundamentals(ticker: str) -> dict:
    """네이버 금융에서 PER, PBR, 배당수익률 가져오기"""
    url = f"https://finance.naver.com/item/main.naver?code={ticker}"
    try:
        r = requests.get(url, headers=_HEADERS, timeout=10)
        r.raise_for_status()
    except Exception:
        return {}

    soup = BeautifulSoup(r.text, "html.parser")
    result = {}

    # em 태그의 id로 PER/PBR 추출
    for em in soup.find_all("em", id=True):
        eid = em["id"]
        try:
            val = float(em.get_text().strip().replace(",", ""))
        except (ValueError, AttributeError):
            continue

        if eid == "_per":
            result["per"] = val
        elif eid == "_cns_per":
            result["consensus_per"] = val
        elif eid == "_pbr":
            result["pbr"] = val

    # 배당수익률 — 페이지 텍스트에서 추출
    text = soup.get_text()
    div_match = re.search(r"배당수익률.*?(\d+\.?\d*)%", text, re.DOTALL)
    if div_match:
        result["div_yield"] = float(div_match.group(1))

    # 시가총액
    for dd in soup.find_all("dd"):
        dd_text = dd.get_text()
        if "시가총액" in dd_text:
            cap_match = re.search(r"([\d,]+)\s*억원", dd_text)
            if cap_match:
                result["market_cap_billion"] = int(cap_match.group(1).replace(",", ""))
            break

    return result


def fetch_fundamentals_batch(tickers: list[str]) -> dict[str, dict]:
    """여러 종목의 펀더멘털 일괄 조회"""
    results = {}
    for ticker in tickers:
        results[ticker] = fetch_naver_fundamentals(ticker)
    return results
