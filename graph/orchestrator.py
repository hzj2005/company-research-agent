"""Orchestrator 子图（重建版 R1）：真正的编排层。

与上一版的关键区别：
- 上一版：派发在条件边，agent_* 是 research 子图里的**普通节点**；
- 本版：`orchestrator` 是**真节点**（读白名单、写派发决策到 state），
  派发目标是**四张独立编译子图**（graph/agents/factory.py 产出）。

LangGraph 约束：Send 只能在条件边发。所以 orchestrator 节点负责"决策"
（写 dispatch_decision 到 state），条件边读决策执行 Send——决策与执行分离，
但 orchestrator 是实打实有状态产出的节点，不是空壳占位。
"""

from __future__ import annotations

import logging
from typing import Any

from typing import Annotated

from langchain_core.tools import StructuredTool
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send
from typing_extensions import TypedDict

from config.loader import Settings
from graph.agents.factory import build_all_agent_subgraphs
from graph.state import append_notes, append_unique, merge_mapping, replace_mapping
from graph.subgraphs.state import (
    ResearchSubgraphInput,
    ResearchSubgraphState,
)

logger = logging.getLogger(__name__)


class OrchestratorState(ResearchSubgraphState, total=False):
    """编排子图 state：在基础字段上承载派发决策与四段落产物。"""

    dispatch_decision: list[str]
    degraded_sections: Annotated[list[str], append_unique]
    retry_count: Annotated[dict[str, int], merge_mapping]
    company_paragraph: Annotated[dict[str, Any], replace_mapping]
    industry_paragraph: Annotated[dict[str, Any], replace_mapping]
    financial_paragraph: Annotated[dict[str, Any], replace_mapping]
    news_paragraph: Annotated[dict[str, Any], replace_mapping]


class OrchestratorOutput(TypedDict, total=False):
    """编排子图输出：只回传四段落与留痕（父图 State 子集）。"""

    company_paragraph: Annotated[dict[str, Any], replace_mapping]
    industry_paragraph: Annotated[dict[str, Any], replace_mapping]
    financial_paragraph: Annotated[dict[str, Any], replace_mapping]
    news_paragraph: Annotated[dict[str, Any], replace_mapping]
    degraded_sections: Annotated[list[str], append_unique]
    retry_count: Annotated[dict[str, int], merge_mapping]
    review_notes: Annotated[list[dict[str, Any]], append_notes]



def pending_sections(state: ResearchSubgraphState, settings: Settings) -> list[str]:
    """首轮白名单为空 → 4 栏目全派发；回退轮只派发不足栏目。"""
    whitelist = state.get("sections_to_research") or []
    return list(whitelist) or list(settings.graph.sections)


def make_orchestrator_node(settings: Settings) -> Any:
    """编排决策节点：读白名单，写派发决策与留痕。"""

    async def orchestrator(state: ResearchSubgraphState) -> dict[str, Any]:
        sections = pending_sections(state, settings)
        decision = {
            "node": "orchestrator",
            "dispatch_to": sections,
            "is_retry": bool(state.get("sections_to_research")),
            "retry_count": dict(state.get("retry_count", {})),
        }
        logger.info("orchestrator 派发 %d 个 Agent 子图: %s", len(sections), sections)
        return {
            "dispatch_decision": sections,
            "review_notes": [decision],
        }

    return orchestrator


def make_dispatch_edge(settings: Settings) -> Any:
    """条件边：读 orchestrator 写下的决策，Send 派发到各独立编译子图。"""

    def dispatch(state: ResearchSubgraphState) -> list[Send]:
        sections = state.get("dispatch_decision") or pending_sections(state, settings)
        base = {
            "company": state.get("company", ""),
            "sections_to_research": list(state.get("sections_to_research", [])),
            "retry_count": dict(state.get("retry_count", {})),
        }
        # 派发目标 = 四张独立子图的节点名
        return [
            Send(f"agent_{section}", {**base, "round_no": state.get("retry_count", {}).get(section, 0)})
            for section in sections
        ]

    return dispatch


def make_arbitrate_node(settings: Settings) -> Any:
    """汇合节点：读四段落状态，写 degraded_sections（供评测/报告判定拒答）。

    R3 主图移除了 degrade 节点，但评测 metrics.py 用 degraded_sections 判定
    abstain。子图段落 status=degraded/no_evidence 时，在这里统一补写该字段，
    保持对外契约不变（报告文本早已由 assemble 写好拒答话术）。
    """

    async def arbitrate(state: ResearchSubgraphState) -> dict[str, Any]:
        degraded: list[str] = []
        for section in settings.graph.sections:
            paragraph = state.get(f"{section}_paragraph") or {}
            if paragraph.get("status") in ("degraded", "no_evidence"):
                degraded.append(section)
        return {
            "degraded_sections": degraded,
            "review_notes": [
                {
                    "node": "arbitrate",
                    "sections_checked": list(settings.graph.sections),
                    "degraded": degraded,
                }
            ],
        }

    return arbitrate


def build_orchestrator_subgraph(
    settings: Settings, document_tool: StructuredTool
) -> Any:
    """编译 Orchestrator 子图：orchestrator → 4 独立 Agent 子图 → arbitrate → END。"""
    builder = StateGraph(
        OrchestratorState,
        input_schema=ResearchSubgraphInput,
        output_schema=OrchestratorOutput,
    )

    agents = build_all_agent_subgraphs(settings, document_tool)
    agent_nodes = [f"agent_{section}" for section in agents]

    builder.add_node("orchestrator", make_orchestrator_node(settings))
    for section, subgraph in agents.items():
        # 关键：add_node 的值是**编译后的子图**，不是普通函数
        builder.add_node(f"agent_{section}", subgraph)
    builder.add_node("arbitrate", make_arbitrate_node(settings))

    builder.add_edge(START, "orchestrator")
    builder.add_conditional_edges("orchestrator", make_dispatch_edge(settings), agent_nodes)
    for node in agent_nodes:
        builder.add_edge(node, "arbitrate")
    builder.add_edge("arbitrate", END)

    return builder.compile()
