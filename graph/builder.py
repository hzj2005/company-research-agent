"""R3 主图：5 节点（grounding → research → briefing，+可选 human_review）。

   START → grounding → [research=Orchestrator 子图] → briefing → END
                                                    （+可选 human_review）

R3 变更（用户 2026-11-17 决策）：
- 移除 curate / evidence_check / rewrite_query / degrade——消歧、证据判定、
  回退重检全部下沉进各 Agent 子图（自闭环，≤2 轮），Orchestrator 只管派发+汇合；
- 四张子图各自写栏目段落（facts+状态，不带编号），briefing 只做拼装编号。

节点名 `research` 保持不变（CLI 轨迹与测试断言依赖它）。
"""

from __future__ import annotations

from langchain_core.tools import StructuredTool
from langgraph.graph import END, START, StateGraph

from capabilities.briefing import BriefingBackend
from config.loader import Settings
from graph.nodes.collect import make_grounding_node
from graph.nodes.human_review import make_human_review_node
from graph.nodes.report import make_briefing_node
from graph.orchestrator import build_orchestrator_subgraph
from graph.state import ResearchState


def build_graph(
    settings: Settings,
    document_tool: StructuredTool,
    *,
    briefing_backend: BriefingBackend | None = None,
) -> StateGraph:
    """`briefing_backend` 由生产路径注入并负责关闭；不传时 briefing 自建。"""
    builder = StateGraph(ResearchState)
    review_enabled = settings.features.human_review

    builder.add_node("grounding", make_grounding_node(settings))
    # research 节点 = Orchestrator 子图（四张独立 Agent 子图 + 自闭环）
    builder.add_node("research", build_orchestrator_subgraph(settings, document_tool))
    if review_enabled:
        builder.add_node("human_review", make_human_review_node(settings))
    # briefing = 拼装工：把四段落统一编号 + References 拼成报告
    builder.add_node("briefing", make_briefing_node(settings, backend=briefing_backend))

    builder.add_edge(START, "grounding")
    builder.add_edge("grounding", "research")
    builder.add_edge("research", "human_review" if review_enabled else "briefing")
    if review_enabled:
        builder.add_edge("human_review", "briefing")
    builder.add_edge("briefing", END)

    return builder
