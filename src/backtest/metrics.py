"""백테스트 성과 지표 — Phase 18 M2"""

import numpy as np


def compute_metrics(
    equity_curve: list[float],
    trades: list[dict],
    trading_days_per_year: int = 252,
) -> dict:
    """백테스트 결과에서 성과 지표를 계산.

    Args:
        equity_curve: 일별 포트폴리오 가치 리스트
        trades: 거래 내역 리스트
        trading_days_per_year: 연간 거래일

    Returns:
        성과 지표 dict
    """
    if len(equity_curve) < 2:
        return {"error": "데이터 부족"}

    eq = np.array(equity_curve, dtype=float)
    initial = eq[0]
    final = eq[-1]
    n_days = len(eq) - 1

    # 누적 수익률
    total_return = (final - initial) / initial * 100

    # 연환산 수익률 (CAGR)
    years = n_days / trading_days_per_year
    if years > 0 and final > 0:
        cagr = ((final / initial) ** (1 / years) - 1) * 100
    else:
        cagr = 0.0

    # 일간 수익률
    daily_returns = np.diff(eq) / eq[:-1]

    # 샤프 비율 (무위험 수익률 = 0)
    if len(daily_returns) > 1 and np.std(daily_returns) > 1e-10:
        sharpe = np.mean(daily_returns) / np.std(daily_returns) * np.sqrt(trading_days_per_year)
    else:
        sharpe = 0.0

    # 최대 낙폭 (MDD)
    peak = np.maximum.accumulate(eq)
    drawdown = (eq - peak) / peak * 100
    mdd = float(np.min(drawdown))

    # 거래 분석
    completed = [t for t in trades if t.get("pnl_pct") is not None]
    wins = [t for t in completed if t["pnl_pct"] > 0]
    losses = [t for t in completed if t["pnl_pct"] <= 0]

    win_rate = len(wins) / len(completed) * 100 if completed else 0
    avg_win = np.mean([t["pnl_pct"] for t in wins]) if wins else 0
    avg_loss = np.mean([t["pnl_pct"] for t in losses]) if losses else 0
    profit_factor = abs(avg_win / avg_loss) if avg_loss != 0 else float("inf")

    # 평균 보유 기간
    hold_days = [t.get("hold_days", 0) for t in completed if t.get("hold_days")]
    avg_hold = np.mean(hold_days) if hold_days else 0

    return {
        "initial_capital": round(initial),
        "final_value": round(final),
        "total_return_pct": round(total_return, 2),
        "cagr_pct": round(cagr, 2),
        "sharpe_ratio": round(float(sharpe), 2),
        "mdd_pct": round(float(mdd), 2),
        "total_trades": len(completed),
        "win_rate_pct": round(win_rate, 1),
        "avg_win_pct": round(float(avg_win), 2),
        "avg_loss_pct": round(float(avg_loss), 2),
        "profit_factor": round(float(profit_factor), 2) if profit_factor != float("inf") else "∞",
        "avg_hold_days": round(float(avg_hold), 1),
        "trading_days": n_days,
    }
