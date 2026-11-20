from __future__ import annotations

from dataclasses import dataclass, field

from services.tool_conversation import run_tool_conversation


@dataclass
class FakeMessage:
    content: str = ""
    tool_calls: list[dict] = field(default_factory=list)


class FakeChain:
    def __init__(self):
        self.calls = 0

    def invoke(self, messages):
        self.calls += 1
        if self.calls == 1:
            return FakeMessage(tool_calls=[{
                "id": "balance-1", "name": "get_balance_sheet", "args": {},
            }])
        if self.calls == 2:
            return FakeMessage(tool_calls=[
                {"id": "income-1", "name": "get_Income_Statement", "args": {}},
                {"id": "cash-1", "name": "get_Cash_Flow_Statement", "args": {}},
            ])
        return FakeMessage(content="**建议决策**：[观望]\n- **置信度**：0.6\n- **报告**：财务数据完整。")


class FakeTool:
    def __init__(self, name):
        self.name = name

    def invoke(self, args):
        return f"{self.name} data"


def test_multi_round_tool_calls_produce_nonempty_fundamentals_report():
    chain = FakeChain()
    tools = [
        FakeTool("get_balance_sheet"),
        FakeTool("get_Income_Statement"),
        FakeTool("get_Cash_Flow_Statement"),
    ]

    result = run_tool_conversation(
        chain,
        [],
        tools,
        tool_message_factory=lambda content, tool_call_id: FakeMessage(content=content),
    )

    assert chain.calls == 3
    assert "财务数据完整" in result.content
