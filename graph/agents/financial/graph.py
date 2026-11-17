"""Financial Agent 子图拓扑（四件套之一，R3）。"""

from __future__ import annotations

from langchain_core.tools import StructuredTool
from langgraph.graph import END, START, StateGraph

from config.loader import Settings
from graph.agents.financial.nodes import make_financial_pipeline_node
from graph.agents.financial.state import (
    FinancialAgentInput,
    FinancialAgentOutput,
    FinancialAgentState,
)


def build_financial_subgraph(settings: Settings, document_tool: StructuredTool) -> object:
    builder = StateGraph(
        FinancialAgentState,
        input_schema=FinancialAgentInput,
        output_schema=FinancialAgentOutput,
    )
    builder.add_node("financial_pipeline", make_financial_pipeline_node(settings, document_tool))
    builder.add_edge(START, "financial_pipeline")
    builder.add_edge("financial_pipeline", END)
    return builder.compile()
