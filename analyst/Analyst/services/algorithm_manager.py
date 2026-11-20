"""可信本地实现、持久化算法定义和运行注册表的统一管理。"""

from __future__ import annotations

import importlib
import json
import math
import os
import pkgutil
import re
import tempfile
from pathlib import Path
from threading import RLock
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from services.chat_models import ToolResult
from services.http_tool_config import HttpToolConfig
from services.tool_registry import ToolRegistry
from services.tools import Tool, ToolContext, missing_parameters
from services.tools.http_tool import HttpTool


class HttpSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    url: str
    method: Literal["GET", "POST"] = "POST"
    timeout_seconds: float = Field(default=10, gt=0, le=300)
    request_mapping: dict[str, str] = Field(default_factory=dict)
    response_mapping: dict[str, str] = Field(default_factory=dict)
    summary_field: str | None = None


class DuplicateAlgorithmError(ValueError):
    pass


class AlgorithmDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=r"^[a-zA-Z][a-zA-Z0-9_-]{0,63}$")
    description: str = Field(min_length=1, max_length=2000)
    required_parameters: list[str] = Field(default_factory=list, max_length=50)
    kind: Literal["python", "http"]
    local_tool: str | None = None
    http: HttpSettings | None = None

    @model_validator(mode="after")
    def validate_definition(self):
        self.description = self.description.strip()
        if not self.description:
            raise ValueError("算法描述不能为空")
        if self.name in {"general_chat", "local-tools"}:
            raise ValueError(f"{self.name} 是保留名称")
        if len(set(self.required_parameters)) != len(self.required_parameters):
            raise ValueError("必填参数不能重复")
        if any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", p) for p in self.required_parameters):
            raise ValueError("参数名必须由字母、数字、下划线组成，且不能以数字开头")
        if self.kind == "python" and (not self.local_tool or self.http is not None):
            raise ValueError("Python 算法必须选择本地实现，不能配置 HTTP")
        if self.kind == "http" and (self.http is None or self.local_tool is not None):
            raise ValueError("HTTP 算法必须提供 HTTP 配置，不能选择本地实现")
        return self


class RegisteredTool:
    """使管理元数据、参数检查和实现返回值遵循同一契约。"""

    def __init__(self, definition: AlgorithmDefinition, implementation: Tool):
        self.name = definition.name
        self.description = definition.description
        self.required_parameters = tuple(definition.required_parameters)
        self._implementation = implementation

    def missing_parameters(self, arguments: dict[str, Any]) -> list[str]:
        return missing_parameters(self.required_parameters, arguments)

    def execute(self, arguments: dict[str, Any], context: ToolContext | None) -> ToolResult:
        missing = self.missing_parameters(arguments)
        if missing:
            raise ValueError("缺少必填参数：" + ", ".join(missing))
        result = self._implementation.execute(arguments, context)
        if not isinstance(result, ToolResult):
            raise TypeError("算法必须返回 ToolResult")
        return result.model_copy(update={"tool": self.name})


def discover_local_tools(builtins: dict[str, Tool]) -> dict[str, Tool]:
    """仅加载服务端可信插件包，不接收客户端模块路径。"""
    from services.tools import plugins

    tools = dict(builtins)
    for entry in sorted(pkgutil.iter_modules(plugins.__path__), key=lambda item: item.name):
        if entry.name.startswith("_"):
            continue
        module = importlib.import_module(f"{plugins.__name__}.{entry.name}")
        tool = module.build_tool()
        if tool.name in tools:
            raise ValueError(f"Duplicate local tool: {tool.name}")
        tools[tool.name] = tool
    for key, tool in tools.items():
        if not callable(getattr(tool, "execute", None)):
            raise ValueError(f"本地算法 {key} 未实现 execute")
        AlgorithmDefinition(name=key, description=tool.description, required_parameters=list(tool.required_parameters), kind="python", local_tool=key)
    return tools


class AlgorithmManager:
    def __init__(self, path: Path, local_tools: dict[str, Tool], *, registry: ToolRegistry | None = None, defaults: list[dict] | None = None):
        self.path = Path(path)
        self.local_tools = dict(local_tools)
        self.registry = registry if registry is not None else ToolRegistry()
        self._lock = RLock()
        if self.path.exists():
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or payload.get("version") != 1 or not isinstance(payload.get("algorithms"), list):
                raise ValueError("算法配置文件格式无效")
            raw = payload["algorithms"]
        else:
            raw = defaults or []
        self._definitions, tools = self._prepare(raw)
        self.registry.replace(tools)

    def _prepare(self, raw: list[dict]) -> tuple[dict[str, AlgorithmDefinition], list[Tool]]:
        definitions = {}
        tools = []
        for item in raw:
            definition = AlgorithmDefinition.model_validate(item)
            if definition.name in definitions:
                raise ValueError(f"Duplicate tool name: {definition.name}")
            if definition.kind == "python":
                implementation = self.local_tools.get(definition.local_tool)
                if implementation is None:
                    raise ValueError("未知本地算法实现")
                if not set(implementation.required_parameters) <= set(definition.required_parameters):
                    raise ValueError("不能移除本地实现的必填参数")
            else:
                settings = definition.http.model_dump()
                if not math.isfinite(settings["timeout_seconds"]):
                    raise ValueError("超时时间必须为有限数值")
                implementation = HttpTool(HttpToolConfig(name=definition.name, description=definition.description, required_parameters=tuple(definition.required_parameters), **settings))
            definitions[definition.name] = definition
            tools.append(RegisteredTool(definition, implementation))
        return definitions, tools

    def list(self) -> list[dict]:
        with self._lock:
            return [item.model_dump() for item in self._definitions.values()]

    def get(self, name: str) -> dict:
        with self._lock:
            if name not in self._definitions:
                raise KeyError(f"Unknown tool: {name}")
            return self._definitions[name].model_dump()

    def available_local_tools(self) -> list[dict]:
        return [{"name": key, "description": tool.description, "required_parameters": list(tool.required_parameters)} for key, tool in self.local_tools.items()]

    def create(self, payload: dict) -> dict:
        definition = AlgorithmDefinition.model_validate(payload)
        with self._lock:
            if definition.name in self._definitions:
                raise DuplicateAlgorithmError(f"算法 {definition.name} 已存在")
            self._save([*self.list(), definition.model_dump()])
            return self.get(definition.name)

    def update(self, name: str, payload: dict) -> dict:
        definition = AlgorithmDefinition.model_validate(payload)
        with self._lock:
            self.get(name)
            if definition.name != name:
                raise ValueError("算法名称不能修改")
            self._save([definition.model_dump() if item["name"] == name else item for item in self.list()])
            return self.get(name)

    def delete(self, name: str) -> None:
        with self._lock:
            self.get(name)
            self._save([item for item in self.list() if item["name"] != name])

    def _save(self, raw: list[dict]) -> None:
        definitions, tools = self._prepare(raw)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent, prefix=f".{self.path.name}.", suffix=".tmp", delete=False) as stream:
                temp_path = Path(stream.name)
                json.dump({"version": 1, "algorithms": raw}, stream, ensure_ascii=False, indent=2, allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_path, self.path)
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
        self._definitions = definitions
        self.registry.replace(tools)
