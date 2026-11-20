"""Thread-safe in-process storage for chat orchestration state."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from math import isfinite
from numbers import Integral, Real
from threading import RLock
from typing import Any, Callable
from uuid import uuid4


@dataclass
class ChatSession:
    id: str = field(default_factory=lambda: str(uuid4()))
    messages: list[Any] = field(default_factory=list)
    pending_tool: str | None = None
    pending_arguments: dict[str, Any] = field(default_factory=dict)
    pending_confirmation: Any | None = None
    task_id: str | None = None
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class ChatSessionStore:
    def __init__(
        self,
        *,
        max_sessions: int = 100,
        ttl_seconds: float = 3600,
        clock: Callable[[], datetime] | None = None,
    ):
        if (
            not isinstance(max_sessions, Integral)
            or isinstance(max_sessions, bool)
            or max_sessions <= 0
        ):
            raise ValueError("max_sessions must be a positive integer")
        if (
            not isinstance(ttl_seconds, Real)
            or isinstance(ttl_seconds, bool)
            or not isfinite(ttl_seconds)
            or ttl_seconds <= 0
        ):
            raise ValueError("ttl_seconds must be a positive finite number")
        self._max_sessions = max_sessions
        self._ttl = timedelta(seconds=ttl_seconds)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._sessions: dict[str, ChatSession] = {}
        self._lock = RLock()

    def create(self) -> ChatSession:
        with self._lock:
            now = self._clock()
            self._remove_expired(now)
            while len(self._sessions) >= self._max_sessions:
                oldest_id = min(
                    self._sessions,
                    key=lambda session_id: self._sessions[session_id].updated_at,
                )
                del self._sessions[oldest_id]

            session = ChatSession(updated_at=now)
            self._sessions[session.id] = session
            return self._snapshot(session)

    def get(self, session_id: str) -> ChatSession | None:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None

            now = self._clock()
            if self._is_expired(session, now):
                del self._sessions[session_id]
                return None

            session.updated_at = now
            return self._snapshot(session)

    def set_pending(
        self,
        session_id: str,
        tool: str,
        arguments: dict[str, Any],
    ) -> ChatSession:
        with self._lock:
            now = self._clock()
            session = self._require(session_id, now)
            session.pending_tool = tool
            session.pending_arguments = deepcopy(arguments)
            session.updated_at = now
            return self._snapshot(session)

    def merge_pending_arguments(
        self,
        session_id: str,
        arguments: dict[str, Any],
    ) -> ChatSession:
        with self._lock:
            now = self._clock()
            session = self._require(session_id, now)
            session.pending_arguments.update(deepcopy(arguments))
            session.updated_at = now
            return self._snapshot(session)

    def append_message(self, session_id: str, message: Any) -> ChatSession:
        with self._lock:
            now = self._clock()
            session = self._require(session_id, now)
            session.messages.append(deepcopy(message))
            session.updated_at = now
            return self._snapshot(session)

    def set_pending_confirmation(
        self,
        session_id: str,
        confirmation: Any,
    ) -> ChatSession:
        with self._lock:
            now = self._clock()
            session = self._require(session_id, now)
            session.pending_confirmation = deepcopy(confirmation)
            session.updated_at = now
            return self._snapshot(session)

    def clear_pending_confirmation(self, session_id: str) -> ChatSession:
        with self._lock:
            now = self._clock()
            session = self._require(session_id, now)
            session.pending_confirmation = None
            session.updated_at = now
            return self._snapshot(session)

    def set_task_id(self, session_id: str, task_id: str) -> ChatSession:
        with self._lock:
            now = self._clock()
            session = self._require(session_id, now)
            session.task_id = task_id
            session.updated_at = now
            return self._snapshot(session)

    def clear_task_id(self, session_id: str) -> ChatSession:
        with self._lock:
            now = self._clock()
            session = self._require(session_id, now)
            session.task_id = None
            session.updated_at = now
            return self._snapshot(session)

    def clear_pending(self, session_id: str) -> ChatSession:
        """Clear the pending tool and its collected arguments only."""
        with self._lock:
            now = self._clock()
            session = self._require(session_id, now)
            session.pending_tool = None
            session.pending_arguments = {}
            session.updated_at = now
            return self._snapshot(session)

    def _require(self, session_id: str, now: datetime) -> ChatSession:
        try:
            session = self._sessions[session_id]
        except KeyError:
            raise KeyError(f"Unknown chat session: {session_id}") from None
        if self._is_expired(session, now):
            del self._sessions[session_id]
            raise KeyError(f"Unknown chat session: {session_id}")
        return session

    def _remove_expired(self, now: datetime) -> None:
        expired_ids = [
            session_id
            for session_id, session in self._sessions.items()
            if self._is_expired(session, now)
        ]
        for session_id in expired_ids:
            del self._sessions[session_id]

    def _is_expired(self, session: ChatSession, now: datetime) -> bool:
        return now - session.updated_at >= self._ttl

    def _snapshot(self, session: ChatSession) -> ChatSession:
        return deepcopy(session)
