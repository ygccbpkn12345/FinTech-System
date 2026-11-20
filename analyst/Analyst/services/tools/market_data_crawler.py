"""行情数据爬虫聊天工具：与 /api/data/fetch 共用同一服务。"""

from __future__ import annotations

from typing import Any

from services.chat_models import Action, ToolResult
from services.market_data_crawler import (
    MarketDataCrawlerService,
    normalize_fetch_request,
)
from services.tools import ToolContext, missing_parameters


STATUS_MAP = {"ok": "completed", "partial": "partial", "error": "failed"}


class MarketDataCrawlerTool:
    name = "market_data_crawler"
    description = "抓取或更新本地行情、新闻和财务数据"
    required_parameters = ("stockCode",)

    def __init__(self, crawler: Any = None):
        self._crawler = crawler or MarketDataCrawlerService()

    def missing_parameters(self, arguments: dict[str, Any]) -> list[str]:
        return missing_parameters(self.required_parameters, arguments)

    def execute(
        self,
        arguments: dict[str, Any],
        context: ToolContext | None,
    ) -> ToolResult:
        payload = dict(arguments)
        payload.setdefault("stockCode", payload.get("symbol"))
        normalized = normalize_fetch_request(payload)
        raw = self._crawler.fetch(normalized)

        status = STATUS_MAP.get(str(raw.get("status")), "completed")
        summary = str(raw.get("message") or "行情数据更新完成")
        actions = (
            [Action(type="retry", label="重试")]
            if status == "failed"
            else [Action(type="navigate", label="查看数据状态", target="/settings")]
        )
        return ToolResult(
            tool=self.name,
            status=status,
            summary=summary,
            data=raw,
            actions=actions,
        )
