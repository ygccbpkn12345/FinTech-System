# AnalystVerse Chat Tool Router UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 先交付可用的 DeepSeek 风格聊天与股票预测闭环，再补齐爬虫工具、通用 HTTP 工具和界面细节。

**Architecture:** FastAPI 聊天编排器负责多轮会话、DeepSeek 意图判断、关键词兜底和工具执行；React 聊天页只处理统一消息协议。现有股票分析任务、SSE 和工作台继续复用，爬虫逻辑从 API 路由下沉为共享服务。

**Tech Stack:** Python 3、FastAPI、Pydantic、pytest、React 19、React Router、Ant Design、ECharts、Node test runner、Vite。

---

## 交付顺序

### 主体阶段

先完成用户能直接体验和验收的核心链路：

1. 聊天消息和工具结果契约。
2. 进程内多轮会话与缺参补全。
3. 普通聊天、股票预测路由和关键词兜底。
4. 股票预测任务启动、进度显示、摘要结果和工作台跳转。
5. DeepSeek 风格聊天主界面。

主体阶段验收标准：用户可以正常聊天；输入“预测中兴通讯”后系统追问日期；补充日期后启动现有股票分析；聊天中出现进度、摘要和走势图；点击按钮进入完整工作台且不重复计算。

### 细节阶段

主体闭环稳定后再实现：

6. 将现有爬虫封装为可复用工具，并加入确认流程。
7. 通用 HTTP 工具与响应适配器。
8. 本地会话历史、恢复、移动端和错误交互打磨。
9. 全量回归与文档更新。

---

## 主体阶段

### Task 1: 定义聊天领域契约

**Files:**
- Create: `Analyst/services/chat_models.py`
- Create: `Analyst/tests/test_chat_models.py`

- [ ] **Step 1: 写失败测试，约束消息和工具结果序列化**

```python
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
```

- [ ] **Step 2: 运行测试并确认因模块不存在而失败**

Run: `cd Analyst; python -m pytest tests/test_chat_models.py -q`

Expected: FAIL with `ModuleNotFoundError: services.chat_models`.

- [ ] **Step 3: 实现最小领域模型**

```python
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


MessageType = Literal[
    "text", "parameter_request", "confirmation",
    "tool_progress", "result", "error",
]


class Action(BaseModel):
    type: Literal["navigate", "retry", "confirm"]
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
    missing_parameters: list[str] = Field(default_factory=list, alias="missingParameters")
    task_id: str | None = Field(default=None, alias="taskId")
    result: ToolResult | None = None

    model_config = {"populate_by_name": True}

    @classmethod
    def parameter_request(cls, *, content, tool, missing_parameters):
        return cls(
            role="assistant",
            type="parameter_request",
            content=content,
            tool=tool,
            missingParameters=missing_parameters,
        )
```

- [ ] **Step 4: 运行测试并确认通过**

Run: `cd Analyst; python -m pytest tests/test_chat_models.py -q`

Expected: `2 passed`.

- [ ] **Step 5: 提交**

```bash
git add Analyst/services/chat_models.py Analyst/tests/test_chat_models.py
git commit -m "feat: define chat message contract"
```

### Task 2: 实现工具注册表与进程内会话

**Files:**
- Create: `Analyst/services/tool_registry.py`
- Create: `Analyst/services/chat_session_store.py`
- Create: `Analyst/tests/test_tool_registry.py`
- Create: `Analyst/tests/test_chat_session_store.py`

- [ ] **Step 1: 写失败测试，覆盖注册、未知工具和多轮待执行参数**

```python
import pytest

from services.chat_session_store import ChatSessionStore
from services.tool_registry import ToolRegistry


class FakeTool:
    name = "stock_prediction"


def test_registry_returns_registered_tool():
    registry = ToolRegistry([FakeTool()])
    assert registry.get("stock_prediction").name == "stock_prediction"


def test_registry_rejects_unknown_tool():
    registry = ToolRegistry([])
    with pytest.raises(KeyError, match="unknown_tool"):
        registry.get("unknown_tool")


def test_session_merges_parameters_across_turns():
    store = ChatSessionStore(max_sessions=10)
    session = store.create()
    store.set_pending(session.id, "stock_prediction", {"stockCode": "000063"})
    updated = store.merge_pending_arguments(session.id, {"analysisDate": "2024-01-03"})
    assert updated.pending_arguments == {
        "stockCode": "000063",
        "analysisDate": "2024-01-03",
    }
```

