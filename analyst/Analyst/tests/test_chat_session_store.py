from datetime import datetime, timedelta, timezone

import pytest

from services.chat_session_store import ChatSessionStore


class Clock:
    def __init__(self):
        self.now = datetime(2026, 10, 14, tzinfo=timezone.utc)

    def __call__(self):
        return self.now


def test_session_merges_parameters_across_turns():
    store = ChatSessionStore(max_sessions=10)
    session = store.create()
    store.set_pending(session.id, "stock_prediction", {"stockCode": "000063"})

    updated = store.merge_pending_arguments(
        session.id,
        {"analysisDate": "2024-01-03"},
    )

    assert updated.pending_arguments == {
        "stockCode": "000063",
        "analysisDate": "2024-01-03",
    }


def test_session_contains_chat_orchestration_state():
    store = ChatSessionStore(max_sessions=10)

    session = store.create()

    assert session.messages == []
    assert session.pending_tool is None
    assert session.pending_arguments == {}
    assert session.pending_confirmation is None
    assert session.task_id is None
    assert session.updated_at.tzinfo is not None


def test_create_removes_expired_sessions():
    clock = Clock()
    store = ChatSessionStore(max_sessions=10, ttl_seconds=30, clock=clock)
    expired = store.create()
    clock.now += timedelta(seconds=31)

    store.create()

    assert store.get(expired.id) is None


def test_create_evicts_oldest_session_at_capacity():
    clock = Clock()
    store = ChatSessionStore(max_sessions=2, clock=clock)
    oldest = store.create()
    clock.now += timedelta(seconds=1)
    retained = store.create()
    clock.now += timedelta(seconds=1)

    newest = store.create()

    assert store.get(oldest.id) is None
    assert store.get(retained.id).id == retained.id
    assert store.get(newest.id).id == newest.id


def test_returned_sessions_cannot_mutate_stored_state():
    store = ChatSessionStore(max_sessions=10)
    created = store.create()
    created.messages.append("injected")
    created.pending_confirmation = {"confirmed": True}
    created.task_id = "injected-task"

    fetched = store.get(created.id)
    fetched.pending_arguments["stockCode"] = "000063"

    stored = store.get(created.id)
    assert stored.messages == []
    assert stored.pending_confirmation is None
    assert stored.task_id is None
    assert stored.pending_arguments == {}


def test_input_arguments_cannot_mutate_stored_state():
    store = ChatSessionStore(max_sessions=10)
    session = store.create()
    initial = {"filters": {"market": "SZ"}}
    additional = {"options": {"adjust": "forward"}}

    store.set_pending(session.id, "stock_prediction", initial)
    store.merge_pending_arguments(session.id, additional)
    initial["filters"]["market"] = "SH"
    additional["options"]["adjust"] = "none"

    stored = store.get(session.id)
    assert stored.pending_arguments == {
        "filters": {"market": "SZ"},
        "options": {"adjust": "forward"},
    }


def test_append_message_copies_input_and_returns_snapshot():
    store = ChatSessionStore(max_sessions=10)
    session = store.create()
    message = {"content": {"text": "hello"}}

    updated = store.append_message(session.id, message)
    message["content"]["text"] = "changed outside"
    updated.messages[0]["content"]["text"] = "changed snapshot"

    assert store.get(session.id).messages == [{"content": {"text": "hello"}}]


def test_pending_confirmation_has_explicit_set_and_clear_operations():
    store = ChatSessionStore(max_sessions=10)
    session = store.create()
    confirmation = {"action": {"type": "crawl"}}

    updated = store.set_pending_confirmation(session.id, confirmation)
    confirmation["action"]["type"] = "changed outside"
    updated.pending_confirmation["action"]["type"] = "changed snapshot"

    assert store.get(session.id).pending_confirmation == {
        "action": {"type": "crawl"}
    }
    assert store.clear_pending_confirmation(session.id).pending_confirmation is None


def test_task_id_has_explicit_set_and_clear_operations():
    store = ChatSessionStore(max_sessions=10)
    session = store.create()

    assert store.set_task_id(session.id, "task-123").task_id == "task-123"
    assert store.get(session.id).task_id == "task-123"
    assert store.clear_task_id(session.id).task_id is None


def test_clear_pending_only_clears_tool_and_arguments():
    store = ChatSessionStore(max_sessions=10)
    session = store.create()
    store.set_pending(session.id, "stock_prediction", {"stockCode": "000063"})
    store.set_pending_confirmation(session.id, {"confirmed": False})
    store.set_task_id(session.id, "task-123")

    updated = store.clear_pending(session.id)

    assert updated.pending_tool is None
    assert updated.pending_arguments == {}
    assert updated.pending_confirmation == {"confirmed": False}
    assert updated.task_id == "task-123"


def test_get_removes_session_at_exact_ttl_boundary():
    clock = Clock()
    store = ChatSessionStore(max_sessions=10, ttl_seconds=30, clock=clock)
    session = store.create()
    clock.now += timedelta(seconds=30)

    assert store.get(session.id) is None
    assert store.get(session.id) is None


def test_mutation_rejects_expired_session_instead_of_reviving_it():
    clock = Clock()
    store = ChatSessionStore(max_sessions=10, ttl_seconds=30, clock=clock)
    session = store.create()
    clock.now += timedelta(seconds=31)

    with pytest.raises(KeyError, match=session.id):
        store.set_pending(session.id, "stock_prediction", {})

    assert store.get(session.id) is None


@pytest.mark.parametrize("max_sessions", [0, -1])
def test_store_requires_positive_max_sessions(max_sessions):
    with pytest.raises(ValueError, match="max_sessions"):
        ChatSessionStore(max_sessions=max_sessions)


@pytest.mark.parametrize("ttl_seconds", [0, -1, float("inf"), float("nan")])
def test_store_requires_positive_finite_ttl(ttl_seconds):
    with pytest.raises(ValueError, match="ttl_seconds"):
        ChatSessionStore(ttl_seconds=ttl_seconds)
