"""S3 验收：条件边、有上限回退、降级拒答，全部在 fixture 模式真实跑图。

覆盖 ACTION_PLAN S3 的三条验收标准：
- sufficient 一轮通过
- sparse 触发回退并在上限内收敛
- empty 重试达限后明确拒答，且不把无关文档编进报告
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from capabilities.retrieval import load_fixture_store, make_document_tool
from config.loader import Settings, get_settings
from graph.builder import build_graph
from graph.conditions import ROUTE_DEGRADE, ROUTE_PASS, ROUTE_RETRY, route_after_evidence
from graph.run import run_research
from graph.state import initial_state
from persistence.checkpointer import CheckpointSession


def _run_case(
    case: str, tmp_path: Path, settings: Settings | None = None
) -> tuple[str, dict[str, Any], list[str]]:
    s = settings or get_settings()
    company = load_fixture_store(s).case_by_key(case)["company"]
    state, trace = asyncio.run(
        run_research(company, s, tmp_path / f"{case}.db", collect_trace=True)
    )
    return company, state, trace


def test_sufficient_passes_first_round(tmp_path: Path) -> None:
    _, state, trace = _run_case("sufficient", tmp_path)
    assert set(state["evidence_verdict"].values()) == {"sufficient"}
    assert state["retry_count"] == {}, "充足样本不应触发任何回退"
    assert state["degraded"] is False
    assert trace.count("research") == 1
    assert "rewrite_query" not in trace and "degrade" not in trace
    assert "该类信息未找到公开依据" not in state["report"]
    assert "[1]" in state["report"], "应生成行内引用"
    assert state["references"], "行内引用与 References 必须同源"


def test_sparse_retries_once_then_converges(tmp_path: Path) -> None:
    _, state, trace = _run_case("sparse", tmp_path)
    assert state["retry_count"].get("company") == 1
    assert state["evidence_verdict"]["company"] == "sufficient"
    assert state["degraded"] is False
    assert trace.count("research") == 2, "首轮 + 一次回退"
    assert "https://example.org/linear/about" in state["report"], "回退补回的文档应进报告"
    # 回退只重搜不足栏目，其余栏目状态不能被覆盖
    # 重建版：orchestrator 节点写派发决策，字段 dispatch_to
    notes = [n for n in state["review_notes"] if n["node"] == "orchestrator"]
    assert any(n["dispatch_to"] == ["company"] for n in notes), "回退应精确指向不足栏目"


def test_empty_degrades_after_max_retry_without_fabrication(tmp_path: Path) -> None:
    s = get_settings()
    _, state, trace = _run_case("empty", tmp_path, s)
    assert state["degraded"] is True
    assert "company" in state["degraded_sections"]
    assert state["evidence_verdict"]["company"] == "degraded"
    assert state["retry_count"]["company"] == s.graph.max_retry
    assert trace.count("research") == s.graph.max_retry + 1, "循环必须在上限内收敛"
    assert s.graph.degrade.message in state["report"]
    assert "low-relevance" not in state["report"], "低分无关文档不得被写进报告"
    # 其他栏目仍正常输出，验证降级是栏目级的而非整篇拒答
    assert "行业概览" in state["report"] or "该领域缺少公开规模数据" in state["report"]


def test_self_correction_switch_off_skips_retry(tmp_path: Path) -> None:
    s = get_settings().model_copy(deep=True)
    s.features.self_correction = False
    _, state, trace = _run_case("sparse", tmp_path, s)
    assert trace.count("research") == 1, "关闭自纠正后不得回退"
    assert state["degraded"] is True
    assert s.graph.degrade.message in state["report"]


def test_route_is_pure_and_covers_all_branches() -> None:
    s = get_settings()
    base = initial_state("Notion")

    assert route_after_evidence(
        {**base, "evidence_verdict": {"company": "sufficient"}}, settings=s
    ) == ROUTE_PASS

    retry_state = {
        **base,
        "evidence_verdict": {"company": "insufficient"},
        "retry_count": {"company": 0},
    }
    assert route_after_evidence(retry_state, settings=s) == ROUTE_RETRY
    assert retry_state["retry_count"] == {"company": 0}, "条件函数不得有副作用"

    assert route_after_evidence(
        {
            **base,
            "evidence_verdict": {"company": "insufficient"},
            "retry_count": {"company": s.graph.max_retry},
        },
        settings=s,
    ) == ROUTE_DEGRADE


def test_compiled_graph_has_conditional_edges(tmp_path: Path) -> None:
    """证明不是直线 DAG：条件边真实存在于编译后的图对象。"""
    s = get_settings()

    async def inspect_edges() -> list[tuple[str, Any]]:
        async with CheckpointSession(settings=s, path=tmp_path / "edges.db") as session:
            compiled = session.compile(build_graph(s, make_document_tool(s)))
            return [
                (getattr(e, "source", "?"), bool(getattr(e, "conditional", False)))
                for e in compiled.get_graph().edges
            ]

    edges = asyncio.run(inspect_edges())
    conditional_sources = {src for src, cond in edges if cond}
    assert "evidence_check" in conditional_sources, "evidence_check 必须挂条件边"
    assert len([1 for _, cond in edges if cond]) >= 3, "应有 pass/retry/degrade 三条分支"

def test_every_node_is_exercised_by_acceptance_cases(tmp_path: Path) -> None:
    """AGENT.md 第 6.10 条：每个节点、每条条件边都要有用例覆盖。

    S3 用三条端到端用例覆盖全部 7 个节点与 pass/retry/degrade 三条分支；
    S4 拆成并行子图后再拆成节点级独立用例文件。
    """
    executed: set[str] = set()
    for case in ("sufficient", "sparse", "empty"):
        _, _, trace = _run_case(case, tmp_path)
        executed.update(trace)
    assert {
        "grounding", "research", "curate", "evidence_check",
        "rewrite_query", "degrade", "briefing",
    } <= executed
