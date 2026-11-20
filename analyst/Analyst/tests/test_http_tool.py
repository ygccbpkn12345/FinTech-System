import json

import httpx
import pytest

from services.http_tool_config import HttpToolConfig
from services.tools.http_tool import ToolExecutionError, build_http_tool


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeHttp:
    def __init__(self):
        self.last_url = None
        self.last_method = None
        self.last_json = None
        self.last_timeout = None
        self.response = {}
        self.status_code = 200
        self.error = None

    def request(self, method, url, json=None, timeout=None, params=None):
        self.last_url = url
        self.last_method = method
        self.last_json = json
        self.last_timeout = timeout
        if self.error is not None:
            raise self.error
        return FakeResponse(self.status_code, self.response)


@pytest.fixture
def fake_http():
    return FakeHttp()


def build_tool(url="http://127.0.0.1:9100/predict", client=None, **kwargs):
    return build_http_tool(url=url, client=client, **kwargs)


def test_http_tool_uses_configured_url_not_model_argument(fake_http):
    tool = build_tool(url="http://127.0.0.1:9100/predict", client=fake_http)

    tool.execute({"url": "http://malicious.invalid", "query": "hello"}, None)

    assert fake_http.last_url == "http://127.0.0.1:9100/predict"
    assert fake_http.last_json == {"query": "hello"}


def test_http_tool_adapts_success_to_tool_result(fake_http):
    fake_http.response = {"answer": "ok", "score": 0.8}

    result = build_tool(client=fake_http).execute({"query": "hello"}, None)

    assert result.status == "completed"
    assert result.data["score"] == 0.8


def test_http_tool_maps_request_fields(fake_http):
    tool = build_tool(
        client=fake_http,
        request_mapping={"query": "question"},
    )

    tool.execute({"query": "hello"}, None)

    assert fake_http.last_json == {"question": "hello"}


def test_http_tool_maps_response_fields(fake_http):
    fake_http.response = {"data": {"answer": "ok"}, "score": 0.8}
    tool = build_tool(
        client=fake_http,
        response_mapping={"text": "data.answer", "score": "score"},
    )

    result = tool.execute({"query": "hello"}, None)

    assert result.data == {"text": "ok", "score": 0.8}
    assert result.summary


def test_http_tool_uses_configured_method_and_timeout(fake_http):
    build_tool(client=fake_http, method="GET", timeout_seconds=3).execute(
        {"query": "hello"},
        None,
    )

    assert fake_http.last_method == "GET"
    assert fake_http.last_timeout == 3


def test_http_tool_rejects_non_2xx_response(fake_http):
    fake_http.status_code = 503

    with pytest.raises(ToolExecutionError, match="503"):
        build_tool(client=fake_http).execute({"query": "hello"}, None)


def test_http_tool_rejects_invalid_json(fake_http):
    fake_http.response = ValueError("not json")

    with pytest.raises(ToolExecutionError, match="JSON"):
        build_tool(client=fake_http).execute({"query": "hello"}, None)


def test_http_tool_reports_timeout(fake_http):
    fake_http.error = httpx.TimeoutException("timed out")

    with pytest.raises(ToolExecutionError, match="超时"):
        build_tool(client=fake_http).execute({"query": "hello"}, None)


def test_http_tool_requires_configured_parameters(fake_http):
    tool = build_tool(client=fake_http, required_parameters=("query",))

    assert tool.missing_parameters({}) == ["query"]
    assert tool.missing_parameters({"query": "hello"}) == []


def test_http_config_rejects_non_http_urls():
    with pytest.raises(ValueError, match="http"):
        HttpToolConfig(name="demo", description="demo", url="file:///etc/passwd")


def test_http_config_rejects_unknown_method():
    with pytest.raises(ValueError, match="method"):
        HttpToolConfig(
            name="demo",
            description="demo",
            url="http://127.0.0.1:9100/predict",
            method="DELETE",
        )


def test_http_tool_uses_module_request_without_an_injected_client(monkeypatch):
    calls = {}

    class Response:
        status_code = 200

        def json(self):
            return {"answer": "ok"}

    def fake_request(method, url, **kwargs):
        calls["method"] = method
        calls["url"] = url
        calls["json"] = kwargs.get("json")
        return Response()

    monkeypatch.setattr(httpx, "request", fake_request)

    result = build_tool(url="http://127.0.0.1:9100/predict").execute(
        {"query": "hello"},
        None,
    )

    assert calls["url"] == "http://127.0.0.1:9100/predict"
    assert calls["json"] == {"query": "hello"}
    assert result.status == "completed"
