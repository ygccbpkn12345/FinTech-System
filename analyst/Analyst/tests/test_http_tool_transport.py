import httpx
import pytest

from services.tools.http_tool import build_http_tool


def test_get_uses_query_parameters_and_fixed_url():
    def respond(request):
        assert request.url.host == "algorithm.example"
        assert request.url.params["question"] == "hello"
        assert request.content == b""
        return httpx.Response(200, json={"answer": "ok"})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        tool = build_http_tool(url="https://algorithm.example/run", method="GET", client=client, request_mapping={"query": "question"})
        assert tool.execute({"query": "hello", "url": "https://other.invalid"}, None).data == {"answer": "ok"}


def test_http_required_parameter_validation_before_request():
    def respond(request):
        pytest.fail("Missing parameters must not trigger HTTP")

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        tool = build_http_tool(url="https://algorithm.example/run", client=client)
        with pytest.raises(ValueError, match="query"):
            tool.execute({}, None)


def test_http_accepts_false_and_zero_arguments():
    tool = build_http_tool(url="https://algorithm.example/run")
    assert tool.missing_parameters({"query": 0}) == []
    assert tool.missing_parameters({"query": False}) == []
