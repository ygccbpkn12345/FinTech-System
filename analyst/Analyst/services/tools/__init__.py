"""聊天工具包：把现有能力封装成编排器可调用的工具。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from services.chat_models import ToolResult


@dataclass(frozen=True)
class ToolContext:
    """一次工具执行所需的请求级上下文。"""

    background_tasks: Any = None


class Tool(Protocol):
    """所有本地/HTTP 算法共同遵循的最小契约。"""

    name: str
    description: str
    required_parameters: tuple[str, ...]

    def execute(self, arguments: dict[str, Any], context: ToolContext | None) -> ToolResult: ...


def missing_parameters(required: tuple[str, ...], arguments: dict[str, Any]) -> list[str]:
    return [
        name for name in required
        if arguments.get(name) is None
        or (isinstance(arguments.get(name), str) and not arguments[name].strip())
    ]
