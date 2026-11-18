"""R7 验收：行业两阶段检索。

第一轮 query 围绕目标公司，拿不到竞品自己的事实；第二轮拿竞品名单去补查。
这里用注入的假检索工具验证拓扑与额度行为，不动全局 fixture（基线零漂移）。
"""

from __future__ import annotations

import asyncio
from typing import Any

from langchain_core.tools import tool

from config.loader import get_settings
from graph.agents.industry.graph import build_industry_subgraph


def _doc(url: str, content: str, score: float = 0.9) -> dict[str, Any]:
    return {"url": url, "title": content[:24], "content": content, "score": score,
            "source": "test", "section": "industry"}


INDUSTRY_DOCS = [
    _doc("https://e.org/m1", "协同文档市场持续增长。"),
    _doc("https://e.org/m2", "直接竞品包括 Obsidian 与 Coda，差异化在模板生态。"),
]
COMPETITOR_DOCS = [
    _doc("https://obsidian.md/pricing", "Obsidian 个人免费，同步服务 8 美元/月。"),
    _doc("https://coda.io/pricing", "Coda 团队版每人每月 10 美元。"),
]


def _two_stage_tool(calls: list[dict[str, Any]]) -> Any:
    @tool
    async def fetch(
        company: str,
        sections: list[str],
        round_no: int,
        queries: list[str] | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        """第一轮返回行业文档；带 queries 时返回竞品文档。"""
        calls.append({"queries": queries})
        return {"industry": COMPETITOR_DOCS if queries else INDUSTRY_DOCS}

    return fetch


def _settings(**overrides: Any):
    s = get_settings().model_copy(deep=True)
    for key, value in overrides.items():
        setattr(s.graph.competitor_fetch, key, value)
    return s


def test_second_round_queries_are_issued_per_competitor() -> None:
    calls: list[dict[str, Any]] = []
    graph = build_industry_subgraph(_settings(), _two_stage_tool(calls))
    state = asyncio.run(graph.ainvoke({"company": "Notion", "round_no": 0}))

    staged = [c for c in calls if c["queries"]]
    assert len(staged) == 1, "应只发起一次补检索"
    assert len(staged[0]["queries"]) == 2, "每个竞品一条 query"
    assert all("pricing" in q for q in staged[0]["queries"])

    facts = state["industry_paragraph"]["facts"]
    assert len(facts) == 4, "两轮文档都要抽：2 篇行业 + 2 篇竞品"
    urls = {f["source_url"] for f in facts}
    assert "https://obsidian.md/pricing" in urls


def test_target_company_is_not_treated_as_competitor() -> None:
    calls: list[dict[str, Any]] = []

    @tool
    async def fetch(
        company: str,
        sections: list[str],
        round_no: int,
        queries: list[str] | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        """行业文档里连目标公司自己也出现在竞品句式中。"""
        calls.append({"queries": queries})
        if queries:
            return {"industry": []}
        return {
            "industry": [
                _doc("https://e.org/a", "市场持续增长。"),
                _doc("https://e.org/b", "直接竞品包括 Notion 与 Coda。"),
            ]
        }

    graph = build_industry_subgraph(_settings(), fetch)
    state = asyncio.run(graph.ainvoke({"company": "Notion", "round_no": 0}))
    staged = [c for c in calls if c["queries"]]
    if staged:
        assert all("Notion" not in q for q in staged[0]["queries"]), (
            "目标公司不能出现在补检索的 query 里"
        )


def test_switch_off_skips_second_round_entirely() -> None:
    calls: list[dict[str, Any]] = []
    graph = build_industry_subgraph(_settings(enabled=False), _two_stage_tool(calls))
    state = asyncio.run(graph.ainvoke({"company": "Notion", "round_no": 0}))

    assert not any(c["queries"] for c in calls), "关闭后不得发起补检索"
    assert len(state["industry_paragraph"]["facts"]) == 2
