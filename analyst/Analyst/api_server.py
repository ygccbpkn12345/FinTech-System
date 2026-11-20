"""AnalystVerse FastAPI 后端入口。"""

from __future__ import annotations

import threading
import uuid
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Literal

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

load_dotenv(Path(__file__).resolve().parent / ".env")
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from config import get_config

from services.data_upload_service import DataUploadError, save_uploaded_file
from services.chat_orchestrator import ChatOrchestrator, ChatResponse
from services.algorithm_api import build_algorithm_router
from services.algorithm_manager import AlgorithmManager, discover_local_tools
from services.pipeline_service import run_analysis_pipeline, run_reflection_pipeline
from services.market_data_crawler import (
    MarketDataCrawlerService,
    normalize_fetch_request,
)
from services.runtime_config import (
    RuntimeConfigError,
    build_chat_model,
    build_data_overrides,
    build_llm_overrides,
    get_runtime_config,
    update_runtime_config,
)
from services.symbol_service import (
    get_available_dates,
    get_recommended_codes,
    get_symbol_data_status,
    list_symbols,
    normalize_symbol,
    validate_symbol_for_analysis,
)
from services.strategy_validation import build_strategy_validation_router
from services.task_event_stream import TaskEventStream, encode_heartbeat, encode_sse
from services.tools.market_data_crawler import MarketDataCrawlerTool
from services.tools.stock_prediction import StockPredictionTool

load_dotenv()

app = FastAPI(
    title="AnalystVerse API",
    description="多分析师 LLM 股票决策模型后端接口",
    version="0.2.0",
)

CORS_ORIGINS = [
    f"http://{host}:{port}"
    for host in ("localhost", "127.0.0.1")
    for port in range(5173, 5181)
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

TaskStatus = Literal["running", "completed", "failed"]

_tasks_lock = threading.RLock()
_tasks: dict[str, dict] = {}
# 同一股票记忆库路径不能并发；按 symbol 加锁，不同股票可并行
_symbol_run_locks: dict[str, threading.Lock] = {}
_symbol_run_locks_guard = threading.Lock()
_postprocessing_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="reflection")
# 聊天工具没有请求级 BackgroundTasks 时，回退到线程池执行分析
_analysis_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="analysis")
_POSTPROCESSING_REASON_TODAY = "当天尚无事后结果，不执行反思"


def _get_symbol_run_lock(symbol: str) -> threading.Lock:
    code = normalize_symbol(symbol)
    with _symbol_run_locks_guard:
        if code not in _symbol_run_locks:
            _symbol_run_locks[code] = threading.Lock()
        return _symbol_run_locks[code]


def _find_running_task(stock_code: str, analysis_date: str) -> dict | None:
    code = normalize_symbol(stock_code)
    with _tasks_lock:
        for task in _tasks.values():
            if (
                task.get("status") == "running"
                and normalize_symbol(task.get("stockCode", "")) == code
                and task.get("analysisDate") == analysis_date
            ):
                return dict(task)
    return None


class LlmConfigModel(BaseModel):
    baseUrl: str | None = None
    apiKey: str | None = None
    quickThinkLlm: str | None = None
    deepThinkLlm: str | None = None
    timeout: int | None = None
    maxRetries: int | None = None


class DataConfigModel(BaseModel):
    dataDir: str | None = None
    dataCache: str | None = None
    resultDir: str | None = None


class AnalyzeStartRequest(BaseModel):
    stockCode: str = Field(..., examples=["000063"])
    analysisDate: str = Field(..., examples=["2024-01-03"])
    dataSource: str | None = Field(default=None, examples=["local_file", "baostock", "tushare"])
    llmConfig: LlmConfigModel | None = None
    dataConfig: DataConfigModel | None = None


class RuntimeConfigUpdateRequest(BaseModel):
    dataConfig: DataConfigModel | None = None
    llmConfig: LlmConfigModel | None = None
    dataDir: str | None = None
    dataCache: str | None = None
    resultDir: str | None = None
    quickThinkLlm: str | None = None
    deepThinkLlm: str | None = None
    baseUrl: str | None = None
    apiKey: str | None = None
    timeout: int | None = None
    maxRetries: int | None = None
    dataSource: str | None = None
    crawlUrl: str | None = None
    tushareToken: str | None = None
    clearApiKey: bool = False
    clearTushareToken: bool = False


