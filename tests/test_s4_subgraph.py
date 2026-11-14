"""S4 验收：并行子图、Send 精确派发、栏目级重试、引用全量重算。

覆盖 ACTION_PLAN 第 7.4 节：4 路 Send 并行、reducer 合并不覆盖、回退只派发
不足栏目、部分栏目用尽额度不连累其他栏目、旧引用可被移除、降级不可关闭。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

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
from graph.state import initial_state, latest_list, replace_mapping
from graph.subgraphs.research import build_research_subgraph, fanout_dispatch


def _run(company: str, tmp_path: Path) -> tuple[dict[str, Any], list[str]]:
    return asyncio.run(
        run_research(company, get_settings(), tmp_path / f"{company}.db", collect_trace=True)
    )


def _analyst_notes(state: dict[str, Any]) -> list[dict[str, Any]]:
    return [n for n in state["review_notes"] if n["node"] == "research"]


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


def test_curate_recomputes_references_so_stale_urls_disappear() -> None:
    from graph.nodes.collect import make_curate_node

    s = get_settings()
    curate = make_curate_node(s)
    url = "https://example.org/a"
    doc = {"url": url, "title": "A", "score": 0.9, "content": "x", "section": "company"}
    first = asyncio.run(curate({**initial_state("X"), "company_data": {url: doc}}))
    assert url in first["references"]
    second = asyncio.run(curate(initial_state("X")))
    merged = replace_mapping(first["references"], second["references"])
    assert merged == {}, "旧引用必须能被移除，不能靠 merge_docs 无限累积"


def test_degrade_switch_removed_from_config() -> None:
    assert "enabled" not in get_settings().graph.degrade.model_dump(), "降级不可关闭是红线"
