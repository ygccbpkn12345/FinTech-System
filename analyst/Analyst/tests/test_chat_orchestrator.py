import pytest

from services.chat_orchestrator import ChatOrchestrator
from services.tools.stock_prediction import StockPredictionTool


class BrokenModel:
    def invoke(self, _messages):
        raise TimeoutError("model timeout")


class TextModel:
    def __init__(self, content="你好，我是 AnalystVerse 助手。"):
        self.content = content

    def invoke(self, _messages):
        return type("Response", (), {"content": self.content})()


class Recorder:
    def __init__(self, task_id="task-123"):
        self.calls = []
        self.task_id = task_id

    def __call__(self, stock_code, analysis_date, background_tasks=None):
        self.calls.append((stock_code, analysis_date))
        return self.task_id


def build_orchestrator(model=None, recorder=None):
    recorder = recorder or Recorder()
    tool = StockPredictionTool(start_task=recorder, validate=lambda *_: "000063")
    orchestrator = ChatOrchestrator(
        [tool],
        model_factory=lambda: model or BrokenModel(),
    )
    return orchestrator, recorder


def test_second_turn_starts_prediction_with_merged_parameters():
    orchestrator, recorder = build_orchestrator()

    first = orchestrator.handle(None, "预测中兴通讯")
    assert first.messages[0].type == "parameter_request"
    assert first.messages[0].missing_parameters == ["analysisDate"]

    second = orchestrator.handle(first.conversation_id, "2024-01-03")
    assert second.messages[0].type == "tool_progress"
    assert second.messages[0].task_id == "task-123"
    assert recorder.calls == [("000063", "2024-01-03")]


def test_general_chat_returns_assistant_text():
    orchestrator, _ = build_orchestrator(model=TextModel("你好！我是 AnalystVerse 助手。"))

    response = orchestrator.handle(None, "你好，介绍一下自己")

    assert response.messages[0].type == "text"
    assert response.messages[0].role == "assistant"
    assert "AnalystVerse" in response.messages[0].content


def test_general_chat_model_failure_returns_retryable_error():
    orchestrator, _ = build_orchestrator()

    response = orchestrator.handle(None, "你好")

    assert response.messages[0].type == "error"
    assert response.messages[0].result.actions[0].type == "retry"


def test_conversation_is_reused_between_turns():
    orchestrator, _ = build_orchestrator()

    first = orchestrator.handle(None, "预测中兴通讯")
    second = orchestrator.handle(first.conversation_id, "2024-01-03")

    assert second.conversation_id == first.conversation_id


def test_unknown_conversation_id_starts_a_new_session():
    orchestrator, _ = build_orchestrator()

    response = orchestrator.handle("missing-session", "你好")

    assert response.conversation_id != "missing-session"


def test_tool_failure_becomes_error_message_without_leaking_details():
    def failing_start(*_args, **_kwargs):
        raise RuntimeError("database dsn postgres://secret")

    tool = StockPredictionTool(start_task=failing_start, validate=lambda *_: "000063")
    orchestrator = ChatOrchestrator([tool], model_factory=lambda: BrokenModel())

    response = orchestrator.handle(None, "预测 000063 2024-01-03")

    message = response.messages[0]
    assert message.type == "error"
    assert "postgres" not in message.content
    assert message.result.actions[0].type == "retry"


def test_parameter_request_is_recorded_in_session_history():
    orchestrator, _ = build_orchestrator()

    first = orchestrator.handle(None, "预测中兴通讯")
    session = orchestrator.store.get(first.conversation_id)

    roles = [message.role for message in session.messages]
    assert roles == ["user", "assistant"]
    assert session.pending_tool == "stock_prediction"
    assert session.pending_arguments == {"stockCode": "000063"}


