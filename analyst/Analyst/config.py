import os
from pathlib import Path

DEFAULT_CONFIG = {
    "data_dir": "./data",
    "data_cache": "./data_cache",
    "result": "./result",
    "deep_think_llm": "deepseek-reasoner",
    "quick_think_llm": "deepseek-chat",
    "base_url": "https://api.deepseek.com",
    "api_key": "",
    "llm_timeout": 120,
    "llm_max_retries": 3,
    "data_source": "local_file",
    "crawl_url": "https://finance.eastmoney.com/",
}

# 兼容旧引用
config = DEFAULT_CONFIG.copy()


def _merge_config(base: dict, overrides: dict | None) -> dict:
    merged = base.copy()
    if overrides:
        for key, value in overrides.items():
            if value is None:
                continue
            if isinstance(value, str) and not value.strip():
                if key in ("api_key", "base_url", "quick_think_llm", "deep_think_llm"):
                    continue
            merged[key] = value
    return merged


def get_config(overrides: dict | None = None) -> dict:
    """
    配置优先级：overrides > runtime config > 环境变量 > 默认值。
    """
    from services.runtime_config import get_runtime_config_internal

    env_layer = {}
    if os.getenv("DEEPSEEK_BASE_URL"):
        env_layer["base_url"] = os.getenv("DEEPSEEK_BASE_URL")
    if os.getenv("QUICK_THINK_LLM"):
        env_layer["quick_think_llm"] = os.getenv("QUICK_THINK_LLM")
    if os.getenv("DEEP_THINK_LLM"):
        env_layer["deep_think_llm"] = os.getenv("DEEP_THINK_LLM")
    if os.getenv("LLM_TIMEOUT"):
        env_layer["llm_timeout"] = int(os.getenv("LLM_TIMEOUT", "120"))
    if os.getenv("LLM_MAX_RETRIES"):
        env_layer["llm_max_retries"] = int(os.getenv("LLM_MAX_RETRIES", "3"))
    if os.getenv("DEEPSEEK_API_KEY"):
        env_layer["api_key"] = os.getenv("DEEPSEEK_API_KEY")
    if os.getenv("TUSHARE_TOKEN"):
        env_layer["tushare_token"] = os.getenv("TUSHARE_TOKEN")
    if os.getenv("DATA_SOURCE"):
        env_layer["data_source"] = os.getenv("DATA_SOURCE")
    if os.getenv("CRAWL_URL"):
        env_layer["crawl_url"] = os.getenv("CRAWL_URL")

    merged = DEFAULT_CONFIG.copy()
    merged.update(env_layer)
    merged.update(get_runtime_config_internal())
    merged = _merge_config(merged, overrides)

    if not merged.get("api_key"):
        merged["api_key"] = os.getenv("DEEPSEEK_API_KEY") or ""
    if not merged.get("base_url"):
        merged["base_url"] = os.getenv("DEEPSEEK_BASE_URL") or DEFAULT_CONFIG["base_url"]
    merged["llm_timeout"] = int(merged.get("llm_timeout", 120))
    merged["llm_max_retries"] = int(merged.get("llm_max_retries", 3))
    return merged


def get_path_config(overrides: dict | None = None) -> dict[str, Path]:
    cfg = get_config(overrides)
    return {
        "data_dir": Path(cfg["data_dir"]).resolve(),
        "data_cache": Path(cfg["data_cache"]).resolve(),
        "result": Path(cfg["result"]).resolve(),
    }


def apply_data_paths(data_dir: str | Path, result_dir: str | Path) -> None:
    """在单次分析前切换工具读取路径（不修改 agent 核心逻辑）。"""
    import utils

    utils.DATA_DIR = str(Path(data_dir).resolve())
    utils.RESULT_DIR = str(Path(result_dir).resolve())


def get_chat_openai_kwargs(config: dict | None = None) -> dict:
    """构建 ChatOpenAI 通用连接参数（含 timeout / retry）。"""
    cfg = config or get_config()
    return {
        "base_url": cfg["base_url"],
        "api_key": cfg["api_key"],
        "timeout": cfg.get("llm_timeout", 120),
        "max_retries": cfg.get("llm_max_retries", 3),
    }


def build_runtime_config_view(cfg: dict) -> dict:
    from services.runtime_config import mask_api_key

    api_key = cfg.get("api_key") or ""
    return {
        "llmProvider": "deepseek",
        "quickThinkModel": cfg.get("quick_think_llm"),
        "deepThinkModel": cfg.get("deep_think_llm"),
        "baseUrl": cfg.get("base_url"),
        "apiKeyConfigured": bool(api_key),
        "maskedApiKey": mask_api_key(api_key),
        "dataDir": cfg.get("data_dir"),
        "dataCache": cfg.get("data_cache"),
        "resultDir": cfg.get("result"),
        "timeout": cfg.get("llm_timeout"),
        "maxRetries": cfg.get("llm_max_retries"),
    }


for path_key in ("data_dir", "data_cache", "result"):
    os.makedirs(DEFAULT_CONFIG[path_key], exist_ok=True)
