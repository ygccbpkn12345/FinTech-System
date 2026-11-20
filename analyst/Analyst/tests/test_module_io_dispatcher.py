from __future__ import annotations

import json
import threading
import time

import pytest

from services.module_io_dispatcher import (
    ModuleIODispatcher,
    ModuleIOError,
    ModuleSnapshot,
)


def test_dispatcher_uses_three_workers_and_writes_ordered_events(tmp_path):
    release = threading.Event()
    started = threading.Barrier(4)
    worker_threads = set()
    lock = threading.Lock()

    def before_write(snapshot):
        with lock:
            worker_threads.add(threading.get_ident())
        started.wait(timeout=2)
        release.wait(timeout=2)

    dispatcher = ModuleIODispatcher(
        output_root=tmp_path,
        task_id="task-1",
        before_write=before_write,
    )
    for index, name in enumerate(("market", "news", "fundamentals"), start=1):
        dispatcher.submit(ModuleSnapshot(name, {"value": index}, 1000.0 + index))

    started.wait(timeout=2)
    assert len(worker_threads) == 3
    release.set()
    dispatcher.close()

    task_dir = tmp_path / "task-1"
    events = json.loads((task_dir / "events.json").read_text(encoding="utf-8"))
    assert [event["sequence"] for event in events] == [1, 2, 3]
    assert {event["module"] for event in events} == {"market", "news", "fundamentals"}
    assert json.loads((task_dir / "modules" / "market.json").read_text(encoding="utf-8"))[
        "result"
    ] == {"value": 1}


def test_submit_is_async_but_close_waits_for_pending_write(tmp_path):
    release = threading.Event()
    write_started = threading.Event()

    def before_write(snapshot):
        write_started.set()
        release.wait(timeout=2)

    dispatcher = ModuleIODispatcher(
        output_root=tmp_path,
        task_id="task-2",
        before_write=before_write,
    )
    started = time.perf_counter()
    dispatcher.submit(ModuleSnapshot("market", {"value": 1}, 1001.0))
    assert time.perf_counter() - started < 0.2
    assert write_started.wait(timeout=1)

    closer = threading.Thread(target=dispatcher.close)
    closer.start()
    time.sleep(0.03)
    assert closer.is_alive()
    release.set()
    closer.join(timeout=2)
    assert not closer.is_alive()


def test_close_reports_module_specific_write_failures_after_drain(tmp_path):
    completed = []

    def before_write(snapshot):
        if snapshot.module == "news":
            raise OSError("disk unavailable")
        completed.append(snapshot.module)

    dispatcher = ModuleIODispatcher(
        output_root=tmp_path,
        task_id="task-3",
        before_write=before_write,
    )
    dispatcher.submit(ModuleSnapshot("news", {"value": 1}, 1001.0))
    dispatcher.submit(ModuleSnapshot("market", {"value": 2}, 1002.0))

    with pytest.raises(ModuleIOError, match="news"):
        dispatcher.close()

    assert completed == ["market"]


def test_snapshot_drops_sensitive_fields(tmp_path):
    dispatcher = ModuleIODispatcher(output_root=tmp_path, task_id="task-4")
    dispatcher.submit(
        ModuleSnapshot(
            "market",
            {"report": "ok", "api_key": "secret", "nested": {"tushare_token": "secret-2"}},
            1001.0,
        )
    )
    dispatcher.close()

    text = (tmp_path / "task-4" / "modules" / "market.json").read_text(encoding="utf-8")
    assert "secret" not in text
    assert "report" in text
