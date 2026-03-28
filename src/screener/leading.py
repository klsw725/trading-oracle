"""주도주 스크리닝 — 이광수 철학 기반

주도주 = 주가가 오르고 있고 + 오르는 이유가 분명한 종목
- 시가총액 상위
- 최근 20일 수익률 양수
- PER/PBR 합리적
- 거래량 활발
"""

import FinanceDataReader as fdr

from src.data.market import fetch_ohlcv
from src.data.fundamentals import fetch_naver_fundamentals


def screen_leading_stocks(market: str = "ALL", top_n: int = 30) -> list[dict]:
    """주도주 스크리닝. 시총 상위에서 모멘텀+밸류에이션 필터링."""

    listing = fdr.StockListing("KRX")
    if listing.empty:
        return []

    # 시장 필터
    if market == "KOSPI":
        listing = listing[listing["Market"] == "KOSPI"]
    elif market == "KOSDAQ":
        listing = listing[listing["Market"] == "KOSDAQ"]

    # 우선주 제외 (코드 끝자리 5,7,8,9 → 보통주는 0)
    listing = listing[listing["Code"].str[-1] == "0"]

    # 시총 상위
    listing = listing.sort_values("Marcap", ascending=False).head(top_n)

    candidates = []
    for _, row in listing.iterrows():
        ticker = row["Code"]
        name = row["Name"]

        try:
            ohlcv = fetch_ohlcv(ticker, days_back=60)
            if ohlcv.empty or len(ohlcv) < 20:
                continue

            closes = ohlcv["close"].values
            volumes = ohlcv["volume"].values

            current_price = closes[-1]
            ret_20d = (closes[-1] - closes[-20]) / closes[-20]
            ret_5d = (closes[-1] - closes[-5]) / closes[-5]
            avg_volume_20d = volumes[-20:].mean()

            # 네이버에서 PER/PBR
            fund = fetch_naver_fundamentals(ticker)
            per = fund.get("per", 0)
            pbr = fund.get("pbr", 0)
            div_yield = fund.get("div_yield", 0)

            market_cap = row["Marcap"]

            # 주도주 점수 계산
            score = 0.0

            # 모멘텀 점수 (20일 수익률 양수 = 오르고 있음)
            if ret_20d > 0.05:
                score += 3
            elif ret_20d > 0:
                score += 1

            # 단기 모멘텀
            if ret_5d > 0.02:
                score += 2
            elif ret_5d > 0:
                score += 1

            # 시가총액 (클수록 주도주 가능성)
            if market_cap > 50_000_000_000_000:
                score += 3
            elif market_cap > 10_000_000_000_000:
                score += 2
            elif market_cap > 1_000_000_000_000:
                score += 1

            # PER 합리적 (0 < PER < 30)
            if 0 < per < 15:
                score += 2
            elif 0 < per < 30:
                score += 1

            # PBR 저평가 (< 2.0)
            if 0 < pbr < 1.0:
                score += 2
            elif 0 < pbr < 2.0:
                score += 1

            # 거래량 증가
            if len(volumes) >= 40 and avg_volume_20d > volumes[-40:-20].mean() * 1.2:
                score += 1

            candidates.append({
                "ticker": ticker,
                "name": name,
                "market": row["Market"],
                "price": current_price,
                "market_cap": market_cap,
                "ret_5d": ret_5d * 100,
                "ret_20d": ret_20d * 100,
                "per": per,
                "pbr": pbr,
                "div_yield": div_yield,
                "avg_volume": avg_volume_20d,
                "score": score,
            })
        except Exception:
            continue

    candidates.sort(key=lambda x: x["score"], reverse=True)
    return candidates
