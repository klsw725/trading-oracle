"""포지션 사이징 — 포트폴리오 레벨 체크 + BUY/SELL 전략 계산

PRD: BUY/SELL 시 포트폴리오 기반 매매 전략 출력
"""

from __future__ import annotations

import math


# ── 기본값 (config.yaml position_sizing로 오버라이드 가능) ──

_DEFAULT_RISK_PER_TRADE = {"very_high": 3, "high": 2, "moderate": 1}
_DEFAULT_FIRST_TRANCHE = {"very_high": 50, "high": 33, "moderate": 25}
_DEFAULT_SELL_RATIO = {"very_high": 100, "high": 67, "moderate": 33}
_DEFAULT_MAX_WEIGHT_PCT = 33
_DEFAULT_PORTFOLIO_LOSS_LIMIT = -10
_DEFAULT_CASH_FLOOR = {"bull": 20, "bear": 30, "sideways": 25}


def _get_sizing_config(config: dict) -> dict:
    """config.yaml에서 position_sizing 섹션을 읽고 기본값과 병합."""
    ps = config.get("position_sizing", {})
    return {
        "risk_per_trade": {**_DEFAULT_RISK_PER_TRADE, **ps.get("risk_per_trade", {})},
        "first_tranche": {**_DEFAULT_FIRST_TRANCHE, **ps.get("first_tranche", {})},
        "sell_ratio": {**_DEFAULT_SELL_RATIO, **ps.get("sell_ratio", {})},
        "max_weight_pct": ps.get("max_weight_pct", _DEFAULT_MAX_WEIGHT_PCT),
        "portfolio_loss_limit": ps.get("portfolio_loss_limit", _DEFAULT_PORTFOLIO_LOSS_LIMIT),
        "cash_floor": {**_DEFAULT_CASH_FLOOR, **ps.get("cash_floor", {})},
    }


# ── 포트폴리오 레벨 체크 ──

