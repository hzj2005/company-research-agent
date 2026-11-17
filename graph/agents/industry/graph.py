"""Industry Agent 子图拓扑（四件套之一，R3）。"""

from __future__ import annotations

from langchain_core.tools import StructuredTool
from langgraph.graph import END, START, StateGraph

from config.loader import Settings
from graph.agents.industry.nodes import make_industry_pipeline_node
from graph.agents.industry.state import (
    IndustryAgentInput,
    IndustryAgentOutput,
    IndustryAgentState,
)


def build_industry_subgraph(settings: Settings, document_tool: StructuredTool) -> object:
    builder = StateGraph(
        IndustryAgentState,
        input_schema=IndustryAgentInput,
        output_schema=IndustryAgentOutput,
    )
    builder.add_node("industry_pipeline", make_industry_pipeline_node(settings, document_tool))
    builder.add_edge(START, "industry_pipeline")
    builder.add_edge("industry_pipeline", END)
    return builder.compile()
