"""指标计算口径测试。"""
import math

from app.core.metrics import (
    compute_metrics,
    drawdown_series,
    turnover_series,
    wealth_series,
)


def test_constant_positive_returns():
    r = [0.01] * 10
    m = compute_metrics(r)
    assert m["days"] == 10
    assert math.isclose(m["cumulative_return"], 1.01 ** 10 - 1, rel_tol=1e-9)
    # 几何年化：10 个 1% 日 → 1.01^252 - 1
    assert math.isclose(m["annualized_return"], 1.01 ** 252 - 1, rel_tol=1e-9)
    assert math.isclose(m["annualized_volatility"], 0.0, abs_tol=1e-12)
    assert m["sharpe_ratio"] is None       # 零波动无法定义
    assert m["max_drawdown"] == 0.0


def test_known_drawdown():
    # 净值 1.0 → 1.25 → 1.0：最大回撤 -20%，累计收益 0 → calmar = 0
    r = [0.25, -0.2]
    m = compute_metrics(r)
    assert math.isclose(m["max_drawdown"], -0.2, rel_tol=1e-9)
    assert m["calmar_ratio"] == 0.0


def test_negative_returns_sharpe():
    r = [0.01, -0.02, 0.005, -0.01, 0.012, 0.004, -0.006, 0.009, 0.002, -0.003]
    m = compute_metrics(r)
    assert m["sharpe_ratio"] is not None
    assert m["sortino_ratio"] is not None
    # 下行波动不小于总波动 → sortino 数值绝对值 >= sharpe 数值绝对值（负收益情形）
    assert abs(m["sortino_ratio"]) >= abs(m["sharpe_ratio"]) - 1e-12


def test_risk_free_rate_affects_sharpe():
    r = [0.001] * 50 + [0.0] * 50
    m0 = compute_metrics(r, risk_free_rate=0.0)
    m5 = compute_metrics(r, risk_free_rate=0.05)
    assert m5["sharpe_ratio"] < m0["sharpe_ratio"]


def test_turnover_series_buy_and_hold():
    # 首日全仓建仓（现金→股票是同一笔交易的两条腿）：
    # 单边换手 = 0.5 * (|Δstock_A|+|Δstock_B|+|Δcash|) = 0.5*(0.5+0.5+1.0) = 1.0
    w = [{"A": 0.5, "B": 0.5}, {"A": 0.5, "B": 0.5}]
    t = turnover_series(w, [0.0, 0.0])
    assert math.isclose(t[0], 1.0, rel_tol=1e-9)
    assert math.isclose(t[1], 0.0, rel_tol=1e-9)


def test_turnover_rebalance():
    w = [{"A": 0.6, "B": 0.4}, {"A": 0.4, "B": 0.6}]
    t = turnover_series(w, [0.0, 0.0])
    assert math.isclose(t[1], 0.2, rel_tol=1e-9)   # 0.5 * (0.2+0.2)


def test_wealth_and_drawdown_align():
    r = [0.1, -0.2, 0.3]
    w = wealth_series(r)
    assert math.isclose(w[0], 1.1)
    dd = drawdown_series(r)
    assert min(dd) == dd[1]
    assert math.isclose(dd[1], (1.1 * 0.8) / 1.1 - 1, rel_tol=1e-9)
