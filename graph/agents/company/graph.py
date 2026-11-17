"""Company Agent 子图拓扑（四件套之一，R3）。"""

from __future__ import annotations

from langchain_core.tools import StructuredTool
from langgraph.graph import END, START, StateGraph

from config.loader import Settings
from graph.agents.company.nodes import make_company_pipeline_node
from graph.agents.company.state import CompanyAgentInput, CompanyAgentOutput, CompanyAgentState


def build_company_subgraph(settings: Settings, document_tool: StructuredTool) -> object:
    builder = StateGraph(
        CompanyAgentState, input_schema=CompanyAgentInput, output_schema=CompanyAgentOutput
    )
    builder.add_node("company_pipeline", make_company_pipeline_node(settings, document_tool))
    builder.add_edge(START, "company_pipeline")
    builder.add_edge("company_pipeline", END)
    return builder.compile()
