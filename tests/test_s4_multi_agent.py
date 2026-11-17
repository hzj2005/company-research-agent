"""S4 验收：4 个专职栏目节点 + 回滚开关。

验证：
1. multi_agent=false（默认）：子图仍是单一 analyst，V1 行为不变；
2. multi_agent=true：子图是 4 个具名节点，Send 按栏目派发；
3. Company 节点的实体消歧、Financial 节点的两道实体门真的会拒绝异实体；
4. 主图 7 节点不变（继承 test_s4_subgraph 的断言，此处再确认一次）。

全流程 fixture、0 网络 0 模型调用。
"""

from __future__ import annotations

import asyncio
from typing import Any

from langchain_core.tools import tool

from config.loader import Settings, apply_overrides, get_settings
from capabilities.retrieval import make_document_tool
from graph.agents.company.nodes import make_company_node
from graph.agents.financial.nodes import make_financial_node
from graph.builder import build_graph
from graph.subgraphs.research import build_research_subgraph, fanout_dispatch


def _offline_tool(docs: dict[str, list[dict[str, Any]]]) -> Any:
    @tool
    async def fetch_company_documents(
        company: str, sections: list[str], round_no: int
    ) -> dict[str, list[dict[str, Any]]]:
        """离线返回给定文档，不联网。"""
        return {s: docs.get(s, []) for s in sections}

    return fetch_company_documents


def _doc(url: str, title: str, content: str = "一些内容") -> dict[str, Any]:
    return {"url": url, "title": title, "content": content, "score": 0.9, "source": "test"}


# --------------------------------------------------------------- 开关行为 ---

def test_default_uses_single_analyst() -> None:
    s = get_settings()
    assert s.features.multi_agent is False
    sub = build_research_subgraph(s, make_document_tool(s))
    nodes = set(sub.get_graph().nodes.keys())
    assert "analyst" in nodes
    assert not any(n.startswith("agent_") for n in nodes)


def test_multi_agent_uses_four_named_nodes() -> None:
    s = apply_overrides(get_settings(), {"features.multi_agent": True})
    sub = build_research_subgraph(s, make_document_tool(s))
    nodes = set(sub.get_graph().nodes.keys())
    assert {"agent_company", "agent_industry", "agent_financial", "agent_news"} <= nodes
    assert "analyst" not in nodes


def test_fanout_targets_named_nodes_when_enabled() -> None:
    s = apply_overrides(get_settings(), {"features.multi_agent": True})
    sends = fanout_dispatch({"sections_to_research": []}, settings=s)
    assert {x.node for x in sends} == {
        "agent_company", "agent_industry", "agent_financial", "agent_news"
    }


def test_main_graph_still_seven_nodes() -> None:
    s = apply_overrides(get_settings(), {"features.multi_agent": True})
    main = build_graph(s, make_document_tool(s))
    assert set(main.nodes.keys()) == {
        "grounding", "research", "curate", "evidence_check",
        "rewrite_query", "degrade", "briefing",
    }


# ----------------------------------------------------------- 差异化行为 ---

def test_company_node_rejects_same_name_foreign_entity() -> None:
    """Company 节点应挡掉'同名不同实体'的行情页。"""
    s = apply_overrides(get_settings(), {"features.multi_agent": True})
    docs = {
        "company": [
            _doc("https://e.org/real", "Notion 产品概览", "Notion 提供协作工作区。"),
            _doc(
                "https://e.org/fake",
                "Notion VTec Berhad (0083.KL) Valuation Measures",
                "Notion VTec Berhad 是马来西亚上市公司。",
            ),
        ]
    }
    node = make_company_node(s, _offline_tool(docs))
    out = asyncio.run(node({"company": "Notion", "retry_count": {}}))
    assert set(out["company_data"]) == {"https://e.org/real"}
    guard_notes = [n for n in out["review_notes"] if n.get("node") == "entity_guard"]
    assert guard_notes and guard_notes[0]["rejected"][0]["code"] == "ticker_binding"


def test_financial_node_rejects_ticker_page() -> None:
    """Financial 节点第一道门应挡掉股票代码绑定页。"""
    s = apply_overrides(get_settings(), {"features.multi_agent": True})
    docs = {
        "financial": [
            _doc("https://e.org/real", "Notion 融资信息", "2021 年完成 A 轮融资。"),
            _doc(
                "https://e.org/fake",
                "Notion VTec Berhad (0083.KL) Key Statistics",
                "market cap and shares outstanding data here.",
            ),
        ]
    }
    node = make_financial_node(s, _offline_tool(docs))
    out = asyncio.run(node({"company": "Notion", "retry_count": {}}))
    assert set(out["financial_data"]) == {"https://e.org/real"}
    guard_notes = [n for n in out["review_notes"] if n.get("node") == "entity_guard"]
    assert guard_notes and any(r["code"] == "ticker_binding" for r in guard_notes[0]["rejected"])


def test_financial_all_rejected_fallback_keeps_docs() -> None:
    """全灭护栏：整栏都是带法域后缀的文档时全部放行。"""
    s = apply_overrides(get_settings(), {"features.multi_agent": True})
    docs = {
        "financial": [
            _doc("https://e.org/a", "Notion VTec Berhad (0083.KL) Valuation"),
        ]
    }
    node = make_financial_node(s, _offline_tool(docs))
    out = asyncio.run(node({"company": "Notion", "retry_count": {}}))
    assert "https://e.org/a" in out["financial_data"]
    guard_notes = [n for n in out["review_notes"] if n.get("node") == "entity_guard"]
    assert guard_notes and guard_notes[0]["all_rejected_fallback"] is True
