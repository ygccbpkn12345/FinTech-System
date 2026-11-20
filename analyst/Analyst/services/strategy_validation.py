"""Submit and recover the two FinPortfolio experiments for a buy report."""
from collections.abc import Callable, Iterator
import os
import re
from threading import Lock
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException


ALGORITHM = "single_stock_entry"
MODES = ("single", "staged")
RETRYABLE = {"FAILED", "CANCELLED"}
COST_PCT = 0.001
WINDOW_SESSIONS = 20
SECOND_ENTRY_SESSION = 6


def portfolio_client() -> Iterator[httpx.Client]:
    base_url = os.getenv("FINPORTFOLIO_API_BASE_URL", "http://127.0.0.1:8001")
    with httpx.Client(base_url=base_url, timeout=10.0, trust_env=False) as client:
        yield client


def request_json(client: httpx.Client, method: str, path: str, **options):
    try:
        response = client.request(method, path, **options)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 400 and path == "/api/experiments":
            reason = exc.response.json().get("detail", "")
            if "not registered" in str(reason):
                raise HTTPException(503, "FinPortfolio 尚未加载单股买入插件，请重启其后端") from exc
        raise HTTPException(502, "FinPortfolio 无法处理该回测请求，请检查实验或数据集") from exc
    except (httpx.RequestError, ValueError) as exc:
        raise HTTPException(503, "暂时无法连接 FinPortfolio，请检查回测后端是否已启动") from exc


def get_plan(task: dict | None) -> dict:
    if task is None:
        raise HTTPException(404, "分析任务不存在")
    if task["status"] != "completed":
        raise HTTPException(409, "分析尚未完成")
    report = task["result"]
    decision = report.get("finalDecision") or {}
    if decision.get("action") not in {"买入", "谨慎买入"}:
        raise HTTPException(409, "买入报告才可验证买入方式")
    position = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*%\s*", str(decision.get("position", "")))
    if not position or not 0.0001 <= float(position[1]) <= 100:
        raise HTTPException(422, "报告缺少可回测的建议仓位")
    symbol = task["stockCode"]
    if not re.fullmatch(r"\d{6}", symbol):
        raise HTTPException(422, "首版仅支持已登记日线数据的六位 A 股代码")
    return {
        "symbol": symbol,
        "analysis_mode": report.get("analysisMode"),
        "cutoff_date": task["analysisDate"],
        "position_ratio": float(position[1]) / 100,
        "cost_pct": COST_PCT,
        "window_sessions": WINDOW_SESSIONS,
        "second_entry_session": SECOND_ENTRY_SESSION,
    }


def find_runs(client: httpx.Client, prefix: str) -> dict:
    matches = request_json(client, "GET", "/api/experiments", params={"name_prefix": prefix})
    found = {}
    for run in matches:
        if run["algorithm_id"] != ALGORITHM:
            continue
        for mode in MODES:
            if run["name"] == f"{prefix}{mode}":
                found.setdefault(mode, run)
    return found


def choose_dataset(client: httpx.Client, plan: dict) -> str:
    datasets = request_json(client, "GET", "/api/datasets")
    prefix = f"analystverse_{plan['symbol']}_"
    matches = [row for row in datasets if row["dataset_id"].startswith(prefix)]
    if not matches:
        raise HTTPException(422, f"FinPortfolio 尚未登记 {plan['symbol']} 的演示日线")
    matches.sort(key=lambda row: (row.get("date_range") or {}).get("end") or "", reverse=True)
    for row in matches:
        dataset_id = row["dataset_id"]
        coverage = request_json(
            client, "GET", f"/api/datasets/{dataset_id}/price-coverage",
            params={"symbol": plan["symbol"], "before": plan["cutoff_date"]},
        )
        if coverage["sessions"] >= WINDOW_SESSIONS:
            return dataset_id
    raise HTTPException(422, "已登记行情在分析日之前不足 20 个有效交易日期")


def summarize(client: httpx.Client, plan: dict, runs: dict) -> dict:
    response = {"plan": plan, "results": {}}
    if not runs:
        return {**response, "status": "idle"}
    if any(run["status"] in RETRYABLE for run in runs.values()):
        return {**response, "status": "failed",
                "message": "回测失败。请检查该分析日之前是否有 20 条有效日线，再重试或到实验管理查看日志。"}
    if len(runs) != len(MODES):
        return {**response, "status": "incomplete", "message": "还有一笔实验未提交，可以继续验证。"}
    if any(run["status"] != "SUCCEEDED" for run in runs.values()):
        return {**response, "status": "running"}

    results = {}
    for mode, run in runs.items():
        experiment_id = run["experiment_id"]
        result = request_json(client, "GET", f"/api/results/{experiment_id}")
        results[mode] = {
            "experiment_id": experiment_id,
            "dataset_id": run["dataset_id"],
            "dataset_version": result["dataset_version"],
            "window_start": result["dates"][0],
            "window_end": result["dates"][-1],
            "net_return": result["metrics"]["cumulative_return"],
            "max_drawdown": result["metrics"]["max_drawdown"],
            "fills": result["trading_protocol"]["fills"],
        }
    single, staged = (results[mode] for mode in MODES)
    same_window = ("dataset_id", "dataset_version", "window_start", "window_end")
    if any(single[key] != staged[key] for key in same_window):
        return {**response, "status": "failed", "message": "两种方式的日期或行情版本不一致"}
    return {**response, "status": "completed", "results": results}


def build_strategy_validation_router(get_task: Callable[[str], dict | None]) -> APIRouter:
    router = APIRouter(prefix="/api/analyze", tags=["strategy-validation"])
    submit_lock = Lock()

    @router.get("/{task_id}/entry-validation")
    def get_comparison(task_id: UUID, client: httpx.Client = Depends(portfolio_client)):
        plan = get_plan(get_task(str(task_id)))
        return summarize(client, plan, find_runs(client, f"analystverse:{task_id}:entry-v1:"))

    @router.post("/{task_id}/entry-validation")
    def submit_comparison(task_id: UUID, client: httpx.Client = Depends(portfolio_client)):
        plan = get_plan(get_task(str(task_id)))
        prefix = f"analystverse:{task_id}:entry-v1:"
        with submit_lock:
            runs = find_runs(client, prefix)
            reusable_run = next((run for run in runs.values() if run["status"] not in RETRYABLE), None)
            dataset_id = reusable_run["dataset_id"] if reusable_run else choose_dataset(client, plan)
            for mode in MODES:
                if mode in runs and runs[mode]["status"] not in RETRYABLE:
                    continue
                runs[mode] = request_json(client, "POST", "/api/experiments", json={
                    "algorithm_id": ALGORITHM,
                    "dataset_id": dataset_id,
                    "capability": "backtest",
                    "name": f"{prefix}{mode}",
                    "params": {
                        "symbol": plan["symbol"], "cutoff_date": plan["cutoff_date"],
                        "position_ratio": plan["position_ratio"], "cost_pct": plan["cost_pct"],
                        "entry_mode": mode,
                    },
                })
        return summarize(client, plan, runs)

    return router

