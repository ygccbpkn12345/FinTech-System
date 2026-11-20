from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

import api_server
from services import runtime_config
from services.task_event_stream import TaskEventStream


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(
        runtime_config, "RUNTIME_CONFIG_PATH", tmp_path / "server_runtime_config.json"
    )
    monkeypatch.setenv("CONFIG_ENCRYPTION_KEY", "competition-secret")
    return TestClient(api_server.app)


def test_unified_config_round_trip(client):
    response = client.post(
        "/api/config",
        json={
            "dataConfig": {
                "dataDir": "./custom-data",
                "dataCache": "./custom-cache",
                "resultDir": "./custom-result",
            },
            "llmConfig": {
                "quickThinkLlm": "model-a",
                "deepThinkLlm": "model-b",
                "baseUrl": "https://models.example/v1",
                "apiKey": "sk-secret-value",
                "timeout": 88,
                "maxRetries": 4,
                "analystConcurrency": 2,
            },
            "dataSource": "tushare",
            "crawlUrl": "https://finance.example/",
            "tushareToken": "tushare-secret-value",
        },
    )

    assert response.status_code == 200
    config = client.get("/api/config").json()
    assert config["dataDir"] == "./custom-data"
    assert config["quickThinkLlm"] == "model-a"
    assert config["dataSource"] == "tushare"
    assert config["apiKeyConfigured"] is True
    assert config["tushareTokenConfigured"] is True
    assert "sk-secret-value" not in response.text
    assert "tushare-secret-value" not in response.text


def test_data_source_compatibility_routes_share_the_repository(client):
    response = client.post(
        "/api/config/data-source",
        json={
            "dataSource": "baostock",
            "crawlUrl": "https://finance.example/",
            "tushareToken": "",
        },
    )

    assert response.status_code == 200
    assert client.get("/api/config").json()["dataSource"] == "baostock"
    compatibility = client.get("/api/config/data-source").json()
    assert compatibility["dataSource"] == "baostock"
    assert compatibility["crawlUrl"] == "https://finance.example/"


def test_secret_save_without_master_key_returns_422(client, monkeypatch):
    monkeypatch.delenv("CONFIG_ENCRYPTION_KEY")

    response = client.post("/api/config", json={"llmConfig": {"apiKey": "secret"}})

    assert response.status_code == 422
    assert "CONFIG_ENCRYPTION_KEY" in response.json()["detail"]


def test_explicit_clear_flags_remove_credentials(client):
    client.post(
        "/api/config",
        json={
            "llmConfig": {"apiKey": "sk-secret-value"},
            "tushareToken": "tushare-secret-value",
        },
    )

    response = client.post(
        "/api/config", json={"clearApiKey": True, "clearTushareToken": True}
    )

    assert response.status_code == 200
    config = client.get("/api/config").json()
    assert config["apiKeyConfigured"] is False
    assert config["tushareTokenConfigured"] is False


def test_analysis_task_captures_configuration_at_creation(client, monkeypatch):
    client.post(
        "/api/config",
        json={"llmConfig": {"quickThinkLlm": "model-a", "apiKey": "secret-a"}},
    )
    monkeypatch.setattr(api_server, "validate_symbol_for_analysis", lambda *_: None)

    captured = []

    class BackgroundCollector:
        def add_task(self, function, *args, **kwargs):
            captured.append((function, args, kwargs))

    request = api_server.AnalyzeStartRequest(
        stockCode="000001", analysisDate="2026-08-08", dataSource="local_file"
    )
    api_server.start_analysis(request, BackgroundCollector())
    client.post("/api/config", json={"llmConfig": {"quickThinkLlm": "model-b"}})

    _, args, _ = captured[0]
    snapshot = args[-1]
    assert snapshot["quick_think_llm"] == "model-a"
    assert snapshot["api_key"] == "secret-a"


def test_invalid_analysis_date_does_not_create_task(client, monkeypatch):
    monkeypatch.setattr(
        api_server,
        "validate_symbol_for_analysis",
        lambda *_: (_ for _ in ()).throw(ValueError("分析日期不可用")),
    )
    with api_server._tasks_lock:
        before = set(api_server._tasks)

    response = client.post(
        "/api/analyze/start",
        json={"stockCode": "600519", "analysisDate": "2026-08-10"},
    )

    assert response.status_code == 400
    with api_server._tasks_lock:
        assert set(api_server._tasks) == before


def _install_terminal_stream_task(task_id="stream-task"):
    stream = TaskEventStream()
    stream.append(
        "module_completed",
        {"module": "market", "status": "completed", "result": {"summary": "ready"}},
    )
    stream.append("completed", {"status": "completed"})
    with api_server._tasks_lock:
        api_server._tasks[task_id] = {
            "taskId": task_id,
            "status": "completed",
            "currentStep": 1,
            "currentNode": "market",
            "progress": 100,
            "modules": {},
            "events": [],
            "eventStream": stream,
        }
    return task_id


def test_analysis_event_stream_replays_events_and_closes_after_terminal(client):
    task_id = _install_terminal_stream_task()

    response = client.get(f"/api/analyze/events/{task_id}")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"
    assert "event: module_completed" in response.text
    assert '"summary":"ready"' in response.text
    assert "event: completed" in response.text


def test_analysis_event_stream_respects_last_event_id(client):
    task_id = _install_terminal_stream_task("resume-task")

    response = client.get(
        f"/api/analyze/events/{task_id}", headers={"Last-Event-ID": "1"}
    )

    assert "event: module_completed" not in response.text
    assert "id: 2" in response.text
    assert "event: completed" in response.text


def test_analysis_event_stream_returns_404_for_unknown_task(client):
    response = client.get("/api/analyze/events/missing-task")

    assert response.status_code == 404
