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
    logger.info("research 子图派发 %d 个 analyst: %s", len(sections), sections)
    return [Send("analyst", {**base, "active_section": section}) for section in sections]


def make_dispatch_node() -> Any:
    async def dispatch(state: ResearchSubgraphState) -> dict[str, Any]:
        # 纯占位：派发逻辑在条件边里，节点本身不写状态
        return {}

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
    builder.add_node("dispatch", make_dispatch_node())
    builder.add_node("analyst", make_analyst_node(settings, document_tool))
    builder.add_edge(START, "dispatch")
    builder.add_conditional_edges(
        "dispatch",
        lambda state: fanout_dispatch(state, settings=settings),
        ["analyst"],
    )
    builder.add_edge("analyst", END)
    return builder.compile()
