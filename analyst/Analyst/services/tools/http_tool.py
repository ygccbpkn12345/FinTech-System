"""可配置的通用 HTTP 工具：固定服务端地址，参数与响应按配置映射。"""

from __future__ import annotations

from typing import Any

import httpx

from services.chat_models import ToolResult
from services.http_tool_config import HttpToolConfig
from services.tools import ToolContext, missing_parameters


class ToolExecutionError(RuntimeError):
    """可安全展示给用户的工具执行错误。"""


class HttpTool:
    def __init__(self, config: HttpToolConfig, client: Any = None):
        self.config = config
        self.name = config.name
        self.description = config.description
        self.required_parameters = tuple(config.required_parameters)
        self._client = client

    def missing_parameters(self, arguments: dict[str, Any]) -> list[str]:
        return missing_parameters(self.required_parameters, arguments)

    def execute(
        self,
        arguments: dict[str, Any],
        context: ToolContext | None,
    ) -> ToolResult:
        missing = self.missing_parameters(arguments)
        if missing:
            raise ValueError("缺少必填参数：" + ", ".join(missing))
        payload = self._build_payload(arguments)
        response = self._call(payload)
        data = self._parse_response(response)
        mapped = self._map_response(data)
        return ToolResult(
            tool=self.name,
            status="completed",
            summary=self._summarize(mapped),
            data=mapped,
        )

    def _build_payload(self, arguments: dict[str, Any]) -> dict[str, Any]:
        allowed = set(self.required_parameters) | set(self.config.request_mapping)
        payload = {}
        for key, value in arguments.items():
            if key not in allowed:
                continue
            if value is None or (isinstance(value, str) and not value.strip()):
                continue
            payload[self.config.request_mapping.get(key, key)] = value
        return payload

    def _call(self, payload: dict[str, Any]) -> Any:
        options = {"params" if self.config.method == "GET" else "json": payload}
        try:
            if self._client is None:
                # 复用 httpx 的临时客户端，避免每次调用都遗留一个未关闭的 Client
                return httpx.request(
                    self.config.method,
                    self.config.url,
                    **options,
                    timeout=self.config.timeout_seconds,
                )
            return self._client.request(
                self.config.method,
                self.config.url,
                **options,
                timeout=self.config.timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            raise ToolExecutionError(f"{self.name} 请求超时，请稍后重试") from exc
        except Exception as exc:
            raise ToolExecutionError(f"{self.name} 请求失败，请稍后重试") from exc

    def _parse_response(self, response: Any) -> dict[str, Any]:
        status_code = getattr(response, "status_code", 0)
        if not 200 <= int(status_code) < 300:
            raise ToolExecutionError(
                f"{self.name} 返回异常状态码 {status_code}"
            )
        try:
            data = response.json()
        except Exception as exc:
            raise ToolExecutionError(f"{self.name} 返回了无效的 JSON") from exc
        if not isinstance(data, dict):
            raise ToolExecutionError(f"{self.name} 响应格式无效")
        return data

    def _map_response(self, data: dict[str, Any]) -> dict[str, Any]:
        if not self.config.response_mapping:
            return dict(data)
        return {
            target: self._read_path(data, source)
            for target, source in self.config.response_mapping.items()
        }

    def _read_path(self, data: dict[str, Any], path: str) -> Any:
        value: Any = data
        for segment in str(path).split("."):
            if not isinstance(value, dict) or segment not in value:
                return None
            value = value[segment]
        return value

    def _summarize(self, data: dict[str, Any]) -> str:
        if self.config.summary_field:
            value = self._read_path(data, self.config.summary_field)
            if value not in (None, ""):
                return str(value)
        return f"{self.name} 执行完成"


def build_http_tool(
    *,
    url: str,
    client: Any = None,
    name: str = "http_example",
    description: str = "通用 HTTP 工具",
    method: str = "POST",
    timeout_seconds: float = 10.0,
    required_parameters: tuple[str, ...] = ("query",),
    request_mapping: dict[str, str] | None = None,
    response_mapping: dict[str, str] | None = None,
    summary_field: str | None = None,
) -> HttpTool:
    config = HttpToolConfig(
        name=name,
        description=description,
        url=url,
        method=method,
        timeout_seconds=timeout_seconds,
        required_parameters=tuple(required_parameters),
        request_mapping=dict(request_mapping or {}),
        response_mapping=dict(response_mapping or {}),
        summary_field=summary_field,
    )
    return HttpTool(config, client=client)
