"""S4 research 子图：4 个 analyst 由图编排并行，回退时只派发不足栏目。

    START → dispatch ──Send(company)──→ analyst ┐
                     ──Send(industry)─→ analyst ├→ END
                     ──Send(financial)→ analyst │
                     ──Send(news)─────→ analyst ┘

S3 的「精确回退」是在单个 research 节点里用 Python 过滤 sections 列表实现的；
S4 改成 `Send` 动态派发：**没被派发的 analyst 根本不会执行**，这是图级并行，
不是函数内部的循环。子图节点名对外仍是 `research`，主图与 CLI 轨迹不破。

`Send` 必须从 `langgraph.types` 导入 —— `langgraph.constants` 在 1.2.22 已弃用
（前置探针实测有 DeprecationWarning）。
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.tools import StructuredTool
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from capabilities.retrieval import SECTION_FIELDS
from config.loader import Settings
from graph.subgraphs.state import (
    ResearchSubgraphInput,
    ResearchSubgraphOutput,
    ResearchSubgraphState,
)

logger = logging.getLogger(__name__)


def pending_sections(state: ResearchSubgraphState, settings: Settings) -> list[str]:
    """首轮白名单为空 → 4 个栏目全派发；回退轮只派发 rewrite_query 写入的栏目。"""
    whitelist = state.get("sections_to_research") or []
    return list(whitelist) or list(settings.graph.sections)


def fanout_dispatch(state: ResearchSubgraphState, *, settings: Settings) -> list[Send]:
    """条件边：按白名单动态派发，每个 Send 只带编排参数 + 当前栏目。

    不把 `*_data` / `review_notes` 等累积字段塞进 Send，否则并行分支会把旧状态
    再写回一次，主图 reducer 会重复累加。
    """
    base = {
        "company": state.get("company", ""),
        "sections_to_research": list(state.get("sections_to_research", [])),
        "retry_count": dict(state.get("retry_count", {})),
    }
    sections = pending_sections(state, settings)
    # V2：多 Agent 模式派发到 4 个具名栏目节点；关闭时走旧的单 analyst（回滚路径）
    target = (lambda s: f"agent_{s}") if settings.features.multi_agent else (lambda s: "analyst")
    logger.info(
        "research 子图派发 %d 个 analyst (multi_agent=%s): %s",
        len(sections), settings.features.multi_agent, sections,
    )
    return [Send(target(s), {**base, "active_section": s}) for s in sections]


def make_dispatch_node(settings: Settings) -> Any:
    """Orchestrator 的决策节点：读白名单、决定派发范围，并写决策留痕。

    派发动作本身仍在条件边 fanout_dispatch 里（Send 只能在条件边发），
    但"本轮派谁、为什么"由这个节点显式记下来，让编排决策可追溯。
    """

    async def dispatch(state: ResearchSubgraphState) -> dict[str, Any]:
        sections = pending_sections(state, settings)
        is_retry = bool(state.get("sections_to_research"))
        return {
            "review_notes": [
                {
                    "node": "dispatch",
                    "sections": sections,
                    "is_retry": is_retry,
                    "retry_count": dict(state.get("retry_count", {})),
                    "multi_agent": settings.features.multi_agent,
                }
            ]
        }

    return dispatch


def make_analyst_node(settings: Settings, document_tool: StructuredTool) -> Any:
    async def analyst(state: ResearchSubgraphState) -> dict[str, Any]:
        section = state["active_section"]
        field = SECTION_FIELDS.get(section)
        if field is None:
            logger.warning("未知栏目 %s，跳过", section)
            return {}
        # 栏目级重试：只能用本栏目自己的轮次。S3 全体一起回退时取全局 max 没错，
        # S4 改成 per-section 重试后各栏目 retry_count 可能不等，全局 max 会让
        # 「刚开始回退的栏目」错拿别的栏目轮次的数据（S4 复查实测抓到）。
        round_no = int(state.get("retry_count", {}).get(section, 0))
        raw = await document_tool.ainvoke(
            {"company": state["company"], "sections": [section], "round_no": round_no}
        )
        docs = raw.get(section, [])
        return {
            field: {doc["url"]: doc for doc in docs},
            # node 名沿用 research，保持 tests/test_s3_loop.py 的轨迹断言不破
            "review_notes": [
                {
                    "node": "research",
                    "analyst": section,
                    "round": round_no,
                    "sections": [section],
                    "docs": len(docs),
                }
            ],
        }

    return analyst


def build_research_subgraph(settings: Settings, document_tool: StructuredTool) -> Any:
    """编译子图。不另传 checkpointer：运行时继承父图的 AsyncSqliteSaver（已实测）。"""
    # input_schema/output_schema 隔离子图：主图的累积字段不进子图，子图也不把它们带回
    # （参数名用 input_schema / output_schema，input / output 在 1.2.22 已弃用）
    builder = StateGraph(
        ResearchSubgraphState,
        input_schema=ResearchSubgraphInput,
        output_schema=ResearchSubgraphOutput,
    )
    builder.add_node("dispatch", make_dispatch_node(settings))

    if settings.features.multi_agent:
        # V2：4 个专职栏目节点，派发目标由 fanout_dispatch 按 active_section 决定
        from graph.agents.arbitrate import make_arbitrate_node
        from graph.agents.base import make_base_node
        from graph.agents.company.nodes import make_company_node
        from graph.agents.financial.nodes import make_financial_node

        targets = {
            "company": make_company_node(settings, document_tool),
            "financial": make_financial_node(settings, document_tool),
            "industry": make_base_node(settings, document_tool, "industry"),
            "news": make_base_node(settings, document_tool, "news"),
        }
        for section, node in targets.items():
            builder.add_node(f"agent_{section}", node)
        node_names = [f"agent_{s}" for s in targets]
        # 仲裁节点：4 路汇合后做跨栏一致性标注（只标不改）
        builder.add_node("arbitrate", make_arbitrate_node(settings))
    else:
        # 回滚路径：V1 单一 analyst
        builder.add_node("analyst", make_analyst_node(settings, document_tool))
        node_names = ["analyst"]

    builder.add_edge(START, "dispatch")
    builder.add_conditional_edges(
        "dispatch",
        lambda state: fanout_dispatch(state, settings=settings),
        node_names,
    )
    if settings.features.multi_agent:
        # 4 路都汇入 arbitrate，它等全部完成后执行一次（真汇合，不是各走各的）
        for name in node_names:
            builder.add_edge(name, "arbitrate")
        builder.add_edge("arbitrate", END)
    else:
        for name in node_names:
            builder.add_edge(name, END)
    return builder.compile()
