"""Financial Agent 子图拓扑（八节点，R7）。

    retrieve → guard → bind_subject → extract → verify_amount → judge
                   ↑                                              │
                   └──────── 不足则返工（≤max_retry 轮）───────────┘
                                                                  │ 有结论
                                                            timeline → write → END

为什么财务需要这两步而公司概况不需要：
- **bind_subject**：财务事实的错误以「数字」形式出现，读者无法察觉。必须先确认
  这家公司上市没上市、ticker 是什么，否则 `Notion VTec Berhad (0083.KL)`（马来
  西亚上市公司）的财报会被当成 Notion 的钱。
- **verify_amount**：金额必须原样出现在原文。LLM 会把「5000 万美元」写成
  「5000万美金」，或者凭空补一个数字，这一步用纯规则挡住，不调模型。
"""

from __future__ import annotations

from langchain_core.tools import StructuredTool
from langgraph.graph import END, START, StateGraph

from config.loader import Settings
from graph.agents.financial.analyzer import analyze_financial
from graph.agents.financial.nodes import (
    financial_extract,
    make_bind_subject_node,
    make_verify_amount_node,
)
from graph.agents.financial.state import (
    FinancialAgentInput,
    FinancialAgentOutput,
    FinancialAgentState,
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


def build_financial_subgraph(settings: Settings, document_tool: StructuredTool) -> object:
    section = "financial"
    limits = limits_from(settings)

    builder = StateGraph(
        FinancialAgentState,
        input_schema=FinancialAgentInput,
        output_schema=FinancialAgentOutput,
    )
    builder.add_node("retrieve", make_retrieve_node(section, document_tool))
    builder.add_node("guard", make_guard_node(section, settings, limits, entity_guard=True))
    builder.add_node("bind_subject", make_bind_subject_node(section))
    builder.add_node("extract", make_extract_node(section, financial_extract, settings))
    builder.add_node("verify_amount", make_verify_amount_node(section))
    builder.add_node("judge", make_judge_node(section, limits))
    builder.add_node("timeline", make_analyzer_node(section, analyze_financial, settings))
    builder.add_node("write", make_write_node(section, settings, limits))

    builder.add_edge(START, "retrieve")
    builder.add_edge("retrieve", "guard")
    builder.add_edge("guard", "bind_subject")
    builder.add_edge("bind_subject", "extract")
    builder.add_edge("extract", "verify_amount")
    builder.add_edge("verify_amount", "judge")
    builder.add_conditional_edges(
        "judge", route_after_judge, {"retry": "retrieve", "continue": "timeline"}
    )
    builder.add_edge("timeline", "write")
    builder.add_edge("write", END)
    return builder.compile()
