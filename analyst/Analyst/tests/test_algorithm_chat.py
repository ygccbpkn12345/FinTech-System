import json
import pytest

from services.algorithm_manager import AlgorithmManager
from services.chat_orchestrator import ChatOrchestrator
from services.tool_registry import ToolRegistry
from test_algorithm_manager import Echo, definition


class RouteModel:
    def __init__(self, route):
        self.route = route
        self.prompts = []

    def invoke(self, messages):
        self.prompts.append(messages)
        return type("Response", (), {"content": json.dumps(self.route)})()


def test_new_algorithm_is_discovered_without_rebuilding_orchestrator(tmp_path):
    registry = ToolRegistry([])
    manager = AlgorithmManager(tmp_path / "algorithms.json", {"echo": Echo()}, registry=registry)
    model = RouteModel({"tool": "echo", "arguments": {"query": "hi"}})
    chat = ChatOrchestrator(registry, model_factory=lambda: model)
    manager.create(definition())
    response = chat.handle(None, "执行回声")
    assert response.messages[0].result.summary == "hi"
    assert "Echo query" in model.prompts[-1][0]["content"]
    manager.update("echo", definition(description="Updated echo"))
    chat.handle(None, "执行回声")
    assert "Updated echo" in model.prompts[-1][0]["content"]


def test_generic_required_argument_can_be_completed_in_next_turn(tmp_path):
    manager = AlgorithmManager(tmp_path / "algorithms.json", {"echo": Echo()})
    manager.create(definition())
    model = RouteModel({"tool": "echo", "arguments": {}})
    chat = ChatOrchestrator(manager.registry, model_factory=lambda: model)
    first = chat.handle(None, "执行回声")
    assert first.messages[0].missing_parameters == ["query"]
    second = chat.handle(first.conversation_id, "hello world")
    assert second.messages[0].result.summary == "hello world"


def test_deleted_pending_algorithm_returns_error_and_clears_pending(tmp_path):
    manager = AlgorithmManager(tmp_path / "algorithms.json", {"echo": Echo()})
    manager.create(definition())
    model = RouteModel({"tool": "echo", "arguments": {}})
    chat = ChatOrchestrator(manager.registry, model_factory=lambda: model)
    first = chat.handle(None, "执行回声")
    manager.delete("echo")
    second = chat.handle(first.conversation_id, "hello")
    assert second.messages[0].type == "error"
    assert chat.store.get(first.conversation_id).pending_tool is None


def test_deleted_builtin_is_not_routed_by_keyword_fallback():
    chat = ChatOrchestrator(ToolRegistry([]), model_factory=lambda: None)
    assert chat.handle(None, "预测 000063").messages[0].tool == "general_chat"


@pytest.mark.parametrize("text, expected", [("123", 123), ("false", False), ('"hello"', "hello")])
def test_generic_parameter_accepts_scalar_json_reply(tmp_path, text, expected):
    manager = AlgorithmManager(tmp_path / "algorithms.json", {"echo": Echo()})
    manager.create(definition())
    model = RouteModel({"tool": "echo", "arguments": {}})
    chat = ChatOrchestrator(manager.registry, model_factory=lambda: model)
    first = chat.handle(None, "echo")
    second = chat.handle(first.conversation_id, text)
    assert second.messages[0].result.data["query"] == expected


@pytest.mark.parametrize("reply", ["AAPL", '{"stockCode":"AAPL"}', "stockCode=AAPL"])
def test_new_tool_can_complete_stock_named_parameter_without_stock_format(tmp_path, reply):
    class Quote(Echo):
        name = "us_quote"
        required_parameters = ("stockCode",)

        def execute(self, arguments, context):
            return super().execute({"query": arguments["stockCode"]}, context)

    manager = AlgorithmManager(tmp_path / "algorithms.json", {"us_quote": Quote()})
    manager.create(definition(name="us_quote", local_tool="us_quote", required_parameters=["stockCode"]))
    model = RouteModel({"tool": "us_quote", "arguments": {}})
    chat = ChatOrchestrator(manager.registry, model_factory=lambda: model)
    first = chat.handle(None, "查美股")
    second = chat.handle(first.conversation_id, reply)
    assert second.messages[0].result.summary == "AAPL"


def test_registry_change_during_route_does_not_break_current_turn(tmp_path):
    manager = AlgorithmManager(tmp_path / "algorithms.json", {"echo": Echo()})
    manager.create(definition())

    class DeletingModel(RouteModel):
        def invoke(self, messages):
            manager.delete("echo")
            return super().invoke(messages)

    model = DeletingModel({"tool": "echo", "arguments": {"query": "snapshot"}})
    chat = ChatOrchestrator(manager.registry, model_factory=lambda: model)
    assert chat.handle(None, "echo").messages[0].result.summary == "snapshot"
    assert manager.list() == []
