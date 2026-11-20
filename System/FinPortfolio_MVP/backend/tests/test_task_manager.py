"""任务状态机测试：启动/成功/失败/取消/超时/并发上限。"""
import sys
import time
from pathlib import Path

import pytest

from app.workers.task_manager import TaskManager

SLEEP_SCRIPT = "import time; time.sleep({seconds})"
FAIL_SCRIPT = "import sys; print('boom', file=sys.stderr); sys.exit(3)"
OK_SCRIPT = "print('hello from task')"


def _submit(tm, tmp_path, name, script, timeout=None):
    script_file = tmp_path / f"{name}.py"
    script_file.write_text(script, encoding="utf-8")
    return tm.submit(
        task_id=name,
        command=[sys.executable, str(script_file)],
        cwd=str(tmp_path),
        log_path=str(tmp_path / f"{name}.log"),
        timeout_seconds=timeout,
    )


def _wait_state(tm, task_id, wanted, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        state = tm.status(task_id)["state"]
        if state in wanted if isinstance(wanted, tuple) else state == wanted:
            return state
        time.sleep(0.1)
    return tm.status(task_id)["state"]


def test_success_path(tmp_path):
    tm = TaskManager(max_concurrent=2)
    try:
        _submit(tm, tmp_path, "ok", OK_SCRIPT)
        assert _wait_state(tm, "ok", "SUCCEEDED") == "SUCCEEDED"
        logs = tm.logs("ok")
        assert "hello from task" in logs["log"]
        assert tm.status("ok")["returncode"] == 0
    finally:
        tm.shutdown()


def test_failure_path_keeps_exit_code(tmp_path):
    tm = TaskManager(max_concurrent=1)
    try:
        _submit(tm, tmp_path, "fail", FAIL_SCRIPT)
        st = tm.status("fail")
        assert _wait_state(tm, "fail", "FAILED") == "FAILED"
        st = tm.status("fail")
        assert st["returncode"] == 3
        assert "exit" in (st["error"] or "")
        assert "boom" in tm.logs("fail")["log"]
    finally:
        tm.shutdown()


def test_cancel_running_task(tmp_path):
    tm = TaskManager(max_concurrent=1)
    try:
        _submit(tm, tmp_path, "sleep30", SLEEP_SCRIPT.format(seconds=30))
        assert _wait_state(tm, "sleep30", "RUNNING") == "RUNNING"
        result = tm.cancel("sleep30")
        assert result["state"] == "CANCELLED"
    finally:
        tm.shutdown()


def test_cancel_pending_task(tmp_path):
    tm = TaskManager(max_concurrent=1)   # 单并发，第二个任务将排队
    try:
        _submit(tm, tmp_path, "blocker", SLEEP_SCRIPT.format(seconds=8))
        _wait_state(tm, "blocker", "RUNNING")
        _submit(tm, tmp_path, "queued", SLEEP_SCRIPT.format(seconds=0.1))
        time.sleep(0.3)
        assert tm.status("queued")["state"] == "PENDING"
        result = tm.cancel("queued")
        assert result["state"] == "CANCELLED"
        assert tm.status("blocker")["state"] == "RUNNING"
    finally:
        tm.shutdown()


def test_timeout_marks_failed(tmp_path):
    tm = TaskManager(max_concurrent=1)
    try:
        _submit(tm, tmp_path, "slow", SLEEP_SCRIPT.format(seconds=60), timeout=3)
        state = _wait_state(tm, "slow", "FAILED", timeout=20)
        assert state == "FAILED"
        assert "timeout" in (tm.status("slow")["error"] or "")
    finally:
        tm.shutdown()


def test_shell_string_command_rejected(tmp_path):
    tm = TaskManager(max_concurrent=1)
    try:
        with pytest.raises(ValueError):
            tm.submit("bad", "echo hack", cwd=".", log_path=str(tmp_path / "x.log"))
    finally:
        tm.shutdown()


def test_state_transition_sequence(tmp_path):
    """PENDING → RUNNING → SUCCEEDED 全链路状态留痕。"""
    tm = TaskManager(max_concurrent=1)
    try:
        _submit(tm, tmp_path, "trace", "import time; time.sleep(1); print('done')")
        seen = []
        for _ in range(100):
            seen.append(tm.status("trace")["state"])
            if seen[-1] in ("SUCCEEDED", "FAILED"):
                break
            time.sleep(0.05)
        assert "SUCCEEDED" in seen
        assert seen[0] in ("PENDING", "RUNNING")
        st = tm.status("trace")
        assert st["started_at"] >= st["created_at"]
        assert st["finished_at"] >= st["started_at"]
    finally:
        tm.shutdown()
