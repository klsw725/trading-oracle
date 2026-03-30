"""매크로 변수 정량 시계열 수집 — Phase 11

12개 매크로 변수를 FDR로 수집, parquet 캐시, 파생 지표 계산.
Phase 12 Granger 검증의 입력 데이터.
"""

from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import FinanceDataReader as fdr

MACRO_PARQUET = Path("data/macro_series.parquet")

# 수집 대상 (SPEC §3-1)
# FDR은 Yahoo Finance 기반 — 금리는 ^TNX 등 Yahoo 심볼 사용
MACRO_SYMBOLS = {
    "US10YT": "^TNX",         # 미국 10년 국채금리 (Yahoo)
    "US30YT": "^TYX",         # 미국 30년 국채금리 (Yahoo)
    "US13WT": "^IRX",         # 미국 13주 T-Bill (Yahoo)
    "USD_KRW": "USD/KRW",    # 원달러 환율
    "JPY_KRW": "JPYKRW=X",   # 엔화 환율 (자동차/전자 경쟁, Yahoo)
    "EUR_KRW": "EURKRW=X",   # 유로 환율 (자동차/조선 수출, Yahoo)
    "DXY": "DX-Y.NYB",       # 달러 인덱스 (Yahoo)
    "WTI": "CL=F",           # WTI 원유
    "GOLD": "GC=F",          # 금
    "KOSPI": "KS11",         # 코스피
    "KOSDAQ": "KQ11",        # 코스닥
    "NASDAQ": "IXIC",        # 나스닥
    "SP500": "US500",        # S&P 500
}