class AnalyzeStartResponse(BaseModel):
    taskId: str
    status: TaskStatus
    message: str


class AnalyzeStatusResponse(BaseModel):
    taskId: str
    status: TaskStatus
    currentStep: int
    currentNode: str
    progress: int


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _update_task(task_id: str, **fields) -> None:
    with _tasks_lock:
        if task_id not in _tasks:
            return
        _tasks[task_id].update(fields)
        _tasks[task_id]["updatedAt"] = _utc_now_iso()


def _get_task(task_id: str) -> dict | None:
    with _tasks_lock:
        task = _tasks.get(task_id)
        if task is None:
            return None
        return {key: value for key, value in task.items() if key != "eventStream"}


def _append_module_event(task_id: str, event: dict[str, Any]) -> None:
    with _tasks_lock:
        task = _tasks.get(task_id)
        if task is None:
            return
        public_event = dict(event)
        task.setdefault("events", []).append(public_event)
        task.setdefault("modules", {})[public_event["module"]] = {
            "status": public_event["status"],
            "completedAt": public_event["completedAt"],
            "sequence": public_event["sequence"],
            "result": public_event.get("result"),
        }
        task["eventStream"].append("module_completed", public_event)
        task["currentNode"] = public_event["module"]
        task["updatedAt"] = _utc_now_iso()


def _finish_task(task_id: str, status: TaskStatus, **fields: Any) -> None:
    with _tasks_lock:
        task = _tasks.get(task_id)
        if task is None:
            return
        task.update(fields)
        task["status"] = status
        task["updatedAt"] = _utc_now_iso()
        terminal_data = {"status": status}
        if status == "failed":
            terminal_data["message"] = task.get("error") or "任务执行失败"
        task["eventStream"].append(status, terminal_data)


def _model_to_dict(model: BaseModel | None) -> dict[str, Any] | None:
    if model is None:
        return None
    return model.model_dump(exclude_none=True)


def _sanitize_llm_config(llm_config: dict[str, Any] | None) -> dict[str, Any] | None:
    """忽略前端传来的空 Key、脱敏占位符，回退到服务器 .env。"""
    if not llm_config:
        return None
    clean = dict(llm_config)
    api_key = clean.get("apiKey") or clean.get("api_key")
    if isinstance(api_key, str):
        key = api_key.strip()
        if not key or "****" in key:
            clean.pop("apiKey", None)
            clean.pop("api_key", None)
    base_url = clean.get("baseUrl") or clean.get("base_url")
    if isinstance(base_url, str) and not base_url.strip():
        clean.pop("baseUrl", None)
        clean.pop("base_url", None)
    return clean or None


def _execute_pipeline(
    task_id: str,
    stock_code: str,
    analysis_date: str,
    data_source: str,
    llm_config: dict[str, Any] | None,
    data_config: dict[str, Any] | None,
    config_snapshot: dict[str, Any],
) -> None:
    symbol_lock = _get_symbol_run_lock(stock_code)
    symbol_lock.acquire()

    def on_progress(step: int, node_name: str, progress: int) -> None:
        _update_task(
            task_id,
            status="running",
            currentStep=step,
            currentNode=node_name,
            progress=progress,
        )

    def on_module_event(event: dict[str, Any]) -> None:
        _append_module_event(task_id, event)

    try:
        result = run_analysis_pipeline(
            stock_code=stock_code,
            analysis_date=analysis_date,
            data_source=data_source,
            on_progress=on_progress,
            llm_config=llm_config,
            data_config=data_config,
            runtime_config=config_snapshot,
            task_id=task_id,
            on_module_event=on_module_event,
        )
        _finish_task(
            task_id,
            status="completed",
            currentStep=len(result.get("analysts", [])) + 5,
            currentNode="final_decision",
            progress=100,
            result=result,
        )
        if date.fromisoformat(analysis_date) == datetime.now().astimezone().date():
            _update_task(task_id, postprocessing={
                "status": "not_applicable", "reason": _POSTPROCESSING_REASON_TODAY,
                "updatedAt": _utc_now_iso(),
            })
        else:
            _update_task(task_id, postprocessing={"status": "pending", "updatedAt": _utc_now_iso()})
            _postprocessing_executor.submit(
                _execute_postprocessing, task_id, stock_code, analysis_date, config_snapshot
            )
    except Exception as exc:
        message = str(exc)
        if "Connection error" in message or "RemoteProtocolError" in message:
            message = (
                "DeepSeek API 连接中断，请稍后重试。"
                "若已在系统配置填写 apiKey，请确认与 .env 中 Key 一致且 base_url 为 https://api.deepseek.com。"
            )
        elif "Authentication" in message or "401" in message:
            message = "DeepSeek API Key 无效，请检查系统配置中的 apiKey 或服务器 .env。"
        _finish_task(
            task_id,
            status="failed",
            error=message,
        )
    finally:
        symbol_lock.release()


