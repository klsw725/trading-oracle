"""토스증권 Open API 읽기 전용 시장 데이터 클라이언트."""

from __future__ import annotations

import os
from collections.abc import Mapping
from datetime import datetime, timedelta
from pathlib import Path
from threading import Lock
from time import monotonic
from typing import Any

import httpx
import pandas as pd
import yaml


TOSS_API_BASE_URL = "https://openapi.tossinvest.com"
_client: TossMarketClient | None = None
_client_lock = Lock()


class TossApiError(RuntimeError):
    """토스 API가 반환한 오류."""

    def __init__(self, status_code: int, code: str, request_id: str = "") -> None:
        self.status_code: int = status_code
        self.code: str = code
        self.request_id: str = request_id
        super().__init__(f"Toss API {status_code}: {code} ({request_id})")


class TossMarketClient:
    """OAuth 토큰을 재사용하는 동기 시장 데이터 클라이언트."""

    def __init__(self, client_id: str, client_secret: str, base_url: str = TOSS_API_BASE_URL) -> None:
        self._client_id: str = client_id
        self._client_secret: str = client_secret
        self._http: httpx.Client = httpx.Client(base_url=base_url, timeout=30.0)
        self._access_token: str = ""
        self._token_expires_at: float = 0.0
        self._token_lock: Lock = Lock()

    def candles(self, symbol: str, days_back: int, indicator: bool = False) -> pd.DataFrame:
        """종목 또는 시장 지표의 일봉을 기존 OHLCV 형식으로 반환."""
        path = (
            f"/api/v1/market-indicators/{symbol}/candles"
            if indicator
            else "/api/v1/candles"
        )
        cutoff = datetime.now().astimezone() - timedelta(days=days_back)
        rows: list[dict[str, Any]] = []
        before: str | None = None

        for _ in range(20):
            params: dict[str, str | int | bool] = {
                "interval": "1d",
                "count": 200,
            }
            if not indicator:
                params["symbol"] = symbol
                params["adjusted"] = True
            if before:
                params["before"] = before

            result = self._request("GET", path, params=params).get("result", {})
            if not isinstance(result, dict):
                break
            candles = result.get("candles", [])
            if not isinstance(candles, list) or not candles:
                break
            rows.extend(row for row in candles if isinstance(row, dict))

            oldest = pd.to_datetime(candles[-1].get("timestamp"), errors="coerce")
            before = result.get("nextBefore")
            if not before or (not pd.isna(oldest) and oldest.to_pydatetime() <= cutoff):
                break

        return _normalize_candles(rows, cutoff)

    def prices(self, symbols: list[str]) -> dict[str, float]:
        """최대 200개 종목의 현재가를 심볼별로 반환."""
        result = self._request(
            "GET", "/api/v1/prices", params={"symbols": ",".join(symbols)}
        ).get("result", [])
        if not isinstance(result, list):
            return {}
        return {
            str(item["symbol"]): float(item["lastPrice"])
            for item in result
            if isinstance(item, dict) and item.get("symbol") and item.get("lastPrice")
        }

    def stocks(self, symbols: list[str]) -> list[dict[str, Any]]:
        """최대 200개 종목의 기본 정보를 반환."""
        result = self._request(
            "GET", "/api/v1/stocks", params={"symbols": ",".join(symbols)}
        ).get("result", [])
        return [item for item in result if isinstance(item, dict)] if isinstance(result, list) else []

    def rankings(self, country: str, count: int = 100) -> list[dict[str, Any]]:
        """시장 전체 실시간 거래대금 상위 종목을 반환."""
        result = self._request(
            "GET",
            "/api/v1/rankings",
            params={
                "type": "MARKET_TRADING_AMOUNT",
                "marketCountry": country,
                "duration": "realtime",
                "excludeInvestmentCaution": True,
                "count": min(count, 100),
            },
        ).get("result", {})
        rankings = result.get("rankings", []) if isinstance(result, dict) else []
        return [item for item in rankings if isinstance(item, dict)] if isinstance(rankings, list) else []

    def exchange_rate(self) -> float:
        """KRW/USD 매매기준율을 반환."""
        result = self._request(
            "GET",
            "/api/v1/exchange-rate",
            params={"baseCurrency": "USD", "quoteCurrency": "KRW"},
        ).get("result", {})
        if not isinstance(result, dict):
            raise TossApiError(200, "invalid-exchange-rate-response")
        return float(result["midRate"])

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        response = self._http.request(
            method,
            path,
            headers={"Authorization": f"Bearer {self._token()}"},
            **kwargs,
        )
        payload = response.json()
        if response.is_error:
            error = payload.get("error", {}) if isinstance(payload, dict) else {}
            raise TossApiError(
                response.status_code,
                str(error.get("code", "unknown-error")),
                str(error.get("requestId", "")),
            )
        if not isinstance(payload, dict):
            raise TossApiError(response.status_code, "invalid-response")
        return payload

    def _token(self) -> str:
        with self._token_lock:
            if self._access_token and monotonic() < self._token_expires_at:
                return self._access_token
            response = self._http.post(
                "/oauth2/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                },
            )
            response.raise_for_status()
            payload = response.json()
            self._access_token = str(payload["access_token"])
            self._token_expires_at = monotonic() + max(int(payload["expires_in"]) - 60, 0)
            return self._access_token


