from uuid import UUID

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

import services.strategy_validation as validation


TASK_ID = UUID("01a1e3a2-3626-7111-a92d-9358d28c9bcf")


def test_buy_report_submits_two_modes_once_and_recovers_results():
    runs = {}

    def portfolio(request):
        path = request.url.path
        if path == "/api/datasets":
            return httpx.Response(200, json=[{
                "dataset_id": "analystverse_000063_demo", "version": "abc",
                "date_range": {"start": "2025-01-01", "end": "2025-10-31", "days": 200},
            }])
        if path == "/api/datasets/analystverse_000063_demo/price-coverage":
            assert request.url.params["symbol"] == "000063"
            assert request.url.params["before"] == "2025-11-01"
            return httpx.Response(200, json={"sessions": 20})
        if path == "/api/experiments" and request.method == "GET":
            return httpx.Response(200, json=list(runs.values()))
        if path == "/api/experiments":
            import json
            body = json.loads(request.content)
            entry_mode = body["params"]["entry_mode"]
            assert body["algorithm_id"] == "single_stock_entry"
            assert body["dataset_id"] == "analystverse_000063_demo"
            assert body["params"]["position_ratio"] == 0.08
            assert body["params"]["cutoff_date"] == "2025-11-01"
            assert entry_mode not in runs, "should reuse submitted experiments"
            runs[entry_mode] = {
                "name": body["name"], "experiment_id": f"exp_{entry_mode}",
                "status": "SUCCEEDED", "dataset_id": body["dataset_id"],
                "algorithm_id": body["algorithm_id"],
            }
            return httpx.Response(200, json=runs[entry_mode])
        if path.startswith("/api/results/"):
            mode = path.rsplit("_", 1)[1]
            return httpx.Response(200, json={
                "dates": ["2025-10-01", "2025-10-31"], "dataset_version": "abc",
                "metrics": {"cumulative_return": 0.03 if mode == "staged" else 0.02,
                            "max_drawdown": -0.02 if mode == "staged" else -0.03},
                "trading_protocol": {"fills": []},
            })
        raise AssertionError(str(request.url))

    task = {
        "status": "completed", "stockCode": "000063", "analysisDate": "2025-11-01",
        "result": {"analysisMode": "mock", "finalDecision": {"action": "谨慎买入", "position": "8%"}},
    }
    app = FastAPI()
    app.include_router(validation.build_strategy_validation_router(
        lambda task_id: task if task_id == str(TASK_ID) else None,
    ))
    with httpx.Client(base_url="http://portfolio", transport=httpx.MockTransport(portfolio)) as upstream:
        app.dependency_overrides[validation.portfolio_client] = lambda: upstream
        with TestClient(app) as client:
            url = f"/api/analyze/{TASK_ID}/entry-validation"
            assert client.get(url).json()["status"] == "idle"
            submitted = client.post(url)
            assert submitted.status_code == 200, submitted.text
            assert client.post(url).status_code == 200
            report = client.get(url).json()
            assert report["status"] == "completed"
            assert report["plan"]["analysis_mode"] == "mock"
            assert report["results"]["single"]["net_return"] == 0.02
            assert report["results"]["staged"]["net_return"] == 0.03
            assert report["results"]["staged"]["experiment_id"] == "exp_staged"
            task["result"]["finalDecision"]["action"] = "观望"
            assert client.post(url).status_code == 409