def check_portfolio_health(
    portfolio: dict,
    market_regime: str,
    config: dict,
) -> dict:
    """포트폴리오 건전성 평가. BUY/SELL 전략 계산 전에 호출.

    Returns:
        portfolio_health: "healthy" | "caution" | "danger"
        cash_ratio: 현재 현금 비중 %
        cash_floor: 레짐별 현금 하한 %
        available_cash: 매수 가능 현금 (cash_floor 보호분 제외)
        total_pnl_pct: 전체 손익률
        can_buy: 매수 가능 여부
        buy_block_reason: 차단 사유
        overweight_tickers: 비중 초과 종목
        forced_sell_tickers: 강제 감축 대상
    """
    sc = _get_sizing_config(config)
    positions = portfolio.get("positions", [])
    cash = portfolio.get("cash", 0)
    max_positions = config.get("max_positions", 3)

    # 총 자산 / 손익
    total_invested = sum(p["entry_price"] * p["shares"] for p in positions)
    total_market_value = sum(
        p.get("market_value", p["entry_price"] * p["shares"]) for p in positions
    )
    total_assets = total_market_value + cash
    total_pnl_pct = (
        (total_market_value - total_invested) / total_invested * 100
        if total_invested > 0
        else 0
    )

    # 현금 비중
    cash_ratio = (cash / total_assets * 100) if total_assets > 0 else 100
    regime_key = market_regime if market_regime in sc["cash_floor"] else "sideways"
    cash_floor_pct = sc["cash_floor"][regime_key]
    cash_floor_amount = total_assets * cash_floor_pct / 100
    available_cash = max(0, cash - cash_floor_amount)

    # 종목 집중도 체크
    max_weight = sc["max_weight_pct"]
    overweight = []
    for p in positions:
        mv = p.get("market_value", p["entry_price"] * p["shares"])
        weight = (mv / total_assets * 100) if total_assets > 0 else 0
        if weight > max_weight:
            overweight.append({
                "ticker": p["ticker"],
                "name": p["name"],
                "weight_pct": round(weight, 1),
                "excess_pct": round(weight - max_weight, 1),
            })

    # 강제 감축 대상
    forced_sell = []
    loss_limit = sc["portfolio_loss_limit"]
    if total_pnl_pct < loss_limit and positions:
        # 최악 종목부터 정렬
        sorted_pos = sorted(positions, key=lambda p: p.get("pnl_pct", 0))
        for p in sorted_pos:
            if p.get("pnl_pct", 0) < 0:
                forced_sell.append({
                    "ticker": p["ticker"],
                    "name": p["name"],
                    "pnl_pct": round(p.get("pnl_pct", 0), 1),
                })

    # 매수 가능 여부
    can_buy = True
    buy_block_reason = None

    if len(positions) >= max_positions:
        can_buy = False
        buy_block_reason = f"최대 보유 종목 수({max_positions}) 도달"
    elif cash_ratio < cash_floor_pct:
        can_buy = False
        buy_block_reason = f"현금 비중 {cash_ratio:.1f}% < 하한 {cash_floor_pct}%"
    elif available_cash <= 0:
        can_buy = False
        buy_block_reason = "매수 가능 현금 없음"
    elif forced_sell:
        can_buy = False
        buy_block_reason = f"포트폴리오 손실 {total_pnl_pct:.1f}% — 감축 우선"

    # 상관 리스크 분석 (Phase 19)
    correlation_risk = {}
    sector_concentration = {}
    diversification_score = 0.0
    if len(positions) >= 2:
        try:
            from src.portfolio.correlation import (
                compute_correlation_matrix, compute_sector_concentration,
                compute_diversification_score,
            )
            corr_config = config.get("correlation", {})
            window = corr_config.get("window_days", 60)

            ptickers = [p["ticker"] for p in positions]
            corr_matrix = compute_correlation_matrix(ptickers, days_back=window)

            if corr_matrix is not None:
                high_pairs = []
                max_pair_corr = 0.0
                threshold = corr_config.get("max_pair_correlation", 0.7)
                for i, t1 in enumerate(ptickers):
                    for j, t2 in enumerate(ptickers):
                        if i < j and t1 in corr_matrix.index and t2 in corr_matrix.columns:
                            c = abs(corr_matrix.loc[t1, t2])
                            if c > max_pair_corr:
                                max_pair_corr = c
                            if c > threshold:
                                n1 = next((p["name"] for p in positions if p["ticker"] == t1), t1)
                                n2 = next((p["name"] for p in positions if p["ticker"] == t2), t2)
                                high_pairs.append((t1, t2, round(c, 3), n1, n2))

                correlation_risk = {
                    "max_pair_correlation": round(max_pair_corr, 3),
                    "high_corr_pairs": high_pairs,
                }

            sector_concentration = compute_sector_concentration(positions)
            diversification_score = compute_diversification_score(corr_matrix, sector_concentration)
        except Exception:
            pass

    # 건전성 등급
    has_corr_risk = bool(correlation_risk.get("high_corr_pairs"))
    is_sector_concentrated = sector_concentration.get("is_concentrated", False)

    if forced_sell or total_pnl_pct < loss_limit:
        health = "danger"
    elif not can_buy or overweight or cash_ratio < cash_floor_pct + 5:
        health = "caution"
    elif has_corr_risk or is_sector_concentrated:
        health = "caution"
    else:
        health = "healthy"

    return {
        "portfolio_health": health,
        "cash_ratio": round(cash_ratio, 1),
        "cash_floor": cash_floor_pct,
        "available_cash": round(available_cash),
        "total_assets": round(total_assets),
        "total_pnl_pct": round(total_pnl_pct, 1),
        "can_buy": can_buy,
        "buy_block_reason": buy_block_reason,
        "overweight_tickers": overweight,
        "forced_sell_tickers": forced_sell,
        "num_positions": len(positions),
        "max_positions": max_positions,
        "correlation_risk": correlation_risk,
        "sector_concentration": sector_concentration,
        "diversification_score": diversification_score,
    }


# ── BUY 사이징 ──

def _fx_sizing_multiplier(fx_signal: dict | None, fx_regime: dict | None, config: dict) -> float:
    """환율 팩터 기반 포지션 사이징 조정 계수 (Phase 17).

    Returns:
        0.7 ~ 1.15 사이의 배수. 기본 1.0.
    """
    if not fx_signal or not fx_regime:
        return 1.0

    fx_config = config.get("forex", {}).get("sizing_adjustment", {})
    fx_class = fx_signal.get("fx_class", "neutral")
    regime = fx_regime.get("fx_regime", "unknown")
    is_extreme = fx_regime.get("is_extreme", False)

    # 극단 환율 → 전체 축소
    if is_extreme:
        return fx_config.get("extreme_cap", 0.70)

    if regime in ("krw_weak", "krw_extreme_weak"):
        if fx_class == "export":
            return fx_config.get("weak_export", 1.15)
        elif fx_class == "import":
            return fx_config.get("weak_import", 0.85)
    elif regime in ("krw_strong", "krw_extreme_strong"):
        if fx_class == "export":
            return fx_config.get("strong_export", 0.90)
        elif fx_class == "import":
            return fx_config.get("strong_import", 1.10)

    return 1.0


