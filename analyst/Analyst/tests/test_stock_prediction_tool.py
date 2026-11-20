import pytest

from services.chat_models import ToolResult
from services.tools.stock_prediction import StockPredictionTool


class Recorder:
    def __init__(self, task_id="task-123"):
        self.calls = []
        self.task_id = task_id

    def __call__(self, stock_code, analysis_date, background_tasks=None):
        self.calls.append((stock_code, analysis_date, background_tasks))
        return self.task_id


def test_stock_tool_requests_only_missing_analysis_date():
    tool = StockPredictionTool(start_task=lambda *_: "unused")

    assert tool.missing_parameters({"stockCode": "000063"}) == ["analysisDate"]


def test_stock_tool_requests_nothing_when_parameters_are_complete():
    tool = StockPredictionTool(start_task=lambda *_: "unused")

    assert tool.missing_parameters(
        {"stockCode": "000063", "analysisDate": "2024-01-03"}
    ) == []


def test_stock_tool_requires_stock_code_first():
    tool = StockPredictionTool(start_task=lambda *_: "unused")

    assert tool.missing_parameters({}) == ["stockCode", "analysisDate"]
    assert tool.missing_parameters({"analysisDate": "2024-01-03"}) == ["stockCode"]


def test_execute_starts_task_and_returns_running_result():
    recorder = Recorder()
    tool = StockPredictionTool(start_task=recorder, validate=lambda *_: "000063")

    result = tool.execute(
        {"stockCode": "000063", "analysisDate": "2024-01-03"},
        None,
    )

    assert recorder.calls == [("000063", "2024-01-03", None)]
    assert isinstance(result, ToolResult)
    assert result.tool == "stock_prediction"
    assert result.status == "running"
    assert result.data["taskId"] == "task-123"
    assert result.data["stockCode"] == "000063"
    assert result.actions[0].type == "navigate"
    assert result.actions[0].target == "/dashboard"


def test_execute_forwards_background_tasks_from_context():
    from services.tools import ToolContext

    recorder = Recorder()
    background = object()

    StockPredictionTool(start_task=recorder, validate=lambda *_: "000063").execute(
        {"stockCode": "000063", "analysisDate": "2024-01-03"},
        ToolContext(background_tasks=background),
    )

    assert recorder.calls[0][2] is background


def test_execute_rejects_invalid_symbol_before_starting_task():
    recorder = Recorder()

    def rejecting_validator(stock_code, analysis_date=None):
        raise ValueError("股票 999999 缺少本地数据")

    tool = StockPredictionTool(
        start_task=recorder,
        validate=rejecting_validator,
    )

    with pytest.raises(ValueError, match="缺少本地数据"):
        tool.execute({"stockCode": "999999", "analysisDate": "2024-01-03"}, None)
    assert recorder.calls == []
