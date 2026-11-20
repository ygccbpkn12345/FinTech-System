import pytest

import api_server


class BackgroundRecorder:
    def __init__(self):
        self.calls = []

    def add_task(self, func, *args, **kwargs):
        self.calls.append((func, args, kwargs))


def test_create_analysis_task_records_task_and_schedules_pipeline(monkeypatch):
    background = BackgroundRecorder()
    monkeypatch.setattr(
        api_server,
        "validate_symbol_for_analysis",
        lambda code, date: code,
    )
    monkeypatch.setattr(api_server, "_find_running_task", lambda code, date: None)

    created = api_server.create_analysis_task("000063", "2024-01-03", background)

    stored = api_server._get_task(created["taskId"])
    assert created["status"] == "running"
    assert created["message"] == "分析任务已启动"
    assert stored["stockCode"] == "000063"
    assert stored["analysisDate"] == "2024-01-03"
    assert [call[0] for call in background.calls] == [api_server._execute_pipeline]


def test_create_analysis_task_reuses_running_task(monkeypatch):
    monkeypatch.setattr(
        api_server,
        "validate_symbol_for_analysis",
        lambda code, date: code,
    )
    monkeypatch.setattr(
        api_server,
        "_find_running_task",
        lambda code, date: {"taskId": "task-1"},
    )

    created = api_server.create_analysis_task("000063", "2024-01-03", None)

    assert created["taskId"] == "task-1"
    assert created["status"] == "running"
    assert created["message"] == "分析任务进行中，请稍候"


def test_create_analysis_task_surfaces_validation_errors(monkeypatch):
    def reject(code, date):
        raise ValueError("股票 000000 缺少本地数据")

    monkeypatch.setattr(api_server, "validate_symbol_for_analysis", reject)

    with pytest.raises(ValueError, match="缺少本地数据"):
        api_server.create_analysis_task("000000", "2024-01-03", None)
