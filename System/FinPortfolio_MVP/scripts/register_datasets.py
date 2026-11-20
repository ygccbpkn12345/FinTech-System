"""把本机已有的论文研究数据登记进 DatasetRegistry。

用法（在 backend 环境中）：
    python scripts/register_datasets.py                # 使用默认路径探测
    python scripts/register_datasets.py --list         # 查看已登记数据集
    python scripts/register_datasets.py --asacpl-data <dir> --hmmp-data <dir>

默认探测路径基于本仓库在本机的实际布局（System/FinPortfolio_MVP 的上级目录）：
- ASACPL: ../A-Experiment-1/AAA_Paper1_05/S&P500/test2023/datasets
- HMMP:   ../Paper2-1/Data
换机器部署时用参数显式指定路径即可，元信息登记不复制数据（reference 模式）。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.core.paths import DATASETS_DIR  # noqa: E402
from app.services.dataset_service import DatasetError, DatasetService  # noqa: E402

DEFAULT_ASACPL = PROJECT_ROOT.parents[1] / "A-Experiment-1" / "AAA_Paper1_05" / "S&P500" / "test2023" / "datasets"
DEFAULT_HMMP = PROJECT_ROOT.parents[1] / "Paper2-1" / "Data"


def prune_same_source(svc: DatasetService, dataset_id: str, source_dir: Path) -> list[str]:
    """删除与目标 dataset_id 同名（含 `_N` 后缀副本）且指向同一源目录的旧登记。

    register() 对已存在的 id 自动加后缀追加而非去重 —— 重复运行本脚本会
    产生 asacpl_sp500_test2023_2/_3/... 这类同源副本。此处先清理再登记，
    保证脚本幂等：无论跑多少次，索引里始终只有每个数据集一条记录。
    """
    import re as _re

    removed: list[str] = []
    for ds in svc.list_datasets():
        same_id = ds["dataset_id"] == dataset_id or _re.fullmatch(
            rf"{_re.escape(dataset_id)}_\d+", ds["dataset_id"]
        )
        same_src = Path(ds.get("storage_path", "")).resolve() == source_dir.resolve()
        if same_id and same_src:
            svc.delete(ds["dataset_id"])
            removed.append(ds["dataset_id"])
    return removed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asacpl-data", type=Path, default=DEFAULT_ASACPL)
    parser.add_argument("--hmmp-data", type=Path, default=DEFAULT_HMMP)
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()

    svc = DatasetService()

    if args.list:
        for ds in svc.list_datasets():
            print(f"{ds['dataset_id']:32s} {ds['market']:8s} "
                  f"{ds['date_range'].get('start')}~{ds['date_range'].get('end')} "
                  f"[{', '.join(ds['available_modalities'])}]")
        return 0

    ok = True

    if args.asacpl_data.is_dir():
        for gone in prune_same_source(svc, "asacpl_sp500_test2023", args.asacpl_data.resolve()):
            print(f"[clean] removed duplicate registration: {gone}")
        meta = svc.register(
            name="ASACPL S&P500 test2023 (paper preprocessed)",
            market="SP500",
            files={"train_prices": "02_train_CNN.csv", "test_prices": "02_test_CNN.csv"},
            available_modalities=["prices", "covariance", "tech_indicators"],
            storage_mode="reference",
            source_dir=str(args.asacpl_data),
            description="HLB-AS 筛选后 20 只股票、f1-f4 特征与 cov_list（00/01 notebook 产物）",
            provenance=str(args.asacpl_data),
            dataset_id="asacpl_sp500_test2023",
        )
        print(f"[ok] registered {meta['dataset_id']}: "
              f"{meta['date_range']['start']}~{meta['date_range']['end']}, "
              f"{len(meta['assets'])} assets")
    else:
        print(f"[skip] ASACPL data dir not found: {args.asacpl_data}")
        ok = False

    if args.hmmp_data.is_dir():
        for gone in prune_same_source(svc, "hmmp_csi500_features", args.hmmp_data.resolve()):
            print(f"[clean] removed duplicate registration: {gone}")
        meta = svc.register(
            name="HMMP CSI500 multimodal features (paper preprocessed)",
            market="CSI500",
            files={
                "industry_prices": "industry_price_features.csv",
                "industry_news": "industry_news_features.csv",
                "stock_features": "IndustryPrice/Industry0.csv",
            },
            available_modalities=["stock_features", "industry_prices", "industry_news"],
            storage_mode="reference",
            source_dir=str(args.hmmp_data),
            description="A_* 预处理产物：行业价格特征 + 行业新闻特征 + 行业成分股特征",
            provenance=str(args.hmmp_data),
            dataset_id="hmmp_csi500_features",
        )
        print(f"[ok] registered {meta['dataset_id']}: "
              f"{meta['date_range'].get('start')}~{meta['date_range'].get('end')}")
    else:
        print(f"[skip] HMMP data dir not found: {args.hmmp_data}")
        ok = False

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
