"""聊天编排：会话状态、意图路由、参数补全与工具执行。"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from contextvars import ContextVar
import json
import re
from typing import Any, Callable, Iterable

from pydantic import BaseModel, ConfigDict, Field

from services.chat_models import Action, ChatMessage, ToolResult
from services.chat_router import (
    GENERAL_CHAT,
    MARKET_DATA_CRAWLER,
    STOCK_PREDICTION,
    ChatRouter,
)
from services.chat_session_store import ChatSession, ChatSessionStore
from services.tool_registry import ToolRegistry
from services.tools import ToolContext, missing_parameters
from services.tools.http_tool import ToolExecutionError


PARAMETER_PROMPTS = {
    "stockCode": "请告诉我要分析的股票名称或六位代码。",
    "analysisDate": "希望分析哪个交易日？（格式：YYYY-MM-DD）",
}

GENERAL_CHAT_SYSTEM_PROMPT = (
    "你是 AnalystVerse 的股票分析助手，用简洁、专业的中文回答。"
    "如果用户想预测股票或更新行情数据，提醒他可以提供股票名称和交易日。"
)

GENERAL_CHAT_FAILURE = "模型暂时不可用，请稍后重试。"

AFFIRMATIVE_REPLIES = {"确认", "确定", "是", "好", "好的", "同意", "更新", "继续"}
NEGATIVE_REPLIES = {"取消", "不用", "算了", "否", "不要"}

CANCELLED_MESSAGE = "已取消本次操作。"
CRAWL_FAILURE_MESSAGE = "数据更新失败，请稍后重试。"


class ChatResponse(BaseModel):
    conversation_id: str = Field(alias="conversationId")
    messages: list[ChatMessage] = Field(default_factory=list)

    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)


def _default_model_factory() -> Any:
    from services.runtime_config import build_chat_model

    return build_chat_model()


class ChatOrchestrator:
    def __init__(
        self,
        tools: Iterable[Any] | ToolRegistry,
        *,
        store: ChatSessionStore | None = None,
        model_factory: Callable[[], Any] | None = None,
    ):
        self._registry = tools if isinstance(tools, ToolRegistry) else ToolRegistry(tools)
        self._turn_registry = ContextVar("chat_tool_registry", default=None)
        self.store = store or ChatSessionStore()
        self._model_factory = model_factory or _default_model_factory

    def handle(
        self,
        conversation_id: str | None,
        message: str,
        *,
        background_tasks: Any = None,
    ) -> ChatResponse:
        # 每轮使用一致快照；CRUD 在下一轮生效，不中断正在执行的算法。
        token = self._turn_registry.set(ToolRegistry(self._registry.snapshot()))
        try:
            return self._handle(conversation_id, message, background_tasks=background_tasks)
        finally:
            self._turn_registry.reset(token)

    @property
    def _available_tools(self) -> ToolRegistry:
        return self._turn_registry.get() or self._registry

    def _handle(
        self,
        conversation_id: str | None,
        message: str,
        *,
        background_tasks: Any = None,
    ) -> ChatResponse:
        text = (message or "").strip()
        session = self._load_or_create(conversation_id)
        self._append(
            session.id,
            ChatMessage(role="user", type="text", content=text),
        )

        model = self._model_factory()
        router = ChatRouter(model, tools=self._available_tools.snapshot())
        context = ToolContext(background_tasks=background_tasks)

        messages = None
        if session.pending_confirmation:
            messages = self._handle_confirmation(session, text, context)
        if messages is None:
            if session.pending_tool:
                messages = self._continue_pending_tool(
                    session,
                    text,
                    router,
                    context,
                )
            else:
                messages = self._route_and_respond(
                    session,
                    text,
                    router,
                    model,
                    context,
                )

        for produced in messages:
            self._append(session.id, produced)
        return ChatResponse(conversationId=session.id, messages=messages)

    def _route_and_respond(
        self,
        session: ChatSession,
        text: str,
        router: ChatRouter,
        model: Any,
        context: ToolContext,
    ) -> list[ChatMessage]:
        route = router.route(text, session.messages)
        if route.tool == GENERAL_CHAT:
            return [self._general_reply(model, session.messages, text)]

        try:
            tool = self._available_tools.get(route.tool)
        except KeyError:
            return [self._tool_error(session, route.tool, "该算法已删除或暂不可用，请重新选择。")]
        arguments = dict(route.arguments)
        for key, value in router.extract_arguments(text).items():
            arguments.setdefault(key, value)
        return self._run_tool(session, tool, arguments, context)

    def _continue_pending_tool(
        self,
        session: ChatSession,
        text: str,
        router: ChatRouter,
        context: ToolContext,
    ) -> list[ChatMessage]:
        try:
            tool = self._available_tools.get(session.pending_tool)
        except KeyError:
            return [self._tool_error(session, session.pending_tool, "该算法已删除或暂不可用，请重新选择。")]
        arguments = {
            **session.pending_arguments,
            **router.extract_arguments(text),
        }
        missing = missing_parameters(tuple(tool.required_parameters), arguments)
        # 只补当前工具的参数，模型不能在补参阶段切换工具。
        if missing:
            route = router.route(
                f"正在补充工具 {tool.name} 的参数 {', '.join(missing)}。用户回复：{text}",
                session.messages,
            )
            if route.tool == tool.name:
                arguments.update(route.arguments)
            scalar_reply = text
            try:
                explicit = json.loads(text)
                if not isinstance(explicit, dict):
                    scalar_reply = explicit
                    explicit = {}
            except (ValueError, TypeError):
                explicit = dict(re.findall(r'([A-Za-z_][A-Za-z0-9_]*)\s*=\s*("[^"]*"|[^\s,;，；]+)', text))
                explicit = {key: value.strip('"') for key, value in explicit.items()}
            if isinstance(explicit, dict):
                arguments.update({key: value for key, value in explicit.items() if key in tool.required_parameters})
            remaining = missing_parameters(tuple(tool.required_parameters), arguments)
            if remaining and not explicit and remaining == missing:
                parameter = remaining[0]
                if tool.name not in {STOCK_PREDICTION, MARKET_DATA_CRAWLER} or parameter not in {"stockCode", "analysisDate"}:
                    arguments[parameter] = scalar_reply
        return self._run_tool(session, tool, arguments, context)

    def _run_tool(
        self,
        session: ChatSession,
        tool: Any,
        arguments: dict[str, Any],
        context: ToolContext,
        *,
        allow_confirmation: bool = True,
    ) -> list[ChatMessage]:
        missing = missing_parameters(tuple(tool.required_parameters), arguments)
        if missing:
            self.store.set_pending(session.id, tool.name, arguments)
            return [
                ChatMessage.parameter_request(
                    content=self._parameter_prompt(missing),
                    tool=tool.name,
                    missing_parameters=missing,
                )
            ]
        return self._execute_tool(
            session,
            tool,
            arguments,
            context,
            allow_confirmation=allow_confirmation,
        )

    def _execute_tool(
        self,
        session: ChatSession,
        tool: Any,
        arguments: dict[str, Any],
        context: ToolContext,
        *,
        allow_confirmation: bool = True,
    ) -> list[ChatMessage]:
        try:
            result = tool.execute(arguments, context)
        except ToolExecutionError as exc:
            return [self._tool_error(session, tool.name, str(exc))]
        except ValueError as exc:
            if (
                allow_confirmation
                and tool.name == STOCK_PREDICTION
                and self._has_crawler()
            ):
                return [self._crawl_confirmation(session, tool, arguments, exc)]
            return [self._tool_error(session, tool.name, str(exc))]
        except Exception:
            return [self._tool_error(session, tool.name, "工具执行失败，请稍后重试。")]

        self.store.clear_pending(session.id)
        task_id = result.data.get("taskId")
        if isinstance(task_id, str) and task_id:
            self.store.set_task_id(session.id, task_id)

        if result.status == "running":
            message_type = "tool_progress"
        elif result.status == "failed":
            message_type = "error"
        else:
            message_type = "result"

        return [
            ChatMessage(
                role="tool" if result.status != "failed" else "assistant",
                type=message_type,
                content=result.summary,
                tool=tool.name,
                task_id=task_id if isinstance(task_id, str) else None,
                result=result,
            )
        ]

    def _handle_confirmation(
        self,
        session: ChatSession,
        text: str,
        context: ToolContext,
    ) -> list[ChatMessage] | None:
        confirmation = session.pending_confirmation or {}
        if self._is_affirmative(text):
            return self._execute_confirmation(session, confirmation, context)

        self.store.clear_pending_confirmation(session.id)
        if self._is_negative(text):
            self.store.clear_pending(session.id)
            return [
                ChatMessage(
                    role="assistant",
                    type="text",
                    content=CANCELLED_MESSAGE,
                )
            ]
        return None

    def _execute_confirmation(
        self,
        session: ChatSession,
        confirmation: dict[str, Any],
        context: ToolContext,
    ) -> list[ChatMessage]:
        self.store.clear_pending_confirmation(session.id)
        tool_name = str(confirmation.get("tool") or MARKET_DATA_CRAWLER)
        try:
            tool = self._available_tools.get(tool_name)
        except KeyError:
            self.store.clear_pending(session.id)
            return [self._tool_error(session, tool_name, CRAWL_FAILURE_MESSAGE)]

        arguments = dict(confirmation.get("arguments") or {})
        try:
            result = tool.execute(arguments, context)
        except Exception:
            self.store.clear_pending(session.id)
            return [self._tool_error(session, tool.name, CRAWL_FAILURE_MESSAGE)]

        if result.status == "failed":
            self.store.clear_pending(session.id)
            return [self._tool_error(session, tool.name, result.summary)]

        messages: list[ChatMessage] = []
        if result.status == "partial":
            messages.append(
                ChatMessage(
                    role="tool",
                    type="result",
                    content=result.summary,
                    tool=tool.name,
                    result=result,
                )
            )

        if not session.pending_tool:
            if not messages:
                messages.append(
                    ChatMessage(
                        role="tool",
                        type="result",
                        content=result.summary,
                        tool=tool.name,
                        result=result,
                    )
                )
            return messages

        try:
            prediction_tool = self._available_tools.get(session.pending_tool)
        except KeyError:
            return [*messages, self._tool_error(session, session.pending_tool, "该算法已删除或暂不可用，请重新选择。")]
        messages.extend(
            self._run_tool(
                session,
                prediction_tool,
                session.pending_arguments,
                context,
                allow_confirmation=False,
            )
        )
        return messages

    def _crawl_confirmation(
        self,
        session: ChatSession,
        tool: Any,
        arguments: dict[str, Any],
        error: Exception,
    ) -> ChatMessage:
        self.store.set_pending(session.id, tool.name, arguments)
        crawl_arguments = self._crawl_arguments(arguments)
        self.store.set_pending_confirmation(
            session.id,
            {"tool": MARKET_DATA_CRAWLER, "arguments": crawl_arguments},
        )
        summary = f"{error} 是否先更新行情数据？"
        return ChatMessage(
            role="assistant",
            type="confirmation",
            content=summary,
            tool=MARKET_DATA_CRAWLER,
            result=ToolResult(
                tool=MARKET_DATA_CRAWLER,
                status="partial",
                summary=summary,
                data={"crawlArguments": crawl_arguments},
                actions=[
                    Action(type="confirm", label="更新数据"),
                    Action(type="cancel", label="取消"),
                ],
            ),
        )

    def _crawl_arguments(self, arguments: dict[str, Any]) -> dict[str, str]:
        analysis_date = str(arguments.get("analysisDate") or "").strip()
        try:
            end = datetime.strptime(analysis_date, "%Y-%m-%d").date()
        except ValueError:
            end = date.today()
        start = end - timedelta(days=90)
        return {
            "stockCode": str(arguments.get("stockCode") or ""),
            "startDate": start.isoformat(),
            "endDate": end.isoformat(),
        }

    def _has_crawler(self) -> bool:
        try:
            self._available_tools.get(MARKET_DATA_CRAWLER)
        except KeyError:
            return False
        return True

    def _is_affirmative(self, text: str) -> bool:
        value = text.strip().lower()
        return value in AFFIRMATIVE_REPLIES or "确认" in value

    def _is_negative(self, text: str) -> bool:
        value = text.strip().lower()
        return value in NEGATIVE_REPLIES or "取消" in value or "算了" in value

    def _tool_error(
        self,
        session: ChatSession,
        tool_name: str,
        content: str,
    ) -> ChatMessage:
        self.store.clear_pending(session.id)
        return ChatMessage(
            role="assistant",
            type="error",
            content=content,
            tool=tool_name,
            result=ToolResult(
                tool=tool_name,
                status="failed",
                summary=content,
                actions=[Action(type="retry", label="重试")],
            ),
        )

    def _general_reply(
        self,
        model: Any,
        history: list[ChatMessage],
        text: str,
    ) -> ChatMessage:
        messages = [{"role": "system", "content": GENERAL_CHAT_SYSTEM_PROMPT}]
        for item in history[-8:]:
            if item.role in {"user", "assistant"} and item.type == "text":
                messages.append({"role": item.role, "content": item.content})
        messages.append({"role": "user", "content": text})
        try:
            response = model.invoke(messages)
            content = str(getattr(response, "content", "") or "").strip()
        except Exception:
            content = ""
        if not content:
            return ChatMessage(
                role="assistant",
                type="error",
                content=GENERAL_CHAT_FAILURE,
                tool=GENERAL_CHAT,
                result=ToolResult(
                    tool=GENERAL_CHAT,
                    status="failed",
                    summary=GENERAL_CHAT_FAILURE,
                    actions=[Action(type="retry", label="重试")],
                ),
            )
        return ChatMessage(role="assistant", type="text", content=content)

    def _parameter_prompt(self, missing: list[str]) -> str:
        return "\n".join(
            PARAMETER_PROMPTS.get(name, f"请补充参数 {name}。") for name in missing
        )

    def _load_or_create(self, conversation_id: str | None) -> ChatSession:
        if conversation_id:
            session = self.store.get(conversation_id)
            if session is not None:
                return session
        return self.store.create()

    def _append(self, session_id: str, message: ChatMessage) -> None:
        self.store.append_message(session_id, message)
