"""기술적 분석 시그널 (auto-researchtrading 앙상블 보팅 기반, 일봉 적응)"""

import numpy as np
import pandas as pd


def ema(values: np.ndarray, span: int) -> np.ndarray:
    alpha = 2.0 / (span + 1)
    result = np.empty_like(values, dtype=float)
    result[0] = values[0]
    for i in range(1, len(values)):
        result[i] = alpha * values[i] + (1 - alpha) * result[i - 1]
    return result


def calc_rsi(closes: np.ndarray, period: int = 8) -> float:
    if len(closes) < period + 1:
        return 50.0
    deltas = np.diff(closes[-(period + 1) :])
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    avg_gain = np.mean(gains)
    avg_loss = np.mean(losses)
    if avg_loss < 1e-10:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - 100 / (1 + rs)


def calc_macd(closes: np.ndarray, fast: int = 12, slow: int = 26, signal: int = 9) -> float:
    if len(closes) < slow + signal + 5:
        return 0.0
    data = closes[-(slow + signal + 5) :]
    fast_ema = ema(data, fast)
    slow_ema = ema(data, slow)
    macd_line = fast_ema - slow_ema
    signal_line = ema(macd_line, signal)
    return macd_line[-1] - signal_line[-1]


def calc_bb_width_percentile(closes: np.ndarray, period: int = 20) -> float:
    if len(closes) < period * 3:
        return 50.0
    widths = []
    for i in range(period * 2, len(closes)):
        window = closes[i - period : i]
        sma = np.mean(window)
        std = np.std(window)
        width = (2 * std) / sma if sma > 0 else 0
        widths.append(width)
    if len(widths) < 2:
        return 50.0
    current_width = widths[-1]
    pctile = 100 * np.sum(np.array(widths) <= current_width) / len(widths)
    return pctile


def calc_atr(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, lookback: int = 20) -> float:
    if len(closes) < lookback + 1:
        return closes[-1] * 0.02
    h = highs[-lookback:]
    l = lows[-lookback:]
    c = closes[-(lookback + 1) : -1]
    tr = np.maximum(h - l, np.maximum(np.abs(h - c), np.abs(l - c)))
    return np.mean(tr)


def compute_signals(df: pd.DataFrame, config: dict) -> dict:
    """OHLCV DataFrame에서 6-시그널 앙상블 보팅 계산.

    Returns dict with signal details and final verdict.
    """
    if len(df) < 60:
        return {"error": "데이터 부족 (최소 60일 필요)"}

    closes = df["close"].values.astype(float)
    highs = df["high"].values.astype(float)
    lows = df["low"].values.astype(float)

    cfg = config.get("signals", {})
    ema_fast_period = cfg.get("ema_fast", 5)
    ema_slow_period = cfg.get("ema_slow", 20)
    rsi_period = cfg.get("rsi_period", 8)
    rsi_ob = cfg.get("rsi_overbought", 69)
    rsi_os = cfg.get("rsi_oversold", 31)
    macd_fast = cfg.get("macd_fast", 12)
    macd_slow = cfg.get("macd_slow", 26)
    macd_signal = cfg.get("macd_signal", 9)
    bb_period = cfg.get("bb_period", 20)
    mom_window = cfg.get("momentum_window", 20)
    min_votes = cfg.get("min_votes", 4)

    current_price = closes[-1]

    # Signal 1: Momentum (mom_window일 수익률)
    ret_mom = (closes[-1] - closes[-mom_window]) / closes[-mom_window]
    threshold = 0.03  # 일봉에서는 3% 기준
    mom_bull = ret_mom > threshold
    mom_bear = ret_mom < -threshold

    # Signal 2: Short-term Momentum (5일)
    ret_short = (closes[-1] - closes[-5]) / closes[-5] if len(closes) >= 5 else 0
    short_bull = ret_short > threshold * 0.5
    short_bear = ret_short < -threshold * 0.5

    # Signal 3: EMA Crossover
    ema_fast_arr = ema(closes[-(ema_slow_period + 10) :], ema_fast_period)
    ema_slow_arr = ema(closes[-(ema_slow_period + 10) :], ema_slow_period)
    ema_bull = ema_fast_arr[-1] > ema_slow_arr[-1]
    ema_bear = ema_fast_arr[-1] < ema_slow_arr[-1]

    # Signal 4: RSI
    rsi = calc_rsi(closes, rsi_period)
    rsi_bull = rsi > 50
    rsi_bear = rsi < 50

    # Signal 5: MACD
    macd_hist = calc_macd(closes, macd_fast, macd_slow, macd_signal)
    macd_bull_sig = macd_hist > 0
    macd_bear_sig = macd_hist < 0

    # Signal 6: BB Compression (방향 중립 — 양쪽 모두 투표)
    bb_pctile = calc_bb_width_percentile(closes, bb_period)
    bb_compressed = bb_pctile < 80

    # Voting
    bull_votes = sum([mom_bull, short_bull, ema_bull, rsi_bull, macd_bull_sig, bb_compressed])
    bear_votes = sum([mom_bear, short_bear, ema_bear, rsi_bear, macd_bear_sig, bb_compressed])

    if bull_votes >= min_votes:
        verdict = "BULLISH"
    elif bear_votes >= min_votes:
        verdict = "BEARISH"
    else:
        verdict = "NEUTRAL"

    # ATR for stop loss calculation
    atr = calc_atr(highs, lows, closes)
    trailing_stop = current_price - 3.0 * atr  # 일봉은 ATR 3배

    # 고점/저점
    high_52w = np.max(highs[-min(252, len(highs)) :])
    low_52w = np.min(lows[-min(252, len(lows)) :])
    high_20d = np.max(highs[-20:])

    # 추적 손절매 가격 (고점 대비 10%)
    trailing_stop_10pct = high_20d * 0.9

    return {
        "current_price": current_price,
        "verdict": verdict,
        "bull_votes": bull_votes,
        "bear_votes": bear_votes,
        "signals": {
            "momentum": {"value": ret_mom * 100, "bull": mom_bull, "bear": mom_bear},
            "short_momentum": {"value": ret_short * 100, "bull": short_bull, "bear": short_bear},
            "ema_crossover": {"fast": ema_fast_arr[-1], "slow": ema_slow_arr[-1], "bull": ema_bull, "bear": ema_bear},
            "rsi": {"value": rsi, "bull": rsi_bull, "bear": rsi_bear, "overbought": rsi > rsi_ob, "oversold": rsi < rsi_os},
            "macd": {"histogram": macd_hist, "bull": macd_bull_sig, "bear": macd_bear_sig},
            "bb_compression": {"percentile": bb_pctile, "compressed": bb_compressed},
        },
        "atr": atr,
        "trailing_stop_atr": trailing_stop,
        "trailing_stop_10pct": trailing_stop_10pct,
        "high_52w": high_52w,
        "low_52w": low_52w,
        "high_20d": high_20d,
        "change_5d": ret_short * 100,
        "change_20d": ret_mom * 100,
    }
