"""포트폴리오 추적 — 추적 손절매, 기록 관리"""

import json
from pathlib import Path
from datetime import datetime


PORTFOLIO_PATH = Path("data/portfolio.json")


def _normalize_portfolio(portfolio: dict) -> tuple[dict, bool]:
    changed = False

    legacy_cash = portfolio.pop("cash", None)
    if legacy_cash is not None:
        changed = True

    if "cash_krw" not in portfolio:
        portfolio["cash_krw"] = float(legacy_cash or 0)
        changed = True
    else:
        portfolio["cash_krw"] = float(portfolio.get("cash_krw", 0))

    if "cash_usd" not in portfolio:
        portfolio["cash_usd"] = 0.0
        changed = True
    else:
        portfolio["cash_usd"] = float(portfolio.get("cash_usd", 0))

    return portfolio, changed


def load_portfolio() -> dict:
    if PORTFOLIO_PATH.exists():
        portfolio, changed = _normalize_portfolio(
            json.loads(PORTFOLIO_PATH.read_text())
        )
        if changed:
            save_portfolio(portfolio)
        return portfolio
    return _normalize_portfolio(
        {
            "positions": [],
            "cash_krw": 0,
            "cash_usd": 0,
            "history": [],
            "created_at": datetime.now().isoformat(),
        }
    )[0]


class _NumEncoder(json.JSONEncoder):
    def default(self, obj):
        import numpy as np

        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, (np.bool_,)):
            return bool(obj)
        return super().default(obj)


def save_portfolio(portfolio: dict):
    portfolio, _ = _normalize_portfolio(portfolio)
    PORTFOLIO_PATH.parent.mkdir(parents=True, exist_ok=True)
    PORTFOLIO_PATH.write_text(
        json.dumps(portfolio, ensure_ascii=False, indent=2, cls=_NumEncoder)
    )


def get_cash_balance(portfolio: dict, currency: str = "KRW") -> float:
    portfolio, _ = _normalize_portfolio(portfolio)
    field = "cash_usd" if currency == "USD" else "cash_krw"
    return float(portfolio.get(field, 0))


def set_cash(portfolio: dict, amount: float, currency: str = "KRW"):
    portfolio, _ = _normalize_portfolio(portfolio)
    field = "cash_usd" if currency == "USD" else "cash_krw"
    portfolio[field] = amount
    save_portfolio(portfolio)


def adjust_cash_balance(portfolio: dict, delta: float, currency: str = "KRW"):
    portfolio, _ = _normalize_portfolio(portfolio)
    field = "cash_usd" if currency == "USD" else "cash_krw"
    portfolio[field] = float(portfolio.get(field, 0)) + delta
    save_portfolio(portfolio)


def add_position(
    portfolio: dict,
    ticker: str,
    name: str,
    entry_price: float,
    shares: int,
    reason: str = "",
    stop_loss: float | None = None,
):
    if stop_loss is None:
        stop_loss = entry_price * 0.9  # 기본 10% 손절

    # 같은 종목이 이미 있으면 수량/평단가 업데이트
    for pos in portfolio["positions"]:
        if pos["ticker"] == ticker:
            old_total = pos["entry_price"] * pos["shares"]
            new_total = entry_price * shares
            combined_shares = pos["shares"] + shares
            pos["entry_price"] = (old_total + new_total) / combined_shares
            pos["shares"] = combined_shares
            pos["stop_loss"] = stop_loss
            pos["peak_price"] = max(pos.get("peak_price", entry_price), entry_price)
            if reason:
                pos["reason"] = reason
            pos["updated_at"] = datetime.now().isoformat()
            save_portfolio(portfolio)
            return

    position = {
        "ticker": ticker,
        "name": name,
        "entry_price": entry_price,
        "shares": shares,
        "entry_date": datetime.now().isoformat(),
        "reason": reason,
        "stop_loss": stop_loss,
        "peak_price": entry_price,
    }
    portfolio["positions"].append(position)
    save_portfolio(portfolio)


