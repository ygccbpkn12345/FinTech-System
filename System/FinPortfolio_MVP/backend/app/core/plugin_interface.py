"""统一插件接口（抽象基类）。

重要约束：本文件必须保持 **纯标准库**，不能 import fastapi/pandas/numpy，
因为它会被 plugin_runner.py 在插件自己的 Python 环境（可能是独立的
TensorFlow / PyTorch 虚拟环境）中以 importlib 方式加载。

生命周期：
  1. 后端注册表只解析 manifest.yaml，绝不 import 本文件以外的插件代码；
  2. 执行能力（train / predict / backtest ...）时，后端通过 plugin_runner.py
     在独立子进程中加载 adapter.py 并调用对应方法；
  3. adapter.py 可以（但不强制）继承 BasePortfolioPlugin 获得默认行为。

适配器约定（鸭子类型即可，不要求继承）：
  class Adapter:
      def __init__(self, context: dict) -> None: ...
      def backtest(self, params: dict, context: dict) -> dict: ...  # 能力同名方法
  返回 dict 必须符合 StandardPortfolioResult 结构（由后端在任务完成后用
  Pydantic 严格校验）。normalize_result() 负责把算法原始输出转换成该结构。
"""
from __future__ import annotations

from typing import Any, Optional


class PluginCapabilityError(Exception):
    """插件不支持所请求的能力。"""


class BasePortfolioPlugin:
    """算法插件抽象基类。

    capabilities 声明插件支持的能力；未实现的能力方法保持基类默认实现，
    调用时抛出 PluginCapabilityError，任务会被标记为 FAILED 并保留准确错误信息。
    """

    #: 支持的能力子集：train / predict / backtest / stock_selection /
    #: industry_allocation / news_analysis / portfolio_weights
    capabilities: tuple = ()

    def __init__(self, context: Optional[dict] = None) -> None:
        #: context 由 plugin_runner 注入，包含 experiment_id / 数据集路径 /
        #: 工作目录 / manifest 摘要等只读信息
        self.context: dict = dict(context or {})

    # ------------------------------------------------------------------
    # 元信息（可选覆盖；默认从 context.manifest 取）
    # ------------------------------------------------------------------
    def get_info(self) -> dict:
        return dict(self.context.get("manifest", {}))

    def get_config_schema(self) -> list[dict]:
        manifest = self.context.get("manifest", {})
        return list(manifest.get("parameters", []))

    # ------------------------------------------------------------------
    # 数据集校验（可选覆盖）：返回问题列表，空列表表示通过
    # ------------------------------------------------------------------
    def validate_dataset(self, dataset: dict) -> list[str]:
        problems: list[str] = []
        manifest = self.context.get("manifest", {})
        reqs = manifest.get("dataset_requirements", [])
        have = set(dataset.get("available_modalities", []))
        for req in reqs:
            missing = set(req.get("modalities", [])) - have
            if req is reqs[0] and missing:
                problems.append(
                    f"dataset missing modalities: {sorted(missing)}"
                )
        return problems

    # ------------------------------------------------------------------
    # 能力方法：按声明选择性实现
    # ------------------------------------------------------------------
    def train(self, params: dict, context: dict) -> dict:
        raise PluginCapabilityError(
            f"plugin {type(self).__name__} declares no 'train' implementation"
        )

    def predict(self, params: dict, context: dict) -> dict:
        raise PluginCapabilityError(
            f"plugin {type(self).__name__} declares no 'predict' implementation"
        )

    def backtest(self, params: dict, context: dict) -> dict:
        raise PluginCapabilityError(
            f"plugin {type(self).__name__} declares no 'backtest' implementation"
        )

    def stock_selection(self, params: dict, context: dict) -> dict:
        raise PluginCapabilityError(
            f"plugin {type(self).__name__} declares no 'stock_selection' implementation"
        )

    # ------------------------------------------------------------------
    # 结果标准化：把算法原始输出转换为 StandardPortfolioResult dict
    # ------------------------------------------------------------------
    def normalize_result(self, raw: Any, context: dict) -> dict:
        raise PluginCapabilityError(
            f"plugin {type(self).__name__} does not implement normalize_result; "
            "capability methods must already return StandardPortfolioResult dicts"
        )

    # ------------------------------------------------------------------
    def supports(self, capability: str) -> bool:
        if capability in self.capabilities:
            return True
        method = getattr(self, capability, None)
        if callable(method) and capability in (
            "train", "predict", "backtest", "stock_selection"
        ):
            # 方法被真实覆盖（不属于基类默认实现）
            owner = getattr(method, "__objclass__", None) or type(self)
            cls_method = getattr(BasePortfolioPlugin, capability, None)
            if method.__func__ is not getattr(cls_method, "__func__", None):
                return True
        return False
