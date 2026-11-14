"""S6 HITL 验收：图内 `interrupt()` + 跨 session `Command(resume=...)`。

全程 fixture、0 次真实 Tavily / 模型调用。两次 `run_research` 各自新建
`CheckpointSession`，等价于「关掉进程再重开」，验证 S2 的持久化不是摆设。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from capabilities.retrieval import make_document_tool
from config.loader import apply_overrides, get_settings
from graph.builder import build_graph
from graph.run import run_research

BASE_NODES = {
    "grounding", "research", "curate", "evidence_check",
    "rewrite_query", "degrade", "briefing",
}
ABSTAIN = "该类信息未找到公开依据"


def _review_settings(**extra: object):
    return apply_overrides(
        get_settings(),
        {"features.human_review": True, "features.auto_approve_review": False, **extra},
    )


def _start(company: str, db: Path):
    return asyncio.run(
        run_research(company, _review_settings(), db, collect_trace=True)
    )


def _resume(company: str, db: Path, decision: object):
    return asyncio.run(
        run_research(company, _review_settings(), db, collect_trace=True, resume=decision)
    )


def test_default_graph_has_no_review_node_and_report_is_unchanged(tmp_path: Path) -> None:
    """开关默认关：主图严格 7 节点，报告与 S5 逐字一致（`test_s4_subgraph.py:97` 依赖）。"""
    s = get_settings()
    assert s.features.human_review is False
    assert set(build_graph(s, make_document_tool(s)).nodes.keys()) == BASE_NODES

    state, _ = asyncio.run(run_research("Notion", s, tmp_path / "default.db"))
    assert len(state["report"]) == 822
    assert "_interrupt" not in state
    assert state["review_decision"] == {}


def test_switch_on_adds_node_but_auto_approve_never_interrupts(tmp_path: Path) -> None:
    s = apply_overrides(
        get_settings(),
        {"features.human_review": True, "features.auto_approve_review": True},
    )
    assert "human_review" in build_graph(s, make_document_tool(s)).nodes
    state, trace = asyncio.run(
        run_research("Notion", s, tmp_path / "auto.db", collect_trace=True)
    )
    assert "_interrupt" not in state
    assert state["review_decision"]["note"] == "auto_approved"
    assert "human_review" in trace
    assert len(state["report"]) == 822


def test_real_interrupt_pauses_before_briefing(tmp_path: Path) -> None:
    db = tmp_path / "review.db"
    state, trace = _start("Notion", db)

    assert "_interrupt" in state, "auto_approve=false 时必须真的暂停"
    payload = state["_interrupt"]["payload"]
    assert payload["company"] == "Notion"
    assert payload["sections"] == ["company", "industry", "financial", "news"]
    assert "decision_schema" in payload
    assert state["_interrupt"]["thread_id"]
    assert state["report"] == "", "中断时绝不能已经成稿"
    assert "__interrupt__" in trace
    assert "briefing" not in trace


def test_resume_in_a_new_session_completes_the_report(tmp_path: Path) -> None:
    """两次 run_research = 两个独立 CheckpointSession，等价跨进程恢复。"""
    db = tmp_path / "resume.db"
    _start("Linear", db)
    state, trace = _resume("Linear", db, {"approved": True, "note": "looks good"})

    assert "_interrupt" not in state
    assert len(state["report"]) == 829
    assert state["review_decision"]["approved"] is True
    assert state["review_decision"]["note"] == "looks good"
    assert "human_review" in trace and "briefing" in trace
    # 前半段节点从 checkpoint 恢复，没有重跑
    assert "research" not in trace


def test_reject_sections_changes_only_that_section(tmp_path: Path) -> None:
    db = tmp_path / "partial.db"
    _start("Notion", db)
    state, _ = _resume(
        "Notion", db,
        {"approved": True, "rejected_sections": ["news"], "note": "新闻来源存疑"},
    )
    report = state["report"]
    assert state["degraded"] is True
    assert "news" in state["degraded_sections"]
    assert "company" not in state["degraded_sections"]
    assert ABSTAIN in report
    assert "Notion 产品概览" in report, "未拒答栏目必须照常出稿"
    assert "## News\n\n- " + ABSTAIN in report
    assert len(report) != 822, "人工决定必须真能改变报告，而不是只留条日志"
    assert any(n["node"] == "human_review" and n["status"] == "rejected"
               for n in state["review_notes"])


def test_reject_all_abstains_without_fabrication(tmp_path: Path) -> None:
    db = tmp_path / "reject.db"
    _start("Notion", db)
    state, _ = _resume("Notion", db, {"approved": False, "note": "整体不可用"})
    report = state["report"]

    assert set(state["degraded_sections"]) == {"company", "industry", "financial", "news"}
    assert report.count(ABSTAIN) == 4
    assert "https://" not in report, "全部拒答时 References 必须为空，不能留无引用结论"
    assert "（合成）" not in report, "不得残留任何合成事实"


def test_invalid_resume_value_fails_safe_and_unknown_sections_are_filtered(
    tmp_path: Path,
) -> None:
    db = tmp_path / "invalid.db"
    _start("Notion", db)
    state, _ = _resume("Notion", db, "not-a-dict")
    assert state["review_decision"]["invalid"] is True
    assert state["review_decision"]["approved"] is False
    assert set(state["degraded_sections"]) == {"company", "industry", "financial", "news"}

    db2 = tmp_path / "whitelist.db"
    _start("Notion", db2)
    state2, _ = _resume(
        "Notion", db2,
        {"approved": True, "rejected_sections": ["news", "evil-section", "news"]},
    )
    assert state2["degraded_sections"] == ["news"], "非法栏目必须被白名单过滤且去重"


def test_review_mode_still_makes_zero_external_calls(tmp_path: Path) -> None:
    """S6 不引入任何网络路径：复核 + 恢复全程只碰本地 SQLite 与 mock HTTP。"""
    import socket
    from unittest.mock import patch

    original = socket.socket.connect
    attempts: list[object] = []

    def guarded(self: socket.socket, address: object, *a: object, **kw: object) -> object:
        host = str(address[0]) if isinstance(address, tuple) and address else str(address)
        if host.startswith("127.") or host in ("::1", "localhost"):
            return original(self, address, *a, **kw)
        attempts.append(address)
        raise AssertionError(f"外部连接 {address!r}：S6 应 0 次外部调用")

    db = tmp_path / "offline.db"
    with patch.object(socket.socket, "connect", guarded):
        _start("Notion", db)
        state, _ = _resume("Notion", db, {"approved": True})
    assert len(state["report"]) == 822
    assert attempts == []
    assert socket.socket.connect is original
