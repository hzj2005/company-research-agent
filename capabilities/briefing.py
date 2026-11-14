"""S5-B 简报结构化输出后端（fixture 用本地 mock，live 用真实模型）。

两种后端都返回**同一条 LCEL 链**：`prompt | model.with_structured_output(SectionBrief)`。

- `fixture`：`httpx.MockTransport` 注入 `ChatOpenAI`，handler 把 `<documents>` 里的每篇文档
  确定性转成 `Fact(claim=content, source_url=url, confidence=score)`。这是**确定性 stub，
  不是模型能力**：目的是在无 key、0 次网络请求下真跑 `with_structured_output`、
  校验重试与 URL 级回溯链路。
- `live`：`make_chat_model(settings, "briefing")` 接真实 provider；缺 key 明确抛
  `MissingLLMCredentials`，不回退 fixture。本阶段 **0 次 live 调用**。

mock 的 `base_url` 指向不可达本地端口：一旦注入失效，请求会立刻 connection refused
而不是静默走外网（S5.1 已用同样手法验证）。
"""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

import httpx
from langchain_core.runnables import Runnable
from pydantic import SecretStr

from capabilities.llm import make_chat_model
from capabilities.structured import make_extraction_chain
from config.loader import LLMCredentials, Settings

logger = logging.getLogger(__name__)

_UNREACHABLE_BASE_URL = "http://127.0.0.1:1/v1"


@dataclass
class BriefingBackend:
    chain: Runnable
    mode: str
    seen: list[str] = field(default_factory=list)
    client: httpx.AsyncClient | None = None
    # 记录模型实际指向的地址，供测试核对「完全离网」，而不是靠口头声明
    base_url: str | None = None

    async def aclose(self) -> None:
        if self.client is not None:
            await self.client.aclose()
            self.client = None


def _score_as_confidence(doc: dict[str, Any]) -> float:
    """兑现 ACTION_PLAN 9.4：stub 的 confidence 取文档 score，不硬编码。

    缺失或非数值记 0.0（不伪造高置信度），并夹到 Fact 契约的 [0, 1] 区间。
    """
    try:
        return max(0.0, min(1.0, float(doc.get("score", 0.0) or 0.0)))
    except (TypeError, ValueError):
        return 0.0


def _fixture_payload(human: str) -> dict[str, Any]:
    """从 prompt 的 <documents> 里确定性构造 SectionBrief，不使用任何外部知识。"""
    lines = human.splitlines()
    section = "company"
    docs: list[dict[str, Any]] = []
    inside = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("section:"):
            section = stripped.split(":", 1)[1].strip()
            continue
        if stripped == "<documents>":
            inside = True
            continue
        if stripped == "</documents>":
            inside = False
            continue
        if inside and stripped.startswith("{"):
            try:
                docs.append(json.loads(stripped))
            except json.JSONDecodeError:
                continue
    facts = [
        {
            "claim": d["content"],
            "source_url": d["url"],
            "confidence": _score_as_confidence(d),
        }
        for d in docs
        if d.get("url") and d.get("content")
    ]
    return {"section": section, "facts": facts, "degraded": False}


def _mock_completion(request: httpx.Request, seen: list[str]) -> httpx.Response:
    body = json.loads(request.content)
    messages = body.get("messages", [])
    # ChatPromptTemplate 的 ("human", ...) 在 OpenAI 请求体里 role 是 "user"；
    # content 也可能是多模态的 part list，这里统一取文本。
    content: Any = ""
    for message in reversed(messages):
        if message.get("role") in ("user", "human"):
            content = message.get("content", "")
            break
    if isinstance(content, list):
        content = "".join(
            part.get("text", "") for part in content if isinstance(part, dict)
        )
    human = content if isinstance(content, str) else str(content)
    seen.append(human)
    payload = _fixture_payload(human)
    return httpx.Response(
        200,
        json={
            "id": "chatcmpl-fixture-stub",
            "object": "chat.completion",
            "created": 0,
            "model": body.get("model", "fixture-stub"),
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "tool_calls",
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_fixture_1",
                                "type": "function",
                                "function": {
                                    "name": "SectionBrief",
                                    "arguments": json.dumps(payload, ensure_ascii=False),
                                },
                            }
                        ],
                    },
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        },
    )


def make_briefing_backend(settings: Settings) -> BriefingBackend:
    """按 app.mode 构造简报抽取后端。fixture 完全离网，live 需模型 key。"""
    if settings.app.mode == "fixture":
        seen: list[str] = []
        client = httpx.AsyncClient(
            transport=httpx.MockTransport(lambda req: _mock_completion(req, seen))
        )
        creds = LLMCredentials(
            provider="openai",
            api_key=SecretStr("fixture-stub-not-a-real-key"),
            base_url=_UNREACHABLE_BASE_URL,
        )
        model = make_chat_model(
            settings, "briefing", credentials=creds, http_async_client=client
        )
        return BriefingBackend(
            chain=make_extraction_chain(model),
            mode="fixture",
            seen=seen,
            client=client,
            base_url=_UNREACHABLE_BASE_URL,
        )

    model = make_chat_model(settings, "briefing")
    logger.warning("live 简报后端已构造；是否发起真实模型调用取决于后续节点执行")
    return BriefingBackend(chain=make_extraction_chain(model), mode="live")


@asynccontextmanager
async def briefing_backend_scope(
    settings: Settings,
) -> AsyncIterator[BriefingBackend | None]:
    """生产路径专用：把 backend 的所有权交给「一次图运行」。

    `make_briefing_backend()` 会为 fixture 构造一个 `httpx.AsyncClient`，必须由调用方
    在图跑完后 `aclose()`；否则长驻的 FastAPI `/research` 每来一个请求就泄漏一个
    client（S5-B 复查实测：5 次运行 → 5 个未关闭）。

    `structured_output=false` 时不构造 backend，直接 yield None（A/B 基线路径）。
    Studio 入口是模块级单例、随 Server 进程存活，**不走这个 scope**，避免被提前关闭。
    """
    if not settings.features.structured_output:
        yield None
        return

    backend = make_briefing_backend(settings)
    try:
        yield backend
    finally:
        await backend.aclose()
