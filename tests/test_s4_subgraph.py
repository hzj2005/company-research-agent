"""S4 验收：并行子图、Send 精确派发、栏目级重试、引用全量重算。

覆盖 ACTION_PLAN 第 7.4 节：4 路 Send 并行、reducer 合并不覆盖、回退只派发
不足栏目、部分栏目用尽额度不连累其他栏目、旧引用可被移除、降级不可关闭。
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

from langchain_core.tools import tool

from capabilities.retrieval import make_document_tool
from config.loader import get_settings
from graph.builder import build_graph
from graph.conditions import (
    ROUTE_DEGRADE,
    ROUTE_RETRY,
    route_after_evidence,
    sections_to_research,
)
from graph.run import run_research
from graph.state import initial_state, latest_list, merge_docs, replace_mapping
from graph.subgraphs.research import build_research_subgraph, fanout_dispatch
from persistence.checkpointer import CheckpointSession


def _run(company: str, tmp_path: Path) -> tuple[dict[str, Any], list[str]]:
    return asyncio.run(
        run_research(company, get_settings(), tmp_path / f"{company}.db", collect_trace=True)
    )


def _analyst_notes(state: dict[str, Any]) -> list[dict[str, Any]]:
    # 重建版：四张独立 Agent 子图的留痕 node=agent_<section>，按 analyst 字段筛选
    return [n for n in state["review_notes"] if n.get("analyst") in set(get_settings().graph.sections)]


def test_first_round_fans_out_to_four_analysts(tmp_path: Path) -> None:
    state, trace = _run("Notion", tmp_path)
    notes = _analyst_notes(state)
    assert len(notes) == 4, "子图不得把累积字段重复回传给主图 reducer"
    assert {n["analyst"] for n in notes} == set(get_settings().graph.sections)
    assert trace.count("research") == 1


def test_retry_only_dispatches_insufficient_analyst(tmp_path: Path) -> None:
    state, trace = _run("Linear", tmp_path)
    second_round = [n for n in _analyst_notes(state) if n["round"] == 1]
    assert [n["analyst"] for n in second_round] == ["company"], "回退不得唤醒其余 3 个 analyst"
    assert state["sections_to_research"] == ["company"], "派发白名单必须写进 State"
    assert trace.count("research") == 2


def test_empty_keeps_bounded_retry_then_degrades(tmp_path: Path) -> None:
    state, trace = _run("Zephyrstone Labs", tmp_path)
    assert trace.count("research") == get_settings().graph.max_retry + 1
    assert state["degraded"] is True
    assert len([n for n in _analyst_notes(state) if n["round"] > 0]) == 2


def test_parallel_writes_are_merged_not_overwritten(tmp_path: Path) -> None:
    state, _ = _run("Notion", tmp_path)
    for field, section in (
        ("company_data", "company"),
        ("industry_data", "industry"),
        ("financial_data", "financial"),
        ("news_data", "news"),
    ):
        assert state[field], f"{field} 不应被其他 analyst 覆盖"
        assert all(doc.get("section") == section for doc in state[field].values())


def test_fanout_is_pure_and_whitelist_driven() -> None:
    s = get_settings()
    first = fanout_dispatch({"sections_to_research": []}, settings=s)
    retry = fanout_dispatch({"sections_to_research": ["company"]}, settings=s)
    assert len(first) == 4 and len(retry) == 1
    assert {x.node for x in first} == {"analyst"}
    assert retry[0].arg["active_section"] == "company"


def test_subgraph_structure_and_conditional_edge() -> None:
    s = get_settings()
    sub = build_research_subgraph(s, make_document_tool(s))
    assert {"dispatch", "analyst"} <= set(sub.get_graph().nodes.keys())
    conditional_sources = {
        getattr(e, "source", "?")
        for e in sub.get_graph().edges
        if getattr(e, "conditional", False)
    }
    assert "dispatch" in conditional_sources, "Send 派发必须是真实条件边"

    main = build_graph(s, make_document_tool(s))
    assert set(main.nodes.keys()) == {
        "grounding", "research", "curate", "evidence_check",
        "rewrite_query", "degrade", "briefing",
    }


def test_partial_retry_budget_does_not_abort_other_sections() -> None:
    """旧 `any(...)`：company 达上限会把还有额度的 industry 一起降级。"""
    s = get_settings()
    state = {
        **initial_state("X"),
        "evidence_verdict": {"company": "insufficient", "industry": "insufficient"},
        "retry_count": {"company": s.graph.max_retry, "industry": 0},
    }
    assert route_after_evidence(state, settings=s) == ROUTE_RETRY
    assert sections_to_research(state, s) == ["industry"], "已达上限栏目不该再被重搜"
    exhausted = {**state, "retry_count": {"company": s.graph.max_retry, "industry": s.graph.max_retry}}
    assert route_after_evidence(exhausted, settings=s) == ROUTE_DEGRADE


def test_reducers_are_last_write_wins_and_full_replace() -> None:
    assert latest_list(["company"], ["industry"]) == ["industry"]
    assert latest_list(["company"], None) == ["company"]
    assert latest_list(["company"], []) == []
    assert replace_mapping({"old": 1}, {"new": 2}) == {"new": 2}
    assert replace_mapping({"old": 1}, {}) == {}
    assert replace_mapping({"old": 1}, None) == {"old": 1}


def test_curate_drops_reference_when_new_version_falls_below_threshold() -> None:
    """走真实链路：同 URL 新版本经 merge_docs 覆盖 → curate 重判 → replace_mapping 移除。

    只在这个范围内 `replace_mapping` 确实能移除旧引用；不夸大成「所有旧引用都能移除」。
    """
    from graph.nodes.collect import make_curate_node

    s = get_settings()
    curate = make_curate_node(s)
    url = "https://example.org/a"
    good = {"url": url, "title": "A", "score": 0.9, "content": "x"}
    stale = {**good, "score": 0.1}  # 同一来源的新版本被判定低相关

    first = asyncio.run(curate({**initial_state("X"), "company_data": {url: good}}))
    assert url in first["references"]

    merged_data = merge_docs({url: good}, {url: stale})
    second = asyncio.run(curate({**initial_state("X"), "company_data": merged_data}))
    final = replace_mapping(first["references"], second["references"])
    assert url not in final, "同一 URL 的新版本不合格时，旧引用必须被移除"


def test_url_that_stops_being_returned_is_retained_as_known_limitation() -> None:
    """如实记录边界，不假装修复：`*_data` 按 URL 累积，URL 不再返回时旧引用移除不掉。

    要让这类旧引用消失，需要按栏目维护「本轮有效 URL 集合」，真实检索接入后才有
    意义（挂 S5/S7）。文档措辞因此不得写「旧引用自动移除」。
    """
    from graph.nodes.collect import make_curate_node

    s = get_settings()
    curate = make_curate_node(s)
    old_url = "https://example.org/old"
    new_url = "https://example.org/new"
    doc = lambda u: {"url": u, "title": u, "score": 0.9, "content": "x"}  # noqa: E731

    first = asyncio.run(curate({**initial_state("X"), "company_data": {old_url: doc(old_url)}}))
    merged_data = merge_docs({old_url: doc(old_url)}, {new_url: doc(new_url)})
    second = asyncio.run(curate({**initial_state("X"), "company_data": merged_data}))
    final = replace_mapping(first["references"], second["references"])
    assert old_url in final, "当前实现确实保留不再返回的旧 URL；这是已知边界，改实现时此断言应随之更新"


def test_degrade_switch_removed_from_config() -> None:
    assert "enabled" not in get_settings().graph.degrade.model_dump(), "降级不可关闭是红线"


def test_analyst_uses_its_own_retry_round_when_sections_are_out_of_sync(tmp_path: Path) -> None:
    """S4 复查回归：不能用全局 max 当轮次（会让刚开始回退的栏目错拿别的栏目数据）。

    端到端跑主图（真 compile + checkpointer + Send 派发）：
    company 已用尽 2 次额度、industry 才第 1 次，白名单只派发 industry，
    它请求 fixture/live 的 round_no 必须是 1 而不是 2。
    """
    captured: list[tuple[str, int]] = []

    @tool
    async def fetch_company_documents(
        company: str, sections: list[str], round_no: int
    ) -> dict[str, list[dict[str, Any]]]:
        """记录每个 analyst 实际请求的轮次，不返回文档。"""
        captured.append((sections[0], round_no))
        return {sections[0]: []}

    base = get_settings()
    # 关掉自纠正，让主图在第一轮 evidence_check 后直接 degrade，不会再回到 research
    settings = base.model_copy(
        update={"features": base.features.model_copy(update={"self_correction": False})}
    )
    start = {
        **initial_state("X"),
        "retry_count": {"company": 2, "industry": 1},
        "sections_to_research": ["industry"],
    }

    async def run() -> None:
        async with CheckpointSession(settings=settings, path=tmp_path / "round.db") as sess:
            graph = sess.compile(build_graph(settings, fetch_company_documents))
            await graph.ainvoke(start, config=sess.config_for("s4:round:1"))

    asyncio.run(run())
    assert captured == [("industry", 1)], (
        "白名单只派发 industry，它自己的 retry_count=1；不能用 company 的 2"
    )


def test_send_branches_overlap_in_time() -> None:
    """证明 4 路 Send 是真并发，不是顺序循环。

    用「所有分支都已开始、才允许第一个分支结束」的时间窗重叠断言，不依赖绝对
    耗时，避免不同机器/CI 负载下的时序抖动。串行执行时该断言必然失败。
    """
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

    sub = build_research_subgraph(get_settings(), slow_fetch)
    asyncio.run(
        sub.ainvoke({"company": "X", "sections_to_research": [], "retry_count": {}})
    )
    assert {s for s, _, _ in spans} == set(get_settings().graph.sections)
    assert max(start for _, start, _ in spans) < min(end for _, _, end in spans), (
        "4 个分支时间窗必须重叠；若串行执行，最后一个开始时会晚于第一个结束"
    )