def compute_buy_plan(
    current_price: float,
    stop_price: float,
    confidence: str,
    portfolio: dict,
    portfolio_check: dict,
    config: dict,
    ticker: str | None = None,
    fx_signal: dict | None = None,
    fx_regime: dict | None = None,
) -> dict | None:
    """BUY 합의 시 분할 매수 전략 계산.

    Args:
        current_price: 현재가
        stop_price: 손절가 (trailing_stop_10pct)
        confidence: "very_high" | "high" | "moderate"
        portfolio: 포트폴리오 dict
        portfolio_check: check_portfolio_health() 결과
        config: config.yaml
        ticker: 종목코드 (기존 보유 체크용)

    Returns:
        action_plan dict 또는 None (매수 불가 시)
    """
    if not portfolio_check["can_buy"]:
        return {
            "type": "buy_blocked",
            "reason": portfolio_check["buy_block_reason"],
        }

    sc = _get_sizing_config(config)
    total_assets = portfolio_check["total_assets"]
    available_cash = portfolio_check["available_cash"]
    max_weight_pct = sc["max_weight_pct"]

    # 손절가까지의 거리
    loss_per_share = current_price - stop_price
    if loss_per_share <= 0:
        return {
            "type": "buy_blocked",
            "reason": "손절가가 현재가 이상 — 매수 불가",
        }

    # Step 1: 목표 수량 (손절 기반)
    risk_pct = sc["risk_per_trade"].get(confidence, 1) / 100
    max_risk = total_assets * risk_pct
    target_shares = int(max_risk / loss_per_share)

    # Step 2: 포트폴리오 제약
    max_weight_amount = total_assets * max_weight_pct / 100
    existing_value = 0
    if ticker:
        for p in portfolio.get("positions", []):
            if p["ticker"] == ticker:
                existing_value = p.get("market_value", p["entry_price"] * p["shares"])
                break
    remaining_weight = max_weight_amount - existing_value
    max_shares_by_weight = int(remaining_weight / current_price) if current_price > 0 else 0
    max_shares_by_cash = int(available_cash / current_price) if current_price > 0 else 0

    target_shares = max(1, min(target_shares, max_shares_by_weight, max_shares_by_cash))

    # Step 2.5: 환율 팩터 조정 (Phase 17)
    fx_mult = _fx_sizing_multiplier(fx_signal, fx_regime, config)
    if fx_mult != 1.0:
        target_shares = max(1, int(target_shares * fx_mult))

    # Step 3: 분할 매수 비율
    tranche_pct = sc["first_tranche"].get(confidence, 25) / 100
    first_shares = max(1, math.ceil(target_shares * tranche_pct))
    first_shares = min(first_shares, target_shares)

    investment = round(current_price * first_shares)
    risk_amount = round(loss_per_share * first_shares)
    cash_after = portfolio.get("cash", 0) - investment
    total_after = total_assets - investment + investment  # 자산 총액은 변하지 않음 (현금→주식)
    weight_after = (existing_value + investment) / total_after * 100 if total_after > 0 else 0
    cash_ratio_after = cash_after / total_after * 100 if total_after > 0 else 0

    return {
        "type": "buy",
        "entry_price": current_price,
        "stop_loss": stop_price,
        "target_shares": target_shares,
        "first_tranche_shares": first_shares,
        "first_tranche_pct": sc["first_tranche"].get(confidence, 25),
        "investment": investment,
        "remaining_shares": target_shares - first_shares,
        "risk_amount": risk_amount,
        "risk_pct": round(risk_amount / total_assets * 100, 1) if total_assets > 0 else 0,
        "weight_pct": round(weight_after, 1),
        "portfolio_cash_after": round(cash_after),
        "portfolio_cash_ratio_after": round(cash_ratio_after, 1),
        "note": "추세 확인 후 2차 매수 검토" if first_shares < target_shares else None,
        "fx_adjustment": round(fx_mult, 2) if fx_mult != 1.0 else None,
    }


# ── SELL 사이징 ──

