"""Thread-safe runtime configuration with encrypted credential persistence."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import tempfile
import threading
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

RUNTIME_CONFIG_PATH = Path(os.getenv("RUNTIME_CONFIG_PATH", "server_runtime_config.json"))

_lock = threading.RLock()


class RuntimeConfigError(Exception):
    """Base class for safe, user-facing configuration errors."""


class RuntimeConfigValidationError(RuntimeConfigError):
    """Raised when a submitted configuration value is invalid."""


class RuntimeConfigEncryptionError(RuntimeConfigError):
    """Raised when credentials cannot be encrypted or decrypted."""


PERSISTED_KEYS = (
    "data_dir",
    "data_cache",
    "result",
    "deep_think_llm",
    "quick_think_llm",
    "base_url",
    "llm_timeout",
    "llm_max_retries",
    "data_source",
    "crawl_url",
)

CAMEL_TO_SNAKE = {
    "dataDir": "data_dir",
    "dataCache": "data_cache",
    "resultDir": "result",
    "quickThinkLlm": "quick_think_llm",
    "deepThinkLlm": "deep_think_llm",
    "baseUrl": "base_url",
    "apiKey": "api_key",
    "tushareToken": "tushare_token",
    "timeout": "llm_timeout",
    "maxRetries": "llm_max_retries",
    "dataSource": "data_source",
    "crawlUrl": "crawl_url",
    "clearApiKey": "clear_api_key",
    "clearTushareToken": "clear_tushare_token",
}

SECRET_FIELDS = ("api_key", "tushare_token")
SUPPORTED_DATA_SOURCES = {"local_file", "baostock", "tushare"}


def mask_api_key(secret: str | None) -> str | None:
    if not secret:
        return None
    value = secret.strip()
    if len(value) <= 8:
        return "****"
    return f"{value[:3]}****{value[-4:]}"


def _load_persisted() -> dict[str, Any]:
    if not RUNTIME_CONFIG_PATH.is_file():
        return {}
    try:
        with RUNTIME_CONFIG_PATH.open(encoding="utf-8") as file:
            data = json.load(file)
    except (json.JSONDecodeError, OSError) as exc:
        raise RuntimeConfigError("运行时配置文件无法读取") from exc
    if not isinstance(data, dict):
        raise RuntimeConfigError("运行时配置文件格式无效")
    return data


def _save_persisted(data: dict[str, Any]) -> None:
    directory = RUNTIME_CONFIG_PATH.parent
    directory.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=directory,
            prefix=f".{RUNTIME_CONFIG_PATH.name}.",
            suffix=".tmp",
            delete=False,
        ) as file:
            temporary_path = Path(file.name)
            json.dump(data, file, indent=2, ensure_ascii=False)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary_path, RUNTIME_CONFIG_PATH)
    except OSError as exc:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
        raise RuntimeConfigError("运行时配置保存失败") from exc


def _normalize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {CAMEL_TO_SNAKE.get(key, key): value for key, value in payload.items()}


def _master_key() -> str:
    value = (os.getenv("CONFIG_ENCRYPTION_KEY") or "").strip()
    if not value:
        raise RuntimeConfigEncryptionError(
            "服务器未配置 CONFIG_ENCRYPTION_KEY，无法保存或读取敏感凭据"
        )
    return value


def _fernet(master_key: str, salt: bytes) -> Fernet:
    derived = hashlib.pbkdf2_hmac(
        "sha256", master_key.encode("utf-8"), salt, 390_000, dklen=32
    )
    return Fernet(base64.urlsafe_b64encode(derived))


def _salt_for_write(data: dict[str, Any]) -> bytes:
    encryption = data.setdefault("_encryption", {})
    encoded = encryption.get("salt")
    if encoded:
        try:
            return base64.urlsafe_b64decode(encoded.encode("ascii"))
        except (ValueError, UnicodeEncodeError) as exc:
            raise RuntimeConfigEncryptionError("配置加密盐格式无效") from exc
    salt = os.urandom(16)
    encryption["salt"] = base64.urlsafe_b64encode(salt).decode("ascii")
    return salt


def _decrypt_secrets(data: dict[str, Any]) -> dict[str, str]:
    encrypted = data.get("_secrets") or {}
    if not encrypted:
        return {}
    encoded_salt = (data.get("_encryption") or {}).get("salt")
    if not encoded_salt:
        raise RuntimeConfigEncryptionError("敏感凭据缺少加密盐")
    try:
        salt = base64.urlsafe_b64decode(encoded_salt.encode("ascii"))
        cipher = _fernet(_master_key(), salt)
        return {
            field: cipher.decrypt(token.encode("ascii")).decode("utf-8")
            for field, token in encrypted.items()
            if field in SECRET_FIELDS
        }
    except (InvalidToken, ValueError, UnicodeError) as exc:
        raise RuntimeConfigEncryptionError(
            "敏感凭据无法解密，请恢复原 CONFIG_ENCRYPTION_KEY 或显式重置凭据"
        ) from exc


def _validate(values: dict[str, Any]) -> None:
    for key in ("llm_timeout", "llm_max_retries"):
        if key in values:
            try:
                number = int(values[key])
            except (TypeError, ValueError) as exc:
                raise RuntimeConfigValidationError(f"{key} 必须是整数") from exc
            if number < 0 or (key != "llm_max_retries" and number == 0):
                raise RuntimeConfigValidationError(f"{key} 必须为正数")
            values[key] = number
    if "data_source" in values and values["data_source"] not in SUPPORTED_DATA_SOURCES:
        raise RuntimeConfigValidationError("dataSource 仅支持 local_file、baostock 或 tushare")


def get_runtime_config_internal() -> dict[str, Any]:
    from config import DEFAULT_CONFIG

    with _lock:
        persisted = _load_persisted()
        merged = {**DEFAULT_CONFIG}
        environment_values = {
            "api_key": os.getenv("DEEPSEEK_API_KEY"),
            "tushare_token": os.getenv("TUSHARE_TOKEN"),
            "base_url": os.getenv("DEEPSEEK_BASE_URL"),
            "quick_think_llm": os.getenv("QUICK_THINK_LLM"),
            "deep_think_llm": os.getenv("DEEP_THINK_LLM"),
            "llm_timeout": os.getenv("LLM_TIMEOUT"),
            "llm_max_retries": os.getenv("LLM_MAX_RETRIES"),
            "data_source": os.getenv("DATA_SOURCE"),
            "crawl_url": os.getenv("CRAWL_URL"),
        }
        merged.update(
            {key: value for key, value in environment_values.items() if value not in (None, "")}
        )
        merged.update({key: persisted[key] for key in PERSISTED_KEYS if key in persisted})
        merged.update(_decrypt_secrets(persisted))
        return merged


def get_runtime_config(include_secrets: bool = False) -> dict[str, Any]:
    with _lock:
        internal = get_runtime_config_internal()
        api_key = internal.get("api_key") or ""
        tushare_token = internal.get("tushare_token") or ""
        public = {
            "dataDir": internal.get("data_dir", "./data"),
            "dataCache": internal.get("data_cache", "./data_cache"),
            "resultDir": internal.get("result", "./result"),
            "quickThinkLlm": internal.get("quick_think_llm", "deepseek-chat"),
            "deepThinkLlm": internal.get("deep_think_llm", "deepseek-reasoner"),
            "baseUrl": internal.get("base_url", "https://api.deepseek.com"),
            "timeout": int(internal.get("llm_timeout", 120)),
            "maxRetries": int(internal.get("llm_max_retries", 3)),
            "dataSource": internal.get("data_source", "local_file"),
            "crawlUrl": internal.get("crawl_url", "https://finance.eastmoney.com/"),
            "apiKeyConfigured": bool(api_key),
            "maskedApiKey": mask_api_key(api_key),
            "tushareTokenConfigured": bool(tushare_token),
            "maskedTushareToken": mask_api_key(tushare_token),
            "apiKeyPersisted": bool(api_key),
        }
        if include_secrets:
            public["api_key"] = api_key or None
            public["tushare_token"] = tushare_token or None
        return public


def update_runtime_config(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = _normalize_payload(payload)
    _validate(normalized)

    with _lock:
        current = _load_persisted()
        updated = dict(current)
        for key in PERSISTED_KEYS:
            if key in normalized and normalized[key] is not None:
                updated[key] = normalized[key]

        secrets = dict(updated.get("_secrets") or {})
        for field in SECRET_FIELDS:
            clear_key = f"clear_{field}"
            if normalized.get(clear_key) is True:
                secrets.pop(field, None)
                continue
            if field not in normalized:
                continue
            value = str(normalized[field] or "").strip()
            if not value or "****" in value:
                continue
            salt = _salt_for_write(updated)
            secrets[field] = _fernet(_master_key(), salt).encrypt(
                value.encode("utf-8")
            ).decode("ascii")

        if secrets:
            updated["_secrets"] = secrets
        else:
            updated.pop("_secrets", None)
        _save_persisted(updated)
        return {"success": True, "config": get_runtime_config()}


def get_runtime_api_key() -> str | None:
    return get_runtime_config_internal().get("api_key")


def resolve_tushare_token(submitted_token: str | None) -> str | None:
    value = str(submitted_token or "").strip()
    if value:
        return value
    return get_runtime_config_internal().get("tushare_token")


def set_runtime_api_key(api_key: str | None) -> None:
    update_runtime_config({"api_key": api_key} if api_key else {"clear_api_key": True})


def build_chat_model(model: str | None = None) -> Any:
    """按当前运行时配置构建聊天与意图路由使用的模型客户端。"""
    from langchain_openai import ChatOpenAI

    from config import get_chat_openai_kwargs, get_config

    cfg = get_config()
    return ChatOpenAI(
        model=model or cfg.get("quick_think_llm") or "deepseek-chat",
        **get_chat_openai_kwargs(cfg),
    )


def build_llm_overrides(llm_config: dict[str, Any] | None) -> dict[str, Any]:
    if not llm_config:
        return {}
    normalized = _normalize_payload(llm_config)
    allowed = {
        "api_key",
        "base_url",
        "quick_think_llm",
        "deep_think_llm",
        "llm_timeout",
        "llm_max_retries",
    }
    return {
        key: value
        for key, value in normalized.items()
        if key in allowed and value is not None and not (isinstance(value, str) and not value.strip())
    }


def build_data_overrides(data_config: dict[str, Any] | None) -> dict[str, Any]:
    if not data_config:
        return {}
    normalized = _normalize_payload(data_config)
    return {
        key: str(normalized[key])
        for key in ("data_dir", "data_cache", "result")
        if normalized.get(key)
    }


def validate_symbol_token(symbol: str) -> str:
    code = symbol.split(".")[0].strip()
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", code):
        raise ValueError("股票代码格式不合法")
    return code