- [ ] **Step 2: 运行测试并确认缺少实现**

Run: `cd Analyst; python -m pytest tests/test_tool_registry.py tests/test_chat_session_store.py -q`

Expected: FAIL because both service modules are absent.

- [ ] **Step 3: 实现小型注册表和带锁的内存会话存储**

注册表公开 `get(name)`、`descriptions()`；会话保存 `messages`、`pending_tool`、`pending_arguments`、`pending_confirmation`、`task_id` 与 `updated_at`。所有读写使用 `threading.RLock`，并在创建会话时清理超时记录和最旧记录。

- [ ] **Step 4: 运行测试并确认通过**

Run: `cd Analyst; python -m pytest tests/test_tool_registry.py tests/test_chat_session_store.py -q`

Expected: all tests PASS.

- [ ] **Step 5: 提交**

```bash
git add Analyst/services/tool_registry.py Analyst/services/chat_session_store.py Analyst/tests/test_tool_registry.py Analyst/tests/test_chat_session_store.py
git commit -m "feat: add chat tool registry and sessions"
```

### Task 3: 实现 DeepSeek 路由与关键词兜底

**Files:**
- Create: `Analyst/services/chat_router.py`
- Create: `Analyst/tests/test_chat_router.py`
- Modify: `Analyst/services/runtime_config.py`

- [ ] **Step 1: 写失败测试**

```python
from services.chat_router import ChatRouter


class BrokenModel:
    def invoke(self, _messages):
        raise TimeoutError("model timeout")


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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd Analyst; python -m pytest tests/test_chat_router.py -q`

Expected: FAIL because `ChatRouter` is absent.

- [ ] **Step 3: 实现结构化模型路由与兜底**

路由结果固定为：

```python
class RouteDecision(BaseModel):
    tool: str
    arguments: dict[str, str] = Field(default_factory=dict)
    confidence: float = 0.0
```

模型提示词只能选择注册表提供的工具。股票识别首先匹配六位代码，再使用现有 `symbol_service` 中的股票名称映射。包含“预测、走势、买入、卖出、分析股票”等表达时兜底到 `stock_prediction`；包含“爬取、抓取、更新数据、更新行情”时兜底到 `market_data_crawler`；其他消息进入 `general_chat`。

- [ ] **Step 4: 运行路由测试和现有配置测试**

Run: `cd Analyst; python -m pytest tests/test_chat_router.py tests/test_runtime_config.py -q`

Expected: all tests PASS.

- [ ] **Step 5: 提交**

```bash
git add Analyst/services/chat_router.py Analyst/services/runtime_config.py Analyst/tests/test_chat_router.py
git commit -m "feat: route chat messages to tools"
```

### Task 4: 封装股票预测工具与聊天编排器

**Files:**
- Create: `Analyst/services/tools/__init__.py`
- Create: `Analyst/services/tools/stock_prediction.py`
- Create: `Analyst/services/chat_orchestrator.py`
- Create: `Analyst/tests/test_stock_prediction_tool.py`
- Create: `Analyst/tests/test_chat_orchestrator.py`
- Modify: `Analyst/api_server.py`

- [ ] **Step 1: 写失败测试，覆盖追问和任务启动**

```python
from services.chat_orchestrator import ChatOrchestrator
from services.tools.stock_prediction import StockPredictionTool


def test_stock_tool_requests_only_missing_analysis_date():
    tool = StockPredictionTool(start_task=lambda _: "unused")
    assert tool.missing_parameters({"stockCode": "000063"}) == ["analysisDate"]


def test_second_turn_starts_prediction_with_merged_parameters(orchestrator):
    first = orchestrator.handle(None, "预测中兴通讯")
    assert first.messages[0].type == "parameter_request"

    second = orchestrator.handle(first.conversation_id, "2024-01-03")
    assert second.messages[0].type == "tool_progress"
    assert second.messages[0].task_id == "task-123"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd Analyst; python -m pytest tests/test_stock_prediction_tool.py tests/test_chat_orchestrator.py -q`