def compute_sell_plan(
    current_price: float,
    confidence: str,
    portfolio: dict,
    portfolio_check: dict,
    config: dict,
    ticker: str,
    fx_signal: dict | None = None,
    fx_regime: dict | None = None,
) -> dict | None:
    """SELL 합의 시 매도 전략 계산.

    Args:
        current_price: 현재가
        confidence: "very_high" | "high" | "moderate"
        portfolio: 포트폴리오 dict
        portfolio_check: check_portfolio_health() 결과
        config: config.yaml
        ticker: 종목코드

    Returns:
        action_plan dict 또는 None (미보유 시)
    """
    pos = next((p for p in portfolio.get("positions", []) if p["ticker"] == ticker), None)
    if not pos:
        return {"type": "sell_blocked", "reason": "매도 대상 없음 (미보유)"}

    sc = _get_sizing_config(config)
    total_shares = pos["shares"]
    entry_price = pos["entry_price"]
    stop_loss = pos.get("stop_loss", entry_price * 0.9)
    trailing_stop = pos.get("trailing_stop", stop_loss)

    # Step 1: 손절매 체크 — 전량 즉시
    hit_stop = current_price <= stop_loss
    hit_trailing = current_price <= trailing_stop
    if hit_stop or hit_trailing:
        sell_shares = total_shares
        sell_reason = "손절매 도달" if hit_stop else "추적 손절매 도달"
        urgency = "immediate"
    else:
        # Step 2: 합의 강도별 비율
        sell_pct = sc["sell_ratio"].get(confidence, 33) / 100
        sell_shares = max(1, math.ceil(total_shares * sell_pct))
        sell_reason = f"합의 강도별 분할 ({sc['sell_ratio'].get(confidence, 33)}%)"
        urgency = "planned"

    # Step 2.5: 환율 기반 매도 비율 조정 (Phase 17)
    if fx_signal and fx_regime and urgency != "immediate":
        fx_class = fx_signal.get("fx_class", "neutral")
        fx_reg = fx_regime.get("fx_regime", "unknown")
        if fx_reg == "krw_extreme_weak" and fx_class == "import":
            sell_shares = max(sell_shares, math.ceil(total_shares * (sell_pct + 0.20)))
            sell_reason = "원화 급락 + 내수주 — 환율 리스크 감축"
        elif fx_reg == "krw_extreme_strong" and fx_class == "export":
            sell_shares = max(sell_shares, math.ceil(total_shares * (sell_pct + 0.10)))
            sell_reason = "원화 급등 + 수출주 — 환율 리스크 감축"

    # Step 3: 포트폴리오 레벨 조정
    loss_limit = sc["portfolio_loss_limit"]
    cash_floor_pct = portfolio_check["cash_floor"]
    cash_ratio = portfolio_check["cash_ratio"]

    if portfolio_check["total_pnl_pct"] < loss_limit:
        sell_shares = max(sell_shares, math.ceil(total_shares * 2 / 3))
        sell_reason = f"포트폴리오 손실 {portfolio_check['total_pnl_pct']:.1f}% — 감축"
        urgency = "immediate"
    elif cash_ratio < cash_floor_pct:
        sell_shares = max(sell_shares, math.ceil(total_shares * 2 / 3))
        sell_reason = f"현금 비중 부족 ({cash_ratio:.0f}% < {cash_floor_pct}%) — 비중 축소"

    sell_shares = min(sell_shares, total_shares)
    remaining = total_shares - sell_shares

    pnl_per_share = current_price - entry_price
    expected_pnl = round(pnl_per_share * sell_shares)
    expected_pnl_pct = round(pnl_per_share / entry_price * 100, 1) if entry_price > 0 else 0

    proceeds = round(current_price * sell_shares)
    cash_after = portfolio.get("cash", 0) + proceeds
    total_assets = portfolio_check["total_assets"]
    cash_ratio_after = cash_after / total_assets * 100 if total_assets > 0 else 0

    return {
        "type": "sell",
        "sell_price": current_price,
        "total_shares": total_shares,
        "sell_shares": sell_shares,
        "sell_ratio": round(sell_shares / total_shares * 100) if total_shares > 0 else 0,
        "remaining_shares": remaining,
        "expected_pnl": expected_pnl,
        "expected_pnl_pct": expected_pnl_pct,
        "sell_reason": sell_reason,
        "portfolio_cash_after": round(cash_after),
        "portfolio_cash_ratio_after": round(cash_ratio_after, 1),
        "urgency": urgency,
    }


# ── 통합 엔트리포인트 ──

def compute_action_plan(
    ticker: str,
    current_price: float,
    stop_price: float,
    consensus_verdict: str,
    confidence: str,
    portfolio: dict,
    portfolio_check: dict,
    config: dict,
    fx_signal: dict | None = None,
    fx_regime: dict | None = None,
) -> dict | None:
    """합의 결과에 따라 BUY/SELL action_plan 계산.

    HOLD / DIVIDED / INSUFFICIENT → None 반환.
    """
    if consensus_verdict == "BUY":
        return compute_buy_plan(
            current_price, stop_price, confidence,
            portfolio, portfolio_check, config, ticker,
            fx_signal=fx_signal, fx_regime=fx_regime,
        )
    elif consensus_verdict == "SELL":
        return compute_sell_plan(
            current_price, confidence,
            portfolio, portfolio_check, config, ticker,
            fx_signal=fx_signal, fx_regime=fx_regime,
        )
    return None
