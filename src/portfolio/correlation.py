"""포트폴리오 상관 리스크 관리 — Phase 19

M1: 상관계수 계산
M2: 섹터 분류 + 집중도
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.data.market import fetch_ohlcv

# 섹터 분류 (종목명 키워드 기반)
SECTOR_MAP = {
    "반도체": "반도체", "전자": "반도체", "하이닉스": "반도체",
    "자동차": "자동차", "기아": "자동차", "현대차": "자동차", "현대모비스": "자동차",
    "금융": "금융", "은행": "금융", "KB": "금융", "신한": "금융", "하나": "금융",
    "에어로": "방산", "한화": "방산",
    "바이오": "바이오", "제약": "바이오", "셀트리온": "바이오",
    "화학": "화학", "LG화학": "화학",
    "배터리": "에너지", "SDI": "에너지", "에코프로": "에너지", "포스코퓨처엠": "에너지",
    "NAVER": "IT", "카카오": "IT", "네이버": "IT",
    "조선": "조선", "중공업": "조선",
    "철강": "철강", "포스코": "철강",
}


def classify_sector(name: str) -> str:
    """종목명에서 섹터를 분류."""
    for keyword, sector in SECTOR_MAP.items():
        if keyword in name:
            return sector
    return "기타"


def compute_correlation_matrix(
    tickers: list[str],
    days_back: int = 60,
) -> pd.DataFrame | None:
    """종목 간 일간 수익률 상관계수 행렬.

    Returns:
        NxN DataFrame (index=columns=tickers). 데이터 부족 시 None.
    """
    if len(tickers) < 2:
        return None

    returns = {}
    for ticker in tickers:
        df = fetch_ohlcv(ticker, days_back=days_back + 10)
        if not df.empty and len(df) >= 20:
            ret = df["close"].pct_change().dropna()
            returns[ticker] = ret

    if len(returns) < 2:
        return None

    ret_df = pd.DataFrame(returns)
    # 공통 날짜만 사용
    ret_df = ret_df.dropna()
    if len(ret_df) < 20:
        return None

    return ret_df.corr()


def compute_correlation_from_data(
    ohlcv_data: dict[str, pd.DataFrame],
    tickers: list[str],
    up_to_date=None,
    window: int = 60,
) -> pd.DataFrame | None:
    """사전 로드된 OHLCV 데이터에서 상관계수 계산 (백테스트용)."""
    if len(tickers) < 2:
        return None

    returns = {}
    for ticker in tickers:
        if ticker not in ohlcv_data:
            continue
        df = ohlcv_data[ticker]
        if up_to_date is not None:
            df = df[df.index <= up_to_date]
        if len(df) < 20:
            continue
        ret = df["close"].pct_change().dropna().tail(window)
        returns[ticker] = ret

    if len(returns) < 2:
        return None

    ret_df = pd.DataFrame(returns).dropna()
    if len(ret_df) < 20:
        return None

    return ret_df.corr()


def get_max_correlation(
    ticker: str,
    portfolio_tickers: list[str],
    corr_matrix: pd.DataFrame | None = None,
    days_back: int = 60,
) -> tuple[float, str | None]:
    """신규 매수 후보와 기존 보유 종목 간 최대 상관계수.

    Returns:
        (max_corr, most_correlated_ticker) 또는 (0.0, None) 데이터 부족 시.
    """
    if not portfolio_tickers:
        return 0.0, None

    if corr_matrix is None:
        all_tickers = [ticker] + portfolio_tickers
        corr_matrix = compute_correlation_matrix(all_tickers, days_back)

    if corr_matrix is None or ticker not in corr_matrix.index:
        return 0.0, None

    max_corr = 0.0
    max_ticker = None
    for pt in portfolio_tickers:
        if pt in corr_matrix.columns and pt != ticker:
            c = abs(corr_matrix.loc[ticker, pt])
            if c > max_corr:
                max_corr = c
                max_ticker = pt

    return round(max_corr, 4), max_ticker


def compute_sector_concentration(
    positions: list[dict],
    ticker_names: dict[str, str] | None = None,
) -> dict:
    """보유 포지션의 섹터 집중도 계산.

    Returns:
        {
            "sectors": {"반도체": 65.0, "자동차": 35.0},
            "most_concentrated": "반도체",
            "concentration_pct": 65.0,
            "is_concentrated": True,
        }
    """
    if not positions:
        return {"sectors": {}, "most_concentrated": None, "concentration_pct": 0, "is_concentrated": False}

    sector_values = {}
    total_value = 0

    for pos in positions:
        name = pos.get("name", "")
        if not name and ticker_names:
            name = ticker_names.get(pos.get("ticker", ""), "")
        sector = classify_sector(name)
        value = pos.get("market_value", pos.get("entry_price", 0) * pos.get("shares", 0))
        sector_values[sector] = sector_values.get(sector, 0) + value
        total_value += value

    if total_value <= 0:
        return {"sectors": {}, "most_concentrated": None, "concentration_pct": 0, "is_concentrated": False}

    sectors = {s: round(v / total_value * 100, 1) for s, v in sector_values.items()}
    most = max(sectors, key=sectors.get)

    return {
        "sectors": sectors,
        "most_concentrated": most,
        "concentration_pct": sectors[most],
        "is_concentrated": sectors[most] > 50,
    }


def compute_diversification_score(
    corr_matrix: pd.DataFrame | None,
    sector_concentration: dict,
) -> float:
    """분산도 점수 (0=완전집중, 1=완전분산).

    상관 평균과 섹터 집중도를 결합.
    """
    if corr_matrix is None or corr_matrix.shape[0] < 2:
        # 단일 종목 → 분산 없음
        return 0.0

    # 상관 점수 (0=고상관, 1=무상관)
    n = corr_matrix.shape[0]
    upper = []
    for i in range(n):
        for j in range(i + 1, n):
            upper.append(abs(corr_matrix.iloc[i, j]))
    avg_corr = np.mean(upper) if upper else 1.0
    corr_score = max(0, 1 - avg_corr)

    # 섹터 점수 (0=단일섹터, 1=균등분배)
    sectors = sector_concentration.get("sectors", {})
    if len(sectors) <= 1:
        sector_score = 0.0
    else:
        pcts = list(sectors.values())
        n_sectors = len(pcts)
        ideal = 100 / n_sectors
        deviation = sum(abs(p - ideal) for p in pcts) / (2 * 100)
        sector_score = max(0, 1 - deviation)

    return round((corr_score * 0.6 + sector_score * 0.4), 2)
