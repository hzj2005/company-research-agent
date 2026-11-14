"""S4 主图：7 节点，其中 `research` 是编译后的 4 路 Send 并行子图。

    START → grounding → [research 子图] → curate → evidence_check
                              ↑               ├─ pass    → briefing → END
                              │               ├─ retry   → rewrite_query ─┘
                              │               └─ degrade → degrade → briefing → END

节点名 `research` 保持不变：三档 CLI 轨迹统计与 S3 的测试断言都依赖它，
白板上把这个节点展开成 dispatch + 4 analyst 即可。
"""

from __future__ import annotations

from langchain_core.tools import StructuredTool
from langgraph.graph import END, START, StateGraph

from capabilities.briefing import BriefingBackend
from config.loader import Settings
from graph.conditions import route_after_evidence
from graph.nodes.collect import make_curate_node, make_grounding_node
from graph.nodes.decide import (
    make_degrade_node,
    make_evidence_check_node,
    make_rewrite_query_node,
)
from graph.nodes.human_review import make_human_review_node
from graph.nodes.report import make_briefing_node
from graph.state import ResearchState
from graph.subgraphs.research import build_research_subgraph


def build_graph(
    settings: Settings,
    document_tool: StructuredTool,
    *,
    briefing_backend: BriefingBackend | None = None,
) -> StateGraph:
    """`briefing_backend` 由生产路径的 `briefing_backend_scope()` 注入并负责关闭。

    不传时 `make_briefing_node` 会自建（仅测试/短生命周期脚本使用，兼容旧调用）。
    """
    builder = StateGraph(ResearchState)
    review_enabled = settings.features.human_review

    builder.add_node("grounding", make_grounding_node(settings))
    # 编译后的子图直接当节点：主图 astream 里仍叫 research（前置探针实测）
    builder.add_node("research", build_research_subgraph(settings, document_tool))
    builder.add_node("curate", make_curate_node(settings))
    builder.add_node("evidence_check", make_evidence_check_node(settings))
    builder.add_node("rewrite_query", make_rewrite_query_node(settings))
    builder.add_node("degrade", make_degrade_node(settings))
    if review_enabled:
        builder.add_node("human_review", make_human_review_node(settings))
    builder.add_node("briefing", make_briefing_node(settings, backend=briefing_backend))

    builder.add_edge(START, "grounding")
    builder.add_edge("grounding", "research")
    builder.add_edge("research", "curate")
    builder.add_edge("curate", "evidence_check")

    # 条件函数保持纯函数，settings 由闭包注入；S6 开关关闭时目标仍是 briefing
    after_evidence = "human_review" if review_enabled else "briefing"
    builder.add_conditional_edges(
        "evidence_check",
        lambda state: route_after_evidence(state, settings=settings),
        {
            "pass": after_evidence,
            "retry": "rewrite_query",
            "degrade": "degrade",
        },
    )
    builder.add_edge("rewrite_query", "research")
    builder.add_edge("degrade", after_evidence)
    if review_enabled:
        builder.add_edge("human_review", "briefing")
    builder.add_edge("briefing", END)

    return builder
