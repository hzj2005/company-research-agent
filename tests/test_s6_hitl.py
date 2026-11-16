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
    assert len(state["report"]) == 772
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
    assert len(state["report"]) == 772


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
    assert len(state["report"]) == 779
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
    assert "## 新闻动态\n\n- " + ABSTAIN in report
    assert len(report) != 772, "人工决定必须真能改变报告，而不是只留条日志"
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
    assert len(state["report"]) == 772
    assert attempts == []
    assert socket.socket.connect is original


def test_api_review_end_to_end(tmp_path: Path, monkeypatch) -> None:
    """API 级 HITL 闭环：POST /research 停在 waiting_review，POST /review 续跑成稿。

    这是 S13 接通前端的后端护栏——之前开开关从前端发起会直接 failed（缺 resume 接口），
    这条用例钉死「能暂停、能提交决定、能落库」三段都不再退化。
    """
    import time

    from fastapi.testclient import TestClient

    import application
    from backend.classes.state import job_status

    review_settings = _review_settings()

    # 两个进程内入口（research 后台任务 / review 续跑）必须读同一份 HITL 配置、
    # 落同一个临时 checkpoint，否则续跑拿不到存档。
    monkeypatch.setattr(application, "get_settings", lambda: review_settings)
    monkeypatch.setattr(application, "review_db_path", str(tmp_path / "api.db"))

    original = application.process_research
    async def _with_temp_db(job_id: str, data: object, **kw: object) -> None:
        await original(job_id, data, db_path=tmp_path / "api.db", **kw)

    monkeypatch.setattr(application, "process_research", _with_temp_db)

    with TestClient(application.app) as client:
        resp = client.post("/research", json={"company": "Notion"})
        assert resp.status_code == 200, resp.text
        jid = resp.json()["job_id"]

        # 等它停在人工复核，而不是一路跑完或失败
        state: dict = {}
        for _ in range(80):
            state = dict(job_status.get(jid, {}))
            if state.get("status") in ("waiting_review", "completed", "failed"):
                break
            time.sleep(0.1)
        assert state.get("status") == "waiting_review", state
        assert state.get("current_step") == "human_review"
        assert state.get("review_payload", {}).get("company") == "Notion"
        assert not state.get("report"), "中断时绝不能已经成稿"

        # 提交批准决定 → 续跑成稿
        resp = client.post(
            f"/research/{jid}/review",
            json={"approved": True, "rejected_sections": [], "note": "通过"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "completed"

        final = dict(job_status.get(jid, {}))
        assert final["status"] == "completed"
        assert len(final["report"]) == 772, "批准后报告应与默认一致"


def test_api_review_rejects_on_bad_state(tmp_path: Path, monkeypatch) -> None:
    """review 接口对「已完成 / 不存在的任务」必须明确拒绝，不能静默续跑。"""
    from fastapi.testclient import TestClient

    import application
    from backend.classes.state import job_status

    monkeypatch.setattr(application, "get_settings", lambda: _review_settings())

    with TestClient(application.app) as client:
        # 不存在的任务 → 404
        assert client.post("/research/nope/review", json={"approved": True}).status_code == 404

        # 已完成的任务 → 409（不是 waiting_review，不能重复提交）
        job_status["done-job"] = {
            "status": "completed", "company": "Notion", "thread_id": "tid",
        }
        assert client.post(
            "/research/done-job/review", json={"approved": True}
        ).status_code == 409

        # 还在跑（processing）的任务 → 409，还没到复核点
        job_status["busy-job"] = {
            "status": "processing", "company": "Notion", "thread_id": "tid",
        }
        assert client.post(
            "/research/busy-job/review", json={"approved": True}
        ).status_code == 409
