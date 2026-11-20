"""测试夹具：隔离的临时存储目录 + 预置真实插件副本。

必须在导入 app.* 之前设置环境变量（paths.py 在导入时解析），
因此全部在模块顶层完成。
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

_TMP = Path(tempfile.mkdtemp(prefix="finportfolio_test_"))
_TMP_PLUGINS = _TMP / "plugins"
shutil.copytree(PROJECT_ROOT / "plugins", _TMP_PLUGINS)

os.environ["FINPORTFOLIO_ROOT"] = str(_TMP)
os.environ["FINPORTFOLIO_PLUGINS_DIR"] = str(_TMP_PLUGINS)
os.environ["FINPORTFOLIO_DATASETS_DIR"] = str(_TMP / "datasets")
os.environ["FINPORTFOLIO_EXPERIMENTS_DIR"] = str(_TMP / "experiments")
os.environ["FINPORTFOLIO_LOGS_DIR"] = str(_TMP / "logs")
os.environ["FINPORTFOLIO_CHECKPOINTS_DIR"] = str(_TMP / "checkpoints")
os.environ["FINPORTFOLIO_ORIGINAL_CODE_ROOT"] = str(_TMP / "original_code")

sys.path.insert(0, str(PROJECT_ROOT / "backend"))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.core.plugin_registry import PluginRegistry  # noqa: E402


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def tmp_root() -> Path:
    return _TMP


@pytest.fixture(scope="session")
def real_registry() -> PluginRegistry:
    reg = PluginRegistry(_TMP_PLUGINS)
    reg.reload()
    return reg


@pytest.fixture(scope="session", autouse=True)
def price_dataset(client) -> dict:
    """确定性的合成行情数据集 —— 仅用于机制测试，绝不充当论文实验结果。"""
    import json

    import numpy as np
    import pandas as pd

    storage = _TMP / "datasets" / "storage" / "synthetic_test_prices"
    storage.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(7)
    dates = pd.bdate_range("2024-01-02", periods=120)
    rows = []
    for tic in ["AAA", "BBB", "CCC", "DDD", "EEE"]:
        px = 100.0 * np.cumprod(1 + rng.normal(0.0005, 0.01, len(dates)))
        for d, p in zip(dates, px):
            rows.append({"date": d.strftime("%Y-%m-%d"), "tic": tic, "close": round(p, 6)})
    csv = storage / "prices.csv"
    pd.DataFrame(rows).to_csv(csv, index=False)

    resp = client.post("/api/datasets", json={
        "name": "synthetic test prices (5 assets, 120 days, rng=7)",
        "market": "TEST",
        "files": {"prices": "prices.csv"},
        "available_modalities": ["prices"],
        "storage_mode": "copy",
        "source_dir": str(storage),
        "description": "deterministic synthetic fixture for mechanics tests only",
        "provenance": "synthetic (numpy default_rng(7))",
        "dataset_id": "synthetic_test_prices",
    })
    assert resp.status_code == 200, resp.text
    return resp.json()
