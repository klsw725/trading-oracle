"""환율 팩터 시스템 — Phase 17

M2: 종목별 환율 베타 + 수출/내수 분류
M3: 환율 시그널 생성
M5: 환율 레짐 감지
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd

FX_BETA_CACHE = Path("data/fx_beta_cache.json")

# 섹터-통화 매핑 (종목명 키워드 → 관련 통화)
SECTOR_FX_MAP = {
    "반도체": ["USD_KRW"],
    "전자": ["USD_KRW"],
    "하이닉스": ["USD_KRW"],
    "자동차": ["USD_KRW", "JPY_KRW"],
    "기아": ["USD_KRW", "JPY_KRW"],
    "현대": ["USD_KRW", "JPY_KRW"],
    "화학": ["USD_KRW", "CNY_KRW"],
    "철강": ["CNY_KRW"],
    "포스코": ["CNY_KRW"],
    "조선": ["USD_KRW", "EUR_KRW"],
    "에너지": ["USD_KRW"],
    "배터리": ["USD_KRW", "CNY_KRW"],
    "금융": ["USD_KRW"],
    "은행": ["USD_KRW"],
    "에어로": ["USD_KRW"],
    "바이오": ["USD_KRW"],
    "제약": ["USD_KRW"],
}

# 섹터 기반 환율 민감도 분류 (펀더멘털 기반 — 베타와 독립)
# 한국 시장에서는 리스크오프 시 원화 약세 + 주가 하락이 동시 발생하므로
# 순수 베타로는 수출주/내수주를 구분할 수 없음.
SECTOR_FX_CLASS = {
    # 수출주: 원화 약세 → 수출 채산성 개선 → 펀더멘털 양호
    "반도체": "export", "전자": "export", "하이닉스": "export",
    "자동차": "export", "기아": "export", "현대": "export",
    "조선": "export", "에어로": "export",
    "배터리": "export", "에너지": "export",
    # 내수/수입주: 원화 약세 → 원가 부담 증가
    "항공": "import", "여행": "import",
    "음식": "import", "리테일": "import", "마트": "import",
    # 금융: 환율 중립 (간접 영향)
    "금융": "neutral", "은행": "neutral", "보험": "neutral",
    # 바이오: 혼합 (원료 수입 + 해외 매출)
    "바이오": "neutral", "제약": "neutral",
}


def _get_sector_currencies(name: str) -> list[str]:
    """종목명에서 관련 통화 목록을 추출."""
    currencies = set()
    for keyword, curs in SECTOR_FX_MAP.items():
        if keyword in name:
            currencies.update(curs)
    if not currencies:
        currencies.add("USD_KRW")
    return list(currencies)


# ── M2: 환율 베타 계산 ──

def compute_fx_beta(
    ticker_ohlcv: pd.DataFrame,
    fx_series: pd.Series,
    window: int = 60,
) -> float | None:
    """종목 일간 수익률과 환율 일간 수익률의 롤링 베타.

    양수 = 원화 약세 시 주가 상승 (수출주)
    음수 = 원화 약세 시 주가 하락 (내수주)
    """
    if len(ticker_ohlcv) < window or len(fx_series) < window:
        return None

    stock_ret = ticker_ohlcv["close"].pct_change().dropna()
    fx_ret = fx_series.pct_change().dropna()

    # 날짜 정렬 후 교집합
    common = stock_ret.index.intersection(fx_ret.index)
    if len(common) < window:
        return None

    sr = stock_ret.loc[common].values[-window:]
    fr = fx_ret.loc[common].values[-window:]

    cov = np.cov(sr, fr)
    var_fx = cov[1, 1]
    if var_fx < 1e-12:
        return 0.0
    return float(cov[0, 1] / var_fx)


def classify_fx_sensitivity(name: str) -> str:
    """섹터 기반 환율 민감도 분류.

    한국 시장에서는 리스크오프 시 원화 약세와 주가 하락이 동시 발생하므로
    순수 통계 베타로는 수출주/내수주를 구분할 수 없음.
    종목명 키워드로 펀더멘털 기반 분류.
    """
    for keyword, fx_class in SECTOR_FX_CLASS.items():
        if keyword in name:
            return fx_class
    return "neutral"


def compute_fx_betas(
    ticker: str,
    name: str,
    ohlcv: pd.DataFrame,
    macro_df: pd.DataFrame,
    config: dict,
) -> dict:
    """종목의 다통화 베타를 계산하고 분류한다.

    Returns:
        {
            "primary_beta": float,
            "fx_class": "export"|"import"|"neutral",
            "betas": {"USD_KRW": 0.45, "JPY_KRW": -0.1, ...},
            "sector_currencies": ["USD_KRW", "JPY_KRW"],
        }
    """
    fx_config = config.get("forex", {})
    window = fx_config.get("beta_window", 60)

    sector_curs = _get_sector_currencies(name)
    betas = {}

    for cur in sector_curs:
        if cur in macro_df.columns:
            beta = compute_fx_beta(ohlcv, macro_df[cur], window=window)
            if beta is not None:
                betas[cur] = round(beta, 4)

    # 주요 베타 = USD_KRW (기본), 없으면 첫 번째 유효 베타
    primary = betas.get("USD_KRW")
    if primary is None and betas:
        primary = next(iter(betas.values()))

    return {
        "primary_beta": primary,
        "fx_class": classify_fx_sensitivity(name),
        "betas": betas,
        "sector_currencies": sector_curs,
    }


# ── M5: 환율 레짐 감지 ──

def detect_fx_regime(
    fx_series: pd.Series,
    config: dict,
) -> dict:
    """USD/KRW 시계열에서 환율 레짐을 감지.

    Returns:
        {
            "fx_regime": "krw_weak"|"krw_strong"|"krw_stable"|"krw_extreme_weak"|"krw_extreme_strong",
            "fx_regime_description": str,
            "usd_krw_ma20": float,
            "usd_krw_ma60": float,
            "usd_krw_bb_position": float,
            "change_20d_pct": float,
            "is_extreme": bool,
        }
    """
    fx_config = config.get("forex", {})
    ma_short = fx_config.get("regime_ma_short", 20)
    ma_long = fx_config.get("regime_ma_long", 60)
    extreme_th = fx_config.get("regime_extreme_threshold", 5.0)

    valid = fx_series.dropna()
    if len(valid) < ma_long + 5:
        return {
            "fx_regime": "unknown",
            "fx_regime_description": "환율 데이터 부족",
            "is_extreme": False,
        }

    closes = valid.values.astype(float)
    ma20 = float(np.mean(closes[-ma_short:]))
    ma60 = float(np.mean(closes[-ma_long:]))

    # 20일 변화율
    if len(closes) >= ma_short:
        chg_20d = (closes[-1] - closes[-ma_short]) / closes[-ma_short] * 100
    else:
        chg_20d = 0.0

    # 볼린저 밴드 위치
    if len(closes) >= ma_short:
        window = closes[-ma_short:]
        sma = np.mean(window)
        std = np.std(window)
        if std > 1e-10:
            upper = sma + 2 * std
            lower = sma - 2 * std
            bb_pos = float(np.clip((closes[-1] - lower) / (upper - lower), 0.0, 1.0))
        else:
            bb_pos = 0.5
    else:
        bb_pos = 0.5

    # 레짐 판정
    is_extreme = abs(chg_20d) >= extreme_th
    if chg_20d >= extreme_th:
        regime = "krw_extreme_weak"
        desc = f"원화 급락 (20일 {chg_20d:+.1f}%%)"
    elif chg_20d <= -extreme_th:
        regime = "krw_extreme_strong"
        desc = f"원화 급등 (20일 {chg_20d:+.1f}%%)"
    elif ma20 > ma60 and chg_20d > 1.0:
        regime = "krw_weak"
        desc = f"원화 약세 (MA20 {ma20:.0f} > MA60 {ma60:.0f})"
    elif ma20 < ma60 and chg_20d < -1.0:
        regime = "krw_strong"
        desc = f"원화 강세 (MA20 {ma20:.0f} < MA60 {ma60:.0f})"
    else:
        regime = "krw_stable"
        desc = f"환율 안정 (20일 {chg_20d:+.1f}%%)"

    return {
        "fx_regime": regime,
        "fx_regime_description": desc,
        "usd_krw_ma20": round(ma20, 1),
        "usd_krw_ma60": round(ma60, 1),
        "usd_krw_bb_position": round(bb_pos, 3),
        "change_20d_pct": round(chg_20d, 2),
        "is_extreme": is_extreme,
    }


def detect_multi_fx_regimes(macro_df: pd.DataFrame, config: dict) -> dict:
    """다통화 레짐 감지. USD/KRW 메인 + JPY/CNY/EUR 보조."""
    result = {}
    for cur in ["USD_KRW", "JPY_KRW", "CNY_KRW", "EUR_KRW"]:
        if cur in macro_df.columns:
            series = macro_df[cur].dropna()
            if len(series) >= 20:
                result[cur] = detect_fx_regime(series, config)
    return result


# ── M3: 환율 시그널 ──

def compute_fx_signal(
    ticker: str,
    name: str,
    ohlcv: pd.DataFrame,
    macro_df: pd.DataFrame,
    fx_regime: dict,
    config: dict,
) -> dict:
    """종목별 환율 시그널 생성.

    Returns:
        {
            "fx_verdict": "BULLISH"|"BEARISH"|"NEUTRAL",
            "fx_confidence": 0.0~1.0,
            "fx_beta": float,
            "fx_class": "export"|"import"|"neutral",
            "components": { ... },
        }
    """
    # 베타 계산
    beta_info = compute_fx_betas(ticker, name, ohlcv, macro_df, config)
    primary_beta = beta_info["primary_beta"]
    fx_class = beta_info["fx_class"]

    regime_label = fx_regime.get("fx_regime", "unknown")
    is_extreme = fx_regime.get("is_extreme", False)
    chg_20d = fx_regime.get("change_20d_pct", 0.0)

    # USD/KRW 5일 변화율
    usd_krw_5d = 0.0
    if "USD_KRW" in macro_df.columns:
        usd = macro_df["USD_KRW"].dropna()
        if len(usd) >= 5:
            usd_krw_5d = (usd.iloc[-1] - usd.iloc[-5]) / usd.iloc[-5] * 100

    # 모멘텀 방향
    if usd_krw_5d > 0.5:
        momentum_dir = "weakening"  # 원화 약세 방향
    elif usd_krw_5d < -0.5:
        momentum_dir = "strengthening"  # 원화 강세 방향
    else:
        momentum_dir = "flat"

    # 변동성
    if "USD_KRW" in macro_df.columns:
        usd = macro_df["USD_KRW"].dropna()
        if len(usd) >= 20:
            vol_20d = float(usd.pct_change().dropna().tail(20).std() * np.sqrt(252) * 100)
        else:
            vol_20d = 0.0
    else:
        vol_20d = 0.0

    vol_level = "high" if vol_20d > 12 else ("normal" if vol_20d > 6 else "low")

    # 레짐-종목 정합성 판정
    boost = "NEUTRAL"
    if regime_label in ("krw_weak", "krw_extreme_weak"):
        if fx_class == "export":
            boost = "BULLISH"
        elif fx_class == "import":
            boost = "BEARISH"
    elif regime_label in ("krw_strong", "krw_extreme_strong"):
        if fx_class == "export":
            boost = "BEARISH"
        elif fx_class == "import":
            boost = "BULLISH"

    # 크로스 통화 시그널
    cross_signals = {}
    for cur in beta_info["sector_currencies"]:
        if cur == "USD_KRW":
            continue
        if cur in macro_df.columns:
            s = macro_df[cur].dropna()
            if len(s) >= 5:
                c5d = (s.iloc[-1] - s.iloc[-5]) / s.iloc[-5] * 100
                cross_signals[cur] = "BEARISH" if c5d > 1.0 else ("BULLISH" if c5d < -1.0 else "NEUTRAL")

    # 최종 verdict + confidence 계산
    score = 0.0
    if boost == "BULLISH":
        score += 0.4
    elif boost == "BEARISH":
        score -= 0.4

    if momentum_dir == "weakening" and fx_class == "export":
        score += 0.2
    elif momentum_dir == "strengthening" and fx_class == "export":
        score -= 0.2
    elif momentum_dir == "weakening" and fx_class == "import":
        score -= 0.2
    elif momentum_dir == "strengthening" and fx_class == "import":
        score += 0.2

    if is_extreme:
        score *= 1.3

    # 크로스 통화 보정 (자동차: JPY 약세 = 한국차 경쟁력 약화)
    for cur, sig in cross_signals.items():
        if cur == "JPY_KRW":
            if sig == "BEARISH":  # JPY/KRW 상승 = 엔 강세 = 한국 수출 유리
                score += 0.1
            elif sig == "BULLISH":  # JPY/KRW 하락 = 엔 약세 = 한국 수출 불리
                score -= 0.1
        elif cur == "CNY_KRW":
            if sig == "BEARISH":  # CNY 약세 = 중국 덤핑 리스크
                score -= 0.1

    if score > 0.15:
        verdict = "BULLISH"
    elif score < -0.15:
        verdict = "BEARISH"
    else:
        verdict = "NEUTRAL"

    confidence = min(abs(score), 1.0)

    return {
        "fx_verdict": verdict,
        "fx_confidence": round(confidence, 2),
        "fx_beta": primary_beta,
        "fx_class": fx_class,
        "betas": beta_info["betas"],
        "components": {
            "momentum": {"usd_krw_5d": round(usd_krw_5d, 2), "direction": momentum_dir},
            "volatility": {"usd_krw_20d_vol": round(vol_20d, 1), "level": vol_level},
            "regime_alignment": {"aligned": boost != "NEUTRAL", "boost": boost},
            "cross_currency": cross_signals,
        },
    }
