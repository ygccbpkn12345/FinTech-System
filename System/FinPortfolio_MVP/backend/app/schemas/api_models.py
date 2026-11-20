"""API 请求/响应模型。"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class DataSplitConfig(BaseModel):
    """实验级数据时间范围切片（可选）。

    不是算法超参数，不进 manifest：作为数据集使用方式的一部分随 payload
    传给插件适配器，由各算法按自身数据加载流程消费（ASACPL 切 CSV、
    HMMP 映射为 --train_start_date/--train_end_date）。全部字段可留空，
    留空 = 使用数据集全量（与旧行为完全一致）。
    """

    train_start: Optional[str] = None   # YYYY-MM-DD（含）
    train_end: Optional[str] = None     # YYYY-MM-DD（含）
    test_start: Optional[str] = None    # YYYY-MM-DD（含）
    test_end: Optional[str] = None      # YYYY-MM-DD（含）


class ExperimentCreate(BaseModel):
    algorithm_id: str = Field(min_length=1)
    dataset_id: str = Field(min_length=1)
    capability: str = Field(default="train", pattern=r"^[a-z_]+$")
    params: dict[str, Any] = Field(default_factory=dict)
    data_split: Optional[DataSplitConfig] = None
    name: Optional[str] = None
    timeout_seconds: Optional[int] = Field(default=None, gt=0, le=604800)


class DatasetRegister(BaseModel):
    name: str = Field(min_length=1)
    market: str = Field(min_length=1)
    files: dict[str, str] = Field(min_length=1)
    available_modalities: list[str] = Field(min_length=1)
    storage_mode: str = Field(default="reference", pattern=r"^(reference|copy)$")
    source_dir: Optional[str] = None
    frequency: str = "daily"
    version: str = "1"
    description: str = ""
    provenance: str = ""
    dataset_id: Optional[str] = None


class ImportCreate(BaseModel):
    """通过服务端本地路径导入论文结果（受信任管理员显式开启）。"""

    algorithm_id: str = Field(min_length=1)
    source_dir: str = Field(min_length=1)
    returns_file: str = Field(min_length=1)
    weights_file: Optional[str] = None
    industry_file: Optional[str] = None
    intra_file: Optional[str] = None
    dataset_id: str = Field(default="unknown")
    dataset_name: str = Field(default="unknown")
    name: str = Field(default="imported paper result")
