"""聊天意图路由：大模型优先，关键词规则兜底。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable

from pydantic import BaseModel, Field

from services.symbol_service import STOCK_NAMES


GENERAL_CHAT = "general_chat"
STOCK_PREDICTION = "stock_prediction"
MARKET_DATA_CRAWLER = "market_data_crawler"

_STOCK_CODE = re.compile(r"(?<!\d)(\d{6})(?!\d)")
_ISO_DATE = re.compile(r"(?<!\d)(\d{4}-\d{2}-\d{2})(?!\d)")
_JSON_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)

_CRAWLER_KEYWORDS = ("爬取", "抓取", "更新数据", "更新行情", "更新行情数据", "下载数据")
_PREDICTION_KEYWORDS = (
    "预测",
    "走势",
    "买入",
    "卖出",
    "分析股票",
    "股票分析",
    "股价",
    "行情分析",
)


class RouteDecision(BaseModel):
    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    confidence: float = 0.0


@dataclass(frozen=True)
class _ToolSpec:
    name: str
    description: str
    required_parameters: tuple[str, ...] = ()


DEFAULT_TOOLS: tuple[_ToolSpec, ...] = (
    _ToolSpec(
        STOCK_PREDICTION,
        "运行多分析师股票预测，返回决策摘要、置信度和价格走势图",
        ("stockCode", "analysisDate"),
    ),
    _ToolSpec(
        MARKET_DATA_CRAWLER,
        "抓取或更新本地行情、新闻和财务数据",
        ("stockCode",),
    ),
)


class ChatRouter:
    def __init__(self, model: Any = None, tools: Iterable[Any] | None = None):
        self._model = model
        if tools is None:
            self._tools = {tool.name: tool for tool in DEFAULT_TOOLS}
        else:
            self._tools = {tool.name: tool for tool in tools}

    def route(
        self,
        message: str,
        history: Iterable[Any] | None = None,
    ) -> RouteDecision:
        try:
            decision = self._route_with_model(message, list(history or []))
        except Exception:
            decision = None
        if decision is not None:
            return decision
        return self._fallback_route(message)

    def extract_arguments(self, text: str) -> dict[str, str]:
        arguments: dict[str, str] = {}
        code = self._find_stock_code(text)
        if code:
            arguments["stockCode"] = code
        analysis_date = self._find_date(text)
        if analysis_date:
            arguments["analysisDate"] = analysis_date
        return arguments

    def _route_with_model(
        self,
        message: str,
        history: list[Any],
    ) -> RouteDecision | None:
        if self._model is None:
            return None
        response = self._model.invoke(self._build_messages(message, history))
        payload = self._parse_payload(getattr(response, "content", response))
        if payload is None:
            return None
        tool = payload.get("tool")
        arguments = payload.get("arguments")
        if not isinstance(tool, str) or not isinstance(arguments, dict):
            return None
        if tool != GENERAL_CHAT and tool not in self._tools:
            return None
        clean_arguments = {
            str(key): value
            for key, value in arguments.items()
            if value is not None and str(value).strip()
        }
        confidence = payload.get("confidence", 0.0)
        if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
            confidence = 0.0
        return RouteDecision(
            tool=tool,
            arguments=clean_arguments,
            confidence=max(0.0, min(1.0, float(confidence))),
        )

    def _build_messages(self, message: str, history: list[Any]) -> list[dict[str, str]]:
        tool_lines = [
            f"- {GENERAL_CHAT}: 普通聊天，不需要业务工具",
        ]
        for tool in self._tools.values():
            required = ", ".join(tool.required_parameters) or "无"
            tool_lines.append(
                f"- {tool.name}: {tool.description}（必填参数：{required}）"
            )
        system = (
            "你是 AnalystVerse 的意图路由器。"
            "只输出一个 JSON 对象，格式为 "
            '{"tool": "<工具名>", "arguments": {<参数名与值>}, "confidence": <0 到 1>}。'
            "只能从下列工具中选择，不要输出 JSON 以外的内容。\n"
            + "\n".join(tool_lines)
        )
        transcript = []
        for item in history[-6:]:
            role = getattr(item, "role", None) or (
                item.get("role") if isinstance(item, dict) else None
            )
            content = getattr(item, "content", None) or (
                item.get("content") if isinstance(item, dict) else None
            )
            if role in {"user", "assistant"} and isinstance(content, str):
                transcript.append(f"{role}: {content}")
        user = message
        if transcript:
            user = "最近的对话：\n" + "\n".join(transcript) + f"\n\n本轮用户消息：{message}"
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

    def _parse_payload(self, raw: Any) -> dict[str, Any] | None:
        if not isinstance(raw, str):
            return None
        text = raw.strip()
        fenced = _JSON_FENCE.search(text)
        if fenced:
            text = fenced.group(1).strip()
        try:
            payload = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            return None
        if not isinstance(payload, dict):
            return None
        return payload

    def _fallback_route(self, message: str) -> RouteDecision:
        arguments = self.extract_arguments(message)
        if MARKET_DATA_CRAWLER in self._tools and self._is_crawler_request(message):
            return RouteDecision(
                tool=MARKET_DATA_CRAWLER,
                arguments=arguments,
                confidence=0.4,
            )
        if STOCK_PREDICTION in self._tools and (self._matches(message, _PREDICTION_KEYWORDS) or "stockCode" in arguments):
            return RouteDecision(
                tool=STOCK_PREDICTION,
                arguments=arguments,
                confidence=0.4,
            )
        return RouteDecision(tool=GENERAL_CHAT, arguments={}, confidence=0.2)

    def _matches(self, message: str, keywords: tuple[str, ...]) -> bool:
        return any(keyword in message for keyword in keywords)

    def _is_crawler_request(self, message: str) -> bool:
        if self._matches(message, _CRAWLER_KEYWORDS):
            return True
        return "更新" in message and ("数据" in message or "行情" in message)

    def _find_stock_code(self, text: str) -> str | None:
        match = _STOCK_CODE.search(text)
        if match:
            return match.group(1)
        for code, name in STOCK_NAMES.items():
            if name in text:
                return code
        return None

    def _find_date(self, text: str) -> str | None:
        for match in _ISO_DATE.finditer(text):
            value = match.group(1)
            try:
                datetime.strptime(value, "%Y-%m-%d")
            except ValueError:
                continue
            return value
        return None
