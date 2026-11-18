"""Company Agent 子图拓扑（六节点，R7）。

    retrieve → guard → extract → judge ─┬─ ok   → conflict → write → END
                     ↑                   └─ 不足 → retrieve（返工，≤max_retry 轮）

为什么是这条流程：公司概况只要「查一个实体的静态属性」，一次检索的召回通常就够，
加阶段是浪费。真正需要额外一步的只有冲突标注——五份来源给出的成立年份各不相同
（2026-11-18 实测 Notion：2012 / 2014 / 2016，真实是 2013）。
"""

from __future__ import annotations

from langchain_core.tools import StructuredTool
from langgraph.graph import END, START, StateGraph

from config.loader import Settings
from graph.agents.company.analyzer import detect_same_round_conflicts
from graph.agents.company.nodes import company_extract
from graph.agents.company.state import (
    CompanyAgentInput,
    CompanyAgentOutput,
    CompanyAgentState,
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


def build_company_subgraph(settings: Settings, document_tool: StructuredTool) -> object:
    section = "company"
    limits = limits_from(settings)

    builder = StateGraph(
        CompanyAgentState, input_schema=CompanyAgentInput, output_schema=CompanyAgentOutput
    )
    builder.add_node("retrieve", make_retrieve_node(section, document_tool))
    builder.add_node("guard", make_guard_node(section, settings, limits, entity_guard=True))
    builder.add_node("extract", make_extract_node(section, company_extract, settings))
    builder.add_node("judge", make_judge_node(section, limits))
    builder.add_node(
        "conflict", make_analyzer_node(section, detect_same_round_conflicts, settings)
    )
    builder.add_node("write", make_write_node(section, settings, limits))

    builder.add_edge(START, "retrieve")
    builder.add_edge("retrieve", "guard")
    builder.add_edge("guard", "extract")
    builder.add_edge("extract", "judge")
    builder.add_conditional_edges(
        "judge", route_after_judge, {"retry": "retrieve", "continue": "conflict"}
    )
    builder.add_edge("conflict", "write")
    builder.add_edge("write", END)
    return builder.compile()