def fetch_macro_series(days_back: int = 730) -> pd.DataFrame:
    """12개 매크로 변수 일간 시계열 수집. parquet 캐시 사용.

    Returns:
        DataFrame (index=Date, columns=변수명). 실패한 변수는 NaN.
    """
    # 캐시 확인: 당일 수집분 존재 시 로드
    if MACRO_PARQUET.exists():
        try:
            cached = pd.read_parquet(MACRO_PARQUET)
            if not cached.empty:
                last_date = cached.index.max()
                if isinstance(last_date, pd.Timestamp):
                    today = pd.Timestamp.now().normalize()
                    if last_date >= today - pd.Timedelta(days=1):
                        return _add_derived(cached)
                    # 증분 수집
                    start = (last_date + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
                    incremental = _fetch_all(start=start)
                    if not incremental.empty:
                        combined = pd.concat([cached, incremental])
                        combined = combined[~combined.index.duplicated(keep="last")]
                        combined = combined.sort_index()
                        # 2년치만 유지
                        cutoff = pd.Timestamp.now() - pd.Timedelta(days=days_back)
                        combined = combined[combined.index >= cutoff]
                        _save(combined)
                        return _add_derived(combined)
                    return _add_derived(cached)
        except Exception:
            pass

    # 초기 수집 (2년치)
    start = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    df = _fetch_all(start=start)
    if not df.empty:
        _save(df)
    return _add_derived(df)


def _fetch_all(start: str) -> pd.DataFrame:
    """모든 매크로 변수 수집. 개별 실패 시 스킵."""
    series = {}
    for name, symbol in MACRO_SYMBOLS.items():
        try:
            raw = fdr.DataReader(symbol, start)
            if not raw.empty and "Close" in raw.columns:
                series[name] = raw["Close"]
        except Exception:
            continue
    if not series:
        return pd.DataFrame()
    df = pd.DataFrame(series)
    df.index.name = "Date"
    return df


def _save(df: pd.DataFrame):
    """parquet으로 저장."""
    MACRO_PARQUET.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(MACRO_PARQUET)


def _add_derived(df: pd.DataFrame) -> pd.DataFrame:
    """파생 지표 계산: 변화율, 차분, 금리차."""
    if df.empty:
        return df

    result = df.copy()

    # 변화율 (5일, 20일) — NaN을 건너뛰고 유효 행 기준으로 계산
    for col in df.columns:
        valid = df[col].dropna()
        if len(valid) >= 20:
            chg5 = valid.pct_change(5) * 100
            chg20 = valid.pct_change(20) * 100
            result[f"{col}_chg5d"] = chg5.reindex(df.index)
            result[f"{col}_chg20d"] = chg20.reindex(df.index)
        # 1일 차분 (Granger test 용 — 정상성 확보)
        diff = valid.diff()
        result[f"{col}_diff"] = diff.reindex(df.index)

    # 장단기 금리차 (10년 - 13주)
    if "US10YT" in df.columns and "US13WT" in df.columns:
        result["US_TERM_SPREAD"] = df["US10YT"] - df["US13WT"]

    # CNY/KRW 크로스레이트 (USD/KRW ÷ USD/CNY)
    if "USD_KRW" in df.columns and "CNY_KRW" not in df.columns:
        try:
            usd_cny = fdr.DataReader("USD/CNY", (df.index.min()).strftime("%Y-%m-%d"))
            if not usd_cny.empty and "Close" in usd_cny.columns:
                cny_series = usd_cny["Close"].reindex(df.index, method="ffill")
                valid = cny_series.notna() & df["USD_KRW"].notna() & (cny_series > 0)
                result.loc[valid, "CNY_KRW"] = df.loc[valid, "USD_KRW"] / cny_series[valid]
        except Exception:
            pass

    return result


def get_macro_snapshot(df: pd.DataFrame | None = None) -> dict:
    """최신 매크로 데이터를 프롬프트 삽입용 dict로 반환.

    Returns:
        {"KR10YT": {"value": 3.42, "chg5d": 0.08, "chg20d": 0.15, "direction": "↑"}, ...}
    """
    if df is None:
        df = fetch_macro_series()
    if df.empty:
        return {}

    snapshot = {}
    # 마지막 유효 행 (주말/공휴일 NaN 스킵)
    base_cols = [c for c in MACRO_SYMBOLS.keys() if c in df.columns]
    valid = df[base_cols].dropna(how="all")
    if valid.empty:
        return {}
    latest = df.loc[valid.index[-1]]

    for col in MACRO_SYMBOLS.keys():
        if col not in df.columns:
            continue
        val = latest.get(col)
        if pd.isna(val):
            continue

        chg5d = latest.get(f"{col}_chg5d")
        chg20d = latest.get(f"{col}_chg20d")

        # 방향 판정
        direction = "→"
        if pd.notna(chg5d):
            if chg5d > 0.5:
                direction = "↑"
            elif chg5d < -0.5:
                direction = "↓"

        entry = {"value": round(float(val), 2), "direction": direction}
        if pd.notna(chg5d):
            entry["chg5d"] = round(float(chg5d), 2)
        if pd.notna(chg20d):
            entry["chg20d"] = round(float(chg20d), 2)

        snapshot[col] = entry

    return snapshot


def format_macro_for_prompt(snapshot: dict) -> str:
    """매크로 스냅샷을 프롬프트 삽입용 텍스트로 포맷."""
    if not snapshot:
        return ""

    labels = {
        "US10YT": "미국10년국채",
        "US30YT": "미국30년국채",
        "US13WT": "미국13주T-Bill",
        "USD_KRW": "원달러환율",
        "JPY_KRW": "엔화환율",
        "CNY_KRW": "위안화환율",
        "EUR_KRW": "유로환율",
        "DXY": "달러인덱스",
        "WTI": "WTI원유",
        "GOLD": "금",
        "KOSPI": "코스피",
        "KOSDAQ": "코스닥",
        "NASDAQ": "나스닥",
        "SP500": "S&P500",
    }
    units = {
        "US10YT": "%", "US30YT": "%", "US13WT": "%",
        "USD_KRW": "원", "JPY_KRW": "원", "CNY_KRW": "원", "EUR_KRW": "원",
        "DXY": "pt", "WTI": "$", "GOLD": "$",
        "KOSPI": "pt", "KOSDAQ": "pt", "NASDAQ": "pt", "SP500": "pt",
    }

    lines = ["### 매크로 정량 데이터 (시계열)"]
    for key in ["US10YT", "US30YT", "US13WT", "USD_KRW", "JPY_KRW", "CNY_KRW", "EUR_KRW", "DXY", "WTI", "GOLD"]:
        data = snapshot.get(key)
        if not data:
            continue
        label = labels.get(key, key)
        unit = units.get(key, "")
        val = data["value"]
        direction = data.get("direction", "→")
        parts = [f"- {label}: {val}{unit}"]
        if "chg5d" in data:
            parts.append(f"(5일 {data['chg5d']:+.2f}%%")
            if "chg20d" in data:
                parts.append(f"20일 {data['chg20d']:+.2f}%%)")
            else:
                parts[-1] += ")"
        parts.append(direction)
        lines.append(" ".join(parts))

    # 금리차
    if "US_TERM_SPREAD" in str(snapshot):
        pass  # 향후 추가

    return "\n".join(lines)
