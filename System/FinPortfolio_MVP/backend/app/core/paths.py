"""项目路径解析。所有存储位置集中在此，可用环境变量覆盖。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]


def _resolve(env_var: str, default: Path) -> Path:
    value = os.environ.get(env_var)
    return Path(value).resolve() if value else default


PROJECT_ROOT: Path = _resolve("FINPORTFOLIO_ROOT", BACKEND_DIR.parent)
PLUGINS_DIR: Path = _resolve("FINPORTFOLIO_PLUGINS_DIR", PROJECT_ROOT / "plugins")
DATASETS_DIR: Path = _resolve("FINPORTFOLIO_DATASETS_DIR", PROJECT_ROOT / "datasets")
EXPERIMENTS_DIR: Path = _resolve("FINPORTFOLIO_EXPERIMENTS_DIR", PROJECT_ROOT / "experiments")
LOGS_DIR: Path = _resolve("FINPORTFOLIO_LOGS_DIR", PROJECT_ROOT / "logs")
CHECKPOINTS_DIR: Path = _resolve("FINPORTFOLIO_CHECKPOINTS_DIR", PROJECT_ROOT / "checkpoints")

# 原始论文代码目录（ASACPL / HMMP），位于本仓库之外，保持原样不修改。
# 插件 manifest 通过相对路径引用；可用环境变量整体搬迁。
DEFAULT_ORIGINAL_CODE_ROOT: Path = _resolve(
    "FINPORTFOLIO_ORIGINAL_CODE_ROOT", PROJECT_ROOT.parent
)

PLUGIN_RUNNER_PATH: Path = Path(__file__).resolve().parents[1] / "workers" / "plugin_runner.py"
PLUGIN_INTERFACE_PATH: Path = Path(__file__).resolve().parent / "plugin_interface.py"

DEFAULT_PYTHON: str = sys.executable


def ensure_runtime_dirs() -> None:
    for d in (DATASETS_DIR, EXPERIMENTS_DIR, LOGS_DIR, CHECKPOINTS_DIR):
        d.mkdir(parents=True, exist_ok=True)
