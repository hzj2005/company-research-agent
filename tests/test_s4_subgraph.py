"""S4 验收（R3 迁移版）：四路并行派发、reducer 合并不覆盖、栏目级隔离。

R3：research = Orchestrator 子图，Send 派发到 4 张独立 pipeline 子图；
回退在子图内；主图 5 节点。保留仍有效的验证：
- 4 路真并行（时间窗重叠）
- 各栏目段落互不覆盖、reducer 合并正确
- Send 白名单驱动
- 降级不可关闭是红线
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

from langchain_core.tools import tool

from capabilities.retrieval import make_document_tool
from config.loader import get_settings
from graph.agents.factory import build_all_agent_subgraphs
from graph.builder import build_graph
from graph.orchestrator import build_orchestrator_subgraph, make_dispatch_edge
from graph.run import run_research
from graph.state import merge_docs, replace_mapping, append_unique


def _run(company: str, tmp_path: Path) -> tuple[dict[str, Any], list[str]]:
    return asyncio.run(
        run_research(company, get_settings(), tmp_path / f"{company}.db", collect_trace=True)
    )


def test_first_round_fans_out_to_four_pipelines(tmp_path: Path) -> None:
    state, trace = _run("Notion", tmp_path)
    for section in get_settings().graph.sections:
        assert state[f"{section}_paragraph"]["facts"], f"{section} 段落应有事实"
    assert trace.count("research") == 1


def test_parallel_writes_are_merged_not_overwritten(tmp_path: Path) -> None:
    state, _ = _run("Notion", tmp_path)
    # 四栏目 references 都在，没被其他分支覆盖
    for section in ("company", "industry", "financial", "news"):
        assert state[f"{section}_paragraph"]["references"], f"{section} 引用被覆盖"


def test_fanout_is_pure_and_whitelist_driven() -> None:
    s = get_settings()
    edge = make_dispatch_edge(s)
    first = edge({"sections_to_research": [], "dispatch_decision": []})
    retry = edge({"sections_to_research": ["company"], "dispatch_decision": ["company"]})
    assert len(first) == 4 and len(retry) == 1
    assert {x.node for x in first} == {f"agent_{k}" for k in s.graph.sections}
    assert retry[0].node == "agent_company"


def test_subgraph_structure_and_conditional_edge() -> None:
    s = get_settings()
    sub = build_orchestrator_subgraph(s, make_document_tool(s))
    nodes = set(sub.get_graph().nodes.keys())
    assert {"orchestrator", "arbitrate"} <= nodes
    assert all(f"agent_{k}" in nodes for k in s.graph.sections)
    conditional_sources = {
        getattr(e, "source", "?")
        for e in sub.get_graph().edges
        if getattr(e, "conditional", False)
    }
    assert "orchestrator" in conditional_sources, "Send 派发必须是真实条件边"

    main = build_graph(s, make_document_tool(s))
    # R3：主图 5 节点（human_review 默认关）
    assert {"grounding", "research", "briefing"} <= set(main.nodes.keys())
    assert "curate" not in main.nodes.keys() and "evidence_check" not in main.nodes.keys()


def test_reducers_are_last_write_wins_and_full_replace() -> None:
    assert append_unique(["company"], ["company", "industry"]) == ["company", "industry"]
    assert append_unique(["company"], ["company"]) == ["company"]
    assert replace_mapping({"old": 1}, {"new": 2}) == {"new": 2}
    assert replace_mapping({"old": 1}, None) == {"old": 1}
    assert merge_docs({"u1": {"a": 1}}, {"u2": {"b": 2}}) == {
        "u1": {"a": 1}, "u2": {"b": 2}
    }


def test_degrade_switch_removed_from_config() -> None:
    assert "enabled" not in get_settings().graph.degrade.model_dump(), "降级不可关闭是红线"


def test_four_agent_subgraphs_are_independently_compiled() -> None:
    """四张子图各自编译、各自独立（架构真实性）。

    R7 起各栏目自己编排节点，所以断言的是「每张子图都有自己的检索入口」而不是
    统一命名的单节点；company 已改成六节点带自环，额外断言它的拓扑。
    """
    from langgraph.graph.state import CompiledStateGraph

    s = get_settings()
    agents = build_all_agent_subgraphs(s, make_document_tool(s))
    assert set(agents) == set(s.graph.sections)
    for section, sub in agents.items():
        assert isinstance(sub, CompiledStateGraph)
        names = set(sub.get_graph().nodes.keys())
        assert "retrieve" in names or f"{section}_pipeline" in names, f"{section} 无检索入口"
    assert len({id(sub) for sub in agents.values()}) == 4, "四张子图必须是不同实例"

    company_nodes = set(agents["company"].get_graph().nodes.keys())
    assert {"retrieve", "guard", "extract", "judge", "conflict", "write"} <= company_nodes
    cycles = [
        e for e in agents["company"].get_graph().edges
        if getattr(e, "conditional", False)
    ]
    assert cycles, "company 子图必须保留「判定不足」的条件边"


def test_send_branches_overlap_in_time() -> None:
    """4 路 Send 是真并发（时间窗重叠，不依赖绝对耗时）。"""
    spans: list[tuple[str, float, float]] = []

    @tool
    async def slow_fetch(
        company: str, sections: list[str], round_no: int
    ) -> dict[str, list[dict[str, Any]]]:
        """每个分支停留 0.12s，记录进入/离开时间窗。"""
        started = time.perf_counter()
        await asyncio.sleep(0.12)
        spans.append((sections[0], started, time.perf_counter()))
        return {sections[0]: []}

    sub = build_orchestrator_subgraph(get_settings(), slow_fetch)
    asyncio.run(
        sub.ainvoke({
            "company": "X", "sections_to_research": [], "retry_count": {},
            "degraded_sections": [], "company_paragraph": {}, "industry_paragraph": {},
            "financial_paragraph": {}, "news_paragraph": {}, "review_notes": [],
        })
    )
    assert {s for s, _, _ in spans} == set(get_settings().graph.sections)
    # 某栏目可能因证据不足返工跑多轮，按栏目归并首轮时间窗；
    # 只要首轮四栏目时间窗重叠即证明 Send 并行（不是串行循环）。
    first_round: dict[str, tuple[float, float]] = {}
    for section, start, end in spans:
        prev = first_round.get(section)
        if prev is None or start < prev[0]:
            first_round[section] = (start, end)
    assert max(w[0] for w in first_round.values()) < min(w[1] for w in first_round.values()), (
        "4 个分支首轮时间窗必须重叠；若串行执行，最后一个开始会晚于第一个结束"
    )
