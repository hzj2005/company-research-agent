"""S6 验收：Orchestrator 显式化（dispatch 决策留痕 + arbitrate 跨栏仲裁）。

验证：
1. dispatch 节点读白名单、写决策留痕（派谁 / 是否回退 / 轮次）；
2. arbitrate 只标跨栏冲突、不改任何 *_data、不产出报告内容；
3. multi_agent 模式下 4 路真汇合到 arbitrate（图结构断言）；
4. 关闭模式零 arbitrate 节点（回滚路径）；
5. 报告文本不受影响。

全程 fixture、0 网络 0 模型调用。
"""

from __future__ import annotations

import asyncio

from config.loader import apply_overrides, get_settings
from capabilities.retrieval import make_document_tool
from graph.agents.arbitrate import make_arbitrate_node
from graph.subgraphs.research import build_research_subgraph, make_dispatch_node


# ----------------------------------------------------------- dispatch ---

def test_dispatch_records_decision() -> None:
    s = get_settings()
    node = make_dispatch_node(s)
    out = asyncio.run(
        node({"sections_to_research": ["company"], "retry_count": {"company": 1}})
    )
    note = out["review_notes"][0]
    assert note["node"] == "dispatch"
    assert note["sections"] == ["company"]
    assert note["is_retry"] is True
    assert note["retry_count"] == {"company": 1}


def test_dispatch_first_round_marks_not_retry() -> None:
    s = get_settings()
    node = make_dispatch_node(s)
    out = asyncio.run(node({"sections_to_research": [], "retry_count": {}}))
    note = out["review_notes"][0]
    assert note["is_retry"] is False
    assert set(note["sections"]) == set(s.graph.sections)


# ---------------------------------------------------------- arbitrate ---

def test_arbitrate_flags_cross_section_conflict_without_mutating_docs() -> None:
    s = apply_overrides(get_settings(), {"features.conflict_annotation": True})
    node = make_arbitrate_node(s)
    state = {
        "company_data": {
            "u1": {"url": "u1", "content": "Notion 成立于 2013 年"},
        },
        "news_data": {
            "u2": {"url": "u2", "content": "Notion 成立于 2014 年"},
        },
        "financial_data": {},
        "industry_data": {},
    }
    out = asyncio.run(node(state))
    # 只标不改：输出只有 review_notes，没有任何 *_data
    assert set(out.keys()) == {"review_notes"}
    note = out["review_notes"][0]
    assert note["node"] == "arbitrate"
    assert note["cross_section_year_conflict"] == ["2013", "2014"]
    assert note["years_by_section"]["company"] == ["2013"]
    assert note["years_by_section"]["news"] == ["2014"]


def test_arbitrate_ignores_same_section_conflict() -> None:
    """同栏内的年份冲突归报告层 detect_conflicts，arbitrate 不越界误报。"""
    s = get_settings()
    node = make_arbitrate_node(s)
    state = {
        "company_data": {
            "u1": {"url": "u1", "content": "Notion 成立于 2013 年"},
            "u2": {"url": "u2", "content": "Notion 成立于 2014 年"},
        },
        "news_data": {},
        "financial_data": {},
        "industry_data": {},
    }
    out = asyncio.run(node(state))
    assert out == {"review_notes": []}, "同栏冲突不应由 arbitrate 报"


def test_arbitrate_silent_when_no_conflict() -> None:
    s = get_settings()
    node = make_arbitrate_node(s)
    state = {
        "company_data": {"u1": {"url": "u1", "content": "Notion 成立于 2013 年"}},
        "news_data": {},
        "financial_data": {},
        "industry_data": {},
    }
    out = asyncio.run(node(state))
    assert out == {"review_notes": []}


def test_arbitrate_disabled_by_conflict_switch() -> None:
    s = apply_overrides(get_settings(), {"features.conflict_annotation": False})
    node = make_arbitrate_node(s)
    state = {
        "company_data": {"u1": {"url": "u1", "content": "Notion 成立于 2013 年"}},
        "news_data": {"u2": {"url": "u2", "content": "Notion 成立于 2014 年"}},
        "financial_data": {},
        "industry_data": {},
    }
    out = asyncio.run(node(state))
    assert out == {"review_notes": []}


# -------------------------------------------------------- 图结构 ---

def test_arbitrate_only_in_multi_agent_mode() -> None:
    s = apply_overrides(get_settings(), {"features.multi_agent": True})
    sub = build_research_subgraph(s, make_document_tool(s))
    nodes = set(sub.get_graph().nodes.keys())
    assert "arbitrate" in nodes
    # 4 路都指向 arbitrate
    incoming = {
        getattr(e, "target", "?")
        for e in sub.get_graph().edges
        if getattr(e, "source", "?") in {
            "agent_company", "agent_industry", "agent_financial", "agent_news"
        }
    }
    assert incoming == {"arbitrate"}


def test_no_arbitrate_in_rollback_mode() -> None:
    s = get_settings()
    assert s.features.multi_agent is False
    sub = build_research_subgraph(s, make_document_tool(s))
    assert "arbitrate" not in set(sub.get_graph().nodes.keys())