def remove_position(
    portfolio: dict,
    ticker: str,
    sell_price: float | None = None,
    reason: str = "",
    shares: int | None = None,
):
    """매도 기록. shares=None이면 전량, 숫자면 해당 수량만 매도."""
    remaining = []
    for pos in portfolio["positions"]:
        if pos["ticker"] != ticker:
            remaining.append(pos)
            continue

        sell_shares = shares if shares is not None else pos["shares"]
        if sell_shares > pos["shares"]:
            raise ValueError(
                f"매도 수량({sell_shares})이 보유 수량({pos['shares']})을 초과합니다"
            )

        if sell_price:
            record = {
                **pos,
                "sell_shares": sell_shares,
                "sell_price": sell_price,
                "sell_date": datetime.now().isoformat(),
                "sell_reason": reason,
                "final_pnl_pct": (sell_price - pos["entry_price"])
                / pos["entry_price"]
                * 100,
            }
            portfolio["history"].append(record)

        # 분할 매도: 잔여 수량이 있으면 포지션 유지
        leftover = pos["shares"] - sell_shares
        if leftover > 0:
            pos["shares"] = leftover
            if pos.get("current_price"):
                pos["market_value"] = pos["current_price"] * leftover
                pos["pnl_amount"] = (
                    pos["current_price"] - pos["entry_price"]
                ) * leftover
            remaining.append(pos)

    portfolio["positions"] = remaining
    save_portfolio(portfolio)


def update_positions(
    portfolio: dict, current_prices: dict[str, float], trailing_stop_pct: float = 10
) -> list[dict]:
    """현재가로 포지션 업데이트. 추적 손절매 체크."""
    alerts = []
    for pos in portfolio["positions"]:
        ticker = pos["ticker"]
        if ticker not in current_prices:
            continue

        current = current_prices[ticker]
        pos["current_price"] = current
        pos["pnl_pct"] = (current - pos["entry_price"]) / pos["entry_price"] * 100
        pos["pnl_amount"] = (current - pos["entry_price"]) * pos["shares"]
        pos["market_value"] = current * pos["shares"]

        # 고점 갱신
        if current > pos.get("peak_price", 0):
            pos["peak_price"] = current

        # 추적 손절매 가격 갱신 (고점 대비 trailing_stop_pct%)
        trailing_stop = pos["peak_price"] * (1 - trailing_stop_pct / 100)
        pos["trailing_stop"] = trailing_stop

        if current <= pos["stop_loss"]:
            alerts.append(
                {
                    "type": "STOP_LOSS",
                    "ticker": ticker,
                    "name": pos["name"],
                    "price": current,
                    "stop_loss": pos["stop_loss"],
                    "message": f"⚠️ 손절매 도달! {pos['name']}({ticker}) 현재가 {current:,.0f}원 ≤ 손절가 {pos['stop_loss']:,.0f}원 → 즉시 매도 검토",
                }
            )
        elif current <= trailing_stop:
            alerts.append(
                {
                    "type": "TRAILING_STOP",
                    "ticker": ticker,
                    "name": pos["name"],
                    "price": current,
                    "trailing_stop": trailing_stop,
                    "peak": pos["peak_price"],
                    "message": f"⚠️ 추적 손절매 도달! {pos['name']}({ticker}) 고점 {pos['peak_price']:,.0f}원 → 현재 {current:,.0f}원 ({pos['pnl_pct']:+.1f}%) → 매도 검토",
                }
            )

    save_portfolio(portfolio)
    return alerts


def get_portfolio_summary(portfolio: dict) -> dict:
    """포트폴리오 요약 통계"""
    portfolio, _ = _normalize_portfolio(portfolio)
    positions = portfolio.get("positions", [])
    cash_krw = get_cash_balance(portfolio, "KRW")
    cash_usd = get_cash_balance(portfolio, "USD")

    total_invested = sum(p["entry_price"] * p["shares"] for p in positions)
    total_market_value = sum(
        p.get("market_value", p["entry_price"] * p["shares"]) for p in positions
    )
    total_pnl = total_market_value - total_invested
    total_pnl_pct = (total_pnl / total_invested * 100) if total_invested > 0 else 0
    total_assets = total_market_value + cash_krw
    cash_pct = (cash_krw / total_assets * 100) if total_assets > 0 else 100

    return {
        "num_positions": len(positions),
        "cash": cash_krw,
        "cash_krw": cash_krw,
        "cash_usd": cash_usd,
        "total_invested": total_invested,
        "total_market_value": total_market_value,
        "total_pnl": total_pnl,
        "total_pnl_pct": total_pnl_pct,
        "total_assets": total_assets,
        "cash_pct": cash_pct,
    }
