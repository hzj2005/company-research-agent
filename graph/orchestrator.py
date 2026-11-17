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

from langchain_core.tools import StructuredTool
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from config.loader import Settings
from graph.agents.factory import build_all_agent_subgraphs
from graph.subgraphs.state import (
    ResearchSubgraphInput,
    ResearchSubgraphOutput,
    ResearchSubgraphState,
)

logger = logging.getLogger(__name__)


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
    """汇合节点：4 路子图结果汇总后的一致性检查（R1 留痕，R5 加实质逻辑）。"""

    async def arbitrate(state: ResearchSubgraphState) -> dict[str, Any]:
        return {
            "review_notes": [
                {
                    "node": "arbitrate",
                    "sections_checked": list(settings.graph.sections),
                }
            ]
        }

    return arbitrate


def build_orchestrator_subgraph(
    settings: Settings, document_tool: StructuredTool
) -> Any:
    """编译 Orchestrator 子图：orchestrator → 4 独立 Agent 子图 → arbitrate → END。"""
    # 子图 state 需要承载派发决策字段
    class OrchestratorState(ResearchSubgraphState, total=False):
        dispatch_decision: list[str]

    builder = StateGraph(
        OrchestratorState,
        input_schema=ResearchSubgraphInput,
        output_schema=ResearchSubgraphOutput,
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