def get_toss_client() -> TossMarketClient | None:
    """config.yaml에 인증정보가 있으면 프로세스 공유 Toss 클라이언트를 반환."""
    global _client
    client_id, client_secret = _load_toss_credentials()
    if not client_id or not client_secret:
        return None
    with _client_lock:
        if _client is None:
            base_url = os.getenv("TOSS_API_BASE_URL", TOSS_API_BASE_URL).rstrip("/")
            _client = TossMarketClient(client_id, client_secret, base_url)
    return _client


def _load_toss_credentials() -> tuple[str, str]:
    config_path = Path(__file__).resolve().parents[2] / "config.yaml"
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, Mapping):
        return "", ""
    settings = payload.get("toss")
    if not isinstance(settings, Mapping):
        return "", ""
    return (
        str(settings.get("client_id", "")).strip(),
        str(settings.get("client_secret", "")).strip(),
    )


def fetch_toss_candles(
    symbol: str, days_back: int, indicator: bool = False
) -> pd.DataFrame:
    """Toss가 사용 가능하면 OHLCV를 반환하고 아니면 빈 DataFrame을 반환."""
    client = get_toss_client()
    if client is None:
        return pd.DataFrame()
    try:
        return client.candles(symbol, days_back, indicator)
    except (httpx.HTTPError, TossApiError, KeyError, TypeError, ValueError):
        return pd.DataFrame()


def fetch_toss_market_cap(symbol: str) -> dict[str, int]:
    """Toss 종목정보와 현재가로 계산한 시가총액을 반환."""
    client = get_toss_client()
    if client is None:
        return {}
    try:
        stocks = client.stocks([symbol])
        prices = client.prices([symbol])
        if not stocks or symbol not in prices:
            return {}
        shares = int(float(str(stocks[0].get("sharesOutstanding", 0))))
        return {"market_cap": int(prices[symbol] * shares), "shares": shares}
    except (httpx.HTTPError, TossApiError, KeyError, TypeError, ValueError):
        return {}


def fetch_toss_name(symbol: str) -> str | None:
    """Toss 종목정보의 표시 이름을 반환."""
    client = get_toss_client()
    if client is None:
        return None
    try:
        stocks = client.stocks([symbol])
        return str(stocks[0].get("name") or symbol) if stocks else None
    except (httpx.HTTPError, TossApiError, KeyError, TypeError, ValueError):
        return None


def fetch_toss_exchange_rate() -> float | None:
    """Toss USD/KRW 매매기준율을 반환."""
    client = get_toss_client()
    if client is None:
        return None
    try:
        return client.exchange_rate()
    except (httpx.HTTPError, TossApiError, KeyError, TypeError, ValueError):
        return None


def _normalize_candles(rows: list[dict[str, Any]], cutoff: datetime) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    frame = pd.DataFrame(rows)
    frame.pop("timestamp")
    frame.index = pd.DatetimeIndex(
        datetime.fromisoformat(str(row["timestamp"])).replace(
            hour=0, minute=0, second=0, microsecond=0, tzinfo=None
        )
        for row in rows
    )
    frame = frame.rename(
        columns={
            "openPrice": "open",
            "highPrice": "high",
            "lowPrice": "low",
            "closePrice": "close",
        }
    )
    columns = ["open", "high", "low", "close", "volume"]
    frame = pd.DataFrame(frame.loc[:, columns])
    for column in columns:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=columns)
    frame = pd.DataFrame(frame.loc[~frame.index.duplicated(keep="last")]).sort_index()
    cutoff_date = pd.Timestamp(cutoff.date())
    frame = pd.DataFrame(frame.loc[frame.index >= cutoff_date])
    close = pd.Series(frame["close"], index=frame.index, dtype=float)
    frame["change_pct"] = close.pct_change() * 100
    return pd.DataFrame(frame)