Expected: FAIL because tool and orchestrator modules are absent.

- [ ] **Step 3: 实现股票预测工具**

工具复用 `validate_symbol_for_analysis` 与现有任务创建逻辑。为避免 HTTP 内部回调，将 `api_server.py` 中创建任务的共享部分提取为普通函数 `create_analysis_task(stock_code, analysis_date, background_tasks)`，原 `/api/analyze/start` 和股票工具共同调用。

- [ ] **Step 4: 实现聊天编排器**

编排器流程固定为：加载或创建会话 → 若存在待执行工具则提取本轮参数并合并 → 否则执行路由 → 普通聊天调用模型 → 业务工具校验 → 缺参返回追问 → 参数齐全则执行。每一步将用户和助手消息追加到会话。

- [ ] **Step 5: 运行相关后端测试**

Run: `cd Analyst; python -m pytest tests/test_stock_prediction_tool.py tests/test_chat_orchestrator.py tests/test_task_event_stream.py -q`

Expected: all tests PASS.

- [ ] **Step 6: 提交**

```bash
git add Analyst/services/tools Analyst/services/chat_orchestrator.py Analyst/api_server.py Analyst/tests/test_stock_prediction_tool.py Analyst/tests/test_chat_orchestrator.py
git commit -m "feat: orchestrate stock predictions from chat"
```

### Task 5: 暴露聊天 API

**Files:**
- Modify: `Analyst/api_server.py`
- Create: `Analyst/tests/test_chat_api.py`

- [ ] **Step 1: 写失败 API 测试**

```python
from fastapi.testclient import TestClient

from api_server import app


def test_chat_api_returns_conversation_and_messages(monkeypatch):
    client = TestClient(app)
    response = client.post("/api/chat/messages", json={
        "message": "预测 000063",
        "clientMessageId": "client-1",
    })
    assert response.status_code == 200
    body = response.json()
    assert body["conversationId"]
    assert body["messages"][0]["type"] == "parameter_request"
```

- [ ] **Step 2: 运行测试并确认 404**

Run: `cd Analyst; python -m pytest tests/test_chat_api.py -q`

Expected: FAIL with HTTP 404.

- [ ] **Step 3: 新增请求响应模型和 `/api/chat/messages`**

```python
class ChatRequest(BaseModel):
    conversationId: str | None = None
    message: str = Field(min_length=1, max_length=8000)
    clientMessageId: str


@app.post("/api/chat/messages")
def send_chat_message(request: ChatRequest, background_tasks: BackgroundTasks):
    return chat_orchestrator.handle(
        request.conversationId,
        request.message.strip(),
        background_tasks=background_tasks,
    )
```

- [ ] **Step 4: 运行 API 与现有分析 API 测试**

Run: `cd Analyst; python -m pytest tests/test_chat_api.py tests/test_task_event_stream.py tests/test_config_api.py -q`

Expected: all tests PASS.

- [ ] **Step 5: 提交**

```bash
git add Analyst/api_server.py Analyst/tests/test_chat_api.py
git commit -m "feat: expose chat messages endpoint"
```

### Task 6: 实现前端聊天状态与 API 客户端

**Files:**
- Create: `frontend/src/api/chatApi.js`
- Create: `frontend/src/utils/chatState.js`
- Create: `frontend/src/utils/chatState.test.js`
- Modify: `frontend/package.json`

- [ ] **Step 1: 写失败测试**

```javascript
import test from 'node:test'
import assert from 'node:assert/strict'
import { appendAssistantMessages, resolveToolProgress } from './chatState.js'

test('assistant messages append without duplicating client message', () => {
  const current = [{ id: 'u1', role: 'user', type: 'text', content: '预测 000063' }]
  const next = appendAssistantMessages(current, [
    { id: 'a1', role: 'assistant', type: 'parameter_request', content: '请选择日期' },
  ])
  assert.equal(next.length, 2)
})

test('completed result replaces matching progress message', () => {
  const next = resolveToolProgress(
    [{ id: 'p1', type: 'tool_progress', taskId: 'task-1' }],
    { id: 'r1', type: 'result', taskId: 'task-1' },
  )
  assert.equal(next[0].type, 'result')
})
```

