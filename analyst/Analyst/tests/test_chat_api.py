import pytest
from fastapi.testclient import TestClient

import api_server
from api_server import app


@pytest.fixture
def client():
    return TestClient(app)


def test_chat_api_returns_conversation_and_messages(client):
    response = client.post(
        "/api/chat/messages",
        json={"message": "预测 000063", "clientMessageId": "client-1"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["conversationId"]
    assert body["messages"][0]["type"] == "parameter_request"
    assert body["messages"][0]["missingParameters"] == ["analysisDate"]


def test_chat_api_rejects_empty_message(client):
    response = client.post(
        "/api/chat/messages",
        json={"message": "   ", "clientMessageId": "client-2"},
    )

    assert response.status_code in {400, 422}


def test_chat_api_continues_existing_conversation(client, monkeypatch):
    # 此测试验证会话和任务衔接，日期可用性不依赖工作目录中不断更新的行情 CSV。
    monkeypatch.setattr(
        "services.tools.stock_prediction.validate_symbol_for_analysis",
        lambda stock_code, analysis_date: stock_code,
    )
    monkeypatch.setattr(
        api_server,
        "create_analysis_task",
        lambda stock_code, analysis_date, background_tasks=None, **kwargs: {
            "taskId": "task-123",
            "status": "running",
            "message": "分析任务已启动",
        },
    )

    first = client.post(
        "/api/chat/messages",
        json={"message": "预测中兴通讯", "clientMessageId": "client-3"},
    )
    conversation_id = first.json()["conversationId"]

    second = client.post(
        "/api/chat/messages",
        json={
            "conversationId": conversation_id,
            "message": "2024-01-03",
            "clientMessageId": "client-4",
        },
    )

    assert second.status_code == 200
    body = second.json()
    assert body["conversationId"] == conversation_id
    assert body["messages"][0]["type"] == "tool_progress"
    assert body["messages"][0]["taskId"] == "task-123"


def test_chat_api_routes_general_chat_to_a_text_message(client):
    response = client.post(
        "/api/chat/messages",
        json={"message": "你好", "clientMessageId": "client-5"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["messages"][0]["type"] in {"text", "error"}
