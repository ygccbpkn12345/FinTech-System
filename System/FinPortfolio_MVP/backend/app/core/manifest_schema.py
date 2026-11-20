"""插件 manifest.yaml 的严格校验模型（Pydantic v2）。

注册表只解析 manifest，不在 FastAPI 进程内执行任何插件代码；
因此 manifest 是算法元数据的唯一可信来源，必须严格校验。
"""
from __future__ import annotations

import re
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,63}$")

# 系统认识的能力集合；不在集合内的能力声明视为 manifest 错误
KNOWN_CAPABILITIES = (
    "train",
    "predict",
    "backtest",
    "stock_selection",
    "industry_allocation",
    "news_analysis",
    "portfolio_weights",
)

# 系统认识的数据模态（用于算法-数据集兼容性检查）
KNOWN_MODALITIES = (
    "prices",              # 个股行情（date, tic, close ...）
    "covariance",          # 协方差矩阵（cov_list）
    "tech_indicators",     # 个股技术指标特征
    "stock_features",      # 行业成分股特征表
    "industry_prices",     # 行业价格特征
    "industry_news",       # 行业新闻特征
    "news",                # 原始新闻文本
)


class PaperInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1)
    authors: Optional[list[str]] = None
    venue: Optional[str] = None
    year: Optional[int] = None
    url: Optional[str] = None
    note: Optional[str] = None


class ParameterSpec(BaseModel):
    """一个可由前端动态渲染的训练/回测参数。"""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    label: Optional[str] = None
    type: Literal["int", "float", "str", "bool", "enum"]
    default: Any = None
    min: Optional[float] = None
    max: Optional[float] = None
    choices: Optional[list[str]] = None
    description: Optional[str] = None
    cli_flag: Optional[str] = None      # 子进程适配器使用的命令行旗标
    advanced: bool = False
    required: bool = False

    @field_validator("name")
    @classmethod
    def _valid_name(cls, v: str) -> str:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", v):
            raise ValueError(f"parameter name '{v}' must be a valid identifier")
        return v

    @model_validator(mode="after")
    def _check(self) -> "ParameterSpec":
        if self.type == "enum":
            if not self.choices:
                raise ValueError(f"parameter '{self.name}': enum type requires choices")
            if self.default is not None and str(self.default) not in self.choices:
                raise ValueError(f"parameter '{self.name}': default not in choices")
        if self.type in ("int", "float"):
            if self.default is None:
                raise ValueError(f"parameter '{self.name}': numeric type requires default")
            if not isinstance(self.default, (int, float)) or isinstance(self.default, bool):
                raise ValueError(f"parameter '{self.name}': default must be numeric")
            if self.min is not None and float(self.default) < self.min:
                raise ValueError(f"parameter '{self.name}': default < min")
            if self.max is not None and float(self.default) > self.max:
                raise ValueError(f"parameter '{self.name}': default > max")
        if self.type == "int" and not float(self.default).is_integer():
            raise ValueError(f"parameter '{self.name}': int type requires integer default")
        if self.type == "bool" and not isinstance(self.default, bool):
            raise ValueError(f"parameter '{self.name}': bool type requires bool default")
        if self.type == "str" and self.default is None:
            raise ValueError(f"parameter '{self.name}': str type requires default")
        return self


class DatasetRequirement(BaseModel):
    """算法对数据集的要求；与 DatasetMeta 做兼容性匹配。"""

    model_config = ConfigDict(extra="forbid")

    markets: list[str] = Field(default_factory=list)
    modalities: list[str] = Field(min_length=1)
    required_fields: list[str] = Field(default_factory=list)
    description: Optional[str] = None

    @field_validator("modalities")
    @classmethod
    def _known_modalities(cls, v: list[str]) -> list[str]:
        unknown = [m for m in v if m not in KNOWN_MODALITIES]
        if unknown:
            raise ValueError(f"unknown modalities {unknown}; known: {list(KNOWN_MODALITIES)}")
        return v


class ExecutionSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    adapter_file: str = "adapter.py"       # 相对插件目录
    # 原始论文代码位置：相对 FINPORTFOLIO_ORIGINAL_CODE_ROOT 的子目录名（如 ASACPL），
    # 也可以是绝对路径。算法主体代码不复制进插件目录，保持原样。
    original_code_subdir: Optional[str] = None
    default_timeout_seconds: int = Field(default=86400, ge=1)
    max_timeout_seconds: int = Field(default=604800, ge=1)

    @model_validator(mode="after")
    def _check(self) -> "ExecutionSpec":
        if self.default_timeout_seconds > self.max_timeout_seconds:
            raise ValueError("default_timeout_seconds > max_timeout_seconds")
        return self


class OutputSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    result_format: Literal["StandardPortfolioResult"] = "StandardPortfolioResult"
    artifacts: list[str] = Field(default_factory=list)
    notes: Optional[str] = None


class PluginManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"]
    id: str
    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    description: str = Field(min_length=1)
    paper: PaperInfo
    framework: str = Field(min_length=1)          # tensorflow / pytorch / numpy ...
    # 插件独立 Python 解释器（虚拟环境）。为空表示与后端共用解释器。
    python_executable: Optional[str] = None
    capabilities: list[str] = Field(min_length=1)
    dataset_requirements: list[DatasetRequirement] = Field(min_length=1)
    parameters: list[ParameterSpec] = Field(default_factory=list)
    outputs: OutputSpec
    execution: ExecutionSpec

    @field_validator("id")
    @classmethod
    def _valid_id(cls, v: str) -> str:
        if not ID_PATTERN.fullmatch(v):
            raise ValueError(f"plugin id '{v}' must match {ID_PATTERN.pattern}")
        return v

    @field_validator("capabilities")
    @classmethod
    def _known_caps(cls, v: list[str]) -> list[str]:
        unknown = [c for c in v if c not in KNOWN_CAPABILITIES]
        if unknown:
            raise ValueError(f"unknown capabilities {unknown}; known: {list(KNOWN_CAPABILITIES)}")
        if len(set(v)) != len(v):
            raise ValueError("duplicate capabilities")
        return v

    @model_validator(mode="after")
    def _check(self) -> "PluginManifest":
        names = [p.name for p in self.parameters]
        if len(set(names)) != len(names):
            raise ValueError("duplicate parameter names")
        return self

    def parameter_by_name(self, name: str) -> Optional[ParameterSpec]:
        for p in self.parameters:
            if p.name == name:
                return p
        return None

    def default_params(self) -> dict[str, Any]:
        return {p.name: p.default for p in self.parameters}


class ManifestError(Exception):
    """manifest 解析 / 校验失败。"""
