import pytest

from services.tool_registry import ToolRegistry


class FakeTool:
    name = "stock_prediction"
    description = "Predict a stock."
    required_parameters = ("stockCode", "analysisDate")


def test_registry_returns_registered_tool():
    registry = ToolRegistry([FakeTool()])
    assert registry.get("stock_prediction").name == "stock_prediction"


def test_registry_rejects_unknown_tool():
    registry = ToolRegistry([])
    with pytest.raises(KeyError, match="unknown_tool"):
        registry.get("unknown_tool")


def test_registry_describes_available_tools():
    registry = ToolRegistry([FakeTool()])

    assert registry.descriptions() == [
        {
            "name": "stock_prediction",
            "description": "Predict a stock.",
            "required_parameters": ["stockCode", "analysisDate"],
        }
    ]


def test_registry_rejects_duplicate_tool_names():
    with pytest.raises(ValueError, match="Duplicate tool name: stock_prediction"):
        ToolRegistry([FakeTool(), FakeTool()])