- [ ] **Step 2: 运行测试并确认模块不存在**

Run: `cd frontend; node --test src/utils/chatState.test.js`

Expected: FAIL with module-not-found.

- [ ] **Step 3: 实现纯状态函数和聊天 API 客户端**

`sendChatMessage({ conversationId, message, clientMessageId })` 调用 `/api/chat/messages`。状态工具保持不可变更新，并按 `taskId` 将运行消息替换为最终结果。

- [ ] **Step 4: 将测试加入统一脚本并运行**

在 `package.json` 增加：

```json
"test:chat": "node --test src/utils/chatState.test.js src/utils/chatResult.test.js"
```

Run: `cd frontend; npm run test:chat`

Expected: all tests PASS.

- [ ] **Step 5: 提交**

```bash
git add frontend/src/api/chatApi.js frontend/src/utils/chatState.js frontend/src/utils/chatState.test.js frontend/package.json
git commit -m "feat: add frontend chat state and API"
```

### Task 7: 构建 DeepSeek 风格聊天主体

**Files:**
- Create: `frontend/src/pages/Chat.jsx`
- Create: `frontend/src/components/chat/ChatSidebar.jsx`
- Create: `frontend/src/components/chat/ChatComposer.jsx`
- Create: `frontend/src/components/chat/ChatMessage.jsx`
- Create: `frontend/src/components/chat/ToolStatusMessage.jsx`
- Create: `frontend/src/components/chat/StockResultCard.jsx`
- Create: `frontend/src/utils/chatResult.js`
- Create: `frontend/src/utils/chatResult.test.js`
- Modify: `frontend/src/App.jsx`
- Modify: `frontend/src/components/AppLayout.jsx`
- Modify: `frontend/src/styles/global.css`

- [ ] **Step 1: 写失败测试，锁定股票结果到图表的转换**

```javascript
import test from 'node:test'
import assert from 'node:assert/strict'
import { toStockChartOption } from './chatResult.js'

test('stock result becomes line chart option', () => {
  const option = toStockChartOption({
    visualizations: [{
      type: 'line',
      title: '价格走势',
      x: ['2024-01-02', '2024-01-03'],
      series: [{ name: '收盘价', data: [10, 11] }],
    }],
  })
  assert.deepEqual(option.xAxis.data, ['2024-01-02', '2024-01-03'])
  assert.deepEqual(option.series[0].data, [10, 11])
})
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `cd frontend; node --test src/utils/chatResult.test.js`

Expected: FAIL because `chatResult.js` is absent.

- [ ] **Step 3: 实现图表转换和结果卡**

结果卡读取 `summary`、`data.action`、`data.confidence`、风险摘要和首个折线图描述。按钮通过 React Router 导航到 `/dashboard`，state 携带 `{ taskId, fromChat: true }`。

- [ ] **Step 4: 实现聊天页与输入交互**

`Chat.jsx` 管理输入、加载状态、会话 ID 和消息。提交时立即追加用户消息，调用 API 后追加助手消息；收到 `tool_progress` 后复用 `subscribeAnalysisEvents` 和结果接口，完成时生成标准结果消息。

- [ ] **Step 5: 调整路由和整体布局**

`/` 默认重定向 `/chat`；`/chat` 使用专用聊天布局。`/dashboard` 保留现有工作台。侧栏菜单保留完整分析、历史、反思和设置入口，但聊天页视觉以历史会话为主。

- [ ] **Step 6: 实现响应式样式**

桌面端侧栏宽 248px、聊天正文最大宽 800px、输入框固定在内容底部；小于 768px 时侧栏抽屉化，卡片和图表宽度为 100%。颜色使用中性灰白背景和现有品牌强调色。

- [ ] **Step 7: 运行测试、构建并人工验证主体**

Run: `cd frontend; npm run test:chat`

Expected: all tests PASS.

Run: `cd frontend; npm run build`

Expected: Vite build succeeds without warnings introduced by the new files.

- [ ] **Step 8: 提交**

```bash
git add frontend/src frontend/package.json
git commit -m "feat: add chat-first interface"
```

### Task 8: 让完整工作台加载聊天任务结果

**Files:**
- Modify: `frontend/src/pages/Dashboard.jsx`
- Modify: `frontend/src/api/analysisApi.js`
- Create: `frontend/src/utils/chatDashboardHandoff.js`
- Create: `frontend/src/utils/chatDashboardHandoff.test.js`

- [ ] **Step 1: 写失败测试**

```javascript
import test from 'node:test'
import assert from 'node:assert/strict'
import { resolveChatHandoff } from './chatDashboardHandoff.js'

