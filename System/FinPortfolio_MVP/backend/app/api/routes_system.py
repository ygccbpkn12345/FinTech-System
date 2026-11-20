"""系统概览 API（仪表盘聚合）。"""
from __future__ import annotations

from fastapi import APIRouter, Request

from ..core.plugin_registry import registry

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/overview")
def overview(request: Request):
    experiments = request.app.state.experiments.list_experiments(limit=1000)
    done = [e for e in experiments if e["status"] == "SUCCEEDED" and e.get("result_summary")]
    running = [e for e in experiments if e["status"] in ("PENDING", "RUNNING")]

    latest_curve = None
    if done:
        try:
            result = request.app.state.experiments.get_result(done[0]["experiment_id"])
            from ..core.metrics import drawdown_series
            latest_curve = {
                "experiment_id": result.experiment_id,
                "name": done[0]["name"],
                "dates": result.dates,
                "values": result.portfolio_values,
                "drawdown": drawdown_series(result.daily_returns),
                "metrics": done[0]["result_summary"],
            }
        except Exception:  # noqa: BLE001 —— 概览页不因单条曲线失败而崩
            latest_curve = None

    return {
        "algorithms_registered": sum(
            1 for a in registry.list_plugins() if a["status"] == "READY"
        ),
        "algorithms_failed": sum(
            1 for a in registry.list_plugins() if a["status"] == "ERROR"
        ),
        "datasets": len(request.app.state.datasets.list_datasets()),
        "experiments_total": len(experiments),
        "experiments_succeeded": sum(1 for e in experiments if e["status"] == "SUCCEEDED"),
        "experiments_failed": sum(1 for e in experiments if e["status"] == "FAILED"),
        "running_tasks": [
            {
                "experiment_id": e["experiment_id"],
                "name": e["name"],
                "algorithm_id": e["algorithm_id"],
                "status": e["status"],
            }
            for e in running
        ],
        "recent_experiments": experiments[:8],
        "latest_portfolio_curve": latest_curve,
        "plugin_scan": registry.scan_summary(),
    }


@router.get("/health")
def health():
    return {"status": "ok"}
