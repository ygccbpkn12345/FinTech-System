from services.chat_models import ChatMessage, ToolResult


def test_parameter_request_serializes_missing_parameters():
    message = ChatMessage.parameter_request(
        content="希望分析哪个交易日？",
        tool="stock_prediction",
        missing_parameters=["analysisDate"],
    )

    payload = message.model_dump()

    assert payload["type"] == "parameter_request"
    assert payload["tool"] == "stock_prediction"
    assert payload["missingParameters"] == ["analysisDate"]


def test_tool_result_has_stable_frontend_contract():
    result = ToolResult(
        tool="stock_prediction",
        status="completed",
        summary="建议谨慎持有",
        data={"confidence": 0.62},
        visualizations=[],
        actions=[],
    )

    assert result.model_dump()["data"]["confidence"] == 0.62
