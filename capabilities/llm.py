"""S5 配置驱动的 LLM 工厂。

与上游 `backend/llm.py` 的区别（后者保留原样，不复用）：
- 模型名只从 `settings.models.roles[role]` 读，不硬编码；
- 温度 / 重试次数从 `settings.models` 读；
- 凭据经 `config.loader.resolve_llm_credentials()` 解析，业务层不碰 `os.getenv`；
- `http_async_client` 可注入，让 `httpx.MockTransport` 在**无 key、无网络**下真跑
  `with_structured_output` 全链路（S5 前置探针已验证）。

fixture 模式不调用本模块：确定性 stub 由 `capabilities/retrieval.py` 提供。
"""

from __future__ import annotations

import httpx
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI

from config.loader import (
    LLMCredentials,
    Settings,
    resolve_llm_credentials,
)

# 仅是 OpenRouter 要求的归因 header，不是模型名/阈值/密钥
_OPENROUTER_HEADERS = {
    "HTTP-Referer": "https://github.com/guy-hartstein/company-research-agent",
    "X-Title": "Company Research Agent",
}


def make_chat_model(
    settings: Settings,
    role: str,
    *,
    credentials: LLMCredentials | None = None,
    http_async_client: httpx.AsyncClient | None = None,
) -> BaseChatModel:
    """按角色构造 BaseChatModel。role 必须存在于 `settings.models.roles`。"""
    if role not in settings.models.roles:
        raise ValueError(
            f"未知模型角色 {role!r}；可选：{sorted(settings.models.roles)}"
        )
    model_name = settings.models.roles[role]
    creds = credentials or resolve_llm_credentials()
    common = {
        "model": model_name,
        "temperature": settings.models.temperature,
        "max_retries": settings.models.max_retries,
    }

    if creds.provider == "gemini":
        if http_async_client is not None:
            raise ValueError("Gemini 路径不支持注入 http_async_client，请用 OpenAI 兼容 provider")
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(
            **common,
            google_api_key=creds.resolved_key(),
        )

    kwargs: dict[str, object] = {**common, "api_key": creds.resolved_key()}
    if creds.base_url:
        kwargs["base_url"] = creds.base_url
    if http_async_client is not None:
        kwargs["http_async_client"] = http_async_client
    if creds.provider == "openrouter":
        kwargs["default_headers"] = dict(_OPENROUTER_HEADERS)
    return ChatOpenAI(**kwargs)
