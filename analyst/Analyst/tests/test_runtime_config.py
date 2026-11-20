from __future__ import annotations

import json
import sys
import types
from concurrent.futures import ThreadPoolExecutor

import pytest

from services import runtime_config


def _fake_langchain_openai(chat_openai_class):
    module = types.ModuleType("langchain_openai")
    module.ChatOpenAI = chat_openai_class
    return module


@pytest.fixture
def config_store(tmp_path, monkeypatch):
    path = tmp_path / "server_runtime_config.json"
    monkeypatch.setattr(runtime_config, "RUNTIME_CONFIG_PATH", path)
    monkeypatch.setenv("CONFIG_ENCRYPTION_KEY", "competition-secret")
    return path


def test_non_sensitive_values_survive_a_reload(config_store):
    runtime_config.update_runtime_config(
        {
            "quickThinkLlm": "model-a",
            "timeout": 90,
            "dataSource": "baostock",
        }
    )

    public = runtime_config.get_runtime_config()

    assert public["quickThinkLlm"] == "model-a"
    assert public["timeout"] == 90
    assert public["dataSource"] == "baostock"


def test_secrets_are_encrypted_and_can_be_decrypted(config_store):
    runtime_config.update_runtime_config(
        {"apiKey": "sk-secret-value", "tushareToken": "tushare-secret-value"}
    )

    persisted_text = config_store.read_text(encoding="utf-8")
    internal = runtime_config.get_runtime_config_internal()
    public = runtime_config.get_runtime_config()

    assert "sk-secret-value" not in persisted_text
    assert "tushare-secret-value" not in persisted_text
    assert internal["api_key"] == "sk-secret-value"
    assert internal["tushare_token"] == "tushare-secret-value"
    assert public["apiKeyConfigured"] is True
    assert public["tushareTokenConfigured"] is True
    assert "api_key" not in public
    assert "tushare_token" not in public


def test_blank_or_masked_secret_preserves_existing_ciphertext(config_store):
    runtime_config.update_runtime_config({"apiKey": "sk-secret-value"})
    before = json.loads(config_store.read_text(encoding="utf-8"))["_secrets"]["api_key"]

    runtime_config.update_runtime_config({"apiKey": ""})
    runtime_config.update_runtime_config({"apiKey": "sk-****alue"})

    after = json.loads(config_store.read_text(encoding="utf-8"))["_secrets"]["api_key"]
    assert after == before
    assert runtime_config.get_runtime_config_internal()["api_key"] == "sk-secret-value"


def test_explicit_clear_removes_only_requested_secret(config_store):
    runtime_config.update_runtime_config(
        {"apiKey": "sk-secret-value", "tushareToken": "tushare-secret-value"}
    )

    runtime_config.update_runtime_config({"clearApiKey": True})

    internal = runtime_config.get_runtime_config_internal()
    assert internal.get("api_key") in (None, "")
    assert internal["tushare_token"] == "tushare-secret-value"


def test_missing_master_key_rejects_secret_save(config_store, monkeypatch):
    monkeypatch.delenv("CONFIG_ENCRYPTION_KEY")

    with pytest.raises(runtime_config.RuntimeConfigEncryptionError, match="CONFIG_ENCRYPTION_KEY"):
        runtime_config.update_runtime_config({"apiKey": "sk-secret-value"})


def test_wrong_master_key_does_not_destroy_ciphertext(config_store, monkeypatch):
    runtime_config.update_runtime_config({"apiKey": "sk-secret-value"})
    before = config_store.read_bytes()
    monkeypatch.setenv("CONFIG_ENCRYPTION_KEY", "wrong-secret")

    with pytest.raises(runtime_config.RuntimeConfigEncryptionError):
        runtime_config.get_runtime_config_internal()

    assert config_store.read_bytes() == before


def test_concurrent_updates_always_leave_valid_json(config_store):
    def save(index: int) -> None:
        runtime_config.update_runtime_config({"timeout": 100 + index})

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(save, range(20)))

    persisted = json.loads(config_store.read_text(encoding="utf-8"))
    assert persisted["llm_timeout"] in range(100, 120)


def test_environment_values_are_initial_fallbacks(config_store, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "environment-api-key")
    monkeypatch.setenv("DATA_SOURCE", "baostock")

    internal = runtime_config.get_runtime_config_internal()

    assert internal["api_key"] == "environment-api-key"
    assert internal["data_source"] == "baostock"


def test_obsolete_analyst_concurrency_is_ignored_and_not_public(config_store):
    runtime_config.update_runtime_config({"analystConcurrency": 1})

    public = runtime_config.get_runtime_config()
    persisted = json.loads(config_store.read_text(encoding="utf-8"))

    assert "analystConcurrency" not in public
    assert "llm_analyst_concurrency" not in persisted


def test_resolve_tushare_token_prefers_request_then_saved_runtime_value(config_store):
    runtime_config.update_runtime_config({"tushareToken": "saved-token"})

    assert runtime_config.resolve_tushare_token("request-token") == "request-token"
    assert runtime_config.resolve_tushare_token("") == "saved-token"
    assert runtime_config.resolve_tushare_token(None) == "saved-token"


def test_build_chat_model_uses_current_runtime_llm_settings(config_store, monkeypatch):
    captured: dict = {}

    class RecordingChatOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setitem(
        sys.modules,
        "langchain_openai",
        _fake_langchain_openai(RecordingChatOpenAI),
    )
    runtime_config.update_runtime_config(
        {"quickThinkLlm": "model-fast", "timeout": 33, "apiKey": "sk-runtime-key"}
    )

    model = runtime_config.build_chat_model()

    assert isinstance(model, RecordingChatOpenAI)
    assert captured["model"] == "model-fast"
    assert captured["timeout"] == 33
    assert captured["api_key"] == "sk-runtime-key"


def test_build_chat_model_accepts_an_explicit_model(config_store, monkeypatch):
    captured: dict = {}

    class RecordingChatOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setitem(
        sys.modules,
        "langchain_openai",
        _fake_langchain_openai(RecordingChatOpenAI),
    )
    runtime_config.build_chat_model("deepseek-chat")

    assert captured["model"] == "deepseek-chat"
