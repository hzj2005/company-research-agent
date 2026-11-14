"""S5-B 8.2 验收：Tavily 额度护栏 + BaseRetriever 契约。

**本文件 0 次真实 Tavily 调用、0 次网络请求、0 次 `AsyncTavilyClient` 构造。**
所有 live 编排都通过注入 fake client / fake retriever 验证；真实 API 行为未实测，
不写任何准确率、延迟、成本数字。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from pydantic import ConfigDict, Field

from capabilities.retrieval import build_live_query, make_document_tool
from capabilities.tavily_retriever import (
    CallBudget,
    LiveRetrievalDisabled,
    TavilyBudgetExceeded,
    TavilyRetriever,
    build_live_retrievers,
    documents_from_results,
)
from config.loader import (
    MissingTavilyCredentials,
    get_settings,
    load_settings,
    resolve_tavily_credentials,
)


def _live_settings(**overrides: str) -> Any:
    env = {
        "APP_MODE": "live",
        "TAVILY_LIVE_ENABLED": "true",
        "TAVILY_MAX_CALLS": "2",
        "TAVILY_DRY_RUN": "false",
        **overrides,
    }
    return load_settings(environ=env)


class FakeTavilyClient:
    """记录每次 search 调用；任何真实请求都会在这里留下证据。"""

    def __init__(self, results: list[dict[str, Any]] | None = None):
        self.calls: list[dict[str, Any]] = []
        self.results = results if results is not None else [
            {"url": "https://example.org/a", "title": "A", "content": "事实 A", "score": 0.9},
            {"url": "https://example.org/b", "title": "B", "content": "事实 B", "score": 0.8},
        ]

    async def search(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return {"results": self.results}


class ExplodingTavilyClient:
    """一旦被构造就失败，用来证明 fixture / 注入路径没碰真实 SDK。"""

    def __init__(self, *args: Any, **kwargs: Any):
        raise AssertionError("不应构造 AsyncTavilyClient（会消耗真实额度）")


class FakeRetriever(BaseRetriever):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    calls: list[str] = Field(default_factory=list)

    def _get_relevant_documents(self, query: str, **kwargs: Any) -> list[Document]:
        return self._docs(query)

    async def _aget_relevant_documents(self, query: str, **kwargs: Any) -> list[Document]:
        return self._docs(query)

    def _docs(self, query: str) -> list[Document]:
        self.calls.append(query)
        return [
            Document(
                page_content=f"raw:{query}",
                metadata={
                    "url": "https://fake.local/a",
                    "title": "Fake",
                    "score": 0.95,
                    "section": "company",
                    "source": "fake",
                },
            )
        ]


def _retriever(client: FakeTavilyClient, budget: CallBudget, cache_dir: Path) -> TavilyRetriever:
    return TavilyRetriever(
        client=client,
        budget=budget,
        cache_dir=cache_dir,
        section="company",
        max_results=3,
        search_depth="advanced",
        topic="general",
    )


# ---------------------------------------------------------------- 护栏默认值

def test_default_settings_never_allow_real_calls() -> None:
    s = get_settings()
    assert s.app.mode == "fixture"
    assert s.retrieval.live.enabled is False
    assert s.retrieval.live.max_calls_per_run == 0
    assert s.retrieval.live.dry_run is False


@pytest.mark.parametrize(
    "overrides",
    [
        {"TAVILY_LIVE_ENABLED": "false"},
        {"TAVILY_MAX_CALLS": "0"},
    ],
)
def test_live_requires_all_three_optins(overrides: dict[str, str]) -> None:
    s = _live_settings(**overrides)
    with pytest.raises(LiveRetrievalDisabled, match="默认禁用|TAVILY_MAX_CALLS"):
        make_document_tool(s)


def test_fixture_mode_wins_even_when_live_flags_are_set() -> None:
    """APP_MODE=fixture 是第一道闸：即使误开了 live 开关也只返回本地样本。"""
    s = _live_settings(APP_MODE="fixture")
    tool = make_document_tool(s)
    out = asyncio.run(tool.ainvoke({"company": "Notion", "sections": ["company"], "round_no": 0}))
    assert out["company"][0]["source"] != "tavily"


def test_fixture_mode_never_constructs_tavily_client(monkeypatch: pytest.MonkeyPatch) -> None:
    import tavily

    monkeypatch.setattr(tavily, "AsyncTavilyClient", ExplodingTavilyClient)
    tool = make_document_tool(get_settings())
    out = asyncio.run(tool.ainvoke({"company": "Notion", "sections": ["company"], "round_no": 0}))
    assert len(out["company"]) > 0, "fixture 模式应仍返回合成文档"


def test_missing_key_is_explicit_and_never_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    with pytest.raises(MissingTavilyCredentials):
        resolve_tavily_credentials(environ={})
    # live + opt-in 但不给 key：直接报错，不静默回退 fixture
    with pytest.raises(MissingTavilyCredentials):
        make_document_tool(_live_settings())


def test_credentials_are_secret_and_never_printed() -> None:
    creds = resolve_tavily_credentials(environ={"TAVILY_API_KEY": "super-secret-value"})
    assert creds.resolved_key() == "super-secret-value"
    assert "super-secret-value" not in repr(creds)
    assert "super-secret-value" not in str(creds.model_dump())


# ---------------------------------------------------------------- 预算与缓存

def test_budget_blocks_second_real_call(tmp_path: Path) -> None:
    client = FakeTavilyClient()
    budget = CallBudget(1)
    r = _retriever(client, budget, tmp_path)

    asyncio.run(r.ainvoke("query A"))
    assert budget.calls_made == 1 and len(client.calls) == 1
    with pytest.raises(TavilyBudgetExceeded, match="预算已用尽"):
        asyncio.run(r.ainvoke("query B"))
    assert len(client.calls) == 1, "超额后绝不能再发请求"


def test_cache_hit_does_not_consume_budget(tmp_path: Path) -> None:
    client = FakeTavilyClient()
    budget = CallBudget(1)
    r = _retriever(client, budget, tmp_path)

    first = asyncio.run(r.ainvoke("query A"))
    second = asyncio.run(r.ainvoke("query A"))
    assert [d.metadata["url"] for d in second] == [d.metadata["url"] for d in first]
    assert budget.calls_made == 1
    assert budget.cache_hits == 1
    assert len(client.calls) == 1, "缓存命中不得触发真实请求"
    with pytest.raises(TavilyBudgetExceeded):
        asyncio.run(r.ainvoke("query B"))  # 缓存没有凭空多出额度


def test_dry_run_never_calls_client(tmp_path: Path) -> None:
    client = FakeTavilyClient()
    budget = CallBudget(5, dry_run=True)
    r = _retriever(client, budget, tmp_path)

    assert asyncio.run(r.ainvoke("query A")) == []
    assert client.calls == []
    assert budget.calls_made == 0
    assert budget.dry_runs == 1


def test_document_conversion_drops_url_less_results() -> None:
    docs = documents_from_results(
        [
            {"url": "https://example.org/a", "title": "A", "content": "x", "score": "0.7"},
            {"title": "无 URL", "content": "应被丢弃"},
            {"url": "https://example.org/c", "content": "分数非法", "score": "n/a"},
        ],
        section="news",
    )
    assert len(docs) == 2
    assert docs[0].metadata["section"] == "news"
    assert docs[0].metadata["score"] == 0.7
    assert docs[1].metadata["score"] == 0.0
    assert all(d.metadata["source"] == "tavily" for d in docs)


# ---------------------------------------------------------------- 工具编排

def test_live_tool_with_injected_fake_retriever(tmp_path: Path) -> None:
    """注入离线替身，验证 live 编排链路，且 0 次真实 client 构造。"""
    s = _live_settings()
    fake = FakeRetriever()
    tool = make_document_tool(
        s,
        retriever_factory=lambda _s: {section: fake for section in _s.graph.sections},
        budget=CallBudget(3),
        cache_dir=tmp_path,
    )
    out = asyncio.run(
        tool.ainvoke({"company": "Notion", "sections": ["company", "news"], "round_no": 0})
    )
    assert set(out) == {"company", "news"}
    assert out["company"][0]["url"] == "https://fake.local/a"
    assert out["company"][0]["source"] == "fake"
    assert len(fake.calls) == 2


def test_live_query_changes_on_retry_round() -> None:
    assert build_live_query("Notion", "company", 0) != build_live_query("Notion", "company", 1)


def test_build_live_retrievers_covers_all_sections(tmp_path: Path) -> None:
    s = _live_settings()
    retrievers = build_live_retrievers(
        s, client=FakeTavilyClient(), budget=CallBudget(1), cache_dir=tmp_path
    )
    assert set(retrievers) == set(s.graph.sections)
    assert all(isinstance(r, BaseRetriever) for r in retrievers.values())
    assert retrievers["financial"].topic == "finance"
    assert retrievers["news"].topic == "news"
