"""StandardPortfolioResult 约束校验测试（权重非负 / 预算 / 序列一致性）。"""
import pytest
from pydantic import ValidationError

from app.core.result_schema import StandardPortfolioResult


def _result(**over):
    base = dict(
        experiment_id="exp_x",
        algorithm_id="eq",
        algorithm_version="1",
        dataset_id="ds",
        backtest_mode="unified_rebalance",
        dates=["2024-01-02", "2024-01-03"],
        daily_returns=[0.01, -0.01],
        portfolio_values=[1.01, 0.9999],
        stock_weights=[{"A": 1.0}, {"A": 1.0}],
        cash_weights=[0.0, 0.0],
    )
    base.update(over)
    return StandardPortfolioResult(**base)


def test_valid_result_passes():
    r = _result()
    assert r.cost_included is True
    assert r.asset_label_mode == "ticker"


def test_negative_weight_rejected():
    with pytest.raises(ValidationError):
        _result(stock_weights=[{"A": 1.2, "B": -0.2}, {"A": 1.0}])


def test_budget_violation_rejected():
    with pytest.raises(ValidationError):
        _result(stock_weights=[{"A": 0.5, "B": 0.2}, {"A": 1.0}],
                cash_weights=[0.0, 0.0])


def test_budget_within_rounding_tolerance_accepted():
    # HMMP 4 位小数导出：0.9997 总权重应被 5e-3 容差接受
    r = _result(stock_weights=[{"A": 0.9997}, {"A": 1.0}])
    assert r is not None


def test_length_mismatch_rejected():
    with pytest.raises(ValidationError):
        _result(daily_returns=[0.01])


def test_unsorted_dates_rejected():
    with pytest.raises(ValidationError):
        _result(dates=["2024-01-03", "2024-01-02"])


def test_return_below_minus_100pct_rejected():
    with pytest.raises(ValidationError):
        _result(daily_returns=[-1.5, 0.01], portfolio_values=[-0.5, -0.505])


def test_negative_cash_rejected():
    with pytest.raises(ValidationError):
        _result(cash_weights=[-0.1, 0.0],
                stock_weights=[{"A": 1.1}, {"A": 1.0}])


def test_empty_asset_label_rejected():
    with pytest.raises(ValidationError):
        _result(stock_weights=[{"": 1.0}, {"A": 1.0}])


def test_industry_weights_budget_enforced():
    ok = _result(industry_weights=[{"I1": 0.5, "I2": 0.5}, {"I1": 1.0}])
    assert ok.industry_weights is not None
    with pytest.raises(ValidationError):
        _result(industry_weights=[{"I1": 0.2}, {"I1": 1.0}])


def test_import_position_label_mode_allowed():
    r = _result(asset_label_mode="position_index",
                stock_weights=[{"Asset_1": 1.0}, {"Asset_1": 1.0}])
    assert r.asset_label_mode == "position_index"
