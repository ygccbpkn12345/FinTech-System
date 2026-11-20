"""股票预测聊天工具：复用现有分析任务创建流程。"""

from __future__ import annotations

from typing import Any, Callable

from services.chat_models import Action, ToolResult
from services.symbol_service import normalize_symbol, validate_symbol_for_analysis
from services.tools import ToolContext, missing_parameters


class StockPredictionTool:
    name = "stock_prediction"
    description = "运行多分析师股票预测，返回决策摘要、置信度和价格走势"
    required_parameters = ("stockCode", "analysisDate")

    def __init__(
        self,
        start_task: Callable[..., str],
        validate: Callable[..., str] | None = None,
    ):
        self._start_task = start_task
        self._validate = validate or (
            lambda stock_code, analysis_date: validate_symbol_for_analysis(
                stock_code,
                analysis_date,
            )
        )

    def missing_parameters(self, arguments: dict[str, Any]) -> list[str]:
        return missing_parameters(self.required_parameters, arguments)

    def execute(self, arguments: dict[str, Any], context: ToolContext | None) -> ToolResult:
        stock_code = normalize_symbol(str(arguments["stockCode"]))
        analysis_date = str(arguments["analysisDate"]).strip()
        self._validate(stock_code, analysis_date)
        background_tasks = context.background_tasks if context is not None else None
        task_id = self._start_task(stock_code, analysis_date, background_tasks)
        return ToolResult(
            tool=self.name,
            status="running",
            summary=(
                f"{stock_code} 在 {analysis_date} 的预测任务已启动，"
                "正在运行多分析师决策流程。"
            ),
            data={
                "taskId": task_id,
                "stockCode": stock_code,
                "analysisDate": analysis_date,
            },
            actions=[
                Action(type="navigate", label="查看完整分析", target="/dashboard"),
            ],
        )
