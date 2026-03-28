"""주식 시장 데이터 수집 (한국: pykrx + FDR, 미국: FDR + yfinance)"""

import re
import warnings
warnings.filterwarnings("ignore", category=UserWarning, module="pykrx")

from datetime import datetime, timedelta

import pandas as pd
import FinanceDataReader as fdr
from pykrx import stock as krx


def is_us_ticker(ticker: str) -> bool:
    """미국 종목 여부 판별. 알파벳으로만 구성되면 US."""
    return bool(re.match(r'^[A-Za-z]{1,5}$', ticker))


def get_trading_dates(days_back: int = 120) -> tuple[str, str]:
    end = datetime.now()
    start = end - timedelta(days=days_back)
    return start.strftime("%Y%m%d"), end.strftime("%Y%m%d")


def fetch_ohlcv(ticker: str, days_back: int = 120) -> pd.DataFrame:
    if is_us_ticker(ticker):
        return _fetch_ohlcv_us(ticker, days_back)
    return _fetch_ohlcv_kr(ticker, days_back)


def _fetch_ohlcv_kr(ticker: str, days_back: int = 120) -> pd.DataFrame:
    start, end = get_trading_dates(days_back)
    df = krx.get_market_ohlcv(start, end, ticker)
    if df.empty:
        return df
    df.columns = ["open", "high", "low", "close", "volume", "change_pct"]
    return df


def _fetch_ohlcv_us(ticker: str, days_back: int = 120) -> pd.DataFrame:
    start = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    df = fdr.DataReader(ticker, start)
    if df.empty:
        return df
    result = pd.DataFrame({
        "open": df["Open"],
        "high": df["High"],
        "low": df["Low"],
        "close": df["Close"],
        "volume": df["Volume"],
    })
    if "Change" in df.columns:
        result["change_pct"] = df["Change"] * 100
    else:
        result["change_pct"] = result["close"].pct_change() * 100
    return result


def fetch_fundamentals(ticker: str) -> dict:
    start, end = get_trading_dates(5)
    df = krx.get_market_fundamental(start, end, ticker)
    if df.empty:
        return {}
    latest = df.iloc[-1]
    return {
        "bps": latest.get("BPS", 0),
        "per": latest.get("PER", 0),
        "pbr": latest.get("PBR", 0),
        "eps": latest.get("EPS", 0),
        "div_yield": latest.get("DIV", 0),
    }


def fetch_market_cap(ticker: str) -> dict:
    if is_us_ticker(ticker):
        return _fetch_market_cap_us(ticker)
    listing = fdr.StockListing("KRX")
    row = listing[listing["Code"] == ticker]
    if row.empty:
        return {}
    return {
        "market_cap": int(row.iloc[0].get("Marcap", 0)),
        "shares": int(row.iloc[0].get("Stocks", 0)),
    }


def _fetch_market_cap_us(ticker: str) -> dict:
    try:
        import yfinance as yf
        info = yf.Ticker(ticker).info
        return {
            "market_cap": int(info.get("marketCap", 0)),
            "shares": int(info.get("sharesOutstanding", 0)),
        }
    except Exception:
        return {}


def fetch_index_ohlcv(index_symbol: str = "KS11", days_back: int = 120) -> pd.DataFrame:
    """지수 데이터 — FinanceDataReader 사용
    한국: KS11(코스피), KQ11(코스닥)
    미국: IXIC(나스닥), US500(S&P500)
    """
    start = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    df = fdr.DataReader(index_symbol, start)
    if df.empty:
        return df
    result = pd.DataFrame({
        "open": df["Open"],
        "high": df["High"],
        "low": df["Low"],
        "close": df["Close"],
        "volume": df["Volume"],
    })
    return result


def get_kospi_tickers() -> list[str]:
    return krx.get_market_ticker_list(datetime.now().strftime("%Y%m%d"), market="KOSPI")


def get_kosdaq_tickers() -> list[str]:
    return krx.get_market_ticker_list(datetime.now().strftime("%Y%m%d"), market="KOSDAQ")


_US_LISTING_CACHE: pd.DataFrame | None = None


def _get_us_listing() -> pd.DataFrame:
    global _US_LISTING_CACHE
    if _US_LISTING_CACHE is None:
        nasdaq = fdr.StockListing("NASDAQ")
        nyse = fdr.StockListing("NYSE")
        _US_LISTING_CACHE = pd.concat([nasdaq, nyse], ignore_index=True)
    return _US_LISTING_CACHE


def get_ticker_name(ticker: str) -> str:
    if is_us_ticker(ticker):
        listing = _get_us_listing()
        row = listing[listing["Symbol"] == ticker.upper()]
        if not row.empty:
            return str(row.iloc[0].get("Name", ticker))
        return ticker
    return krx.get_market_ticker_name(ticker)


def fetch_top_market_cap(market: str = "KOSPI", top_n: int = 50) -> pd.DataFrame:
    date = datetime.now().strftime("%Y%m%d")
    df = krx.get_market_cap(date, market=market)
    if df.empty:
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
        df = krx.get_market_cap(yesterday, market=market)
    if df.empty:
        for i in range(2, 5):
            day = (datetime.now() - timedelta(days=i)).strftime("%Y%m%d")
            df = krx.get_market_cap(day, market=market)
            if not df.empty:
                break
    if df.empty:
        return df
    df = df.sort_values("시가총액", ascending=False).head(top_n)
    return df
