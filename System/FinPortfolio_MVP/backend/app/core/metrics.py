"""统一绩效指标计算。

所有指标的计算口径在此显式声明：
- 年化假设默认 252 个交易日 / 年（A 股与美股通用研究口径）；
- 无风险利率默认 0.0（与两篇论文的原实验一致）；可通过参数覆盖；
- 年化收益采用几何复利： (末期净值) ** (252 / 天数) - 1；
- 年化波动率 = 日收益样本标准差(ddof=1) * sqrt(252)；
- Sharpe = (mean(r) - rf/252) / std(r) * sqrt(252)；
- Sortino 以下行波动（仅负收益）计；
- Max Drawdown 基于累计净值；
- Calmar = 年化收益 / |MDD|；
- 换手率为单边口径：mean(0.5 * sum|w_t - w_{t-1}|)。
"""
from __future__ import annotations

from typing import Optional

import numpy as np

TRADING_DAYS_PER_YEAR = 252


def compute_metrics(
    daily_returns,
    turnover: Optional[list] = None,
    cash_weights: Optional[list] = None,
    trading_days: int = TRADING_DAYS_PER_YEAR,
    risk_free_rate: float = 0.0,
) -> dict:
    r = np.asarray(daily_returns, dtype=float)
    n = r.size
    out: dict = {
        "days": int(n),
        "trading_days_per_year": trading_days,
        "risk_free_rate": risk_free_rate,
    }
    if n == 0:
        return out

    wealth = np.cumprod(1.0 + r)
    running_max = np.maximum.accumulate(np.concatenate(([1.0], wealth)))[1:]
    drawdown = wealth / running_max - 1.0
    cumulative = float(wealth[-1] - 1.0)
    annual_return = float(wealth[-1] ** (trading_days / n) - 1.0)

    if n > 1:
        vol_daily = float(np.std(r, ddof=1))
    else:
        vol_daily = 0.0
    annual_vol = vol_daily * float(np.sqrt(trading_days))

    daily_rf = risk_free_rate / trading_days
    sharpe = None
    if vol_daily > 1e-12:      # 浮点噪声（恒定收益序列 std≈1e-17）视为零波动
        sharpe = float((np.mean(r) - daily_rf) / vol_daily * np.sqrt(trading_days))

    neg = np.minimum(r - daily_rf, 0.0)
    downside = float(np.sqrt(np.mean(neg ** 2))) if n > 0 else 0.0
    sortino = None
    if downside > 1e-12:
        sortino = float((np.mean(r) - daily_rf) / downside * np.sqrt(trading_days))

    mdd = float(drawdown.min()) if n else 0.0
    calmar = None
    if mdd < 0:
        calmar = float(annual_return / abs(mdd))

    out.update({
        "cumulative_return": cumulative,
        "annualized_return": annual_return,
        "annualized_volatility": annual_vol,
        "sharpe_ratio": sharpe,
        "sortino_ratio": sortino,
        "max_drawdown": mdd,
        "calmar_ratio": calmar,
    })

    if turnover is not None and len(turnover):
        out["avg_turnover"] = float(np.mean(np.asarray(turnover, dtype=float)))
        out["total_turnover"] = float(np.sum(np.asarray(turnover, dtype=float)))
    if cash_weights is not None and len(cash_weights):
        out["avg_cash_ratio"] = float(np.mean(np.asarray(cash_weights, dtype=float)))
    return out


def turnover_series(stock_weights: list[dict], cash_weights: list) -> list:
    """单边换手率序列：0.5 * sum_t |w_t - w_{t-1}|（首日 = 0.5*|w_0 - 初始等权|? ）。

    首日相对初始现金状态（100% 现金）建仓：turnover_0 = 0.5 * sum(|w_0|) = 0.5 * 投资比例。
    """
    out: list[float] = []
    prev: dict[str, float] = {}
    prev_cash = 1.0
    for i, sw in enumerate(stock_weights):
        cw = float(cash_weights[i]) if cash_weights is not None and i < len(cash_weights) else 0.0
        codes = set(prev) | set(sw)
        gross = sum(abs(sw.get(c, 0.0) - prev.get(c, 0.0)) for c in codes)
        gross += abs(cw - prev_cash)
        out.append(float(0.5 * gross))
        prev, prev_cash = sw, cw
    return out


def wealth_series(daily_returns) -> list:
    r = np.asarray(daily_returns, dtype=float)
    return np.cumprod(1.0 + r).tolist()


def drawdown_series(daily_returns) -> list:
    r = np.asarray(daily_returns, dtype=float)
    wealth = np.cumprod(1.0 + r)
    running_max = np.maximum.accumulate(np.concatenate(([1.0], wealth)))[1:]
    return (wealth / running_max - 1.0).tolist()
