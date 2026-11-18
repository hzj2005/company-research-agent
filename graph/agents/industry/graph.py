"""Industry Agent 子图拓扑（八节点，R7，唯一有两轮检索的栏目）。

    retrieve → guard → extract → judge ─┬─ ok → scan ─┬─ 有名单 → fetch → extract2 ─┐
                      ↑                  └ 不足→retrieve  │                        │
                      │                                 └─ 无名单 → matrix ←────────┘
                      └────────────────────────────────────────────── matrix → write → END

为什么必须两阶段：第一轮 query 围绕目标公司（`X industry market landscape
competitors`），拿到的是"提到竞品"的行业文章，不是竞品自己的事实。矩阵要填格子，
就得拿名单再查一轮（`Obsidian pricing features positioning`）。

成本：每条竞品 1 次检索（advanced=2 credits），由 `graph.competitor_fetch`
两个开关约束；关闭后拓扑退回单阶段，行为与 R4 一致。
"""

from __future__ import annotations

from langchain_core.tools import StructuredTool
from langgraph.graph import END, START, StateGraph

from config.loader import Settings
from graph.agents.industry.analyzer import analyze_industry
from graph.agents.industry.nodes import (
    industry_extract,
    make_competitor_fetch_node,
    make_competitor_scan_node,
    route_after_scan,
)
from graph.agents.industry.state import (
    IndustryAgentInput,
    IndustryAgentOutput,
    IndustryAgentState,
)
from graph.agents.primitives import (
    limits_from,
    make_analyzer_node,
    make_extract_node,
    make_guard_node,
    make_judge_node,
    make_retrieve_node,
    make_write_node,
    route_after_judge,
)


def build_industry_subgraph(settings: Settings, document_tool: StructuredTool) -> object:
    section = "industry"
    limits = limits_from(settings)

    builder = StateGraph(
        IndustryAgentState,
        input_schema=IndustryAgentInput,
        output_schema=IndustryAgentOutput,
    )
    builder.add_node("retrieve", make_retrieve_node(section, document_tool))
    builder.add_node("guard", make_guard_node(section, settings, limits, entity_guard=False))
    builder.add_node("extract", make_extract_node(section, industry_extract, settings))
    builder.add_node("judge", make_judge_node(section, limits))
    builder.add_node("scan", make_competitor_scan_node(section, settings))
    builder.add_node("fetch", make_competitor_fetch_node(section, document_tool))
    builder.add_node("extract2", make_extract_node(section, industry_extract, settings))
    builder.add_node("matrix", make_analyzer_node(section, analyze_industry, settings))
    builder.add_node("write", make_write_node(section, settings, limits))

    builder.add_edge(START, "retrieve")
    builder.add_edge("retrieve", "guard")
    builder.add_edge("guard", "extract")
    builder.add_edge("extract", "judge")
    builder.add_conditional_edges(
        "judge", route_after_judge, {"retry": "retrieve", "continue": "scan"}
    )
    builder.add_conditional_edges(
        "scan", route_after_scan, {"fetch": "fetch", "matrix": "matrix"}
    )
    builder.add_edge("fetch", "extract2")
    builder.add_edge("extract2", "matrix")
    builder.add_edge("matrix", "write")
    builder.add_edge("write", END)
    return builder.compile()
