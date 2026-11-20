from __future__ import annotations

import json
import threading
import time

from services.task_event_stream import TaskEventStream, encode_heartbeat, encode_sse


def test_append_assigns_ids_and_replays_only_after_requested_id():
    stream = TaskEventStream()
    first = stream.append("module_completed", {"module": "market"})
    second = stream.append("module_completed", {"module": "news"})

    assert first["id"] == 1
    assert second["id"] == 2
    assert [event["data"]["module"] for event in stream.events_after(1)] == ["news"]


def test_wait_after_is_woken_by_new_event():
    stream = TaskEventStream()
    received = []

    waiter = threading.Thread(
        target=lambda: received.extend(stream.wait_after(0, timeout=1.0))
    )
    waiter.start()
    time.sleep(0.03)
    stream.append("module_completed", {"module": "market"})
    waiter.join(timeout=1.0)

    assert not waiter.is_alive()
    assert received[0]["data"]["module"] == "market"


def test_wait_timeout_returns_empty_for_heartbeat_and_terminal_closes_stream():
    stream = TaskEventStream()
    assert stream.wait_after(0, timeout=0.01) == []

    stream.append("completed", {"status": "completed"})

    assert stream.is_terminal is True
    assert stream.wait_after(1, timeout=0.01) == []


def test_sensitive_fields_are_removed_recursively_and_sse_is_well_formed():
    stream = TaskEventStream()
    event = stream.append(
        "module_completed",
        {
            "module": "market",
            "result": {
                "summary": "ok",
                "apiKey": "sk-secret",
                "nested": {"tushare_token": "token-secret"},
            },
            "config_snapshot": {"model": "private"},
        },
    )

    encoded = encode_sse(event)
    payload = json.loads(encoded.split("data: ", 1)[1].strip())

    assert encoded.startswith("id: 1\nevent: module_completed\n")
    assert payload["result"]["summary"] == "ok"
    assert "sk-secret" not in encoded
    assert "token-secret" not in encoded
    assert "config_snapshot" not in encoded
    assert encode_heartbeat() == ": heartbeat\n\n"
