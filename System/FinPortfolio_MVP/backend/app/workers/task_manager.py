"""子进程任务管理器。

- 长时间训练绝不阻塞 FastAPI 请求线程（独立 worker 线程池）；
- 安全参数列表启动（subprocess list argv，绝不拼接 shell 命令）；
- 捕获 stdout/stderr → 逐行写入日志文件；
- 状态机：PENDING → RUNNING → SUCCEEDED / FAILED / CANCELLED；
- 支持取消（Windows 下 terminate 失败回退 taskkill /T /F 杀进程树）、
  超时、并发上限、服务重启后的中断恢复。
"""
from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

IS_WINDOWS = sys.platform == "win32"

TASK_STATES = ("PENDING", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED")
TERMINAL_STATES = ("SUCCEEDED", "FAILED", "CANCELLED")


@dataclass
class Task:
    task_id: str
    command: list          # argv 列表，绝不经过 shell
    cwd: str
    log_path: str
    timeout_seconds: int
    env: dict = field(default_factory=dict)
    state: str = "PENDING"
    returncode: Optional[int] = None
    error: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    process: Optional[subprocess.Popen] = None
    cancel_requested: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "state": self.state,
            "command": self.command,
            "cwd": self.cwd,
            "log_path": self.log_path,
            "timeout_seconds": self.timeout_seconds,
            "returncode": self.returncode,
            "error": self.error,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_seconds": (
                (self.finished_at or time.time()) - (self.started_at or self.created_at)
            ),
        }


