"""S8 阿里云百炼（DashScope）适配：0 次真实调用、0 次外部连接。

覆盖「凭据解析 → model 构造」全链路，并反向验证 provider 锁定后
不会静默回退到别的 key（这会让真实调用误打到错误服务商、白烧额度）。
"""

from __future__ import annotations

import asyncio

import httpx
import pytest
from pydantic import SecretStr

from capabilities.llm import make_chat_model
from config.loader import (
    DASHSCOPE_BASE_URL,
    OPENROUTER_BASE_URL,
    LLMCredentials,
    MissingLLMCredentials,
    apply_overrides,
    load_settings,
    resolve_llm_credentials,
)
from evals.run_eval import eval_offline_guard

_KEY = "sk-unit-test-not-a-real-key"


def _mock_client() -> httpx.AsyncClient:
    """任何请求都会拿到 200 空响应；目的是让构造过程不发网络请求。"""
    return httpx.AsyncClient(
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json={}))
    )


def test_dashscope_credentials_resolve_with_official_compatible_base_url() -> None:
    creds = resolve_llm_credentials(
        environ={"LLM_PROVIDER": "dashscope", "DASHSCOPE_API_KEY": _KEY}
    )
    assert creds.provider == "dashscope"
    assert creds.base_url == DASHSCOPE_BASE_URL
    assert creds.resolved_key() == _KEY
    assert _KEY not in repr(creds), "SecretStr 不能让密钥出现在 repr / 日志里"


def test_llm_base_url_override_is_honored() -> None:
    creds = resolve_llm_credentials(
        environ={
            "LLM_PROVIDER": "dashscope",
            "DASHSCOPE_API_KEY": _KEY,
            "LLM_BASE_URL": "https://example.invalid/compatible/v1",
        }
    )
    assert creds.base_url == "https://example.invalid/compatible/v1"


def test_explicit_provider_does_not_fall_back_to_other_keys() -> None:
    """本机同时装了多个 key 时，锁定 dashscope 就必须用 dashscope。"""
    creds = resolve_llm_credentials(
        environ={
            "LLM_PROVIDER": "dashscope",
            "OPENROUTER_API_KEY": "sk-openrouter",
            "DASHSCOPE_API_KEY": _KEY,
        }
    )
    assert creds.provider == "dashscope"
    assert creds.resolved_key() == _KEY


def test_explicit_provider_without_key_raises_instead_of_falling_back() -> None:
    with pytest.raises(MissingLLMCredentials, match="缺少 DASHSCOPE_API_KEY"):
        resolve_llm_credentials(
            environ={"LLM_PROVIDER": "dashscope", "OPENROUTER_API_KEY": "sk-openrouter"}
        )


def test_unknown_provider_raises() -> None:
    with pytest.raises(MissingLLMCredentials, match="未知 LLM_PROVIDER"):
        resolve_llm_credentials(environ={"LLM_PROVIDER": "some-fake-provider"})


def test_existing_provider_priority_unchanged() -> None:
    """新增 provider 不能改变原有 OpenRouter → OpenAI → Gemini 顺序。"""
    assert (
        resolve_llm_credentials(
            environ={"OPENROUTER_API_KEY": "a", "OPENAI_API_KEY": "b"}
        ).base_url
        == OPENROUTER_BASE_URL
    )
    assert resolve_llm_credentials(environ={"OPENAI_API_KEY": "b"}).provider == "openai"
    assert resolve_llm_credentials(environ={"GEMINI_API_KEY": "c"}).provider == "gemini"
    assert resolve_llm_credentials(
        environ={"DASHSCOPE_API_KEY": _KEY, "GEMINI_API_KEY": "c"}
    ).provider == "dashscope"


def test_llm_model_env_var_feeds_all_roles() -> None:
    settings = load_settings(environ={"LLM_MODEL": "qwen-plus"})
    assert set(settings.models.roles.values()) == {"qwen-plus"}


def test_make_chat_model_uses_qwen_plus_and_dashscope_endpoint_offline() -> None:
    """真构造 ChatOpenAI 并核对端点/模型名；MockTransport 保证 0 外部连接。"""
    settings = apply_overrides(load_settings(), {"models.roles.briefing": "qwen-plus"})
    creds = LLMCredentials(
        provider="dashscope",
        api_key=SecretStr(_KEY),
        base_url=DASHSCOPE_BASE_URL,
    )
    client = _mock_client()
    try:
        with eval_offline_guard("S8 dashscope unit test") as attempts:
            model = make_chat_model(
                settings, "briefing", credentials=creds, http_async_client=client
            )
        assert attempts == []
        assert model.model_name == "qwen-plus"
        assert model.openai_api_base == DASHSCOPE_BASE_URL
        assert _KEY not in repr(model.model_dump())
    finally:
        asyncio.run(client.aclose())


def test_credentials_never_enter_settings_serialization() -> None:
    """凭据刻意不进 Settings，避免 model_dump / scorecard / 日志泄露。"""
    settings = load_settings(
        environ={
            "APP_MODE": "live",
            "LLM_PROVIDER": "dashscope",
            "LLM_MODEL": "qwen-plus",
        }
    )
    dumped = repr(settings.model_dump())
    assert _KEY not in dumped
    assert "DASHSCOPE_API_KEY" not in dumped


def test_no_key_still_raises_with_explicit_mode() -> None:
    with pytest.raises(MissingLLMCredentials, match="APP_MODE=fixture"):
        resolve_llm_credentials(environ={})
