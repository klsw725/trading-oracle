"""시그널 백테스트 엔진 — Phase 18 M1

LLM 호출 없이 시그널 레이어(6-앙상블 + 환율)만으로 매매 시뮬레이션.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from src.data.market import fetch_ohlcv
from src.signals.technical import compute_signals


@dataclass
class BacktestConfig:
    """백테스트 설정."""
    initial_capital: float = 10_000_000
    max_positions: int = 3
    position_size_pct: float = 30.0   # 종목당 자산 대비 비율 %
    stop_loss_pct: float = 10.0       # 고점 대비 손절매 %
    commission_pct: float = 0.015     # 편도 수수료 % (증권사 0.015%)
    slippage_pct: float = 0.1         # 슬리피지 %
    min_votes: int = 4                # 시그널 최소 투표 수
    use_forex: bool = True            # 환율 팩터 사용 여부
    cash_floor_pct: float = 20.0      # 최소 현금 비중 %
    use_correlation: bool = True      # 상관 리스크 체크 여부
    max_pair_correlation: float = 0.7 # 최대 허용 상관계수


@dataclass
class Position:
    """보유 포지션."""
    ticker: str
    name: str
    entry_price: float
    shares: int
    entry_date: str
    high_since_entry: float = 0.0
    stop_loss_pct: float = 10.0

    @property
    def stop_price(self) -> float:
        return self.high_since_entry * (1 - self.stop_loss_pct / 100)


@dataclass
class Trade:
    """완료된 거래."""
    ticker: str
    name: str
    entry_date: str
    exit_date: str
    entry_price: float
    exit_price: float
    shares: int
    pnl: float
    pnl_pct: float
    hold_days: int
    exit_reason: str


def preload_data(
    tickers: list[str],
    period_days: int,
) -> dict[str, pd.DataFrame]:
    """OHLCV 데이터 사전 로드. 최적화 시 중복 수집 방지."""
    lookback = period_days + 80
    ohlcv_data = {}
    for ticker in tickers:
        df = fetch_ohlcv(ticker, days_back=lookback)
        if not df.empty and len(df) >= 60:
            ohlcv_data[ticker] = df
    return ohlcv_data


def run_backtest(
    tickers: list[str],
    ticker_names: dict[str, str],
    period_days: int,
    config: BacktestConfig,
    signal_config: dict,
    forex_config: dict | None = None,
    on_progress: callable | None = None,
    preloaded_data: dict[str, pd.DataFrame] | None = None,
) -> dict:
    """시그널 기반 백테스트 실행.

    Args:
        tickers: 백테스트 대상 종목 코드 리스트
        ticker_names: {종목코드: 종목명} 매핑
        period_days: 백테스트 기간 (거래일)
        config: 백테스트 설정
        signal_config: config.yaml의 signals 섹션
        forex_config: config.yaml의 forex 섹션 (None이면 환율 미사용)
        on_progress: 진행률 콜백 (current, total)

    Returns:
        {
            "config": {...},
            "equity_curve": [float, ...],
            "dates": [str, ...],
            "trades": [Trade, ...],
            "final_positions": [Position, ...],
        }
    """
    # 데이터: 사전 로드 또는 새로 수집
    if preloaded_data:
        ohlcv_data = preloaded_data
    else:
        ohlcv_data = preload_data(tickers, period_days)

    if not ohlcv_data:
        return {"error": "백테스트용 데이터 부족"}

    # 공통 날짜 범위 (모든 종목이 데이터를 가진 날짜)
    common_dates = None
    for df in ohlcv_data.values():
        dates = set(df.index)
        common_dates = dates if common_dates is None else common_dates & dates
    if not common_dates:
        return {"error": "공통 거래일 없음"}

    sorted_dates = sorted(common_dates)
    # 백테스트 기간만 사용 (앞부분은 시그널 계산용 lookback)
    if len(sorted_dates) > period_days:
        bt_dates = sorted_dates[-period_days:]
    else:
        bt_dates = sorted_dates

    # 환율 데이터 로드
    macro_df = None
    fx_regime_cache: dict[str, dict] = {}
    if config.use_forex and forex_config:
        try:
            from src.data.macro import fetch_macro_series
            macro_df = fetch_macro_series()
        except Exception:
            macro_df = None

    # 상태 초기화
    cash = config.initial_capital
    positions: dict[str, Position] = {}
    trades: list[Trade] = []
    equity_curve: list[float] = []
    date_labels: list[str] = []

    total_days = len(bt_dates)

    for day_idx, date in enumerate(bt_dates):
        date_str = date.strftime("%Y-%m-%d") if hasattr(date, "strftime") else str(date)

        # 포트폴리오 가치 계산
        portfolio_value = cash
        for pos in positions.values():
            ticker_df = ohlcv_data[pos.ticker]
            if date in ticker_df.index:
                current_price = float(ticker_df.loc[date, "close"])
                portfolio_value += current_price * pos.shares
                # 고점 갱신
                pos.high_since_entry = max(pos.high_since_entry, current_price)

        equity_curve.append(portfolio_value)
        date_labels.append(date_str)

        # 각 종목 시그널 계산 + 매매 판정
        for ticker in tickers:
            if ticker not in ohlcv_data:
                continue

            ticker_df = ohlcv_data[ticker]
            # 이 날짜까지의 데이터로 시그널 계산
            mask = ticker_df.index <= date
            df_up_to = ticker_df[mask]
            if len(df_up_to) < 60:
                continue

            signals = compute_signals(df_up_to, {"signals": signal_config})
            if "error" in signals:
                continue

            current_price = float(df_up_to["close"].iloc[-1])
            name = ticker_names.get(ticker, ticker)

            # 보유 중인 종목: 매도 판정
            if ticker in positions:
                pos = positions[ticker]
                sell_reason = None

                # 손절매 체크
                if current_price <= pos.stop_price:
                    sell_reason = "stop_loss"
                # 시그널 매도
                elif signals["bear_votes"] >= config.min_votes:
                    sell_reason = "signal_sell"

                if sell_reason:
                    # 매도 실행
                    sell_price = current_price * (1 - config.slippage_pct / 100)
                    commission = sell_price * pos.shares * config.commission_pct / 100
                    proceeds = sell_price * pos.shares - commission
                    cash += proceeds

                    pnl = proceeds - pos.entry_price * pos.shares
                    pnl_pct = (sell_price - pos.entry_price) / pos.entry_price * 100

                    entry_dt = datetime.strptime(pos.entry_date, "%Y-%m-%d")
                    exit_dt = datetime.strptime(date_str, "%Y-%m-%d")
                    hold_days = (exit_dt - entry_dt).days

                    trades.append(Trade(
                        ticker=ticker, name=name,
                        entry_date=pos.entry_date, exit_date=date_str,
                        entry_price=pos.entry_price, exit_price=round(sell_price, 2),
                        shares=pos.shares, pnl=round(pnl),
                        pnl_pct=round(pnl_pct, 2), hold_days=hold_days,
                        exit_reason=sell_reason,
                    ))
                    del positions[ticker]

            # 미보유 종목: 매수 판정
            elif ticker not in positions:
                if signals["bull_votes"] >= config.min_votes:
                    if len(positions) >= config.max_positions:
                        continue

                    # 상관 리스크 체크 (Phase 19)
                    if config.use_correlation and positions:
                        try:
                            from src.portfolio.correlation import compute_correlation_from_data
                            check_tickers = [ticker] + list(positions.keys())
                            corr_mat = compute_correlation_from_data(
                                ohlcv_data, check_tickers, up_to_date=date, window=60,
                            )
                            if corr_mat is not None and ticker in corr_mat.index:
                                skip = False
                                for pt in positions:
                                    if pt in corr_mat.columns:
                                        c = abs(corr_mat.loc[ticker, pt])
                                        if c > config.max_pair_correlation:
                                            skip = True
                                            break
                                if skip:
                                    continue
                        except Exception:
                            pass

                    # 현금 비중 체크
                    available = cash - portfolio_value * config.cash_floor_pct / 100
                    if available <= 0:
                        continue

                    # 포지션 크기
                    target_amount = min(
                        portfolio_value * config.position_size_pct / 100,
                        available,
                    )

                    # 환율 조정
                    fx_mult = 1.0
                    if config.use_forex and macro_df is not None and forex_config:
                        fx_mult = _get_fx_multiplier(
                            ticker, name, df_up_to, macro_df,
                            date, forex_config,
                        )
                    target_amount *= fx_mult

                    buy_price = current_price * (1 + config.slippage_pct / 100)
                    shares = int(target_amount / buy_price)
                    if shares <= 0:
                        continue

                    commission = buy_price * shares * config.commission_pct / 100
                    cost = buy_price * shares + commission

                    if cost > cash:
                        shares = int((cash - commission) / buy_price)
                        if shares <= 0:
                            continue
                        cost = buy_price * shares + buy_price * shares * config.commission_pct / 100

                    cash -= cost
                    positions[ticker] = Position(
                        ticker=ticker, name=name,
                        entry_price=round(buy_price, 2),
                        shares=shares, entry_date=date_str,
                        high_since_entry=current_price,
                        stop_loss_pct=config.stop_loss_pct,
                    )

        if on_progress:
            on_progress(day_idx + 1, total_days)

    # 최종 포지션 정리 (미청산)
    final_positions = []
    for pos in positions.values():
        ticker_df = ohlcv_data.get(pos.ticker)
        if ticker_df is not None and len(ticker_df) > 0:
            last_price = float(ticker_df["close"].iloc[-1])
            pnl_pct = (last_price - pos.entry_price) / pos.entry_price * 100
            final_positions.append({
                "ticker": pos.ticker, "name": pos.name,
                "entry_price": pos.entry_price, "current_price": last_price,
                "shares": pos.shares, "pnl_pct": round(pnl_pct, 2),
            })

    return {
        "config": {
            "initial_capital": config.initial_capital,
            "max_positions": config.max_positions,
            "position_size_pct": config.position_size_pct,
            "stop_loss_pct": config.stop_loss_pct,
            "use_forex": config.use_forex,
            "min_votes": config.min_votes,
            "period_days": len(bt_dates),
            "tickers": tickers,
        },
        "equity_curve": equity_curve,
        "dates": date_labels,
        "trades": [_trade_to_dict(t) for t in trades],
        "final_positions": final_positions,
    }


def run_optimization(
    tickers: list[str],
    ticker_names: dict[str, str],
    period_days: int,
    signal_config: dict,
    forex_config: dict | None = None,
    base_config: BacktestConfig | None = None,
    param_grid: dict | None = None,
    on_progress: callable | None = None,
) -> list[dict]:
    """파라미터 그리드 서치. 데이터 1회 로드 후 N회 백테스트.

    Args:
        param_grid: {"min_votes": [3,4,5], "stop_loss_pct": [7,10,15], ...}

    Returns:
        결과 리스트 (샤프 비율 내림차순 정렬)
    """
    from src.backtest.metrics import compute_metrics
    from itertools import product

    if base_config is None:
        base_config = BacktestConfig()

    if param_grid is None:
        param_grid = {
            "min_votes": [3, 4, 5],
            "stop_loss_pct": [7, 10, 13, 15],
            "position_size_pct": [20, 25, 30],
        }

    # 데이터 1회 로드
    data = preload_data(tickers, period_days)
    if not data:
        return [{"error": "데이터 부족"}]

    # 매크로 데이터 1회 로드
    macro_df = None
    if base_config.use_forex and forex_config:
        try:
            from src.data.macro import fetch_macro_series
            macro_df = fetch_macro_series()
        except Exception:
            pass

    # 파라미터 조합 생성
    keys = list(param_grid.keys())
    values = list(param_grid.values())
    combos = list(product(*values))
    total = len(combos)

    results = []
    for i, combo in enumerate(combos):
        params = dict(zip(keys, combo))

        cfg = BacktestConfig(
            initial_capital=base_config.initial_capital,
            max_positions=base_config.max_positions,
            commission_pct=base_config.commission_pct,
            slippage_pct=base_config.slippage_pct,
            use_forex=base_config.use_forex,
            cash_floor_pct=base_config.cash_floor_pct,
            min_votes=params.get("min_votes", base_config.min_votes),
            stop_loss_pct=params.get("stop_loss_pct", base_config.stop_loss_pct),
            position_size_pct=params.get("position_size_pct", base_config.position_size_pct),
        )

        result = run_backtest(
            tickers=tickers,
            ticker_names=ticker_names,
            period_days=period_days,
            config=cfg,
            signal_config=signal_config,
            forex_config=forex_config,
            preloaded_data=data,
        )

        if "error" not in result:
            metrics = compute_metrics(result["equity_curve"], result["trades"])
            results.append({
                "params": params,
                "metrics": metrics,
            })

        if on_progress:
            on_progress(i + 1, total)

    # 샤프 비율 내림차순
    results.sort(key=lambda r: r["metrics"].get("sharpe_ratio", -999), reverse=True)
    return results


def _get_fx_multiplier(
    ticker: str,
    name: str,
    ohlcv: pd.DataFrame,
    macro_df: pd.DataFrame,
    date,
    forex_config: dict,
) -> float:
    """해당 날짜의 환율 사이징 배수."""
    try:
        from src.signals.forex import classify_fx_sensitivity, detect_fx_regime

        fx_class = classify_fx_sensitivity(name)
        if fx_class == "neutral":
            return 1.0

        # 해당 날짜까지의 매크로 데이터
        if "USD_KRW" not in macro_df.columns:
            return 1.0

        mask = macro_df.index <= date
        usd_series = macro_df.loc[mask, "USD_KRW"].dropna()
        if len(usd_series) < 20:
            return 1.0

        fx_regime = detect_fx_regime(usd_series, {"forex": forex_config})
        regime = fx_regime.get("fx_regime", "unknown")
        is_extreme = fx_regime.get("is_extreme", False)

        adj = forex_config.get("sizing_adjustment", {})
        if is_extreme:
            return adj.get("extreme_cap", 0.70)
        if regime in ("krw_weak", "krw_extreme_weak"):
            if fx_class == "export":
                return adj.get("weak_export", 1.15)
            elif fx_class == "import":
                return adj.get("weak_import", 0.85)
        elif regime in ("krw_strong", "krw_extreme_strong"):
            if fx_class == "export":
                return adj.get("strong_export", 0.90)
            elif fx_class == "import":
                return adj.get("strong_import", 1.10)
    except Exception:
        pass
    return 1.0


def _trade_to_dict(t: Trade) -> dict:
    return {
        "ticker": t.ticker, "name": t.name,
        "entry_date": t.entry_date, "exit_date": t.exit_date,
        "entry_price": t.entry_price, "exit_price": t.exit_price,
        "shares": t.shares, "pnl": t.pnl, "pnl_pct": t.pnl_pct,
        "hold_days": t.hold_days, "exit_reason": t.exit_reason,
    }
