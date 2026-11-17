"""News Agent 子图拓扑（四件套之一，R3）。"""

from __future__ import annotations

from langchain_core.tools import StructuredTool
from langgraph.graph import END, START, StateGraph

from config.loader import Settings
from graph.agents.news.nodes import make_news_pipeline_node
from graph.agents.news.state import NewsAgentInput, NewsAgentOutput, NewsAgentState


def build_news_subgraph(settings: Settings, document_tool: StructuredTool) -> object:
    builder = StateGraph(
        NewsAgentState, input_schema=NewsAgentInput, output_schema=NewsAgentOutput
    )
    builder.add_node("news_pipeline", make_news_pipeline_node(settings, document_tool))
    builder.add_edge(START, "news_pipeline")
    builder.add_edge("news_pipeline", END)
    return builder.compile()
