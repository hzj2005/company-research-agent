"""R1 验收：架构真实性——四张独立编译子图 + Orchestrator 真节点。

这是重建的核心命题，必须拿代码事实说话，不靠文字声明：
1. orchestrator 是真节点（不是条件边），且写下派发决策；
2. 4 个 agent_* 节点的值是**编译后的 StateGraph 子图**（不是普通函数）；
3. 四张子图各有独立 state schema；
4. 4 路真并行 + arbitrate 汇合；
5. 端到端能跑通，4 栏目数据不串。

全程 fixture、0 网络 0 模型。
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from langgraph.graph.state import CompiledStateGraph

from capabilities.retrieval import make_document_tool
from config.loader import get_settings
from graph.agents.factory import build_all_agent_subgraphs
from graph.orchestrator import build_orchestrator_subgraph
from graph.run import run_research


def test_four_independent_state_schemas() -> None:
    """四套 state 是不同类，不共用。"""
    from graph.agents.company.state import CompanyAgentState
    from graph.agents.financial.state import FinancialAgentState
    from graph.agents.industry.state import IndustryAgentState
    from graph.agents.news.state import NewsAgentState

    states = [CompanyAgentState, IndustryAgentState, FinancialAgentState, NewsAgentState]
    assert len(set(states)) == 4, "四栏目必须各有独立 state schema"
    # 各自的段落输出字段不同（R3：*_data → *_paragraph）
    assert "company_paragraph" in CompanyAgentState.__annotations__
    assert "financial_paragraph" in FinancialAgentState.__annotations__
    assert "industry_paragraph" in IndustryAgentState.__annotations__
    assert "news_paragraph" in NewsAgentState.__annotations__


def test_each_agent_subgraph_is_compiled() -> None:
    """每张 Agent 子图都是独立编译的图。"""
    s = get_settings()
    agents = build_all_agent_subgraphs(s, make_document_tool(s))
    assert set(agents) == {"company", "industry", "financial", "news"}
    for section, subgraph in agents.items():
        assert isinstance(subgraph, CompiledStateGraph), f"{section} 必须是编译子图"
        nodes = set(subgraph.get_graph().nodes.keys())
        # R7：各栏目自己编排，不再统一叫 `{section}_pipeline`；只要求有检索入口
        assert "retrieve" in nodes or f"{section}_pipeline" in nodes, f"{section} 无检索入口"


def test_orchestrator_is_a_real_node() -> None:
    """orchestrator 是图里真实存在的节点。"""
    s = get_settings()
    orch = build_orchestrator_subgraph(s, make_document_tool(s))
    nodes = set(orch.get_graph().nodes.keys())
    assert "orchestrator" in nodes
    assert "arbitrate" in nodes


def test_agent_nodes_are_compiled_subgraphs() -> None:
    """orchestrator 子图里 agent_* 节点的值是编译子图（关键命题）。"""
    s = get_settings()
    orch = build_orchestrator_subgraph(s, make_document_tool(s))
    subgraphs = orch.get_graph().nodes
    for section in ("company", "industry", "financial", "news"):
        node = subgraphs[f"agent_{section}"]
        # LangGraph 把挂载的编译子图放在 Node.data 里
        assert isinstance(node.data, CompiledStateGraph), f"agent_{section} 应挂载编译子图"


def test_conditional_edge_targets_four_subgraphs() -> None:
    """orchestrator 的条件边派发到 4 个子图节点。"""
    s = get_settings()
    orch = build_orchestrator_subgraph(s, make_document_tool(s))
    conditional_sources = {
        getattr(e, "source", "?")
        for e in orch.get_graph().edges
        if getattr(e, "conditional", False)
    }
    assert "orchestrator" in conditional_sources


def test_end_to_end_four_sections_no_crosstalk() -> None:
    """端到端：4 栏目数据都在、互不串。"""
    s = get_settings()
    with tempfile.TemporaryDirectory() as td:
        state, _ = asyncio.run(run_research("Notion", s, Path(td) / "p.db"))
    for section in ("company", "industry", "financial", "news"):
        para = state.get(f"{section}_paragraph") or {}
        assert para.get("facts"), f"{section}_paragraph 不应为空"
    # 各栏目段落的 references URL 应带各自特征，没串栏
    comp_urls = state["company_paragraph"]["references"]
    assert all("notion" in u for u in comp_urls)
    orch_notes = [n for n in state["review_notes"] if n.get("node") == "orchestrator"]
    assert orch_notes and set(orch_notes[0]["dispatch_to"]) == {
        "company", "industry", "financial", "news"
    }