test('chat handoff requests existing result without starting another task', () => {
  assert.deepEqual(resolveChatHandoff({ taskId: 'task-1', fromChat: true }), {
    taskId: 'task-1',
    shouldLoadResult: true,
    shouldStartAnalysis: false,
  })
})
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd frontend; node --test src/utils/chatDashboardHandoff.test.js`

Expected: FAIL because helper is absent.

- [ ] **Step 3: 实现任务交接**

Dashboard 检测 `location.state.taskId` 后调用现有结果接口，填充 `analysisData`、完成状态和股票日期；不调用 `startAnalysis`。加载失败时保留工作台输入区并显示可重试错误。

- [ ] **Step 4: 运行测试与构建**

Run: `cd frontend; node --test src/utils/chatDashboardHandoff.test.js; npm run build`

Expected: test and build PASS.

- [ ] **Step 5: 提交主体阶段**

```bash
git add frontend/src/pages/Dashboard.jsx frontend/src/api/analysisApi.js frontend/src/utils/chatDashboardHandoff.js frontend/src/utils/chatDashboardHandoff.test.js
git commit -m "feat: open chat predictions in dashboard"
```

---

## 细节阶段

### Task 9: 将爬虫下沉为服务并注册为工具

**Files:**
- Create: `Analyst/services/market_data_crawler.py`
- Create: `Analyst/services/tools/market_data_crawler.py`
- Create: `Analyst/tests/test_market_data_crawler_tool.py`
- Modify: `Analyst/api_server.py`
- Modify: `Analyst/services/chat_orchestrator.py`

- [ ] **Step 1: 写失败测试，验证 API 与聊天工具调用同一个服务**

测试注入假的 crawler，分别通过 `/api/data/fetch` 和工具执行入口调用，并断言二者收到相同的规范化参数 `{symbol, start_date, end_date, data_source}`。

- [ ] **Step 2: 运行测试确认失败**

Run: `cd Analyst; python -m pytest tests/test_market_data_crawler_tool.py -q`

Expected: FAIL because crawler tool is absent.

- [ ] **Step 3: 提取现有 `/api/data/fetch` 业务逻辑**

将 Baostock、Tushare、东方财富、指标生成和文件同步迁入 `market_data_crawler.py` 的 `fetch_market_data()`。API 路由只负责解析请求和返回服务结果，行为与原接口保持一致。

- [ ] **Step 4: 实现确认流程**

当预测发现数据不完整时，返回 `confirmation` 消息和 `confirm_crawl` 动作。只有用户明确回复确认或点击确认按钮后执行爬虫；完成后重新检查可分析状态，再继续原待执行预测。

- [ ] **Step 5: 运行爬虫、日期和编排测试**

Run: `cd Analyst; python -m pytest tests/test_market_data_crawler_tool.py tests/test_crawl_date_range.py tests/test_data_fetch_service.py tests/test_chat_orchestrator.py -q`

Expected: all tests PASS.

- [ ] **Step 6: 提交**

```bash
git add Analyst/services/market_data_crawler.py Analyst/services/tools/market_data_crawler.py Analyst/services/chat_orchestrator.py Analyst/api_server.py Analyst/tests/test_market_data_crawler_tool.py
git commit -m "feat: expose market crawler as chat tool"
```

### Task 10: 增加通用 HTTP 工具

**Files:**
- Create: `Analyst/services/tools/http_tool.py`
- Create: `Analyst/services/http_tool_config.py`
- Create: `Analyst/tests/test_http_tool.py`

- [ ] **Step 1: 写失败测试，覆盖固定 URL、映射和错误**

```python
def test_http_tool_uses_configured_url_not_model_argument(fake_http):
    tool = build_tool(url="http://127.0.0.1:9100/predict", client=fake_http)
    tool.execute({"url": "http://malicious.invalid", "query": "hello"}, None)
    assert fake_http.last_url == "http://127.0.0.1:9100/predict"


