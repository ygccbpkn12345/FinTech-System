"""Bounded asynchronous persistence for per-module analysis results."""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


class ModuleIOError(RuntimeError):
    """Raised after pending I/O drains when one or more modules failed."""


@dataclass(frozen=True)
class ModuleSnapshot:
    module: str
    result: dict[str, Any]
    completed_at: float


_SENSITIVE_KEYS = {
    "api_key",
    "apikey",
    "tushare_token",
    "tusharetoken",
    "config_encryption_key",
}


def _public_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _public_value(item)
            for key, item in value.items()
            if str(key).lower() not in _SENSITIVE_KEYS
        }
    if isinstance(value, list):
        return [_public_value(item) for item in value]
    if isinstance(value, tuple):
        return [_public_value(item) for item in value]
    return value


def _atomic_json_write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as file:
            temporary = Path(file.name)
            json.dump(payload, file, ensure_ascii=False, indent=2, default=str)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    except OSError:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
        raise


class ModuleIODispatcher:
    WORKER_COUNT = 3
    PENDING_LIMIT = 12

    def __init__(
        self,
        *,
        output_root: str | Path,
        task_id: str,
        on_event: Callable[[dict[str, Any]], None] | None = None,
        before_write: Callable[[ModuleSnapshot], None] | None = None,
    ) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", task_id):
            raise ValueError("task_id contains unsupported path characters")
        self._task_dir = Path(output_root).resolve() / task_id
        self._on_event = on_event
        self._before_write = before_write
        self._executor = ThreadPoolExecutor(
            max_workers=self.WORKER_COUNT, thread_name_prefix="module-io"
        )
        self._slots = threading.BoundedSemaphore(self.PENDING_LIMIT)
        self._event_lock = threading.Lock()
        self._future_lock = threading.Lock()
        self._futures: list[tuple[str, Future[None]]] = []
        self._events: list[dict[str, Any]] = []
        self._closed = False

    def submit(self, snapshot: ModuleSnapshot) -> None:
        if self._closed:
            raise RuntimeError("module I/O dispatcher is closed")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", snapshot.module):
            raise ValueError("module contains unsupported path characters")
        safe_snapshot = ModuleSnapshot(
            module=snapshot.module,
            result=deepcopy(_public_value(snapshot.result)),
            completed_at=float(snapshot.completed_at),
        )
        self._slots.acquire()
        try:
            future = self._executor.submit(self._write_snapshot, safe_snapshot)
        except Exception:
            self._slots.release()
            raise
        future.add_done_callback(lambda _: self._slots.release())
        with self._future_lock:
            self._futures.append((snapshot.module, future))

    def _write_snapshot(self, snapshot: ModuleSnapshot) -> None:
        if self._before_write is not None:
            self._before_write(snapshot)
        module_payload = {
            "module": snapshot.module,
            "completedAt": snapshot.completed_at,
            "status": "completed",
            "result": snapshot.result,
        }
        _atomic_json_write(
            self._task_dir / "modules" / f"{snapshot.module}.json", module_payload
        )
        with self._event_lock:
            event = {
                "sequence": len(self._events) + 1,
                "module": snapshot.module,
                "completedAt": snapshot.completed_at,
                "status": "completed",
                "result": snapshot.result,
            }
            self._events.append(event)
            _atomic_json_write(self._task_dir / "events.json", self._events)
            if self._on_event is not None:
                self._on_event(deepcopy(event))

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        with self._future_lock:
            futures = list(self._futures)
        failures: list[tuple[str, BaseException]] = []
        for module, future in futures:
            try:
                future.result()
            except BaseException as exc:
                failures.append((module, exc))
        self._executor.shutdown(wait=True, cancel_futures=False)
        if failures:
            modules = ", ".join(module for module, _ in failures)
            raise ModuleIOError(f"module I/O failed for: {modules}") from failures[0][1]