def test_completed_turn_clears_pending_state_and_records_task():
    orchestrator, _ = build_orchestrator()

    first = orchestrator.handle(None, "预测中兴通讯")
    orchestrator.handle(first.conversation_id, "2024-01-03")

    session = orchestrator.store.get(first.conversation_id)
    assert session.pending_tool is None
    assert session.pending_arguments == {}
    assert session.task_id == "task-123"


class FakeCrawler:
    def __init__(self, result=None, on_fetch=None):
        self.calls = []
        self.result = result or {
            "status": "ok",
            "message": "行情数据已更新",
            "modules": {"market": {"status": "ok"}},
            "failedModules": [],
        }
        self.on_fetch = on_fetch

    def fetch(self, arguments):
        self.calls.append(arguments)
        if self.on_fetch is not None:
            self.on_fetch()
        return self.result


def build_crawl_orchestrator(crawl_result=None):
    from services.tools.market_data_crawler import MarketDataCrawlerTool

    state = {"ready": False}

    def validate(stock_code, analysis_date=None):
        if not state["ready"]:
            raise ValueError(
                f"股票 {stock_code} 缺少本地数据，请上传：technical_indicators。"
            )
        return stock_code

    def mark_ready():
        state["ready"] = True

    recorder = Recorder()
    crawler = FakeCrawler(crawl_result, on_fetch=mark_ready)
    tools = [
        StockPredictionTool(start_task=recorder, validate=validate),
        MarketDataCrawlerTool(crawler=crawler),
    ]
    orchestrator = ChatOrchestrator(
        tools,
        model_factory=lambda: BrokenModel(),
    )
    return orchestrator, recorder, crawler


def test_missing_data_asks_for_crawl_confirmation():
    orchestrator, recorder, crawler = build_crawl_orchestrator()

    response = orchestrator.handle(None, "预测 000063 2024-01-03")

    message = response.messages[0]
    assert message.type == "confirmation"
    assert "缺少本地数据" in message.content
    assert [action.type for action in message.result.actions] == ["confirm", "cancel"]
    assert recorder.calls == []
    assert crawler.calls == []


def test_confirmation_crawls_then_resumes_prediction():
    orchestrator, recorder, crawler = build_crawl_orchestrator()

    first = orchestrator.handle(None, "预测 000063 2024-01-03")
    second = orchestrator.handle(first.conversation_id, "确认")

    assert len(crawler.calls) == 1
    normalized = crawler.calls[0]
    assert normalized["symbol"] == "000063"
    assert normalized["end_date"] == "2024-01-03"
    assert normalized["start_date"] < normalized["end_date"]

    types = [message.type for message in second.messages]
    assert "tool_progress" in types
    assert recorder.calls == [("000063", "2024-01-03")]

    session = orchestrator.store.get(first.conversation_id)
    assert session.pending_confirmation is None
    assert session.pending_tool is None
    assert session.task_id == "task-123"


def test_cancel_clears_pending_work_without_crawling():
    orchestrator, recorder, crawler = build_crawl_orchestrator()

    first = orchestrator.handle(None, "预测 000063 2024-01-03")
    second = orchestrator.handle(first.conversation_id, "取消")

    assert second.messages[0].type == "text"
    assert "取消" in second.messages[0].content
    assert crawler.calls == []
    assert recorder.calls == []

    session = orchestrator.store.get(first.conversation_id)
    assert session.pending_confirmation is None
    assert session.pending_tool is None


def test_crawl_failure_is_reported_and_pending_work_is_cleared():
    orchestrator, recorder, crawler = build_crawl_orchestrator(
        {
            "status": "error",
            "message": "Tushare 需要 token",
            "modules": {},
            "failedModules": ["market"],
        }
    )

    first = orchestrator.handle(None, "预测 000063 2024-01-03")
    second = orchestrator.handle(first.conversation_id, "确认")

    assert second.messages[0].type == "error"
    assert "token" in second.messages[0].content
    assert recorder.calls == []

    session = orchestrator.store.get(first.conversation_id)
    assert session.pending_confirmation is None
    assert session.pending_tool is None