class TaskManager:
    def __init__(
        self,
        max_concurrent: int = 1,
        default_timeout: int = 86400,
        on_finish: Optional[Callable[[Task], None]] = None,
    ) -> None:
        self.max_concurrent = max_concurrent
        self.default_timeout = default_timeout
        self.on_finish = on_finish
        self._tasks: dict[str, Task] = {}
        self._lock = threading.RLock()
        self._queue: "queue.Queue[str]" = queue.Queue()
        self._workers: list[threading.Thread] = []
        self._timeout_thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._start_workers()

    # ------------------------------------------------------------------
    def _start_workers(self) -> None:
        for i in range(max(1, self.max_concurrent)):
            t = threading.Thread(target=self._worker_loop, name=f"task-worker-{i}", daemon=True)
            t.start()
            self._workers.append(t)
        self._timeout_thread = threading.Thread(
            target=self._timeout_loop, name="task-timeout", daemon=True
        )
        self._timeout_thread.start()

    def _worker_loop(self) -> None:
        while not self._stop.is_set():
            try:
                task_id = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            task = self._tasks.get(task_id)
            if task is None or task.state != "PENDING":
                continue
            self._run(task)

    def _timeout_loop(self) -> None:
        while not self._stop.is_set():
            time.sleep(2.0)
            now = time.time()
            with self._lock:
                for task in list(self._tasks.values()):
                    if (
                        task.state == "RUNNING"
                        and task.started_at is not None
                        and now - task.started_at > task.timeout_seconds
                    ):
                        task.error = (
                            f"timeout after {task.timeout_seconds}s"
                        )
                        self._terminate(task)
                        self._finish(task, "FAILED")

    # ------------------------------------------------------------------
    def submit(
        self,
        task_id: str,
        command: list,
        cwd: str,
        log_path: str,
        timeout_seconds: Optional[int] = None,
        env: Optional[dict] = None,
    ) -> Task:
        if not isinstance(command, list) or not all(isinstance(x, str) for x in command):
            raise ValueError("command must be a list of strings (no shell strings)")
        with self._lock:
            if task_id in self._tasks and self._tasks[task_id].state == "RUNNING":
                raise ValueError(f"task '{task_id}' already running")
            task = Task(
                task_id=task_id,
                command=command,
                cwd=cwd,
                log_path=log_path,
                timeout_seconds=timeout_seconds or self.default_timeout,
                env=env or {},
            )
            self._tasks[task_id] = task
        self._queue.put(task_id)
        return task

    # ------------------------------------------------------------------
    def _run(self, task: Task) -> None:
        with self._lock:
            if task.cancel_requested:
                self._finish(task, "CANCELLED")
                return
            task.state = "RUNNING"
            task.started_at = time.time()

        Path(task.log_path).parent.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        env.update(task.env)
        env.setdefault("PYTHONIOENCODING", "utf-8")
        env.setdefault("PYTHONUNBUFFERED", "1")

        creationflags = 0
        if IS_WINDOWS:
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP

        log_file = open(task.log_path, "ab")
        try:
            proc = subprocess.Popen(
                task.command,
                cwd=task.cwd,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                env=env,
                creationflags=creationflags,
                shell=False,
            )
        except OSError as e:
            log_file.close()
            task.error = f"failed to start subprocess: {e}"
            self._finish(task, "FAILED")
            return

        task.process = proc
        header = (
            f"\n==== task {task.task_id} start {time.strftime('%Y-%m-%d %H:%M:%S')} ====\n"
            f"command: {' '.join(task.command)}\ncwd: {task.cwd}\n"
        ).encode("utf-8")
        log_file.write(header)
        log_file.flush()

        returncode = proc.wait()
        log_file.write(
            f"\n==== task {task.task_id} exit code {returncode} "
            f"at {time.strftime('%Y-%m-%d %H:%M:%S')} ====\n".encode("utf-8")
        )
        log_file.close()

        with self._lock:
            task.returncode = returncode
            if task.cancel_requested:
                self._finish(task, "CANCELLED")
            elif returncode == 0:
                self._finish(task, "SUCCEEDED")
            else:
                task.error = task.error or f"process exited with code {returncode}"
                self._finish(task, "FAILED")

    # ------------------------------------------------------------------
    def _terminate(self, task: Task) -> None:
        proc = task.process
        if proc is None or proc.poll() is not None:
            return
        try:
            proc.terminate()
            proc.wait(timeout=10)
            return
        except Exception:  # noqa: BLE001
            pass
        # Windows：terminate 可能无法杀掉子进程树，回退 taskkill
        if IS_WINDOWS:
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                    capture_output=True,
                    check=False,
                )
            except OSError:
                pass
        else:
            try:
                proc.kill()
                proc.wait(timeout=5)
            except Exception:  # noqa: BLE001
                pass

    def _finish(self, task: Task, state: str) -> None:
        task.state = state
        task.finished_at = time.time()
        if self.on_finish:
            try:
                self.on_finish(task)
            except Exception:  # noqa: BLE001 —— 回调故障不影响任务状态
                pass

    # ------------------------------------------------------------------
    def cancel(self, task_id: str) -> dict:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                raise KeyError(f"task '{task_id}' not found")
            if task.state in TERMINAL_STATES:
                return task.to_dict()
            task.cancel_requested = True
            if task.state == "PENDING":
                self._finish(task, "CANCELLED")
                return task.to_dict()
        self._terminate(task)
        # _run 的 wait() 返回后会置 CANCELLED；等待其落定
        deadline = time.time() + 15
        while time.time() < deadline and task.state == "RUNNING":
            time.sleep(0.2)
        if task.state == "RUNNING":
            with self._lock:
                self._finish(task, "CANCELLED")
        return task.to_dict()

    def status(self, task_id: str) -> dict:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                raise KeyError(f"task '{task_id}' not found")
            return task.to_dict()

    def logs(self, task_id: str, tail: int = 200) -> dict:
        with self._lock:
            task = self._tasks.get(task_id)
        if task is None:
            raise KeyError(f"task '{task_id}' not found")
        path = Path(task.log_path)
        if not path.is_file():
            return {"task_id": task_id, "state": task.state, "log": ""}
        text = path.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        if tail and len(lines) > tail:
            lines = lines[-tail:]
        return {"task_id": task_id, "state": task.state, "log": "\n".join(lines)}

    def list_tasks(self, state: Optional[str] = None) -> list[dict]:
        with self._lock:
            tasks = [t.to_dict() for t in self._tasks.values()]
        if state:
            tasks = [t for t in tasks if t["state"] == state]
        return sorted(tasks, key=lambda t: t["created_at"], reverse=True)

    def running_count(self) -> int:
        with self._lock:
            return sum(1 for t in self._tasks.values() if t.state in ("PENDING", "RUNNING"))

    def shutdown(self) -> None:
        self._stop.set()
        with self._lock:
            for task in self._tasks.values():
                if task.state == "RUNNING":
                    task.cancel_requested = True
                    self._terminate(task)
                    self._finish(task, "CANCELLED")