def test_http_tool_adapts_success_to_tool_result(fake_http):
    fake_http.response = {"answer": "ok", "score": 0.8}
    result = build_tool(client=fake_http).execute({"query": "hello"}, None)
    assert result.status == "completed"
    assert result.data["score"] == 0.8
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd Analyst; python -m pytest tests/test_http_tool.py -q`

Expected: FAIL because HTTP tool modules are absent.

- [ ] **Step 3: 实现静态配置和适配器**

配置字段包括 `name`、`description`、`url`、`method`、`timeout_seconds`、`required_parameters`、`request_mapping` 和 `response_mapping`。目标 URL 只读取服务端配置。超时、非 2xx 和无效 JSON 转换成受控 `ToolExecutionError`。

- [ ] **Step 4: 注册一个仅供测试的示例配置并运行测试**

Run: `cd Analyst; python -m pytest tests/test_http_tool.py tests/test_tool_registry.py -q`

Expected: all tests PASS.

- [ ] **Step 5: 提交**

```bash
git add Analyst/services/tools/http_tool.py Analyst/services/http_tool_config.py Analyst/tests/test_http_tool.py
git commit -m "feat: add configurable HTTP tools"
```

### Task 11: 完成本地历史、恢复和交互细节

**Files:**
- Create: `frontend/src/utils/chatStorage.js`
- Create: `frontend/src/utils/chatStorage.test.js`
- Modify: `frontend/src/pages/Chat.jsx`
- Modify: `frontend/src/components/chat/ChatSidebar.jsx`
- Modify: `frontend/src/components/chat/ChatMessage.jsx`
- Modify: `frontend/src/styles/global.css`

- [ ] **Step 1: 写失败测试，覆盖版本化存储和损坏数据恢复**

测试 `saveConversation`、`loadConversations`、按更新时间排序、最大保留数量，以及 JSON 损坏时返回空数组。

- [ ] **Step 2: 运行测试确认失败**

Run: `cd frontend; node --test src/utils/chatStorage.test.js`

Expected: FAIL because storage helper is absent.

- [ ] **Step 3: 实现本地历史和恢复**

使用键 `analystverse_chat_history_v1`，只保存会话 ID、标题、更新时间和消息。运行中消息保留任务 ID；刷新后重新查询现有任务状态。限制最近 50 个会话。

- [ ] **Step 4: 补齐错误、重试和移动端交互**

错误消息提供重试按钮；确认消息提供确认/取消；侧栏在移动端使用抽屉；输入框支持 Enter 发送、Shift+Enter 换行、请求期间仍允许滚动和复制历史内容。

- [ ] **Step 5: 运行聊天测试与构建**

Run: `cd frontend; npm run test:chat; npm run build`

Expected: all tests and build PASS.

- [ ] **Step 6: 提交**

```bash
git add frontend/src
git commit -m "feat: persist and polish chat conversations"
```

### Task 12: 全量验证与文档更新

**Files:**
- Modify: `README.md`
- Modify: `docker/nginx.conf` only if chat API requires a timeout adjustment

- [ ] **Step 1: 运行后端全量测试**

Run: `cd Analyst; python -m pytest tests -q`

Expected: all tests PASS.

- [ ] **Step 2: 运行前端全部现有测试**

Run: `cd frontend; npm run test:events; npm run test:config; npm run test:reflection; npm run test:crawl; npm run test:analysis-date; npm run test:chat`

Expected: all test commands PASS.

- [ ] **Step 3: 构建前端**

Run: `cd frontend; npm run build`

Expected: Vite build succeeds.

- [ ] **Step 4: 执行主体端到端验收**

依次验证普通聊天、股票名称识别、日期追问、任务进度、结果图、无重复跳转、数据缺失确认爬虫、爬虫部分失败、HTTP 工具成功和 HTTP 工具超时。

- [ ] **Step 5: 更新 README**

补充 `/chat` 首页、聊天 API 示例、工具注册方式、单 worker 约束、爬虫确认行为和 HTTP 工具服务端固定 URL 规则。

- [ ] **Step 6: 最终提交**

```bash
git add README.md docker/nginx.conf
git commit -m "docs: document chat tool platform"
```

