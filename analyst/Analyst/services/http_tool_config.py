"""服务端静态的 HTTP 工具配置：目标地址只能来自这里。"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from urllib.parse import urlparse


SUPPORTED_METHODS = ("GET", "POST")


@dataclass(frozen=True)
class HttpToolConfig:
    name: str
    description: str
    url: str
    method: str = "POST"
    timeout_seconds: float = 10.0
    required_parameters: tuple[str, ...] = ("query",)
    request_mapping: dict[str, str] = field(default_factory=dict)
    response_mapping: dict[str, str] = field(default_factory=dict)
    summary_field: str | None = None

    def __post_init__(self) -> None:
        method = str(self.method).upper()
        if method not in SUPPORTED_METHODS:
            raise ValueError(f"不支持的 HTTP method: {self.method}")
        object.__setattr__(self, "method", method)

        parsed = urlparse(str(self.url))
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError(f"HTTP 工具地址必须是 http(s) URL: {self.url}")

        if not str(self.name).strip():
            raise ValueError("HTTP 工具必须有名称")
        if not math.isfinite(float(self.timeout_seconds)) or float(self.timeout_seconds) <= 0:
            raise ValueError("HTTP 工具超时时间必须为正数")
