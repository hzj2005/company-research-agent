"""R1：构建四张**独立编译**的 Agent 子图。

每张子图：
- 独立 state schema（graph/agents/<section>/state.py）
- 独立 compiled StateGraph（build_agent_subgraph 产出）
- 输出字段 = 自己那一个 *_data + review_notes，带同名 reducer

R1 阶段节点是最小实现（检索出文档）；R3/R4 会把 extract(LLM) 与差异化节点加入。
这样 R1 可以纯 fixture 验证"架构独立性"，不依赖 key、不烧额度。
"""

from __future__ import annotations

from typing import Any

from langchain_core.tools import StructuredTool
from langgraph.graph import END, START, StateGraph

from capabilities.retrieval import SECTION_FIELDS
from config.loader import Settings
from graph.agents.company.state import (
    CompanyAgentInput,
    CompanyAgentOutput,
    CompanyAgentState,
)
from graph.agents.financial.state import (
    FinancialAgentInput,
    FinancialAgentOutput,
    FinancialAgentState,
)
from graph.agents.industry.state import (
    IndustryAgentInput,
    IndustryAgentOutput,
    IndustryAgentState,
)
from graph.agents.news.state import NewsAgentInput, NewsAgentOutput, NewsAgentState

# section -> (state, input_schema, output_schema)
_AGENT_SCHEMAS: dict[str, tuple[Any, Any, Any]] = {
    "company": (CompanyAgentState, CompanyAgentInput, CompanyAgentOutput),
    "industry": (IndustryAgentState, IndustryAgentInput, IndustryAgentOutput),
    "financial": (FinancialAgentState, FinancialAgentInput, FinancialAgentOutput),
    "news": (NewsAgentState, NewsAgentInput, NewsAgentOutput),
}


def make_agent_node(section: str, document_tool: StructuredTool) -> Any:
    """最小节点：检索本栏目文档，输出本栏目数据 + 留痕。R3/R4 在此基础上加抽取。"""
    field = SECTION_FIELDS[section]

    async def agent(state: dict[str, Any]) -> dict[str, Any]:
        round_no = int(state.get("round_no", 0))
        raw = await document_tool.ainvoke(
            {"company": state["company"], "sections": [section], "round_no": round_no}
        )
        docs = list(raw.get(section, []))
        return {
            field: {str(doc["url"]): doc for doc in docs},
            "review_notes": [
                {
                    "node": f"agent_{section}",
                    "analyst": section,
                    "round": round_no,
                    "docs": len(docs),
                }
            ],
        }

    return agent


def build_agent_subgraph(
    section: str, settings: Settings, document_tool: StructuredTool
) -> Any:
    """构建一张独立编译的 Agent 子图。"""
    state_schema, input_schema, output_schema = _AGENT_SCHEMAS[section]
    builder = StateGraph(state_schema, input_schema=input_schema, output_schema=output_schema)
    builder.add_node(f"{section}_agent", make_agent_node(section, document_tool))
    builder.add_edge(START, f"{section}_agent")
    builder.add_edge(f"{section}_agent", END)
    return builder.compile()


def build_all_agent_subgraphs(
    settings: Settings, document_tool: StructuredTool
) -> dict[str, Any]:
    """构建四张独立子图，供 Orchestrator 派发。"""
    return {
        section: build_agent_subgraph(section, settings, document_tool)
        for section in _AGENT_SCHEMAS
    }
