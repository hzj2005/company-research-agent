"""S3 主图：把线性 DAG 改成带条件边与有上限回退的状态图。

    START → grounding → research → curate → evidence_check
                            ↑                     ├─ pass    → briefing → END
                            │                     ├─ retry   → rewrite_query ─┘
                            └─────────────────────┴─ degrade → degrade → briefing → END

S4 会把 research 拆成 4 analyst 的并行子图；S3 先保证条件边、循环上限、
降级拒答与 reducer 合并真实可跑。
"""

from __future__ import annotations

from langchain_core.tools import StructuredTool
from langgraph.graph import END, START, StateGraph

from config.loader import Settings
from graph.conditions import route_after_evidence
from graph.nodes.collect import make_curate_node, make_grounding_node, make_research_node
from graph.nodes.decide import (
    make_degrade_node,
    make_evidence_check_node,
    make_rewrite_query_node,
)
from graph.nodes.report import make_briefing_node
from graph.state import ResearchState


def build_graph(settings: Settings, document_tool: StructuredTool) -> StateGraph:
    builder = StateGraph(ResearchState)

    builder.add_node("grounding", make_grounding_node(settings))
    builder.add_node("research", make_research_node(settings, document_tool))
    builder.add_node("curate", make_curate_node(settings))
    builder.add_node("evidence_check", make_evidence_check_node(settings))
    builder.add_node("rewrite_query", make_rewrite_query_node(settings))
    builder.add_node("degrade", make_degrade_node(settings))
    builder.add_node("briefing", make_briefing_node(settings))

    builder.add_edge(START, "grounding")
    builder.add_edge("grounding", "research")
    builder.add_edge("research", "curate")
    builder.add_edge("curate", "evidence_check")

    # 条件函数保持纯函数，settings 由闭包注入
    builder.add_conditional_edges(
        "evidence_check",
        lambda state: route_after_evidence(state, settings=settings),
        {
            "pass": "briefing",
            "retry": "rewrite_query",
            "degrade": "degrade",
        },
    )
    builder.add_edge("rewrite_query", "research")
    builder.add_edge("degrade", "briefing")
    builder.add_edge("briefing", END)

    return builder
