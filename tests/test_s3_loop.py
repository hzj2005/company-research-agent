"""S3 验收（R3 迁移版）：有上限回退、降级拒答，在 fixture 模式真实跑图。

R3 后回退闭环下沉进各 Agent 子图（pipeline 内部 attempt 循环），主图只有
grounding → research → briefing。本测试验证三种 case 的**行为**仍成立：
- sufficient 一轮通过
- sparse 子图内回退一次并收敛（retry_count 传出）
- empty 重试达限后明确拒答，且不把无关低分文档编进报告
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from capabilities.retrieval import load_fixture_store
from config.loader import Settings, get_settings
from graph.run import run_research


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
    # 新架构无 evidence_verdict；用 retry_count 与段落 status 判定
    assert state["retry_count"] == {}, "充足样本不应触发任何回退"
    assert all(
        state[f"{k}_paragraph"]["status"] == "ok"
        for k in ("company", "industry", "financial", "news")
    )
    assert state["degraded_sections"] == []
    assert trace.count("research") == 1
    assert "rewrite_query" not in trace and "degrade" not in trace
    assert "该类信息未找到公开依据" not in state["report"]
    assert "[1]" in state["report"], "应生成行内引用"
    assert state["briefings"], "拼装器应产出 briefings"


def test_sparse_retries_once_then_converges(tmp_path: Path) -> None:
    _, state, trace = _run_case("sparse", tmp_path)
    assert state["retry_count"].get("company") == 1, "子图内应返工一次"
    assert state["company_paragraph"]["status"] == "ok"
    assert state["degraded_sections"] == []
    assert trace.count("research") == 1, "回退在子图内，主图 research 仍一次"
    assert "https://example.org/linear/about" in state["report"], "回退补回的证据应进报告"
    # 首轮证据也保留（累积）
    assert "项目管理工具" in state["report"]


def test_empty_degrades_after_max_retry_without_fabrication(tmp_path: Path) -> None:
    s = get_settings()
    _, state, trace = _run_case("empty", tmp_path, s)
    assert "company" in state["degraded_sections"]
    assert state["company_paragraph"]["status"] == "degraded"
    assert state["retry_count"]["company"] == s.graph.max_retry, "子图内重试达上限"
    assert trace.count("research") == 1
    assert s.graph.degrade.message in state["report"]
    assert "low-relevance" not in state["report"], "低分无关文档不得被写进报告"
    # 其它栏目正常输出，降级是栏目级的
    assert "该领域缺少公开规模数据" in state["report"]


def test_self_correction_switch_off_skips_retry(tmp_path: Path) -> None:
    s = get_settings().model_copy(deep=True)
    s.features.self_correction = False
    _, state, trace = _run_case("sparse", tmp_path, s)
    # 关闭自纠正：pipeline 不返工（max_retry 视为 0）
    assert state["retry_count"].get("company", 0) == 0
    assert "company" in state["degraded_sections"], "证据不足且不允许返工 → 降级拒答"
    assert s.graph.degrade.message in state["report"]


def test_subgraph_self_loop_is_not_linear_dag(tmp_path: Path) -> None:
    """证明回退闭环真实存在：sparse case 的 pipeline 留痕有 attempt 0 和 1。"""
    _, state, _ = _run_case("sparse", tmp_path)
    evidence_notes = [
        n for n in state["review_notes"]
        if n.get("node") == "evidence" and n.get("section") == "company"
    ]
    assert {n["attempt"] for n in evidence_notes} == {0}, "只有首次判定为不足"
    pipeline_notes = [
        n for n in state["review_notes"]
        if n.get("node") == "pipeline" and n.get("section") == "company"
    ]
    assert pipeline_notes and pipeline_notes[0]["facts"] >= 2, "返工后证据充足"


def test_every_case_exercises_main_graph_nodes(tmp_path: Path) -> None:
    """主图 5 节点：grounding / research / briefing 均被覆盖。"""
    executed: set[str] = set()
    for case in ("sufficient", "sparse", "empty"):
        _, _, trace = _run_case(case, tmp_path)
        executed.update(trace)
    assert {"grounding", "research", "briefing"} <= executed
