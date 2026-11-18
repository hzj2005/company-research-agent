"""News Agent 子图拓扑（七节点，R7）。

    retrieve → guard → filter_entity → extract → judge ─┬─ ok  → freshness → write → END
                        ↑                               └─ 不足 → retrieve（返工）

为什么新闻要多一个 filter_entity：
新闻检索的面最广，同名公司混入概率最高。真实事故（2026-11-18 live 报告）：
`Sia Partners buys … Notion Consulting` 被当成 Notion（协作工具）的动态写进报告。
`entity_guard` 的字面规则挡不住这类（`Notion Labs, Inc.` 就是 Notion 自己），
只能靠语义判定，见 `capabilities/entity_filter.py`。

注意：fixture 模式下这一步跳过（合成样本没有同名实体，且抽取后端是本地 mock），
报告文本与基线保持一致；live 才真正调用判定。
"""

from __future__ import annotations

from langchain_core.tools import StructuredTool
from langgraph.graph import END, START, StateGraph

from capabilities.entity_filter import make_filter_entity_node
from config.loader import Settings
from graph.agents.news.analyzer import analyze_news
from graph.agents.news.nodes import news_extract
from graph.agents.news.state import NewsAgentInput, NewsAgentOutput, NewsAgentState
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


def build_news_subgraph(settings: Settings, document_tool: StructuredTool) -> object:
    section = "news"
    limits = limits_from(settings)

    builder = StateGraph(
        NewsAgentState, input_schema=NewsAgentInput, output_schema=NewsAgentOutput
    )
    builder.add_node("retrieve", make_retrieve_node(section, document_tool))
    builder.add_node("guard", make_guard_node(section, settings, limits, entity_guard=False))
    builder.add_node("filter_entity", make_filter_entity_node(section, settings))
    builder.add_node("extract", make_extract_node(section, news_extract, settings))
    builder.add_node("judge", make_judge_node(section, limits))
    builder.add_node("freshness", make_analyzer_node(section, analyze_news, settings))
    builder.add_node("write", make_write_node(section, settings, limits))

    builder.add_edge(START, "retrieve")
    builder.add_edge("retrieve", "guard")
    builder.add_edge("guard", "filter_entity")
    builder.add_edge("filter_entity", "extract")
    builder.add_edge("extract", "judge")
    builder.add_conditional_edges(
        "judge", route_after_judge, {"retry": "retrieve", "continue": "freshness"}
    )
    builder.add_edge("freshness", "write")
    builder.add_edge("write", END)
    return builder.compile()
