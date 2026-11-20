from __future__ import annotations

from datetime import datetime

import api_server


class CapturingExecutor:
    def __init__(self):
        self.calls = []

    def submit(self, fn, *args):
        self.calls.append((fn, args))


def make_task(task_id, analysis_date):
    with api_server._tasks_lock:
        api_server._tasks[task_id] = {
            "taskId": task_id,
            "status": "running",
            "currentStep": 0,
            "currentNode": "init",
            "progress": 0,
            "stockCode": "000063",
            "analysisDate": analysis_date,
            "result": None,
            "error": None,
            "modules": {},
            "events": [],
            "eventStream": api_server.TaskEventStream(api_server._tasks_lock),
        }


def test_historical_main_completes_before_postprocessing(monkeypatch):
    task_id = "historical"
    make_task(task_id, "2024-01-03")
    executor = CapturingExecutor()
    monkeypatch.setattr(api_server, "_postprocessing_executor", executor)
    monkeypatch.setattr(api_server, "run_analysis_pipeline", lambda **kwargs: {
        "stock": {"code": "000063", "analysisDate": "2024-01-03"},
        "finalDecision": {"action": "观望"},
    })

    api_server._execute_pipeline(task_id, "000063", "2024-01-03", "local_file", None, None, {})

    task = api_server._get_task(task_id)
    assert task["status"] == "completed"
    assert task["currentNode"] == "final_decision"
    assert task["postprocessing"]["status"] == "pending"
    assert len(executor.calls) == 1


def test_today_skips_postprocessing(monkeypatch):
    today = datetime.now().astimezone().date().isoformat()
    task_id = "today"
    make_task(task_id, today)
    executor = CapturingExecutor()
    monkeypatch.setattr(api_server, "_postprocessing_executor", executor)
    monkeypatch.setattr(api_server, "run_analysis_pipeline", lambda **kwargs: {
        "stock": {"code": "000063", "analysisDate": today},
        "finalDecision": {"action": "观望"},
    })

    api_server._execute_pipeline(task_id, "000063", today, "local_file", None, None, {})

    task = api_server._get_task(task_id)
    assert task["status"] == "completed"
    assert task["postprocessing"]["status"] == "not_applicable"
    assert executor.calls == []


def test_postprocessing_failure_does_not_change_main_status(monkeypatch):
    task_id = "failure"
    make_task(task_id, "2024-01-03")
    api_server._finish_task(task_id, "completed", result={"finalDecision": {"action": "买入"}})
    monkeypatch.setattr(api_server, "run_reflection_pipeline", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))

    api_server._execute_postprocessing(task_id, "000063", "2024-01-03", {})

    task = api_server._get_task(task_id)
    assert task["status"] == "completed"
    assert task["result"]["finalDecision"]["action"] == "买入"
    assert task["postprocessing"]["status"] == "failed"
    assert task["postprocessing"]["error"] == "boom"


def test_postprocessing_merges_only_owned_fields(monkeypatch):
    task_id = "merge"
    make_task(task_id, "2024-01-03")
    api_server._finish_task(task_id, "completed", result={"finalDecision": {"action": "买入"}})
    monkeypatch.setattr(api_server, "run_reflection_pipeline", lambda **kwargs: {
        "reflection": {"summary": "复盘完成"},
        "environmentSimulation": {"actual": "上涨"},
        "finalDecision": {"action": "篡改"},
    })

    api_server._execute_postprocessing(task_id, "000063", "2024-01-03", {})

    task = api_server._get_task(task_id)
    assert task["result"]["finalDecision"]["action"] == "买入"
    assert task["result"]["reflection"]["summary"] == "复盘完成"
    assert task["postprocessing"]["status"] == "completed"


def test_reflection_status_returns_identity_and_lifecycle():
    task_id = "status"
    make_task(task_id, "2024-01-03")
    api_server._update_task(task_id, postprocessing={"status": "pending"})

    payload = api_server.get_reflection_status(task_id)

    assert payload["taskId"] == task_id
    assert payload["stockCode"] == "000063"
    assert payload["analysisDate"] == "2024-01-03"
    assert payload["status"] == "pending"
