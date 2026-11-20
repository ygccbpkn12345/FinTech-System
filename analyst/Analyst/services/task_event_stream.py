"""Thread-safe, replayable task events for Server-Sent Events clients."""

from __future__ import annotations

import json
import threading
from copy import deepcopy
from typing import Any


TERMINAL_EVENT_TYPES = frozenset({"completed", "failed"})
_SENSITIVE_KEY_PARTS = ("apikey", "api_key", "token", "secret", "credential", "config")


def _is_sensitive_key(key: object) -> bool:
    normalized = str(key).replace("-", "_").lower()
    return any(part in normalized for part in _SENSITIVE_KEY_PARTS)


def sanitize_public_data(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: sanitize_public_data(item)
            for key, item in value.items()
            if not _is_sensitive_key(key)
        }
    if isinstance(value, (list, tuple)):
        return [sanitize_public_data(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


class TaskEventStream:
    """An in-memory monotonic event log with blocking replay support."""

    def __init__(self, lock: threading.RLock | None = None) -> None:
        self._condition = threading.Condition(lock or threading.RLock())
        self._events: list[dict[str, Any]] = []

    @property
    def is_terminal(self) -> bool:
        with self._condition:
            return bool(self._events and self._events[-1]["event"] in TERMINAL_EVENT_TYPES)

    def append(self, event_type: str, data: dict[str, Any]) -> dict[str, Any]:
        with self._condition:
            event = {
                "id": len(self._events) + 1,
                "event": event_type,
                "data": sanitize_public_data(data),
            }
            self._events.append(event)
            self._condition.notify_all()
            return deepcopy(event)

    def events_after(self, last_id: int) -> list[dict[str, Any]]:
        with self._condition:
            return deepcopy([event for event in self._events if event["id"] > last_id])

    def wait_after(self, last_id: int, timeout: float) -> list[dict[str, Any]]:
        with self._condition:
            pending = [event for event in self._events if event["id"] > last_id]
            if not pending and not self.is_terminal:
                self._condition.wait(timeout=timeout)
                pending = [event for event in self._events if event["id"] > last_id]
            return deepcopy(pending)


def encode_sse(event: dict[str, Any]) -> str:
    payload = json.dumps(event["data"], ensure_ascii=False, separators=(",", ":"))
    return f'id: {event["id"]}\nevent: {event["event"]}\ndata: {payload}\n\n'


def encode_heartbeat() -> str:
    return ": heartbeat\n\n"
