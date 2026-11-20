import json

from services.chat_router import ChatRouter


class BrokenModel:
    def invoke(self, _messages):
        raise TimeoutError("model timeout")


class StaticModel:
    def __init__(self, content):
        self.content = content
        self.calls = []

    def invoke(self, messages):
        self.calls.append(messages)
        return type("Response", (), {"content": self.content})()


class FakeTool:
    def __init__(self, name, description, required_parameters=()):
        self.name = name
        self.description = description
        self.required_parameters = tuple(required_parameters)


def test_keyword_fallback_routes_stock_prediction_when_model_fails():
    route = ChatRouter(BrokenModel()).route("帮我预测中兴通讯", [])

    assert route.tool == "stock_prediction"
    assert route.arguments["stockCode"] == "000063"


def test_keyword_fallback_routes_crawler_when_model_fails():
    route = ChatRouter(BrokenModel()).route("更新 000063 的行情数据", [])

    assert route.tool == "market_data_crawler"


def test_non_business_message_falls_back_to_general_chat():
    route = ChatRouter(BrokenModel()).route("你好，介绍一下自己", [])

    assert route.tool == "general_chat"


def test_model_route_selects_tool_arguments_and_confidence():
    model = StaticModel(
        json.dumps(
            {
                "tool": "stock_prediction",
                "arguments": {"stockCode": "000063", "analysisDate": "2024-01-03"},
                "confidence": 0.91,
            }
        )
    )

    route = ChatRouter(model).route("看看中兴通讯 2024-01-03 怎么走", [])

    assert route.tool == "stock_prediction"
    assert route.arguments == {
        "stockCode": "000063",
        "analysisDate": "2024-01-03",
    }
    assert route.confidence == 0.91


def test_prompt_lists_only_registered_tools():
    tool = FakeTool("market_data_crawler", "抓取行情数据", ("stockCode",))
    model = StaticModel(json.dumps({"tool": "market_data_crawler", "arguments": {}}))
    router = ChatRouter(model, tools=[tool])

    router.route("更新数据", [])

    prompt = "\n".join(item["content"] for item in model.calls[0])
    assert "抓取行情数据" in prompt
    assert "general_chat" in prompt
    assert "stock_prediction" not in prompt


def test_invalid_model_payload_falls_back_to_keywords():
    route = ChatRouter(StaticModel("这不是 JSON")).route("预测中兴通讯", [])

    assert route.tool == "stock_prediction"
    assert route.arguments["stockCode"] == "000063"


def test_unknown_tool_from_model_falls_back_to_keywords():
    model = StaticModel(json.dumps({"tool": "drop_database", "arguments": {}}))

    route = ChatRouter(model).route("你好", [])

    assert route.tool == "general_chat"


def test_model_payload_inside_markdown_fence_is_accepted():
    payload = '```json\n{"tool": "stock_prediction", "arguments": {}}\n```'

    route = ChatRouter(StaticModel(payload)).route("预测中兴通讯", [])

    assert route.tool == "stock_prediction"


def test_non_object_arguments_fall_back_to_keywords():
    payload = json.dumps({"tool": "stock_prediction", "arguments": "000063"})

    route = ChatRouter(StaticModel(payload)).route("你好", [])

    assert route.tool == "general_chat"


def test_extract_arguments_reads_code_and_valid_date():
    router = ChatRouter(BrokenModel())

    assert router.extract_arguments("帮我分析 600519 在 2024-01-03 的走势") == {
        "stockCode": "600519",
        "analysisDate": "2024-01-03",
    }


def test_extract_arguments_drops_impossible_date():
    router = ChatRouter(BrokenModel())

    assert router.extract_arguments("2024-13-45 看看 000063") == {
        "stockCode": "000063"
    }


def test_extract_arguments_keeps_yesterdays_date_statement_ignored():
    router = ChatRouter(BrokenModel())

    assert router.extract_arguments("预测中兴通讯") == {"stockCode": "000063"}