def _execute_postprocessing(task_id: str, stock_code: str, analysis_date: str, config_snapshot: dict) -> None:
    _update_task(task_id, postprocessing={"status": "running", "updatedAt": _utc_now_iso()})
    symbol_lock = _get_symbol_run_lock(stock_code)
    symbol_lock.acquire()
    try:
        update = run_reflection_pipeline(
            task_id=task_id,
            stock_code=stock_code,
            analysis_date=analysis_date,
            runtime_config=config_snapshot,
        )
        with _tasks_lock:
            task = _tasks.get(task_id)
            if task is None:
                return
            result = dict(task.get("result") or {})
            for field in ("reflection", "environmentSimulation"):
                if field in update:
                    result[field] = update[field]
            task["result"] = result
            task["postprocessing"] = {"status": "completed", "updatedAt": _utc_now_iso()}
            task["updatedAt"] = _utc_now_iso()
    except Exception as exc:
        _update_task(task_id, postprocessing={
            "status": "failed", "error": str(exc), "updatedAt": _utc_now_iso(),
        })
    finally:
        symbol_lock.release()


@app.get("/api/health")
def health_check() -> dict:
    return {
        "status": "ok",
        "service": "AnalystVerse FastAPI Backend",
    }


@app.get("/api/config")
def read_runtime_config() -> dict:
    return get_runtime_config()


@app.post("/api/config")
def write_runtime_config(request: RuntimeConfigUpdateRequest) -> dict:
    payload = request.model_dump(exclude_none=True)
    payload.update(payload.pop("dataConfig", None) or {})
    payload.update(payload.pop("llmConfig", None) or {})
    try:
        return update_runtime_config(payload)
    except RuntimeConfigError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/symbols")
def get_symbols() -> list[dict]:
    return list_symbols()


@app.get("/api/symbols/{symbol}/data-status")
def get_symbol_data_status_api(symbol: str) -> dict:
    code = normalize_symbol(symbol)
    return get_symbol_data_status(code)


@app.get("/api/symbols/{symbol}/available-dates")
def get_symbol_available_dates(symbol: str) -> dict:
    code = normalize_symbol(symbol)
    try:
        return get_available_dates(code)
    except ValueError as exc:
        recommended = ", ".join(get_recommended_codes())
        raise HTTPException(
            status_code=404,
            detail=f"{exc}。请使用 {recommended} 等已准备股票，或通过 /api/data/upload 上传数据。",
        ) from exc


