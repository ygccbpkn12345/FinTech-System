"""Registry for chat tools exposed to the routing layer."""

from __future__ import annotations

from threading import RLock
from typing import Any, Iterable

from services.tools import Tool


class ToolRegistry:
    def __init__(self, tools: Iterable[Tool] = ()):
        self._lock = RLock()
        with self._lock:
            self._tools = {}
            for tool in tools:
                if tool.name in self._tools:
                    raise ValueError(f"Duplicate tool name: {tool.name}")
                self._tools[tool.name] = tool

    def snapshot(self) -> tuple[Tool, ...]:
        with self._lock:
            return tuple(self._tools.values())

    def register(self, tool: Tool) -> None:
        with self._lock:
            if tool.name in self._tools:
                raise ValueError(f"Duplicate tool name: {tool.name}")
            self._tools[tool.name] = tool

    def update(self, name: str, tool: Tool) -> None:
        with self._lock:
            self.get(name)
            if tool.name != name:
                raise ValueError("工具名称不能修改")
            self._tools[name] = tool

    def remove(self, name: str) -> None:
        with self._lock:
            self.get(name)
            del self._tools[name]

    def replace(self, tools: Iterable[Tool]) -> None:
        replacement = ToolRegistry(tools)
        with self._lock:
            self._tools = replacement._tools

    def get(self, name: str) -> Any:
        with self._lock:
            try:
                return self._tools[name]
            except KeyError:
                raise KeyError(f"Unknown tool: {name}") from None

    def descriptions(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "required_parameters": list(tool.required_parameters),
                }
                for tool in self._tools.values()
            ]
