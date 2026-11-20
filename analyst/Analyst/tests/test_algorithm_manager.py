import json

import pytest

from services.algorithm_manager import AlgorithmManager, discover_local_tools
from services.chat_models import ToolResult
from services.tool_registry import ToolRegistry


class Echo:
    name = "echo"
    description = "Echo"
    required_parameters = ("query",)

    def execute(self, arguments, context):
        return ToolResult(tool=self.name, status="completed", summary=str(arguments["query"]), data=arguments)


def definition(**changes):
    return {"name": "echo", "description": "Echo query", "kind": "python", "local_tool": "echo", "required_parameters": ["query"], **changes}


def manager(tmp_path):
    return AlgorithmManager(tmp_path / "algorithms.json", {"echo": Echo()}, registry=ToolRegistry([]))


def test_crud_survives_restart_including_empty_catalog(tmp_path):
    m = manager(tmp_path)
    m.create(definition())
    assert manager(tmp_path).registry.get("echo").execute({"query": "hello"}, None).summary == "hello"
    m.update("echo", definition(description="Updated"))
    assert manager(tmp_path).get("echo")["description"] == "Updated"
    m.delete("echo")
    assert manager(tmp_path).list() == []
    assert json.loads((tmp_path / "algorithms.json").read_text())["algorithms"] == []


def test_duplicate_and_invalid_updates_leave_catalog_unchanged(tmp_path):
    m = manager(tmp_path)
    m.create(definition())
    original = m.path.read_bytes()
    with pytest.raises(ValueError):
        m.create(definition())
    with pytest.raises(ValueError):
        m.update("echo", definition(required_parameters=[]))
    with pytest.raises(ValueError):
        m.create(definition(name="bad", local_tool="os:system"))
    assert m.path.read_bytes() == original
    assert m.registry.get("echo").description == "Echo query"


def test_failed_save_keeps_previous_registry(tmp_path, monkeypatch):
    m = manager(tmp_path)
    m.create(definition())

    def fail(*args):
        raise OSError("disk full")

    monkeypatch.setattr("services.algorithm_manager.os.replace", fail)
    with pytest.raises(OSError):
        m.delete("echo")
    assert m.registry.get("echo").name == "echo"
    assert manager(tmp_path).get("echo")["name"] == "echo"


def test_required_arguments_accept_zero_and_false(tmp_path):
    m = manager(tmp_path)
    m.create(definition())
    tool = m.registry.get("echo")
    assert tool.missing_parameters({"query": 0}) == []
    assert tool.missing_parameters({"query": False}) == []
    assert tool.missing_parameters({"query": "  "}) == ["query"]


def test_http_definition_rejects_invalid_url_and_timeout(tmp_path):
    m = manager(tmp_path)
    for http in ({"url": "file:///tmp/x"}, {"url": "https://example.com", "timeout_seconds": float("inf")}):
        with pytest.raises(ValueError):
            m.create(definition(name="remote", kind="http", local_tool=None, http=http))
    assert m.list() == []


def test_trusted_plugin_is_discovered_without_editing_bootstrap(tmp_path, monkeypatch):
    from services.tools import plugins

    (tmp_path / "test_echo_plugin.py").write_text(
        'from services.chat_models import ToolResult\n'
        'class Plugin:\n'
        '    name = "discovered_echo"\n'
        '    description = "Plugin echo"\n'
        '    required_parameters = ("query",)\n'
        '    def execute(self, arguments, context):\n'
        '        return ToolResult(tool=self.name, status="completed", summary=arguments["query"])\n'
        'def build_tool():\n'
        '    return Plugin()\n', encoding="utf-8",
    )
    monkeypatch.setattr(plugins, "__path__", [str(tmp_path)])
    tool = discover_local_tools({})["discovered_echo"]
    assert tool.execute({"query": "plugin loaded"}, None).summary == "plugin loaded"


def test_reserved_api_path_cannot_be_registered_as_algorithm(tmp_path):
    m = manager(tmp_path)
    with pytest.raises(ValueError):
        m.create(definition(name="local-tools"))