@app.post("/api/data/upload")
async def upload_stock_data(
    symbol: str = Form(...),
    dataType: str = Form(...),
    file: UploadFile = File(...),
) -> dict:
    content = await file.read()
    try:
        return save_uploaded_file(
            symbol=symbol,
            data_type=dataType,
            filename=file.filename or "upload.csv",
            content=content,
        )
    except DataUploadError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def create_analysis_task(
    stock_code: str,
    analysis_date: str,
    background_tasks: BackgroundTasks | None = None,
    *,
    data_source: str | None = None,
    llm_config: dict[str, Any] | None = None,
    data_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """校验并登记分析任务；HTTP 路由与聊天工具共用这一入口。"""
    validate_symbol_for_analysis(stock_code, analysis_date)

    existing = _find_running_task(stock_code, analysis_date)
    if existing is not None:
        return {
            "taskId": existing["taskId"],
            "status": "running",
            "message": "分析任务进行中，请稍候",
        }

    task_id = str(uuid.uuid4())
    now = _utc_now_iso()
    resolved_source = data_source or get_config().get("data_source", "local_file")
    config_snapshot = get_config(
        {
            **build_data_overrides(data_config),
            **build_llm_overrides(llm_config),
            "data_source": resolved_source,
        }
    )

    with _tasks_lock:
        _tasks[task_id] = {
            "taskId": task_id,
            "status": "running",
            "currentStep": 0,
            "currentNode": "init",
            "progress": 0,
            "stockCode": stock_code,
            "analysisDate": analysis_date,
            "dataSource": resolved_source,
            "result": None,
            "error": None,
            "modules": {},
            "events": [],
            "eventStream": TaskEventStream(_tasks_lock),
            "postprocessing": {"status": "pending", "updatedAt": now},
            "createdAt": now,
            "updatedAt": now,
        }

    if background_tasks is not None:
        background_tasks.add_task(
            _execute_pipeline,
            task_id,
            stock_code,
            analysis_date,
            resolved_source,
            llm_config,
            data_config,
            config_snapshot,
        )
    else:
        _analysis_executor.submit(
            _execute_pipeline,
            task_id,
            stock_code,
            analysis_date,
            resolved_source,
            llm_config,
            data_config,
            config_snapshot,
        )

    return {
        "taskId": task_id,
        "status": "running",
        "message": "分析任务已启动",
    }


@app.post("/api/analyze/start", response_model=AnalyzeStartResponse)
def start_analysis(request: AnalyzeStartRequest, background_tasks: BackgroundTasks) -> AnalyzeStartResponse:
    try:
        created = create_analysis_task(
            request.stockCode,
            request.analysisDate,
            background_tasks,
            data_source=request.dataSource,
            llm_config=_sanitize_llm_config(_model_to_dict(request.llmConfig)),
            data_config=_model_to_dict(request.dataConfig),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return AnalyzeStartResponse(**created)


@app.get("/api/analyze/status/{task_id}", response_model=AnalyzeStatusResponse)
def get_analysis_status(task_id: str) -> AnalyzeStatusResponse:
    task = _get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")

    return AnalyzeStatusResponse(
        taskId=task["taskId"],
        status=task["status"],
        currentStep=task["currentStep"],
        currentNode=task["currentNode"],
        progress=task["progress"],
    )


@app.get("/api/analyze/reflection/{task_id}")
def get_reflection_status(task_id: str) -> dict:
    task = _get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    lifecycle = dict(task.get("postprocessing") or {"status": "pending"})
    result = task.get("result") or {}
    return {
        "taskId": task_id,
        "stockCode": task.get("stockCode"),
        "analysisDate": task.get("analysisDate"),
        **lifecycle,
        "reflection": result.get("reflection"),
        "environmentSimulation": result.get("environmentSimulation"),
    }


@app.get("/api/analyze/events/{task_id}")
def stream_analysis_events(
    task_id: str,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
) -> StreamingResponse:
    with _tasks_lock:
        task = _tasks.get(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="任务不存在")
        event_stream: TaskEventStream = task["eventStream"]

    try:
        cursor = max(0, int(last_event_id or 0))
    except ValueError:
        cursor = 0

    def generate():
        nonlocal cursor
        while True:
            pending = event_stream.wait_after(cursor, timeout=15.0)
            if not pending:
                if event_stream.is_terminal:
                    return
                yield encode_heartbeat()
                continue
            for event in pending:
                cursor = event["id"]
                yield encode_sse(event)
            if pending[-1]["event"] in {"completed", "failed"}:
                return

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/analyze/result/{task_id}")
def get_analysis_result(task_id: str) -> dict:
    task = _get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")

    if task["status"] == "running":
        raise HTTPException(status_code=409, detail="任务仍在运行中")

    if task["status"] == "failed":
        raise HTTPException(status_code=500, detail=task.get("error") or "任务执行失败")

    return task["result"]


app.include_router(build_strategy_validation_router(_get_task))


class DataSourceConfigRequest(BaseModel):
    dataSource: str = Field(default="local_file", description="数据源: local_file / baostock / tushare")
    crawlUrl: str = Field(default="https://finance.eastmoney.com/", description="爬虫目标网址")
    tushareToken: str = Field(default="", description="Tushare Token")


@app.post("/api/config/data-source")
def save_data_source_config(request: DataSourceConfigRequest) -> dict:
    payload = {"dataSource": request.dataSource, "crawlUrl": request.crawlUrl}
    if request.tushareToken.strip():
        payload["tushareToken"] = request.tushareToken
    try:
        config = update_runtime_config(payload)["config"]
    except RuntimeConfigError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "status": "ok",
        "message": "数据源配置已保存",
        "dataSource": config["dataSource"],
        "crawlUrl": config["crawlUrl"],
        "tushareTokenConfigured": config["tushareTokenConfigured"],
    }

    # Legacy .env mutation code below is intentionally unreachable during the
    # compatibility window and will be removed with the data-fetch extraction.
    """保存数据源配置到 .env"""
    import os
    from pathlib import Path
    
    env_path = Path(__file__).resolve().parents[1] / ".env"
    
    env_vars = {}
    if env_path.exists():
        with open(env_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    if '=' in line:
                        key, value = line.split('=', 1)
                        value = value.strip().strip('"').strip("'")
                        env_vars[key] = value
    
    env_vars["DATA_SOURCE"] = request.dataSource
    env_vars["CRAWL_URL"] = request.crawlUrl
    if request.tushareToken:
        env_vars["TUSHARE_TOKEN"] = request.tushareToken
    
    with open(env_path, 'w', encoding='utf-8') as f:
        for key, value in env_vars.items():
            if any(c in value for c in [' ', '#', '=']):
                f.write(f'{key}="{value}"\n')
            else:
                f.write(f'{key}={value}\n')
    
    return {
        "status": "ok",
        "message": "数据源配置已保存",
        "dataSource": request.dataSource,
        "crawlUrl": request.crawlUrl,
    }


@app.get("/api/config/data-source")
def get_data_source_config() -> dict:
    config = get_runtime_config()
    return {
        "dataSource": config["dataSource"],
        "crawlUrl": config["crawlUrl"],
        "hasTushareToken": config["tushareTokenConfigured"],
        "tushareTokenConfigured": config["tushareTokenConfigured"],
        "maskedTushareToken": config["maskedTushareToken"],
    }

    # Legacy environment-only response kept unreachable for compatibility cleanup.
    """获取当前数据源配置"""
    import os
    return {
        "dataSource": os.getenv("DATA_SOURCE", "local_file"),
        "crawlUrl": os.getenv("CRAWL_URL", "https://finance.eastmoney.com/"),
        "hasTushareToken": bool(os.getenv("TUSHARE_TOKEN")),
    }


market_data_crawler = MarketDataCrawlerService()


@app.post("/api/data/fetch")
async def fetch_stock_data(request: dict):
    """手动触发爬虫/API 获取数据，自动保存到所有需要的目录（与聊天工具共用服务）"""
    try:
        arguments = normalize_fetch_request(request)
    except ValueError as exc:
        return {"status": "error", "message": str(exc)}
    return market_data_crawler.fetch(arguments)


# ================================================================
# 聊天入口
# ================================================================


def _build_chat_model_safely():
    """模型不可用（缺少依赖或密钥）时降级为关键词路由。"""
    try:
        return build_chat_model()
    except Exception:
        return None


def _start_analysis_from_chat(
    stock_code: str,
    analysis_date: str,
    background_tasks: BackgroundTasks | None = None,
) -> str:
    created = create_analysis_task(stock_code, analysis_date, background_tasks)
    return created["taskId"]


_local_tools = discover_local_tools({
    "stock_prediction": StockPredictionTool(start_task=_start_analysis_from_chat),
    "market_data_crawler": MarketDataCrawlerTool(crawler=market_data_crawler),
})
algorithm_manager = AlgorithmManager(
    Path(os.getenv("ALGORITHM_REGISTRY_PATH", str(Path(__file__).resolve().parent / "algorithm_registry.json"))),
    _local_tools,
    defaults=[
        {"name": name, "description": tool.description, "required_parameters": list(tool.required_parameters), "kind": "python", "local_tool": name}
        for name, tool in _local_tools.items()
    ],
)
app.include_router(build_algorithm_router(algorithm_manager))

chat_orchestrator = ChatOrchestrator(
    algorithm_manager.registry,
    model_factory=_build_chat_model_safely,
)


class ChatRequest(BaseModel):
    conversationId: str | None = None
    message: str = Field(min_length=1, max_length=8000)
    clientMessageId: str = ""


@app.post("/api/chat/messages", response_model=ChatResponse)
def send_chat_message(
    request: ChatRequest,
    background_tasks: BackgroundTasks,
) -> ChatResponse:
    text = request.message.strip()
    if not text:
        raise HTTPException(status_code=400, detail="消息不能为空")
    return chat_orchestrator.handle(
        request.conversationId,
        text,
        background_tasks=background_tasks,
    )
