"""S5.1 验收：无 key、无网络真跑 `with_structured_output` 全链路。

前置探针实测 LangChain 自带 `GenericFakeChatModel` 不支持 `with_structured_output`
（NotImplementedError），因此用 `httpx.MockTransport` 注入 `ChatOpenAI` 的
`http_async_client`。这是**真实的 LangChain 调用链**，只是把 HTTP 层换成本地响应；
不代表任何真实模型能力，也不产生准确率/延迟数字。
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from capabilities.llm import make_chat_model
from capabilities.structured import (
    ExtractionResult,
    extract_section_brief,
    make_extraction_chain,
)
from config.loader import (
    LLMCredentials,
    MissingLLMCredentials,
    Settings,
    get_settings,
    resolve_llm_credentials,
)
from graph.contracts import Fact, SectionBrief

DOCS: list[dict[str, Any]] = [
    {"url": "https://example.org/a", "title": "Source A", "content": "公司成立于 2013 年"},
]
# base_url 故意指向不可达的本地端口：MockTransport 会拦截所有请求；
# 一旦注入失效、请求真的出网，会立刻 connection refused 而不是静默走外网。
# 这是「本测试完全离网」的硬保证，不是靠口头声明。
CREDS = LLMCredentials(
    provider="openai",
    api_key=SecretStr("dummy"),
    base_url="http://127.0.0.1:1/v1",
)


def _legal(section: str = "company") -> dict[str, Any]:
    return {
        "section": section,
        "facts": [
            {
                "claim": "公司成立于 2013 年",
                "source_url": "https://example.org/a",
                "confidence": 0.9,
            }
        ],
        "degraded": False,
    }


def _completion(payload: dict[str, Any]) -> dict[str, Any]:
    """构造 OpenAI 兼容的 tool_calls 响应（method="function_calling" 走这条路径）。"""
    return {
        "id": "chatcmpl-mock",
        "object": "chat.completion",
        "created": 0,
        "model": "mock",
        "choices": [
            {
                "index": 0,
                "finish_reason": "tool_calls",
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_mock",
                            "type": "function",
                            "function": {
                                "name": "SectionBrief",
                                "arguments": json.dumps(payload),
                            },
                        }
                    ],
                },
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


def _client(payloads: list[dict[str, Any]], seen: list[dict[str, Any]]) -> httpx.AsyncClient:
    it = iter(payloads)
    last = payloads[-1]

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        payload = next(it, last)
        return httpx.Response(200, json=_completion(payload))

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def _extract(
    payloads: list[dict[str, Any]],
    *,
    docs: list[dict[str, Any]] | None = None,
    settings: Settings | None = None,
) -> tuple[ExtractionResult, list[dict[str, Any]]]:
    s = settings or get_settings()
    seen: list[dict[str, Any]] = []
    client = _client(payloads, seen)
    try:
        model = make_chat_model(
            s, "briefing", credentials=CREDS, http_async_client=client
        )
        chain = make_extraction_chain(model)
        result = await extract_section_brief(
            chain,
            section="company",
            company="X",
            docs=DOCS if docs is None else docs,
            settings=s,
        )
        return result, seen
    finally:
        await client.aclose()


def test_structured_output_runs_without_api_key() -> None:
    result, seen = asyncio.run(_extract([_legal()]))
    assert len(seen) == 1, "必须真的发出一次 LangChain 调用，不是本地伪造对象"
    assert isinstance(result.brief, SectionBrief)
    assert result.brief.degraded is False
    assert len(result.brief.facts) == 1
    assert str(result.brief.facts[0].source_url).rstrip("/") == "https://example.org/a"
    assert any(n["status"] == "ok" for n in result.notes)


def test_missing_source_url_retries_then_degrades() -> None:
    """缺 source_url 被 Pydantic 拦下；重试耗尽后整栏降级，不静默丢字段。"""
    bad = {
        "section": "company",
        "facts": [{"claim": "无来源", "confidence": 0.9}],
        "degraded": False,
    }
    result, seen = asyncio.run(_extract([bad, bad]))
    assert len(seen) == get_settings().models.max_retries + 1
    assert result.brief.degraded is True
    assert result.brief.facts == []
    assert "校验失败" in (result.brief.degrade_reason or "")
    failures = [n for n in result.notes if n["status"] == "validation_failed"]
    assert len(failures) == 2
    assert all("source_url" in n["error"] for n in failures)
    assert any(n["status"] == "degraded" for n in result.notes)


def test_validation_failure_then_success_on_retry() -> None:
    first = {
        "section": "company",
        "facts": [{"claim": "缺来源", "confidence": 0.9}],
        "degraded": False,
    }
    result, seen = asyncio.run(_extract([first, _legal()]))
    assert len(seen) == 2
    assert result.brief.degraded is False
    assert len(result.brief.facts) == 1
    assert [n["status"] for n in result.notes] == ["validation_failed", "ok"]


def test_fact_with_unknown_url_is_dropped_with_note() -> None:
    """模型编造了文档里没有的 URL：剔除并留痕，绝不静默。"""
    forged = {
        "section": "company",
        "facts": [
            {"claim": "编造", "source_url": "https://evil.example/fake", "confidence": 0.9}
        ],
        "degraded": False,
    }
    result, _ = asyncio.run(_extract([forged]))
    assert result.brief.facts == []
    assert result.brief.degraded is True
    dropped = [n for n in result.notes if n["status"] == "dropped_uncited_facts"]
    assert len(dropped) == 1
    assert dropped[0]["urls"] == ["https://evil.example/fake"]


def test_no_documents_short_circuits_without_calling_model() -> None:
    result, seen = asyncio.run(_extract([_legal()], docs=[]))
    assert seen == [], "没有文档时不应调用模型"
    assert result.brief.degraded is True
    assert result.notes[0]["reason"] == "本栏目没有可用文档"


def test_model_name_comes_from_settings_roles() -> None:
    """禁止硬编码模型名：改配置后请求体里的 model 必须跟着变。"""
    base = get_settings()
    custom = base.model_copy(
        update={
            "models": base.models.model_copy(
                update={"roles": {**base.models.roles, "briefing": "my/custom-model"}}
            )
        }
    )
    _, seen = asyncio.run(_extract([_legal()], settings=custom))
    assert seen[0]["model"] == "my/custom-model"
    assert seen[0]["temperature"] == custom.models.temperature


def test_resolve_llm_credentials_priority_and_no_secret_leak() -> None:
    creds = resolve_llm_credentials(
        environ={"OPENROUTER_API_KEY": "topsecret", "OPENAI_API_KEY": "other"}
    )
    assert creds.provider == "openrouter"
    assert creds.base_url == "https://openrouter.ai/api/v1"
    assert creds.resolved_key() == "topsecret"
    assert "topsecret" not in repr(creds), "SecretStr 不能让密钥出现在 repr / 日志里"
    assert resolve_llm_credentials(environ={"OPENAI_API_KEY": "k"}).provider == "openai"
    with pytest.raises(MissingLLMCredentials) as exc:
        resolve_llm_credentials(environ={})
    assert "APP_MODE=fixture" in str(exc.value)


def test_contracts_forbid_extra_fields() -> None:
    with pytest.raises(ValidationError):
        Fact(
            claim="x",
            source_url="https://example.org/a",  # type: ignore[arg-type]
            confidence=0.9,
            bogus=1,  # type: ignore[call-arg]
        )
    with pytest.raises(ValidationError):
        SectionBrief(section="company", facts=[], unexpected=True)  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        Fact(
            claim="x",
            source_url="https://example.org/a",  # type: ignore[arg-type]
            confidence=1.5,
        )


def test_make_chat_model_rejects_unknown_role() -> None:
    with pytest.raises(ValueError, match="未知模型角色"):
        make_chat_model(get_settings(), "not_a_role", credentials=CREDS)


def test_extraction_prompt_requires_chinese_and_separate_facts() -> None:
    """两个容易回退的要求：中文输出、不把多个事实揉成一句。

    同时守住原有红线（禁止编造、只能引用给定 URL），防止改提示词时顺手删掉。
    """
    from capabilities.structured import _SYSTEM_PROMPT

    assert "简体中文" in _SYSTEM_PROMPT
    assert "合并" in _SYSTEM_PROMPT
    assert "禁止编造" in _SYSTEM_PROMPT
    assert "source_url" in _SYSTEM_PROMPT
