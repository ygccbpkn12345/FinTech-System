"""Shared multi-round tool conversation loop for analyst agents."""

from __future__ import annotations


def run_tool_conversation(
    chain,
    initial_messages,
    tools,
    *,
    tool_message_factory,
    max_rounds: int = 6,
):
    messages = list(initial_messages)
    tools_by_name = {tool.name: tool for tool in tools}

    for _ in range(max_rounds):
        result = chain.invoke(messages)
        messages.append(result)
        tool_calls = list(getattr(result, "tool_calls", None) or [])
        if not tool_calls:
            return result

        for tool_call in tool_calls:
            name = tool_call["name"]
            tool = tools_by_name.get(name)
            if tool is None:
                content = f"错误: 找不到工具 {name}"
            else:
                try:
                    content = str(tool.invoke(tool_call.get("args", {})))
                except Exception as exc:
                    content = f"工具执行错误: {exc}"
            messages.append(tool_message_factory(content, tool_call["id"]))

    raise RuntimeError(f"分析师连续 {max_rounds} 轮请求工具，未生成最终报告")
