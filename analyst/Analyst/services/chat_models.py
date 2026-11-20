from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


MessageType = Literal[
    "text",
    "parameter_request",
    "confirmation",
    "tool_progress",
    "result",
    "error",
]


class Action(BaseModel):
    type: Literal["navigate", "retry", "confirm", "cancel"]
    label: str
    target: str | None = None
    value: str | None = None


class Visualization(BaseModel):
    type: Literal["line", "bar", "metric"]
    title: str
    x: list[str] = Field(default_factory=list)
    series: list[dict[str, Any]] = Field(default_factory=list)


class ToolResult(BaseModel):
    tool: str
    status: Literal["completed", "partial", "failed", "running"]
    summary: str
    data: dict[str, Any] = Field(default_factory=dict)
    visualizations: list[Visualization] = Field(default_factory=list)
    actions: list[Action] = Field(default_factory=list)


class ChatMessage(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    role: Literal["user", "assistant", "tool"]
    type: MessageType
    content: str
    tool: str | None = None
    missing_parameters: list[str] = Field(
        default_factory=list,
        alias="missingParameters",
    )
    task_id: str | None = Field(default=None, alias="taskId")
    result: ToolResult | None = None

    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)

    @classmethod
    def parameter_request(
        cls,
        *,
        content: str,
        tool: str,
        missing_parameters: list[str],
    ) -> "ChatMessage":
        return cls(
            role="assistant",
            type="parameter_request",
            content=content,
            tool=tool,
            missingParameters=missing_parameters,
        )
