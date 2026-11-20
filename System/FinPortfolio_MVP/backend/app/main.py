"""FinPortfolio 后端入口。

启动：在 backend 目录执行 python -m app。
"""
from __future__ import annotations

import atexit
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import (
    routes_algorithms,
    routes_datasets,
    routes_experiments,
    routes_results,
    routes_system,
    routes_tasks,
)
from .core.paths import ensure_runtime_dirs
from .core.plugin_registry import registry
from .services.dataset_service import DatasetService
from .services.experiment_service import ExperimentService
from .workers.task_manager import TaskManager

ensure_runtime_dirs()

app = FastAPI(
    title="FinPortfolio",
    version="2.0.0",
    description="可扩展金融投资组合算法管理与可视化平台（插件化架构）",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5174",
        "http://127.0.0.1:5174",
        "http://localhost:4173",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---- 组装服务（组合根） ----
max_concurrent = int(os.environ.get("FINPORTFOLIO_MAX_CONCURRENT_TASKS", "1"))
task_manager = TaskManager(max_concurrent=max_concurrent, default_timeout=86400)
dataset_service = DatasetService()
experiment_service = ExperimentService(
    task_manager=task_manager,
    dataset_service=dataset_service,
)
experiment_service.recover_interrupted()

app.state.tasks = task_manager
app.state.datasets = dataset_service
app.state.experiments = experiment_service

app.include_router(routes_system.router)
app.include_router(routes_algorithms.router)
app.include_router(routes_datasets.router)
app.include_router(routes_experiments.router)
app.include_router(routes_tasks.router)
app.include_router(routes_results.router)


@app.get("/api/health")
def health():
    return {"status": "ok", "version": "2.0.0"}


@atexit.register
def _shutdown() -> None:
    task_manager.shutdown()
