"""StandardPortfolioResult —— 统一实验结果模式与约束校验。

规则（对应任务书第八节）：
- 结果必须来自真实算法输出（本模块只做校验，不生成数据）；
- 区分原始收益 daily_returns 与扣费后收益 net_daily_returns，cost_included
  标明算法原始输出是否已含交易费用，严禁重复计费；
- 股票权重必须关联真实股票代码（非 Asset 1 之类占位符；导入旧 ASACPL
  actions 导出时允许通过 asset_label_mode 显式标注 "position_index"）；
- 非负性、预算约束（每期 sum(stock)+cash ≈ 1）、现金比例 [0,1]；
- 指标必须附带年化假设（252 交易日 / 无风险利率）。
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

BudgetTolerance = 5e-3   # HMMP 权重按 4 位小数导出，容差 0.5%
NegTolerance = -1e-6

AssetLabelMode = Literal["ticker", "position_index"]

BACKTEST_MODES = ("paper_original", "unified_rebalance")


class MetricAssumptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trading_days_per_year: int = 252
    risk_free_rate: float = 0.0
    annualization: Literal["compound"] = "compound"
    return_type: Literal["simple", "log"] = "simple"


class ArtifactInfo(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str
    path: str
    kind: str = "file"          # file / dir / checkpoint / csv
    description: Optional[str] = None


class SelectionSnapshot(BaseModel):
    """股票筛选结果（可选能力）。"""

    model_config = ConfigDict(extra="forbid")

    date: str
    ranked: list[dict] = Field(default_factory=list)   # [{code, score, rank}]
    top_k: list[str] = Field(default_factory=list)     # 入选股票代码


class StandardPortfolioResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    experiment_id: str = Field(min_length=1)
    algorithm_id: str = Field(min_length=1)
    algorithm_version: str = Field(min_length=1)
    dataset_id: str = Field(min_length=1)
    dataset_version: str = "1"

    configuration: dict[str, Any] = Field(default_factory=dict)

    # 回测协议元信息（前端必须展示）
    backtest_mode: Literal["paper_original", "unified_rebalance"]
    trading_protocol: dict[str, Any] = Field(default_factory=dict)

    dates: list[str] = Field(min_length=1)
    daily_returns: list[float]
    net_daily_returns: Optional[list[float]] = None
    cost_included: bool = True
    portfolio_values: list[float]

    stock_weights: list[dict[str, float]]
    cash_weights: list[float]
    industry_weights: Optional[list[dict[str, float]]] = None
    turnover: Optional[list[float]] = None

    metrics: dict[str, Any] = Field(default_factory=dict)
    metric_assumptions: MetricAssumptions = Field(default_factory=MetricAssumptions)

    artifacts: list[ArtifactInfo] = Field(default_factory=list)
    stock_selection: Optional[list[SelectionSnapshot]] = None

    execution_status: Literal["SUCCEEDED"] = "SUCCEEDED"
    notes: list[str] = Field(default_factory=list)
    asset_label_mode: AssetLabelMode = "ticker"
    # 返回-only 导入（未提供任何权重文件）时为 False：跳过权重约束校验，
    # 前端应隐藏持仓类视图
    weights_available: bool = True

    # ------------------------------------------------------------------
    @model_validator(mode="after")
    def _check_series(self) -> "StandardPortfolioResult":
        n = len(self.dates)
        for name in ("daily_returns", "portfolio_values", "stock_weights", "cash_weights"):
            if len(getattr(self, name)) != n:
                raise ValueError(f"{name} length {len(getattr(self, name))} != dates length {n}")
        if self.net_daily_returns is not None and len(self.net_daily_returns) != n:
            raise ValueError("net_daily_returns length mismatch")
        if self.industry_weights is not None and len(self.industry_weights) != n:
            raise ValueError("industry_weights length mismatch")
        if self.turnover is not None and len(self.turnover) != n:
            raise ValueError("turnover length mismatch")

        # 日期升序且唯一
        if list(self.dates) != sorted(set(self.dates)):
            raise ValueError("dates must be strictly increasing and unique")

        # 收益率下界（简单收益 > -100%）
        for i, r in enumerate(self.daily_returns):
            if r <= -1.0:
                raise ValueError(f"daily_returns[{i}] = {r} <= -100%")

        # 净值一致性：必须与「毛收益累乘」或「扣费收益累乘」之一严格对应
        import math

        def _cum(rs):
            out, v = [], 1.0
            for r in rs:
                v *= 1.0 + r
                out.append(v)
            return out

        candidates = [_cum(self.daily_returns)]
        if self.net_daily_returns is not None:
            candidates.append(_cum(self.net_daily_returns))
        values = self.portfolio_values
        ok = any(
            len(c) == len(values)
            and all(math.isclose(a, b, rel_tol=1e-6, abs_tol=1e-9)
                    for a, b in zip(c, values))
            for c in candidates
        )
        if not ok:
            raise ValueError(
                "portfolio_values must equal the cumulative product of either "
                "daily_returns or net_daily_returns (starting at 1.0)"
            )

        self._check_weights()
        return self

    def _check_weights(self) -> None:
        if not self.weights_available:
            for i, sw in enumerate(self.stock_weights):
                if sw:
                    raise ValueError(f"weights_available=False but weights[{i}] non-empty")
            return
        for i, (sw, cw) in enumerate(zip(self.stock_weights, self.cash_weights)):
            if not sw and cw is None:
                raise ValueError(f"weights[{i}]: both stock and cash empty")
            for code, w in sw.items():
                if not isinstance(code, str) or not code.strip():
                    raise ValueError(f"weights[{i}]: empty asset label")
                if w < NegTolerance:
                    raise ValueError(f"weights[{i}]: negative weight {w} for {code}")
            if cw < NegTolerance:
                raise ValueError(f"cash_weights[{i}] = {cw} negative")
            total = sum(sw.values()) + max(cw, 0.0)
            if abs(total - 1.0) > BudgetTolerance:
                raise ValueError(
                    f"weights[{i}]: budget constraint violated, sum(stocks)+cash = {total:.6f}"
                )
        if self.industry_weights is not None:
            for i, iw in enumerate(self.industry_weights):
                total = sum(iw.values()) + max(self.cash_weights[i], 0.0)
                if abs(total - 1.0) > BudgetTolerance:
                    raise ValueError(
                        f"industry_weights[{i}]: sum(industry)+cash = {total:.6f}"
                    )


def validate_result_dict(data: dict) -> StandardPortfolioResult:
    """插件 runner 输出 → 严格校验的 StandardPortfolioResult；失败抛出 pydantic 错误。"""
    return StandardPortfolioResult(**data)
